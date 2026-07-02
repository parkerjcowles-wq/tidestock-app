import time
import requests
import config

_HEADERS = {"User-Agent": "TideStock/1.0 (portfolio project; read-only public data)"}

# Subreddits where every post is relevant to inshore/surf fishing — no keyword gating
_HIGH_VALUE_SUBS = {"surf_fishing", "stripers"}

# Species-specific terms for NE inshore fishing (must match one of these to pass generic subs)
_SPECIES_TERMS = {
    "striper", "striped bass", "linesider",
    "flounder", "fluke",
    "bluefish", "blues",
    "bunker", "menhaden", "sandeel", "bloodworm", "sandworm",
}
# Explicit NE location terms
_REGION_TERMS = {
    "newburyport", "merrimack", "cape ann", "gloucester", "ipswich",
    "plum island", "north shore", "massachusetts", "new england",
    "essex county", "boston harbor",
}
_RELEVANCE_TERMS = _SPECIES_TERMS | _REGION_TERMS

_POSITIVE_WORDS = [
    "slammed", "crushing", "limits", "on fire", "hot bite", "getting them",
    "tearing up", "killed it", "stacked", "loaded", "ripping", "caught",
    "limit out", "non-stop", "lights out", "wide open", "great fishing",
    "hammered", "absolutely smashing", "best day", "on them",
]
_NEGATIVE_WORDS = [
    "slow", "dead", "nothing", "skunked", "tough bite", "no fish",
    "blanked", "quiet", "struggled", "couldn't get", "tough day",
]

# Bait keyword → SKU category mapping
_KW_TO_CATEGORY = {
    "paddle tail":   "soft_plastics",
    "ned rig":       "soft_plastics",
    "sandeel":       "soft_plastics",
    "soft plastic":  "soft_plastics",
    "z-man":         "soft_plastics",
    "berkley gulp":  "soft_plastics",
    "bucktail":      "bucktails_jigs",
    "jig":           "bucktails_jigs",
    "crankbait":     "hard_baits",
    "topwater":      "hard_baits",
    "x-rap":         "hard_baits",
    "popper":        "hard_baits",
    "bunker":        "bait",
    "bloodworm":     "bait",
    "sandworm":      "bait",
    "mummichog":     "bait",
    "clam":          "bait",
    "squid":         "bait",
    "fluke":         "bait",
    "circle hook":   "terminal_tackle",
    "hook":          "terminal_tackle",
    "fluorocarbon":  "line_leaders",
    "braid":         "line_leaders",
    "leader":        "line_leaders",
}

_AVATAR_COLORS = [
    "#1d4ed8", "#0f766e", "#7e22ce", "#b45309", "#be123c",
    "#0369a1", "#15803d", "#a16207", "#9333ea", "#c2410c",
]


def _avatar_color(username: str) -> str:
    return _AVATAR_COLORS[hash(username) % len(_AVATAR_COLORS)]


def _initials(username: str) -> str:
    clean = username.replace("_", " ").replace("-", " ")
    parts = clean.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return username[:2].upper()


def _time_ago(created_utc: float) -> str:
    diff = time.time() - created_utc
    if diff < 3600:
        return f"{int(diff / 60)}m ago"
    if diff < 86400:
        return f"{int(diff / 3600)}h ago"
    return f"{int(diff / 86400)}d ago"


def classify_sentiment(text: str) -> str:
    t = text.lower()
    pos = sum(1 for w in _POSITIVE_WORDS if w in t)
    neg = sum(1 for w in _NEGATIVE_WORDS if w in t)
    if pos > neg and pos > 0:
        return "catching"
    if neg > pos and neg > 0:
        return "slow"
    return "neutral"


def extract_bait_mentions(text: str, keywords: list) -> list:
    t = text.lower()
    return [kw for kw in keywords if kw.lower() in t]


def get_category_signals(bait_mentions: list) -> list:
    """Return list of affected category keys from bait mentions."""
    seen = set()
    cats = []
    for kw in bait_mentions:
        cat = _KW_TO_CATEGORY.get(kw.lower())
        if cat and cat not in seen:
            cats.append(cat)
            seen.add(cat)
    return cats


