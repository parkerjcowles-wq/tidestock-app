"""Catch Reports, once Reddit stopped answering at all.

Reddit now returns 403 to anonymous JSON requests — from Render AND from a
laptop, with a browser User-Agent — so `fetch_reddit_signals` and
`fetch_location_reddit_posts` return nothing on every load. That left the Catch
Reports panel permanently empty, and left `velocity` reporting the string
"baseline" for "no feed at all", which is the same defect the barometer had:
a fallback value captioned as a reading.
"""
import pytest

from signals import web_reports as WR


# --- relevance -------------------------------------------------------------
#
# Ground truth from a live run: 11 genuinely relevant reports, and one real
# false positive that shipped — a Nantucket nature column about kingfishers,
# which passed only because "kingfishers" contains the substring "fish".

_REAL_TITLES = [
    "Nantucket Current | Current Waters: Nantucket Fishing Report",
    "Massachusetts Fishing Report- September 3 , 2026 - On The Water",
    "Coastal New Hampshire and Maine Coast Fishing Report- September 3, 2026",
    "Labor Day Weekend Fishing on Cape Cod: The Summer Season Ends With a Bang",
    "Rhode Island Fishing Report- September 3, 2026 - On The Water",
    "Bass (Good) and a New Algae (Bad) Are Back in Cape Cod Bay",
    "The Best Fly Line for Fall Fishing on Cape Cod?",
    "Plum Island Fishing Report Today (August 2026) | Fishing Report Hub",
    "Massachusetts Fishing Report- August 27, 2026 - On The Water",
    "When the Water Cools, the Fishing Heats Up: Understanding Cape Cod's Season",
    "Cape Cod's September Fishing Explosion: What's About to Happen",
    "Striper Fishing with the Super Snax Soft Plastic Lure - My Fishing Cape Cod",
    "Six Stops: For September Tog - The Fisherman",
]


@pytest.mark.parametrize("title", _REAL_TITLES)
def test_real_fishing_reports_stay_relevant(title):
    assert WR._is_relevant(title, "")


def test_the_kingfisher_column_is_rejected():
    """It led the Web Reports panel on 2026-09-03 and Dave cited it as fishing
    intelligence. "Kingfishers" is not a fishing term; substring matching on
    "fish" is what let it through."""
    assert not WR._is_relevant(
        "Belted Kingfishers return to the island | Lifestyle | ack.net",
        "By Suzanne Keating. Belted Kingfishers return to the island each "
        "September, rattling along the shoreline and diving for small prey.")


def test_other_wildlife_columns_that_merely_contain_fish_are_rejected():
    assert not WR._is_relevant("Swordfish Beach house tour | Lifestyle", "")
    assert not WR._is_relevant("Selfishness and the modern town meeting", "")


def test_a_coastal_story_with_no_angling_term_at_all_is_rejected():
    """"tide" and "surf" alone are coastal vocabulary, not evidence of fishing."""
    assert not WR._is_relevant(
        "Island tide chart art show opens Friday",
        "A gallery of prints about the tide, the surf and the dunes.")


# --- catch signal derivation ----------------------------------------------

def test_derive_catch_reports_extracts_bait_and_sentiment():
    reports = [{
        "title": "Massachusetts Fishing Report - stripers crushing sandeels",
        "snippet": "Anglers absolutely smashing it on bucktail jigs and "
                   "bloodworms this week.",
        "url": "https://onthewater.com/x", "domain": "onthewater.com",
        "source_label": "On The Water", "source_color": "#123456",
        "published": "2026-09-03", "time_ago": "TODAY",
    }]
    out = WR.derive_catch_reports(reports)
    assert len(out) == 1
    r = out[0]
    assert r["sentiment"] == "catching"
    assert "bucktail" in r["bait_mentions"]
    assert "bloodworm" in r["bait_mentions"]
    assert "bucktails_jigs" in r["category_signals"]
    assert "bait" in r["category_signals"]
    # The card has to say where this came from - it is a published report, not
    # an angler, and must never be dressed as one.
    assert r["origin"] == "web"
    assert "upvotes" not in r and "author" not in r


def test_derive_catch_reports_drops_reports_with_no_bait_mention():
    reports = [{"title": "Fall fishing outlook for Cape Cod", "snippet": "The "
                "season turns over in September.", "url": "u", "domain": "d",
                "source_label": "L", "source_color": "#000",
                "published": "", "time_ago": ""}]
    assert WR.derive_catch_reports(reports) == []


def test_derive_catch_reports_drops_a_report_saying_the_bite_is_off():
    reports = [{"title": "Slow week on the flats", "snippet": "Skunked on "
                "bloodworms three days running, the bite is dead.",
                "url": "u", "domain": "d", "source_label": "L",
                "source_color": "#000", "published": "", "time_ago": ""}]
    assert WR.derive_catch_reports(reports) == []


