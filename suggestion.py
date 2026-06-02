"""Camada 2 (junção) — gera a sugestão para uma conversa.

Pega a última mensagem do cliente, detecta a intenção e preenche o
template correspondente. Se não há mensagem do cliente, ou a intenção não
é identificada com confiança, devolve None — e o front mostra "sem
sugestão automática".
"""
from __future__ import annotations
from typing import Optional
from models import Conversation, IntentMatch, Suggestion
from intents import detect_intent, order_line_count
from templates import fill


def build_suggestion(conv: Conversation) -> Optional[Suggestion]:
    last_in = next((m for m in reversed(conv.messages) if m.sender == "client"), None)
    if last_in is None:
        return None
    # Cliente já mandou itens + quantidades? Isso é um pedido concreto e tem
    # prioridade — não devolvemos a cotação genérica que pede item/quantidade.
    if order_line_count(last_in.text) >= 1:
        text = fill("pedido_itens", conv)
        if text:
            intent = IntentMatch(id="pedido_itens", label="pedido (itens + qtd)",
                                 confidence="alta", conf=92)
            return Suggestion(intent=intent, text=text)
    intent = detect_intent(last_in.text)
    if intent is None or intent.confidence == "baixa":
        return None
    text = fill(intent.id, conv)
    if text is None:
        return None
    return Suggestion(intent=intent, text=text)
