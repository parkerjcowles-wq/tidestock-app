from analytics import abc_classify, simulate_demand_history, forecast_mape, build_po_draft


def _rec(key, weekly, price):
    return {"sku_key": key, "avg_weekly_demand": weekly, "retail_price": price}


def test_abc_classify_pareto_split():
    recs = [
        _rec("big", 100, 10.0),    # 52,000/yr -> 80.6% cumulative -> A (first SKU always A)
        _rec("mid", 20, 8.0),      # 8,320/yr  -> 93.5% -> B
        _rec("small", 10, 8.0),    # 4,160/yr  -> 100%  -> C
    ]
    out = abc_classify(recs)
    assert out["big"] == "A" and out["mid"] == "B" and out["small"] == "C"


def test_abc_classify_single_sku_is_a():
    assert abc_classify([_rec("only", 5, 5.0)])["only"] == "A"


def test_abc_classify_zero_revenue_is_c():
    recs = [_rec("big", 100, 10.0), _rec("dead", 0, 5.0)]
    assert abc_classify(recs)["dead"] == "C"


def _sku(key, weekly=28, std=2.5):
    return {"sku_key": key, "avg_weekly_demand": weekly, "std_daily_demand": std,
            "retail_price": 9.99}


def test_history_is_deterministic_and_positive():
    a = simulate_demand_history(_sku("z_man"), weeks=8)
    b = simulate_demand_history(_sku("z_man"), weeks=8)
    assert a == b and len(a) == 8 and all(w >= 0 for w in a)


def test_mape_structure_and_range():
    out = forecast_mape([_sku("a"), _sku("b", weekly=45, std=7.0)])
    assert set(out) == {"portfolio_mape", "per_sku", "weeks", "method"}
    assert 0 <= out["portfolio_mape"] <= 100
    assert len(out["per_sku"]) == 2


def _po_rec(key, status, qty, cost, cat="Soft Plastics", supplier="Z-Man"):
    return {"sku_key": key, "product_name": key, "status": status, "order_qty": qty,
            "unit_cost": cost, "unit": "packs", "category_label": cat,
            "supplier": supplier, "order_model": "eoq"}


def test_po_includes_only_flagged_statuses():
    recs = [_po_rec("a", "Critical", 12, 5.0), _po_rec("b", "Healthy", 6, 4.0),
            _po_rec("c", "Reorder Soon", 24, 4.5, cat="Bait")]
    po = build_po_draft(recs)
    keys = [l["sku_key"] for g in po["groups"] for l in g["lines"]]
    assert sorted(keys) == ["a", "c"]


def test_po_totals():
    recs = [_po_rec("a", "Critical", 12, 5.0), _po_rec("c", "Reorder Soon", 24, 4.5, cat="Bait")]
    po = build_po_draft(recs)
    assert po["total_units"] == 36
    assert po["total_cost"] == round(12 * 5.0 + 24 * 4.5, 2)
    assert po["line_count"] == 2


def test_po_empty_when_all_healthy():
    po = build_po_draft([_po_rec("a", "Healthy", 12, 5.0)])
    assert po["groups"] == [] and po["total_cost"] == 0
