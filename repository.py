"""Repositório — abstrai DE ONDE vêm as conversas.

Em modo mock, devolve os dados de exemplo. Com credencial do Ploomes,
é aqui que você monta as Conversation a partir das chamadas da API
(open_deals + deal_context + product_stock) e do score real. O resto da
aplicação não muda — depende só desta interface.
"""
from __future__ import annotations
import asyncio
import datetime as _dt
import logging
import re as _re
import time
from typing import Any, Optional

log = logging.getLogger("cortex.repo")

from config import settings
from models import (Conversation, Message, OrderSummary, QuoteSummary,
                    ClientProfile, ProfileField, TimelineItem)
from scoring import score_of
import ploomes_mapper as pm
from ploomes_mapper import conversation_from_deal
import mock_data

# cache em memória (negócios carregados do Ploomes + mensagens locais)
_state: dict[str, Conversation] = {}


def _load_mock_state() -> None:
    if _state:
        return
    for c in mock_data.MOCK_CONVERSATIONS:
        _state[c.id] = c.model_copy(deep=True)

_CACHE_TTL = 120.0
_ai_ctx_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_profile_cache: dict[str, tuple[float, Optional[ClientProfile]]] = {}
_resolve_cache: dict[str, tuple[float, tuple[Optional[int], str, str]]] = {}
_phone_cache: dict[str, tuple[float, str]] = {}


def invalidate_ai_cache(conv_id: str = "") -> None:
    """Limpa cache de IA (ex.: após nova mensagem no thread)."""
    if conv_id:
        _ai_ctx_cache.pop(conv_id, None)
        _profile_cache.pop(conv_id, None)
        _resolve_cache.pop(conv_id, None)
        _phone_cache.pop(conv_id, None)
    else:
        _ai_ctx_cache.clear()
        _profile_cache.clear()
        _resolve_cache.clear()
        _phone_cache.clear()


async def _load_from_ploomes(day: Optional[str] = None,
                             owner_id: Optional[int] = None) -> list[Conversation]:
    from ploomes_client import ploomes
    if ploomes is None:
        return []
    deals = await ploomes.open_deals(day=day, owner_id=owner_id)
    items: list[Conversation] = []
    for d in deals:
        conv = conversation_from_deal(d)
        cached = _state.get(conv.id)
        if cached and cached.messages:
            conv.messages = list(cached.messages)
        _state[conv.id] = conv
        items.append(conv)
    return items


def _orphan_leads(deals: list[Conversation]) -> list[Conversation]:
    """Leads de WhatsApp que mandaram mensagem mas ainda NÃO têm negócio
    aberto no Ploomes — surgem no painel marcados como 'Lead sem cadastro'.

    O casamento é pelo tail (8 dígitos) do telefone; quem já está coberto por
    um negócio carregado é ignorado para não duplicar.
    """
    import db
    from inbox import _digits_for_conv
    from models import ScoreComponent

    covered: set[str] = set()
    for c in deals:
        d = _digits_for_conv(c)
        if d:
            covered.add(d[-8:] if len(d) >= 8 else d)

    out: list[Conversation] = []
    for row in db.latest_per_phone(limit=500):
        tail = row.get("phone_tail") or ""
        if not tail or tail in covered:
            continue
        covered.add(tail)
        phone = (row.get("phone") or tail).strip()
        name = (row.get("name") or "").strip()
        conv_id = f"wa_{tail}"
        conv = _state.get(conv_id) or Conversation(
            id=conv_id,
            name=name or f"WhatsApp ·{tail[-4:]}",
            initials="WA",
            contact=name or "",
            phone=phone,
            tags=[{"l": "Lead sem cadastro", "k": "warn"}],
            score=[ScoreComponent(label="Lead WhatsApp", points=25)],
        )
        _state[conv_id] = conv
        out.append(conv)
    return out


