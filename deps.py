"""Dependências compartilhadas — auth, SSE, helpers de rota."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import re
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from access_cache import seller_owns
from config import settings
import auth
import db

log = logging.getLogger("cortex")

PUBLIC_PATHS = {
    "/login", "/api/login", "/api/logout", "/logo.png",
    "/favicon.ico", "/api/health",
}
CONV_PATH_RE = re.compile(r"^/api/conversations/([^/]+)")

_subscribers: set[asyncio.Queue] = set()


def subscribers() -> set[asyncio.Queue]:
    return _subscribers


async def publish(event: dict) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except Exception:
            pass


def user(request: Request) -> dict:
    return getattr(request.state, "user", {}) or {}


def require_admin(request: Request) -> dict:
    u = user(request)
    if u.get("role") != "admin":
        raise HTTPException(403, "acesso restrito ao administrador")
    return u


async def enforce_owns(request: Request, conv_id) -> None:
    u = user(request)
    if u.get("role") == "seller" and not await seller_owns(u.get("owner_id"), str(conv_id)):
        raise HTTPException(403, "sem acesso a este cliente")


async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith("/webhooks/"):
        return await call_next(request)
    sess = auth.user_for_token(request.cookies.get("cortex_session"))
    if sess is None:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "não autenticado"}, status_code=401)
        return RedirectResponse("/login")
    request.state.user = sess
    if sess.get("role") == "seller":
        m = CONV_PATH_RE.match(path)
        if m and not await seller_owns(sess.get("owner_id"), m.group(1)):
            return JSONResponse({"detail": "sem acesso a este cliente"}, status_code=403)
    return await call_next(request)


def save_webhook_message(d: dict) -> None:
    db.save_message(
        neppo_id=d.get("id"), phone=d["phone"], direction=d["direction"],
        text=d.get("text", ""), media=d.get("media_url", ""),
        ct=d.get("content_type", "TEXT"), bot=d.get("bot"),
        name=d.get("name", ""), ts=str(d.get("createdAt") or ""),
        agent_id=d.get("agent_id"),
    )


def now_hm() -> str:
    return dt.datetime.now().strftime("%H:%M")
