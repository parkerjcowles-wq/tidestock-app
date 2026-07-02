import datetime
import ephem

_PEAK_PHASES = {"new", "full"}

# Falling pressure ahead of an approaching front triggers aggressive feeding —
# the strongest bite window. Rising/post-front conditions are comparatively slow.
_PRESSURE_BONUS = {"rising": 0, "stable": 0, "falling": 20}

def get_moon_phase(date: datetime.date) -> str:
    m = ephem.Moon(date.isoformat())
    ill = m.moon_phase  # 0.0–1.0 illumination

    if ill < 0.02:
        return "new"
    if ill > 0.98:
        return "full"

    # Determine waxing vs waning using next full vs next new moon
    next_full = ephem.next_full_moon(date.isoformat()).datetime().date()
    next_new = ephem.next_new_moon(date.isoformat()).datetime().date()
    waxing = next_full < next_new  # full moon comes before new moon = waxing

    # Quarter phases: illumination near 50% (±8% window)
    if 0.42 < ill < 0.58:
        return "first_quarter" if waxing else "last_quarter"

    if waxing:
        return "waxing_crescent" if ill < 0.5 else "waxing_gibbous"
    else:
        return "waning_gibbous" if ill > 0.5 else "waning_crescent"

def get_fishing_score(moon_phase: str, pressure_trend: str) -> int:
    base = 90 if moon_phase in _PEAK_PHASES else 70 if "gibbous" in moon_phase else 50
    bonus = _PRESSURE_BONUS.get(pressure_trend, 0)
    return max(0, min(100, base + bonus))

def get_week_moon_data(start: datetime.date = None) -> list:
    if start is None:
        start = datetime.date.today()
    result = []
    for i in range(7):
        d = start + datetime.timedelta(days=i)
        phase = get_moon_phase(d)
        result.append({
            "date": d,
            "phase": phase,
            "score": get_fishing_score(phase, "stable"),
        })
    return result
