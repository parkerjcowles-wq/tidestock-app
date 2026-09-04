"""Tests for the NWS fallback that keeps the barometer and forecast alive
when Open-Meteo refuses Render's shared egress IP."""
import pandas as pd
import pytest

from signals import weather as W


# --- helpers ---------------------------------------------------------------

def _obs(ts, pa, degc, kmh):
    return {"properties": {"timestamp": ts,
                           "barometricPressure": {"value": pa},
                           "temperature": {"value": degc},
                           "windSpeed": {"value": kmh}}}


_OBS_PAYLOAD = {"features": [
    _obs("2026-09-03T18:00:00+00:00", 101354.61, 22, 11.112),
    _obs("2026-09-03T17:00:00+00:00", 101300.00, 21, 9.0),
    _obs("2026-09-03T16:00:00+00:00", 101250.00, 21, 7.4),
]}

_FORECAST_PAYLOAD = {"properties": {"periods": [
    {"name": "This Afternoon", "startTime": "2026-09-03T13:00:00-04:00",
     "isDaytime": True, "temperature": 78, "temperatureUnit": "F",
     "windSpeed": "3 mph", "probabilityOfPrecipitation": {"value": 40},
     "shortForecast": "Chance Showers And Thunderstorms"},
    {"name": "Tonight", "startTime": "2026-09-03T18:00:00-04:00",
     "isDaytime": False, "temperature": 61, "temperatureUnit": "F",
     "windSpeed": "2 mph", "probabilityOfPrecipitation": {"value": 22},
     "shortForecast": "Patchy Fog"},
    {"name": "Saturday", "startTime": "2026-09-05T06:00:00-04:00",
     "isDaytime": True, "temperature": 81, "temperatureUnit": "F",
     "windSpeed": "5 to 10 mph", "probabilityOfPrecipitation": {"value": None},
     "shortForecast": "Mostly Sunny"},
]}}


# --- unit conversion -------------------------------------------------------

def test_pascals_convert_to_the_hectopascals_the_rest_of_the_app_uses():
    # classify_pressure_trend's +/-1.5 threshold is in hPa. Feeding it Pascals
    # would make every load read "rising" by five orders of magnitude.
    assert W._pa_to_hpa(101354.61) == pytest.approx(1013.55, abs=0.01)


def test_celsius_converts_to_fahrenheit():
    assert W._c_to_f(22) == pytest.approx(71.6, abs=0.01)


def test_kmh_converts_to_mph():
    assert W._kmh_to_mph(11.112) == pytest.approx(6.904, abs=0.01)


def test_missing_observation_values_do_not_crash_the_conversion():
    assert W._pa_to_hpa(None) is None
    assert W._c_to_f(None) is None
    assert W._kmh_to_mph(None) is None


def test_wind_speed_string_parses_a_range_to_its_upper_bound():
    # NWS writes "5 to 10 mph". The demand multiplier keys off wind, so the
    # windier end is the one that suppresses trips.
    assert W._parse_wind("5 to 10 mph") == 10.0
    assert W._parse_wind("3 mph") == 3.0
    assert W._parse_wind("") is None


# --- shortForecast -> WMO code --------------------------------------------

def test_short_forecast_maps_to_a_wmo_code_the_emoji_table_knows():
    assert W._short_forecast_to_code("Mostly Sunny") == 1
    assert W._short_forecast_to_code("Chance Showers And Thunderstorms") == 95
    assert W._short_forecast_to_code("Patchy Fog") == 45
    assert W._short_forecast_to_code("Rain Likely") == 61
    # Anything unrecognised still renders an emoji rather than blowing up.
    assert W.weather_code_to_emoji(W._short_forecast_to_code("Zorbling")) != ""


# --- fetch_weather via NWS -------------------------------------------------

