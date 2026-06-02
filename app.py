"""Cortex · API (FastAPI).

Sobe com:   uvicorn app:app --reload
Sem credenciais, roda em modo mock. Coloque o painel-vendas.html na pasta
./static que ele é servido em http://localhost:8000/

Endpoints:
  GET  /api/conversations?mode=smart&q=...     -> lista (formato do front)
  GET  /api/conversations/{id}                 -> uma conversa
  GET  /api/conversations/{id}/suggestion      -> sugestão por regras
  POST /api/send            {conversation_id, text}
  POST /api/feedback        {action, intent_id, conversation_id}  (Camada 4)
  GET  /webhooks/neppo      validação do webhook (hub.challenge)
  POST /webhooks/neppo      mensagem recebida do cliente
  POST /webhooks/ploomes    negócio atualizado -> invalida cache
"""
from __future__ import annotations
import asyncio
import datetime as dt
import json
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (JSONResponse, StreamingResponse, RedirectResponse,
                               FileResponse)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import settings
from models import front_conversation, front_suggestion
from suggestion import build_suggestion
from documents import DocRequest, preview as doc_preview, create as doc_create
import repository as repo
import auth
import db

import logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cortex")

app = FastAPI(title="Cortex · Painel de Vendas")
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# cria o admin inicial na primeira execução e registra a senha padrão
_seed_pwd = auth.ensure_admin()
if _seed_pwd:
    print(f"\n[Cortex] Admin criado: {auth.ADMIN_EMAIL} / senha: {_seed_pwd}"
          f"  (troque após o primeiro login)\n")

# rotas que não exigem login
_PUBLIC = {"/login", "/api/login", "/api/logout", "/logo.png",
           "/favicon.ico", "/api/health"}


import re as _re
_CONV_RE = _re.compile(r"^/api/conversations/([^/]+)")


async def _seller_owns(owner_id, conv_id: str) -> bool:
    """Vendedor só acessa negócios da própria carteira (fail-CLOSED em erro)."""
    if settings.mock or not owner_id:
        return True
    if not str(conv_id).isdigit():
        # ids não numéricos (ex.: lead órfão 'wa_...') não pertencem a carteira
        return False
    try:
        from ploomes_client import ploomes
        if ploomes is None:
            return False
        deal = await ploomes.deal_context(int(conv_id))
        return deal.get("OwnerId") == owner_id
    except Exception as e:  # noqa: BLE001
        log.warning("checagem de posse falhou (%s): %s — negando", conv_id, e)
        return False


async def _enforce_owns(request: Request, conv_id) -> None:
    """Bloqueia (403) se o usuário for vendedor e o negócio não for da carteira.
    Usar nas rotas de ESCRITA que recebem o id no corpo/caminho."""
    u = _user(request)
    if u.get("role") == "seller" and not await _seller_owns(u.get("owner_id"), str(conv_id)):
        raise HTTPException(403, "sem acesso a este cliente")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in _PUBLIC or path.startswith("/webhooks/"):
        return await call_next(request)
    user = auth.user_for_token(request.cookies.get("cortex_session"))
    if user is None:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "não autenticado"}, status_code=401)
        return RedirectResponse("/login")
    request.state.user = user
    # vendedor: bloqueia acesso a cliente fora da carteira
    if user.get("role") == "seller":
        m = _CONV_RE.match(path)
        if m and not await _seller_owns(user.get("owner_id"), m.group(1)):
            return JSONResponse({"detail": "sem acesso a este cliente"}, status_code=403)
    return await call_next(request)


def _user(request: Request) -> dict:
    return getattr(request.state, "user", {}) or {}


@app.get("/login")
async def login_page():
    from paths import data_dir
    return FileResponse(str(data_dir() / "static" / "login.html"))


class LoginIn(BaseModel):
    email: str
    password: str


import time as _time
_login_fails: dict[str, list] = {}   # proteção simples contra força bruta


def _throttled(key: str) -> bool:
    now = _time.monotonic()
    arr = [t for t in _login_fails.get(key, []) if now - t < 300]
    _login_fails[key] = arr
    return len(arr) >= 8


