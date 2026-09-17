import datetime

from conftest import offline_engine


def test_engine_state_offline(monkeypatch):
    engine = offline_engine(monkeypatch)
    state = engine.get_state()
    assert len(state["recs"]) == 25
    assert {r["status"] for r in state["recs"]} <= {"Critical", "Reorder Soon", "Watch", "Healthy"}
    assert all("retail_price" in r and "unit_cost" in r for r in state["recs"])
    # sorted Critical -> Healthy with urgency tiebreak
    prio = {"Critical": 0, "Reorder Soon": 1, "Watch": 2, "Healthy": 3}
    keys = [(prio[r["status"]], -r["urgency"]) for r in state["recs"]]
    assert keys == sorted(keys)


def test_engine_kpis_offline(monkeypatch):
    engine = offline_engine(monkeypatch)
    state = engine.get_state()
    kpis = engine.build_kpis(state["recs"], state)
    assert kpis["n_total"] == 25
    assert kpis["n_critical"] + kpis["n_reorder"] + kpis["n_watch"] <= 25
    assert kpis["total_rev_risk"] >= 0
    assert 0 <= kpis["fishing_score"] <= 100


def test_conditions_json_is_serializable(monkeypatch):
    import json
    engine = offline_engine(monkeypatch)
    state = engine.get_state()
    out = json.dumps(engine.conditions_json(state["cond"]))
    assert "tide_df" in out


def test_brief_context_offline(monkeypatch):
    engine = offline_engine(monkeypatch)
    state = engine.get_state()
    ctx = engine.build_brief_context(state)
    assert set(ctx) == {"inv_summary", "conditions_ctx", "critical_skus", "dave_posts"}
    assert ctx["conditions_ctx"]["moon_phase"]


def test_brief_context_date_uses_shop_clock_not_utc_today(monkeypatch):
    # Pin the shop clock to a fixed ET date so this can't pass by accident
    # near the UTC/ET day boundary - a bare datetime.date.today() would drift
    # a day ahead of this in the evening ET, which is exactly the "12:33 AM,
    # SEP 17" bug this test guards against.
    engine = offline_engine(monkeypatch)
    import clock
    fixed_date = datetime.date(2026, 12, 25)
    monkeypatch.setattr(clock, "today_local", lambda: fixed_date)

    state = engine.get_state()
    ctx = engine.build_brief_context(state)
    assert ctx["conditions_ctx"]["date"] == fixed_date.isoformat()