async def list_conversations(mode: str = "smart", query: str = "",
                             day: Optional[str] = None,
                             owner_id: Optional[int] = None,
                             user_id: Optional[int] = None) -> list[Conversation]:
    if settings.mock:
        _load_mock_state()
        items = list(_state.values())
    elif not settings.ploomes_configured:
        log.error("PLOOMES_API_KEY ausente no .env")
        items = []
    else:
        try:
            items = await _load_from_ploomes(day=day, owner_id=owner_id)
        except Exception as e:  # noqa: BLE001
            log.error("falha ao carregar negócios do Ploomes: %s", e)
            items = []
        # leads de WhatsApp sem negócio no Ploomes (só para admin: vendedor
        # tem carteira isolada e veria leads que podem ser de outro). Sem
        # filtro de dia, que não se aplica a quem ainda não é negócio.
        if owner_id is None and not day:
            try:
                items += _orphan_leads(items)
            except Exception as e:  # noqa: BLE001
                log.warning("falha ao montar leads órfãos: %s", e)

    if query:
        q = query.lower()
        items = [c for c in items
                 if q in c.name.lower() or q in c.contact.lower()
                 or query in c.phone or query in c.cnpj]

    from inbox import enrich_all, sort_conversations

    enrich_all(items, user_id=user_id)
    if mode == "action":
        items = [
            c for c in items
            if (c.awaiting_reply or c.unread_count > 0) and not c.snoozed
        ]
    items = sort_conversations(items, mode)
    return items


async def get_conversation(conv_id: str) -> Optional[Conversation]:
    if settings.mock:
        return _state.get(conv_id)
    conv = _state.get(conv_id)
    if conv is not None:
        return conv
    if conv_id.startswith("wa_"):
        # lead órfão (sem negócio no Ploomes) — reconstrói do histórico local
        import db
        from models import ScoreComponent
        tail = conv_id[3:]
        if db.last_message_for_phone(tail) is None:
            return None
        ph = db.full_phone_for_tail(tail) or tail
        # "sacada": o telefone pode já ser um contato no Ploomes (sem negócio)
        cid, _, cname = await _resolve_contact(conv_id)
        if cid:
            name = cname or f"Cliente ·{tail[-4:]}"
            tags = [{"l": "Cliente (sem negócio aberto)", "k": "info"}]
        else:
            name = f"WhatsApp ·{tail[-4:]}"
            tags = [{"l": "Lead sem cadastro", "k": "warn"}]
        conv = Conversation(
            id=conv_id, name=name, initials="WA", contact=cname or "", phone=ph,
            tags=tags,
            score=[ScoreComponent(label="Lead WhatsApp", points=25)],
        )
        _state[conv_id] = conv
        return conv
    try:
        from ploomes_client import ploomes
        if ploomes is None:
            return None
        deal = await ploomes.deal_context(int(conv_id))
        conv = conversation_from_deal(deal, detail=deal)
        _state[conv.id] = conv
        return conv
    except (ValueError, TypeError):
        return None
    except Exception:
        return None


async def append_seller_message(conv_id: str, text: str, time: str) -> Optional[Conversation]:
    """Registra a mensagem enviada pelo vendedor (no mock, em memória)."""
    from models import Message
    conv = _state.get(conv_id)
    if conv is None:
        return None
    conv.messages.append(Message(sender="seller", text=text, time=time))
    return conv


async def append_client_message(phone: str, text: str, name: str, time: str) -> Optional[Conversation]:
    """Chamado pelo webhook da Neppo quando chega mensagem de cliente."""
    from models import Message
    from neppo_client import normalize_phone
    norm = normalize_phone(phone)
    conv = next(
        (c for c in _state.values()
         if normalize_phone(c.phone) == norm or phone in c.phone or c.phone in phone),
        None,
    )
    if conv is None:
        conv_id = f"wa_{norm}"
        from models import ScoreComponent
        conv = Conversation(
            id=conv_id,
            name=name or f"WhatsApp ·{phone[-4:]}",
            initials="WA",
            contact=name or "",
            phone=phone,
            tags=[{"l": "WhatsApp", "k": "info"}],
            score=[ScoreComponent(label="Lead WhatsApp", points=25)],
        )
        _state[conv_id] = conv
    conv.messages.append(Message(sender="client", text=text, time=time))
    return conv