@app.post("/api/login")
async def api_login(payload: LoginIn, request: Request):
    key = (request.client.host if request.client else "?") + "|" + payload.email.lower()
    if _throttled(key):
        raise HTTPException(429, "muitas tentativas — aguarde alguns minutos")
    token = auth.login(payload.email, payload.password)
    if not token:
        _login_fails.setdefault(key, []).append(_time.monotonic())
        log.warning("login falhou para %s", payload.email)
        raise HTTPException(401, "e-mail ou senha inválidos")
    _login_fails.pop(key, None)
    resp = JSONResponse({"ok": True})
    resp.set_cookie("cortex_session", token, httponly=True, samesite="lax",
                    secure=settings.secure_cookies, max_age=auth.SESSION_DAYS * 86400)
    return resp


@app.post("/api/logout")
async def api_logout(request: Request):
    auth.logout(request.cookies.get("cortex_session"))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("cortex_session")
    return resp


@app.get("/api/me")
async def api_me(request: Request):
    u = _user(request)
    return {"name": u.get("name"), "email": u.get("email"),
            "role": u.get("role"), "owner_id": u.get("owner_id")}


def _require_admin(request: Request) -> dict:
    u = _user(request)
    if u.get("role") != "admin":
        raise HTTPException(403, "acesso restrito ao administrador")
    return u


def _save_msg(d: dict) -> None:
    db.save_message(neppo_id=d.get("id"), phone=d["phone"], direction=d["direction"],
                    text=d.get("text", ""), media=d.get("media_url", ""),
                    ct=d.get("content_type", "TEXT"), bot=d.get("bot"),
                    name=d.get("name", ""), ts=str(d.get("createdAt") or ""),
                    agent_id=d.get("agent_id"))


# -- gestão de usuários (admin) --------------------------------------------
@app.get("/api/admin/users")
async def admin_users(request: Request):
    _require_admin(request)
    return auth.list_users()


class NewUser(BaseModel):
    email: str
    name: str
    password: str
    role: str = "seller"
    owner_id: int | None = None


@app.post("/api/admin/users")
async def admin_create_user(request: Request, payload: NewUser):
    _require_admin(request)
    if auth.user_by_email(payload.email):
        raise HTTPException(409, "e-mail já cadastrado")
    uid = auth.create_user(payload.email, payload.name, payload.password,
                           payload.role, payload.owner_id)
    return {"ok": True, "id": uid}


class PwdIn(BaseModel):
    password: str


@app.post("/api/admin/users/{user_id}/password")
async def admin_reset_pwd(request: Request, user_id: int, payload: PwdIn):
    _require_admin(request)
    auth.set_password(user_id, payload.password)
    return {"ok": True}


class ActiveIn(BaseModel):
    active: bool


@app.post("/api/admin/users/{user_id}/active")
async def admin_set_active(request: Request, user_id: int, payload: ActiveIn):
    u = _require_admin(request)
    if user_id == u.get("id") and not payload.active:
        raise HTTPException(400, "você não pode desativar a si mesmo")
    auth.set_active(user_id, payload.active)
    return {"ok": True}


@app.post("/api/password")
async def change_my_password(request: Request, payload: PwdIn):
    u = _user(request)
    auth.set_password(u["id"], payload.password)
    return {"ok": True}


# -- backfill do WhatsApp para o banco (admin) -----------------------------
@app.post("/api/admin/backfill")
async def admin_backfill(request: Request, pages: int = 200):
    _require_admin(request)
    if settings.mock or not settings.neppo_enabled:
        raise HTTPException(503, "Neppo não configurado")
    from neppo_client import get_neppo
    cli = get_neppo()

    async def job():
        try:
            n = await cli.backfill(_save_msg, pages=pages)
            db.set_meta("backfill", f"{n} msgs varridas em {dt.datetime.now().isoformat()}")
        except Exception as e:  # noqa
            db.set_meta("backfill", f"erro: {e}")

    asyncio.create_task(job())
    return {"ok": True, "started": True, "pages": pages}


@app.get("/api/admin/backfill/status")
async def admin_backfill_status(request: Request):
    _require_admin(request)
    return {"total_in_db": db.message_count(), "last": db.get_meta("backfill", "—")}


@app.get("/api/admin/metrics")
async def admin_metrics(request: Request):
    _require_admin(request)
    return await repo.admin_metrics()


