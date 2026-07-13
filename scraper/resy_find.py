"""
resy_find.py — slot-level Resy availability via the /4/find endpoint.

The calendar endpoint (resy_verify.availability) is day-level: it tells you a
day has *something*. To catch a single cancellation you need the actual time
slots — "7:30 PM, Dining Room, party of 2" — and that's what /4/find returns.

Read-only, uses the same public web key as resy_verify, no booking. Pair it
with sniper.py, which diffs successive snapshots to spot brand-new openings.
"""
import re
import time
try:
    import requests
except ImportError:
    requests = None

from resy_verify import _H, venue_info, _SLUG_RE   # reuse shared auth + helpers

FIND_URL = "https://api.resy.com/4/find"
_START_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})")

# Set when Resy answers 429 twice in a row (sustained rate limit, cools off over
# hours). Callers should stop their Resy pass — more calls just extend the ban.
RATE_LIMITED = False


def slots(venue_id, day, party_size=2, lat=0.0, lng=0.0, session=None):
    """Open time slots for one venue on one day.
    Returns a list of {date, time, type, token}; empty on any miss."""
    global RATE_LIMITED
    if not requests or not venue_id:
        return []
    s = session or requests
    params = {"venue_id": venue_id, "day": day, "party_size": party_size,
              "lat": lat or 0, "long": lng or 0}
    try:
        r = s.get(FIND_URL, params=params, headers=_H, timeout=20)
        if r.status_code == 429:            # rate limited: one polite retry, then flag
            time.sleep(25)
            r = s.get(FIND_URL, params=params, headers=_H, timeout=20)
            if r.status_code == 429:
                RATE_LIMITED = True
                return []
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []
    out = []
    for v in (data.get("results") or {}).get("venues") or []:
        for sl in v.get("slots") or []:
            m = _START_RE.match(((sl.get("date") or {}).get("start")) or "")
            if not m:
                continue
            cfg = sl.get("config") or {}
            out.append({"date": m.group(1), "time": m.group(2),
                        "type": (cfg.get("type") or "").strip(),
                        "token": cfg.get("token") or ""})
    return out