# ===========================================================================
# Enriquecimento por cliente (Cliente 360, pedidos, cotações, timeline)
# ===========================================================================
async def _resolve_contact(conv_id: str) -> tuple[Optional[int], str, str]:
    """(contact_id, phone, name) a partir do negócio. Vazio em mock."""
    now = time.monotonic()
    hit = _resolve_cache.get(conv_id)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    if settings.mock:
        conv = _state.get(conv_id)
        out = (None, (conv.phone if conv else ""), (conv.name if conv else ""))
    elif conv_id.startswith("wa_"):
        # lead órfão: descobre se o telefone já é um contato no Ploomes
        out = None, "", ""
        try:
            from ploomes_client import ploomes
            if ploomes is not None:
                ph = await resolve_phone(conv_id)
                ct = await ploomes.contact_by_phone(ph) if ph else None
                if ct:
                    out = ct.get("Id"), "", (ct.get("Name") or "")
        except Exception:  # noqa: BLE001
            out = None, "", ""
    else:
        out = None, "", ""
        try:
            from ploomes_client import ploomes
            if ploomes is not None:
                deal = await ploomes.deal_context(int(conv_id))
                cid = deal.get("ContactId")
                contact = (deal.get("Contact") or {})
                name = contact.get("Name") or deal.get("Title") or ""
                out = cid, "", name
        except (ValueError, TypeError):
            out = None, "", ""
        except Exception:
            out = None, "", ""
    _resolve_cache[conv_id] = (now, out)
    return out


async def client_profile(conv_id: str) -> Optional[ClientProfile]:
    now = time.monotonic()
    hit = _profile_cache.get(conv_id)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    if settings.mock:
        c = _state.get(conv_id)
        if c is None:
            _profile_cache[conv_id] = (now, None)
            return None
        prof = ClientProfile(
            name=c.name, legal_name=c.name, cnpj=c.cnpj, segment=c.segment,
            situation=c.condition, city=(c.order.city or ""), phone=c.phone,
            status="Ativo (mock)", days_without_purchase=0,
            buy_frequency_days=45, buy_frequency_label="45",
            fields=[ProfileField(label="Cliente há", value=c.since),
                    ProfileField(label="Notas fiscais", value=c.nfs),
                    ProfileField(label="Frete", value=c.freight),
                    ProfileField(label="Condição", value=c.condition)],
        )
        _profile_cache[conv_id] = (time.monotonic(), prof)
        return prof
    cid, _, _ = await _resolve_contact(conv_id)
    if cid is None:
        _profile_cache[conv_id] = (now, None)
        return None
    from ploomes_client import ploomes
    contact = await ploomes.contact(int(cid))
    prof = pm.client_profile_from(contact)
    _profile_cache[conv_id] = (time.monotonic(), prof)
    return prof


async def client_orders(conv_id: str) -> list[OrderSummary]:
    if settings.mock:
        c = _state.get(conv_id)
        if c is None:
            return []
        out = []
        for o in (c.orders or []):
            out.append(OrderSummary(
                id=abs(hash(o.get("c", ""))) % 100000,
                number=str(o.get("c", "")).lstrip("#"),
                amount_fmt=o.get("v", ""), status=o.get("s", ""),
                is_open=o.get("sc") == "go",
            ))
        return out
    cid, _, _ = await _resolve_contact(conv_id)
    if cid is None:
        return []
    from ploomes_client import ploomes
    rows = await ploomes.orders_for_contact(int(cid))
    return [pm.order_summary_from(r) for r in rows]


async def client_commercial_stats(conv_id: str) -> dict:
    """Contagens para os cards do painel 360° (pedidos + orçamentos)."""
    orders = await client_orders(conv_id)
    quotes = await client_quotes(conv_id)
    return {
        "orders_open": sum(1 for o in orders if o.is_open),
        "orders_done": sum(1 for o in orders if not o.is_open),
        "quotes_open": sum(1 for q in quotes if q.is_open),
        "quotes_total": len(quotes),
        "orders_total": len(orders),
    }