@app.get("/api/admin/neppo-agents")
async def admin_neppo_agents(request: Request):
    """Vínculo vendedor (Ploomes) <-> agente (Neppo), lido do campo customizado.
    Use para conferir se o mapeamento está correto antes de usar em métricas."""
    _require_admin(request)
    if settings.mock or not settings.ploomes_configured:
        return {"linked": 0, "by_agent": {}, "mock": settings.mock}
    from ploomes_client import ploomes
    if ploomes is None:
        return {"linked": 0, "by_agent": {}}
    return await ploomes.neppo_agent_map()

FEEDBACK_LOG: list[dict] = []  # Camada 4 — troque por persistência em banco

# --- pub/sub em memória para SSE (tempo real) ------------------------------
_subscribers: set[asyncio.Queue] = set()


async def _publish(event: dict) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except Exception:
            pass


def _now() -> str:
    return dt.datetime.now().strftime("%H:%M")


# --------------------------------------------------------------------------
# API consumida pelo front
# --------------------------------------------------------------------------
@app.get("/api/conversations")
async def conversations(request: Request, mode: str = "smart", q: str = "", day: str = ""):
    if not settings.mock and not settings.ploomes_configured:
        raise HTTPException(
            503,
            "PLOOMES_API_KEY não configurada. Edite o arquivo .env na pasta do Cortex.",
        )
    u = _user(request)
    owner = u.get("owner_id") if u.get("role") == "seller" else None
    items = await repo.list_conversations(
        mode=mode, query=q, day=day or None, owner_id=owner, user_id=u.get("id"),
    )
    return [front_conversation(c) for c in items]


@app.get("/api/alerts")
async def alerts(request: Request):
    """Fila proativa: SLA de resposta, reativação (RFM) e negócios parados.
    Escopo por carteira para vendedor; admin vê tudo."""
    if not settings.mock and not settings.ploomes_configured:
        return {"alerts": [], "count": 0, "by_kind": {}}
    import alerts as alerts_mod
    u = _user(request)
    owner = u.get("owner_id") if u.get("role") == "seller" else None
    items = await repo.list_conversations(
        mode="smart", owner_id=owner, user_id=u.get("id"),
    )
    return alerts_mod.build_alerts(
        items,
        sla_minutes=settings.sla_first_reply_minutes,
        reactivation_factor=settings.reactivation_factor,
        stale_deal_days=settings.stale_deal_days,
    )


@app.get("/api/conversations/{conv_id}")
async def conversation(conv_id: str):
    c = await repo.get_conversation(conv_id)
    if c is None:
        raise HTTPException(404, "conversa não encontrada")
    return front_conversation(c)


@app.get("/api/conversations/{conv_id}/suggestion")
async def suggestion(conv_id: str):
    c = await repo.get_conversation(conv_id)
    if c is None:
        raise HTTPException(404, "conversa não encontrada")
    from models import Message

    raw = await repo.client_messages(conv_id)
    if raw:
        c.messages = [
            Message(
                sender="client" if m["f"] == "in" else "seller",
                text=m.get("t") or "",
                time=m.get("h") or "",
            )
            for m in raw
        ]
    s = build_suggestion(c)
    return front_suggestion(s) if s else JSONResponse(None)


class SeenIn(BaseModel):
    sig: str = ""


@app.post("/api/conversations/{conv_id}/seen")
async def conversation_seen(conv_id: str, request: Request, body: SeenIn):
    u = _user(request)
    phone = await repo.resolve_phone(conv_id)
    sig = body.sig.strip()
    if not sig and phone:
        sig = db.inbox_sig_for_phone(phone)
    if sig:
        db.set_seen_sig(int(u["id"]), conv_id, sig)
    return {"ok": True}


class SnoozeIn(BaseModel):
    hours: int = 2


@app.post("/api/conversations/{conv_id}/snooze")
async def conversation_snooze(conv_id: str, request: Request, body: SnoozeIn):
    u = _user(request)
    hours = max(1, min(body.hours, 168))
    until = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)).isoformat()
    db.set_snooze(int(u["id"]), conv_id, until)
    return {"ok": True, "until": until}


