"""Cache curto para checagem de carteira (vendedor x negócio)."""
from __future__ import annotations

import logging
import time
from typing import Optional

from config import settings

log = logging.getLogger("cortex.access")
_OWN_CACHE_TTL = 60.0
_owns: dict[tuple[int, str], tuple[float, bool]] = {}


def invalidate_owns_cache(conv_id: str = "") -> None:
    if not conv_id:
        _owns.clear()
        return
    cid = str(conv_id)
    for k in list(_owns):
        if k[1] == cid:
            _owns.pop(k, None)


async def seller_owns(owner_id: Optional[int], conv_id: str) -> bool:
    if settings.mock or not owner_id:
        return True
    if not str(conv_id).isdigit():
        return False
    key = (int(owner_id), str(conv_id))
    now = time.monotonic()
    hit = _owns.get(key)
    if hit and now - hit[0] < _OWN_CACHE_TTL:
        return hit[1]
    ok = False
    try:
        from ploomes_client import ploomes
        if ploomes is None:
            ok = False
        else:
            deal = await ploomes.deal_context(int(conv_id))
            ok = deal.get("OwnerId") == owner_id
    except Exception as e:  # noqa: BLE001
        log.warning("checagem de posse falhou (%s): %s — negando", conv_id, e)
        ok = False
    _owns[key] = (now, ok)
    return ok
