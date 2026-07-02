import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "server"))


def offline_engine(monkeypatch):
    """Point every external fetcher at a stub so tests never touch the network."""
    import pandas as pd
    import engine

    engine.clear_caches()
    monkeypatch.setattr(engine, "fetch_tide_predictions",
                        lambda *a, **k: pd.DataFrame(columns=["time", "height"]))
    monkeypatch.setattr(engine, "fetch_water_temp", lambda *a, **k: 55.0)
    monkeypatch.setattr(engine, "fetch_weather", lambda *a, **k: {
        "pressure_series": pd.DataFrame(columns=["time", "pressure"]),
        "current_temp_f": 65.0, "current_wind_mph": 0.0, "pressure_trend": "stable"})
    monkeypatch.setattr(engine, "fetch_7day_forecast", lambda *a, **k: [])
    monkeypatch.setattr(engine, "fetch_reddit_signals", lambda *a, **k: [])
    monkeypatch.setattr(engine, "fetch_location_reddit_posts", lambda *a, **k: [])
    monkeypatch.setattr(engine, "fetch_web_fishing_reports", lambda *a, **k: [])
    monkeypatch.setattr(engine, "fetch_tournaments", lambda *a, **k: [])
    # Reset cross-request state so cache/rate-limit don't leak between tests.
    try:
        import main
        main._brief_cache.update({"t": 0.0, "v": None})
        main._RL_HITS.clear()
    except Exception:
        pass
    return engine
