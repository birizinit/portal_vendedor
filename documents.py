"""Criação GATED de cotações e pedidos no Ploomes.

Fluxo seguro em duas fases (decisão do produto):
  1. PREVIEW (dry_run=True)  -> monta o payload e devolve para revisão; NADA é
     escrito no Ploomes/Sankhya.
  2. CONFIRMAÇÃO (dry_run=False) -> só então faz o POST real.

Documentos do Sankhya costumam exigir campos de cabeçalho (TOP, Natureza,
Empresa...) em OtherProperties. Estes podem ser informados via `extra_fields`
(nome do campo -> valor) e são resolvidos para FieldKey por other_properties.
Comece validando com 1 caso: o preview mostra exatamente o que vai ser enviado.
"""
from __future__ import annotations
from typing import Any, Optional

from pydantic import BaseModel
from config import settings
import other_properties as op


class DocItem(BaseModel):
    product_id: Optional[int] = None
    code: Optional[str] = None
    name: Optional[str] = None
    quantity: float = 1
    unit_price: float = 0.0


class DocRequest(BaseModel):
    conversation_id: str
    kind: str = "quote"                  # "quote" | "order"
    items: list[DocItem] = []
    currency_id: int = 1
    owner_id: Optional[int] = None
    notes: str = ""
    origin_quote_id: Optional[int] = None  # gerar pedido a partir desta cotação
    extra_fields: dict[str, Any] = {}    # {nome do campo Sankhya: valor}
    dry_run: bool = True


def _line_total(it: DocItem) -> float:
    return round((it.quantity or 0) * (it.unit_price or 0), 2)


def build_payload(contact_id: int, req: DocRequest) -> dict:
    """Monta o corpo do POST /Quotes ou /Orders (puro, sem rede)."""
    products = [{
        "ProductId": it.product_id,
        "ProductName": it.name,
        "ProductCode": it.code,
        "Quantity": it.quantity,
        "UnitPrice": it.unit_price,
        "Total": _line_total(it),
    } for it in req.items]

    payload: dict[str, Any] = {
        "ContactId": contact_id,
        "CurrencyId": req.currency_id,
        "Products": products,
    }
    if req.owner_id:
        payload["OwnerId"] = req.owner_id
    if req.notes:
        payload["InternalComments"] = req.notes
    if req.kind == "order" and req.origin_quote_id:
        payload["OriginQuoteId"] = req.origin_quote_id

    # campos customizados (Sankhya) — resolve nome -> FieldKey
    other = []
    for name, value in (req.extra_fields or {}).items():
        item = op.build_other_property(name, value)
        if item is not None:
            other.append(item)
    if other:
        payload["OtherProperties"] = other
    return payload


def preview(contact_id: int, contact_name: str, req: DocRequest) -> dict:
    total = round(sum(_line_total(it) for it in req.items), 2)
    return {
        "kind": req.kind,
        "dry_run": True,
        "contact": {"id": contact_id, "name": contact_name},
        "items": [{
            "code": it.code, "name": it.name, "quantity": it.quantity,
            "unit_price": it.unit_price, "total": _line_total(it),
        } for it in req.items],
        "total": total,
        "total_fmt": f"{total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "payload": build_payload(contact_id, req),
        "warning": "Pré-visualização — nada foi gravado no Ploomes/Sankhya. "
                   "Confirme para criar de verdade.",
    }


async def create(contact_id: int, contact_name: str, req: DocRequest) -> dict:
    """Cria de verdade no Ploomes (só com dry_run=False)."""
    if settings.mock:
        return {"ok": False, "error": "modo mock — defina PLOOMES_API_KEY para criar"}
    if not req.items:
        return {"ok": False, "error": "documento sem itens"}

    from ploomes_client import ploomes
    if ploomes is None:
        return {"ok": False, "error": "Ploomes não configurado"}

    import logging
    payload = build_payload(contact_id, req)
    try:
        if req.kind == "order":
            result = await ploomes.create_order(payload)
        else:
            result = await ploomes.create_quote(payload)
    except Exception as e:  # noqa: BLE001
        logging.getLogger("cortex").error("falha ao criar %s no Ploomes: %s",
                                          req.kind, e)
        return {"ok": False, "error": "falha ao criar o documento no Ploomes"}

    created = (result.get("value") or [result])[0] if isinstance(result, dict) else result
    new_id = created.get("Id") if isinstance(created, dict) else None
    # cache do cliente fica obsoleto após criar
    ploomes.invalidate_contact(int(contact_id))
    return {"ok": True, "kind": req.kind, "id": new_id, "result": created}