async def client_quotes(conv_id: str) -> list[QuoteSummary]:
    if settings.mock:
        return []
    cid, _, _ = await _resolve_contact(conv_id)
    if cid is None:
        return []
    from ploomes_client import ploomes
    rows = await ploomes.quotes_for_contact(int(cid))
    return [pm.quote_summary_from(r) for r in rows]


def _brl_to_float(s: str) -> float:
    try:
        return float(str(s or "").replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


async def admin_metrics(top: int = 300) -> dict:
    """Agrega a carteira inteira para o módulo Admin (macro→micro)."""
    if settings.mock:
        _load_mock_state()
        items = list(_state.values())
    else:
        from ploomes_client import ploomes
        if ploomes is None:
            items = []
        else:
            deals = await ploomes.open_deals(top=top)
            items = [conversation_from_deal(d) for d in deals]

    def is_inativo(c):
        return any("inativ" in t["l"].lower() or "sem comprar" in t["l"].lower()
                   for t in (c.tags or []))

    total = sum(_brl_to_float(c.deal_value) for c in items)
    by_stage: dict[str, dict] = {}
    by_seller: dict[str, dict] = {}
    for c in items:
        v = _brl_to_float(c.deal_value)
        st = by_stage.setdefault(c.stage or "—", {"n": 0, "value": 0.0})
        st["n"] += 1
        st["value"] += v
        sl = by_seller.setdefault(c.owner or "Sem vendedor",
                                  {"n": 0, "value": 0.0, "inativos": 0, "leads": 0})
        sl["n"] += 1
        sl["value"] += v
        if is_inativo(c):
            sl["inativos"] += 1
        if any("lead" in t["l"].lower() for t in (c.tags or [])):
            sl["leads"] += 1

    def rows(d):
        return sorted(({"label": k, **v} for k, v in d.items()),
                      key=lambda r: r["value"], reverse=True)

    neppo_linked = 0
    if not settings.mock:
        try:
            from ploomes_client import ploomes
            if ploomes is not None:
                neppo_linked = (await ploomes.neppo_agent_map()).get("linked", 0)
        except Exception as e:  # noqa: BLE001
            log.warning("mapa de agentes Neppo indisponível: %s", e)

    return {
        "deals": len(items),
        "pipeline": total,
        "sellers": len([k for k in by_seller if k != "Sem vendedor"]),
        "inativos": sum(1 for c in items if is_inativo(c)),
        "by_stage": rows(by_stage),
        "by_seller": rows(by_seller),
        "messages_in_db": __import__("db").message_count(),
        "neppo_agents_linked": neppo_linked,
    }


async def client_messages_for_ai(conv_id: str, limit: int = 35) -> list[dict]:
    """Mensagens só do SQLite (rápido) — sem backfill Neppo na hora da IA."""
    import db

    if settings.mock:
        c = _state.get(conv_id)
        return [{"f": "in" if m.sender == "client" else "out", "t": m.text,
                 "h": m.time} for m in (c.messages if c else [])][-limit:]

    conv = _state.get(conv_id)
    phone = (conv.phone if conv and conv.phone else "") or await resolve_phone(conv_id)
    if not phone:
        return []
    rows = db.messages_for(phone, limit=limit)
    return [{"f": r["direction"], "t": r["text"] or "", "h": _fmt_ts(r["ts"])}
            for r in rows][-limit:]


async def ai_context(conv_id: str) -> dict:
    """Reúne contexto para IA — paralelo + cache (evita Ploomes/Neppo repetidos)."""
    now = time.monotonic()
    hit = _ai_ctx_cache.get(conv_id)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]

    profile, orders, quotes, messages = await asyncio.gather(
        client_profile(conv_id),
        client_orders(conv_id),
        client_quotes(conv_id),
        client_messages_for_ai(conv_id),
    )
    conv = _state.get(conv_id)
    open_orders = [o for o in orders if o.is_open][:6]
    ctx = {
        "contact": (conv.contact if conv else "") or (profile.name if profile else ""),
        "profile": profile.model_dump() if profile else {},
        "orders": [o.model_dump() for o in open_orders],
        "quotes": [q.model_dump() for q in quotes[:4]],
        "insights": pm.insights_from_order_summaries(orders) if orders else {},
        "messages": messages or [],
    }
    _ai_ctx_cache[conv_id] = (time.monotonic(), ctx)
    return ctx


