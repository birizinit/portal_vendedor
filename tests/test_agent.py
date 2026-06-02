"""Testes do assistente noturno — policy e DB."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["CORTEX_USE_MOCK"] = "1"

from agent_policy import is_night_window, sanitize_reply  # noqa: E402
import db  # noqa: E402


def test_sanitize_blocks_money():
    out, blocked = sanitize_reply("O valor é R$ 120,00 por unidade")
    assert blocked
    assert "R$" not in out


def test_sanitize_allows_generic():
    out, blocked = sanitize_reply("Bom dia! Anotei sua necessidade de caixas.")
    assert not blocked
    assert "caixas" in out.lower()


def test_night_window_evening():
    tz = ZoneInfo("America/Sao_Paulo")
    t = datetime(2026, 5, 29, 20, 0, tzinfo=tz)
    assert is_night_window(t)


def test_night_window_morning():
    tz = ZoneInfo("America/Sao_Paulo")
    t = datetime(2026, 5, 29, 6, 30, tzinfo=tz)
    assert is_night_window(t)


def test_night_window_afternoon():
    tz = ZoneInfo("America/Sao_Paulo")
    t = datetime(2026, 5, 29, 15, 0, tzinfo=tz)
    assert not is_night_window(t)


def test_pilot_toggle_db():
    db.agent_pilot_set("test_conv_1", enabled=True, user_id=1, note="t")
    p = db.agent_pilot_get("test_conv_1")
    assert p and p["enabled"] == 1
    db.agent_pilot_set("test_conv_1", enabled=False, user_id=1)
    p2 = db.agent_pilot_get("test_conv_1")
    assert p2 and p2["enabled"] == 0
