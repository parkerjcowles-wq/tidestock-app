"""Data assembly for the TideStock mockup API.

Ports the aggregation that lives in the original Streamlit app.py (loaders +
build_all_recs + KPI math) behind simple TTL caches, and serializes the
results to JSON-safe structures. No HTTP concerns here — main.py owns those.
"""
import datetime
import pathlib
import threading
import time

import pandas as pd
from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env")

import config
from signals.noaa import fetch_tide_predictions, fetch_water_temp, get_tide_quality
from signals.weather import fetch_weather, fetch_7day_forecast, compute_weather_demand_mult
from signals.moon import get_week_moon_data, get_moon_phase, get_fishing_score
from signals.reddit_signals import (
    fetch_reddit_signals, fetch_location_reddit_posts,
    get_overall_social_velocity, compute_social_fishing_boost, get_sku_demand_signals,
)
from signals.web_reports import fetch_web_fishing_reports
from signals.tournament import fetch_tournaments
from inventory.model import (
    safety_stock, reorder_point, economic_order_quantity, days_of_supply,
    SERVICE_LEVEL_Z, stockout_probability,
)
from inventory.data import load_inventory, get_avg_daily_demand, get_std_daily_demand, get_lead_time
from inventory.recommendations import (
    urgency_score, confidence_label, reason_card, gross_margin,
    revenue_at_risk, newsvendor_order_qty,
)

_lock = threading.Lock()
_caches = []


def ttl_cache(seconds):
    def deco(fn):
        state = {}

        def wrapper():
            with _lock:
                if "v" in state and time.time() - state["t"] < seconds:
                    return state["v"]
            val = fn()
            with _lock:
                state["t"], state["v"] = time.time(), val
            return val

        wrapper.clear = state.clear
        _caches.append(state)
        return wrapper

    return deco


def clear_caches():
    with _lock:
        for state in _caches:
            state.clear()


@ttl_cache(3600)
def load_conditions():
    try:
        tide_df = fetch_tide_predictions(config.NOAA_STATION_ID, days=7)
    except Exception:
        tide_df = pd.DataFrame(columns=["time", "height"])
    try:
        water_temp = fetch_water_temp(config.NOAA_STATION_ID)
    except Exception:
        water_temp = 55.0
    try:
        weather = fetch_weather(config.SHOP_LAT, config.SHOP_LON)
    except Exception:
        weather = {
            "pressure_series": pd.DataFrame(columns=["time", "pressure"]),
            "current_temp_f": 65.0, "current_wind_mph": 0.0, "pressure_trend": "stable",
        }
    try:
        forecast = fetch_7day_forecast(config.SHOP_LAT, config.SHOP_LON)
    except Exception:
        forecast = []
    week_moon     = get_week_moon_data()
    today_phase   = get_moon_phase(datetime.date.today())
    tide_quality  = get_tide_quality(tide_df)
    fishing_score = get_fishing_score(today_phase, weather["pressure_trend"])
    weather_mult  = compute_weather_demand_mult(forecast)
    return {
        "tide_df": tide_df, "water_temp": water_temp, "weather": weather,
        "week_moon": week_moon, "today_phase": today_phase,
        "tide_quality": tide_quality, "fishing_score": fishing_score,
        "forecast": forecast, "weather_mult": weather_mult,
        "loaded_at": datetime.datetime.now().strftime("%I:%M %p"),
    }


@ttl_cache(1800)
def load_social_signals():
    try:
        posts = fetch_reddit_signals(limit=20)
    except Exception:
        posts = []
    try:
        local_posts = fetch_location_reddit_posts(config.REDDIT_LOCATION_QUERY, limit=12)
    except Exception:
        local_posts = []
    return {
        "posts":         posts,
        "local_posts":   local_posts,
        "velocity":      get_overall_social_velocity(posts),
        "fishing_boost": compute_social_fishing_boost(posts),
        "sku_signals":   get_sku_demand_signals(posts),
        "loaded_at":     datetime.datetime.now().strftime("%I:%M %p"),
    }


@ttl_cache(3600)
def load_web_reports():
    try:
        return fetch_web_fishing_reports(days=14)
    except Exception:
        return []


@ttl_cache(3600)
def load_tournaments():
    try:
        return fetch_tournaments(days_ahead=30)
    except Exception:
        return []


SEASON_MAP = {1: "off", 2: "off", 3: "shoulder", 4: "shoulder", 5: "peak",
              6: "peak", 7: "shoulder", 8: "shoulder", 9: "peak", 10: "peak",
              11: "shoulder", 12: "off"}


