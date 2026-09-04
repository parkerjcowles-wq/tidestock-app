import os
import re
import time
import datetime
import requests
import config
from signals.reddit_signals import (
    classify_sentiment, extract_bait_mentions, get_category_signals,
    _KW_TO_CATEGORY,
)

_EXA_URL = "https://api.exa.ai/search"

# Page-chrome / boilerplate phrases that signal scraped navigation rather than
# real fishing content. Matched case-insensitively.
_CHROME_PHRASES = [
    "skip to main content", "skip to primary sidebar", "skip to footer",
    "skip to content", "subscribe", "newsletter", "log in", "login",
    "sign up", "sign in", "table of contents", "channel:", "length:",
    "views:", "keywords:", "language:", "please click here", "click here",
    "cookie policy", "privacy policy", "terms of service", "all rights reserved",
    # Added 2026-09-04 from what was actually rendering on live cards.
    "skip to secondary menu", "skip to navigation", "expand image",
    "share this", "advertisement", "related posts",
]

# Script/CSS fragments — if these survive cleaning, the text is markup, not prose.
_SCRIPT_FRAGMENTS = ["!function", "function(", "var ", "window.", "document.",
                     "{", "}", "</", "/>"]


def _strip_title_echo(body: str, title: str) -> str:
    """Drop leading repeats of the page's own headline.

    These pages open by printing their headline, usually more than once, and
    the repeats are not identical: the <title> carries a " - On The Water"
    suffix or a "Nantucket Current |" masthead that the in-page copy drops. So
    the title's separator-delimited segments are candidates too, longest first.
    Without this the card renders the same sentence twice - once as the link,
    once as the summary.
    """
    clean_title = " ".join((title or "").split())
    if not clean_title:
        return body
    candidates = [clean_title] + re.split(r"\s*[|\u2013\u2014]\s*|\s+-\s+", clean_title)
    candidates = sorted({c.strip() for c in candidates if len(c.strip()) >= 12},
                        key=len, reverse=True)
    for _ in range(4):  # bounded: a page repeats its headline, not forever
        low = body.lower()
        # The match must END on a word boundary. The Mighty Fish publishes a
        # <title> truncated mid-word ("Ends With a B") while the body spells it
        # out ("Ends With a Bang"); without this check the strip beheaded the
        # word and the snippet opened with "ang sean Fields".
        hit = next((c for c in candidates
                    if low.startswith(c.lower())
                    and (len(body) == len(c) or not body[len(c)].isalnum())),
                   None)
        if not hit:
            break
        body = body[len(hit):].lstrip(" -\u2013\u2014|\u00b7:,")
    return body


def _clean_snippet(text: str, title: str = "") -> str:
    """Return a clean 1-2 line snippet, or '' if the text is mostly page chrome.

    Strips HTML/markdown/script artifacts and known site-chrome phrases, then
    the page's own headline. Order matters: Exa returns markdown-ish text that
    often opens with an image or a "#" heading marker, so a headline match has
    to run AFTER those artifacts are removed, not before - matching first
    silently failed on live data while passing on hand-written fixtures.

    If too little real content survives (or script fragments remain), returns ''
    so the card hides the snippet rather than showing scraped boilerplate.
    """
    if not text:
        return ""
    # Generous window: the headline repeats consume a few hundred characters
    # before the article starts, and they are about to be removed.
    snippet = text[:1200]
    snippet = re.sub(r"<[^>]*>", " ", snippet)                 # strip HTML tags
    snippet = re.sub(r"!?\[[^\]]*\]\([^)]*\)", " ", snippet)   # markdown links/images
    snippet = snippet.replace("#", "").replace("[![", "").replace("*", "")
    # Carries its own number, so it has to go as one unit - dropping the words
    # alone left a stranded "- 6 " in the middle of a forum byline.
    snippet = re.sub(r"\d+\s*min read", " ", snippet, flags=re.IGNORECASE)
    for phrase in _CHROME_PHRASES:                             # drop chrome phrases
        snippet = re.sub(re.escape(phrase), " ", snippet, flags=re.IGNORECASE)
    snippet = " ".join(snippet.split()).strip(" -\u2013\u2014|\u00b7:")
    snippet = _strip_title_echo(snippet, title)
    # A byline left stranded at the front once the headline goes.
    snippet = re.sub(r"^(?:by\s+)?[A-Z][\w.\u2019'-]*(?:\s+[A-Z][\w.\u2019'-]*){0,3}\s*[|\u2022\u00b7]\s*"
                     r"(?:\w+\s+\d{1,2},?\s*\d{4})?\s*",
                     "", snippet).lstrip(" -\u2013\u2014|\u00b7:,")
    low = snippet.lower()
    if any(frag in low for frag in _SCRIPT_FRAGMENTS):
        return ""
    if len(snippet) < 40:                                      # too little survived
        return ""
    if len(snippet) > 200:
        snippet = snippet[:200].rstrip() + "\u2026"
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
    # The fallback title-cases the bare domain, which turns a run-together name
    # into "Themightyfish". These are the publications the search actually
    # returns; add to this table rather than trying to split words.
    "themightyfish.com":    "The Mighty Fish",
    "nantucketcurrent.com": "Nantucket Current",
    "fishingreporthub.com": "Fishing Report Hub",
    "provincetownindependent.org": "Provincetown Independent",
    "nebass.com":           "NEBA",
    "sportfishingmag.com":  "Sport Fishing",
    "onthewater.press":     "On The Water",
    "goosehummockshops.com": "Goose Hummock",
    "goosehummock.com":      "Goose Hummock",
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


