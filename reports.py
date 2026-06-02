"""Relatório semanal (CSV ou JSON) — feedback e uso de templates."""
from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Any, Optional

import db


def _week_start() -> dt.datetime:
    now = dt.datetime.now(dt.timezone.utc)
    return (now - dt.timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )


def build_weekly_report(
    user_id: Optional[int] = None,
    *,
    as_csv: bool = False,
) -> Any:
    start = _week_start()
    iso_from = start.isoformat()
    feedback = db.feedback_since(iso_from, user_id)
    stats = db.feedback_stats()
    period = db.current_period()
    goal = db.get_goal(user_id, period) if user_id else None

    payload = {
        "period_label": f"Semana desde {start.date().isoformat()}",
        "goal_period": period,
        "goal_target": goal,
        "feedback_rows": len(feedback),
        "feedback_by_action": {r["action"]: r["n"] for r in stats},
        "feedback": feedback[:500],
        "messages_in_db": db.message_count(),
    }
    if not as_csv:
        return payload

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["tipo", "intent_id", "conversation_id", "at", "user_id"])
    for row in feedback:
        w.writerow([
            row.get("action"), row.get("intent_id"),
            row.get("conversation_id"), row.get("at"), row.get("user_id", ""),
        ])
    return buf.getvalue()