@app.delete("/api/conversations/{conv_id}/snooze")
async def conversation_unsnooze(conv_id: str, request: Request):
    u = _user(request)
    db.clear_snooze(int(u["id"]), conv_id)
    return {"ok": True}


@app.get("/api/conversations/{conv_id}/profile")
async def conversation_profile(conv_id: str):
    p = await repo.client_profile(conv_id)
    if p is None:
        raise HTTPException(404, "cliente não encontrado")
    return p


@app.get("/api/conversations/{conv_id}/commercial-stats")
async def conversation_commercial_stats(conv_id: str):
    return await repo.client_commercial_stats(conv_id)


@app.get("/api/conversations/{conv_id}/orders")
async def conversation_orders(conv_id: str):
    return await repo.client_orders(conv_id)


@app.get("/api/conversations/{conv_id}/quotes")
async def conversation_quotes(conv_id: str):
    return await repo.client_quotes(conv_id)


@app.get("/api/conversations/{conv_id}/timeline")
async def conversation_timeline(conv_id: str):
    return await repo.client_timeline(conv_id)


@app.get("/api/conversations/{conv_id}/insights")
async def conversation_insights(conv_id: str):
    return await repo.client_insights(conv_id)


# -- copiloto de IA (OpenRouter) -------------------------------------------
import ai


@app.get("/api/ai/status")
async def ai_status():
    return {"available": ai.available(), "model": ai.current_model() if ai.available() else None}


class AIReplyIn(BaseModel):
    instruction: str = ""


@app.post("/api/conversations/{conv_id}/ai/warm")
async def ai_warm(conv_id: str, background_tasks: BackgroundTasks):
    """Pré-carrega contexto (Ploomes + mensagens) ao abrir o thread — IA fica mais rápida."""
    if ai.available():
        background_tasks.add_task(repo.warm_ai_context, conv_id)
    return {"ok": True}


@app.post("/api/conversations/{conv_id}/ai/summary")
async def ai_summary(conv_id: str):
    if not ai.available():
        raise HTTPException(503, "IA não configurada (defina OPENROUTER_API_KEY)")
    ctx = await repo.ai_context(conv_id)
    text = await ai.summarize(ctx)
    if not text:
        raise HTTPException(502, "IA não retornou resposta")
    return {"text": text}


@app.post("/api/conversations/{conv_id}/ai/reply")
async def ai_reply(conv_id: str, payload: AIReplyIn):
    if not ai.available():
        raise HTTPException(503, "IA não configurada (defina OPENROUTER_API_KEY)")
    ctx = await repo.ai_context(conv_id)
    text = await ai.draft_reply(ctx, payload.instruction)
    if not text:
        raise HTTPException(502, "IA não retornou resposta")
    return {"text": text}


@app.post("/api/conversations/{conv_id}/ai/next-action")
async def ai_next_action(conv_id: str):
    if not ai.available():
        raise HTTPException(503, "IA não configurada (defina OPENROUTER_API_KEY)")
    ctx = await repo.ai_context(conv_id)
    text = await ai.next_best_action(ctx)
    if not text:
        raise HTTPException(502, "IA não retornou resposta")
    return {"text": text}


@app.get("/api/conversations/{conv_id}/ai/sentiment")
async def ai_sentiment(conv_id: str):
    if not ai.available():
        return None
    ctx = await repo.ai_context(conv_id)
    return await ai.sentiment(ctx)


@app.get("/api/conversations/{conv_id}/messages")
async def conversation_messages(conv_id: str):
    return await repo.client_messages(conv_id)


class OrderDraftIn(BaseModel):
    text: str = ""


@app.post("/api/conversations/{conv_id}/order-draft")
async def order_draft(conv_id: str, request: Request, body: OrderDraftIn):
    """Lê o pedido do cliente (ou um texto colado) e devolve itens com preço
    da tabela, prontos para virar uma cotação dry-run em /api/documents."""
    await _enforce_owns(request, conv_id)
    return await repo.build_order_draft(conv_id, body.text)


@app.get("/api/products")
async def products(q: str = ""):
    if settings.mock or not q:
        return []
    from ploomes_client import ploomes
    if ploomes is None:
        return []
    rows = await ploomes.search_products(q)
    return [{"id": r.get("Id"), "code": r.get("Code"), "name": r.get("Name"),
             "stock": None,
             "price": r.get("UnitPrice"),
             "unit": r.get("MeasurementUnit")} for r in rows]


