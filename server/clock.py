"""The shop's wall clock.

Render runs in UTC, so bare datetime.now() stamped the dashboard "12:33 AM,
SEP 17" at 8:33 PM on Sept 16 in Newburyport. Every visitor-facing time and
date comes from here instead.
"""
import datetime
from zoneinfo import ZoneInfo

SHOP_TZ = ZoneInfo("America/New_York")


def now_local() -> datetime.datetime:
    return datetime.datetime.now(SHOP_TZ)


def today_local() -> datetime.date:
    return now_local().date()
