import datetime
import logging
import re
import time

import requests
import pandas as pd

log = logging.getLogger("tidestock.weather")

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo's free tier meters by source IP, and on Render the app shares an
# egress IP with every other free instance on the host — so a 429 here is a
# neighbour's traffic, not this app's. It arrived as a silent fallback: an
# empty barometer panel and a "0 mph" wind reading captioned as live. The same
# shared-IP identity is already why Reddit answers this app 403.
#
# One retry after a short pause clears the transient case; a hard block still
# falls through to the caller's fallback, but now with a logged status line
# saying which it was.
_RETRIES = 2
_BACKOFF_SECONDS = 1.5
_TIMEOUT = 15
# Default python-requests UA is what a bot filter blocks first. Identify the
# app honestly instead.
_HEADERS = {"User-Agent": "TideStock/1.0 (bait-shop demand dashboard; contact via github.com/parkerjcowles-wq)"}


def _get_json(params: dict) -> dict:
    """GET Open-Meteo with one retry, logging the status that made it fail."""
    last = None
    for attempt in range(_RETRIES):
        try:
            r = requests.get(_OPEN_METEO_URL, params=params,
                             timeout=_TIMEOUT, headers=_HEADERS)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            status = getattr(getattr(e, "response", None), "status_code", None)
            log.warning("open-meteo attempt %d/%d failed (status=%s): %s",
                        attempt + 1, _RETRIES, status, e)
            if attempt + 1 < _RETRIES:
                time.sleep(_BACKOFF_SECONDS)
    raise last

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


def _fetch_weather_open_meteo(lat: float, lon: float) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "pressure_msl,temperature_2m,wind_speed_10m",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "forecast_days": 3,
    }
    hourly = _get_json(params)["hourly"]
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
        "source":            "open-meteo",
    }


def _fetch_7day_forecast_open_meteo(lat: float, lon: float) -> list:
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
    d = _get_json(params)["daily"]
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


# --- NWS fallback (api.weather.gov) ----------------------------------------
#
# Open-Meteo meters by source IP and hard-blocks Render's shared free-tier
# egress, so on the deployed app `_fetch_weather_open_meteo` fails every load
# while working fine from a laptop. Retries and an honest User-Agent were tried
# first (see `_get_json` above) and did not clear it: the block is persistent,
# not transient, and the same shared-IP identity is why Reddit answers 403.
#
# api.weather.gov is the fallback because it is the one provider already proven
# to answer THIS deployment: NOAA's tide and water-temperature endpoints run
# from the same egress IP on every load and have never been blocked. It is
# free, keyless, and covers Newburyport. It also carries better evidence than
# the primary for the barometer specifically — Open-Meteo models pressure,
# while NWS reports what a nearby station actually measured.
#
# It is second rather than first because Open-Meteo remains the better source
# for a forward FORECAST series and needs one request where NWS needs three,
# so a working Open-Meteo is still preferred wherever it is reachable.

_NWS_BASE = "https://api.weather.gov"
_NWS_HEADERS = {
    "User-Agent": "TideStock/1.0 (bait-shop demand dashboard; contact via github.com/parkerjcowles-wq)",
    "Accept": "application/geo+json",
}
# Open-Meteo returned three days of hourly pressure. NWS reports every ~5
# minutes, so the window is asked for in HOURS and thinned to one sample per
# hour afterwards: 30 hours of raw samples is ~370 points and ~1.5 MB on the
# wire, which is fine once an hour behind the TTL cache but is not a chart and
# is not something to hand the browser.
_NWS_OBS_HOURS = 30
_NWS_OBS_LIMIT = 500


def _pa_to_hpa(value):
    """NWS reports pressure in Pascals; the rest of this app speaks hPa.

    classify_pressure_trend's +/-1.5 threshold is in hPa, so handing it Pascals
    would report a violent front on every load.
    """
    return None if value is None else round(value / 100.0, 2)


def _c_to_f(value):
    return None if value is None else round(value * 9.0 / 5.0 + 32.0, 1)


def _kmh_to_mph(value):
    return None if value is None else round(value * 0.621371, 3)


def _parse_wind(text):
    """Pull an mph number out of an NWS wind string.

    NWS writes wind as prose ("5 to 10 mph"), not a number. The upper bound is
    the one taken: compute_weather_demand_mult suppresses demand above 18 and
    25 mph, and it is the gusty end of the range that keeps people off the water.
    """
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text or "")]
    return max(nums) if nums else None


