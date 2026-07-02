import pytest
from fastapi.testclient import TestClient

from conftest import offline_engine


@pytest.fixture
def client(monkeypatch):
    offline_engine(monkeypatch)
    from main import app
    return TestClient(app)


def test_dashboard_contract(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"kpis", "recs", "buyer_summary", "forecast_accuracy", "as_of"}
    rec = body["recs"][0]
    assert set(rec) >= {"sku_key", "product_name", "status", "urgency", "dos",
                        "stockout_prob", "abc_class", "order_qty", "rev_risk"}
    assert rec["abc_class"] in ("A", "B", "C")


def test_signals_contract(client):
    r = client.get("/api/signals")
    assert r.status_code == 200
    assert set(r.json()) >= {"tide", "pressure", "moon", "species", "fishing_score",
                             "forecast", "tournaments", "water_temp"}


def test_feeds_contract(client):
    r = client.get("/api/feeds")
    assert r.status_code == 200
    assert set(r.json()) >= {"web_reports", "reddit_local", "reddit_regional", "velocity"}


def test_scenario_weights(client):
    r = client.post("/api/scenario", json={"mode": "weights",
        "weights": {"moon": 0.5, "tide": 1.0, "social": 1.0, "pressure": 1.0,
                    "tournament": 1.0, "season": 1.0},
        "weekend_boost": True})
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"categories", "sku_table", "summary"}
    assert len(body["sku_table"]) == 25


def test_scenario_preset(client):
    r = client.post("/api/scenario", json={"mode": "preset", "preset": "striper_run_peak"})
    assert r.status_code == 200
    assert any(row["changed"] in (True, False) for row in r.json()["sku_table"])


def test_scenario_supplier_delay_extends_lead_time(client):
    r = client.post("/api/scenario", json={"mode": "preset", "preset": "supplier_delay"})
    assert r.status_code == 200
    assert r.json()["summary"]["lead_time_extra"] == 3


def test_scenario_rejects_bad_preset(client):
    r = client.post("/api/scenario", json={"mode": "preset", "preset": "nope"})
    assert r.status_code == 422


def test_po_draft_contract(client):
    r = client.get("/api/po-draft")
    assert r.status_code == 200
    assert set(r.json()) >= {"groups", "total_cost", "total_units", "generated_at"}


def test_brief_fallback_on_llm_failure(client, monkeypatch):
    import main

    def boom(prompt):
        raise RuntimeError("no llm")

    monkeypatch.setattr(main, "_generate_llm", boom)
    r = client.post("/api/brief", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "fallback"
    assert len(body["text"]) > 0


def test_ask_fallback_on_llm_failure(client, monkeypatch):
    import main

    def boom(prompt):
        raise RuntimeError("no llm")

    monkeypatch.setattr(main, "_generate_llm", boom)
    r = client.post("/api/ask", json={"question": "what should I order?"})
    assert r.status_code == 200
    assert r.json()["source"] == "fallback"


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_security_headers_present(client):
    r = client.get("/api/dashboard")
    assert "content-security-policy" in r.headers
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "strict-transport-security" in r.headers


def test_api_docs_disabled(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_ask_rate_limited_after_burst(client, monkeypatch):
    import main
    monkeypatch.setattr(main, "_generate_llm", lambda p: "ok")
    codes = [client.post("/api/ask", json={"question": "hi"}).status_code for _ in range(20)]
    assert 429 in codes  # limiter trips within the burst
