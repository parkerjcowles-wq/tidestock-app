"""HTTP surface for the TideStock mockup. Routes stay thin — data assembly
lives in engine.py, new SC analytics in analytics.py."""
import pathlib
import threading
import time
from collections import defaultdict
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import analytics
import clock
import config
import engine
from ai.brief import build_ask_dave_prompt, build_brief_prompt, generate_brief_streaming
from inventory.forecast import (DEFAULT_WEIGHTS, SCENARIO_EFFECTS,
                                compute_demand_index,
                                compute_scenario_demand_by_category)
from inventory.model import SERVICE_LEVEL_Z, days_of_supply
from inventory.recommendations import fallback_buyer_brief

# Public demo with no auth — the interactive API docs would just hand an
# attacker the full schema, so disable them in favor of a smaller surface.
app = FastAPI(title="TideStock API", docs_url=None, redoc_url=None, openapi_url=None)
WEB_DIR = pathlib.Path(__file__).resolve().parent.parent / "web"

# ── Security headers + rate limiting ──────────────────────────────────────────
# CSP: script-src stays strict (no inline scripts exist); style-src allows inline
# because the markup uses style="" attributes; data: covers the SVG-noise bg.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; object-src 'none'"
)
_SEC_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}

# Per-IP limits on the endpoints that spend Groq quota (uncacheable / per-user).
# 2026-09-02: 15/20 per minute -> 6/10. The old numbers were sized against
# abuse, not against the budget they actually spend: the Groq free tier is a
# 200,000 token/day cap SHARED with Forefront (same org, ~25 briefs/day across
# both apps), so a single visitor holding 15 asks a minute could exhaust the
# day's quota for BOTH resume apps in about ten minutes and leave Dave serving
# the rule-based fallback to everyone after. Six per minute is still well above
# what reading the dashboard and asking follow-ups needs.
_RL_RULES = {"/api/ask": (6, 60), "/api/brief": (10, 60)}  # path -> (max, seconds)
_RL_LOCK = threading.Lock()
_RL_HITS = defaultdict(list)


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")  # Render/Cloudflare front the app
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(request: Request, rule) -> bool:
    limit, window = rule
    ip = _client_ip(request)
    now = time.time()
    with _RL_LOCK:
        if len(_RL_HITS) > 5000:      # crude cap so the map can't grow unbounded
            _RL_HITS.clear()
        hits = _RL_HITS[ip]
        hits[:] = [t for t in hits if now - t < window]
        if len(hits) >= limit:
            return True
        hits.append(now)
        return False


@app.middleware("http")
async def security_and_ratelimit(request: Request, call_next):
    rule = _RL_RULES.get(request.url.path)
    if rule and request.method == "POST" and _rate_limited(request, rule):
        response = JSONResponse({"detail": "Rate limit exceeded. Try again shortly."},
                                status_code=429)
    else:
        response = await call_next(request)
    for k, v in _SEC_HEADERS.items():
        response.headers[k] = v
    return response

SCENARIO_LABELS = {
    "tournament_weekend": "Tournament This Weekend",
    "viral_bait_moment":  "Viral Bait Moment",
    "cold_front":         "Cold Front Incoming",
    "striper_run_peak":   "Striper Run Peak",
    "tourist_season":     "Tourist Season",
    "supplier_delay":     "Supplier Delay",
}
SCENARIO_DESCRIPTIONS = {
    "tournament_weekend": "Local tournament drives finesse tackle and soft plastic demand up sharply.",
    "viral_bait_moment":  "A bait goes viral — soft plastic demand 3× baseline.",
    "cold_front":         "Cold front suppresses activity — bait and soft plastics drop 30–40%.",
    "striper_run_peak":   "Striper migration peak — paddle tails and bucktails in high demand.",
    "tourist_season":     "Summer tourists — accessories and hard baits spike 40–60%.",
    "supplier_delay":     "Key supplier running 3+ days late — models urgency under extended lead times.",
}


