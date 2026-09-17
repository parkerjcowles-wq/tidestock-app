import datetime

import signals.tournament as tournament


class _Resp:
    def __init__(self, results):
        self._results = results

    def raise_for_status(self):
        pass

    def json(self):
        return {"results": self._results}


LIVE_JUNK = [
    {"title": "2026 Tournament Trail Entry Form", "url": "https://a.com/1"},
    {"title": "NEBA of MASS", "url": "https://a.com/2"},
    {"title": "Striped Bass on the Edge: Fast-Action Fishing off Newburyport's Merrimack Mouth",
     "url": "https://a.com/3"},
    {"title": "Lake WinnipesaukeeSeptember 20-21, 2025On-Site Tournament Director Hotline: (603)234-6378TBF",
     "url": "https://a.com/4"},
    # No year in the title, so this fixture does not go stale next year.
    {"title": "Plum Island Striper Derby", "url": "https://a.com/5",
     "publishedDate": "2026-09-01T00:00:00.000Z"},
]


def _fetch(monkeypatch, results):
    monkeypatch.setattr(tournament.requests, "post", lambda *a, **k: _Resp(results))
    return tournament.fetch_tournaments(region="Newburyport MA")


def test_junk_rows_from_the_live_calendar_are_dropped(monkeypatch):
    rows = _fetch(monkeypatch, LIVE_JUNK)
    assert [r["title"] for r in rows] == ["Plum Island Striper Derby"]


def test_proximity_is_unknown_not_same_week(monkeypatch):
    rows = _fetch(monkeypatch, LIVE_JUNK)
    assert rows[0]["proximity"] is None
    assert tournament.get_tournament_proximity(rows) == "none"


def test_past_year_events_are_dropped():
    assert tournament._is_event("Cape Ann Striper Derby 2025", datetime.date(2026, 9, 16)) is False
    assert tournament._is_event("Cape Ann Striper Derby 2026", datetime.date(2026, 9, 16)) is True


def test_titles_are_cleaned_of_mashed_text_and_phone_numbers():
    assert tournament._clean_title("Big Fish Classic(603)234-6378") == "Big Fish Classic"