async def build_order_draft(conv_id: str, text: str = "") -> dict:
    """Transforma a mensagem de pedido do cliente em itens com preço da tabela.

    Parseia 'QTD UNIDADE descrição', casa cada item com o catálogo do Ploomes
    (search_products) e devolve linhas prontas para virar uma cotação dry-run
    em /api/documents. Não grava nada."""
    from intents import parse_order
    if not text:
        msgs = await client_messages(conv_id)
        last_in = next((m for m in reversed(msgs) if m.get("f") == "in"), None)
        text = (last_in.get("t") if last_in else "") or ""
    parsed = parse_order(text)
    if not parsed:
        return {"items": [], "text": text, "all_matched": False}

    ploomes = None
    if not settings.mock:
        from ploomes_client import ploomes as _p
        ploomes = _p

    items: list[dict] = []
    for it in parsed:
        match = None
        if ploomes is not None:
            try:
                rows = await ploomes.search_products(it["description"])
                if rows:
                    r = rows[0]
                    match = {"id": r.get("Id"), "code": r.get("Code"),
                             "name": r.get("Name"),
                             "unit_price": float(r.get("UnitPrice") or 0)}
            except Exception as e:  # noqa: BLE001
                log.warning("busca de produto falhou (%s): %s", it["description"], e)
        items.append({
            "quantity": it["quantity"], "unit": it["unit"],
            "query": it["description"],
            "product_id": match["id"] if match else None,
            "code": match["code"] if match else None,
            "name": match["name"] if match else it["description"],
            "unit_price": match["unit_price"] if match else 0.0,
            "matched": bool(match),
        })
    return {"items": items, "text": text,
            "all_matched": bool(items) and all(i["matched"] for i in items)}


async def _resolve_intake_stage():
    """(pipeline_id, stage_id, pipeline_name, stage_name) do funil de entrada."""
    from ploomes_client import ploomes
    if ploomes is None:
        return None, None, "", ""
    target = settings.intake_pipeline_name.strip().lower()
    pipes = await ploomes.pipelines()
    pipe = (next((p for p in pipes if (p.get("Name") or "").strip().lower() == target), None)
            or next((p for p in pipes if target in (p.get("Name") or "").lower()), None))
    if pipe is None:
        return None, None, "", ""
    pid = pipe.get("Id")
    stages = sorted((s for s in await ploomes.stages() if s.get("PipelineId") == pid),
                    key=lambda s: s.get("Ordination") or 0)
    stage = None
    if settings.intake_stage_name.strip():
        nm = settings.intake_stage_name.strip().lower()
        stage = next((s for s in stages if nm in (s.get("Name") or "").lower()), None)
    if stage is None and stages:
        stage = stages[0]
    return pid, (stage.get("Id") if stage else None), \
        (pipe.get("Name") or ""), (stage.get("Name") if stage else "") or ""


