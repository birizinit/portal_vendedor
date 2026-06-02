"""Camada 2 (parte A) — detecção de intenção por regras.

Sem IA: normaliza o texto (minúsculas, sem acento) e casa contra
conjuntos de palavras-chave por intenção. A intenção de maior pontuação
vence; se nada bate, devolve None (e o sistema não sugere — comportamento
seguro). Para adicionar cobertura, é só editar a lista INTENTS.
"""
from __future__ import annotations
import re
import unicodedata
from typing import Optional
from models import IntentMatch


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


# Linhas de pedido: "60 unid", "10 un", "2 cx", "500 peças", "3x"... — note que
# "20 litros" NÃO casa (litro é especificação do produto, não quantidade).
_ORDER_ITEM_RE = re.compile(
    r"(\d+)\s*(un(?:id(?:ades?)?|d)?|pc|p[cç]|pe[cç]as?|caixas?|cx|fardos?|"
    r"pallets?|paletes?|milheiros?|d[uú]zias?|[xX])\b",
    re.IGNORECASE,
)

# conectores/ruído que sobram entre a quantidade e a descrição
_DESC_STOP = {"e", "de", "da", "do", "com", "mais", "x", ""}


def order_line_count(text: str) -> int:
    """Quantas linhas de pedido (quantidade + unidade) há no texto.

    >0 indica que o cliente JÁ informou item e quantidade — então não faz
    sentido perguntar de novo."""
    if not text:
        return 0
    return len(_ORDER_ITEM_RE.findall(text))


def parse_order(text: str) -> list[dict]:
    """Quebra um pedido em itens: [{quantity, unit, description}].

    Assume o padrão dominante 'QTD UNIDADE descrição' (ex.: '60 unid. Lixeira
    20 litros azul'). A descrição de cada item vai do fim da unidade até a
    próxima quantidade. Não inventa preço — isso é resolvido depois contra o
    catálogo do Ploomes."""
    if not text:
        return []
    matches = list(_ORDER_ITEM_RE.finditer(text))
    items: list[dict] = []
    for i, m in enumerate(matches):
        try:
            qty = int(m.group(1))
        except ValueError:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        desc = text[start:end].strip(" \t\r\n.,;:-–—|/")
        # tira conector inicial ("e", "de"...) que sobra entre itens
        while True:
            head = desc.split(" ", 1)
            if len(head) == 2 and head[0].lower() in _DESC_STOP:
                desc = head[1].strip()
            else:
                break
        if desc and desc.lower() not in _DESC_STOP:
            items.append({"quantity": qty, "unit": m.group(2).lower(),
                          "description": desc})
    return items


# A ordem importa: intenções mais específicas/urgentes vêm antes para
# desempatar quando há sobreposição de termos (ex.: pós-venda > status).
# Palavras-chave já em forma normalizada (sem acento).
INTENTS: list[dict] = [
    # detectado por padrão (order_line_count), não por palavra-chave — kw vazio
    # garante que apareça no editor de templates sem nunca casar por keyword.
    {"id": "pedido_itens",    "label": "pedido (itens + qtd)", "kw": []},
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
