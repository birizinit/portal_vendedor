"""Mapeia registros do Ploomes para os modelos de domínio.

Os campos do Sankhya vivem em OtherProperties; aqui eles viram campos
nomeados (Status Workflow, Nro. Nota, Previsão de Entrega...) via
other_properties.extract + get (que tolera variações no rótulo).
"""
from __future__ import annotations
import datetime as _dt
import re as _re
from typing import Any, Optional

from models import (Conversation, Order, ScoreComponent, OrderSummary,
                    QuoteSummary, ClientProfile, ProfileField, TimelineItem)
from scoring import build_score_components, build_score_real
import other_properties as op


def _initials(name: str) -> str:
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "??"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _contact_name(deal: dict) -> str:
    contact = deal.get("Contact") or {}
    return (contact.get("Name") or deal.get("Title") or "Cliente").strip()


def _phone(deal: dict) -> str:
    contact = deal.get("Contact") or {}
    phones = contact.get("Phones") or []
    if phones:
        p = phones[0]
        ph = str(p.get("PhoneNumber") or p.get("Number") or "")
        if ph:
            return ph
    ph = str(contact.get("Phone") or "")
    if ph:
        return ph
    for src in (deal.get("Title"), contact.get("Name")):
        m = _re.search(r"(\d{10,13})", str(src or ""))
        if m:
            return m.group(1)
    return ""


def _parse_frequency_days(val: Any) -> Optional[int]:
    """Converte 'Frequência de compra' do Sankhya para dias (número)."""
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        n = int(val)
        return n if n > 0 else None
    m = _re.search(r"(\d+)", str(val).replace(",", "."))
    return int(m.group(1)) if m else None


def _amount(deal: dict) -> float:
    for key in ("Amount", "Value", "DealValue"):
        v = deal.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return 0.0


import re as _re

# remove emojis/símbolos (preserva os marcadores ⟨⟩ U+27E8/27E9 dos templates)
_EMOJI_RE = _re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000026FF\U00002700-\U000027BF"
    "\U0001F1E6-\U0001F1FF\U00002B00-\U00002BFF️‍]+")


def _clean(s: Any) -> str:
    return _re.sub(r"\s+", " ", str(s or "")).strip()


def strip_emoji(s: Any) -> str:
    return _re.sub(r"\s+", " ", _EMOJI_RE.sub("", str(s or ""))).strip()


def _classify_status(status: str) -> str:
    s = status.lower()
    if any(w in s for w in ("inativ", "bloque", "suspens", "negativ")):
        return "bad"
    if any(w in s for w in ("lead", "prospect", "👀", "novo")):
        return "info"
    if any(w in s for w in ("ativ", "🟢", "ok")):
        return "ok"
    return "info"


def build_tags(*, props: dict, amount: float, stage: str,
               days_in_stage: Any, segment: str = "") -> list[dict]:
    """Tags inteligentes a partir dos dados que já vêm do negócio + contato.

    Sem custo extra de API: usa o Status do Cliente / Dias sem compra do
    OtherProperties (Sankhya), o valor do negócio e o estágio do funil.
    """
    tags: list[dict] = []

    status = _clean(op.get(props, "Status do Cliente"))
    if status:
        tags.append({"l": strip_emoji(status), "k": _classify_status(status)})

    dias = _int_or_none(op.get(props, "Dias sem compra"))
    if dias is not None and dias >= 30:
        tags.append({"l": f"{dias}d sem comprar",
                     "k": "bad" if dias >= 60 else "warn"})

    if amount and amount >= 10000:
        tags.append({"l": "Alto valor", "k": "value"})
    elif amount and amount >= 3000:
        tags.append({"l": "Bom valor", "k": "value"})

    if stage:
        tags.append({"l": _clean(stage), "k": "stage"})

    dis = _int_or_none(days_in_stage)
    if dis is not None and dis >= 10:
        tags.append({"l": f"parado {dis}d", "k": "stale"})

    return tags[:4]


