import math
from statistics import NormalDist

_norm = NormalDist()

SKU_SPECIES_MAP = {
    "bucktails_jigs": ["Striped Bass", "Flounder"],
    "soft_plastics":  ["Striped Bass", "Largemouth Bass"],
    "bait":           ["Striped Bass", "Flounder"],
    "hard_baits":     ["Striped Bass", "Largemouth Bass"],
    "terminal_tackle": ["Striped Bass", "Largemouth Bass", "Flounder"],
    "line_leaders":   [],
    "accessories":    [],
}

SKU_SEASONAL = {
    "bucktails_jigs": True, "soft_plastics": True, "bait": True,
    "hard_baits": True, "terminal_tackle": False, "line_leaders": False, "accessories": False,
}


def newsvendor_order_qty(daily_demand: float, std_daily: float,
                         shelf_life_days: int, unit_cost: float,
                         retail_price: float) -> float:
    """
    Newsvendor optimal order quantity for perishables.
    Critical ratio = Cu / (Cu + Co) where Cu = lost margin, Co = waste cost.
    For bait, Cu = retail margin and Co = unit cost — so CR = gross margin.
    """
    cr = (retail_price - unit_cost) / retail_price if retail_price > 0 else 0.5
    cr = max(0.01, min(0.99, cr))
    mu = daily_demand * shelf_life_days
    sigma = std_daily * math.sqrt(max(shelf_life_days, 1))
    return max(0.0, mu + sigma * _norm.inv_cdf(cr))


def gross_margin(unit_cost: float, retail_price: float) -> float:
    if retail_price <= 0:
        return 0.0
    return (retail_price - unit_cost) / retail_price


def revenue_at_risk(on_hand: float, rop: float, retail_price: float) -> float:
    return max(0.0, rop - on_hand) * retail_price


def urgency_score(
    on_hand: float, rop: float, dos: float, lead_time: int,
    fishing_score: int, striper_active: bool, sku_key: str, margin: float,
    is_seasonal=None, is_perishable: bool = False, shelf_life_days=None,
    social_sku_boost: int = 0,
) -> int:
    seasonal = is_seasonal if is_seasonal is not None else SKU_SEASONAL.get(sku_key, False)
    score = 0
    if on_hand < rop:
        score += 30
    if dos < lead_time:
        score += 25
    elif dos < lead_time * 1.5:
        score += 12
    if fishing_score >= 70 and seasonal:
        score += 20
    elif fishing_score >= 55 and seasonal:
        score += 8
    if lead_time >= 6:
        score += 10
    if margin >= 0.40:
        score += 10
    if striper_active and seasonal:
        score += 5
    if is_perishable:
        score += 8
    if is_perishable and shelf_life_days and dos > shelf_life_days * 0.85:
        score += 10
    score += min(social_sku_boost, 15)
    return min(score, 100)


def confidence_label(
    on_hand: float, rop: float, dos: float, lead_time: int,
    fishing_score: int, striper_active: bool, sku_key: str,
    is_seasonal=None,
) -> str:
    seasonal = is_seasonal if is_seasonal is not None else SKU_SEASONAL.get(sku_key, False)
    strong = sum([
        on_hand < rop,
        dos < lead_time,
        bool(striper_active and seasonal),
        fishing_score >= 70,
    ])
    if strong >= 3:
        return "High"
    if strong >= 2:
        return "Medium"
    return "Low"


def reason_card(
    sku_key: str, on_hand: float, rop: float, dos: float, lead_time: int,
    fishing_score: int, striper_active: bool, margin: float, species_active: dict,
    species_tags=None, is_seasonal=None,
) -> dict:
    seasonal = is_seasonal if is_seasonal is not None else SKU_SEASONAL.get(sku_key, False)
    species = species_tags if species_tags is not None else SKU_SPECIES_MAP.get(sku_key, [])

    if margin >= 0.40 and seasonal:
        business = "High-margin item with strong seasonal demand"
    elif seasonal:
        business = "Seasonal demand item tied to active species"
    else:
        business = "Steady-demand staple; reorder based on stock level"

    if on_hand < rop:
        calc = f"On hand ({on_hand:.0f}) is below reorder point ({rop:.0f})"
    elif dos < lead_time:
        calc = f"Only {dos:.0f}d of supply — less than {lead_time}d supplier lead time"
    else:
        calc = f"{dos:.0f}d of supply remaining; approaching reorder threshold"

    active_for_sku = [sp for sp in species if species_active.get(sp) in ("Peak", "Good")]
    if not active_for_sku and striper_active and "Striped Bass" in species:
        active_for_sku = ["Striped Bass"]
    if active_for_sku and fishing_score >= 70:
        demand = f"{' & '.join(active_for_sku)} season active; fishing signal {fishing_score}/100"
    elif active_for_sku:
        demand = f"{' & '.join(active_for_sku)} season active this month"
    elif fishing_score >= 70:
        demand = f"Elevated fishing signal ({fishing_score}/100)"
    else:
        demand = f"Moderate conditions (fishing score {fishing_score}/100)"

    return {"business": business, "calc": calc, "demand": demand}


def why_not_reorder(label: str, dos: float, lead_time: int, rop: float, on_hand: float) -> str:
    buffer_days = dos - lead_time
    buffer_units = on_hand - rop
    return (
        f"{label} has {dos:.0f}d of supply — {buffer_days:.0f}d above the {lead_time}d lead time "
        f"and {buffer_units:.0f} units above its reorder point. No action needed."
    )


def fallback_buyer_brief(ranked: list, species_active: dict, fishing_score: int) -> str:
    flagged = [r for r in ranked if r["urgency"] >= 30]
    healthy = [r for r in ranked if r["urgency"] < 20]

    if not flagged:
        return (
            f"Inventory is healthy across all SKUs. "
            f"Fishing signal is at {fishing_score}/100 — monitor conditions heading into the weekend. "
            f"No immediate reorder actions required."
        )

    names = " and ".join(r["label"] for r in flagged[:2])
    top = flagged[0]
    brief = f"Order {names} before the weekend. "
    brief += f"{top['label']} has {top['dos']:.0f} days of supply against a {top['lead_time']}d lead time. "

    active = [sp for sp, lvl in species_active.items() if lvl in ("Peak", "Good")]
    if active:
        brief += f"{' and '.join(active)} activity is strong this month, lifting demand for relevant products. "

    if fishing_score >= 70:
        brief += f"The fishing signal is elevated at {fishing_score}/100, suggesting higher weekend demand. "

    if healthy:
        brief += f"{', '.join(r['label'] for r in healthy[:2])} are well-stocked and do not need action."

    return brief
