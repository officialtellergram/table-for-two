"""
resy_detect.py — derive a venue's booking mechanics from LIVE Resy data, instead
of hand-researching them. This is the "reverse-engineered hardtobook" engine:
hardtobook hand-verifies {bookingWindowDays, releaseTime, releaseSchedule, difficulty}
for NYC; we compute the observable ones ourselves, for any city, from the venue's
own reservation calendar.

The insight (validated 2026-07-24 against 5 NYC venues with known windows, all matched):
a venue's reservation calendar only lists dates INSIDE its booking window. The
furthest bookable date is therefore `today + bookingWindowDays`. And the fraction
of that window that is sold-out is the venue's live scarcity — i.e. its difficulty.
So ONE wide calendar fetch yields two of hardtobook's four hand-verified fields.

  bookingWindowDays  = (furthest bookable date) - today        [direct, ±1]
  difficulty (2-5)   = bucketed sold-out fraction of the window [direct]
  releaseSchedule    = 'daily' by default; 'monthly'/'weekly'   [needs 2+ obs — see detect_state]
  releaseTime        = the clock minute the horizon extends     [needs intraday obs — see detect_state]

Read-only, public web key, low volume — same access posture as resy_verify.
"""
import re
import time
from datetime import date, datetime, timezone, timedelta

try:
    import requests
except ImportError:
    requests = None

from resy_verify import _H, venue_info, _SLUG_RE

CAL_URL = "https://api.resy.com/4/venue/calendar"
# Round windows Resy venues actually use — snap a noisy ±1 observation to the real one.
COMMON_WINDOWS = [7, 14, 21, 28, 30, 45, 56, 60, 90]
# status values that mean "this date is within the released booking window"
IN_WINDOW = {"available", "sold-out"}


def _snap(days):
    """Snap an observed horizon to the nearest common window if within 1 day."""
    if days is None:
        return None
    for w in COMMON_WINDOWS:
        if abs(days - w) <= 1:
            return w
    return days


def _difficulty(sold, total):
    """Live scarcity -> 2..5, matching hardtobook's difficulty scale (it never
    lists 1s — everything tracked is at least 'in-demand')."""
    if not total:
        return None
    frac = sold / total
    if frac >= 0.90:
        return 5
    if frac >= 0.55:
        return 4
    if frac >= 0.15:
        return 3
    return 2


def detect(spot_or_url, party_size=2, scan_days=95, today=None, session=None):
    """Derive booking mechanics for one Resy venue from a single calendar fetch.

    Accepts a spot dict (uses its platformUrl) or a bare Resy URL string.
    Returns a dict, or None if it isn't a resolvable Resy venue. `observedAt` is
    stamped so a caller can build a time series (see detect_state)."""
    if not requests:
        return None
    url = spot_or_url.get("platformUrl") if isinstance(spot_or_url, dict) else spot_or_url
    m = _SLUG_RE.search(url or "")
    if not m:
        return None
    loc, slug = m.group(1), m.group(2)
    s = session or requests
    info = venue_info(slug, loc, s)
    if not info or not info.get("id"):
        return None

    today = today or date.today()
    end = today + timedelta(days=scan_days)
    try:
        r = s.get(CAL_URL, params={"venue_id": info["id"], "num_seats": party_size,
                                   "start_date": today.isoformat(), "end_date": end.isoformat()},
                  headers=_H, timeout=25)
        if r.status_code != 200:
            return None
        days = r.json().get("scheduled", [])
    except Exception:
        return None

    in_window = [d for d in days if (d.get("inventory") or {}).get("reservation") in IN_WINDOW]
    if not in_window:
        return {"venueId": info["id"], "slug": slug, "loc": loc,
                "observedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "bookingWindowDays": None, "difficulty": None, "scarcity": None,
                "openDates": [], "note": "no released window (closed, invite-only, or not bookable)"}

    dates = sorted(d["date"] for d in in_window)
    horizon_raw = (date.fromisoformat(dates[-1]) - today).days
    sold = sum(1 for d in in_window if (d.get("inventory") or {}).get("reservation") == "sold-out")
    total = len(in_window)
    open_dates = [d["date"] for d in in_window
                  if (d.get("inventory") or {}).get("reservation") == "available"]

    return {
        "venueId": info["id"], "slug": slug, "loc": loc,
        "observedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "bookingWindowDays": _snap(horizon_raw),   # snapped to the real window
        "horizonRaw": horizon_raw,                  # unsnapped, for the accumulator
        "difficulty": _difficulty(sold, total),
        "scarcity": round(sold / total, 3),
        "soldOut": sold, "windowDates": total,
        "openDates": open_dates,                    # the actual bookable dates right now
        "releaseScheduleHint": "daily",             # confirm/override via detect_state time series
        "note": "single-shot: bookingWindowDays+difficulty are live; releaseTime needs intraday obs",
    }


# ---- time-series refinement: release TIME + SCHEDULE -----------------------------
# One fetch gives window + scarcity. The release time/schedule need observation
# over time: the horizon (furthest bookable date) jumps forward by a day at the
# daily release time. Accumulate {observedAt, horizonRaw} per venue (see
# .detect_state.json in enrich_windows) and derive them here.
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

