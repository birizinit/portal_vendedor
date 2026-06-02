"""Testes de API (FastAPI TestClient) — modo mock."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["CORTEX_USE_MOCK"] = "1"
os.environ.setdefault("WEBHOOK_ALLOW_INSECURE", "1")

from fastapi.testclient import TestClient  # noqa: E402

import app as cortex_app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(cortex_app.app)


@pytest.fixture
def session(client):
    r = client.post("/api/login", json={
        "email": "gabriel.hernandes@larplasticos.com.br",
        "password": os.environ.get("CORTEX_ADMIN_PWD", "cortex@admin"),
    })
    assert r.status_code == 200
    return client.cookies


def test_health_public(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_conversations_requires_auth(client):
    r = client.get("/api/conversations")
    assert r.status_code == 401


def test_conversations_list_mock(client, session):
    r = client.get("/api/conversations?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert isinstance(body["items"], list)


def test_alerts_mock(client, session):
    r = client.get("/api/alerts")
    assert r.status_code == 200
    j = r.json()
    assert "alerts" in j
    assert j.get("from_cache") is True


def test_search_mock(client, session):
    r = client.get("/api/search?q=test")
    assert r.status_code == 200
    assert "conversations" in r.json()


def test_goals_roundtrip(client, session):
    r = client.post("/api/goals", json={"target": 50000})
    assert r.status_code == 200
    g = client.get("/api/goals").json()
    assert g["target"] == 50000


def test_weekly_report_json(client, session):
    r = client.get("/api/reports/weekly")
    assert r.status_code == 200
    assert "feedback_rows" in r.json()


def test_webhook_neppo_mock(client):
    r = client.post("/webhooks/neppo", json={})
    assert r.status_code == 200
