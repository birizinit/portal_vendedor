"""Camada 1 — motor de score (heurístico, com pesos).

Hoje é uma soma ponderada dos fatores que já vêm preenchidos em
Conversation.score. No produto real, é aqui que você monta os componentes
a partir dos dados do Ploomes (valor do orçamento aberto, recorrência,
estágio do funil, dias sem resposta, histórico de pagamento) — veja
build_score_components() como ponto de partida.
"""
from __future__ import annotations
from models import Conversation, ScoreComponent


def score_of(conv: Conversation) -> int:
    return max(0, min(100, sum(s.points for s in conv.score)))


def score_level(value: int) -> str:
    if value >= 60:
        return "Prioridade alta"
    if value >= 30:
        return "Prioridade média"
    return "Prioridade baixa"


def score_kind(value: int) -> str:
    """Classe de cor usada no front: hi / mid / lo."""
    if value >= 60:
        return "hi"
    if value >= 30:
        return "mid"
    return "lo"


# ---------------------------------------------------------------------------
# Esqueleto para o cálculo real a partir de dados crus do Ploomes.
# Ajuste os pesos olhando seus resultados (a Camada 4 te dá esse feedback).
# ---------------------------------------------------------------------------
import unicodedata


def _norm(s) -> str:
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


# Pesos do score real — ajuste aqui para calibrar a priorização.
_STAGE_PTS = [("fechamento", 24), ("negocia", 18), ("amostra", 16),
              ("credito", 14), ("orcamento", 12), ("proposta", 12),
              ("cotac", 12), ("carrinho", 8)]


def build_score_real(*, open_value: float, stage: str, client_status: str,
                     days_no_purchase, buy_frequency: str) -> list[ScoreComponent]:
    """Score a partir dos sinais reais do cliente (sem chamadas extras).

    Combina: valor do negócio aberto, estágio do funil, status do cliente,
    recência (dias sem compra) e frequência de compra. Resultado clampado em
    0–100 por score_of. Componentes podem ser negativos (cliente esfriando).
    """
    comps: list[ScoreComponent] = []

    pts = min(30, round((open_value or 0) / 800))
    if open_value:
        comps.append(ScoreComponent(
            label=f"Orçamento aberto R$ {open_value:,.0f}".replace(",", "."), points=pts))
    else:
        comps.append(ScoreComponent(label="Sem orçamento aberto", points=0))

    st = _norm(stage)
    stage_pts = next((p for k, p in _STAGE_PTS if k in st), 6)
    comps.append(ScoreComponent(label=f"Estágio: {stage or '—'}", points=stage_pts))

    cs = _norm(client_status)
    if "inativ" in cs:
        sp = -10
    elif "ativ" in cs:
        sp = 16
    elif "lead" in cs:
        sp = 8
    else:
        sp = 4
    if client_status:
        comps.append(ScoreComponent(label=f"Cliente {client_status}", points=sp))

    if days_no_purchase is not None:
        d = int(days_no_purchase)
        if d <= 15:
            rp, rl = 14, "Comprou nos últimos 15 dias"
        elif d <= 45:
            rp, rl = 6, f"{d} dias sem comprar"
        elif d <= 90:
            rp, rl = 0, f"{d} dias sem comprar"
        elif d <= 180:
            rp, rl = -6, f"{d} dias sem comprar"
        else:
            rp, rl = -12, f"Inativo há {d} dias"
        comps.append(ScoreComponent(label=rl, points=rp))

    fr = _norm(buy_frequency)
    fp = 10 if "semanal" in fr else 7 if "quinzenal" in fr else 4 if "mensal" in fr else 0
    if fp:
        comps.append(ScoreComponent(label=f"Compra {buy_frequency}", points=fp))

    return comps


def build_score_components(*, open_quote_value: float, is_recurring: bool,
                           funnel_stage: str, days_without_reply: int,
                           good_payer: bool) -> list[ScoreComponent]:
    comps: list[ScoreComponent] = []

    # valor do orçamento aberto — peso alto, com teto
    pts = min(34, round(open_quote_value / 700))
    comps.append(ScoreComponent(label=f"Orçamento aberto R$ {open_quote_value:,.0f}".replace(",", "."),
                                points=pts))

    comps.append(ScoreComponent(label="Cliente recorrente" if is_recurring else "Cliente novo",
                                points=20 if is_recurring else 8))

    stage_pts = {"fechamento": 24, "negociacao": 15, "proposta": 12,
                 "primeiro contato": 6, "pos-venda": 6}.get(funnel_stage, 6)
    comps.append(ScoreComponent(label=f"Estágio: {funnel_stage}", points=stage_pts))

    reply_pts = max(0, 7 - days_without_reply * 3)
    label = ("0 dias sem resposta" if days_without_reply == 0
             else f"{days_without_reply} dia(s) sem resposta")
    comps.append(ScoreComponent(label=label, points=reply_pts))

    if good_payer:
        comps.append(ScoreComponent(label="Bom histórico de pagamento", points=6))

    return comps