async def create_deal_from_orphan(conv_id: str, *, owner_id: Optional[int] = None,
                                  requesting_owner_id: Optional[int] = None,
                                  dry_run: bool = True) -> dict:
    """Cria (gated) um negócio no funil de entrada a partir de um lead órfão.

    Dono = explícito -> agente Neppo que conversou -> quem está criando.
    dry_run=True só pré-visualiza os payloads; dry_run=False grava de verdade
    (cria o contato se ainda não existir, o negócio e uma anotação com o motivo).
    """
    if settings.mock:
        return {"ok": False, "error": "modo mock"}
    if not conv_id.startswith("wa_"):
        return {"ok": False, "error": "apenas leads de WhatsApp (wa_) entram por aqui"}
    from ploomes_client import ploomes
    if ploomes is None:
        return {"ok": False, "error": "Ploomes não configurado"}

    import db
    tail = conv_id[3:]
    conv = await get_conversation(conv_id)
    if conv is None:
        return {"ok": False, "error": "lead não encontrado"}
    phone = conv.phone or await resolve_phone(conv_id)
    contact_id, _, contact_name = await _resolve_contact(conv_id)
    lead_name = (contact_name or conv.contact or conv.name
                 or f"WhatsApp {tail[-4:]}").strip()

    # dono: explícito -> agente Neppo que bateu papo -> quem está criando
    chosen_owner = owner_id
    owner_via = "explícito" if chosen_owner else ""
    if chosen_owner is None:
        agent = db.last_agent_for_phone(tail)
        if agent is not None:
            amap = await ploomes.neppo_agent_map()
            hit = amap.get("by_agent", {}).get(str(agent))
            if hit and hit.get("id"):
                chosen_owner = hit["id"]
                owner_via = f"agente Neppo {agent}"
    if chosen_owner is None and requesting_owner_id:
        chosen_owner = requesting_owner_id
        owner_via = "usuário que está criando"

    # motivo + detalhe (últimas mensagens do WhatsApp)
    msgs = await client_messages(conv_id)
    recent = [m for m in msgs[-12:] if (m.get("t") or "").strip()]
    transcript = "\n".join(("Cliente: " if m["f"] == "in" else "Vendedor: ")
                           + m["t"] for m in recent)
    motivo = (f"Lead via {settings.intake_source}. Primeiro contato pelo "
              f"WhatsApp ({phone}).")
    detail = motivo + (f"\n\nÚltimas mensagens:\n{transcript}" if transcript else "")

    pid, sid, pipe_name, stage_name = await _resolve_intake_stage()
    if pid is None:
        return {"ok": False,
                "error": f"funil '{settings.intake_pipeline_name}' não encontrado no Ploomes"}

    contact_payload = None if contact_id else {
        "Name": lead_name, "Phones": [{"PhoneNumber": phone}] if phone else [],
    }
    deal_payload: dict = {"Title": lead_name, "PipelineId": pid}
    if sid:
        deal_payload["StageId"] = sid
    if chosen_owner:
        deal_payload["OwnerId"] = chosen_owner
    if contact_id:
        deal_payload["ContactId"] = contact_id

    preview = {
        "pipeline": {"id": pid, "name": pipe_name},
        "stage": {"id": sid, "name": stage_name},
        "owner": {"id": chosen_owner, "via": owner_via or "não definido"},
        "contact": {"id": contact_id, "name": lead_name,
                    "exists": bool(contact_id)},
        "reason": motivo,
        "detail": detail,
        "contact_payload": contact_payload,
        "deal_payload": deal_payload,
    }
    if dry_run:
        return {"ok": True, "dry_run": True, **preview,
                "warning": "Pré-visualização — nada foi gravado no Ploomes."}

    try:
        if contact_id is None:
            created_c = await ploomes.create_contact(contact_payload)
            cc = (created_c.get("value") or [created_c])[0] if isinstance(created_c, dict) else created_c
            contact_id = cc.get("Id") if isinstance(cc, dict) else None
            if not contact_id:
                return {"ok": False, "error": "não consegui criar o contato no Ploomes"}
            deal_payload["ContactId"] = contact_id
        created_d = await ploomes.create_deal(deal_payload)
        cd = (created_d.get("value") or [created_d])[0] if isinstance(created_d, dict) else created_d
        deal_id = cd.get("Id") if isinstance(cd, dict) else None
        # anotação com o motivo/contexto (a "trilha" do lead)
        try:
            ix = {"ContactId": contact_id, "TypeId": 1,
                  "Title": "Origem do lead (WhatsApp)", "Content": detail,
                  "Date": _dt.datetime.now(_dt.timezone.utc).isoformat()}
            if deal_id:
                ix["DealId"] = deal_id
            await ploomes.create_interaction(ix)
        except Exception as e:  # noqa: BLE001 — anotação é best-effort
            log.warning("anotação do lead falhou (deal %s): %s", deal_id, e)
        ploomes._list_cache.clear()
        invalidate_ai_cache(conv_id)
        return {"ok": True, "deal_id": deal_id, "contact_id": contact_id,
                "pipeline": pipe_name, "stage": stage_name, "owner_id": chosen_owner}
    except Exception as e:  # noqa: BLE001
        log.error("falha ao criar negócio do lead %s: %s", conv_id, e)
        return {"ok": False, "error": "falha ao criar o negócio no Ploomes"}