def test_derive_catch_reports_keeps_a_neutral_report_that_names_baits():
    """A weekly published report is written flatter than an angler's post.
    Requiring "catching" emptied the panel against real data; only a report
    that actually says the bite is off is excluded."""
    reports = [{"title": "Massachusetts Fishing Report - September 3",
                "snippet": "Striped bass are moving into the shallows; bunker "
                           "and jigs are producing.",
                "url": "u", "domain": "d", "source_label": "On The Water",
                "source_color": "#000", "published": "", "time_ago": "TODAY"}]
    out = WR.derive_catch_reports(reports)
    assert len(out) == 1
    assert out[0]["sentiment"] == "neutral"
    assert "bunker" in out[0]["bait_mentions"]


def test_precomputed_signals_are_preferred_over_the_short_snippet():
    """fetch_web_fishing_reports mines the full 1,500 characters; the card
    snippet is only 200 and would find nothing."""
    reports = [{"title": "Fall outlook", "snippet": "Short.",
                "sentiment": "catching", "bait_mentions": ["bucktail"],
                "category_signals": ["bucktails_jigs"],
                "url": "u", "domain": "d", "source_label": "L",
                "source_color": "#000", "published": "", "time_ago": ""}]
    out = WR.derive_catch_reports(reports)
    assert len(out) == 1 and out[0]["category_signals"] == ["bucktails_jigs"]


def test_derive_catch_reports_is_safe_on_empty_input():
    assert WR.derive_catch_reports([]) == []
    assert WR.derive_catch_reports(None) == []


# --- the social layer's honesty -------------------------------------------

def test_velocity_is_none_when_no_social_feed_answered(monkeypatch):
    """"baseline" is a measured state - a quiet feed. No feed at all is not
    that, and the strip captioned it as if it were. Same defect as the
    barometer's "stable"."""
    import engine
    monkeypatch.setattr(engine, "fetch_reddit_signals", lambda *a, **k: [])
    monkeypatch.setattr(engine, "fetch_location_reddit_posts", lambda *a, **k: [])
    engine.clear_caches()
    s = engine.load_social_signals()
    assert s["velocity"] is None
    assert "social" in s["degraded"]
    engine.clear_caches()


def test_velocity_is_reported_when_the_feed_does_answer(monkeypatch):
    import config, engine
    monkeypatch.setattr(config, "REDDIT_ENABLED", True)
    post = {"velocity": "elevated", "sentiment": "catching",
            "bait_mentions": ["jig"], "category_signals": ["bucktails_jigs"]}
    monkeypatch.setattr(engine, "fetch_reddit_signals", lambda *a, **k: [post] * 3)
    monkeypatch.setattr(engine, "fetch_location_reddit_posts", lambda *a, **k: [])
    engine.clear_caches()
    s = engine.load_social_signals()
    assert s["velocity"] == "elevated"
    assert "social" not in s["degraded"]
    engine.clear_caches()


def test_feeds_serves_web_derived_catch_reports_when_reddit_is_dead(monkeypatch):
    """End to end: the panel that had been empty on every live load."""
    from fastapi.testclient import TestClient
    from conftest import offline_engine
    import engine

    offline_engine(monkeypatch)
    monkeypatch.setattr(engine, "fetch_web_fishing_reports", lambda *a, **k: [{
        "title": "Massachusetts Fishing Report - stripers crushing sandeels",
        "snippet": "Anglers absolutely smashing it on bucktail jigs this week.",
        "url": "https://onthewater.com/x", "domain": "onthewater.com",
        "source_label": "On The Water", "source_color": "#123456",
        "published": "2026-09-04", "time_ago": "TODAY",
    }])
    engine.clear_caches()

    from main import app
    body = TestClient(app).get("/api/feeds").json()
    assert body["reddit_local"] == [] and body["reddit_regional"] == []
    assert body["catch_reports"], "the Catch Reports panel would still be empty"
    r = body["catch_reports"][0]
    assert r["origin"] == "web"
    assert r["source_label"] == "On The Water"
    assert "bucktail" in r["bait_mentions"]
    assert body["velocity"] is None
    engine.clear_caches()


def test_known_publications_get_a_readable_label():
    """The fallback title-cases the bare domain, so a run-together name renders
    as "Themightyfish" on the card."""
    assert WR._label_for_domain("themightyfish.com") == "The Mighty Fish"
    assert WR._label_for_domain("www.nantucketcurrent.com") == "Nantucket Current"
    # An unknown domain still gets the old fallback rather than nothing.
    assert WR._label_for_domain("someblog.example.com") == "Example"


# --- snippet quality -------------------------------------------------------

def test_snippet_drops_a_leading_echo_of_the_title():
    """These pages open with their own headline, so the first 200 characters of
    body text were the title again - the card rendered the same sentence twice,
    once as the link and once as the summary."""
    title = "Massachusetts Fishing Report- September 3, 2026 - On The Water"
    text = (title + " " + title + " Striped bass are moving into the shallows "
            "this week and bunker schools are holding along the north shore, "
            "with jigs producing best on the outgoing tide.")
    out = WR._clean_snippet(text, title)
    assert not out.lower().startswith("massachusetts fishing report")
    assert "Striped bass are moving" in out