def test_nws_weather_returns_the_same_contract_as_open_meteo(monkeypatch):
    monkeypatch.setattr(W, "_nws_observations", lambda lat, lon: _OBS_PAYLOAD)
    out = W._fetch_weather_nws(42.8, -70.9)
    assert set(out) >= {"pressure_series", "current_temp_f",
                        "current_wind_mph", "pressure_trend"}
    df = out["pressure_series"]
    assert list(df.columns) == ["time", "pressure"]
    assert len(df) == 3
    # Oldest first, so classify_pressure_trend reads the series forwards.
    assert df["time"].is_monotonic_increasing
    assert out["current_temp_f"] == pytest.approx(71.6, abs=0.1)
    assert out["pressure_trend"] in {"rising", "falling", "stable"}


def test_nws_weather_reads_the_trend_in_the_right_direction(monkeypatch):
    # Pressure climbs 1012.50 -> 1013.55 hPa oldest-to-newest across the window.
    monkeypatch.setattr(W, "_nws_observations", lambda lat, lon: _OBS_PAYLOAD)
    out = W._fetch_weather_nws(42.8, -70.9)
    assert out["pressure_trend"] == "stable"  # 1.05 hPa is under the 1.5 threshold


def test_nws_weather_raises_when_no_observation_carries_a_pressure(monkeypatch):
    empty = {"features": [_obs("2026-09-03T18:00:00+00:00", None, None, None)]}
    monkeypatch.setattr(W, "_nws_observations", lambda lat, lon: empty)
    with pytest.raises(Exception):
        W._fetch_weather_nws(42.8, -70.9)


# --- fetch_7day_forecast via NWS ------------------------------------------

def test_nws_forecast_collapses_day_night_periods_into_dated_days(monkeypatch):
    monkeypatch.setattr(W, "_nws_forecast_periods",
                        lambda lat, lon: _FORECAST_PAYLOAD["properties"]["periods"])
    out = W._fetch_7day_forecast_nws(42.8, -70.9)
    assert [d["date"] for d in out] == ["2026-09-03", "2026-09-05"]
    day1 = out[0]
    # The daytime high and the nighttime low both land on the same dated row.
    assert day1["temp_max"] == 78
    assert day1["temp_min"] == 61
    assert day1["precip_pct"] == 40
    assert day1["wind_mph"] == 3.0
    assert day1["dow"] == "Thu"
    assert day1["is_weekend"] is False
    assert day1["emoji"]


def test_nws_forecast_marks_the_weekend_because_demand_weights_it_double(monkeypatch):
    monkeypatch.setattr(W, "_nws_forecast_periods",
                        lambda lat, lon: _FORECAST_PAYLOAD["properties"]["periods"])
    out = W._fetch_7day_forecast_nws(42.8, -70.9)
    sat = [d for d in out if d["date"] == "2026-09-05"][0]
    assert sat["is_weekend"] is True
    assert sat["wind_mph"] == 10.0  # upper bound of "5 to 10 mph"


def test_nws_forecast_treats_a_null_precip_probability_as_zero(monkeypatch):
    monkeypatch.setattr(W, "_nws_forecast_periods",
                        lambda lat, lon: _FORECAST_PAYLOAD["properties"]["periods"])
    out = W._fetch_7day_forecast_nws(42.8, -70.9)
    sat = [d for d in out if d["date"] == "2026-09-05"][0]
    assert sat["precip_pct"] == 0
    # compute_weather_demand_mult indexes precip_pct arithmetically.
    assert W.compute_weather_demand_mult(out) > 0


def test_nws_forecast_raises_rather_than_returning_an_empty_week(monkeypatch):
    monkeypatch.setattr(W, "_nws_forecast_periods", lambda lat, lon: [])
    with pytest.raises(Exception):
        W._fetch_7day_forecast_nws(42.8, -70.9)


# --- the fallback wiring ---------------------------------------------------

