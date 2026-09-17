"""Dave must not narrate a barometer reading that no feed supplied.

The signal strip, the barometer panel and the brief badges already say
"unavailable" when the weather feed is down. The brief text did not: the engine
substitutes a literal "stable" to keep `pressure_trend` a string for
get_fishing_score, and that placeholder reached the prompt, so a live brief read
"Barometric pressure is stable, which supports a consistent bite" on a load
whose own badge said Unavailable.
"""
from ai.brief import _conditions_summary, build_ask_dave_prompt, build_brief_prompt


_INV = {"Bait": {"dos": 4.0, "urgency": "Order Today", "critical_skus": 2}}


def _prompt(pressure_trend):
    return build_brief_prompt(
        conditions={"moon_phase": "waning_gibbous", "tide_quality": "prime",
                    "pressure_trend": pressure_trend, "water_temp": 68.4,
                    "fishing_score": 70, "species": {"Striped Bass": "Good"}},
        inventory_summary=_INV,
        social_velocity="baseline",
        trend_alerts=[],
        tournaments=[],
        critical_skus=[],
        social_posts=[],
    )


def test_summary_says_unavailable_rather_than_inventing_stable():
    line = _conditions_summary({"moon_phase": "full", "tide_quality": "prime",
                                "pressure_trend": None, "water_temp": 60.0,
                                "fishing_score": 70})
    assert "unavailable" in line
    assert "pressure stable" not in line


def test_summary_still_reports_a_real_trend():
    line = _conditions_summary({"moon_phase": "full", "tide_quality": "prime",
                                "pressure_trend": "falling", "water_temp": 60.0,
                                "fishing_score": 70})
    assert "pressure falling" in line


def test_prompt_tells_the_model_not_to_describe_pressure_when_it_is_missing():
    p = _prompt(None)
    assert "unavailable" in p.lower()
    # The interpretation key would otherwise invite the model to pick one.
    assert "do not describe" in p.lower()


def test_prompt_keeps_the_interpretation_key_when_pressure_is_real():
    p = _prompt("falling")
    assert "falling = fish feed aggressively" in p
    assert "do not describe" not in p.lower()


def test_a_missing_key_is_still_treated_as_unavailable_not_as_stable():
    line = _conditions_summary({"moon_phase": "full", "tide_quality": "prime",
                                "water_temp": 60.0, "fishing_score": 70})
    assert "unavailable" in line


# --- the engine boundary ---------------------------------------------------

def test_build_brief_context_hands_dave_a_null_trend_when_weather_is_degraded():
    """`load_conditions` substitutes a literal "stable" so get_fishing_score and
    SIGNAL_MULTIPLIERS keep working on a dead feed. That placeholder is an
    internal contract, not a reading, and must not cross into Dave's prompt."""
    import engine
    state = {
        "recs": [],
        "cond": {
            "today_phase": "full", "tide_quality": "prime", "water_temp": 60.0,
            "fishing_score": 70, "degraded": ["weather", "forecast"],
            "weather": {"pressure_trend": "stable"},
        },
        "species_now": {"Striped Bass": "Good"},
        "social": {"posts": []},
    }
    ctx = engine.build_brief_context(state)
    assert ctx["conditions_ctx"]["pressure_trend"] is None


def test_build_brief_context_passes_a_real_trend_through_untouched():
    import engine
    state = {
        "recs": [],
        "cond": {
            "today_phase": "full", "tide_quality": "prime", "water_temp": 60.0,
            "fishing_score": 70, "degraded": [],
            "weather": {"pressure_trend": "falling"},
        },
        "species_now": {"Striped Bass": "Good"},
        "social": {"posts": []},
    }
    ctx = engine.build_brief_context(state)
    assert ctx["conditions_ctx"]["pressure_trend"] == "falling"


# --- the social feed, same rule as the barometer ---------------------------

def test_prompt_says_the_social_feed_is_unavailable_rather_than_baseline():
    p = build_brief_prompt(
        conditions={"moon_phase": "full", "tide_quality": "prime",
                    "pressure_trend": "falling", "water_temp": 60.0,
                    "fishing_score": 70, "species": {}},
        inventory_summary=_INV, social_velocity=None,
        trend_alerts=[], tournaments=[], critical_skus=[], social_posts=[])
    low = p.lower()
    assert "unavailable" in low
    assert "baseline" not in low


def test_ask_dave_prompt_also_declines_to_invent_a_velocity():
    p = build_ask_dave_prompt("what should I order?",
                              {"moon_phase": "full", "tide_quality": "prime",
                               "pressure_trend": "falling", "water_temp": 60.0,
                               "fishing_score": 70}, None, {})
    assert "unavailable" in p.lower()


def test_ask_prompt_lists_stocked_products_and_limits_recommendations():
    prompt = build_ask_dave_prompt(
        "What bait for stripers?",
        {"moon_phase": "full", "tide_quality": "prime", "pressure_trend": "falling",
         "water_temp": 60.0, "fishing_score": 70},
        "baseline", {"Striped Bass": "Good"},
        products=["Bloodworms — Dozen", "Spro Bucktail Jig 1oz — White"],
    )
    assert "Bloodworms — Dozen" in prompt
    assert "Only recommend products from this list" in prompt


def test_ask_prompt_with_no_products_has_a_blank_line_before_the_question():
    prompt = build_ask_dave_prompt(
        "What bait for stripers?",
        {"moon_phase": "full", "tide_quality": "prime", "pressure_trend": "falling",
         "water_temp": 60.0, "fishing_score": 70},
        "baseline", {"Striped Bass": "Good"},
    )
    lines = prompt.split("\n")
    social_idx = next(i for i, l in enumerate(lines) if l.startswith("Social signal:"))
    assert lines[social_idx + 1] == ""
    assert lines[social_idx + 2].startswith("Question:")
