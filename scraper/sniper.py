#!/usr/bin/env python3
"""
sniper.py — the cancellation radar.

Polls slot-level Resy availability for the tracked venues over the next few
days, diffs each run against the last, and writes cities/just-opened.json: the
freshest openings with how-recently each slot first appeared. Run it on a short
interval from a scheduler; the longer it runs, the more it catches the moment a
table frees up (a cancellation) rather than just the standing availability.

State lives in .sniper_state.json so a run can tell a brand-new opening from one
it already knew about. Venue ids are cached there too (one extra lookup per new
venue, not per run).

Conservative by default — a small per-city venue cap, a short day window, and a
polite sleep between calls so the public Resy key isn't hammered. In production
you'd narrow this to a user's watchlist instead of every venue.

  python sniper.py                       # all manifest cities, next 4 days, top 8 venues each
  python sniper.py --cities nyc --limit 6 --days 3
  python sniper.py --party 2 --sleep 0.5
"""
import argparse, json, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import resy_verify
import resy_find

SCR = Path(__file__).resolve().parent
ROOT = SCR.parent
CITIES_DIR = ROOT / "cities"
DEPLOY_CITIES = ROOT / "deploy" / "cities"
STATE_PATH = SCR / ".sniper_state.json"
FEED_NAME = "just-opened.json"
MAX_ITEMS = 200   # roomier now that OpenTable venues feed in alongside Resy


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_manifest_keys(only=None):
    man = json.loads((CITIES_DIR / "index.json").read_text(encoding="utf-8"))
    keys = [c["key"] for c in man.get("cities", []) if (c.get("source") or {}).get("type") == "json"]
    if only:
        want = {k.strip() for k in only.split(",") if k.strip()}
        keys = [k for k in keys if k in want]
    return keys


def resy_ref(spot):
    """(loc, slug) from a spot's Resy platformUrl, or None."""
    m = resy_verify._SLUG_RE.search(spot.get("platformUrl") or "")
    return (m.group(1), m.group(2)) if m else None


def opentable_ref(spot):
    """The spot's OpenTable page URL, or None."""
    u = spot.get("platformUrl") or ""
    return u if "opentable.com" in u else None


def booking_url(spot, day, party):
    base = spot.get("platformUrl") or ""
    if not base:
        return ""
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}date={day}&seats={party}"


