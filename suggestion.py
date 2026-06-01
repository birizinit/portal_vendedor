"""Camada 2 (junção) — gera a sugestão para uma conversa.

Pega a última mensagem do cliente, detecta a intenção e preenche o
template correspondente. Se não há mensagem do cliente, ou a intenção não
é identificada com confiança, devolve None — e o front mostra "sem
sugestão automática".
"""
from __future__ import annotations
from typing import Optional
from models import Conversation, Suggestion
from intents import detect_intent
from templates import fill


def build_suggestion(conv: Conversation) -> Optional[Suggestion]:
    last_in = next((m for m in reversed(conv.messages) if m.sender == "client"), None)
    if last_in is None:
        return None
    intent = detect_intent(last_in.text)
    if intent is None or intent.confidence == "baixa":
        return None
    text = fill(intent.id, conv)
    if text is None:
        return None
    return Suggestion(intent=intent, text=text)