# Resy release times cluster hard at a few clock values (from hardtobook's NYC
# distribution). So we don't need minute-precise polling: bracket a horizon flip
# coarsely (~4h), then SNAP to the common release time inside that bracket. Same
# trick as _snap for windows. Minutes-of-day (local) -> label.
# minutes-of-day (local) -> (label, PRIOR). Priors are hardtobook's observed NYC
# release-time frequencies — a ~4h poll bracket usually spans several candidates,
# so we disambiguate by which release clock is a-priori most likely.
COMMON_RELEASE = {
    0:  ("12:00 AM (Midnight)", 27), 540: ("9:00 AM", 20), 600: ("10:00 AM", 28),
    630: ("10:30 AM", 2), 660: ("11:00 AM", 4), 720: ("12:00 PM (Noon)", 11),
    780: ("1:00 PM", 2), 840: ("2:00 PM", 2), 900: ("3:00 PM", 3),
    1020: ("5:00 PM", 2), 1080: ("6:00 PM", 2),
}
_TZ_LABEL = {"America/New_York": "ET", "America/Chicago": "CT", "America/Denver": "MT",
             "America/Los_Angeles": "PT", "Pacific/Honolulu": "HST", "America/Phoenix": "MST"}


def _local_minutes(iso_utc, tz):
    """Minutes-of-day (0-1439) of a UTC ISO timestamp in the given IANA tz."""
    dt = datetime.fromisoformat(iso_utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if ZoneInfo:
        dt = dt.astimezone(ZoneInfo(tz))
    return dt.hour * 60 + dt.minute, dt


def infer_release_local(history, tz):
    """From [{observedAt, horizonRaw}, ...] (one venue), return (label, tzlabel,
    confidence) for the daily release time, snapped to a common clock value — or
    None. `tz` is the venue city's IANA zone. Confidence = how many flips agreed."""
    if not ZoneInfo:
        return None
    hist = sorted((h for h in history if h.get("horizonRaw") is not None),
                  key=lambda x: x["observedAt"])
    weight = {}   # label -> prior-weighted vote total
    flips = {}    # label -> count of distinct flip brackets it fell in
    prev = None
    for h in hist:
        if prev is not None and h["horizonRaw"] > prev["horizonRaw"]:
            # release happened in the (prev, h) UTC bracket — every common time in it
            # is a candidate, weighted by its a-priori likelihood.
            m0, _ = _local_minutes(prev["observedAt"], tz)
            m1, _ = _local_minutes(h["observedAt"], tz)
            for mins, (label, prior) in COMMON_RELEASE.items():
                inside = (m0 <= mins <= m1) if m0 <= m1 else (mins >= m0 or mins <= m1)  # day wrap
                if inside:
                    weight[label] = weight.get(label, 0) + prior
                    flips[label] = flips.get(label, 0) + 1
        prev = h
    if not weight:
        return None
    label = max(weight, key=weight.get)
    conf = flips[label]                       # how many flips this clock was consistent with
    # need at least 2 corroborating flips before we commit a release time
    if conf < 2:
        return None
    return (label, _TZ_LABEL.get(tz, "local"), conf)


def infer_schedule(history):
    """'daily' if the horizon advances ~1/day across the series; 'irregular' if it
    sits static for long stretches then jumps (monthly/weekly — needs the LLM/site
    to name which). None if too little history."""
    hist = sorted((h for h in history if h.get("horizonRaw") is not None),
                  key=lambda x: x["observedAt"])
    if len(hist) < 4:
        return None
    diffs = [b["horizonRaw"] - a["horizonRaw"] for a, b in zip(hist, hist[1:])]
    advances = sum(1 for d in diffs if d > 0)
    jumps = sum(1 for d in diffs if d >= 7)
    if jumps and advances <= jumps + 1:
        return "irregular"          # big sporadic jumps => monthly/weekly-ish
    if advances >= max(1, len(diffs) // 3):
        return "daily"
    return None


def difficulty_from_history(obs, curated):
    """Nudge curated difficulty by AT MOST 1 step toward what repeated live scarcity
    implies — never clobber on a single snapshot. Needs >=4 obs across >=2 days that
    consistently disagree by >=2. Returns the (possibly unchanged) difficulty."""
    scars = [o["scarcity"] for o in obs if o.get("scarcity") is not None]
    days = {o["observedAt"][:10] for o in obs if o.get("scarcity") is not None}
    if len(scars) < 4 or len(days) < 2 or not curated:
        return curated
    scars_sorted = sorted(scars)
    med = scars_sorted[len(scars_sorted) // 2]
    implied = _difficulty(int(med * 100), 100)   # reuse the same bucketing
    if implied is None or abs(implied - curated) < 2:
        return curated
    return curated + (1 if implied > curated else -1)   # one step only, bounded by caller


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser(description="Detect Resy booking mechanics for a venue URL.")
    ap.add_argument("url", help="Resy venue URL")
    ap.add_argument("--party", type=int, default=2)
    args = ap.parse_args()
    print(json.dumps(detect(args.url, party_size=args.party), indent=2))