# Terms that only appear when someone is actually fishing. One of these is
# enough on its own.
#
# Matched on WORD BOUNDARIES, which is the whole point: the old filter accepted
# any result whose text contained the substring "fish", and on 2026-09-03 that
# put "Belted Kingfishers return to the island" — a Nantucket nature column —
# at the top of the Web Reports panel, where Dave then cited it as fishing
# intelligence. "Kingfishers" contains "fish"; kingfishers do not buy bait.
_ANGLING_TERMS = (
    "fish", "fishes", "fished", "fishing", "fisherman", "fishermen",
    "angler", "anglers", "angling", "tackle", "lure", "lures", "jig", "jigs",
    "bucktail", "bucktails", "plug", "plugs", "teaser", "surfcasting",
    "surfcaster", "charter", "chum", "striper", "stripers", "striped bass",
    "bluefish", "flounder", "fluke", "tautog", "tog", "albie", "albies",
    "bonito", "bait", "baitfish", "keeper", "hookup", "bite", "catch",
    # "bass" is included despite reading as a music term elsewhere: every
    # query in _QUERIES is already fishing-scoped, so a bass guitar result
    # is not a shape this search returns, while "Bass (Good) and a New
    # Algae (Bad) Are Back in Cape Cod Bay" is exactly what it is for.
    "bass", "sea bass", "largemouth",
    "catches", "caught", "reel", "rod", "casting", "trolling",
)

_ANGLING_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _ANGLING_TERMS) + r")\b", re.I)

_SKIP_TERMS = ["javascript", "cookie policy", "subscribe", "newsletter", "!function",
               "skip to main content", "skip to primary sidebar", "skip to footer",
               "table of contents", "log in", "day pass", "subscriber login",
               "sign up for free", "please click here"]


def _is_relevant(title: str, text: str) -> bool:
    """True if this really is a fishing report, not a story that says "fish".

    Requires an angling term on a word boundary. The previous version accepted
    any of 14 substrings anywhere in the text, so "bass" in a music review and
    "fish" inside "kingfishers" both passed.
    """
    combined = (title + " " + (text or "")).lower()
    if any(t in combined[:200] for t in _SKIP_TERMS):
        return False
    return bool(_ANGLING_RE.search(combined))


def derive_catch_reports(reports: list) -> list:
    """Web reports that read as a catch AND name a bait, for the Catch Reports
    panel and the per-SKU demand signal.

    Reddit answered 403 to anonymous JSON in September 2026 — from Render and
    from a laptop with a browser User-Agent — so the panel this feeds had been
    empty on every load. The bait/sentiment extraction was never Reddit-specific;
    it takes text. What is NOT carried over is anything engagement-shaped: a
    published report has no upvotes, no comment count and no author, and giving
    it invented ones would be exactly the "fallback dressed as a live reading"
    defect the barometer had. The card renders as a publication, and `origin`
    says so.

    Deliberately NOT wired into `compute_social_fishing_boost`: that function
    adds +4 per positive post, and a published fishing report is positive by
    editorial habit ("Bonito Blitz!", "Explosion"), so feeding it these would
    peg the fishing score at its cap on headline tone rather than on evidence.
    """
    out = []
    for r in reports or []:
        # Precomputed at fetch time, where the full 1,500 characters were in
        # hand; falls back to the card text so this stays testable on its own.
        mentions = r.get("bait_mentions")
        sentiment = r.get("sentiment")
        if mentions is None or sentiment is None:
            text = f"{r.get('title', '')} {r.get('snippet', '')}"
            mentions = extract_bait_mentions(text, list(_KW_TO_CATEGORY.keys()))
            sentiment = classify_sentiment(text)
        if not mentions:
            continue
        # "slow" is a report saying the bite is off - the opposite of what this
        # panel is for. "neutral" is kept: a weekly published report naming the
        # baits that are working is a catch report even when it is written
        # without the enthusiasm an angler posts with, and requiring "catching"
        # emptied the panel on real data.
        if sentiment == "slow":
            continue
        out.append({
            "title":        r.get("title", ""),
            "snippet":      r.get("snippet", ""),
            "url":          r.get("url", ""),
            "source_label": r.get("source_label", ""),
            "source_color": r.get("source_color", ""),
            "time_ago":     r.get("time_ago", ""),
            "bait_mentions":    mentions,
            "category_signals": r.get("category_signals") or get_category_signals(mentions),
            "sentiment":    sentiment,
            "origin":       "web",
        })
    return out


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
                    # 300 was enough for a display snippet but not to read a report:
                    # the first ~200 characters of these pages are the title
                    # repeated as chrome, so nothing was left to extract a bait
                    # mention or a sentiment from. The snippet shown on the card
                    # is still built from the first 400.
                    "contents": {"text": {"maxCharacters": 1500}},
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
                snippet = _clean_snippet(text, title)
                # Video pages have no useful prose — their "text" is SEO/metadata
                # noise. Keep the card (title + source) but hide the snippet.
                if any(v in domain for v in ("youtube.com", "youtu.be", "vimeo.com")):
                    snippet = ""
                # Keep a useful title even if its snippet is chrome; drop only
                # when BOTH the title and snippet are low quality.
                if not snippet and not _title_is_useful(title):
                    continue
                signal_text = f"{title} {text}"
                mentions = extract_bait_mentions(signal_text, list(_KW_TO_CATEGORY.keys()))
                reports.append({
                    "title":        title[:90] + ("…" if len(title) > 90 else ""),
                    "snippet":      snippet,
                    "sentiment":       classify_sentiment(signal_text),
                    "bait_mentions":   mentions,
                    "category_signals": get_category_signals(mentions),
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