async def warm_ai_context(conv_id: str) -> None:
    """Pré-carrega contexto em background ao abrir a conversa."""
    try:
        await ai_context(conv_id)
    except Exception as e:  # noqa: BLE001
        log.debug("warm_ai_context(%s): %s", conv_id, e)


async def client_insights(conv_id: str) -> dict:
    """RFM + produtos mais comprados (a partir do histórico de pedidos)."""
    if settings.mock:
        c = _state.get(conv_id)
        if not c:
            return {}
        return {"orders_count": len(c.orders), "total_fmt": "", "ticket_fmt": "",
                "last_purchase": None, "recency_days": None, "avg_gap_days": None,
                "top_products": [{"name": c.order.product or "—", "code": None,
                                  "qty": c.order.qty or 0, "total_fmt": c.order.value or ""}]
                if c.order.product else []}
    cid, _, _ = await _resolve_contact(conv_id)
    if cid is None:
        return {}
    from ploomes_client import ploomes
    rows = await ploomes.orders_for_contact(int(cid))
    return pm.client_insights_from_orders(rows)


async def client_timeline(conv_id: str) -> list[TimelineItem]:
    """Linha do tempo combinada: interações do CRM (Ploomes) + WhatsApp (Neppo)."""
    items: list[TimelineItem] = []

    if settings.mock:
        c = _state.get(conv_id)
        if c:
            for m in c.messages:
                items.append(TimelineItem(
                    kind="whatsapp", source="neppo",
                    title="WhatsApp", content=m.text, date=m.time))
        return items

    cid, _, _ = await _resolve_contact(conv_id)
    from ploomes_client import ploomes

    if cid is not None:
        try:
            recs = await ploomes.interactions_for_contact(int(cid))
            items.extend(pm.timeline_item_from_interaction(r) for r in recs)
        except Exception:
            pass

    # WhatsApp via Neppo (telefone do contato)
    phone = await resolve_phone(conv_id)
    if phone and settings.neppo_enabled:
        try:
            from neppo_client import get_neppo
            cli = get_neppo()
            if cli:
                for m in await cli.message_history(phone, want=30):
                    items.append(TimelineItem(
                        kind="whatsapp", source="neppo",
                        title="WhatsApp", content=m["text"],
                        date=str(m.get("createdAt") or "")))
        except Exception:
            pass

    items.sort(key=lambda x: x.date or "", reverse=True)
    return items[:60]


def _fmt_ts(ts: str) -> str:
    return ts[11:16] if ts and len(ts) >= 16 else ""


async def client_messages(conv_id: str) -> list[dict]:
    """Mensagens do thread (WhatsApp) — banco primeiro (histórico completo),
    Neppo como fallback (e popula o banco na primeira vez)."""
    import db
    if settings.mock:
        c = _state.get(conv_id)
        return [{"f": "in" if m.sender == "client" else "out", "t": m.text,
                 "h": m.time, "media": "", "ct": "TEXT", "bot": False}
                for m in (c.messages if c else [])]
    phone = await resolve_phone(conv_id)
    if not phone:
        return []

    rows = db.messages_for(phone, limit=300)
    if rows:
        return [{"f": r["direction"], "t": r["text"] or "", "h": _fmt_ts(r["ts"]),
                 "d": (r["ts"] or "")[:10], "media": r["media"] or "",
                 "ct": r["ct"] or "TEXT", "bot": bool(r["bot"])} for r in rows]

    if not settings.neppo_enabled:
        return []
    try:
        from neppo_client import get_neppo
        cli = get_neppo()
        if cli is None:
            return []
        hist = await cli.message_history(phone, want=40)
    except Exception as e:  # noqa: BLE001
        log.warning("falha ao buscar histórico WhatsApp (%s): %s", phone, e)
        return []
    out = []
    for m in hist:
        ts = str(m.get("createdAt") or "")
        db.save_message(neppo_id=m.get("id"), phone=phone, direction=m["direction"],
                        text=m.get("text", ""), media=m.get("media_url", ""),
                        ct=m.get("content_type", "TEXT"), bot=m.get("bot"),
                        name=m.get("name", ""), ts=ts)
        out.append({"f": m["direction"], "t": m.get("text", ""), "h": _fmt_ts(ts),
                    "d": ts[:10] if ts else "", "media": m.get("media_url", ""),
                    "ct": m.get("content_type", "TEXT"), "bot": bool(m.get("bot"))})
    return out