def main():
    ap = argparse.ArgumentParser(description="Poll Resy for slot-level openings and write the Just-Opened feed.")
    ap.add_argument("--cities", help="comma list of city keys (default: all json cities in the manifest)")
    ap.add_argument("--days", type=int, default=4, help="day window to scan, starting today (default 4)")
    ap.add_argument("--party", type=int, default=2, help="party size (default 2)")
    ap.add_argument("--limit", type=int, default=8, help="max venues to poll per city (default 8)")
    ap.add_argument("--sleep", type=float, default=0.4, help="seconds between API calls (default 0.4)")
    ap.add_argument("--no-deploy", action="store_true", help="don't also write the deploy/ mirror")
    ap.add_argument("--allow-empty", action="store_true",
                    help="write an empty feed even if the previous one had slots (default: keep last good)")
    ap.add_argument("--notify", action="store_true",
                    help="send Telegram alerts for newly-opened slots matching watchlist.json")
    ap.add_argument("--opentable", action="store_true",
                    help="also scan OpenTable venues (drives a real off-screen Edge window "
                         "via Playwright; ~16s per venue, one page load covers the whole window)")
    args = ap.parse_args()

    state = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
    seen = state.get("slots", {})          # slotKey -> firstSeen ISO
    venue_ids = state.get("venues", {})    # "loc/slug" -> resy venue id (cache)
    polled = set(state.get("polled", []))  # venue keys we've scanned at least once
    polled_now = set()

    # If the last sweep was hours ago (radar was off, PC asleep), the diff is
    # meaningless — everything looks "newly opened". Treat the run as a fresh
    # baseline instead of spamming false cancellations.
    stale = False
    try:
        prev = datetime.fromisoformat(state["updated"])
        stale = datetime.now(timezone.utc) - prev > timedelta(hours=3)
    except (KeyError, ValueError):
        pass

    today = date.today()
    days = [(today + timedelta(days=i)).isoformat() for i in range(max(1, args.days))]
    now = now_iso()

    try:
        import requests
        session = requests.Session()
    except ImportError:
        session = None

    current = {}     # slotKey -> item dict
    ot_queue = []    # (cityKey, spot) OpenTable venues, scanned after the Resy pass
    cities_polled = set(load_manifest_keys(args.cities))
    for key in load_manifest_keys(args.cities):
        path = CITIES_DIR / f"{key}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if args.opentable:
            ot_queue += [(key, s) for s in data.get("spots", [])
                         if opentable_ref(s)][: args.limit]
        spots = [s for s in data.get("spots", []) if resy_ref(s)][: args.limit]
        for spot in spots:
            loc, slug = resy_ref(spot)
            ck = f"{loc}/{slug}"
            vid = venue_ids.get(ck)
            if not vid:
                info = resy_verify.venue_info(slug, loc, session)
                vid = (info or {}).get("id")
                if vid:
                    venue_ids[ck] = vid
                time.sleep(args.sleep)
            if not vid:
                continue
            baseline = ck not in polled    # first time we've ever scanned this venue
            polled_now.add(ck)
            coord = spot.get("coordinates") or {}
            for day in days:
                for sl in resy_find.slots(vid, day, args.party,
                                          coord.get("lat"), coord.get("lng"), session):
                    slot_key = f"{vid}|{sl['date']}|{sl['time']}|{sl['type']}"
                    first_seen = seen.get(slot_key, now)
                    current[slot_key] = {
                        "city": key, "spotId": spot.get("id"), "name": spot.get("name"),
                        "neighborhood": spot.get("neighborhood"), "cuisine": spot.get("cuisine"),
                        "date": sl["date"], "time": sl["time"], "type": sl["type"],
                        "party": args.party, "url": booking_url(spot, sl["date"], args.party),
                        "firstSeen": first_seen,
                        # "new" = a slot that appeared since we last looked at THIS venue.
                        # A venue's first-ever scan is a baseline, not a cancellation, so
                        # nothing it shows that run is flagged new. Ditto a stale run.
                        "new": (slot_key not in seen) and not baseline and not stale,
                    }
                time.sleep(args.sleep)

    # OpenTable pass: one real (off-screen) browser reused across venues; a single
    # page load returns the venue's whole window, so no per-day loop here.
    if ot_queue:
        want_days = set(days)
        try:
            from opentable_find import OTBrowser
            with OTBrowser() as ot:
                for key, spot in ot_queue:
                    url = opentable_ref(spot)
                    slug = url.rstrip("/").split("/")[-1].split("?")[0]
                    ck = f"ot:{slug}"
                    baseline = ck not in polled
                    polled_now.add(ck)
                    sep = "&" if "?" in url else "?"
                    for sl in ot.slots(url, days[0], args.party):
                        if sl["date"] not in want_days:
                            continue
                        slot_key = f"ot:{slug}|{sl['date']}|{sl['time']}|{sl['type']}"
                        first_seen = seen.get(slot_key, now)
                        current[slot_key] = {
                            "city": key, "spotId": spot.get("id"), "name": spot.get("name"),
                            "neighborhood": spot.get("neighborhood"), "cuisine": spot.get("cuisine"),
                            "date": sl["date"], "time": sl["time"], "type": sl["type"],
                            "party": args.party,
                            "url": f"{url}{sep}covers={args.party}&dateTime={sl['date']}T{sl['time']}",
                            "firstSeen": first_seen,
                            "new": (slot_key not in seen) and not baseline and not stale,
                        }
        except Exception as e:
            print(f"opentable scan skipped: {e}")

    # A partial run (--cities) refreshes only its cities; carry the rest of the
    # previous feed forward (future dates only, badges cleared) instead of
    # silently dropping every other city from the site.
    carry = []
    feed_path = CITIES_DIR / FEED_NAME
    if feed_path.exists():
        try:
            prev_items = json.loads(feed_path.read_text(encoding="utf-8")).get("items", [])
            carry = [dict(it, new=False) for it in prev_items
                     if it.get("city") not in cities_polled
                     and (it.get("date") or "") >= today.isoformat()]
        except Exception:
            pass

    items = sorted(carry + list(current.values()),
                   key=lambda it: it["firstSeen"], reverse=True)[:MAX_ITEMS]
    new_count = sum(1 for it in items if it["new"])

    # Safety guard: if a sweep comes back empty but the last good feed had slots,
    # something is wrong (Resy blocking this IP, an outage, a network hiccup) — do
    # NOT overwrite the populated feed or the diff state with nothing. Bail clean.
    if not items:
        feed_path = CITIES_DIR / FEED_NAME
        prev_count = 0
        if feed_path.exists():
            try:
                prev_count = json.loads(feed_path.read_text(encoding="utf-8")).get("count", 0)
            except Exception:
                prev_count = 0
        if prev_count > 0 and not args.allow_empty:
            print(f"polled {len(polled_now)} venues -> 0 open slots, but the last feed had "
                  f"{prev_count}; keeping it (likely IP-blocked/outage). Use --allow-empty to override.")
            return

    feed = {"generated": now, "party": args.party, "windowDays": args.days,
            "count": len(items), "new": new_count, "items": items}

    (CITIES_DIR / FEED_NAME).write_text(json.dumps(feed, indent=2, ensure_ascii=False) + "\n",
                                        encoding="utf-8")
    if not args.no_deploy and DEPLOY_CITIES.exists():
        (DEPLOY_CITIES / FEED_NAME).write_text(json.dumps(feed, indent=2, ensure_ascii=False) + "\n",
                                               encoding="utf-8")

    # Merge, don't replace: a partial run (--cities, or Resy-only vs --opentable)
    # must not wipe the diff memory of venues it didn't poll, or the next full
    # sweep re-flags everything it forgot as "newly opened". Keep unpolled
    # venues' future-dated slots; drop everything else (booked or past).
    polled_ids = {ck if ck.startswith("ot:") else str(venue_ids.get(ck))
                  for ck in polled_now}
    today_iso = today.isoformat()
    kept = {k: v for k, v in seen.items()
            if k.split("|", 1)[0] not in polled_ids
            and (k.split("|") + ["", ""])[1] >= today_iso}
    state = {"updated": now,
             "slots": {**kept, **{k: v["firstSeen"] for k, v in current.items()}},
             "venues": venue_ids, "polled": sorted(polled | polled_now)}
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")

    n_baseline = len(polled_now - polled)
    tag = f" ({n_baseline} venues scanned for the first time — baselined, not flagged)" if n_baseline else ""
    if stale:
        tag += " [state was >3h old — re-baselined, nothing flagged new]"
    print(f"polled {len(polled_now)} venues across {len(days)} days -> "
          f"{len(items)} open slots, {new_count} newly opened{tag}")

    if args.notify:
        try:
            import notify
            sent = notify.notify_new(items)
            if sent:
                print(f"sent {sent} Telegram alert(s) for newly-opened tables")
        except Exception as e:
            print(f"notify skipped: {e}")


if __name__ == "__main__":
    main()
