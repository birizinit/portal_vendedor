"""API do assistente noturno (piloto)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import db
import repository as repo
from agent_policy import is_night_window
from config import settings
import deps
from access_cache import seller_owns

router = APIRouter(tags=["agent"])


class PilotIn(BaseModel):
    enabled: bool
    note: str = ""


@router.get("/api/admin/agent/status")
async def agent_status(request: Request):
    deps.require_admin(request)
    return {
        "enabled": settings.night_agent_enabled,
        "night_active": is_night_window(),
        "start": settings.night_start,
        "end": settings.night_end,
        "tz": settings.night_tz,
        "max_replies": settings.night_max_replies,
    }


@router.get("/api/admin/agent/pilot")
async def list_pilot(request: Request):
    deps.require_admin(request)
    return {"pilots": db.agent_pilot_list()}


@router.post("/api/admin/agent/pilot/{conv_id}")
async def set_pilot(conv_id: str, request: Request, body: PilotIn):
    u = deps.require_admin(request)
    if body.enabled and not settings.night_agent_enabled:
        raise HTTPException(
            503,
            "Assistente noturno desligado (defina CORTEX_NIGHT_AGENT=1 no .env)",
        )
    db.agent_pilot_set(conv_id, enabled=body.enabled, user_id=int(u["id"]), note=body.note)
    return {"ok": True, "conv_id": conv_id, "enabled": body.enabled}


@router.get("/api/admin/agent/tower")
async def agent_tower(request: Request):
    deps.require_admin(request)
    logs = db.agent_log_recent(100)
    pilots = db.agent_pilot_list()
    return {
        "night_active": is_night_window(),
        "logs": logs,
        "pilots": pilots,
    }


@router.get("/api/conversations/{conv_id}/agent")
async def conv_agent_state(conv_id: str, request: Request):
    deps.user(request)
    p = db.agent_pilot_get(conv_id) or {}
    logs = db.agent_log_for_conv(conv_id, 30)
    sent = sum(1 for x in logs if x.get("action") == "sent")
    return {
        "pilot": p,
        "night_active": is_night_window(),
        "agent_enabled_global": settings.night_agent_enabled,
        "replies_logged": sent,
        "log": logs,
    }


@router.post("/api/conversations/{conv_id}/assume")
async def assume_conversation(conv_id: str, request: Request):
    """Vendedor ou admin para a IA — desliga piloto automático."""
    u = deps.user(request)
    if u.get("role") == "seller":
        if not await seller_owns(u.get("owner_id"), conv_id):
            raise HTTPException(403, "sem acesso a este cliente")
    db.agent_human_owned(conv_id, int(u["id"]))
    repo.invalidate_list_cache()
    return {"ok": True, "human_owned": True}


@router.get("/api/conversations/{conv_id}/agent-log")
async def conv_agent_log(conv_id: str, request: Request):
    deps.user(request)
    return {"log": db.agent_log_for_conv(conv_id, 50)}
