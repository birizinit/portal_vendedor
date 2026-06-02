"""Login, sessão e página de login."""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import auth
import repository as repo
from config import settings
import deps

log = logging.getLogger("cortex")
router = APIRouter(tags=["auth"])

_login_fails: dict[str, list] = {}


class LoginIn(BaseModel):
    email: str
    password: str


class PwdIn(BaseModel):
    password: str


def _throttled(key: str) -> bool:
    now = time.monotonic()
    arr = [t for t in _login_fails.get(key, []) if now - t < 300]
    _login_fails[key] = arr
    return len(arr) >= 8


@router.get("/login")
async def login_page():
    from paths import data_dir
    return FileResponse(str(data_dir() / "static" / "login.html"))


@router.post("/api/login")
async def api_login(payload: LoginIn, request: Request):
    key = (request.client.host if request.client else "?") + "|" + payload.email.lower()
    if _throttled(key):
        raise HTTPException(429, "muitas tentativas — aguarde alguns minutos")
    token = auth.login(payload.email, payload.password)
    if not token:
        _login_fails.setdefault(key, []).append(time.monotonic())
        log.warning("login falhou para %s", payload.email)
        raise HTTPException(401, "e-mail ou senha inválidos")
    _login_fails.pop(key, None)
    asyncio.create_task(repo.warm_ploomes())
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        "cortex_session", token, httponly=True, samesite="lax",
        secure=settings.secure_cookies, max_age=auth.SESSION_DAYS * 86400,
    )
    return resp


@router.post("/api/logout")
async def api_logout(request: Request):
    auth.logout(request.cookies.get("cortex_session"))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("cortex_session")
    return resp


@router.get("/api/me")
async def api_me(request: Request):
    u = deps.user(request)
    return {
        "name": u.get("name"), "email": u.get("email"),
        "role": u.get("role"), "owner_id": u.get("owner_id"),
    }


@router.post("/api/password")
async def change_my_password(request: Request, payload: PwdIn):
    u = deps.user(request)
    auth.set_password(u["id"], payload.password)
    return {"ok": True}
