"""API — Carteira do vendedor e campanhas WhatsApp."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import portfolio_db as pdb
import portfolio_sync
import portfolio_templates as ptpl
from config import settings
import deps

log = logging.getLogger("cortex")
router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _owner_id(request: Request, owner_param: int | None = None) -> int:
    u = deps.user(request)
    oid = u.get("owner_id")
    if u.get("role") == "admin" and owner_param:
        return int(owner_param)
    if oid:
        return int(oid)
    if settings.mock:
        return 1
    raise HTTPException(400, "usuário sem owner_id no Ploomes — configure no admin")


@router.get("/stats")
async def portfolio_stats(request: Request, owner_id: int | None = None):
    oid = _owner_id(request, owner_id)
    st = pdb.stats(oid)
    sync = pdb.sync_status(oid)
    return {"stats": st, "sync": sync}


@router.get("/contacts")
async def portfolio_contacts(
    request: Request,
    q: str = "",
    filter: str = "",
    min_days: int | None = None,
    max_days: int | None = None,
    offset: int = 0,
    limit: int = 50,
    owner_id: int | None = None,
):
    oid = _owner_id(request, owner_id)
    lim = min(max(limit, 1), 100)
    items, total = pdb.list_contacts(
        oid, q=q, filter_key=filter,
        min_days=min_days, max_days=max_days,
        offset=offset, limit=lim,
    )
    return {"items": items, "total": total, "offset": offset, "limit": lim,
            "has_more": offset + len(items) < total}


@router.get("/templates")
async def portfolio_templates():
    return {"templates": ptpl.list_templates()}


@router.post("/sync")
async def portfolio_sync_start(request: Request, owner_id: int | None = None):
    oid = _owner_id(request, owner_id)
    if not portfolio_sync.schedule_sync(oid):
        return {"ok": True, "message": "Sincronização já em andamento"}
    return {"ok": True, "message": "Sincronização iniciada"}


class CampaignPreviewIn(BaseModel):
    filter: str = ""
    min_days: int | None = None
    max_days: int | None = None
    template_id: str
    limit: int = Field(default=500, le=2000)


class CampaignStartIn(CampaignPreviewIn):
    confirm: bool = True


@router.post("/campaigns/preview")
async def campaign_preview(payload: CampaignPreviewIn, request: Request):
    oid = _owner_id(request)
    u = deps.user(request)
    tpl = ptpl.get_template(payload.template_id)
    if not tpl:
        raise HTTPException(400, "template inválido")
    items, total = pdb.list_contacts(
        oid, filter_key=payload.filter,
        min_days=payload.min_days, max_days=payload.max_days,
        offset=0, limit=payload.limit,
    )
    with_phone = [r for r in items if (r.get("phone_tail") or "").strip()]
    seller = u.get("name") or "equipe"
    samples = []
    for row in with_phone[:3]:
        ctx = ptpl.build_context(row, seller)
        samples.append({
            "name": row.get("name"),
            "phone": row.get("phone"),
            "message": ptpl.render_message(tpl["body"], ctx),
        })
    return {
        "total_matching": total,
        "with_phone": len(with_phone),
        "will_send": min(len(with_phone), settings.portfolio_campaign_max_per_day),
        "samples": samples,
        "template": tpl,
    }


@router.post("/campaigns")
async def campaign_start(payload: CampaignStartIn, request: Request):
    if not payload.confirm:
        raise HTTPException(400, "confirme a campanha")
    oid = _owner_id(request)
    u = deps.user(request)
    tpl = ptpl.get_template(payload.template_id)
    if not tpl:
        raise HTTPException(400, "template inválido")
    if not settings.neppo_enabled and not settings.mock:
        raise HTTPException(503, "Neppo não configurado — envio indisponível")

    items, _ = pdb.list_contacts(
        oid, filter_key=payload.filter,
        min_days=payload.min_days, max_days=payload.max_days,
        offset=0, limit=payload.limit,
    )
    seller = u.get("name") or "equipe"
    queue: list[dict] = []
    for row in items:
        phone = (row.get("phone") or "").strip()
        if not phone:
            continue
        ctx = ptpl.build_context(row, seller)
        msg = ptpl.render_message(tpl["body"], ctx)
        queue.append({
            "contact_id": row["contact_id"],
            "phone": phone,
            "name": row.get("name") or "",
            "message": msg,
        })
        if len(queue) >= settings.portfolio_campaign_max_per_day:
            break

    if not queue:
        raise HTTPException(400, "nenhum cliente com telefone no filtro")

    cid = pdb.create_campaign(
        owner_id=oid,
        user_id=int(u.get("id") or 0),
        filter_key=payload.filter or "custom",
        template_id=payload.template_id,
        template_body=tpl["body"],
        items=queue,
    )
    return {
        "ok": True,
        "campaign_id": cid,
        "queued": len(queue),
        "message": f"{len(queue)} mensagens na fila (intervalo ~{settings.portfolio_campaign_delay_sec:.0f}s)",
    }


@router.get("/campaigns")
async def campaigns_list(request: Request, owner_id: int | None = None):
    oid = _owner_id(request, owner_id)
    return {"campaigns": pdb.campaigns_list(oid)}


@router.get("/campaigns/{campaign_id}")
async def campaign_detail(campaign_id: int, request: Request):
    oid = _owner_id(request)
    c = pdb.campaign_get(campaign_id, oid)
    if not c:
        raise HTTPException(404, "campanha não encontrada")
    return c