def fetch_location_reddit_posts(location_query: str, limit: int = 12) -> list:
    """Search Reddit for location-specific fishing posts using the public search API."""
    posts = []
    try:
        q = location_query.replace(" ", "+")
        url = f"https://www.reddit.com/search.json?q={q}&sort=new&t=month&limit={limit}&type=link"
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        children = resp.json()["data"]["children"]
        for child in children:
            d = child["data"]
            full_text = f"{d['title']} {d.get('selftext', '')}"
            mentions = extract_bait_mentions(full_text, list(_KW_TO_CATEGORY.keys()))
            sentiment = classify_sentiment(full_text)
            body = d.get("selftext", "").strip()
            posts.append({
                "title":            d["title"],
                "body":             body[:220] + ("…" if len(body) > 220 else ""),
                "subreddit":        d.get("subreddit", "fishing"),
                "author":           d.get("author", "angler"),
                "created_utc":      d.get("created_utc", 0),
                "time_ago":         _time_ago(d.get("created_utc", 0)),
                "upvotes":          d["score"],
                "comments":         d["num_comments"],
                "url":              f"https://reddit.com{d['permalink']}",
                "bait_mentions":    mentions,
                "category_signals": get_category_signals(mentions),
                "sentiment":        sentiment,
                "velocity":         classify_velocity(d["score"], d["num_comments"]),
                "avatar_color":     _avatar_color(d.get("author", "angler")),
                "initials":         _initials(d.get("author", "angler")),
                "is_local":         True,
            })
    except Exception:
        pass
    cutoff = time.time() - 30 * 86400
    posts = [p for p in posts if p["created_utc"] >= cutoff]
    posts.sort(key=lambda x: x["created_utc"], reverse=True)
    return posts


def fetch_reddit_signals(limit: int = 15) -> list:
    posts = []
    for sub_name in config.REDDIT_SUBREDDITS:
        try:
            url = f"https://www.reddit.com/r/{sub_name}/new.json?limit={limit}"
            resp = requests.get(url, headers=_HEADERS, timeout=10)
            resp.raise_for_status()
            children = resp.json()["data"]["children"]
            for child in children:
                d = child["data"]
                full_text = f"{d['title']} {d.get('selftext', '')}"
                # Filter out posts not relevant to NE inshore fishing
                if sub_name not in _HIGH_VALUE_SUBS:
                    t_lower = full_text.lower()
                    if not any(kw in t_lower for kw in _RELEVANCE_TERMS):
                        continue
                mentions = extract_bait_mentions(full_text, list(_KW_TO_CATEGORY.keys()))
                sentiment = classify_sentiment(full_text)
                body = d.get("selftext", "").strip()
                posts.append({
                    "title":         d["title"],
                    "body":          body[:220] + ("…" if len(body) > 220 else ""),
                    "subreddit":     sub_name,
                    "author":        d.get("author", "angler"),
                    "created_utc":   d.get("created_utc", 0),
                    "time_ago":      _time_ago(d.get("created_utc", 0)),
                    "upvotes":       d["score"],
                    "comments":      d["num_comments"],
                    "url":           f"https://reddit.com{d['permalink']}",
                    "bait_mentions": mentions,
                    "category_signals": get_category_signals(mentions),
                    "sentiment":     sentiment,
                    "velocity":      classify_velocity(d["score"], d["num_comments"]),
                    "avatar_color":  _avatar_color(d.get("author", "angler")),
                    "initials":      _initials(d.get("author", "angler")),
                })
        except Exception:
            continue
    cutoff = time.time() - 30 * 86400
    posts = [p for p in posts if p["created_utc"] >= cutoff]
    posts.sort(key=lambda x: x["created_utc"], reverse=True)
    return posts[:20]


def classify_velocity(upvotes: int, comments: int) -> str:
    if upvotes >= 300 or comments >= 50:
        return "trending"
    if upvotes >= 100 or comments >= 15:
        return "elevated"
    return "baseline"


def get_overall_social_velocity(posts: list) -> str:
    if not posts:
        return "baseline"
    trending = sum(1 for p in posts if p["velocity"] == "trending")
    elevated  = sum(1 for p in posts if p["velocity"] == "elevated")
    if trending >= 2:
        return "trending"
    if trending >= 1 or elevated >= 3:
        return "elevated"
    return "baseline"


def compute_social_fishing_boost(posts: list) -> int:
    """0–20 additive boost to fishing score based on positive catch reports."""
    boost = 0
    for p in posts:
        if p["sentiment"] == "catching":
            boost += 4
            if p["bait_mentions"]:
                boost += 2
    return min(boost, 20)


def get_sku_demand_signals(posts: list) -> dict:
    """Return {category_key: boost_score} from catching posts with bait mentions."""
    signals: dict = {}
    for p in posts:
        if p["sentiment"] == "catching":
            for cat in p["category_signals"]:
                signals[cat] = signals.get(cat, 0) + 6
    # Cap per-category boost at 20
    return {k: min(v, 20) for k, v in signals.items()}
