"""Carteira — stats, sync mock, templates."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("CORTEX_USE_MOCK", "1")
os.environ.setdefault("WEBHOOK_ALLOW_INSECURE", "1")

import pytest
import portfolio_db as pdb
import portfolio_templates as ptpl
from portfolio_sync import _mock_rows


def test_templates_render():
    tpl = ptpl.get_template("reativacao_7d")
    assert tpl
    msg = ptpl.render_message(
        tpl["body"],
        {"nome": "João", "vendedor": "Maria", "empresa": "ACME"},
    )
    assert "João" in msg
    assert "Maria" in msg


def test_mock_rows():
    rows = _mock_rows(1, "2026-01-01")
    assert len(rows) >= 3
    assert rows[0]["contact_id"]


def test_db_stats_empty():
    pdb.replace_contacts(99999, [])
    st = pdb.stats(99999)
    assert st["total"] == 0


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import app as cortex_app
    return TestClient(cortex_app.app)


@pytest.fixture
def session(client):
    import os
    r = client.post("/api/login", json={
        "email": "gabriel.hernandes@larplasticos.com.br",
        "password": os.environ.get("CORTEX_ADMIN_PWD", "cortex@admin"),
    })
    assert r.status_code == 200
    return r


def test_api_portfolio(client, session):
    r = client.get("/api/portfolio/templates")
    assert r.status_code == 200
    assert len(r.json()["templates"]) >= 2

    client.post("/api/portfolio/sync")
    import time
    time.sleep(0.5)
    r2 = client.get("/api/portfolio/stats")
    assert r2.status_code == 200
    assert r2.json()["stats"]["total"] >= 1

    r3 = client.get("/api/portfolio/contacts?filter=has_phone&limit=10")
    assert r3.status_code == 200
    assert r3.json()["items"]
