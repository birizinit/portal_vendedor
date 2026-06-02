"""Orquestrador do assistente noturno — pós-webhook."""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Optional

import db
import repository as repo
from agent_playbook import build_prompt
from agent_policy import (
    escalation_reply,
    intro_message,
    is_night_window,
    needs_escalation,
    night_session_start,
    sanitize_reply,
)
from config import settings
import deps

log = logging.getLogger("cortex.agent")


async def _publish_agent(event: dict) -> None:
    await deps.publish({"type": "agent", **event})


async def _light_context(conv_id: str) -> dict[str, Any]:
    c = await repo.get_conversation(conv_id)
    msgs = await repo.client_messages(conv_id)
    return {
        "name": (c.name if c else "") or "",
        "contact": (c.contact if c else "") or "",
        "stage": (c.stage if c else "") or "",
        "owner": (c.owner if c else "") or "",
        "messages": msgs[-12:],
    }


async def _generate_reply(ctx: dict, inbound: str) -> str:
    import ai
    if not ai.available():
        if needs_escalation(inbound):
            return escalation_reply()
        return (
            f"Olá! Recebemos sua mensagem. "
            f"{' ' + ctx.get('name') if ctx.get('name') else ''}"
            "Nosso time comercial retorna amanhã. Pode me contar qual produto você precisa?"
        ).strip()
    prompt = build_prompt(
        client_name=ctx.get("name") or ctx.get("contact") or "",
        stage=ctx.get("stage") or "",
        owner=ctx.get("owner") or "",
        inbound=inbound,
    )
    mini = {
        "profile": {"name": ctx.get("name"), "status": ctx.get("stage")},
        "contact": ctx.get("contact"),
        "messages": ctx.get("messages") or [],
    }
    raw = await ai.ask(mini, prompt, max_tokens=320, temperature=0.4)
    return raw or escalation_reply()


async def _send_reply(conv_id: str, phone: str, text: str) -> bool:
    if settings.neppo_enabled:
        from neppo_client import get_neppo
        client = get_neppo()
        if client is None:
            return False
        try:
            await client.send_message(phone, text)
        except Exception as e:  # noqa: BLE001
            log.error("agent send neppo falhou %s: %s", phone, e)
            return False
    await repo.append_seller_message(conv_id, text, deps.now_hm())
    db.save_message(
        phone=phone, direction="out", text=text, bot=True,
        ts=_dt.datetime.now().isoformat(),
    )
    return True


def _skip_reason(conv_id: str, pilot: Optional[dict]) -> Optional[str]:
    if not settings.night_agent_enabled:
        return "agent_disabled"
    if not pilot or not pilot.get("enabled"):
        return "not_in_pilot"
    if pilot.get("human_owned"):
        return "human_owned"
    if not is_night_window():
        return "outside_hours"
    since = night_session_start().isoformat()
    if db.agent_replies_since(conv_id, since) >= settings.night_max_replies:
        return "max_replies"
    last = db.agent_last_sent_at(conv_id)
    if last:
        try:
            t = _dt.datetime.fromisoformat(last.replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=_dt.timezone.utc)
            now = _dt.datetime.now(t.tzinfo)
            if (now - t).total_seconds() < settings.night_cooldown_sec:
                return "cooldown"
        except ValueError:
            pass
    return None


async def on_client_message(
    *,
    conv_id: str,
    phone: str,
    text: str,
    client_name: str = "",
) -> None:
    """Avalia e, se aplicável, responde automaticamente."""
    pilot = db.agent_pilot_get(conv_id)
    reason = _skip_reason(conv_id, pilot)
    if reason:
        db.agent_log_append(conv_id, "skipped", detail=reason)
        await _publish_agent({
            "conv_id": conv_id, "action": "skipped", "detail": reason,
            "name": client_name,
        })
        return

    inbound = (text or "").strip()
    if not inbound:
        db.agent_log_append(conv_id, "skipped", detail="empty_inbound")
        return

    await _publish_agent({
        "conv_id": conv_id, "action": "thinking", "name": client_name,
    })

    ctx = await _light_context(conv_id)
    if needs_escalation(inbound):
        reply = escalation_reply()
    else:
        reply = await _generate_reply(ctx, inbound)

    blocked = False
    reply, blocked = sanitize_reply(reply)

    if pilot and not pilot.get("intro_sent"):
        reply = f"{intro_message()}\n\n{reply}"
        db.agent_intro_mark(conv_id)

    ok = await _send_reply(conv_id, phone, reply)
    action = "sent" if ok else "send_failed"
    db.agent_log_append(
        conv_id, action,
        detail="policy_blocked" if blocked else "",
        reply_text=reply,
    )
    repo.invalidate_ai_cache(conv_id)
    repo.invalidate_list_cache()
    await _publish_agent({
        "conv_id": conv_id, "action": action, "text": reply,
        "name": client_name, "detail": "policy_blocked" if blocked else "",
    })
    await deps.publish({
        "type": "message", "phone": phone, "text": reply, "name": client_name,
        "bot": True,
    })
