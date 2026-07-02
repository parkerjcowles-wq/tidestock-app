import json
from pathlib import Path

_SEED_PATH = Path(__file__).parent.parent / "data" / "inventory_seed.json"

def load_inventory() -> dict:
    with open(_SEED_PATH) as f:
        data = json.load(f)
    # Strip the _version metadata key so callers only see SKU entries
    return {k: v for k, v in data.items() if not k.startswith("_")}

def get_avg_daily_demand(sku_data: dict) -> float:
    return sku_data["avg_weekly_demand"] / 7

def get_std_daily_demand(sku_data: dict) -> float:
    return sku_data.get("std_daily_demand", sku_data["avg_weekly_demand"] / 7 * 0.3)

def get_lead_time(sku_data: dict, fallback: int = 5) -> int:
    return sku_data.get("lead_time_days", fallback)
