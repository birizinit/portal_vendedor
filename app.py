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
import reports as reports_mod
import deps

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

app.middleware("http")(deps.auth_middleware)


def _user(request: Request) -> dict:
    return deps.user(request)


async def _enforce_owns(request: Request, conv_id) -> None:
    await deps.enforce_owns(request, conv_id)


def _require_admin(request: Request) -> dict:
    return deps.require_admin(request)


from routers import register

register(app)

FEEDBACK_LOG: list[dict] = []  # Camada 4 — troque por persistência em banco


def _now() -> str:
    return deps.now_hm()


# --------------------------------------------------------------------------
# API consumida pelo front
# --------------------------------------------------------------------------
@app.get("/api/conversations")
async def conversations(
    request: Request,
    mode: str = "smart",
    q: str = "",
    day: str = "",
    offset: int = 0,
    limit: int = 80,
):
    if not settings.mock and not settings.ploomes_configured:
        raise HTTPException(
            503,
            "PLOOMES_API_KEY não configurada. Edite o arquivo .env na pasta do Cortex.",
        )
    u = _user(request)
    owner = u.get("owner_id") if u.get("role") == "seller" else None
    items, total = await repo.list_conversations(
        mode=mode, query=q, day=day or None, owner_id=owner,
        user_id=u.get("id"), offset=max(0, offset), limit=max(0, limit),
    )
    lim = limit if limit > 0 else total
    return {
        "items": [front_conversation(c) for c in items],
        "total": total,
        "offset": offset,
        "limit": lim,
        "has_more": limit > 0 and offset + len(items) < total,
    }


@app.get("/api/alerts")
async def alerts(request: Request):
    """Fila proativa — reutiliza cache da lista (sem segunda ida ao Ploomes)."""
    if not settings.mock and not settings.ploomes_configured:
        return {"alerts": [], "count": 0, "by_kind": {}}
    import alerts as alerts_mod
    u = _user(request)
    owner = u.get("owner_id") if u.get("role") == "seller" else None
    items = await repo.get_enriched_list(
        owner_id=owner, user_id=u.get("id"),
    )
    out = alerts_mod.build_alerts(
        items,
        sla_minutes=settings.sla_first_reply_minutes,
        reactivation_factor=settings.reactivation_factor,
        stale_deal_days=settings.stale_deal_days,
    )
    out["from_cache"] = True
    return out


@app.get("/api/search")
async def global_search(request: Request, q: str = ""):
    u = _user(request)
    owner = u.get("owner_id") if u.get("role") == "seller" else None
    return await repo.global_search(
        q, owner_id=owner, user_id=u.get("id"),
    )


class GoalIn(BaseModel):
    target: float
    period: str = ""


@app.get("/api/goals")
async def get_goals(request: Request):
    u = _user(request)
    oid = u.get("owner_id") or u.get("id")
    period = db.current_period()
    return {
        "period": period,
        "target": db.get_goal(int(oid), period),
        "owner_id": oid,
    }


@app.post("/api/goals")
async def set_goals(request: Request, body: GoalIn):
    u = _user(request)
    if u.get("role") == "seller" and not u.get("owner_id"):
        raise HTTPException(400, "vendedor sem owner_id no Ploomes")
    oid = int(u.get("owner_id") or u.get("id"))
    period = body.period.strip() or db.current_period()
    if body.target < 0:
        raise HTTPException(400, "meta inválida")
    db.set_goal(oid, float(body.target), period)
    return {"ok": True, "period": period, "target": body.target}


@app.get("/api/reports/weekly")
async def weekly_report(request: Request, format: str = "json"):
    u = _user(request)
    uid = u.get("id") if u.get("role") == "seller" else None
    if format == "csv":
        from fastapi.responses import PlainTextResponse
        csv_body = reports_mod.build_weekly_report(uid, as_csv=True)
        return PlainTextResponse(
            csv_body,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=cortex-semanal.csv"},
        )
    return reports_mod.build_weekly_report(uid, as_csv=False)


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
    repo.invalidate_list_cache()
    return {"ok": True, "until": until}


@app.delete("/api/conversations/{conv_id}/snooze")
async def conversation_unsnooze(conv_id: str, request: Request):
    u = _user(request)
    db.clear_snooze(int(u["id"]), conv_id)
    repo.invalidate_list_cache()
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
    deps.subscribers().add(q)

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
            deps.subscribers().discard(q)

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
    repo.invalidate_list_cache()
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
# Front-end estático — bundle em /app/static, cópia para data_dir no Fly
# --------------------------------------------------------------------------
from paths import ensure_static_assets

_static = ensure_static_assets()
if _static.exists():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