class ScenarioReq(BaseModel):
    mode: str  # "weights" | "preset"
    weights: Optional[Dict[str, float]] = None
    preset: Optional[str] = None
    weekend_boost: bool = False
    demand_mult: float = Field(1.0, ge=0.0, le=10.0)
    delay_days: int = Field(0, ge=0, le=60)
    service_pct: float = config.DEFAULT_SERVICE_LEVEL
    bad_weather: bool = False


class AskReq(BaseModel):
    question: str


class BriefReq(BaseModel):
    refresh: bool = False


def _recs_with_abc(state: dict) -> list:
    recs = state["recs"]
    abc = analytics.abc_classify(recs)
    for r in recs:
        r["abc_class"] = abc[r["sku_key"]]
    return recs


@app.get("/api/dashboard")
def dashboard():
    state = engine.get_state()
    recs = _recs_with_abc(state)
    return {
        "kpis": engine.build_kpis(recs, state),
        "recs": recs,
        "buyer_summary": fallback_buyer_brief(recs, state["species_now"], state["fishing_score"]),
        "forecast_accuracy": analytics.forecast_mape(recs),
        "as_of": state["cond"]["loaded_at"],
        "social_as_of": state["social"].get("loaded_at", "—"),
        "month": state["month_name"],
        "today": clock.today_local().strftime("%b %d, %Y"),
        "fishing_score": state["fishing_score"],
        "service_pct": state["service_pct"],
        # Also served here so the header's feed-health pill is correct on the
        # landing view, not only after the visitor opens Demand Signals.
        "degraded": state["cond"].get("degraded", []),
    }


def _weather_down(cond: dict) -> bool:
    """True when this load served fallback weather rather than live readings."""
    return "weather" in (cond.get("degraded") or [])


@app.get("/api/signals")
def signals():
    state = engine.get_state()
    cond = engine.conditions_json(state["cond"])
    return {
        "tide": cond["tide_df"],
        "tide_quality": cond["tide_quality"],
        # Nulled for DISPLAY when the weather feed fell back. The engine keeps
        # real defaults internally because the models index on them; what must
        # not happen is the dashboard captioning "stable" and "0 mph" as live
        # readings under a LIVE badge when nothing was actually fetched.
        "pressure": cond["weather"]["pressure_series"],
        "pressure_trend": None if _weather_down(cond) else cond["weather"]["pressure_trend"],
        "current_temp_f": None if _weather_down(cond) else cond["weather"].get("current_temp_f"),
        "current_wind_mph": None if _weather_down(cond) else cond["weather"].get("current_wind_mph"),
        "water_temp": cond["water_temp"],
        "moon": cond["week_moon"],
        "moon_phase": cond["today_phase"],
        "species": state["species_now"],
        "species_colors": config.ACTIVITY_COLORS,
        "fishing_score": state["fishing_score"],
        "fishing_score_env": cond["fishing_score"],
        "social_boost": state["social"]["fishing_boost"],
        "forecast": cond["forecast"],
        "weather_mult": cond["weather_mult"],
        "tournaments": engine.load_tournaments(),
        # Names of the upstreams serving fallback data on this load. The
        # frontend uses it to label a panel as having no data rather than
        # drawing an empty chart and captioning fallback constants as live.
        "degraded": cond.get("degraded", []),
        "as_of": cond["loaded_at"],
    }


@app.get("/api/feeds")
def feeds():
    state = engine.get_state()
    web = engine.load_web_reports()
    # Catch Reports used to read only Reddit, which no longer answers, so the
    # panel was empty on every load. Published reports carry the same bait and
    # sentiment text the extractor wants; what they do not carry is an author or
    # an upvote count, and `origin` keeps the card honest about that.
    catch = state["social"]["posts"] or engine.derive_catch_reports(web)
    return {
        "web_reports": web,
        "reddit_local": state["social"]["local_posts"],
        "reddit_regional": state["social"]["posts"],
        "catch_reports": catch,
        "velocity": state["social"]["velocity"],
        "degraded": state["social"].get("degraded", []),
        "as_of": state["social"].get("loaded_at", "—"),
    }


