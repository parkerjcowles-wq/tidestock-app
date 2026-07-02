import datetime
import requests
import pandas as pd

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

_WMO_EMOJI = {
    0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️",
    51: "🌦️", 53: "🌦️", 55: "🌧️",
    61: "🌧️", 63: "🌧️", 65: "🌧️",
    71: "🌨️", 73: "🌨️", 75: "❄️",
    80: "🌦️", 81: "🌧️", 82: "⛈️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}


def weather_code_to_emoji(code: int) -> str:
    return _WMO_EMOJI.get(code, "🌥️")


def fetch_weather(lat: float, lon: float) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "pressure_msl,temperature_2m,wind_speed_10m",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "forecast_days": 3,
    }
    r = requests.get(_OPEN_METEO_URL, params=params, timeout=10)
    r.raise_for_status()
    hourly = r.json()["hourly"]
    df = pd.DataFrame({
        "time":     pd.to_datetime(hourly["time"]),
        "pressure": hourly["pressure_msl"],
        "temp_f":   hourly["temperature_2m"],
        "wind_mph": hourly["wind_speed_10m"],
    })
    pressures = df["pressure"].tolist()
    return {
        "pressure_series":   df[["time", "pressure"]],
        "current_temp_f":    df["temp_f"].iloc[0],
        "current_wind_mph":  df["wind_mph"].iloc[0],
        "pressure_trend":    classify_pressure_trend(pressures[:12]),
    }


def fetch_7day_forecast(lat: float, lon: float) -> list:
    params = {
        "latitude":       lat,
        "longitude":      lon,
        "daily": (
            "temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max,wind_speed_10m_max,weather_code"
        ),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit":  "mph",
        "forecast_days":    7,
        "timezone":         "America/New_York",
    }
    r = requests.get(_OPEN_METEO_URL, params=params, timeout=10)
    r.raise_for_status()
    d = r.json()["daily"]
    forecast = []
    for i in range(7):
        date_str = d["time"][i]
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        is_weekend = dt.weekday() >= 5
        forecast.append({
            "date":       date_str,
            "dow":        dt.strftime("%a"),
            "is_weekend": is_weekend,
            "temp_max":   d["temperature_2m_max"][i],
            "temp_min":   d["temperature_2m_min"][i],
            "precip_pct": d["precipitation_probability_max"][i],
            "wind_mph":   d["wind_speed_10m_max"][i],
            "code":       d["weather_code"][i],
            "emoji":      weather_code_to_emoji(d["weather_code"][i]),
        })
    return forecast


def compute_weather_demand_mult(forecast: list) -> float:
    """Return demand multiplier (0.65–1.35) from 7-day forecast.

    Good fishing weather (clear, mild, low wind) boosts demand.
    Rain, extreme temps, or high wind suppress it.
    Weekend days weighted 2× since bait shop traffic peaks Fri–Sun.
    """
    if not forecast:
        return 1.0
    total_weight = 0.0
    weighted_sum = 0.0
    for day in forecast:
        mult = 1.0
        precip = day.get("precip_pct", 0) or 0
        temp   = day.get("temp_max", 65) or 65
        wind   = day.get("wind_mph", 10) or 10

        if precip > 70:
            mult *= 0.72
        elif precip > 40:
            mult *= 0.88

        if 52 <= temp <= 76:
            mult *= 1.12
        elif temp < 42 or temp > 88:
            mult *= 0.90

        if wind > 25:
            mult *= 0.85
        elif wind > 18:
            mult *= 0.93

        weight = 2.0 if day.get("is_weekend") else 1.0
        weighted_sum  += mult * weight
        total_weight  += weight

    return round(weighted_sum / total_weight, 3) if total_weight else 1.0


def classify_pressure_trend(pressures: list) -> str:
    if len(pressures) < 2:
        return "stable"
    delta = pressures[-1] - pressures[0]
    if delta > 1.5:
        return "rising"
    if delta < -1.5:
        return "falling"
    return "stable"
