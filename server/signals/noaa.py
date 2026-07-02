import requests
import pandas as pd
import datetime

_BASE = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

def fetch_tide_predictions(station_id: str, days: int = 7) -> pd.DataFrame:
    today = datetime.date.today()
    end = today + datetime.timedelta(days=days)
    params = {
        "station": station_id,
        "product": "predictions",
        "datum": "MLLW",
        "time_zone": "lst_ldt",
        "interval": "h",
        "units": "english",
        "begin_date": today.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
        "application": "tidestock",
        "format": "json",
    }
    r = requests.get(_BASE, params=params, timeout=10)
    r.raise_for_status()
    payload = r.json()
    if "error" in payload:
        raise ValueError(payload["error"].get("message", "NOAA API error"))
    data = payload.get("predictions", [])
    if not data:
        return pd.DataFrame(columns=["time", "height"])
    df = pd.DataFrame(data)
    df["time"] = pd.to_datetime(df["t"])
    df["height"] = df["v"].astype(float)
    return df[["time", "height"]]

def fetch_water_temp(station_id: str) -> float:
    params = {
        "station": station_id,
        "product": "water_temperature",
        "datum": "MLLW",
        "time_zone": "lst_ldt",
        "units": "english",
        "range": "24",
        "application": "tidestock",
        "format": "json",
    }
    r = requests.get(_BASE, params=params, timeout=10)
    r.raise_for_status()
    payload = r.json()
    if "error" not in payload:
        data = payload.get("data", [])
        if data:
            return float(data[-1]["v"])
    # CO-OPS station has no water temp sensor — fall back to NDBC buoy 44013 (Boston offshore)
    try:
        resp = requests.get("https://www.ndbc.noaa.gov/data/realtime2/44013.txt", timeout=10)
        lines = [l for l in resp.text.splitlines() if not l.startswith("#")]
        if lines:
            wtmp_c = float(lines[0].split()[14])
            return round(wtmp_c * 9 / 5 + 32, 1)
    except Exception:
        pass
    return 55.0

def classify_tide_quality(max_range: float, num_peaks: int) -> str:
    if max_range >= 6.0 and num_peaks >= 2:
        return "prime"
    if max_range >= 3.0:
        return "moderate"  # range alone qualifies for moderate; peaks only matter for prime
    return "poor"

def get_tide_quality(df: pd.DataFrame) -> str:
    if df.empty:
        return "moderate"
    max_range = df["height"].max() - df["height"].min()
    heights = df["height"].values
    peaks = sum(
        1 for i in range(1, len(heights) - 1)
        if heights[i] > heights[i-1] and heights[i] > heights[i+1]
    )
    return classify_tide_quality(max_range, peaks)
