"""Camada 2 (parte A) — detecção de intenção por regras.

Sem IA: normaliza o texto (minúsculas, sem acento) e casa contra
conjuntos de palavras-chave por intenção. A intenção de maior pontuação
vence; se nada bate, devolve None (e o sistema não sugere — comportamento
seguro). Para adicionar cobertura, é só editar a lista INTENTS.
"""
from __future__ import annotations
import unicodedata
from typing import Optional
from models import IntentMatch


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


# A ordem importa: intenções mais específicas/urgentes vêm antes para
# desempatar quando há sobreposição de termos (ex.: pós-venda > status).
# Palavras-chave já em forma normalizada (sem acento).
INTENTS: list[dict] = [
    {"id": "pos_venda",       "label": "pós-venda",
     "kw": ["defeito", "amassad", "quebrad", "problema", "reclamac", "troca",
            "devoluc", "errad", "danificad"]},
    {"id": "status_pedido",   "label": "status do pedido",
     "kw": ["cade", "rastreio", "rastreamento", "ja saiu", "saiu", "despachou",
            "enviou", "transportadora", "onde esta", "codigo de rastreio"]},
    {"id": "prazo_entrega",   "label": "prazo de entrega",
     "kw": ["prazo", "entrega", "quando chega", "quando entrega", "previsao",
            "demora", "quantos dias", "chega em"]},
    {"id": "disponibilidade", "label": "disponibilidade",
     "kw": ["tem em estoque", "tem estoque", "disponivel", "pronta entrega",
            "tem o", "tem a", "estoque"]},
    {"id": "negociacao",      "label": "negociação",
     "kw": ["desconto", "melhor preco", "melhor valor", "abaixa", "fechar",
            "negociar", "condicao especial"]},
    {"id": "pagamento",       "label": "condição de pagamento",
     "kw": ["boleto", "pagamento", "parcela", "pix", "a vista", "cartao",
            "faturar", "nota fiscal", "emitir"]},
    {"id": "cotacao_preco",   "label": "cotação / preço",
     "kw": ["quanto custa", "quanto", "valor", "preco", "orcamento", "cotacao",
            "tabela"]},
    {"id": "saudacao",        "label": "abertura",
     "kw": ["bom dia", "boa tarde", "boa noite", "ola", "oi", "tudo bem"]},
]


def detect_intent(text: str) -> Optional[IntentMatch]:
    t = normalize(text)
    best: Optional[dict] = None
    for it in INTENTS:
        hits = 0
        strength = 0
        for k in it["kw"]:
            if k in t:
                hits += 1
                strength += len(k)          # termos mais longos = mais específicos
        if hits == 0:
            continue
        score = hits * 10 + strength
        if best is None or score > best["score"]:
            best = {**it, "hits": hits, "score": score}

    if best is None:
        return None

    if best["hits"] >= 2:
        confidence = "alta"
    elif best["score"] >= 18:
        confidence = "média"
    else:
        confidence = "baixa"

    conf = min(100, 45 + best["score"])     # 0-100, apenas para a barra visual
    return IntentMatch(id=best["id"], label=best["label"],
                       confidence=confidence, conf=conf)
