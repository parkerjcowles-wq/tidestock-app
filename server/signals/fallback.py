import pandas as pd


def fallback_conditions() -> dict:
    return {
        "tide_df": pd.DataFrame(columns=["time", "height"]),
        "water_temp": 55.0,
        "weather": {
            "pressure_series": pd.DataFrame(columns=["time", "pressure"]),
            "current_temp_f": 65.0,
            "current_wind_mph": 0.0,
            "pressure_trend": "stable",
        },
        "week_moon": [],
        "today_phase": "waxing_crescent",
        "tide_quality": "moderate",
        "fishing_score": 50,
    }
