import os
# config.py
SHOP_LAT = 42.8126
SHOP_LON = -70.8773
SHOP_REGION = "Newburyport, MA"
NOAA_STATION_ID = "8440466"  # Newburyport, Merrimack River MA
DEFAULT_LEAD_TIME_DAYS = 5
DEFAULT_SERVICE_LEVEL = 0.95

SKU_CATEGORIES = {
    "soft_plastics":  "Soft Plastics",
    "hard_baits":     "Hard Baits",
    "bait":           "Bait",
    "terminal_tackle": "Terminal Tackle",
    "bucktails_jigs": "Bucktails & Jigs",
    "line_leaders":   "Line & Leaders",
    "accessories":    "Accessories",
}

FISHING_KEYWORDS = [
    "paddle tail", "ned rig", "bucktail", "crankbait", "topwater",
    "striper", "sandeel", "bunker", "fluke", "porgy"
]
REDDIT_SUBREDDITS = ["surf_fishing", "SaltwaterFishing", "fishing"]

# Reddit closed its anonymous public JSON API. Verified 2026-09-04 from a
# laptop with a browser User-Agent, on www.reddit.com and old.reddit.com, on
# both the .json and .rss endpoints: 403 or 429 every time. This is NOT the
# Render egress IP - unlike the Open-Meteo block, no header or host change
# reaches it, and Exa has no Reddit index either (zero results with no date
# filter at all), so there is no way round it without credentials.
#
# Left OFF rather than deleted. Calling a feed that always 403s spends two
# HTTPS round trips and their timeouts on every cache refresh, on a free
# instance where the cold start already costs the visitor a minute. Everything
# behind this flag still works: the fetchers, the sentiment and bait
# extractors, and the angler-post card in the frontend.
#
# To turn it back on: register a Reddit app (reddit.com/prefs/apps), put the
# client id and secret in .env and in Render's environment, add the OAuth token
# call to signals/reddit_signals.py, and set this True.
REDDIT_ENABLED = False
REDDIT_LOCATION_QUERY = "Plum Island fishing OR Newburyport fishing OR Merrimack River striped bass"

SPECIES_CALENDAR = {
    1:  {"Striped Bass": "Inactive", "Largemouth Bass": "Low",  "Flounder": "Inactive"},
    2:  {"Striped Bass": "Inactive", "Largemouth Bass": "Low",  "Flounder": "Inactive"},
    3:  {"Striped Bass": "Low",      "Largemouth Bass": "Fair", "Flounder": "Low"},
    4:  {"Striped Bass": "Good",     "Largemouth Bass": "Peak", "Flounder": "Fair"},
    5:  {"Striped Bass": "Peak",     "Largemouth Bass": "Peak", "Flounder": "Good"},
    6:  {"Striped Bass": "Good",     "Largemouth Bass": "Good", "Flounder": "Peak"},
    7:  {"Striped Bass": "Fair",     "Largemouth Bass": "Good", "Flounder": "Peak"},
    8:  {"Striped Bass": "Fair",     "Largemouth Bass": "Good", "Flounder": "Good"},
    9:  {"Striped Bass": "Good",     "Largemouth Bass": "Fair", "Flounder": "Good"},
    10: {"Striped Bass": "Peak",     "Largemouth Bass": "Fair", "Flounder": "Fair"},
    11: {"Striped Bass": "Good",     "Largemouth Bass": "Low",  "Flounder": "Low"},
    12: {"Striped Bass": "Low",      "Largemouth Bass": "Inactive", "Flounder": "Inactive"},
}

ACTIVITY_COLORS = {"Peak": "#22c55e", "Good": "#86efac", "Fair": "#fbbf24", "Low": "#f97316", "Inactive": "#6b7280"}

# --- Groq synthesis (Dave's brief + Ask Dave) --------------------------------
# 2026-09-01: Groq RETIRED llama-3.3-70b-versatile. Both AI endpoints had been
# failing and silently serving the deterministic fallback: /api/brief reported
# source="fallback" and Ask Dave answered "Can't reach the AI engine right now"
# on the live site. Nothing alerted, because both routes catch bare Exception.
GROQ_MODEL = os.environ.get("TIDESTOCK_MODEL", "openai/gpt-oss-120b")
# gpt-oss bills hidden reasoning tokens against max_tokens before writing any
# answer. Left at default effort the brief comes back truncated or empty.
GROQ_REASONING_EFFORT = os.environ.get("TIDESTOCK_REASONING_EFFORT", "low")
GROQ_MAX_TOKENS = 1200
