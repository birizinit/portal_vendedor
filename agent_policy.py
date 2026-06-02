"""Políticas do assistente noturno — horário, limites e sanitização."""
from __future__ import annotations

import datetime as _dt
import re
from typing import Optional
from zoneinfo import ZoneInfo

from config import settings

_MONEY_RE = re.compile(
    r"(R\$\s*\d|reais\b|\b\d{1,3}(?:\.\d{3})*,\d{2}\b|\borçamento\b.*\d|"
    r"\d+\s*%\s*de\s*desconto|preço\s*:?\s*\d)",
    re.IGNORECASE,
)
_ESCALATE_RE = re.compile(
    r"(gerente|supervisor|advogad|processo|cancel|reclama|procon|"
    r"desconto|mais\s+barat|abaixo\s+do)",
    re.IGNORECASE,
)

_INTRO = (
    "Olá! Sou o assistente virtual da Lar Plásticos. "
    "Nosso time comercial retorna no horário comercial de amanhã. "
    "Posso anotar sua necessidade enquanto isso."
)
_SAFE_PRICE = (
    "Para valores e condições comerciais, nosso consultor te atende amanhã "
    "com a proposta certinha. Me conta qual produto e quantidade você precisa?"
)


def tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.night_tz)
    except Exception:
        return ZoneInfo("America/Sao_Paulo")


def _parse_hm(s: str) -> tuple[int, int]:
    parts = (s or "0:0").strip().split(":")
    h = int(parts[0]) if parts else 0
    m = int(parts[1]) if len(parts) > 1 else 0
    return h, m


def is_night_window(now: Optional[_dt.datetime] = None) -> bool:
    """Janela noturna: a partir de 18:10 até 07:00 (horário de Brasília)."""
    ref = now or _dt.datetime.now(tz())
    sh, sm = _parse_hm(settings.night_start)
    eh, em = _parse_hm(settings.night_end)
    cur = ref.hour * 60 + ref.minute
    start = sh * 60 + sm
    end = eh * 60 + em
    if start > end:
        return cur >= start or cur < end
    return start <= cur < end


def night_session_start(now: Optional[_dt.datetime] = None) -> _dt.datetime:
    """Início da sessão noturna corrente (para contar replies)."""
    ref = now or _dt.datetime.now(tz())
    sh, sm = _parse_hm(settings.night_start)
    eh, em = _parse_hm(settings.night_end)
    cur = ref.hour * 60 + ref.minute
    start = sh * 60 + sm
    boundary = ref.replace(hour=sh, minute=sm, second=0, microsecond=0)
    if cur >= start:
        return boundary
    return boundary - _dt.timedelta(days=1)


def needs_escalation(client_text: str) -> bool:
    return bool(_ESCALATE_RE.search(client_text or ""))


def sanitize_reply(text: str) -> tuple[str, bool]:
    """Remove violações de preço; retorna (texto, foi_bloqueado)."""
    t = (text or "").strip()
    if not t:
        return _SAFE_PRICE, True
    if _MONEY_RE.search(t):
        return _SAFE_PRICE, True
    return t[:1200], False


def intro_message() -> str:
    return _INTRO


def escalation_reply() -> str:
    return (
        "Entendi sua solicitação. Vou registrar para nosso time comercial "
        "priorizar amanhã no primeiro horário. Obrigado pela paciência!"
    )