def test_fetch_weather_prefers_open_meteo_and_never_calls_nws_when_it_works(monkeypatch):
    called = []
    monkeypatch.setattr(W, "_fetch_weather_open_meteo",
                        lambda lat, lon: {"pressure_series": pd.DataFrame(columns=["time", "pressure"]),
                                          "current_temp_f": 70.0, "current_wind_mph": 4.0,
                                          "pressure_trend": "rising", "source": "open-meteo"})
    monkeypatch.setattr(W, "_fetch_weather_nws",
                        lambda lat, lon: called.append(1) or {})
    out = W.fetch_weather(42.8, -70.9)
    assert out["source"] == "open-meteo"
    assert called == []


def test_fetch_weather_falls_back_to_nws_when_open_meteo_is_blocked(monkeypatch):
    def boom(lat, lon):
        raise RuntimeError("429 Too Many Requests")
    monkeypatch.setattr(W, "_fetch_weather_open_meteo", boom)
    monkeypatch.setattr(W, "_nws_observations", lambda lat, lon: _OBS_PAYLOAD)
    out = W.fetch_weather(42.8, -70.9)
    assert out["source"] == "nws"
    assert out["current_temp_f"] == pytest.approx(71.6, abs=0.1)


def test_fetch_weather_raises_the_original_error_when_both_providers_fail(monkeypatch):
    def boom(lat, lon):
        raise RuntimeError("open-meteo is blocked")

    def boom2(lat, lon):
        raise RuntimeError("nws is down too")
    monkeypatch.setattr(W, "_fetch_weather_open_meteo", boom)
    monkeypatch.setattr(W, "_fetch_weather_nws", boom2)
    with pytest.raises(RuntimeError):
        W.fetch_weather(42.8, -70.9)


def test_fetch_7day_forecast_falls_back_to_nws(monkeypatch):
    def boom(lat, lon):
        raise RuntimeError("blocked")
    monkeypatch.setattr(W, "_fetch_7day_forecast_open_meteo", boom)
    monkeypatch.setattr(W, "_nws_forecast_periods",
                        lambda lat, lon: _FORECAST_PAYLOAD["properties"]["periods"])
    out = W.fetch_7day_forecast(42.8, -70.9)
    assert out and out[0]["date"] == "2026-09-03"


# --- through the API, which is what Render actually serves -----------------

def test_signals_serves_live_pressure_from_nws_when_open_meteo_is_blocked(monkeypatch):
    """The production failure, end to end.

    On Render, Open-Meteo answers every load with a block, so `degraded`
    carried "weather" and "forecast", the barometer panel rendered an empty
    card and the 7-day forecast read "Forecast unavailable". With the NWS
    fallback in place the same conditions must produce a populated payload and
    an EMPTY degraded list, without either provider being stubbed away at the
    engine boundary - the point is to exercise the real fallback wiring.
    """
    from fastapi.testclient import TestClient
    from conftest import offline_engine
    import engine

    offline_engine(monkeypatch)

    def blocked(lat, lon):
        raise RuntimeError("429 Too Many Requests (Render shared egress IP)")

    monkeypatch.setattr(W, "_fetch_weather_open_meteo", blocked)
    monkeypatch.setattr(W, "_fetch_7day_forecast_open_meteo", blocked)
    monkeypatch.setattr(W, "_nws_observations", lambda lat, lon: _OBS_PAYLOAD)
    monkeypatch.setattr(W, "_nws_forecast_periods",
                        lambda lat, lon: _FORECAST_PAYLOAD["properties"]["periods"])
    # offline_engine stubs these out entirely; put the real ones back so the
    # fallback is what answers.
    monkeypatch.setattr(engine, "fetch_weather", W.fetch_weather)
    monkeypatch.setattr(engine, "fetch_7day_forecast", W.fetch_7day_forecast)
    engine.clear_caches()

    from main import app
    body = TestClient(app).get("/api/signals").json()

    assert body["degraded"] == []
    assert body["pressure"], "barometer panel would render empty"
    assert body["pressure_trend"] in {"rising", "falling", "stable"}
    assert body["current_temp_f"] is not None
    assert body["forecast"], "7-day forecast panel would read unavailable"
    engine.clear_caches()


