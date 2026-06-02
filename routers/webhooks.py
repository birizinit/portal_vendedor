"""Webhooks Neppo e Ploomes."""
from __future__ import annotations

import datetime as dt
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

import db
import repository as repo
from config import settings
import deps

log = logging.getLogger("cortex")
router = APIRouter(tags=["webhooks"])


def _valid_webhook(request: Request) -> bool:
    if settings.webhook_protected:
        key = request.query_params.get("key") or request.headers.get("X-Webhook-Key", "")
        return key == settings.webhook_validation_key
    if settings.mock or settings.webhook_allow_insecure:
        log.warning("webhook sem chave — liberado (mock/insecure, só dev)")
        return True
    log.error("webhook RECUSADO: defina WEBHOOK_VALIDATION_KEY")
    return False


@router.get("/webhooks/neppo")
async def neppo_validate(request: Request):
    challenge = request.query_params.get("hub.challenge")
    return Response(content=challenge or "ok", media_type="text/plain")


@router.post("/webhooks/neppo")
async def neppo_incoming(request: Request):
    if not _valid_webhook(request):
        raise HTTPException(403, "webhook não autorizado")
    from neppo_client import parse_webhook
    payload = await request.json()
    msg = parse_webhook(payload)
    if msg is None:
        return {"ignored": True}
    conv = await repo.append_client_message(
        msg["phone"], msg["text"], msg["name"], deps.now_hm(),
    )
    db.save_message(
        phone=msg["phone"], direction="in", text=msg["text"],
        name=msg.get("name", ""), ts=dt.datetime.now().isoformat(),
        neppo_id=msg.get("id"),
    )
    conv_id = conv.id if conv else None
    if not conv_id:
        from neppo_client import normalize_phone
        tail = normalize_phone(msg["phone"])
        if len(tail) >= 8:
            conv_id = f"wa_{tail[-8:] if len(tail) >= 8 else tail}"
    if conv:
        repo.invalidate_ai_cache(conv.id)
    repo.invalidate_list_cache()
    await deps.publish({
        "type": "message", "phone": msg["phone"],
        "text": msg["text"], "name": msg.get("name", ""),
    })
    if conv_id and settings.night_agent_enabled:
        import asyncio
        from agent_orchestrator import on_client_message
        asyncio.create_task(on_client_message(
            conv_id=conv_id,
            phone=msg["phone"],
            text=msg.get("text") or "",
            client_name=msg.get("name") or "",
        ))
    return {"ok": True}


@router.post("/webhooks/ploomes")
async def ploomes_changed(request: Request):
    if not _valid_webhook(request):
        raise HTTPException(403, "webhook não autorizado")
    payload = await request.json()
    deal_id = payload.get("Id") or payload.get("dealId")
    if deal_id and not settings.mock:
        from ploomes_client import ploomes
        ploomes.invalidate_deal(int(deal_id))
    repo.invalidate_list_cache()
    return {"ok": True}
