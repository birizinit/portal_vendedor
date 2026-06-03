"""Persistência da carteira de clientes e campanhas WhatsApp."""
from __future__ import annotations

import json
from typing import Any, Optional

import db


def _phone_tail(phone: str) -> str:
    d = "".join(c for c in (phone or "") if c.isdigit())
    return d[-8:] if len(d) >= 8 else d


def sync_start(owner_id: int) -> None:
    db.run(
        "INSERT INTO portfolio_sync(owner_id,status,total,synced,message,started_at) "
        "VALUES(?,?,0,0,'Iniciando…',datetime('now')) "
        "ON CONFLICT(owner_id) DO UPDATE SET "
        "status='running',total=0,synced=0,message='Iniciando…',"
        "started_at=datetime('now'),finished_at=NULL",
        (owner_id, "running"),
    )


def sync_progress(owner_id: int, *, total: int, synced: int, message: str = "") -> None:
    db.run(
        "UPDATE portfolio_sync SET total=?, synced=?, message=? WHERE owner_id=?",
        (total, synced, message, owner_id),
    )


def sync_finish(owner_id: int, *, ok: bool, message: str = "") -> None:
    db.run(
        "UPDATE portfolio_sync SET status=?, message=?, finished_at=datetime('now') "
        "WHERE owner_id=?",
        ("done" if ok else "error", message, owner_id),
    )


def sync_status(owner_id: int) -> Optional[dict]:
    r = db.q1("SELECT * FROM portfolio_sync WHERE owner_id=?", (owner_id,))
    return dict(r) if r else None


def replace_contacts(owner_id: int, rows: list[dict]) -> None:
    db.run("DELETE FROM portfolio_contacts WHERE owner_id=?", (owner_id,))
    if not rows:
        return
    seq = []
    for row in rows:
        tags = row.get("tags") or []
        seq.append((
            int(row["contact_id"]),
            owner_id,
            row.get("name") or "",
            row.get("company") or "",
            row.get("phone") or "",
            _phone_tail(row.get("phone") or ""),
            row.get("cnpj") or "",
            row.get("city") or "",
            row.get("segment") or "",
            row.get("client_status") or "",
            row.get("days_without_purchase"),
            row.get("buy_frequency_days"),
            row.get("last_purchase") or "",
            int(row.get("open_quotes") or 0),
            float(row.get("open_quotes_value") or 0),
            json.dumps(tags, ensure_ascii=False),
            row.get("synced_at") or "",
        ))
    db.runmany(
        "INSERT INTO portfolio_contacts("
        "contact_id,owner_id,name,company,phone,phone_tail,cnpj,city,segment,"
        "client_status,days_without_purchase,buy_frequency_days,last_purchase,"
        "open_quotes,open_quotes_value,tags_json,synced_at"
        ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        seq,
    )


def _filter_sql(filter_key: str, min_days: Optional[int], max_days: Optional[int]) -> tuple[str, list]:
    parts = ["owner_id=?"]
    params: list[Any] = []
    if filter_key == "has_phone":
        parts.append("phone_tail IS NOT NULL AND phone_tail != ''")
    elif filter_key == "open_quote":
        parts.append("open_quotes > 0")
    elif filter_key == "inactive_60":
        parts.append("days_without_purchase >= 60")
    elif filter_key == "no_purchase_7":
        parts.append("days_without_purchase >= 7")
    elif filter_key == "no_purchase_15":
        parts.append("days_without_purchase >= 15")
    elif filter_key == "no_purchase_30":
        parts.append("days_without_purchase >= 30")
    elif filter_key == "no_purchase_60":
        parts.append("days_without_purchase >= 60")
    elif filter_key == "blocked":
        parts.append(
            "(LOWER(client_status) LIKE '%inativ%' OR LOWER(client_status) LIKE '%bloque%')"
        )
    if min_days is not None:
        parts.append("days_without_purchase >= ?")
        params.append(int(min_days))
    if max_days is not None:
        parts.append("days_without_purchase <= ?")
        params.append(int(max_days))
    return " AND ".join(parts), params


def list_contacts(
    owner_id: int,
    *,
    q: str = "",
    filter_key: str = "",
    min_days: Optional[int] = None,
    max_days: Optional[int] = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[dict], int]:
    where, extra = _filter_sql(filter_key, min_days, max_days)
    params: list[Any] = [owner_id] + extra
    if q.strip():
        like = f"%{q.strip().lower()}%"
        where += (
            " AND (LOWER(name) LIKE ? OR LOWER(company) LIKE ? "
            "OR phone LIKE ? OR LOWER(cnpj) LIKE ?)"
        )
        params.extend([like, like, like, like])
    total = db.q1(f"SELECT COUNT(*) n FROM portfolio_contacts WHERE {where}", tuple(params))
    n = int(total["n"]) if total else 0
    params.extend([limit, offset])
    rows = db.q(
        f"SELECT * FROM portfolio_contacts WHERE {where} "
        f"ORDER BY (days_without_purchase IS NULL), days_without_purchase DESC, name ASC "
        f"LIMIT ? OFFSET ?",
        tuple(params),
    )
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["tags"] = json.loads(d.pop("tags_json") or "[]")
        except json.JSONDecodeError:
            d["tags"] = []
        else:
            d.pop("tags_json", None)
        out.append(d)
    return out, n


