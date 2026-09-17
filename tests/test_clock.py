import datetime
from zoneinfo import ZoneInfo


def test_now_local_is_eastern_and_aware():
    import clock
    now = clock.now_local()
    assert now.tzinfo is not None
    expected = datetime.datetime.now(ZoneInfo("America/New_York"))
    assert abs((now - expected).total_seconds()) < 5


def test_today_local_matches_eastern_date():
    import clock
    assert clock.today_local() == datetime.datetime.now(ZoneInfo("America/New_York")).date()