def _owner_name(deal: dict, src: dict) -> str:
    """Nome do vendedor: Owner do negócio, com fallback pro Owner do contato."""
    owner = deal.get("Owner") or src.get("Owner") or {}
    if isinstance(owner, dict) and owner.get("Name"):
        return _clean(owner["Name"])
    contact_owner = (src.get("Contact") or {}).get("Owner") or {}
    if isinstance(contact_owner, dict) and contact_owner.get("Name"):
        return _clean(contact_owner["Name"])
    return ""


def conversation_from_deal(deal: dict, *, detail: Optional[dict] = None) -> Conversation:
    """Monta Conversation a partir de um Deal (lista ou deal_context expandido)."""
    src = detail if detail is not None else deal
    deal_id = deal.get("Id") or src.get("Id")
    name = _contact_name(src)
    company = (src.get("Contact") or {}).get("Company") or {}
    company_name = (company.get("Name") if isinstance(company, dict) else None) or src.get("Title") or name
    stage = src.get("Stage") or {}
    stage_name = (stage.get("Name") or "proposta").lower()

    amount = _amount(src)
    amount_fmt = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    products = src.get("Products") or []
    product_name = ""
    if products:
        product_name = str(products[0].get("Name") or products[0].get("ProductName") or "")

    # vendedor + tags inteligentes (a partir do OtherProperties do contato)
    contact = src.get("Contact") or {}
    props = op.extract(contact) if contact.get("OtherProperties") else {}
    owner = _owner_name(deal, src)
    stage_display = strip_emoji(stage.get("Name")) if isinstance(stage, dict) else ""
    segment = str(op.get(props, "Perfil Principal (Segmento)", default="")
                  or contact.get("Type") or "")
    days_no = _int_or_none(op.get(props, "Dias sem compra"))
    freq_days = _parse_frequency_days(op.get(props, "Frequência de compra"))
    tags = build_tags(props=props, amount=amount, stage=stage_display,
                      days_in_stage=deal.get("DaysInStage") or src.get("DaysInStage"),
                      segment=segment)

    # score real, a partir dos sinais do cliente (status, recência, frequência)
    score = build_score_real(
        open_value=amount, stage=stage_display,
        client_status=strip_emoji(op.get(props, "Status do Cliente", default="")),
        days_no_purchase=days_no,
        buy_frequency=str(op.get(props, "Frequência de compra", default="") or ""),
    )

    return Conversation(
        id=str(deal_id),
        name=str(company_name)[:80],
        initials=_initials(str(company_name)),
        contact=name,
        phone=_phone(src),
        cnpj=str((src.get("Contact") or {}).get("Register") or ""),
        since="",
        condition="",
        nfs="",
        freight="",
        segment=segment,
        days_without_purchase=days_no,
        buy_frequency_days=freq_days,
        owner=owner,
        stage=stage_display,
        stage_id=deal.get("StageId") or src.get("StageId"),
        pipeline_id=deal.get("PipelineId") or src.get("PipelineId"),
        deal_value=amount_fmt if amount else "",
        tags=tags,
        score=score,
        order=Order(
            code=f"#{deal_id}" if deal_id else None,
            status=stage.get("Name") if isinstance(stage, dict) else None,
            status_kind="go",
            value=amount_fmt if amount else None,
            product=product_name or None,
        ),
        orders=[],
        messages=[],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_TERMINAL_STATUS = {"FATURADO", "ENTREGUE", "CANCELADO", "CONCLUIDO",
                    "CONCLUÍDO", "FINALIZADO"}


def _fmt_brl(v: Any) -> str:
    try:
        return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return ""


def _fmt_date(iso: Any, with_year: bool = True) -> Optional[str]:
    if not iso:
        return None
    s = str(iso)
    try:
        d = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d.strftime("%d/%m/%Y" if with_year else "%d/%m")
    except ValueError:
        # já pode vir "29/05/2026 22:12:15"
        return s[:10]


def _int_or_none(v: Any) -> Optional[int]:
    try:
        if v in (None, "", 0, "0"):
            return None
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _parse_installments(raw: Any) -> str:
    """'<p>1  BOLETO - PRAZO  31  R$ 9.936,74</p>...' -> '3x BOLETO (31/60/90d)'."""
    if not raw:
        return ""
    import re as _re
    text = _re.sub(r"</?p>", "\n", str(raw))
    prazos: list[str] = []
    forma = ""
    for ln in text.split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        parts = _re.split(r"\s{2,}", ln)
        if len(parts) >= 3:
            forma = parts[1]
            prazos.append(parts[2].strip())
    if not prazos:
        return ""
    forma_short = forma.replace(" - PRAZO", "").replace("PRAZO", "").strip() or "Parcelado"
    if len(prazos) == 1 and prazos[0] in ("0", "1"):
        return f"{forma_short} à vista"
    return f"{len(prazos)}x {forma_short} ({'/'.join(prazos)}d)"


def _parse_iso_date(iso: Any):
    if not iso:
        return None
    try:
        return _dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _product_lines(rec: dict) -> list[dict]:
    out = []
    for p in rec.get("Products") or []:
        out.append({
            "product_id": p.get("ProductId"),
            "code": p.get("ProductCode"),
            "name": p.get("ProductName"),
            "qty": p.get("Quantity"),
            "unit_price": p.get("UnitPrice"),
            "unit": _fmt_brl(p.get("UnitPrice")),
            "total": _fmt_brl(p.get("Total")),
        })
    return out


# ---------------------------------------------------------------------------
# Pedidos
# ---------------------------------------------------------------------------
def order_summary_from(rec: dict) -> OrderSummary:
    props = op.extract(rec)
    status = str(op.get(props, "Status Workflow", default="") or "")
    nf = op.get(props, "Nro. Nota (Sankhya)", "Nro. Nota")
    nf = None if nf in (None, 0, "0", "") else str(nf)
    billing = op.get(props, "Data de Faturamento (Sankhya)", "Data de Faturamento")
    is_open = bool(status) and status.strip().upper() not in _TERMINAL_STATUS
    if not status and not nf and not billing:
        is_open = True

    # atraso: entrega prevista vencida e pedido ainda em aberto
    eta_raw = op.get(props, "Previsão de Entrega (Sankhya)", "Previsão de Entrega")
    eta_date = _parse_iso_date(eta_raw)
    late, days_late = False, 0
    if is_open and eta_date is not None:
        delta = (_dt.date.today() - eta_date).days
        if delta > 0:
            late, days_late = True, delta

    amount = rec.get("Amount") or 0.0
    return OrderSummary(
        id=int(rec.get("Id")),
        number=str(rec.get("OrderNumber")) if rec.get("OrderNumber") else None,
        date=_fmt_date(rec.get("Date")),
        amount=float(amount),
        amount_fmt=_fmt_brl(amount),
        status=status or (rec.get("StageId") and "—") or "—",
        nf=nf,
        eta=_fmt_date(op.get(props, "Previsão de Entrega (Sankhya)",
                             "Previsão de Entrega")),
        billing_date=_fmt_date(billing),
        freight=str(op.get(props, "CIF/FOB", "Tipo de Frete", default="") or "") or None,
        volumes=_int_or_none(op.get(props, "Qtd Volumes")),
        history=str(op.get(props, "Histórico WF", default="") or "") or None,
        payment=_parse_installments(op.get(props, "Tabela de Parcelas (Sankhya)",
                                           "Tabela de Parcelas")),
        is_open=is_open,
        late=late,
        days_late=days_late,
        items=_product_lines(rec),
        document_url=rec.get("DocumentUrl"),
    )


# ---------------------------------------------------------------------------
# Cotações
# ---------------------------------------------------------------------------
def quote_summary_from(rec: dict) -> QuoteSummary:
    props = op.extract(rec)
    amount = rec.get("Amount") or 0.0
    status = str(op.get(props, "Status da Nota (Sankhya)", default="") or "")
    is_open = bool(status) and status.strip().upper() not in _TERMINAL_STATUS
    if not status:
        is_open = True
    return QuoteSummary(
        id=int(rec.get("Id")),
        number=str(rec.get("QuoteNumber")) if rec.get("QuoteNumber") else None,
        date=_fmt_date(rec.get("Date")),
        amount=float(amount),
        amount_fmt=_fmt_brl(amount),
        needs_approval=str(op.get(props, "Aprovação necessária?", default="") or "") or None,
        discount_validator=str(op.get(props, "Validador de desconto", default="") or "") or None,
        eta=_fmt_date(op.get(props, "Previsão de Entrega (Sankhya)", "Previsão de Entrega")),
        status=status or None,
        is_open=is_open,
        items=_product_lines(rec),
        document_url=rec.get("DocumentUrl"),
    )


# ---------------------------------------------------------------------------
# Insights RFM + produtos mais comprados (a partir do histórico de pedidos)
# ---------------------------------------------------------------------------
def client_insights_from_orders(orders: list[dict]) -> dict:
    """RFM resumido + top produtos. `orders` são os registros crus do Ploomes."""
    total = 0.0
    dated: list = []
    prod: dict[str, dict] = {}
    for o in orders:
        total += float(o.get("Amount") or 0)
        d = _parse_iso_date(o.get("Date"))
        if d:
            dated.append(d)
        for p in o.get("Products") or []:
            name = p.get("ProductName") or p.get("ProductCode") or "—"
            agg = prod.setdefault(name, {"qty": 0.0, "total": 0.0,
                                         "code": p.get("ProductCode")})
            agg["qty"] += float(p.get("Quantity") or 0)
            agg["total"] += float(p.get("Total") or 0)

    n = len(orders)
    ticket = total / n if n else 0.0
    last = max(dated) if dated else None
    recency = (_dt.date.today() - last).days if last else None
    avg_gap = None
    if len(dated) >= 2:
        ds = sorted(dated)
        gaps = [(ds[i + 1] - ds[i]).days for i in range(len(ds) - 1)]
        avg_gap = round(sum(gaps) / len(gaps))

    top = sorted(prod.items(), key=lambda kv: kv[1]["total"], reverse=True)[:5]
    return {
        "orders_count": n,
        "total_fmt": _fmt_brl(total),
        "ticket_fmt": _fmt_brl(ticket),
        "last_purchase": _fmt_date(last.isoformat()) if last else None,
        "recency_days": recency,
        "avg_gap_days": avg_gap,
        "top_products": [{
            "name": name, "code": v["code"],
            "qty": int(v["qty"]) if v["qty"] == int(v["qty"]) else round(v["qty"], 1),
            "total_fmt": _fmt_brl(v["total"]),
        } for name, v in top],
    }


def _parse_br_date(s: Any) -> Optional[_dt.date]:
    if not s:
        return None
    parts = str(s).strip().split("/")
    if len(parts) == 3:
        try:
            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
            if y < 100:
                y += 2000
            return _dt.date(y, m, d)
        except ValueError:
            pass
    return _parse_iso_date(s)


def insights_from_order_summaries(orders: list) -> dict:
    """RFM a partir de OrderSummary (evita segunda ida ao Ploomes na IA)."""
    from models import OrderSummary

    total = 0.0
    dated: list[_dt.date] = []
    prod: dict[str, dict] = {}
    for o in orders:
        if not isinstance(o, OrderSummary):
            continue
        total += float(o.amount or 0)
        d = _parse_br_date(o.date)
        if d:
            dated.append(d)
        for it in o.items or []:
            name = it.get("name") or it.get("code") or "—"
            agg = prod.setdefault(name, {"qty": 0.0, "total": 0.0, "code": it.get("code")})
            try:
                agg["qty"] += float(it.get("qty") or 0)
            except (TypeError, ValueError):
                pass
            t = it.get("total")
            if t:
                try:
                    agg["total"] += float(str(t).replace(".", "").replace(",", "."))
                except ValueError:
                    pass

    n = len(orders)
    ticket = total / n if n else 0.0
    last = max(dated) if dated else None
    recency = (_dt.date.today() - last).days if last else None
    avg_gap = None
    if len(dated) >= 2:
        ds = sorted(dated)
        gaps = [(ds[i + 1] - ds[i]).days for i in range(len(ds) - 1)]
        avg_gap = round(sum(gaps) / len(gaps))

    top = sorted(prod.items(), key=lambda kv: kv[1]["total"], reverse=True)[:5]
    return {
        "orders_count": n,
        "total_fmt": _fmt_brl(total),
        "ticket_fmt": _fmt_brl(ticket),
        "last_purchase": last.strftime("%d/%m/%Y") if last else None,
        "recency_days": recency,
        "avg_gap_days": avg_gap,
        "top_products": [{
            "name": name, "code": v["code"],
            "qty": int(v["qty"]) if v["qty"] == int(v["qty"]) else round(v["qty"], 1),
            "total_fmt": _fmt_brl(v["total"]),
        } for name, v in top],
    }


# ---------------------------------------------------------------------------
# Cliente 360
# ---------------------------------------------------------------------------
# Campos do Sankhya que já viram coluna nomeada no perfil — o resto vira "extra".
_PROFILE_PRIMARY = {
    "Status do Cliente", "Situação", "Dias sem compra", "Frequência de compra",
    "[Ploomes] Último orçamento",
    "Perfil Principal (Segmento)", "Perfil principal", "Cód. Parceiro (Sankhya)",
    "E-mail para envio de NFe", "Inscrição Estadual /Identidade(Sankhya)",
    "Classificação ICMS (Sankhya)", "Região", "Alíquota do destinatário",
}


def client_profile_from(contact: dict) -> ClientProfile:
    props = op.extract(contact)
    phones = contact.get("Phones") or []
    phone = ""
    if phones:
        phone = str(phones[0].get("PhoneNumber") or phones[0].get("Number") or "")

    extras: list[ProfileField] = []
    for name, val in props.items():
        if name in _PROFILE_PRIMARY:
            continue
        if val in (None, "", 0, "0", 0.0):
            continue
        sval = str(val)
        if len(sval) > 60 or "<" in sval[:20]:   # pula HTML/textão
            continue
        extras.append(ProfileField(label=name, value=sval))

    city = contact.get("City")
    city_name = city.get("Name") if isinstance(city, dict) else (contact.get("Neighborhood") or "")

    return ClientProfile(
        contact_id=_int_or_none(contact.get("Id")),
        name=str(contact.get("Name") or ""),
        legal_name=str(contact.get("LegalName") or ""),
        cnpj=str(contact.get("CNPJ") or contact.get("Register") or ""),
        status=strip_emoji(op.get(props, "Status do Cliente", default="")),
        situation=strip_emoji(op.get(props, "Situação", default="")),
        days_without_purchase=_int_or_none(op.get(props, "Dias sem compra")),
        buy_frequency_days=_parse_frequency_days(op.get(props, "Frequência de compra")),
        buy_frequency_label=str(op.get(props, "Frequência de compra", default="") or ""),
        last_quote_date=_fmt_date(op.get(props, "[Ploomes] Último orçamento")),
        segment=str(op.get(props, "Perfil Principal (Segmento)", "Perfil principal",
                           default="") or ""),
        partner_code=str(op.get(props, "Cód. Parceiro (Sankhya)", default="") or ""),
        email=str(contact.get("Email") or ""),
        nfe_email=str(op.get(props, "E-mail para envio de NFe", default="") or ""),
        state_registration=str(op.get(props, "Inscrição Estadual /Identidade(Sankhya)",
                                      default="") or ""),
        city=str(city_name or ""),
        phone=phone,
        icms_class=str(op.get(props, "Classificação ICMS (Sankhya)", default="") or ""),
        fields=extras[:12],
    )


# ---------------------------------------------------------------------------
# Timeline (InteractionRecords do CRM)
# ---------------------------------------------------------------------------
# TypeId do Ploomes -> rótulo amigável (mapeado pelos tipos reais da conta).
_INTERACTION_KIND = {1: "note", 3: "note", 4: "email", 7: "whatsapp", 2: "email"}


def timeline_item_from_interaction(rec: dict) -> TimelineItem:
    type_id = rec.get("TypeId")
    kind = _INTERACTION_KIND.get(type_id, "interaction")
    content = rec.get("Content") or ""
    # remove HTML grosseiro
    if "<" in content:
        import re
        content = re.sub(r"<[^>]+>", " ", content)
        content = re.sub(r"\s+", " ", content).strip()
    return TimelineItem(
        kind=kind,
        title=str(rec.get("Title") or rec.get("EmailSubject") or "Interação"),
        content=content[:500],
        date=str(rec.get("Date") or rec.get("CreateDate") or ""),
        source="ploomes",
    )