async def add_interaction(conv_id: str, type_id: int, content: str,
                          title: str = "") -> dict:
    """Registra uma interação no CRM (anotação/ligação/WhatsApp). Escrita gated."""
    if settings.mock:
        return {"ok": False, "error": "modo mock — defina PLOOMES_API_KEY"}
    if not content.strip():
        return {"ok": False, "error": "conteúdo vazio"}
    cid, _, _ = await _resolve_contact(conv_id)
    if cid is None:
        return {"ok": False, "error": "cliente sem ContactId no Ploomes"}
    from ploomes_client import ploomes
    payload = {
        "ContactId": int(cid),
        "TypeId": int(type_id),
        "Content": content.strip(),
        "Date": _dt.datetime.now().astimezone().isoformat(),
    }
    if title.strip():
        payload["Title"] = title.strip()
    try:
        payload["DealId"] = int(conv_id)
    except (ValueError, TypeError):
        pass
    try:
        res = await ploomes.create_interaction(payload)
        ploomes.invalidate_contact(int(cid))
        created = (res.get("value") or [res])[0] if isinstance(res, dict) else res
        return {"ok": True, "id": created.get("Id") if isinstance(created, dict) else None}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "payload": payload}


async def _phone_for_contact(contact_id: Optional[int]) -> str:
    if contact_id is None:
        return ""
    try:
        from ploomes_client import ploomes
        if ploomes is None:
            return ""
        contact = await ploomes.contact(int(contact_id))
        phones = contact.get("Phones") or []
        if phones:
            return str(phones[0].get("PhoneNumber") or phones[0].get("Number") or "")
    except Exception:
        pass
    return ""


async def resolve_phone(conv_id: str) -> str:
    """Telefone do cliente para WhatsApp — tenta Contact.Phones e, se vazio,
    extrai dos campos de texto (leads 'via loja' trazem o número no título)."""
    now = time.monotonic()
    hit = _phone_cache.get(conv_id)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    if settings.mock:
        c = _state.get(conv_id)
        ph = c.phone if c else ""
        _phone_cache[conv_id] = (now, ph)
        return ph
    conv = _state.get(conv_id)
    if conv and conv.phone:
        _phone_cache[conv_id] = (now, conv.phone)
        return conv.phone
    if conv_id.startswith("wa_"):
        import db
        tail = conv_id[3:]
        ph = db.full_phone_for_tail(tail) or tail
        _phone_cache[conv_id] = (now, ph)
        return ph
    cid, _, name = await _resolve_contact(conv_id)
    ph = await _phone_for_contact(cid)
    if ph:
        _phone_cache[conv_id] = (time.monotonic(), ph)
        return ph
    ph = ""
    try:
        from ploomes_client import ploomes
        if ploomes is not None:
            deal = await ploomes.deal_context(int(conv_id))
            candidates = [deal.get("Title"), (deal.get("Contact") or {}).get("Name"), name]
            for src in candidates:
                m = _re.search(r"(\d{10,13})", str(src or ""))
                if m:
                    ph = m.group(1)
                    break
    except (ValueError, TypeError):
        pass
    except Exception:
        pass
    _phone_cache[conv_id] = (time.monotonic(), ph)
    return ph
