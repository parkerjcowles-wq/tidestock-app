"""New SC-manager analytics for the mockup: ABC classification, forecast
accuracy (MAPE over simulated history), and the draft PO builder."""
import datetime
import random
import statistics


def abc_classify(recs: list) -> dict:
    """A = top ~80% of annual revenue potential, B = next 15%, C = tail.

    Revenue potential = avg_weekly_demand * 52 * retail_price. The highest-
    revenue SKU is always A even if it alone exceeds the 80% band.
    """
    revenue = {
        r["sku_key"]: r["avg_weekly_demand"] * 52 * r.get("retail_price", 0)
        for r in recs
    }
    total = sum(revenue.values())
    if total <= 0:
        return {k: "C" for k in revenue}
    classes, cum, first = {}, 0.0, True
    for key, rev in sorted(revenue.items(), key=lambda kv: -kv[1]):
        if rev <= 0:
            classes[key] = "C"
            continue
        cum += rev / total
        if first or cum <= 0.80:
            classes[key] = "A"
        elif cum <= 0.95:
            classes[key] = "B"
        else:
            classes[key] = "C"
        first = False
    return classes


HISTORY_WEEKS = 8


def simulate_demand_history(rec: dict, weeks: int = HISTORY_WEEKS) -> list:
    """Deterministic simulated weekly demand (demo data — labeled as such in UI).

    Seeded per-SKU so numbers are stable across reloads.
    """
    rng = random.Random(rec["sku_key"])
    weekly_mu = rec["avg_weekly_demand"]
    weekly_sigma = rec.get("std_daily_demand", 1.0) * 7 ** 0.5
    return [max(0.0, round(rng.gauss(weekly_mu, weekly_sigma), 1)) for _ in range(weeks)]


def forecast_mape(recs: list, weeks: int = HISTORY_WEEKS) -> dict:
    """WAPE of a trailing-4-week moving-average forecast vs simulated actuals.

    Forecast for week t = mean(actuals[t-4:t]); scored over the last 4 weeks.
    WAPE (sum of |error| over sum of actuals) instead of plain MAPE — plain
    MAPE explodes on low-volume SKUs where a weekly actual lands near zero.
    """
    per_sku = []
    for r in recs:
        hist = simulate_demand_history(r, weeks)
        abs_err, total_actual = 0.0, 0.0
        for t in range(4, weeks):
            fcst = statistics.mean(hist[t - 4:t])
            abs_err += abs(hist[t] - fcst)
            total_actual += hist[t]
        wape = round(min(100.0, 100 * abs_err / total_actual), 1) if total_actual > 0 else 0.0
        per_sku.append({"sku_key": r["sku_key"], "mape": wape})
    portfolio = round(statistics.mean(s["mape"] for s in per_sku), 1) if per_sku else 0.0
    return {"portfolio_mape": portfolio, "per_sku": per_sku, "weeks": weeks,
            "method": "WAPE · 4-week moving average (simulated history — demo data)"}


PO_STATUSES = ("Critical", "Reorder Soon")


def build_po_draft(recs: list) -> dict:
    """Roll flagged SKUs into a draft purchase order grouped by category."""
    groups = {}
    for r in recs:
        if r["status"] not in PO_STATUSES:
            continue
        line_cost = round(r["order_qty"] * r.get("unit_cost", 0), 2)
        groups.setdefault(r["category_label"], []).append({
            "sku_key": r["sku_key"], "product_name": r["product_name"],
            "supplier": r.get("supplier", "—"), "status": r["status"],
            "order_qty": r["order_qty"], "unit": r.get("unit", ""),
            "unit_cost": r.get("unit_cost", 0), "line_cost": line_cost,
            "order_model": r.get("order_model", "eoq"),
        })
    group_list = [
        {"category": cat, "lines": lines,
         "subtotal": round(sum(l["line_cost"] for l in lines), 2)}
        for cat, lines in sorted(groups.items())
    ]
    all_lines = [l for g in group_list for l in g["lines"]]
    return {
        "generated_at": datetime.datetime.now().strftime("%b %d, %Y %I:%M %p"),
        "groups": group_list,
        "line_count": len(all_lines),
        "total_units": sum(l["order_qty"] for l in all_lines),
        "total_cost": round(sum(l["line_cost"] for l in all_lines), 2),
    }
