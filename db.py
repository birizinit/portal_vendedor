"""Camada de persistência (SQLite — sem dependências externas).

Guarda contas/sessões (auth + papéis), o histórico de WhatsApp (captura via
webhook + envio + backfill) e marcadores de leitura/metas. SQLite local é
suficiente para a escala de uma equipe de vendas e zera dependências.
"""
from __future__ import annotations
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

from paths import data_dir

_DB_PATH = data_dir() / "cortex.db"
_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA busy_timeout=5000")
        _init(_conn)
    return _conn


def _init(c: sqlite3.Connection) -> None:
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            role TEXT NOT NULL DEFAULT 'seller',   -- 'admin' | 'seller'
            owner_id INTEGER,                       -- Id do usuário no Ploomes
            pwd TEXT NOT NULL,                      -- hash pbkdf2
            created TEXT
        );
        CREATE TABLE IF NOT EXISTS sessions(
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            neppo_id INTEGER UNIQUE,
            phone TEXT NOT NULL,
            phone_tail TEXT,                        -- últimos 8 dígitos (p/ casar rápido)
            direction TEXT NOT NULL,                -- 'in' | 'out'
            text TEXT,
            media TEXT,
            ct TEXT DEFAULT 'TEXT',
            bot INTEGER DEFAULT 0,
            name TEXT,
            ts TEXT,                                -- ISO
            agent_id INTEGER                        -- agente Neppo que enviou
        );
        CREATE INDEX IF NOT EXISTS ix_msg_phone ON messages(phone, ts);
        CREATE TABLE IF NOT EXISTS seen(
            user_id INTEGER, conv_id TEXT, sig TEXT,
            PRIMARY KEY(user_id, conv_id)
        );
        CREATE TABLE IF NOT EXISTS goals(
            owner_id INTEGER, period TEXT, target REAL,
            PRIMARY KEY(owner_id, period)
        );
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS feedback(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT, intent_id TEXT, conversation_id TEXT,
            user_id INTEGER, at TEXT
        );
        CREATE TABLE IF NOT EXISTS snooze(
            user_id INTEGER, conv_id TEXT, until TEXT,
            PRIMARY KEY(user_id, conv_id)
        );
        CREATE TABLE IF NOT EXISTS agent_pilot(
            conv_id TEXT PRIMARY KEY,
            enabled INTEGER DEFAULT 0,
            enabled_by INTEGER,
            enabled_at TEXT,
            human_owned INTEGER DEFAULT 0,
            human_owned_by INTEGER,
            human_owned_at TEXT,
            note TEXT,
            intro_sent INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS agent_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conv_id TEXT NOT NULL,
            action TEXT NOT NULL,
            detail TEXT,
            reply_text TEXT,
            at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_agent_log_conv ON agent_log(conv_id, at);
        """
    )
    # migração: coluna 'active' em users (bancos antigos)
    cols = [r["name"] for r in c.execute("PRAGMA table_info(users)").fetchall()]
    if "active" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN active INTEGER DEFAULT 1")
    # migração: coluna 'phone_tail' em messages (bancos antigos) + backfill
    mcols = [r["name"] for r in c.execute("PRAGMA table_info(messages)").fetchall()]
    if "phone_tail" not in mcols:
        c.execute("ALTER TABLE messages ADD COLUMN phone_tail TEXT")
        for r in c.execute("SELECT id, phone FROM messages").fetchall():
            c.execute("UPDATE messages SET phone_tail=? WHERE id=?",
                      (_phone_tail(r["phone"]), r["id"]))
    # migração: id do agente Neppo que enviou a mensagem (p/ atribuir dono)
    if "agent_id" not in mcols:
        c.execute("ALTER TABLE messages ADD COLUMN agent_id INTEGER")
    # índice criado após a migração (coluna garantida em banco novo e antigo)
    c.execute("CREATE INDEX IF NOT EXISTS ix_msg_tail ON messages(phone_tail, ts)")
    c.commit()


def save_feedback(action: str, intent_id: str, conversation_id: str,
                  user_id, at: str) -> None:
    run("INSERT INTO feedback(action,intent_id,conversation_id,user_id,at)"
        " VALUES(?,?,?,?,?)", (action, intent_id, conversation_id, user_id, at))


def feedback_stats() -> list[dict]:
    rows = q("SELECT action, COUNT(*) n FROM feedback GROUP BY action")
    return [dict(r) for r in rows]


def feedback_by_intent() -> dict[str, dict]:
    """Por intenção: quantas vezes a sugestão foi usada/editada/ignorada +
    taxa de aceitação. Base p/ saber quais templates afinar."""
    rows = q("SELECT intent_id, action, COUNT(*) n FROM feedback "
             "WHERE intent_id IS NOT NULL GROUP BY intent_id, action")
    out: dict[str, dict] = {}
    for r in rows:
        d = out.setdefault(r["intent_id"], {"used": 0, "edited": 0, "ignored": 0})
        if r["action"] in d:
            d[r["action"]] = r["n"]
    for d in out.values():
        total = d["used"] + d["edited"] + d["ignored"]
        d["total"] = total
        # aceitação: usar=1, editar=0.5 (aproveitou mas ajustou), ignorar=0
        d["acceptance"] = round((d["used"] + 0.5 * d["edited"]) / total, 2) if total else None
    return out


def q(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        cur = conn().execute(sql, params)
        return cur.fetchall()


def q1(sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    rows = q(sql, params)
    return rows[0] if rows else None


def run(sql: str, params: tuple = ()) -> int:
    with _lock:
        c = conn()
        cur = c.execute(sql, params)
        c.commit()
        return cur.lastrowid


def runmany(sql: str, seq: list[tuple]) -> None:
    with _lock:
        c = conn()
        c.executemany(sql, seq)
        c.commit()


# -- mensagens de WhatsApp ---------------------------------------------------
def save_message(*, phone: str, direction: str, text: str = "", media: str = "",
                 ct: str = "TEXT", bot: bool = False, name: str = "",
                 ts: str = "", neppo_id: Optional[int] = None,
                 agent_id: Optional[int] = None) -> None:
    """Insere uma mensagem (ignora duplicata por neppo_id)."""
    if not phone:
        return
    with _lock:
        c = conn()
        c.execute(
            "INSERT OR IGNORE INTO messages"
            "(neppo_id,phone,phone_tail,direction,text,media,ct,bot,name,ts,agent_id)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (neppo_id, phone, _phone_tail(phone), direction, text, media, ct,
             int(bool(bot)), name, _normalize_ts(ts), agent_id),
        )
        c.commit()


def last_agent_for_phone(phone_digits: str) -> Optional[int]:
    """Id do agente Neppo da mensagem de saída mais recente desse telefone."""
    tail = _phone_tail(phone_digits)
    if not tail:
        return None
    r = q1(
        "SELECT agent_id FROM messages WHERE phone_tail=? AND agent_id IS NOT NULL "
        "ORDER BY ts DESC LIMIT 1",
        (tail,),
    )
    return r["agent_id"] if r and r["agent_id"] is not None else None


def _phone_tail(phone_digits: str) -> str:
    digits = "".join(ch for ch in (phone_digits or "") if ch.isdigit())
    return digits[-8:] if len(digits) >= 8 else digits


def _normalize_ts(ts) -> str:
    """Padroniza o timestamp em ISO 8601 — aceita ISO (com Z/offset) e epoch
    (s ou ms). Sem isso, webhook (isoformat) e backfill (createdAt do Neppo)
    gravam formatos diferentes e a ordenação/MAX(ts) fica errada."""
    s = str(ts or "").strip()
    if not s:
        return ""
    import datetime as _dt
    if s.isdigit():
        try:
            val = int(s)
            if val > 1_000_000_000_000:      # milissegundos
                val //= 1000
            return _dt.datetime.fromtimestamp(val, _dt.timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            return s
    try:
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return s


def messages_for(phone_digits: str, limit: int = 200) -> list[dict]:
    """Histórico de um telefone (casando pelos últimos 8 dígitos, indexado)."""
    tail = _phone_tail(phone_digits)
    if not tail:
        return []
    rows = q(
        "SELECT direction,text,media,ct,bot,ts FROM messages "
        "WHERE phone_tail=? ORDER BY ts ASC LIMIT ?",
        (tail, limit),
    )
    return [dict(r) for r in rows]


def message_count(phone_digits: str = "") -> int:
    if phone_digits:
        r = q1("SELECT COUNT(*) n FROM messages WHERE phone_tail=?",
               (_phone_tail(phone_digits),))
    else:
        r = q1("SELECT COUNT(*) n FROM messages")
    return r["n"] if r else 0


def last_message_for_phone(phone_digits: str) -> Optional[dict]:
    tail = _phone_tail(phone_digits)
    if not tail:
        return None
    r = q1(
        "SELECT direction, text, media, ts FROM messages WHERE phone_tail=? "
        "ORDER BY ts DESC LIMIT 1",
        (tail,),
    )
    return dict(r) if r else None


def full_phone_for_tail(tail: str) -> str:
    """Telefone completo mais recente associado a um tail (p/ leads órfãos)."""
    t = _phone_tail(tail)
    if not t:
        return ""
    r = q1("SELECT phone FROM messages WHERE phone_tail=? ORDER BY ts DESC LIMIT 1", (t,))
    return (r["phone"] if r else "") or ""


def inbox_sig_for_phone(phone_digits: str) -> str:
    last = last_message_for_phone(phone_digits)
    if not last:
        return ""
    d = "in" if last.get("direction") == "in" else "out"
    t = (last.get("text") or "")[:200]
    h = (last.get("ts") or "")[11:16] if last.get("ts") else ""
    return f"{d}|{t}|{h}"


def get_seen_sig(user_id: int, conv_id: str) -> Optional[str]:
    r = q1("SELECT sig FROM seen WHERE user_id=? AND conv_id=?", (user_id, conv_id))
    return r["sig"] if r else None


def seen_map(user_id: int) -> dict[str, str]:
    """Todas as assinaturas 'visto' de um usuário numa consulta só (p/ inbox)."""
    return {r["conv_id"]: r["sig"]
            for r in q("SELECT conv_id, sig FROM seen WHERE user_id=?", (user_id,))}


def latest_per_phone(limit: int = 500) -> list[dict]:
    """Última mensagem por telefone (1 linha por tail) — base p/ leads órfãos."""
    rows = q(
        "SELECT m.phone, m.phone_tail, m.text, m.direction, m.ts, m.name "
        "FROM messages m JOIN ("
        "  SELECT phone_tail, MAX(ts) mts FROM messages "
        "  WHERE phone_tail IS NOT NULL AND phone_tail<>'' GROUP BY phone_tail"
        ") g ON m.phone_tail=g.phone_tail AND m.ts=g.mts "
        "ORDER BY m.ts DESC LIMIT ?",
        (limit,),
    )
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:                       # dedup defensivo em empates de ts
        t = r["phone_tail"]
        if t in seen:
            continue
        seen.add(t)
        out.append(dict(r))
    return out


def set_seen_sig(user_id: int, conv_id: str, sig: str) -> None:
    run(
        "INSERT INTO seen(user_id, conv_id, sig) VALUES(?,?,?) "
        "ON CONFLICT(user_id, conv_id) DO UPDATE SET sig=excluded.sig",
        (user_id, conv_id, sig),
    )


def unread_since_sig(phone_digits: str, sig: str) -> int:
    tail = _phone_tail(phone_digits)
    if not tail:
        return 0
    rows = q(
        "SELECT direction, text, ts FROM messages WHERE phone_tail=? "
        "ORDER BY ts ASC",
        (tail,),
    )
    if not sig:
        last = rows[-1] if rows else None
        return 1 if last and last["direction"] == "in" else 0
    past = False
    n = 0
    for r in rows:
        h = (r["ts"] or "")[11:16] if r["ts"] else ""
        row_sig = f"{r['direction']}|{(r['text'] or '')[:200]}|{h}"
        if not past:
            if row_sig == sig:
                past = True
            continue
        if r["direction"] == "in":
            n += 1
    return n


def is_snoozed(user_id: int, conv_id: str) -> bool:
    r = q1("SELECT until FROM snooze WHERE user_id=? AND conv_id=?", (user_id, conv_id))
    if not r or not r["until"]:
        return False
    try:
        import datetime as _dt
        until = _dt.datetime.fromisoformat(r["until"].replace("Z", "+00:00"))
        now = _dt.datetime.now(_dt.timezone.utc)
        if until.tzinfo is None:
            until = until.replace(tzinfo=_dt.timezone.utc)
        if until > now:
            return True
        run("DELETE FROM snooze WHERE user_id=? AND conv_id=?", (user_id, conv_id))
    except ValueError:
        run("DELETE FROM snooze WHERE user_id=? AND conv_id=?", (user_id, conv_id))
    return False


def snoozed_set(user_id: int) -> set[str]:
    """Conjunto de conv_ids ainda silenciados de um usuário (1 consulta)."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    out: set[str] = set()
    for r in q("SELECT conv_id, until FROM snooze WHERE user_id=?", (user_id,)):
        try:
            until = _dt.datetime.fromisoformat((r["until"] or "").replace("Z", "+00:00"))
            if until.tzinfo is None:
                until = until.replace(tzinfo=_dt.timezone.utc)
            if until > now:
                out.add(r["conv_id"])
        except ValueError:
            pass
    return out


def set_snooze(user_id: int, conv_id: str, until_iso: str) -> None:
    run(
        "INSERT INTO snooze(user_id, conv_id, until) VALUES(?,?,?) "
        "ON CONFLICT(user_id, conv_id) DO UPDATE SET until=excluded.until",
        (user_id, conv_id, until_iso),
    )


def clear_snooze(user_id: int, conv_id: str) -> None:
    run("DELETE FROM snooze WHERE user_id=? AND conv_id=?", (user_id, conv_id))


def get_meta(k: str, default: str = "") -> str:
    r = q1("SELECT v FROM meta WHERE k=?", (k,))
    return r["v"] if r else default


def set_meta(k: str, v: str) -> None:
    run("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


def current_period() -> str:
    import datetime as _dt
    return _dt.datetime.now().strftime("%Y-%m")


def get_goal(owner_id: int, period: str | None = None) -> float | None:
    p = period or current_period()
    r = q1("SELECT target FROM goals WHERE owner_id=? AND period=?", (owner_id, p))
    return float(r["target"]) if r else None


def set_goal(owner_id: int, target: float, period: str | None = None) -> None:
    p = period or current_period()
    run(
        "INSERT INTO goals(owner_id, period, target) VALUES(?,?,?) "
        "ON CONFLICT(owner_id, period) DO UPDATE SET target=excluded.target",
        (owner_id, p, target),
    )


def search_messages(query_text: str, limit: int = 30) -> list[dict]:
    """Busca texto em mensagens WhatsApp locais."""
    needle = f"%{query_text.strip()}%"
    rows = q(
        "SELECT phone, phone_tail, text, direction, ts, name FROM messages "
        "WHERE text LIKE ? ORDER BY ts DESC LIMIT ?",
        (needle, limit),
    )
    return [dict(r) for r in rows]


def feedback_since(iso_from: str, user_id: int | None = None) -> list[dict]:
    if user_id is not None:
        rows = q(
            "SELECT action, intent_id, conversation_id, at FROM feedback "
            "WHERE at>=? AND user_id=? ORDER BY at DESC",
            (iso_from, user_id),
        )
    else:
        rows = q(
            "SELECT action, intent_id, conversation_id, at, user_id FROM feedback "
            "WHERE at>=? ORDER BY at DESC",
            (iso_from,),
        )
    return [dict(r) for r in rows]


# -- assistente noturno (piloto) ---------------------------------------------
def agent_pilot_get(conv_id: str) -> Optional[dict]:
    r = q1("SELECT * FROM agent_pilot WHERE conv_id=?", (conv_id,))
    return dict(r) if r else None


def agent_pilot_set(
    conv_id: str,
    *,
    enabled: bool,
    user_id: int,
    note: str = "",
) -> None:
    import datetime as _dt
    now = _dt.datetime.now().isoformat()
    if enabled:
        run(
            "INSERT INTO agent_pilot(conv_id,enabled,enabled_by,enabled_at,note,"
            "human_owned,intro_sent) VALUES(?,?,?,?,?,0,0) "
            "ON CONFLICT(conv_id) DO UPDATE SET "
            "enabled=1, enabled_by=excluded.enabled_by, enabled_at=excluded.enabled_at, "
            "note=excluded.note, human_owned=0, human_owned_by=NULL, "
            "human_owned_at=NULL, intro_sent=0",
            (conv_id, 1, user_id, now, note),
        )
    else:
        run(
            "INSERT INTO agent_pilot(conv_id,enabled,enabled_by,enabled_at,note) "
            "VALUES(?,?,?,?,?) "
            "ON CONFLICT(conv_id) DO UPDATE SET enabled=0, note=excluded.note",
            (conv_id, 0, user_id, now, note),
        )


def agent_human_owned(conv_id: str, user_id: int) -> None:
    import datetime as _dt
    now = _dt.datetime.now().isoformat()
    run(
        "INSERT INTO agent_pilot(conv_id,enabled,human_owned,human_owned_by,"
        "human_owned_at) VALUES(?,1,1,?,?) "
        "ON CONFLICT(conv_id) DO UPDATE SET human_owned=1, "
        "human_owned_by=excluded.human_owned_by, human_owned_at=excluded.human_owned_at",
        (conv_id, user_id, now),
    )
    run("UPDATE agent_pilot SET enabled=0 WHERE conv_id=?", (conv_id,))


def agent_intro_mark(conv_id: str) -> None:
    run("UPDATE agent_pilot SET intro_sent=1 WHERE conv_id=?", (conv_id,))


def agent_log_append(
    conv_id: str,
    action: str,
    *,
    detail: str = "",
    reply_text: str = "",
) -> int:
    import datetime as _dt
    return run(
        "INSERT INTO agent_log(conv_id,action,detail,reply_text,at) VALUES(?,?,?,?,?)",
        (conv_id, action, detail, reply_text, _dt.datetime.now().isoformat()),
    )


def agent_log_recent(limit: int = 80) -> list[dict]:
    rows = q(
        "SELECT id, conv_id, action, detail, reply_text, at FROM agent_log "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


def agent_log_for_conv(conv_id: str, limit: int = 50) -> list[dict]:
    rows = q(
        "SELECT id, action, detail, reply_text, at FROM agent_log "
        "WHERE conv_id=? ORDER BY id DESC LIMIT ?",
        (conv_id, limit),
    )
    return [dict(r) for r in rows]


def agent_replies_since(conv_id: str, iso_from: str) -> int:
    r = q1(
        "SELECT COUNT(*) n FROM agent_log WHERE conv_id=? AND action='sent' AND at>=?",
        (conv_id, iso_from),
    )
    return int(r["n"]) if r else 0


def agent_last_sent_at(conv_id: str) -> Optional[str]:
    r = q1(
        "SELECT at FROM agent_log WHERE conv_id=? AND action='sent' "
        "ORDER BY id DESC LIMIT 1",
        (conv_id,),
    )
    return r["at"] if r else None


def agent_pilot_list() -> list[dict]:
    rows = q(
        "SELECT conv_id, enabled, enabled_by, enabled_at, human_owned, "
        "human_owned_at, note, intro_sent FROM agent_pilot "
        "WHERE enabled=1 OR human_owned=1 ORDER BY enabled_at DESC"
    )
    return [dict(r) for r in rows]
