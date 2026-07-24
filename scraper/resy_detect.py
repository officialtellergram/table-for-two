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


# ---- time-series refinement (release schedule + release time) -------------------
# One fetch gives the window and difficulty. The release TIME and SCHEDULE need
# observation over time: the horizon (furthest bookable date) jumps forward by one
# day at exactly the daily release time. Accumulate detect() results in a small
# per-venue history and derive:
#   releaseSchedule: horizon advances ~1/day => 'daily'; jumps ~30 at a month
#     boundary and is otherwise static => 'calendar-month'/'monthly'; +7 on a
#     fixed weekday => 'weekly'.
#   releaseTime: the UTC (->local) timestamp at which horizonRaw increments.
# The radar already polls these venues; folding detect() into that sweep and
# appending {observedAt, horizonRaw} per venue is all the history this needs.

def infer_release_time(history):
    """Given [{observedAt, horizonRaw}, ...] for one venue (chronological), return
    the local release time if a daily horizon-advance boundary is visible, else None.
    history entries must be dicts with ISO 'observedAt' and int 'horizonRaw'."""
    prev = None
    flips = []
    for h in sorted(history, key=lambda x: x["observedAt"]):
        hr = h.get("horizonRaw")
        if hr is None:
            continue
        if prev is not None and hr > prev["hr"]:
            # horizon jumped between prev.observedAt and this.observedAt — release happened in that gap
            flips.append((prev["at"], h["observedAt"]))
        prev = {"hr": hr, "at": h["observedAt"]}
    if not flips:
        return None
    # tightest bracket around a flip = best release-time estimate (midpoint)
    a, b = min(flips, key=lambda f: (datetime.fromisoformat(f[1]) - datetime.fromisoformat(f[0])))
    mid = datetime.fromisoformat(a) + (datetime.fromisoformat(b) - datetime.fromisoformat(a)) / 2
    return mid.isoformat()


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser(description="Detect Resy booking mechanics for a venue URL.")
    ap.add_argument("url", help="Resy venue URL")
    ap.add_argument("--party", type=int, default=2)
    args = ap.parse_args()
    print(json.dumps(detect(args.url, party_size=args.party), indent=2))