def stats(owner_id: int) -> dict:
    r = db.q1(
        """
        SELECT
          COUNT(*) total,
          SUM(CASE WHEN phone_tail IS NOT NULL AND phone_tail!='' THEN 1 ELSE 0 END) with_phone,
          SUM(CASE WHEN open_quotes>0 THEN 1 ELSE 0 END) open_quote,
          SUM(CASE WHEN days_without_purchase>=7 THEN 1 ELSE 0 END) d7,
          SUM(CASE WHEN days_without_purchase>=15 THEN 1 ELSE 0 END) d15,
          SUM(CASE WHEN days_without_purchase>=30 THEN 1 ELSE 0 END) d30,
          SUM(CASE WHEN days_without_purchase>=60 THEN 1 ELSE 0 END) d60
        FROM portfolio_contacts WHERE owner_id=?
        """,
        (owner_id,),
    )
    if not r:
        return {"total": 0, "with_phone": 0, "open_quote": 0,
                "no_purchase_7": 0, "no_purchase_15": 0,
                "no_purchase_30": 0, "no_purchase_60": 0}
    return {
        "total": r["total"] or 0,
        "with_phone": r["with_phone"] or 0,
        "open_quote": r["open_quote"] or 0,
        "no_purchase_7": r["d7"] or 0,
        "no_purchase_15": r["d15"] or 0,
        "no_purchase_30": r["d30"] or 0,
        "no_purchase_60": r["d60"] or 0,
    }


def create_campaign(
    *,
    owner_id: int,
    user_id: int,
    filter_key: str,
    template_id: str,
    template_body: str,
    items: list[dict],
) -> int:
    cid = db.run(
        "INSERT INTO portfolio_campaigns("
        "owner_id,user_id,filter_key,template_id,template_body,status,total,created_at"
        ") VALUES(?,?,?,?,?,'running',?,datetime('now'))",
        (owner_id, user_id, filter_key, template_id, template_body, len(items)),
    )
    seq = [
        (cid, it["contact_id"], it["phone"], it["name"], it["message"])
        for it in items
    ]
    if seq:
        db.runmany(
            "INSERT INTO portfolio_campaign_items("
            "campaign_id,contact_id,phone,name,message,status"
            ") VALUES(?,?,?,?,?,'pending')",
            seq,
        )
    return int(cid)


def pending_campaign_items(limit: int = 5) -> list[dict]:
    rows = db.q(
        "SELECT i.id, i.campaign_id, i.phone, i.message, i.name, "
        "c.owner_id, c.user_id "
        "FROM portfolio_campaign_items i "
        "JOIN portfolio_campaigns c ON c.id=i.campaign_id "
        "WHERE i.status='pending' AND c.status='running' "
        "ORDER BY i.id LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


def mark_item(item_id: int, status: str, error: str = "") -> None:
    db.run(
        "UPDATE portfolio_campaign_items SET status=?, error=?, "
        "sent_at=CASE WHEN ?='sent' THEN datetime('now') ELSE sent_at END "
        "WHERE id=?",
        (status, error, status, item_id),
    )


def bump_campaign(campaign_id: int, field: str) -> None:
    if field not in ("sent", "failed", "skipped"):
        return
    db.run(f"UPDATE portfolio_campaigns SET {field}={field}+1 WHERE id=?", (campaign_id,))


def finish_campaign_if_done(campaign_id: int) -> None:
    r = db.q1(
        "SELECT total, sent, failed, skipped FROM portfolio_campaigns WHERE id=?",
        (campaign_id,),
    )
    if not r:
        return
    done = (r["sent"] or 0) + (r["failed"] or 0) + (r["skipped"] or 0)
    if done >= (r["total"] or 0):
        db.run(
            "UPDATE portfolio_campaigns SET status='done', finished_at=datetime('now') "
            "WHERE id=?",
            (campaign_id,),
        )


def campaign_get(campaign_id: int, owner_id: int) -> Optional[dict]:
    r = db.q1(
        "SELECT * FROM portfolio_campaigns WHERE id=? AND owner_id=?",
        (campaign_id, owner_id),
    )
    return dict(r) if r else None


def campaigns_list(owner_id: int, limit: int = 20) -> list[dict]:
    rows = db.q(
        "SELECT * FROM portfolio_campaigns WHERE owner_id=? "
        "ORDER BY id DESC LIMIT ?",
        (owner_id, limit),
    )
    return [dict(r) for r in rows]
