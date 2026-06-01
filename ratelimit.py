"""Utilidades para conversar com APIs externas sem tomar 429.

- AsyncTokenBucket: respeita o teto de requisições/minuto (o Ploomes
  documenta 120 req/min somando todos os usuários de integração).
- TTLCache: guarda o contexto do cliente por alguns minutos, para não
  reconsultar a API a cada mensagem.
"""
from __future__ import annotations
import asyncio
import time
from typing import Any, Optional


class AsyncTokenBucket:
    def __init__(self, rate_per_min: int):
        self.capacity = float(rate_per_min)
        self.tokens = float(rate_per_min)
        self.refill_per_sec = rate_per_min / 60.0
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self.tokens = min(self.capacity,
                              self.tokens + (now - self.updated) * self.refill_per_sec)
            self.updated = now
            if self.tokens < 1.0:
                wait = (1.0 - self.tokens) / self.refill_per_sec
                await asyncio.sleep(wait)
                self.tokens = 0.0
            else:
                self.tokens -= 1.0


class TTLCache:
    def __init__(self, ttl_seconds: int):
        self.ttl = ttl_seconds
        self._d: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        item = self._d.get(key)
        if item is None:
            return None
        value, expires = item
        if time.monotonic() > expires:
            self._d.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._d[key] = (value, time.monotonic() + self.ttl)

    def invalidate(self, key: str) -> None:
        self._d.pop(key, None)

    def clear(self) -> None:
        self._d.clear()
