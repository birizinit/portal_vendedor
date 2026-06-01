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
            direction TEXT NOT NULL,                -- 'in' | 'out'
            text TEXT,
            media TEXT,
            ct TEXT DEFAULT 'TEXT',
            bot INTEGER DEFAULT 0,
            name TEXT,
            ts TEXT                                 -- ISO
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
        """
    )
    # migração: coluna 'active' em users (bancos antigos)
    cols = [r["name"] for r in c.execute("PRAGMA table_info(users)").fetchall()]
    if "active" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN active INTEGER DEFAULT 1")
    c.commit()


def save_feedback(action: str, intent_id: str, conversation_id: str,
                  user_id, at: str) -> None:
    run("INSERT INTO feedback(action,intent_id,conversation_id,user_id,at)"
        " VALUES(?,?,?,?,?)", (action, intent_id, conversation_id, user_id, at))


def feedback_stats() -> list[dict]:
    rows = q("SELECT action, COUNT(*) n FROM feedback GROUP BY action")
    return [dict(r) for r in rows]


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
                 ts: str = "", neppo_id: Optional[int] = None) -> None:
    """Insere uma mensagem (ignora duplicata por neppo_id)."""
    if not phone:
        return
    with _lock:
        c = conn()
        c.execute(
            "INSERT OR IGNORE INTO messages(neppo_id,phone,direction,text,media,ct,bot,name,ts)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (neppo_id, phone, direction, text, media, ct, int(bool(bot)), name, ts),
        )
        c.commit()


def messages_for(phone_digits: str, limit: int = 200) -> list[dict]:
    """Histórico de um telefone (casando pelos últimos 8+ dígitos)."""
    digits = "".join(ch for ch in (phone_digits or "") if ch.isdigit())
    if not digits:
        return []
    tail = digits[-8:]
    rows = q(
        "SELECT direction,text,media,ct,bot,ts FROM messages "
        "WHERE replace(replace(replace(phone,'(',''),')',''),'-','') LIKE ? "
        "ORDER BY ts ASC LIMIT ?",
        (f"%{tail}%", limit),
    )
    return [dict(r) for r in rows]


def message_count(phone_digits: str = "") -> int:
    if phone_digits:
        digits = "".join(ch for ch in phone_digits if ch.isdigit())[-8:]
        r = q1("SELECT COUNT(*) n FROM messages WHERE phone LIKE ?", (f"%{digits}%",))
    else:
        r = q1("SELECT COUNT(*) n FROM messages")
    return r["n"] if r else 0


def _phone_tail(phone_digits: str) -> str:
    digits = "".join(ch for ch in (phone_digits or "") if ch.isdigit())
    return digits[-8:] if len(digits) >= 8 else digits


_PHONE_MATCH = (
    "replace(replace(replace(replace(phone,'(',''),')',''),'-',''),' ','') LIKE ?"
)


def last_message_for_phone(phone_digits: str) -> Optional[dict]:
    tail = _phone_tail(phone_digits)
    if not tail:
        return None
    r = q1(
        f"SELECT direction, text, media, ts FROM messages WHERE {_PHONE_MATCH} "
        "ORDER BY ts DESC LIMIT 1",
        (f"%{tail}%",),
    )
    return dict(r) if r else None


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
        f"SELECT direction, text, ts FROM messages WHERE {_phone_like(tail)} "
        "ORDER BY ts ASC",
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