@app.get("/api/po-draft")
def po_draft():
    state = engine.get_state()
    return analytics.build_po_draft(_recs_with_abc(state))


@app.post("/api/scenario")
def scenario(req: ScenarioReq):
    if req.mode not in ("weights", "preset"):
        raise HTTPException(status_code=422, detail="mode must be 'weights' or 'preset'")
    if req.mode == "preset" and req.preset not in SCENARIO_EFFECTS:
        raise HTTPException(status_code=422, detail=f"unknown preset: {req.preset}")
    if req.service_pct not in SERVICE_LEVEL_Z:
        raise HTTPException(
            status_code=422,
            detail=f"service_pct must be one of {sorted(SERVICE_LEVEL_Z)}",
        )

    state = engine.get_state(demand_mult=req.demand_mult, delay_days=req.delay_days,
                             service_pct=req.service_pct, bad_weather=req.bad_weather)
    recs = state["recs"]
    cond = state["cond"]
    month_now = clock.today_local().month

    cat_base = {}
    for r in recs:
        cat_base[r["category"]] = cat_base.get(r["category"], 0) + r["avg_weekly_demand"]
    total_base = sum(cat_base.values())

    if req.mode == "weights":
        weights = {**DEFAULT_WEIGHTS, **(req.weights or {})}
        boost = 1.25 if req.weekend_boost else 1.0
        adjusted_cat = {
            cat: compute_demand_index(
                base_demand=base * boost,
                moon_phase=cond["today_phase"],
                tide_quality=cond["tide_quality"],
                social_velocity="baseline",
                pressure_trend=cond["weather"]["pressure_trend"],
                tournament_proximity="none",
                season_level=engine.SEASON_MAP.get(month_now, "shoulder"),
                weights=weights,
            )
            for cat, base in cat_base.items()
        }
        # Distribute the category multiplier down to SKUs for the status table
        sku_demands = {
            r["sku_key"]: r["avg_weekly_demand"] * (
                adjusted_cat[r["category"]] / cat_base[r["category"]]
                if cat_base.get(r["category"]) else 1.0
            )
            for r in recs
        }
        lt_extra = 0
        label = "Signal Weights"
        description = ""
    else:
        sku_items = [(r["sku_key"], r["avg_weekly_demand"], r["category"]) for r in recs]
        sku_demands = compute_scenario_demand_by_category(sku_items, req.preset)
        adjusted_cat = {}
        for r in recs:
            adjusted_cat[r["category"]] = (
                adjusted_cat.get(r["category"], 0)
                + sku_demands.get(r["sku_key"], r["avg_weekly_demand"])
            )
        lt_extra = 3 if req.preset == "supplier_delay" else 0
        label = SCENARIO_LABELS[req.preset]
        description = SCENARIO_DESCRIPTIONS[req.preset]

    total_adjusted = sum(adjusted_cat.values())
    sku_table = []
    for r in recs:
        scen_demand = sku_demands.get(r["sku_key"], r["avg_weekly_demand"])
        scen_dos = min(days_of_supply(r["on_hand"], scen_demand / 7), 999.0) if scen_demand > 0 else 999.0
        lt = r["lead_time"] + lt_extra
        if scen_dos < lt or r["on_hand"] < r["rop"] * 0.5:
            scen_status = "Critical"
        elif r["on_hand"] < r["rop"] or scen_dos < lt * 1.5:
            scen_status = "Reorder Soon"
        elif scen_dos < lt * 2 or r["on_hand"] < r["rop"] * 1.2:
            scen_status = "Watch"
        else:
            scen_status = "Healthy"
        sku_table.append({
            "product_name": r["product_name"],
            "category_label": r["category_label"],
            "baseline_status": r["status"],
            "scenario_status": scen_status,
            "demand_delta": round(scen_demand - r["avg_weekly_demand"], 1),
            "changed": scen_status != r["status"],
        })

    return {
        "categories": [
            {"key": cat, "label": config.SKU_CATEGORIES.get(cat, cat),
             "base": round(base, 1), "adjusted": round(adjusted_cat.get(cat, base), 1)}
            for cat, base in cat_base.items()
        ],
        "sku_table": sku_table,
        "summary": {
            "label": label,
            "description": description,
            "demand_index": round(total_adjusted / total_base, 2) if total_base else 1.0,
            "total_shift_pct": round((total_adjusted - total_base) / total_base * 100, 1) if total_base else 0.0,
            "lead_time_extra": lt_extra,
            "n_changed": sum(1 for row in sku_table if row["changed"]),
        },
    }