# NWS gives a prose `shortForecast` where Open-Meteo gives a WMO code. Mapping
# back to WMO keeps `weather_code_to_emoji` and every downstream consumer
# unchanged — the fallback is invisible above this module. Ordered most
# specific first: "Chance Showers And Thunderstorms" must match thunder, not
# showers.
_SHORT_FORECAST_CODES = (
    ("thunder", 95),
    ("fog", 45),
    ("snow", 71),
    ("sleet", 71),
    ("freezing", 71),
    ("rain shower", 80),
    ("showers", 80),
    ("shower", 80),
    ("rain", 61),
    ("drizzle", 51),
    ("mostly cloudy", 3),
    ("partly cloudy", 2),
    ("mostly sunny", 1),
    ("partly sunny", 2),
    ("mostly clear", 1),
    ("cloudy", 3),
    ("overcast", 3),
    ("sunny", 0),
    ("clear", 0),
)


def _short_forecast_to_code(text: str) -> int:
    low = (text or "").lower()
    for needle, code in _SHORT_FORECAST_CODES:
        if needle in low:
            return code
    return 2  # unknown reads as partly cloudy, which is the neutral multiplier


def _nws_get(path: str, params: dict = None) -> dict:
    r = requests.get(f"{_NWS_BASE}{path}", params=params or {},
                     timeout=_TIMEOUT, headers=_NWS_HEADERS)
    r.raise_for_status()
    return r.json()


# `gridId` and `stationIdentifier` arrive in a third-party response and are
# interpolated into the URL of the NEXT request. A value carrying "@" would
# reparse api.weather.gov as userinfo and send the request to whatever followed,
# so both are held to the shape NWS actually uses (office codes like "BOX",
# ICAO-ish station ids like "KLWM") instead of being trusted.
_NWS_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}$")


def _checked_id(value, what: str) -> str:
    text = str(value or "")
    if not _NWS_ID_RE.match(text):
        raise ValueError(f"NWS returned an unusable {what}: {text!r}")
    return text


def _nws_point(lat: float, lon: float) -> dict:
    """Resolve a lat/lon to NWS's grid and its nearest observation station.

    Cached for the process lifetime: the grid for a fixed bait shop never
    changes, and this would otherwise cost an extra round trip on every load.
    """
    key = (round(lat, 4), round(lon, 4))
    if key not in _NWS_POINT_CACHE:
        props = _nws_get(f"/points/{key[0]},{key[1]}")["properties"]
        grid_id = _checked_id(props.get("gridId"), "gridId")
        grid_x, grid_y = int(props["gridX"]), int(props["gridY"])
        stations = _nws_get(
            f"/gridpoints/{grid_id}/{grid_x},{grid_y}/stations"
        )["features"]
        if not stations:
            raise ValueError("NWS returned no observation station for this grid")
        station = _checked_id(
            stations[0]["properties"].get("stationIdentifier"), "stationIdentifier")
        _NWS_POINT_CACHE[key] = {
            "forecast": f"/gridpoints/{grid_id}/{grid_x},{grid_y}/forecast",
            "station": station,
        }
    return _NWS_POINT_CACHE[key]


_NWS_POINT_CACHE = {}


