"""Rotas administrativas."""
from __future__ import annotations

import asyncio
import datetime as dt

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import auth
import db
import repository as repo
from config import settings
import deps

router = APIRouter(tags=["admin"])


class NewUser(BaseModel):
    email: str
    name: str
    password: str
    role: str = "seller"
    owner_id: int | None = None


class PwdIn(BaseModel):
    password: str


class ActiveIn(BaseModel):
    active: bool


def _save_msg(d: dict) -> None:
    deps.save_webhook_message(d)


@router.get("/api/admin/users")
async def admin_users(request: Request):
    deps.require_admin(request)
    return auth.list_users()


@router.post("/api/admin/users")
async def admin_create_user(request: Request, payload: NewUser):
    deps.require_admin(request)
    if auth.user_by_email(payload.email):
        raise HTTPException(409, "e-mail já cadastrado")
    uid = auth.create_user(
        payload.email, payload.name, payload.password,
        payload.role, payload.owner_id,
    )
    return {"ok": True, "id": uid}


@router.post("/api/admin/users/{user_id}/password")
async def admin_reset_pwd(request: Request, user_id: int, payload: PwdIn):
    deps.require_admin(request)
    auth.set_password(user_id, payload.password)
    return {"ok": True}


@router.post("/api/admin/users/{user_id}/active")
async def admin_set_active(request: Request, user_id: int, payload: ActiveIn):
    u = deps.require_admin(request)
    if user_id == u.get("id") and not payload.active:
        raise HTTPException(400, "você não pode desativar a si mesmo")
    auth.set_active(user_id, payload.active)
    return {"ok": True}


@router.post("/api/admin/backfill")
async def admin_backfill(request: Request, pages: int = 200):
    deps.require_admin(request)
    if settings.mock or not settings.neppo_enabled:
        raise HTTPException(503, "Neppo não configurado")
    from neppo_client import get_neppo
    cli = get_neppo()

    async def job():
        try:
            n = await cli.backfill(_save_msg, pages=pages)
            db.set_meta("backfill", f"{n} msgs varridas em {dt.datetime.now().isoformat()}")
        except Exception as e:  # noqa: BLE001
            db.set_meta("backfill", f"erro: {e}")

    asyncio.create_task(job())
    return {"ok": True, "started": True, "pages": pages}


@router.get("/api/admin/backfill/status")
async def admin_backfill_status(request: Request):
    deps.require_admin(request)
    return {"total_in_db": db.message_count(), "last": db.get_meta("backfill", "—")}


@router.get("/api/admin/metrics")
async def admin_metrics(request: Request):
    deps.require_admin(request)
    return await repo.admin_metrics()


@router.get("/api/admin/neppo-agents")
async def admin_neppo_agents(request: Request):
    deps.require_admin(request)
    if settings.mock or not settings.ploomes_configured:
        return {"linked": 0, "by_agent": {}, "mock": settings.mock}
    from ploomes_client import ploomes
    if ploomes is None:
        return {"linked": 0, "by_agent": {}}
    return await ploomes.neppo_agent_map()


@router.post("/api/admin/refresh-fields")
async def refresh_fields(request: Request):
    deps.require_admin(request)
    if settings.mock:
        return {"ok": False, "mock": True}
    from ploomes_client import ploomes
    n = await ploomes.refresh_fields()
    return {"ok": True, "fields": n}