def build_all_recs(demand_mult: float, delay_days: int, service_pct: float,
                   fishing_score: int, species_now: dict,
                   sku_signals: dict = None, weather_mult: float = 1.0) -> list:
    z         = SERVICE_LEVEL_Z[service_pct]
    inventory = load_inventory()
    month_now = datetime.date.today().month
    striper_active = species_now.get("Striped Bass", "Inactive") in ("Peak", "Good")

    season_level = SEASON_MAP.get(month_now, "shoulder")

    recs = []
    for sku_key, sku in inventory.items():
        is_seasonal   = sku.get("is_seasonal", False)
        is_perishable = sku.get("is_perishable", False)
        shelf_life    = sku.get("shelf_life_days")
        species_tags  = sku.get("species_tags", [])
        category      = sku.get("category", sku_key)

        eff_mult = demand_mult * weather_mult if is_seasonal else demand_mult
        daily  = get_avg_daily_demand(sku) * eff_mult
        std    = get_std_daily_demand(sku) * eff_mult
        lt     = get_lead_time(sku, config.DEFAULT_LEAD_TIME_DAYS) + delay_days
        ss     = safety_stock(std, lt, z)
        rop    = reorder_point(daily, lt, ss)
        eoq    = economic_order_quantity(
            sku["avg_weekly_demand"] * 52 * eff_mult,
            sku["order_cost"], sku["holding_cost"],
        )
        # Cap at 999 ("no meaningful burn rate") — also keeps JSON finite.
        dos    = min(days_of_supply(sku["on_hand"], daily), 999.0)
        margin = gross_margin(sku.get("unit_cost", 0), sku.get("retail_price", 1))
        rev_risk = revenue_at_risk(sku["on_hand"], rop, sku.get("retail_price", 0))

        cat_boost = (sku_signals or {}).get(category, 0)
        score = urgency_score(
            sku["on_hand"], rop, dos, lt, fishing_score, striper_active, sku_key, margin,
            is_seasonal=is_seasonal, is_perishable=is_perishable, shelf_life_days=shelf_life,
            social_sku_boost=cat_boost,
        )
        conf = confidence_label(
            sku["on_hand"], rop, dos, lt, fishing_score, striper_active, sku_key,
            is_seasonal=is_seasonal,
        )
        reasons = reason_card(
            sku_key, sku["on_hand"], rop, dos, lt, fishing_score, striper_active,
            margin, species_now, species_tags=species_tags, is_seasonal=is_seasonal,
        )

        if dos < lt or sku["on_hand"] < rop * 0.5:
            status = "Critical"
        elif sku["on_hand"] < rop or dos < lt * 1.5:
            status = "Reorder Soon"
        elif dos < lt * 2 or sku["on_hand"] < rop * 1.2:
            status = "Watch"
        else:
            status = "Healthy"

        stockout_prob = stockout_probability(sku["on_hand"], daily, std, lt)

        pack = sku.get("reorder_pack_size", 1)
        if is_perishable and shelf_life and daily > 0:
            nv_raw = newsvendor_order_qty(
                daily, std, shelf_life,
                sku.get("unit_cost", 0), sku.get("retail_price", 1),
            )
            order_qty = max(pack, round(nv_raw / pack) * pack) if pack > 0 else max(1, round(nv_raw))
            order_model = "newsvendor"
        else:
            raw_qty = (max(eoq, (rop - sku["on_hand"]) + eoq) if sku["on_hand"] < rop else eoq)
            order_qty = max(pack, round(raw_qty / pack) * pack) if pack > 0 else max(1, round(raw_qty))
            order_model = "eoq"

        recs.append({
            "sku_key":      sku_key,
            "product_name": sku.get("product_name", sku_key),
            "label":        sku.get("product_name", sku_key),
            "category":     category,
            "category_label": config.SKU_CATEGORIES.get(category, category),
            "brand":        sku.get("brand", "—"),
            "supplier":     sku.get("supplier", "—"),
            "species_tags": species_tags,
            "status":       status,
            "urgency":      score,
            "confidence":   conf,
            "reasons":      reasons,
            "on_hand":      sku["on_hand"],
            "unit":         sku["unit"],
            "dos":          dos,
            "lead_time":    lt,
            "rop":          rop,
            "eoq":          eoq,
            "order_qty":    order_qty,
            "order_model":  order_model,
            "stockout_prob": stockout_prob,
            "margin":       margin,
            "rev_risk":     rev_risk,
            "retail_price": sku.get("retail_price", 0),
            "unit_cost":    sku.get("unit_cost", 0),
            "safety_stock": ss,
            "service_z":    z,
            "avg_weekly_demand": sku["avg_weekly_demand"],
            "is_perishable": is_perishable,
            "shelf_life":   shelf_life,
            "season_level": season_level,
        })

    STATUS_PRIORITY = {"Critical": 0, "Reorder Soon": 1, "Watch": 2, "Healthy": 3}
    recs.sort(key=lambda r: (STATUS_PRIORITY.get(r["status"], 4), -r["urgency"]))
    return recs


