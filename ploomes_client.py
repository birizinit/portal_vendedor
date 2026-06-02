"""Cliente do Ploomes (CRM).

A API do Ploomes é REST/OData v4, autenticada por uma chave no header
'User-Key'. Aqui ficam as chamadas que alimentam o painel — leituras de
Deals/Orders/Quotes/Contacts/Products/InteractionRecords e a criação
(gated) de cotações e pedidos. Tudo passa pelo rate limiter (120 req/min)
e por um cache TTL para não reconsultar o mesmo cliente a cada mensagem.

Os campos CUSTOMIZADOS (Sankhya) vêm em OtherProperties e são resolvidos
por other_properties.catalog (mapa FieldKey -> Nome). Doc oficial:
https://developers.ploomes.com/
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any, Optional

import httpx

from config import settings
from ratelimit import AsyncTokenBucket, TTLCache

log = logging.getLogger("cortex.ploomes")
_RETRY_STATUS = {429, 500, 502, 503, 504}
from other_properties import catalog


class PloomesClient:
    def __init__(self) -> None:
        self._bucket = AsyncTokenBucket(settings.ploomes_rate_limit_per_min)
        self._cache = TTLCache(settings.ploomes_cache_ttl)
        self._list_cache = TTLCache(45)   # lista de negócios: cache curto
        self._client = httpx.AsyncClient(
            base_url=settings.ploomes_base_url,
            headers={"User-Key": settings.ploomes_api_key},
            timeout=20.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kw) -> Any:
        """GET/POST com rate-limit + retry/backoff em 429/5xx e erros de rede."""
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            await self._bucket.acquire()
            try:
                resp = await self._client.request(method, path, **kw)
                if resp.status_code in _RETRY_STATUS and attempt < 2:
                    wait = 0.6 * (attempt + 1)
                    log.warning("Ploomes %s %s -> %s, retry em %.1fs",
                                method, path, resp.status_code, wait)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json() if resp.content else {}
            except httpx.TransportError as e:
                last_exc = e
                if attempt < 2:
                    await asyncio.sleep(0.6 * (attempt + 1))
                    continue
                log.error("Ploomes %s %s falhou (rede): %s", method, path, e)
                raise
        if last_exc:
            raise last_exc

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        return await self._request("GET", path, params=params)

    async def _post(self, path: str, body: dict) -> Any:
        return await self._request("POST", path, json=body)

    # -- catálogo de campos customizados ------------------------------------

    async def refresh_fields(self) -> int:
        """Recarrega o mapa FieldKey->Nome da API (paginado) e persiste o cache."""
        names: dict[str, str] = {}
        skip = 0
        while True:
            data = await self._get("/Fields", params={
                "$top": 300, "$skip": skip, "$select": "Key,Name",
            })
            rows = data.get("value", [])
            if not rows:
                break
            for f in rows:
                if f.get("Key"):
                    names[f["Key"]] = f.get("Name") or f["Key"]
            skip += len(rows)
            if len(rows) < 300:
                break
        if names:
            catalog.replace(names)
            catalog.persist()
        return len(names)

    # -- leituras de alto nível ---------------------------------------------

    async def open_deals(self, top: int = 50, day: Optional[str] = None,
                         owner_id: Optional[int] = None) -> list[dict]:
        """Negócios em aberto, base da lista de atendimentos.

        `day` (YYYY-MM-DD) filtra por data de criação; `owner_id` restringe à
        carteira de um vendedor (usado quando o login é de papel 'seller').
        """
        cache_key = f"deals:{top}:{day}:{owner_id}"
        cached = self._list_cache.get(cache_key)
        if cached is not None:
            return cached
        flt = "StatusId eq 1"             # 1 = aberto
        order = "LastUpdateDate desc"
        if owner_id:
            flt += f" and OwnerId eq {int(owner_id)}"
        if day:
            import datetime as _dt
            nxt = (_dt.date.fromisoformat(day) + _dt.timedelta(days=1)).isoformat()
            flt += (f" and CreateDate ge {day}T00:00:00-03:00"
                    f" and CreateDate lt {nxt}T00:00:00-03:00")
            order = "CreateDate desc"
        data = await self._get("/Deals", params={
            "$top": top,
            "$orderby": order,
            # expand aninhado: traz vendedor (Owner), estágio e os campos
            # Sankhya do contato (status, dias sem compra) numa requisição só.
            "$expand": "Stage,Owner,Contact($expand=OtherProperties,Owner,Phones)",
            "$filter": flt,
        })
        rows = data.get("value", [])
        self._list_cache.set(cache_key, rows)
        return rows

    async def deal_context(self, deal_id: int) -> dict:
        key = f"deal:{deal_id}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        data = await self._get(f"/Deals", params={
            "$filter": f"Id eq {deal_id}",
            "$expand": "Contact,Stage,OtherProperties",
            "$top": 1,
        })
        deal = (data.get("value") or [{}])[0]
        self._cache.set(key, deal)
        return deal

    async def contact(self, contact_id: int) -> dict:
        """Cadastro completo do cliente + OtherProperties (Sankhya), com cache."""
        key = f"contact:{contact_id}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        data = await self._get("/Contacts", params={
            "$filter": f"Id eq {contact_id}",
            "$expand": "OtherProperties,Phones,City,State",
            "$top": 1,
        })
        ct = (data.get("value") or [{}])[0]
        self._cache.set(key, ct)
        return ct

    async def contact_by_phone(self, phone: str) -> Optional[dict]:
        """Procura um contato cadastrado pelo telefone (últimos 8 dígitos).

        Usado para descobrir que um 'lead sem cadastro' do WhatsApp na verdade
        já é um cliente no Ploomes (só sem negócio aberto). Cache positivo e
        negativo para não repetir a busca a cada aba aberta."""
        digits = "".join(ch for ch in (phone or "") if ch.isdigit())
        if len(digits) < 8:
            return None
        tail = digits[-8:]
        key = f"contact_phone:{tail}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached or None
        contact = None
        try:
            data = await self._get("/Contacts", params={
                "$filter": f"Phones/any(p: contains(p/PhoneNumber,'{tail}'))",
                "$expand": "OtherProperties,Phones,City,State",
                "$top": 1,
            })
            contact = (data.get("value") or [None])[0]
        except Exception as e:  # noqa: BLE001  — falha não derruba o fluxo
            log.warning("busca de contato por telefone falhou (%s): %s", tail, e)
            contact = None
        self._cache.set(key, contact or {})   # cacheia também o "não achou"
        return contact or None

    async def orders_for_contact(self, contact_id: int, top: int = 20) -> list[dict]:
        key = f"orders:{contact_id}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        data = await self._get("/Orders", params={
            "$filter": f"ContactId eq {contact_id}",
            "$orderby": "Date desc",
            "$expand": "OtherProperties,Products",
            "$top": top,
        })
        rows = data.get("value", [])
        self._cache.set(key, rows)
        return rows

    async def quotes_for_contact(self, contact_id: int, top: int = 20) -> list[dict]:
        key = f"quotes:{contact_id}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        data = await self._get("/Quotes", params={
            "$filter": f"ContactId eq {contact_id} and LastReview eq true",
            "$orderby": "Date desc",
            "$expand": "OtherProperties,Products",
            "$top": top,
        })
        rows = data.get("value", [])
        self._cache.set(key, rows)
        return rows

    async def interactions_for_contact(self, contact_id: int, top: int = 30) -> list[dict]:
        data = await self._get("/InteractionRecords", params={
            "$filter": f"ContactId eq {contact_id}",
            "$orderby": "Date desc",
            "$expand": "OtherProperties",   # traz dados de sessão do Neppo
            "$top": top,
        })
        return data.get("value", [])

    async def search_products(self, term: str, top: int = 10) -> list[dict]:
        """Busca produto por código ou nome (para montar cotação/pedido).

        Obs.: nesta conta o campo StockBalance não é exposto (403); usamos
        UnitPrice como preço de referência e não trazemos saldo em estoque.
        """
        safe = term.replace("'", "''")
        flt = f"Code eq '{safe}'" if safe.isdigit() else f"contains(Name,'{safe}')"
        data = await self._get("/Products", params={
            "$filter": flt,
            "$select": "Id,Code,Name,UnitPrice,MeasurementUnit",
            "$top": top,
        })
        return data.get("value", [])

    async def product_stock(self, product_code: str) -> Optional[int]:
        """Saldo em estoque — indisponível nesta conta (StockBalance é 403)."""
        return None

    def invalidate_deal(self, deal_id: int) -> None:
        self._cache.invalidate(f"deal:{deal_id}")

    def invalidate_contact(self, contact_id: int) -> None:
        for prefix in ("contact", "orders", "quotes"):
            self._cache.invalidate(f"{prefix}:{contact_id}")

    # -- escrita (GATED) ----------------------------------------------------

    async def create_quote(self, payload: dict) -> dict:
        """Cria uma cotação no Ploomes. Use só após preview/confirmação."""
        return await self._post("/Quotes", payload)

    async def create_order(self, payload: dict) -> dict:
        """Cria um pedido no Ploomes. Use só após preview/confirmação."""
        return await self._post("/Orders", payload)

    async def create_interaction(self, payload: dict) -> dict:
        """Registra uma interação (anotação/ligação/WhatsApp) no CRM."""
        return await self._post("/InteractionRecords", payload)

    async def create_contact(self, payload: dict) -> dict:
        """Cria um contato (cliente) — usado quando um lead de WhatsApp ainda
        não existe no Ploomes e vamos abrir um negócio pra ele."""
        return await self._post("/Contacts", payload)

    async def create_deal(self, payload: dict) -> dict:
        """Cria um negócio (deal). Use só após preview/confirmação."""
        return await self._post("/Deals", payload)

    async def pipelines(self) -> list[dict]:
        """Funis (pipelines) com cache — p/ achar 'Entradas e Prospecção'."""
        cached = self._cache.get("pipelines")
        if cached is not None:
            return cached
        data = await self._get("/Deals@Pipelines", params={
            "$select": "Id,Name", "$top": 200,
        })
        rows = data.get("value", [])
        self._cache.set("pipelines", rows)
        return rows

    async def stages(self) -> list[dict]:
        """Estágios do funil (todos os pipelines), com cache."""
        cached = self._cache.get("stages")
        if cached is not None:
            return cached
        data = await self._get("/Deals@Stages", params={
            "$select": "Id,Name,PipelineId,Ordination",
            "$orderby": "PipelineId,Ordination", "$top": 200,
        })
        rows = data.get("value", [])
        self._cache.set("stages", rows)
        return rows

    async def users(self) -> list[dict]:
        """Usuários (vendedores) para atribuição, com cache."""
        cached = self._cache.get("users")
        if cached is not None:
            return cached
        out: list[dict] = []
        skip = 0
        while True:
            data = await self._get("/Users", params={
                "$select": "Id,Name,Email", "$top": 300, "$skip": skip,
            })
            rows = data.get("value", [])
            if not rows:
                break
            out.extend(rows)
            skip += len(rows)
            if len(rows) < 300:
                break
        self._cache.set("users", out)
        return out

    async def neppo_agent_map(self) -> dict:
        """Mapa vendedor (Ploomes) <-> agente (Neppo), lido do campo customizado
        'Id do usuário (Neppo)' na entidade User. Cacheado.

        Retorna {"by_agent": {neppo_id: {id,name}}, "by_user": {user_id: neppo_id},
        "field_key": <key>, "linked": <n>}.
        """
        cached = self._cache.get("neppo_agents")
        if cached is not None:
            return cached
        from other_properties import catalog, value_by_key
        key = catalog.find_key("id do usu", "neppo")   # "Id do usuário (Neppo)"
        out: dict = {"by_agent": {}, "by_user": {}, "field_key": key, "linked": 0}
        if not key:
            log.warning("campo 'Id do usuário (Neppo)' não encontrado no catálogo")
            self._cache.set("neppo_agents", out)
            return out
        skip = 0
        while True:
            data = await self._get("/Users", params={
                "$expand": "OtherProperties", "$top": 300, "$skip": skip,
            })
            rows = data.get("value", [])
            if not rows:
                break
            for u in rows:
                raw = value_by_key(u, key)
                try:
                    aid = int(raw) if raw is not None else None
                except (TypeError, ValueError):
                    aid = None
                if aid is not None:
                    out["by_agent"][str(aid)] = {"id": u.get("Id"), "name": u.get("Name")}
                    out["by_user"][str(u.get("Id"))] = aid
            skip += len(rows)
            if len(rows) < 300:
                break
        out["linked"] = len(out["by_agent"])
        self._cache.set("neppo_agents", out)
        return out

    async def update_deal(self, deal_id: int, patch: dict) -> Any:
        """PATCH em um negócio (mover estágio, trocar vendedor...)."""
        await self._bucket.acquire()
        resp = await self._client.patch(f"/Deals({deal_id})", json=patch)
        resp.raise_for_status()
        self.invalidate_deal(deal_id)
        self._list_cache.clear()   # a lista muda (estágio/vendedor)
        return resp.json() if resp.content else {"ok": True}


# instância única — só com chave real (sem mock automático)
ploomes: Optional[PloomesClient] = (
    PloomesClient() if settings.ploomes_configured and not settings.mock else None
)
