import pandas as pd
from pytrends.request import TrendReq


def classify_trend_spike(current: float, baseline: float) -> str:
    if baseline == 0:
        return "baseline"
    ratio = current / baseline
    if ratio >= 2.0:
        return "trending"
    if ratio >= 1.3:
        return "elevated"
    return "baseline"


def fetch_trends_data(keywords: list, timeframe: str = "today 3-m") -> pd.DataFrame:
    pt = TrendReq(hl="en-US", tz=300)
    pt.build_payload(keywords, timeframe=timeframe, geo="US-MA")
    df = pt.interest_over_time()
    if "isPartial" in df.columns:
        df = df.drop(columns=["isPartial"])
    return df


def get_trending_keywords_from_df(df: pd.DataFrame, keywords: list) -> list:
    results = []
    for kw in keywords:
        if df is None or kw not in df.columns or len(df) < 4:
            results.append({"keyword": kw, "velocity": "baseline", "pct_change": 0})
            continue
        recent = df[kw].iloc[-1]
        baseline = df[kw].iloc[:-4].mean()
        velocity = classify_trend_spike(recent, baseline)
        pct = ((recent - baseline) / baseline * 100) if baseline > 0 else 0
        results.append({"keyword": kw, "velocity": velocity, "pct_change": round(pct)})
    return results


def get_trending_keywords(keywords: list) -> list:
    try:
        df = fetch_trends_data(keywords)
    except Exception:
        return [{"keyword": kw, "velocity": "baseline", "pct_change": 0} for kw in keywords]
    return get_trending_keywords_from_df(df, keywords)