def _generate_llm(prompt: str) -> str:
    """Join the Groq stream into one string. Isolated so tests can monkeypatch."""
    return "".join(generate_brief_streaming(prompt))


# The brief is identical for every visitor, so cache it briefly — this keeps a
# burst of visitors (or a scripted flood) from each triggering a Groq call.
_BRIEF_TTL = 600  # seconds
_brief_cache = {"t": 0.0, "v": None}
_brief_lock = threading.Lock()


@app.post("/api/brief")
def brief(req: BriefReq = BriefReq()):
    if not req.refresh:
        with _brief_lock:
            if _brief_cache["v"] is not None and time.time() - _brief_cache["t"] < _BRIEF_TTL:
                return _brief_cache["v"]
    result = _build_brief()
    with _brief_lock:
        _brief_cache["t"], _brief_cache["v"] = time.time(), result
    return result


def _build_brief():
    state = engine.get_state()
    ctx = engine.build_brief_context(state)
    web_reports = engine.load_web_reports()[:3]
    prompt = build_brief_prompt(
        conditions=ctx["conditions_ctx"],
        inventory_summary=ctx["inv_summary"],
        social_velocity=state["social"]["velocity"],
        trend_alerts=[],
        tournaments=[],
        active_scenario=None,
        service_level=state["service_pct"],
        critical_skus=ctx["critical_skus"],
        social_posts=ctx["dave_posts"],
        web_reports=web_reports,
    )
    try:
        text = _generate_llm(prompt)
        source = "groq"
    except Exception:
        text = fallback_buyer_brief(state["recs"], state["species_now"], state["fishing_score"])
        source = "fallback"
    return {"text": text, "source": source,
            "generated_at": clock.now_local().strftime("%I:%M %p"),
            "badges": {
                "moon": state["cond"]["today_phase"].replace("_", " ").title(),
                "water_temp": round(state["cond"]["water_temp"]),
                "pressure": ("Unavailable" if _weather_down(state["cond"])
                             else state["cond"]["weather"]["pressure_trend"].capitalize()),
                "fishing_score": state["fishing_score"],
                "social": (state["social"]["velocity"].capitalize()
                           if state["social"]["velocity"] else "Unavailable"),
            }}


@app.post("/api/ask")
def ask(req: AskReq):
    question = req.question.strip()[:300]
    if not question:
        raise HTTPException(status_code=422, detail="question is required")
    state = engine.get_state()
    ctx = engine.build_brief_context(state)
    prompt = build_ask_dave_prompt(question, ctx["conditions_ctx"],
                                   state["social"]["velocity"], state["species_now"])
    try:
        text = _generate_llm(prompt)
        source = "groq"
    except Exception:
        # The deterministic path is real supply-chain output (urgency, days of
        # supply vs lead time, species activity), not an error state, so it is
        # not framed as one. The response still reports source="fallback", so
        # nothing is hidden from anyone reading the API.
        text = ("Based on the current numbers: "
                + fallback_buyer_brief(state["recs"], state["species_now"], state["fishing_score"]))
        source = "fallback"
    return {"text": text, "source": source}


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
