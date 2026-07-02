SIGNAL_MULTIPLIERS = {
    "moon": {
        "new": 1.8, "full": 1.8, "waxing_gibbous": 1.4, "waning_gibbous": 1.4,
        "first_quarter": 1.2, "last_quarter": 1.2, "waxing_crescent": 1.0, "waning_crescent": 1.0,
    },
    "tide": {"prime": 1.6, "moderate": 1.2, "poor": 0.8},
    "social": {"trending": 2.0, "elevated": 1.4, "baseline": 1.0},
    "pressure": {"rising": 0.9, "stable": 1.0, "falling": 1.3},
    "tournament": {"within_3_days": 2.2, "same_week": 1.5, "none": 1.0},
    "season": {"peak": 1.7, "shoulder": 1.2, "off": 0.7},
}

DEFAULT_WEIGHTS = {
    "moon": 1.0, "tide": 1.0, "social": 1.0,
    "pressure": 1.0, "tournament": 1.0, "season": 1.0,
}

SCENARIO_EFFECTS = {
    "tournament_weekend": {"terminal_tackle": 2.2, "soft_plastics": 1.5, "hard_baits": 1.3},
    "viral_bait_moment":  {"soft_plastics": 3.0, "hard_baits": 1.5},
    "cold_front":         {"bait": 0.6, "soft_plastics": 0.7, "hard_baits": 0.8},
    "striper_run_peak":   {"soft_plastics": 2.0, "bucktails_jigs": 2.2, "accessories": 1.3},
    "tourist_season":     {"accessories": 1.6, "hard_baits": 1.4, "terminal_tackle": 1.3, "soft_plastics": 1.2},
    "supplier_delay":     {},
}


def compute_demand_index(
    base_demand: float,
    moon_phase: str,
    tide_quality: str,
    social_velocity: str,
    pressure_trend: str,
    tournament_proximity: str,
    season_level: str,
    weights: dict,
) -> float:
    signals = {
        "moon":       SIGNAL_MULTIPLIERS["moon"][moon_phase],
        "tide":       SIGNAL_MULTIPLIERS["tide"][tide_quality],
        "social":     SIGNAL_MULTIPLIERS["social"][social_velocity],
        "pressure":   SIGNAL_MULTIPLIERS["pressure"][pressure_trend],
        "tournament": SIGNAL_MULTIPLIERS["tournament"][tournament_proximity],
        "season":     SIGNAL_MULTIPLIERS["season"][season_level],
    }
    total_weight = sum(weights.get(k, 1.0) for k in signals)
    if total_weight == 0:
        return base_demand
    weighted = sum(signals[k] * weights.get(k, 1.0) for k in signals)
    return base_demand * (weighted / total_weight)


def compute_scenario_demand(base_demands: dict, scenario_key: str) -> dict:
    """base_demands keyed by sku_key (category-level, legacy)."""
    effects = SCENARIO_EFFECTS.get(scenario_key, {})
    return {sku: base * effects.get(sku, 1.0) for sku, base in base_demands.items()}


def compute_scenario_demand_by_category(sku_items: list, scenario_key: str) -> dict:
    """
    sku_items: list of (sku_key, base_demand, category_key) tuples.
    Returns dict of sku_key → adjusted demand using category-level scenario effects.
    """
    effects = SCENARIO_EFFECTS.get(scenario_key, {})
    return {
        sku_key: base_demand * effects.get(category_key, 1.0)
        for sku_key, base_demand, category_key in sku_items
    }