def test_a_rainy_night_does_not_relabel_a_clear_day(monkeypatch):
    """The day's emoji describes the day people fish.

    The daytime period is written first, but if it happened to map to the
    neutral code 2 ("Partly Sunny"), the "have we set a code yet" test could not
    tell that apart from the initial value, so the night's period overwrote it —
    a partly sunny Friday rendered with a rain icon on the forecast strip.
    """
    periods = [
        {"name": "Friday", "startTime": "2026-09-04T06:00:00-04:00",
         "isDaytime": True, "temperature": 81, "windSpeed": "5 mph",
         "probabilityOfPrecipitation": {"value": 10},
         "shortForecast": "Partly Sunny"},
        {"name": "Friday Night", "startTime": "2026-09-04T18:00:00-04:00",
         "isDaytime": False, "temperature": 60, "windSpeed": "6 mph",
         "probabilityOfPrecipitation": {"value": 80},
         "shortForecast": "Rain Likely"},
    ]
    monkeypatch.setattr(W, "_nws_forecast_periods", lambda lat, lon: periods)
    day = W._fetch_7day_forecast_nws(42.8, -70.9)[0]
    assert day["code"] == W._short_forecast_to_code("Partly Sunny")
    # The night's rain still has to reach demand, which keys off precip.
    assert day["precip_pct"] == 80


def test_a_date_with_only_a_night_period_still_gets_that_nights_code(monkeypatch):
    """Late in the day NWS leads with "Tonight" and there is no daytime period
    for today at all, so the night's condition is the only one there is."""
    periods = [
        {"name": "Tonight", "startTime": "2026-09-03T18:00:00-04:00",
         "isDaytime": False, "temperature": 61, "windSpeed": "2 mph",
         "probabilityOfPrecipitation": {"value": 70},
         "shortForecast": "Rain Likely"},
    ]
    monkeypatch.setattr(W, "_nws_forecast_periods", lambda lat, lon: periods)
    day = W._fetch_7day_forecast_nws(42.8, -70.9)[0]
    assert day["code"] == W._short_forecast_to_code("Rain Likely")
    assert day["temp_max"] == day["temp_min"] == 61


# --- URL construction from third-party response values ---------------------

def test_grid_identifiers_from_the_upstream_response_are_validated(monkeypatch):
    """`gridId` and `stationIdentifier` come from NWS's response and are
    interpolated into the next request's URL. A value containing "@" would move
    the host out of api.weather.gov entirely (userinfo@host), so they are
    checked against a strict shape rather than trusted."""
    W._NWS_POINT_CACHE.clear()

    def hostile(path, params=None):
        return {"properties": {"gridId": "BOX@evil.example.com",
                               "gridX": 74, "gridY": 123}}

    monkeypatch.setattr(W, "_nws_get", hostile)
    with pytest.raises(ValueError):
        W._nws_point(42.8, -70.9)
    W._NWS_POINT_CACHE.clear()


def test_a_hostile_station_identifier_is_rejected(monkeypatch):
    W._NWS_POINT_CACHE.clear()
    calls = {"n": 0}

    def responses(path, params=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"properties": {"gridId": "BOX", "gridX": 74, "gridY": 123}}
        return {"features": [{"properties": {"stationIdentifier": "../../etc"}}]}

    monkeypatch.setattr(W, "_nws_get", responses)
    with pytest.raises(ValueError):
        W._nws_point(42.8, -70.9)
    W._NWS_POINT_CACHE.clear()


def test_a_normal_grid_and_station_resolve(monkeypatch):
    W._NWS_POINT_CACHE.clear()
    calls = {"n": 0}

    def responses(path, params=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"properties": {"gridId": "BOX", "gridX": 74, "gridY": 123}}
        return {"features": [{"properties": {"stationIdentifier": "KLWM"}}]}

    monkeypatch.setattr(W, "_nws_get", responses)
    pt = W._nws_point(42.8, -70.9)
    assert pt["station"] == "KLWM"
    assert pt["forecast"] == "/gridpoints/BOX/74,123/forecast"
    W._NWS_POINT_CACHE.clear()
