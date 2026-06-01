"""Lógica de inbox — priorização, aguardando resposta, snippets do WhatsApp."""
from __future__ import annotations

import re as _re
from typing import Optional

from models import Conversation
from neppo_client import normalize_phone
from scoring import score_of


def _phone_tail(phone: str) -> str:
    d = normalize_phone(phone)
    return d[-8:] if len(d) >= 8 else d


def _digits_for_conv(c: Conversation) -> str:
    """Telefone normalizado — usa o cadastro ou extrai do nome/título do lead."""
    digits = normalize_phone(c.phone) if c.phone else ""
    if len(digits) >= 10:
        return digits
    for src in (c.contact, c.name):
        m = _re.search(r"(\d{10,13})", str(src or ""))
        if m:
            return normalize_phone(m.group(1))
    return digits


def _preview_from_row(last: dict) -> str:
    txt = (last.get("text") or "").strip()
    if txt:
        return txt[:160]
    if last.get("media"):
        return "📎 Mídia"
    if last.get("direction") == "in":
        return "Nova mensagem do cliente"
    return "Mensagem enviada"


def _crm_snippet(c: Conversation) -> str:
    parts: list[str] = []
    if c.stage:
        parts.append(c.stage.strip())
    if c.deal_value:
        parts.append(f"R$ {c.deal_value}")
    if c.days_without_purchase is not None:
        parts.append(f"{c.days_without_purchase}d sem compra")
    elif c.buy_frequency_days:
        parts.append(f"compra ~cada {c.buy_frequency_days}d")
    return " · ".join(parts)[:160]


def enrich_conversation(c: Conversation, *, user_id: Optional[int] = None) -> None:
    """Preenche metadados de inbox a partir do SQLite (mensagens WhatsApp)."""
    import db

    digits = _digits_for_conv(c)
    c.no_phone = len(digits) < 10

    if user_id and db.is_snoozed(user_id, c.id):
        c.snoozed = True
    else:
        c.snoozed = False

    if digits:
        last = db.last_message_for_phone(digits)
        if last:
            c.last_preview = _preview_from_row(last)
            c.last_activity = str(last.get("ts") or "")
            c.awaiting_reply = last.get("direction") == "in"
        else:
            c.awaiting_reply = False
            c.last_preview = ""
            c.last_activity = ""
    else:
        c.awaiting_reply = False
        c.last_preview = ""
        c.last_activity = ""

    if not (c.last_preview or "").strip():
        c.last_preview = _crm_snippet(c)

    if user_id and digits:
        sig = db.get_seen_sig(user_id, c.id)
        c.unread_count = db.unread_since_sig(digits, sig) if sig else (1 if c.awaiting_reply else 0)
    else:
        c.unread_count = 0


def enrich_all(items: list[Conversation], *, user_id: Optional[int] = None) -> None:
    for c in items:
        enrich_conversation(c, user_id=user_id)


def sort_conversations(items: list[Conversation], mode: str) -> list[Conversation]:
    if mode == "action":
        active = [c for c in items if not c.snoozed]
        waiting = [c for c in active if c.awaiting_reply or c.unread_count > 0]
        rest = [c for c in active if c not in waiting]
        waiting.sort(
            key=lambda c: (c.unread_count, score_of(c)),
            reverse=True,
        )
        rest.sort(key=score_of, reverse=True)
        snoozed = [c for c in items if c.snoozed]
        snoozed.sort(key=lambda c: c.last_activity or "", reverse=True)
        return waiting + rest + snoozed
    if mode == "chrono":
        return sorted(items, key=lambda c: c.last_activity or "", reverse=True)
    return sorted(items, key=score_of, reverse=True)
