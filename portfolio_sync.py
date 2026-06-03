"""Sincroniza carteira do vendedor (contatos Ploomes → SQLite local)."""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import logging
from typing import Any, Optional

from config import settings
import portfolio_db as pdb
import other_properties as op
from ploomes_mapper import build_tags, strip_emoji, _parse_frequency_days

log = logging.getLogger("cortex.portfolio")

_TERMINAL = {"FATURADO", "ENTREGUE", "CANCELADO", "CONCLUIDO", "CONCLUÍDO", "FINALIZADO"}


def _phone_from_contact(contact: dict) -> str:
    phones = contact.get("Phones") or []
    if phones:
        p = phones[0]
        ph = str(p.get("PhoneNumber") or p.get("Number") or "")
        if ph:
            return ph
    return str(contact.get("Phone") or "")


def _int_or_none(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(float(str(v).replace(",", ".")))
    except (TypeError, ValueError):
        return None


def _quote_open(rec: dict) -> bool:
    props = op.extract(rec)
    status = str(op.get(props, "Status da Nota (Sankhya)", default="") or "")
    if status and status.strip().upper() in _TERMINAL:
        return False
    return True


async def _open_quotes_map(owner_id: int) -> dict[int, dict]:
    """contact_id -> {count, value} para cotações em aberto do vendedor."""
    if settings.mock or not settings.ploomes_configured:
        return {}
    from ploomes_client import ploomes
    if ploomes is None:
        return {}
    out: dict[int, dict] = {}
    skip = 0
    page = 100
    while skip < 2000:
        try:
            data = await ploomes._get("/Quotes", params={
                "$filter": f"OwnerId eq {int(owner_id)}",
                "$orderby": "Date desc",
                "$expand": "OtherProperties",
                "$top": page,
                "$skip": skip,
            })
        except Exception as e:  # noqa: BLE001
            log.warning("quotes sync owner %s: %s", owner_id, e)
            break
        rows = data.get("value") or []
        if not rows:
            break
        for rec in rows:
            if not _quote_open(rec):
                continue
            cid = rec.get("ContactId")
            if not cid:
                continue
            cid = int(cid)
            amt = float(rec.get("Amount") or 0)
            bucket = out.setdefault(cid, {"count": 0, "value": 0.0})
            bucket["count"] += 1
            bucket["value"] += amt
        if len(rows) < page:
            break
        skip += page
    return out


def _row_from_contact(contact: dict, quotes: dict[int, dict], synced_at: str) -> dict:
    props = op.extract(contact) if contact.get("OtherProperties") else {}
    days = _int_or_none(op.get(props, "Dias sem compra"))
    freq = _parse_frequency_days(op.get(props, "Frequência de compra"))
    status = strip_emoji(op.get(props, "Status do Cliente", default=""))
    segment = str(op.get(props, "Perfil Principal (Segmento)", default="") or "")
    amount = float(contact.get("Amount") or 0)
    stage = ""
    tags = build_tags(
        props=props, amount=amount, stage=stage,
        days_in_stage=None, segment=segment,
    )
    cid = int(contact["Id"])
    q = quotes.get(cid) or {}
    city = ""
    city_obj = contact.get("City")
    if isinstance(city_obj, dict):
        city = str(city_obj.get("Name") or "")
    company = ""
    co = contact.get("Company")
    if isinstance(co, dict):
        company = str(co.get("Name") or "")
    return {
        "contact_id": cid,
        "name": strip_emoji(contact.get("Name") or company or "Cliente"),
        "company": strip_emoji(company),
        "phone": _phone_from_contact(contact),
        "cnpj": str(contact.get("Register") or contact.get("CNPJ") or ""),
        "city": city,
        "segment": segment,
        "client_status": status,
        "days_without_purchase": days,
        "buy_frequency_days": freq,
        "last_purchase": str(op.get(props, "Data Última Compra", default="") or ""),
        "open_quotes": q.get("count", 0),
        "open_quotes_value": q.get("value", 0.0),
        "tags": tags,
        "synced_at": synced_at,
    }


async def sync_owner(owner_id: int) -> None:
    synced_at = _dt.datetime.now().isoformat()
    pdb.sync_start(owner_id)
    try:
        if settings.mock:
            rows = _mock_rows(owner_id, synced_at)
            pdb.replace_contacts(owner_id, rows)
            pdb.sync_progress(owner_id, total=len(rows), synced=len(rows),
                              message="Carteira demo carregada")
            pdb.sync_finish(owner_id, ok=True, message=f"{len(rows)} clientes")
            return

        if not settings.ploomes_configured:
            pdb.sync_finish(owner_id, ok=False, message="Ploomes não configurado")
            return

        from ploomes_client import ploomes
        if ploomes is None:
            pdb.sync_finish(owner_id, ok=False, message="Cliente Ploomes indisponível")
            return

        quotes = await _open_quotes_map(owner_id)
        all_rows: list[dict] = []
        skip = 0
        page = int(getattr(settings, "portfolio_sync_page_size", 100) or 100)
        max_pages = int(getattr(settings, "portfolio_sync_max_pages", 80) or 80)

        for page_i in range(max_pages):
            data = await ploomes._get("/Contacts", params={
                "$filter": f"OwnerId eq {int(owner_id)}",
                "$expand": "OtherProperties,Phones,City,Company",
                "$orderby": "Name",
                "$top": page,
                "$skip": skip,
            })
            batch = data.get("value") or []
            if not batch:
                break
            for c in batch:
                all_rows.append(_row_from_contact(c, quotes, synced_at))
            skip += len(batch)
            pdb.sync_progress(
                owner_id, total=skip, synced=skip,
                message=f"Sincronizando… {skip} contatos",
            )
            if len(batch) < page:
                break
            await asyncio.sleep(0.05)

        pdb.replace_contacts(owner_id, all_rows)
        pdb.sync_finish(owner_id, ok=True, message=f"{len(all_rows)} clientes sincronizados")
        log.info("portfolio sync owner %s: %d contacts", owner_id, len(all_rows))
    except Exception as e:  # noqa: BLE001
        log.exception("portfolio sync failed owner %s", owner_id)
        pdb.sync_finish(owner_id, ok=False, message=str(e)[:200])


def _mock_rows(owner_id: int, synced_at: str) -> list[dict]:
    import mock_data
    rows = []
    for i, c in enumerate(mock_data.MOCK_CONVERSATIONS):
        days = [5, 12, 45, 8, 90, 22, 7, 120][i % 8]
        tags = [{"l": f"{days}d sem comprar", "k": "warn" if days >= 30 else "info"}]
        if i % 3 == 0:
            tags.append({"l": "Orçamento aberto", "k": "value"})
        rows.append({
            "contact_id": 1000 + i,
            "name": c.name,
            "company": c.name,
            "phone": c.phone or "",
            "cnpj": c.cnpj or "",
            "city": getattr(c, "city", None) or (c.order.city if c.order else "") or "",
            "segment": c.segment or "",
            "client_status": "Ativo" if days < 60 else "Inativo",
            "days_without_purchase": days,
            "buy_frequency_days": 30,
            "last_purchase": "",
            "open_quotes": 1 if i % 3 == 0 else 0,
            "open_quotes_value": 5000.0 if i % 3 == 0 else 0,
            "tags": tags,
            "synced_at": synced_at,
        })
    return rows


_running: set[int] = set()


def schedule_sync(owner_id: int) -> bool:
    """Dispara sync em background; retorna False se já está rodando."""
    if owner_id in _running:
        return False
    _running.add(owner_id)

    async def _run() -> None:
        try:
            await sync_owner(owner_id)
        finally:
            _running.discard(owner_id)

    asyncio.create_task(_run())
    return True
