import os
import re
import time
import datetime
import requests
import config

_EXA_URL = "https://api.exa.ai/search"

# Page-chrome / boilerplate phrases that signal scraped navigation rather than
# real fishing content. Matched case-insensitively.
_CHROME_PHRASES = [
    "skip to main content", "skip to primary sidebar", "skip to footer",
    "skip to content", "subscribe", "newsletter", "log in", "login",
    "sign up", "sign in", "table of contents", "channel:", "length:",
    "views:", "keywords:", "language:", "please click here", "click here",
    "cookie policy", "privacy policy", "terms of service", "all rights reserved",
]

# Script/CSS fragments — if these survive cleaning, the text is markup, not prose.
_SCRIPT_FRAGMENTS = ["!function", "function(", "var ", "window.", "document.",
                     "{", "}", "</", "/>"]


def _clean_snippet(text: str) -> str:
    """Return a clean 1–2 line snippet, or '' if the text is mostly page chrome.

    Strips HTML/markdown/script artifacts and known site-chrome phrases. If too
    little real content survives (or script fragments remain), returns '' so the
    card hides the snippet rather than showing scraped boilerplate.
    """
    if not text:
        return ""
    snippet = text[:400]
    snippet = re.sub(r"<[^>]*>", " ", snippet)                 # strip HTML tags
    snippet = snippet.replace("#", "").replace("[![", "").replace("*", "")
    for phrase in _CHROME_PHRASES:                             # drop chrome phrases
        snippet = re.sub(re.escape(phrase), " ", snippet, flags=re.IGNORECASE)
    snippet = " ".join(snippet.split()).strip(" -–—|·:")
    low = snippet.lower()
    if any(frag in low for frag in _SCRIPT_FRAGMENTS):
        return ""
    if len(snippet) < 40:                                      # too little survived
        return ""
    if len(snippet) > 200:
        snippet = snippet[:200].rstrip() + "…"
    return snippet


def _title_is_useful(title: str) -> bool:
    """True if the title carries real content (not empty / chrome / too short)."""
    if not title or len(title.strip()) < 8:
        return False
    low = title.lower()
    return not any(p in low for p in _CHROME_PHRASES)

_DOMAIN_LABELS = {
    "onthewater.com":       "On The Water",
    "thefisherman.com":     "The Fisherman",
    "stripersonline.com":   "StripersOnline",
    "myfishingcapecod.com": "My Fishing Cape Cod",
    "ristripedbass.blogspot.com": "RI Striper Bass",
    "blogspot.com":         "Fishing Blog",
    "reddit.com":           "Reddit",
    "youtube.com":          "YouTube",
    "instagram.com":        "Instagram",
    "fishcrusade.com":      "Fish Crusade",
    "dsflyfishing.com":     "DS Fly Fishing",
}

_DOMAIN_COLORS = {
    "onthewater.com":       "#0ea5e9",
    "thefisherman.com":     "#f59e0b",
    "stripersonline.com":   "#22c55e",
    "myfishingcapecod.com": "#a78bfa",
    "reddit.com":           "#f97316",
    "default":              "#6b7280",
}

_QUERIES = [
    f"Plum Island Newburyport striper fishing report {datetime.date.today().strftime('%B %Y')}",
    f"Massachusetts New England fishing report striper {datetime.date.today().strftime('%B %Y')}",
    f"striper migration report Cape Ann North Shore {datetime.date.today().strftime('%B %Y')}",
]


def _domain_from_url(url: str) -> str:
    try:
        host = url.split("/")[2].lower()
        return host.removeprefix("www.")
    except Exception:
        return "web"


def _label_for_domain(domain: str) -> str:
    for key, label in _DOMAIN_LABELS.items():
        if key in domain:
            return label
    # Fall back to cleaned domain name
    parts = domain.split(".")
    return parts[-2].replace("-", " ").title() if len(parts) >= 2 else domain


def _color_for_domain(domain: str) -> str:
    for key, color in _DOMAIN_COLORS.items():
        if key in domain:
            return color
    return _DOMAIN_COLORS["default"]


def _format_date(iso_str: str) -> str:
    if not iso_str:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        diff = now - dt
        if diff.days == 0:
            return "Today"
        if diff.days == 1:
            return "Yesterday"
        if diff.days <= 14:
            return f"{diff.days}d ago"
        return dt.strftime("%b %d")
    except Exception:
        return ""


def _is_relevant(title: str, text: str) -> bool:
    """Filter out results that are clearly not fishing reports."""
    combined = (title + " " + (text or "")).lower()
    skip_terms = ["javascript", "cookie policy", "subscribe", "newsletter", "!function",
                   "skip to main content", "skip to primary sidebar", "skip to footer",
                   "table of contents", "log in", "day pass", "subscriber login",
                   "sign up for free", "please click here"]
    if any(t in combined[:200] for t in skip_terms):
        return False
    fish_terms = ["fish", "striper", "bass", "flounder", "bait", "catch", "rod", "reel",
                  "tide", "surf", "angler", "tackle", "hook", "lure"]
    return any(t in combined for t in fish_terms)


def fetch_web_fishing_reports(days: int = 14) -> list:
    """Pull fishing reports from across the web via Exa neural search."""
    api_key = os.environ.get("EXA_API_KEY", "")
    if not api_key:
        return []

    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    seen_urls: set = set()
    reports = []

    for query in _QUERIES:
        try:
            resp = requests.post(
                _EXA_URL,
                headers={"x-api-key": api_key, "Content-Type": "application/json"},
                json={
                    "query": query,
                    "numResults": 8,
                    "useAutoprompt": True,
                    "type": "neural",
                    "startPublishedDate": cutoff,
                    "contents": {"text": {"maxCharacters": 300}},
                },
                timeout=12,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            for res in results:
                url = res.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                title = (res.get("title") or "").strip()
                text  = (res.get("text") or "").strip()
                if not _is_relevant(title, text):
                    continue
                domain = _domain_from_url(url)
                snippet = _clean_snippet(text)
                # Video pages have no useful prose — their "text" is SEO/metadata
                # noise. Keep the card (title + source) but hide the snippet.
                if any(v in domain for v in ("youtube.com", "youtu.be", "vimeo.com")):
                    snippet = ""
                # Keep a useful title even if its snippet is chrome; drop only
                # when BOTH the title and snippet are low quality.
                if not snippet and not _title_is_useful(title):
                    continue
                reports.append({
                    "title":        title[:90] + ("…" if len(title) > 90 else ""),
                    "snippet":      snippet,
                    "url":          url,
                    "domain":       domain,
                    "source_label": _label_for_domain(domain),
                    "source_color": _color_for_domain(domain),
                    "published":    res.get("publishedDate", ""),
                    "time_ago":     _format_date(res.get("publishedDate", "")),
                })
        except Exception:
            continue

    # Sort by most recent, deduplicated
    def _pub_sort_key(r):
        try:
            return datetime.datetime.fromisoformat(r["published"].replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0

    reports.sort(key=_pub_sort_key, reverse=True)
    return reports[:18]