# -- criação gated de cotações/pedidos (dry-run -> confirmação) -------------
@app.post("/api/documents")
async def documents(req: DocRequest, request: Request):
    await _enforce_owns(request, req.conversation_id)
    from repository import _resolve_contact
    cid, _, name = await _resolve_contact(req.conversation_id)
    if cid is None:
        raise HTTPException(400, "cliente sem ContactId no Ploomes — não dá pra criar")
    if req.dry_run:
        return doc_preview(cid, name, req)
    return await doc_create(cid, name, req)


class CreateDealIn(BaseModel):
    owner_id: int | None = None     # força um dono; senão usa agente/requisitante
    dry_run: bool = True


@app.post("/api/conversations/{conv_id}/create-deal")
async def create_deal(conv_id: str, request: Request, body: CreateDealIn):
    """Transforma um lead órfão (wa_...) em negócio no funil de entrada.
    dry_run=true só mostra o que seria criado; false grava no Ploomes."""
    u = _user(request)
    req_owner = u.get("owner_id") if u.get("role") == "seller" else None
    res = await repo.create_deal_from_orphan(
        conv_id, owner_id=body.owner_id, requesting_owner_id=req_owner,
        dry_run=body.dry_run,
    )
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "falha ao criar negócio"))
    return res


class InteractionIn(BaseModel):
    conversation_id: str
    type_id: int = 1            # 1=anotação, 7=WhatsApp, 4=e-mail
    content: str
    title: str = ""


@app.post("/api/interactions")
async def create_interaction(payload: InteractionIn, request: Request):
    await _enforce_owns(request, payload.conversation_id)
    res = await repo.add_interaction(payload.conversation_id, payload.type_id,
                                     payload.content, payload.title)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "falha ao registrar"))
    return res


@app.get("/api/templates")
async def list_templates():
    import intents as it
    import templates as tpl
    custom = tpl.load_custom()
    fb = db.feedback_by_intent()
    out = []
    for intent in it.INTENTS:
        iid = intent["id"]
        stats = fb.get(iid, {"used": 0, "edited": 0, "ignored": 0,
                             "total": 0, "acceptance": None})
        out.append({
            "id": iid, "label": intent["label"],
            "text": custom.get(iid) or tpl.DEFAULT_TEMPLATES.get(iid, ""),
            "customized": iid in custom,
            "feedback": stats,
        })
    # piores (mais ignorados, com dados) primeiro — chamam atenção pra revisão
    out.sort(key=lambda t: (t["feedback"]["total"] == 0,
                            t["feedback"]["acceptance"]
                            if t["feedback"]["acceptance"] is not None else 1))
    return {"templates": out,
            "placeholders": ["contato", "empresa", "pedido", "status", "entrega",
                             "rastreio", "transportadora", "cidade", "produto",
                             "unitario", "valor", "condicao", "estoque"]}


class TemplateIn(BaseModel):
    intent_id: str
    text: str


@app.post("/api/templates")
async def save_template(payload: TemplateIn):
    import templates as tpl
    tpl.save_custom(payload.intent_id, payload.text)
    return {"ok": True, "customized": bool(payload.text.strip())}


@app.post("/api/admin/refresh-fields")
async def refresh_fields():
    if settings.mock:
        return {"ok": False, "mock": True}
    from ploomes_client import ploomes
    n = await ploomes.refresh_fields()
    return {"ok": True, "fields": n}


# -- funil: estágios, vendedores, mover/atribuir (writes diretos) ----------
@app.get("/api/stages")
async def stages(pipeline: int = 0):
    if settings.mock:
        return []
    from ploomes_client import ploomes
    from ploomes_mapper import strip_emoji
    rows = await ploomes.stages()
    if pipeline:
        rows = [s for s in rows if s.get("PipelineId") == pipeline]
    return [{"id": s.get("Id"), "name": strip_emoji(s.get("Name")) or s.get("Name"),
             "pipeline": s.get("PipelineId"), "ord": s.get("Ordination")} for s in rows]


@app.get("/api/users")
async def users():
    if settings.mock:
        return []
    from ploomes_client import ploomes
    rows = await ploomes.users()
    return [{"id": u.get("Id"), "name": u.get("Name")} for u in rows if u.get("Name")]


