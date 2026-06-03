"""Modelos de domínio (pydantic v2).

Internamente usamos nomes claros (sender, points, ...). O front protótipo
espera chaves curtas (f, t, h, l, p, ...), então `front_conversation()`
converte para o formato que o painel-vendas.html já consome — assim o
backend vira um drop-in: basta trocar o array DATA do front por um
fetch em /api/conversations.
"""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel


class Message(BaseModel):
    sender: Literal["client", "seller"]
    text: str
    time: str


class ScoreComponent(BaseModel):
    label: str
    points: int


class Order(BaseModel):
    code: Optional[str] = None
    date: Optional[str] = None
    status: Optional[str] = None
    status_kind: Optional[Literal["ok", "go"]] = None   # cor do selo no front
    eta: Optional[str] = None
    tracking: Optional[str] = None
    carrier: Optional[str] = None
    value: Optional[str] = None
    city: Optional[str] = None
    product: Optional[str] = None
    qty: Optional[int] = None
    unit: Optional[str] = None
    stock: Optional[int] = None


class Conversation(BaseModel):
    id: str
    name: str
    initials: str
    contact: str
    phone: str
    cnpj: str = ""
    since: str = ""
    condition: str = ""
    nfs: str = ""
    freight: str = ""
    segment: str = ""
    owner: str = ""                  # vendedor (Owner do Ploomes, já resolvido)
    stage: str = ""                  # estágio do funil (nome)
    stage_id: Optional[int] = None
    pipeline_id: Optional[int] = None
    deal_value: str = ""             # valor do negócio em aberto (formatado)
    tags: list[dict] = []            # tags inteligentes [{l: rótulo, k: tipo}]
    score: list[ScoreComponent] = []
    order: Order = Order()
    orders: list[dict] = []          # lista resumida p/ o painel (c, s, sc, v)
    deals: list[dict] = []           # negócios abertos deste número (id/title/stage/value)
    messages: list[Message] = []
    days_without_purchase: Optional[int] = None
    buy_frequency_days: Optional[int] = None
    days_in_stage: Optional[int] = None      # dias parado no estágio atual do funil
    # metadados de inbox (WhatsApp + leitura)
    awaiting_reply: bool = False
    unread_count: int = 0
    last_preview: str = ""
    last_activity: str = ""
    no_phone: bool = False
    snoozed: bool = False


# ---------------------------------------------------------------------------
# Enriquecimento vindo do Ploomes/Sankhya (pedidos, cotações, perfil, timeline)
# ---------------------------------------------------------------------------
class OrderSummary(BaseModel):
    id: int
    number: Optional[str] = None
    date: Optional[str] = None
    amount: float = 0.0
    amount_fmt: str = ""
    status: str = ""                  # "Status Workflow" do Sankhya (ex.: EM PCP)
    nf: Optional[str] = None          # Nro. Nota
    eta: Optional[str] = None         # Previsão de Entrega
    billing_date: Optional[str] = None  # Data de Faturamento
    freight: Optional[str] = None     # CIF/FOB
    volumes: Optional[int] = None
    history: Optional[str] = None     # Histórico WF (trilha de auditoria)
    payment: str = ""                 # condição de pagamento resumida (parcelas)
    is_open: bool = True
    late: bool = False                # entrega prevista vencida e ainda em aberto
    days_late: int = 0
    items: list[dict] = []
    document_url: Optional[str] = None


class QuoteSummary(BaseModel):
    id: int
    number: Optional[str] = None
    date: Optional[str] = None
    amount: float = 0.0
    amount_fmt: str = ""
    needs_approval: Optional[str] = None     # "Aprovação necessária?"
    discount_validator: Optional[str] = None  # "Validador de desconto"
    eta: Optional[str] = None
    status: Optional[str] = None
    is_open: bool = True
    items: list[dict] = []
    document_url: Optional[str] = None


class ProfileField(BaseModel):
    label: str
    value: str


class ClientProfile(BaseModel):
    contact_id: Optional[int] = None
    name: str = ""
    legal_name: str = ""
    cnpj: str = ""
    status: str = ""                  # "Status do Cliente"
    situation: str = ""               # "Situação"
    days_without_purchase: Optional[int] = None
    buy_frequency_days: Optional[int] = None
    buy_frequency_label: str = ""
    last_quote_date: Optional[str] = None
    segment: str = ""
    partner_code: str = ""            # "Cód. Parceiro (Sankhya)"
    email: str = ""
    nfe_email: str = ""
    state_registration: str = ""
    city: str = ""
    phone: str = ""
    icms_class: str = ""
    fields: list[ProfileField] = []   # extras genéricos do Sankhya


class TimelineItem(BaseModel):
    kind: str = "interaction"         # interaction | whatsapp | note | email | call
    title: str = ""
    content: str = ""
    date: str = ""                    # ISO
    source: str = "ploomes"           # ploomes | neppo


class IntentMatch(BaseModel):
    id: str
    label: str
    confidence: Literal["alta", "média", "baixa"]
    conf: int                         # 0-100, só para a barra visual


class Suggestion(BaseModel):
    intent: IntentMatch
    text: str


# ---------------------------------------------------------------------------
# Serialização para o formato do front protótipo (painel-vendas.html)
# ---------------------------------------------------------------------------
def front_conversation(c: Conversation) -> dict:
    o = c.order
    return {
        "id": c.id, "name": c.name, "initials": c.initials,
        "contact": c.contact, "phone": c.phone, "cnpj": c.cnpj,
        "since": c.since, "condition": c.condition, "nfs": c.nfs,
        "freight": c.freight, "segment": c.segment,
        "owner": c.owner, "stage": c.stage, "stage_id": c.stage_id,
        "pipeline_id": c.pipeline_id, "deal_value": c.deal_value, "tags": c.tags,
        "score": [{"l": s.label, "p": s.points} for s in c.score],
        "order": {
            "code": o.code, "date": o.date, "status": o.status, "st": o.status_kind,
            "eta": o.eta, "tracking": o.tracking, "carrier": o.carrier,
            "value": o.value, "city": o.city, "product": o.product,
            "qty": o.qty, "unit": o.unit, "stock": o.stock,
        },
        "orders": c.orders,
        "deals": c.deals,
        "messages": [{"f": "in" if m.sender == "client" else "out",
                      "t": m.text, "h": m.time} for m in c.messages],
        "inbox": {
            "awaiting": c.awaiting_reply,
            "unread": c.unread_count,
            "preview": c.last_preview,
            "activity": c.last_activity,
            "no_phone": c.no_phone,
            "snoozed": c.snoozed,
        },
    }


def front_suggestion(s: Suggestion) -> dict:
    return {
        "intent": {"id": s.intent.id, "label": s.intent.label,
                   "confidence": s.intent.confidence, "conf": s.intent.conf},
        "text": s.text,
    }
