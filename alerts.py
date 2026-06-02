"""Alertas proativos — transforma a lista de conversas (já enriquecida) em uma
fila de "o que precisa de ação agora", sem nenhuma chamada extra ao Ploomes.

Tipos:
  - sla          : cliente aguardando resposta há tempo demais
  - reactivation : passou do ciclo habitual de compra (RFM) — risco de esfriar
  - stale_deal   : negócio parado no mesmo estágio do funil há muitos dias

O cálculo usa só campos que a Conversation já carrega (last_activity,
awaiting_reply, days_without_purchase, buy_frequency_days, days_in_stage).
"""
from __future__ import annotations
import datetime as _dt
from typing import Optional

from models import Conversation


def _minutes_since(iso: str, now: Optional[_dt.datetime] = None) -> Optional[float]:
    """Minutos decorridos desde um timestamp ISO. Tolera valor com ou sem
    timezone (webhook grava naive local; backfill pode trazer com offset)."""
    s = (iso or "").strip()
    if not s:
        return None
    try:
        d = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is not None:
        ref = now if (now and now.tzinfo) else _dt.datetime.now(_dt.timezone.utc)
        d = d.astimezone(ref.tzinfo)
    else:
        ref = now if (now and now.tzinfo is None) else _dt.datetime.now()
    delta = (ref - d).total_seconds() / 60.0
    return delta if delta >= 0 else 0.0


def _fmt_dur(minutes: float) -> str:
    m = int(round(minutes))
    if m < 60:
        return f"{m} min"
    h, rest = divmod(m, 60)
    if h < 24:
        return f"{h}h{rest:02d}" if rest else f"{h}h"
    d = h // 24
    return f"{d}d"


def build_alerts(items: list[Conversation], *, sla_minutes: int = 15,
                 reactivation_factor: float = 1.3, stale_deal_days: int = 7,
                 now: Optional[_dt.datetime] = None) -> dict:
    """Lista de alertas priorizada a partir das conversas já carregadas."""
    out: list[dict] = []
    for c in items:
        if getattr(c, "snoozed", False):
            continue

        # 1) SLA — aguardando resposta do cliente há tempo demais
        if c.awaiting_reply and c.last_activity:
            mins = _minutes_since(c.last_activity, now)
            if mins is not None and mins >= sla_minutes:
                out.append({
                    "kind": "sla",
                    "severity": "high" if mins >= sla_minutes * 3 else "med",
                    "conv_id": c.id, "name": c.name,
                    "title": f"Aguardando resposta há {_fmt_dur(mins)}",
                    "detail": (c.last_preview or "").strip()[:120],
                    "minutes": round(mins),
                    "score": _score_of(c),
                })

        # 2) Reativação — passou do ciclo habitual de compra
        if c.days_without_purchase is not None and c.buy_frequency_days:
            ratio = c.days_without_purchase / c.buy_frequency_days
            if ratio >= reactivation_factor:
                out.append({
                    "kind": "reactivation",
                    "severity": "high" if ratio >= 2 else "med",
                    "conv_id": c.id, "name": c.name,
                    "title": (f"{c.days_without_purchase} dias sem comprar "
                              f"(costuma comprar a cada ~{c.buy_frequency_days}d)"),
                    "detail": "Cliente pode estar esfriando — vale um contato.",
                    "ratio": round(ratio, 2),
                    "score": _score_of(c),
                })

        # 3) Negócio parado no estágio
        if c.days_in_stage is not None and c.days_in_stage >= stale_deal_days:
            out.append({
                "kind": "stale_deal",
                "severity": "high" if c.days_in_stage >= stale_deal_days * 2 else "med",
                "conv_id": c.id, "name": c.name,
                "title": f"Parado em \"{c.stage or 'estágio'}\" há {c.days_in_stage} dias",
                "detail": (f"R$ {c.deal_value}" if c.deal_value else
                           "Negócio sem movimentação."),
                "days": c.days_in_stage,
                "score": _score_of(c),
            })

    _SEV = {"high": 0, "med": 1}
    out.sort(key=lambda a: (_SEV.get(a["severity"], 2), -(a.get("score") or 0)))
    by_kind: dict[str, int] = {}
    for a in out:
        by_kind[a["kind"]] = by_kind.get(a["kind"], 0) + 1
    return {"alerts": out, "count": len(out), "by_kind": by_kind}


def _score_of(c: Conversation) -> int:
    try:
        from scoring import score_of
        return score_of(c)
    except Exception:  # noqa: BLE001
        return 0