def get_state(demand_mult: float = 1.0, delay_days: int = 0,
              service_pct: float = config.DEFAULT_SERVICE_LEVEL,
              bad_weather: bool = False) -> dict:
    cond   = load_conditions()
    social = load_social_signals()
    month_now   = datetime.date.today().month
    species_now = config.SPECIES_CALENDAR.get(month_now, {})
    fishing_score = min(cond["fishing_score"] + social["fishing_boost"], 100)
    eff_mult = demand_mult * (0.80 if bad_weather else 1.0)
    recs = build_all_recs(eff_mult, delay_days, service_pct, fishing_score,
                          species_now, sku_signals=social["sku_signals"],
                          weather_mult=cond["weather_mult"])
    return {
        "cond": cond, "social": social, "species_now": species_now,
        "fishing_score": fishing_score, "recs": recs,
        "service_pct": service_pct,
        "month_name": datetime.date.today().strftime("%B"),
    }


def build_kpis(recs: list, state: dict) -> dict:
    n_critical = sum(1 for r in recs if r["status"] == "Critical")
    n_reorder  = sum(1 for r in recs if r["status"] == "Reorder Soon")
    n_watch    = sum(1 for r in recs if r["status"] == "Watch")
    total_rev_risk = sum(r["rev_risk"] for r in recs if r["status"] in ("Critical", "Reorder Soon"))
    valid_dos = [r["dos"] for r in recs if r["dos"] < 999]
    avg_dos   = sum(valid_dos) / len(valid_dos) if valid_dos else 0
    avg_lt    = sum(r["lead_time"] for r in recs) / max(1, len(recs))
    return {
        "n_critical": n_critical,
        "n_reorder": n_reorder,
        "n_watch": n_watch,
        "n_total": len(recs),
        "n_categories": len(config.SKU_CATEGORIES),
        "total_rev_risk": round(total_rev_risk, 2),
        "avg_dos": round(avg_dos, 1),
        "avg_lead_time": round(avg_lt, 1),
        "fishing_score": state["fishing_score"],
    }


def build_brief_context(state: dict) -> dict:
    """Inventory + conditions context for Dave's brief (ported from app.py tab 5)."""
    recs = state["recs"]
    cond = state["cond"]
    inv_summary = {}
    for cat_key, cat_label in config.SKU_CATEGORIES.items():
        cat_recs = [r for r in recs if r["category"] == cat_key]
        if not cat_recs:
            continue
        critical_count = sum(1 for r in cat_recs if r["status"] == "Critical")
        valid = [r["dos"] for r in cat_recs if r["dos"] < 999]
        avg_dos_cat = sum(valid) / len(valid) if valid else 0
        worst_urgency = max((r["urgency"] for r in cat_recs), default=0)
        urgency_label = ("Order Today" if worst_urgency >= 55
                         else "This Week" if worst_urgency >= 30 else "Monitor")
        inv_summary[cat_label] = {"dos": avg_dos_cat, "urgency": urgency_label,
                                  "critical_skus": critical_count}

    conditions_ctx = {
        "date":           datetime.date.today().isoformat(),
        "moon_phase":     cond["today_phase"],
        "tide_quality":   cond["tide_quality"],
        "pressure_trend": cond["weather"]["pressure_trend"],
        "water_temp":     cond["water_temp"],
        "fishing_score":  cond["fishing_score"],
        "species":        state["species_now"],
    }
    critical_skus = [r for r in recs if r["status"] in ("Critical", "Reorder Soon")]
    dave_posts = [p for p in state["social"]["posts"]
                  if p.get("sentiment") == "catching" and p.get("bait_mentions")][:4]
    return {
        "inv_summary": inv_summary,
        "conditions_ctx": conditions_ctx,
        "critical_skus": critical_skus,
        "dave_posts": dave_posts,
    }


# ── JSON serialization helpers ────────────────────────────────────────────────

def _df_records(df, time_col="time"):
    if df is None or len(df) == 0:
        return []
    out = df.copy()
    if time_col in out.columns:
        out[time_col] = out[time_col].astype(str)
    return out.to_dict("records")


def conditions_json(cond: dict) -> dict:
    c = dict(cond)
    c["tide_df"] = _df_records(cond["tide_df"])
    w = dict(cond["weather"])
    w["pressure_series"] = _df_records(cond["weather"]["pressure_series"])
    c["weather"] = w
    c["week_moon"] = [
        {**m, "date": m["date"].isoformat(), "dow": m["date"].strftime("%a")}
        for m in cond["week_moon"]
    ]
    return c
