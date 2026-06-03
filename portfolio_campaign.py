"""Fila de envio de campanhas WhatsApp da carteira."""
from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import re

from config import settings
import portfolio_db as pdb
import db

log = logging.getLogger("cortex.portfolio.campaign")


def _digits(phone: str) -> str:
    return "".join(c for c in (phone or "") if c.isdigit())


def _in_send_window() -> bool:
    h = _dt.datetime.now().hour
    return settings.portfolio_campaign_hour_start <= h < settings.portfolio_campaign_hour_end


async def _send_one(phone: str, text: str) -> tuple[bool, str]:
    digits = _digits(phone)
    if len(digits) < 10:
        return False, "telefone inválido"
    if settings.mock:
        await asyncio.sleep(0.1)
        db.save_message(
            phone=digits, direction="out", text=text,
            ts=_dt.datetime.now().isoformat(),
        )
        return True, ""
    if not settings.neppo_enabled:
        return False, "Neppo não configurado"
    from neppo_client import get_neppo
    client = get_neppo()
    if client is None:
        return False, "cliente Neppo indisponível"
    try:
        await client.send_message(digits, text)
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:120]
    db.save_message(
        phone=digits, direction="out", text=text,
        ts=_dt.datetime.now().isoformat(),
    )
    return True, ""


async def process_tick() -> None:
    if not _in_send_window():
        return
    items = pdb.pending_campaign_items(limit=3)
    for it in items:
        ok, err = await _send_one(it["phone"], it["message"])
        cid = int(it["campaign_id"])
        iid = int(it["id"])
        if ok:
            pdb.mark_item(iid, "sent")
            pdb.bump_campaign(cid, "sent")
        else:
            pdb.mark_item(iid, "failed", err)
            pdb.bump_campaign(cid, "failed")
        pdb.finish_campaign_if_done(cid)
        await asyncio.sleep(settings.portfolio_campaign_delay_sec)


async def campaign_loop() -> None:
    while True:
        try:
            await process_tick()
        except Exception as e:  # noqa: BLE001
            log.exception("campaign tick: %s", e)
        await asyncio.sleep(5)


def start_campaign_worker() -> None:
    asyncio.create_task(campaign_loop())