class StageIn(BaseModel):
    stage_id: int


@app.post("/api/deals/{deal_id}/stage")
async def move_stage(deal_id: int, payload: StageIn, request: Request):
    if settings.mock:
        return {"ok": False, "error": "modo mock"}
    await _enforce_owns(request, deal_id)
    from ploomes_client import ploomes
    try:
        await ploomes.update_deal(deal_id, {"StageId": payload.stage_id})
        return {"ok": True}
    except Exception as e:
        log.error("Ploomes update_deal(stage) falhou (%s): %s", deal_id, e)
        raise HTTPException(502, "falha ao mover o negócio no Ploomes") from e


class OwnerIn(BaseModel):
    owner_id: int


@app.post("/api/deals/{deal_id}/owner")
async def assign_owner(deal_id: int, payload: OwnerIn, request: Request):
    if settings.mock:
        return {"ok": False, "error": "modo mock"}
    await _enforce_owns(request, deal_id)
    from ploomes_client import ploomes
    try:
        await ploomes.update_deal(deal_id, {"OwnerId": payload.owner_id})
        return {"ok": True}
    except Exception as e:
        log.error("Ploomes update_deal(owner) falhou (%s): %s", deal_id, e)
        raise HTTPException(502, "falha ao reatribuir o negócio no Ploomes") from e