def _nws_observations(lat: float, lon: float) -> dict:
    station = _nws_point(lat, lon)["station"]
    start = (datetime.datetime.utcnow()
             - datetime.timedelta(hours=_NWS_OBS_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _nws_get(f"/stations/{station}/observations",
                    {"start": start, "limit": _NWS_OBS_LIMIT})


def _nws_forecast_periods(lat: float, lon: float) -> list:
    return _nws_get(_nws_point(lat, lon)["forecast"])["properties"]["periods"]


def _fetch_weather_nws(lat: float, lon: float) -> dict:
    """Same contract as `_fetch_weather_open_meteo`, from measured observations."""
    feats = _nws_observations(lat, lon).get("features") or []
    rows, temp_f, wind_mph = [], None, None
    for f in feats:
        p = f.get("properties") or {}
        hpa = _pa_to_hpa((p.get("barometricPressure") or {}).get("value"))
        if hpa is not None:
            rows.append({"time": p.get("timestamp"), "pressure": hpa})
        # The feed is newest-first, so the first non-null reading is the current
        # one. A station that drops a single sample must not blank the strip.
        if temp_f is None:
            temp_f = _c_to_f((p.get("temperature") or {}).get("value"))
        if wind_mph is None:
            wind_mph = _kmh_to_mph((p.get("windSpeed") or {}).get("value"))

    if not rows:
        raise ValueError("NWS returned no observation carrying a barometric pressure")

    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    # Oldest first: classify_pressure_trend reads the series forwards and would
    # invert rising/falling on the newest-first order NWS ships.
    df = df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    df["time"] = df["time"].dt.tz_localize(None)
    # Thin ~370 five-minute samples to one an hour. The barometer panel plots a
    # slope, not a seismograph, and this is the shape Open-Meteo already
    # returned, so the chart and every downstream consumer read the same series
    # whichever provider answered.
    # Truncate to the hour with numpy rather than a pandas frequency alias:
    # requirements pin only `pandas>=1.5`, and the spelling of hourly aliases
    # changed across that range.
    df = (df.assign(_hr=df["time"].values.astype("datetime64[h]"))
            .groupby("_hr", as_index=False).last()
            .rename(columns={"_hr": "hour"}))
    df = df[["time", "pressure"]].reset_index(drop=True)

    return {
        "pressure_series":  df[["time", "pressure"]],
        "current_temp_f":   temp_f if temp_f is not None else 65.0,
        "current_wind_mph": wind_mph if wind_mph is not None else 0.0,
        "pressure_trend":   classify_pressure_trend(df["pressure"].tolist()),
        "source":           "nws",
    }


def _fetch_7day_forecast_nws(lat: float, lon: float) -> list:
    """Collapse NWS's day/night periods into the dated daily rows this app uses.

    NWS ships 14 half-day periods where Open-Meteo ships 7 days. A day's high
    comes from its daytime period and its low from the night that follows, so
    both fold onto one dated row keyed by the period's local start date.
    """
    periods = _nws_forecast_periods(lat, lon) or []
    days = {}
    order = []
    for p in periods:
        date_str = (p.get("startTime") or "")[:10]
        if not date_str:
            continue
        if date_str not in days:
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            days[date_str] = {
                "date": date_str,
                "dow": dt.strftime("%a"),
                "is_weekend": dt.weekday() >= 5,
                "temp_max": None, "temp_min": None,
                "precip_pct": 0, "wind_mph": None,
                "code": 2, "emoji": weather_code_to_emoji(2),
                # Whether a DAYTIME period has set the code yet. Without this
                # flag a day whose own condition maps to the neutral code 2 is
                # indistinguishable from a day with no code yet, and the night
                # that follows overwrites it - a partly sunny Friday rendered
                # with the rain icon from Friday Night.
                "_day_code_set": False,
            }
            order.append(date_str)
        row = days[date_str]
        temp = p.get("temperature")
        if temp is not None:
            if p.get("isDaytime"):
                row["temp_max"] = temp if row["temp_max"] is None else max(row["temp_max"], temp)
            else:
                row["temp_min"] = temp if row["temp_min"] is None else min(row["temp_min"], temp)
        # A null probabilityOfPrecipitation means "none forecast", not "unknown";
        # compute_weather_demand_mult does arithmetic on this, so it must be a
        # number rather than None.
        pop = (p.get("probabilityOfPrecipitation") or {}).get("value") or 0
        row["precip_pct"] = max(row["precip_pct"], pop)
        wind = _parse_wind(p.get("windSpeed"))
        if wind is not None:
            row["wind_mph"] = wind if row["wind_mph"] is None else max(row["wind_mph"], wind)
        # The daytime period describes the day people actually fish; a night
        # period only supplies the code when the day has none (which happens
        # for today, once its daytime period has already passed).
        if p.get("isDaytime") or not row["_day_code_set"]:
            row["code"] = _short_forecast_to_code(p.get("shortForecast"))
            row["emoji"] = weather_code_to_emoji(row["code"])
            if p.get("isDaytime"):
                row["_day_code_set"] = True

    out = []
    for d in order[:7]:
        row = days[d]
        # A day with only a night period still needs both ends filled, because
        # compute_weather_demand_mult and the frontend both read them directly.
        if row["temp_max"] is None:
            row["temp_max"] = row["temp_min"]
        if row["temp_min"] is None:
            row["temp_min"] = row["temp_max"]
        if row["wind_mph"] is None:
            row["wind_mph"] = 0.0
        row.pop("_day_code_set", None)
        out.append(row)

    if not out:
        raise ValueError("NWS returned no forecast periods")
    return out


def fetch_weather(lat: float, lon: float) -> dict:
    """Open-Meteo, falling back to NWS when it is unreachable.

    Raises only when BOTH providers fail, which `engine.load_conditions`
    still catches and reports through `degraded`.
    """
    try:
        return _fetch_weather_open_meteo(lat, lon)
    except Exception as primary:
        log.warning("open-meteo weather unavailable (%s: %s) - falling back to NWS",
                    type(primary).__name__, primary)
        return _fetch_weather_nws(lat, lon)


def fetch_7day_forecast(lat: float, lon: float) -> list:
    try:
        return _fetch_7day_forecast_open_meteo(lat, lon)
    except Exception as primary:
        log.warning("open-meteo forecast unavailable (%s: %s) - falling back to NWS",
                    type(primary).__name__, primary)
        return _fetch_7day_forecast_nws(lat, lon)
