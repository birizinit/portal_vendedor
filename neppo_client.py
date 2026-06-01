"""Cliente Neppo — OAuth2 + envio ativo WhatsApp."""
from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from config import settings

SEND_PATH = "/chatapi/1.0/api/direct-message/save"
MESSAGES_PATH = "/chatapi/1.0/api/messages"
from paths import data_dir

_LASTPAGE_FILE = data_dir() / ".neppo_lastpage"


def clean_message_text(raw: Any) -> str:
    """Mensagens interativas do WhatsApp chegam como JSON (botões/listas).
    Extrai o texto legível; senão devolve o texto como veio."""
    if raw in (None, ""):
        return ""
    s = str(raw).strip()
    if s[:1] not in "{[":
        return s
    try:
        obj = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return s
    if isinstance(obj, dict):
        t = obj.get("type")
        if t == "button":
            return (obj.get("body") or {}).get("text") or s
        if t == "button_reply":
            br = obj.get("button_reply") or {}
            return br.get("title") or br.get("text") or br.get("id") or s
        if t in ("list_reply", "interactive"):
            node = obj.get("list_reply") or obj.get("interactive") or {}
            return node.get("title") or node.get("text") or s
        for path in (("body", "text"), ("text",), ("title",), ("caption",)):
            cur = obj
            for k in path:
                cur = cur.get(k) if isinstance(cur, dict) else None
            if cur:
                return str(cur)
    return s


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return ""
    if len(digits) in (10, 11) and not digits.startswith("55"):
        digits = "55" + digits
    return digits


class NeppoClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=25.0)
        self._token: Optional[str] = None
        self._token_expires: float = 0.0
        self._last_page: int = 0
        self._last_page_at: float = 0.0

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _fetch_token(self) -> str:
        creds = f"{settings.neppo_client_key}:{settings.neppo_client_secret}".encode()
        basic = base64.b64encode(creds).decode()
        resp = await self._http.post(
            settings.neppo_auth_url,
            data={
                "grant_type": "password",
                "username": settings.neppo_username,
                "password": settings.neppo_password,
            },
            headers={"Authorization": f"Basic {basic}"},
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires = time.monotonic() + max(60, int(data.get("expires_in", 3600)) - 60)
        return self._token

    async def get_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires:
            return self._token
        return await self._fetch_token()

    async def _api_post(self, path: str, body: dict) -> dict:
        token = await self.get_token()
        url = settings.neppo_base_url.rstrip("/") + path
        resp = await self._http.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()

    async def send_message(self, phone: str, text: str) -> dict:
        """Envio ativo WhatsApp (canal não oficial — texto livre)."""
        phone_number = normalize_phone(phone)
        if not phone_number:
            raise ValueError("telefone inválido para envio Neppo")

        body: dict[str, Any] = {
            "phoneNumber": phone_number,
            "channel": "WHATSAPP",
            "message": text,
            "groupName": settings.neppo_group_name,
            "status": "PROCESSANDO",
            "createdBy": settings.neppo_username,
            "groupConfId": settings.neppo_group_conf_id,
        }
        if settings.neppo_user_id:
            body["userId"] = settings.neppo_user_id

        return await self._api_post(SEND_PATH, body)

    # -- histórico de mensagens WhatsApp ------------------------------------
    # A API /messages não filtra por telefone nem ordena (ignora os params) e
    # devolve tudo paginado por id crescente (cronológico). Para pegar o
    # histórico recente de um cliente: localiza a "cauda" (página mais nova,
    # cacheada) e varre de trás pra frente filtrando por session.user.phone.

    async def _fetch_page(self, page: int, size: int = 100) -> list[dict]:
        token = await self.get_token()
        url = settings.neppo_base_url.rstrip("/") + MESSAGES_PATH
        resp = await self._http.post(
            url, json={"page": page, "size": size},
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
        )
        if resp.status_code >= 400:
            return []
        return resp.json().get("results", []) or []

    @staticmethod
    def _load_estimate() -> int:
        try:
            return int(_LASTPAGE_FILE.read_text().strip())
        except (OSError, ValueError):
            return 0

    @staticmethod
    def _save_estimate(page: int) -> None:
        try:
            _LASTPAGE_FILE.write_text(str(page))
        except OSError:
            pass

    async def _full_search(self, size: int) -> int:
        """Busca exponencial + binária (cara — só no primeiro uso)."""
        lo, hi = 1, 1
        while await self._fetch_page(hi, size):
            lo = hi
            hi *= 2
            if hi > 500_000:
                break
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if await self._fetch_page(mid, size):
                lo = mid
            else:
                hi = mid
        return lo

    async def _find_last_page(self, size: int = 100) -> int:
        """Última página com dados — cacheada em memória (120s) e em disco.

        A cauda cresce devagar (poucas páginas/dia). Partindo da estimativa
        salva, uma varredura linear curta acha o fim em poucas requisições;
        só cai na busca completa quando não há estimativa ou ela está longe.
        """
        if self._last_page and (time.monotonic() - self._last_page_at) < 120:
            return self._last_page

        est = self._last_page or self._load_estimate()
        page = 0
        if est:
            # garante que a estimativa tem dados; se não, recua exponencialmente
            cur = est
            while cur > 1 and not await self._fetch_page(cur, size):
                cur //= 2
            if await self._fetch_page(cur, size):
                # caminha pra frente enquanto a próxima tiver dados (limite curto)
                steps = 0
                while steps < 80 and await self._fetch_page(cur + 1, size):
                    cur += 1
                    steps += 1
                page = cur if steps < 80 else 0   # se estourou, estimativa ruim

        if not page:
            page = await self._full_search(size)

        self._last_page, self._last_page_at = page, time.monotonic()
        self._save_estimate(page)
        return page

    @staticmethod
    def _direction(msg: dict) -> str:
        if (msg.get("sendBy") or "").lower() == "user":
            return "in"
        if str(msg.get("fromUser") or "").startswith("whatsapp_"):
            return "in"
        return "out"

    def _extract(self, m: dict) -> dict:
        """Normaliza uma mensagem crua da Neppo para o formato de armazenamento."""
        user = ((m.get("session") or {}).get("user") or {})
        ct = (m.get("contentType") or "TEXT").upper()
        raw = m.get("message") or ""
        media = raw if (ct in ("IMAGE", "AUDIO", "VIDEO", "APPLICATION")
                        and str(raw).startswith("http")) else ""
        text = clean_message_text(m.get("caption") or raw) if media \
            else clean_message_text(raw or m.get("caption") or "")
        return {
            "id": m.get("id"),
            "phone": normalize_phone(str(user.get("phone") or "")),
            "direction": self._direction(m),
            "text": text, "media_url": media, "content_type": ct,
            "bot": (m.get("sendBy") or "").lower() in ("bot", "system"),
            "name": user.get("displayName") or "",
            "createdAt": m.get("createdAt"),
        }

    async def backfill(self, save_fn, pages: int = 100, size: int = 100) -> int:
        """Varre as últimas `pages` páginas e chama save_fn(msg) por mensagem.
        Usado para popular o banco com o histórico (job de admin)."""
        last = await self._find_last_page(size)
        start = max(1, last - pages + 1)
        saved = 0
        pg = last
        while pg >= start:
            batch = [p for p in range(pg, max(start - 1, pg - 8), -1)]
            results = await asyncio.gather(*(self._fetch_page(p, size) for p in batch))
            for rows in results:
                for m in rows:
                    d = self._extract(m)
                    if d["phone"]:
                        save_fn(d)
                        saved += 1
            pg -= len(batch)
        return saved

    async def message_history(self, phone: str, want: int = 40,
                              max_scan_pages: int = 14, size: int = 100) -> list[dict]:
        """Mensagens recentes de WhatsApp de um telefone (mais antigas -> recentes)."""
        target = normalize_phone(phone)
        if not target:
            return []
        last = await self._find_last_page(size)
        # busca as páginas da cauda EM PARALELO (a API Neppo não tem rate limit
        # próprio aqui) — derruba a varredura de ~5s para ~0.5s
        pages = [p for p in range(last, max(0, last - max_scan_pages), -1) if p >= 1]
        results = await asyncio.gather(*(self._fetch_page(p, size) for p in pages))

        collected: list[dict] = []
        for rows in results:
            for m in rows:
                d = self._extract(m)
                if d["phone"] == target:
                    collected.append(d)
        collected.sort(key=lambda x: x.get("createdAt") or "")
        return collected[-want:]


_client: Optional[NeppoClient] = None


def get_neppo() -> Optional[NeppoClient]:
    global _client
    if not settings.neppo_enabled:
        return None
    if _client is None:
        _client = NeppoClient()
    return _client


def _parse_content(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        return json.loads(raw)
    return {}


def _phone_from_content(content: dict) -> str:
    for key in ("phone", "phoneNumber", "phoneContact"):
        if content.get(key):
            return str(content[key])
    user = content.get("user") or {}
    if isinstance(user, dict):
        if user.get("phone"):
            return str(user["phone"])
        uname = str(user.get("userName") or "")
        m = re.search(r"(\d{10,15})", uname)
        if m:
            return m.group(1)
    return ""


def parse_webhook(payload: dict) -> Optional[dict]:
    """Normaliza webhook Neppo (MESSAGE / SESSION) ou payload simples."""
    try:
        component = payload.get("component")
        if component in ("MESSAGE", "SESSION", "CHAT_API"):
            content = _parse_content(payload.get("content"))
            text = content.get("message") or content.get("text") or content.get("body")
            phone = _phone_from_content(content)
            user = content.get("user") or {}
            if isinstance(user, dict) and user.get("typeUser") in ("AGENT", "BOT"):
                return None
            if text and phone:
                name = ""
                if isinstance(user, dict):
                    name = str(user.get("displayName") or user.get("name") or "")
                return {"phone": phone, "text": str(text), "name": name}

        phone = payload.get("from") or payload.get("phone") or payload.get("phoneNumber")
        text = payload.get("text")
        msg = payload.get("message")
        if not text and isinstance(msg, dict):
            text = msg.get("text")
        elif not text and isinstance(msg, str):
            text = msg
        if phone and text:
            return {
                "phone": str(phone),
                "text": str(text),
                "name": str(payload.get("contactName") or payload.get("name") or ""),
            }
    except (json.JSONDecodeError, AttributeError, TypeError):
        return None
    return None
