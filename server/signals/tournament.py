import os
import re
import datetime

import requests

import clock
import config

_EXA_URL = "https://api.exa.ai/search"

# Neural search returns anything tournament-adjacent: entry forms, fishing
# articles, last year's freshwater bass listings. On 2026-09-16 every one of the
# four rows on the live calendar was one of those, all labeled "same week".
_EVENT_RE = re.compile(
    r"\b(tournament|derby|classic|shootout|challenge|fishing contest|open)\b", re.I)
_NOT_EVENT_RE = re.compile(
    r"\b(entry form|registration form|rules|results|report|recap|charter|guide|how to)\b",
    re.I)
_YEAR_RE = re.compile(r"\b(20\d\d)\b")
_PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")


def _clean_title(raw: str) -> str:
    text = _PHONE_RE.sub(" ", raw or "")
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)      # "WinnipesaukeeSeptember"
    text = re.sub(r"(\d{4})(?=[A-Za-z])", r"\1 ", text)    # "2025On-Site"
    text = re.sub(r"\s+", " ", text).strip(" -|·:")
    return text[:90]


def _is_event(title: str, today: datetime.date) -> bool:
    if not _EVENT_RE.search(title) or _NOT_EVENT_RE.search(title):
        return False
    years = [int(y) for y in _YEAR_RE.findall(title)]
    return not years or max(years) >= today.year


def fetch_tournaments(region: str = None, days_ahead: int = 30) -> list:
    region = region or config.SHOP_REGION
    today = clock.today_local()
    query = f"striped bass fishing tournament derby {region} {today.strftime('%B %Y')}"
    headers = {"x-api-key": os.environ.get("EXA_API_KEY", ""), "Content-Type": "application/json"}
    payload = {"query": query, "numResults": 10, "useAutoprompt": True, "type": "neural"}
    try:
        r = requests.post(_EXA_URL, json=payload, headers=headers, timeout=10)
        r.raise_for_status()
        results = r.json().get("results", [])
    except Exception:
        return _fallback_tournaments()
    rows = []
    for res in results:
        title = _clean_title(res.get("title", ""))
        if not title or not _is_event(title, today):
            continue
        rows.append({
            "title": title,
            "url": res.get("url", ""),
            "published": res.get("publishedDate", ""),
            "days_until": None,
            # Search results carry no event date, so proximity is unknown.
            # Claiming "same_week" was a measurement nobody took.
            "proximity": None,
        })
    return rows[:4]


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