def test_snippet_is_unchanged_when_it_does_not_echo_the_title():
    title = "Fall outlook"
    text = ("Striped bass are moving into the shallows this week and bunker "
            "schools are holding along the north shore, with jigs producing.")
    assert WR._clean_snippet(text, title).startswith("Striped bass are moving")


def test_snippet_survives_a_title_that_is_the_entire_text():
    """If stripping the echo leaves nothing, the card hides the snippet rather
    than showing an empty line."""
    title = "Nantucket Current | Current Waters: Nantucket Fishing Report"
    assert WR._clean_snippet(title + " " + title, title) == ""


def test_snippet_drops_a_second_echo_that_omits_the_site_suffix():
    """The real shape: the page repeats its headline twice, and the second copy
    drops the " - On The Water" the <title> tag carries, so matching the full
    title only ever removed the first one."""
    title = "Massachusetts Fishing Report- September 3 , 2026 - On The Water"
    text = ("Massachusetts Fishing Report- September 3 , 2026 - On The Water "
            "Massachusetts Fishing Report- September 3 , 2026 "
            "Striped bass are moving into the shallows, cod are becoming more "
            "reliable and bunker schools are holding along the north shore.")
    out = WR._clean_snippet(text, title)
    assert out.startswith("Striped bass are moving")


def test_snippet_drops_an_echo_of_the_leading_pipe_segment():
    title = "Nantucket Current | Current Waters: Nantucket Fishing Report"
    text = (title + " Current Waters: Nantucket Fishing Report "
            "Ah, September. Certain dates mark the season for surfcasters "
            "chasing albies along the south shore beaches this month.")
    out = WR._clean_snippet(text, title)
    assert out.startswith("Ah, September")


def test_a_title_truncated_mid_word_does_not_behead_the_snippet():
    """The Mighty Fish publishes a <title> cut off mid-word ("Ends With a B"),
    while the article body spells it out ("Ends With a Bang"). Matching that
    prefix without checking for a word boundary left the snippet starting
    "ang sean Fields | ..."."""
    title = ("Labor Day Weekend Fishing on Cape Cod: The Summer Season Ends "
             "With a B – The Mighty Fish")
    text = ("Labor Day Weekend Fishing on Cape Cod: The Summer Season Ends "
            "With a Bang sean Fields | September 3, 2026 "
            "Labor Day weekend may mark the unofficial end of summer, but for "
            "Cape Cod anglers the bass and albie fishing is only getting going.")
    out = WR._clean_snippet(text, title)
    assert not out.startswith("ang")
    assert "Labor Day weekend may mark" in out


def test_more_page_chrome_seen_live_is_stripped():
    """Observed on live cards: a "Skip to secondary menu" nav (the phrase list
    only had "primary sidebar" / "main content" / "footer") and a forum
    byline's "6 min read" / "Expand image" furniture."""
    out = WR._clean_snippet(
        "Skip to secondary menu - - THE SCUTTLEBUTT In the on-again, off-again "
        "world of striped bass, the fish are back in Cape Cod Bay this week and "
        "anglers are finding them on the flats.", "")
    assert not out.lower().startswith("skip to")
    out2 = WR._clean_snippet(
        "6 min read Expand image When fall arrives on Cape Cod, fly fishing for "
        "false albacore becomes the main event for anglers chasing them.", "")
    assert "min read" not in out2.lower()
    assert "6" not in out2.split("When")[0]  # the count goes with the words
    assert "Expand image" not in out2


# --- the dead feed is not called at all ------------------------------------

def test_reddit_is_not_called_while_it_is_disabled(monkeypatch):
    """Reddit answers 403 to every anonymous request, so calling it just spends
    two HTTPS round trips and their timeouts on every cache refresh - on a free
    instance where a cold start already costs the visitor a minute."""
    import config, engine
    called = []
    monkeypatch.setattr(config, "REDDIT_ENABLED", False)
    monkeypatch.setattr(engine, "fetch_reddit_signals",
                        lambda *a, **k: called.append("signals") or [])
    monkeypatch.setattr(engine, "fetch_location_reddit_posts",
                        lambda *a, **k: called.append("location") or [])
    engine.clear_caches()
    s = engine.load_social_signals()
    assert called == []
    assert s["posts"] == [] and s["local_posts"] == []
    assert s["velocity"] is None
    assert "social" in s["degraded"]
    engine.clear_caches()


def test_flipping_the_flag_back_on_calls_reddit_again(monkeypatch):
    """The switch OAuth credentials would flip - the fetchers, the extractors
    and the card that renders an angler post are all still here."""
    import config, engine
    called = []
    monkeypatch.setattr(config, "REDDIT_ENABLED", True)
    monkeypatch.setattr(engine, "fetch_reddit_signals",
                        lambda *a, **k: called.append("signals") or [])
    monkeypatch.setattr(engine, "fetch_location_reddit_posts",
                        lambda *a, **k: called.append("location") or [])
    engine.clear_caches()
    engine.load_social_signals()
    assert called == ["signals", "location"]
    engine.clear_caches()