# -- tempo real (Server-Sent Events) ---------------------------------------
@app.get("/api/stream")
async def stream():
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.add(q)

    async def gen():
        try:
            yield "retry: 5000\n\n"
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {json.dumps(ev)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _subscribers.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


class SendIn(BaseModel):
    conversation_id: str
    text: str


@app.post("/api/send")
async def send(payload: SendIn, request: Request):
    await _enforce_owns(request, payload.conversation_id)
    # eco local otimista (best-effort; não bloqueia o envio se faltar no cache)
    await repo.append_seller_message(payload.conversation_id, payload.text, _now())
    out = {"ok": True, "neppo": settings.neppo_enabled}
    if settings.neppo_enabled:
        phone = await repo.resolve_phone(payload.conversation_id)
        if not phone:
            raise HTTPException(400, "telefone do cliente não encontrado para envio")
        from neppo_client import get_neppo
        client = get_neppo()
        if client is None:
            raise HTTPException(503, "Neppo não configurado")
        try:
            await client.send_message(phone, payload.text)
        except Exception as e:
            log.error("Neppo send_message falhou (%s): %s", phone, e)
            raise HTTPException(502, "falha ao enviar a mensagem no WhatsApp") from e
        out["phone"] = phone
        db.save_message(phone=phone, direction="out", text=payload.text,
                        ts=dt.datetime.now().isoformat())
    repo.invalidate_ai_cache(payload.conversation_id)
    return out


class FeedbackIn(BaseModel):
    action: str          # used | edited | ignored
    intent_id: str
    conversation_id: str


@app.post("/api/feedback")
async def feedback(payload: FeedbackIn, request: Request):
    db.save_feedback(payload.action, payload.intent_id, payload.conversation_id,
                     _user(request).get("id"), dt.datetime.now().isoformat())
    return {"ok": True}


# --------------------------------------------------------------------------
# Webhooks
# --------------------------------------------------------------------------
def _valid_webhook(request: Request) -> bool:
    """Confere a chave do webhook (query `key` ou header X-Webhook-Key).

    Seguro por padrão: sem chave configurada, RECUSA — a menos que esteja em
    modo mock ou WEBHOOK_ALLOW_INSECURE=1 (só para desenvolvimento local)."""
    if settings.webhook_protected:
        key = request.query_params.get("key") or request.headers.get("X-Webhook-Key", "")
        return key == settings.webhook_validation_key
    if settings.mock or settings.webhook_allow_insecure:
        log.warning("webhook sem chave — liberado (mock/insecure, só dev)")
        return True
    log.error("webhook RECUSADO: defina WEBHOOK_VALIDATION_KEY (ou "
              "WEBHOOK_ALLOW_INSECURE=1 só em dev)")
    return False


@app.get("/webhooks/neppo")
async def neppo_validate(request: Request):
    # validação no estilo Meta: ecoa o challenge
    challenge = request.query_params.get("hub.challenge")
    return Response(content=challenge or "ok", media_type="text/plain")


@app.post("/webhooks/neppo")
async def neppo_incoming(request: Request):
    if not _valid_webhook(request):
        raise HTTPException(403, "webhook não autorizado")
    from neppo_client import parse_webhook
    payload = await request.json()
    msg = parse_webhook(payload)
    if msg is None:
        return {"ignored": True}
    conv = await repo.append_client_message(msg["phone"], msg["text"], msg["name"], _now())
    # persiste no banco (histórico permanente, busca, não-lidas). neppo_id
    # dedupa reentregas do webhook (INSERT OR IGNORE).
    db.save_message(phone=msg["phone"], direction="in", text=msg["text"],
                    name=msg.get("name", ""), ts=dt.datetime.now().isoformat(),
                    neppo_id=msg.get("id"))
    if conv:
        repo.invalidate_ai_cache(conv.id)
    # avisa as telas abertas em tempo real (SSE)
    await _publish({"type": "message", "phone": msg["phone"],
                    "text": msg["text"], "name": msg.get("name", "")})
    return {"ok": True}


@app.post("/webhooks/ploomes")
async def ploomes_changed(request: Request):
    if not _valid_webhook(request):
        raise HTTPException(403, "webhook não autorizado")
    payload = await request.json()
    deal_id = payload.get("Id") or payload.get("dealId")
    if deal_id and not settings.mock:
        from ploomes_client import ploomes
        ploomes.invalidate_deal(int(deal_id))   # cache fica fresco
    return {"ok": True}


@app.on_event("shutdown")
async def _close_clients():
    """Fecha os clientes HTTP (Ploomes/Neppo) ao desligar — evita leaks."""
    try:
        from ploomes_client import ploomes
        if ploomes is not None:
            await ploomes.aclose()
    except Exception as e:  # noqa: BLE001
        log.debug("aclose Ploomes: %s", e)
    try:
        from neppo_client import _client as _neppo
        if _neppo is not None:
            await _neppo.aclose()
    except Exception as e:  # noqa: BLE001
        log.debug("aclose Neppo: %s", e)
    try:
        import ai as _ai
        if getattr(_ai, "_http", None) is not None:
            await _ai._http.aclose()
    except Exception as e:  # noqa: BLE001
        log.debug("aclose IA: %s", e)


@app.get("/api/health")
async def health():
    if settings.mock:
        mode = "mock"
    elif not settings.ploomes_configured:
        mode = "no_credentials"
    else:
        mode = "live"
    out = {"status": "ok", "mode": mode}
    if settings.ploomes_configured and not settings.mock:
        try:
            from ploomes_client import ploomes
            if ploomes:
                deals = await ploomes.open_deals(top=1)
                out["ploomes"] = "ok"
                out["deals_sample"] = len(deals)
        except Exception as e:
            out["ploomes"] = "error"
            out["ploomes_error"] = str(e)
    if settings.neppo_enabled:
        try:
            from neppo_client import get_neppo
            client = get_neppo()
            if client:
                await client.get_token()
                out["neppo"] = "ok"
        except Exception as e:
            out["neppo"] = "error"
            out["neppo_error"] = str(e)
    else:
        out["neppo"] = "disabled"
    return out


# --------------------------------------------------------------------------
# Front-end estático (coloque painel-vendas.html em ./static/index.html)
# --------------------------------------------------------------------------
from paths import app_dir, data_dir

_root = app_dir()
_static = data_dir() / "static"
_static.mkdir(parents=True, exist_ok=True)
import shutil as _shutil
_idx_src, _idx_dst = _root / "index.html", _static / "index.html"
if _idx_src.exists() and _idx_src.resolve() != _idx_dst.resolve():
    _shutil.copy2(_idx_src, _idx_dst)
_bundle_static = _root / "static"
if _bundle_static.is_dir():
    for _f in _bundle_static.iterdir():
        if _f.is_file():
            _dst = _static / _f.name
            if _f.resolve() == _dst.resolve():
                continue
            if not _dst.exists() or _f.name == "index.html":
                _shutil.copy2(_f, _dst)
if _static.exists():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
