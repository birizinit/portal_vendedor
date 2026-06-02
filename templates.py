"""Camada 2 (parte B) — templates de resposta.

Cada intenção tem uma função que recebe a Conversation (com os dados já
buscados do Ploomes/ERP) e devolve o rascunho preenchido. Os marcadores
⟨...⟩ são guard-rails: quando falta dado, o template degrada com elegância
e sinaliza "verificar manualmente" em vez de mandar um campo vazio ou
inventar informação. Nenhuma promessa de preço/prazo sai sem dado de
origem — esse é o motivo de não usarmos LLM aqui.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Callable, Optional
from models import Conversation

from paths import data_dir

_CUSTOM_FILE = data_dir() / "templates_custom.json"


def _first(full: str) -> str:
    return (full or "").split(" ")[0]


def t_status_pedido(c: Conversation) -> str:
    o = c.order
    if o and o.tracking:
        return (f"Bom dia, {_first(c.contact)}! O pedido {o.code} já saiu "
                f"({o.date}) pela {o.carrier}. Previsão de entrega em {o.city}: "
                f"{o.eta}. Rastreio: {o.tracking}.")
    if o and o.status:
        return (f"Bom dia, {_first(c.contact)}! O pedido {o.code} está em "
                f'"{o.status}". Assim que despachar eu te envio o código de '
                f"rastreio. ⟨verificar transportadora⟩")
    return (f"Bom dia, {_first(c.contact)}! Vou verificar o status do seu "
            f"pedido e já te retorno. ⟨pedido não localizado — checar manualmente⟩")


def t_prazo_entrega(c: Conversation) -> str:
    o = c.order
    if o and o.eta and o.eta != "—":
        extra = f". Rastreio: {o.tracking}" if o.tracking else ""
        return (f"Oi, {_first(c.contact)}! Seu pedido {o.code} tem previsão de "
                f"entrega em {o.city} para {o.eta}{extra}.")
    cidade = o.city if (o and o.city) else "sua região"
    return (f"Oi, {_first(c.contact)}! O prazo de entrega para {cidade} é "
            f"calculado no faturamento. Quer que eu confirme com a logística? "
            f"⟨prazo a confirmar⟩")


def t_disponibilidade(c: Conversation) -> str:
    o = c.order
    if o and o.stock is not None:
        return (f"Oi, {_first(c.contact)}! Sim, temos {o.product} em estoque "
                f"({o.stock} un. disponíveis), pronta entrega. Quer que eu já "
                f"monte o orçamento?")
    item = o.product if o else "esse item"
    return (f"Oi, {_first(c.contact)}! Deixa eu confirmar o saldo de {item} no "
            f"estoque e já te falo. ⟨consultar ERP⟩")


def t_pedido_itens(c: Conversation) -> str:
    return (f"Perfeito, {_first(c.contact)}! Recebi seu pedido com os itens e as "
            f"quantidades. Já vou montar o orçamento na sua tabela e te retorno "
            f"com os valores e o prazo de entrega. Confirma que é para o CNPJ/"
            f"endereço de sempre? ⟨conferir itens e montar a cotação⟩")


def t_cotacao_preco(c: Conversation) -> str:
    o = c.order
    if o and o.unit:
        return (f"Olá, {_first(c.contact)}! O {o.product} está R$ {o.unit} a "
                f"unidade na sua tabela. Para qual quantidade você precisa? "
                f"Faço o orçamento na hora.")
    return (f"Olá, {_first(c.contact)}! Me diz o item e a quantidade que eu já "
            f"te passo o valor da sua tabela.")


def t_pagamento(c: Conversation) -> str:
    return (f"Perfeito, {_first(c.contact)}! Vou emitir a nota e te enviar o "
            f"boleto na condição {c.condition}. Confirma o e-mail para envio "
            f"dos documentos?")


def t_negociacao(c: Conversation) -> str:
    o = c.order
    valor = f" de R$ {o.value}" if (o and o.value) else ""
    return (f"{_first(c.contact)}, sobre o valor{valor}: consigo melhorar a "
            f"condição conforme o volume e a forma de pagamento. Se fecharmos "
            f"hoje, vejo a melhor faixa com a gerência. Quanto você precisaria "
            f"pra fechar? ⟨não prometer desconto sem aprovação⟩")


def t_pos_venda(c: Conversation) -> str:
    ped = c.order.code if c.order else ""
    return (f"{_first(c.contact)}, sinto muito pelo ocorrido. Já vou abrir o "
            f"registro da ocorrência do pedido {ped} e acionar a troca. Pode me "
            f"enviar uma foto para agilizar? ⟨abrir ticket de pós-venda⟩")


def t_saudacao(c: Conversation) -> str:
    return f"Olá, {_first(c.contact)}! Tudo bem? Como posso te ajudar hoje?"


TEMPLATES: dict[str, Callable[[Conversation], str]] = {
    "pedido_itens": t_pedido_itens,
    "status_pedido": t_status_pedido,
    "prazo_entrega": t_prazo_entrega,
    "disponibilidade": t_disponibilidade,
    "cotacao_preco": t_cotacao_preco,
    "pagamento": t_pagamento,
    "negociacao": t_negociacao,
    "pos_venda": t_pos_venda,
    "saudacao": t_saudacao,
}


# ---------------------------------------------------------------------------
# Camada editável: o usuário pode sobrescrever o texto de cada intenção por um
# template com {placeholders}. Se houver override, ele tem prioridade; senão
# usa a função codada (que degrada com elegância quando falta dado).
# ---------------------------------------------------------------------------

# Versão estática (com placeholders) mostrada no editor como ponto de partida.
DEFAULT_TEMPLATES: dict[str, str] = {
    "pedido_itens": "Perfeito, {contato}! Recebi seu pedido com os itens e "
                    "quantidades. Já monto o orçamento na sua tabela e retorno "
                    "com valores e prazo. Confirma o CNPJ/endereço de sempre?",
    "status_pedido": "Oi, {contato}! O pedido {pedido} está em \"{status}\". "
                     "Previsão de entrega em {cidade}: {entrega}. Rastreio: {rastreio}.",
    "prazo_entrega": "Oi, {contato}! Seu pedido {pedido} tem previsão de entrega "
                     "em {cidade} para {entrega}.",
    "disponibilidade": "Oi, {contato}! Sobre {produto}: já confirmo o saldo em "
                       "estoque e te falo. Quer que eu monte o orçamento?",
    "cotacao_preco": "Olá, {contato}! O {produto} está R$ {unitario} a unidade na "
                     "sua tabela. Para qual quantidade você precisa?",
    "pagamento": "Perfeito, {contato}! Emito a nota e te envio o boleto na condição "
                 "{condicao}. Confirma o e-mail para envio?",
    "negociacao": "{contato}, sobre o valor de R$ {valor}: consigo melhorar conforme "
                  "volume e forma de pagamento. Quanto precisaria pra fechar?",
    "pos_venda": "{contato}, sinto muito pelo ocorrido. Já abro a ocorrência do pedido "
                 "{pedido} e aciono a troca. Pode me enviar uma foto?",
    "saudacao": "Olá, {contato}! Tudo bem? Como posso te ajudar hoje?",
}


class _SafeDict(dict):
    def __missing__(self, key):    # placeholder sem dado vira "—" em vez de erro
        return "⟨—⟩"


def _context(conv: Conversation) -> dict:
    o = conv.order
    return _SafeDict({
        "contato": _first(conv.contact), "empresa": conv.name,
        "pedido": o.code or "", "status": o.status or "",
        "entrega": o.eta or "", "rastreio": o.tracking or "",
        "transportadora": o.carrier or "", "cidade": o.city or "",
        "produto": o.product or "", "unitario": o.unit or "",
        "valor": o.value or "", "condicao": conv.condition or "",
        "estoque": str(o.stock) if o.stock is not None else "",
    })


def load_custom() -> dict[str, str]:
    if _CUSTOM_FILE.exists():
        try:
            return json.loads(_CUSTOM_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_custom(intent_id: str, text: str) -> None:
    data = load_custom()
    if text and text.strip():
        data[intent_id] = text
    else:
        data.pop(intent_id, None)   # texto vazio = volta ao padrão
    _CUSTOM_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                            encoding="utf-8")


def render_custom(text: str, conv: Conversation) -> str:
    try:
        return text.format_map(_context(conv))
    except (ValueError, KeyError, IndexError):
        return text


def fill(intent_id: str, conv: Conversation) -> Optional[str]:
    custom = load_custom().get(intent_id)
    if custom:
        return render_custom(custom, conv)
    fn = TEMPLATES.get(intent_id)
    if fn:
        return fn(conv)
    default = DEFAULT_TEMPLATES.get(intent_id)
    return render_custom(default, conv) if default else None
