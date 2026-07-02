import os
import requests
import datetime
import config

_EXA_URL = "https://api.exa.ai/search"


def fetch_tournaments(region: str = None, days_ahead: int = 30) -> list:
    region = region or config.SHOP_REGION
    today = datetime.date.today()
    query = f"bass fishing tournament {region} {today.strftime('%B %Y')}"
    headers = {"x-api-key": os.environ.get("EXA_API_KEY", ""), "Content-Type": "application/json"}
    payload = {"query": query, "numResults": 5, "useAutoprompt": True, "type": "neural"}
    try:
        r = requests.post(_EXA_URL, json=payload, headers=headers, timeout=10)
        r.raise_for_status()
        results = r.json().get("results", [])
    except Exception:
        return _fallback_tournaments()
    return [
        {
            "title": res.get("title", "Fishing Tournament"),
            "url": res.get("url", ""),
            "published": res.get("publishedDate", ""),
            "days_until": None,
            "proximity": "same_week",
        }
        for res in results[:4]
    ]


def get_tournament_proximity(tournaments: list) -> str:
    if not tournaments:
        return "none"
    if any(t["proximity"] == "within_3_days" for t in tournaments):
        return "within_3_days"
    if any(t["proximity"] == "same_week" for t in tournaments):
        return "same_week"
    return "none"


def _fallback_tournaments() -> list:
    return []
