#!/usr/bin/env python3
"""enrich_windows.py — the deterministic pre-pass: keep Resy venues' booking
mechanics live-accurate, city by city, with NO hand research and NO LLM. Uses
resy_detect over each venue's real Resy calendar, and accumulates a per-venue
time series in .detect_state.json so the release TIME and SCHEDULE (which need
observation over time) converge run over run.

Per Resy spot in cities/<key>.json it maintains:
  * bookingWindowDays / bookingWindow  — AUTHORITATIVE live fact; overwritten.
    (Skipped when the detected horizon is at the scan ceiling => window unknown-large.)
  * releaseTime + releaseSchedule='daily' — filled once the time series brackets a
    daily horizon flip and snaps it to a common release clock. Never fabricated.
  * difficulty — nudged AT MOST ±1 toward repeated live scarcity (>=4 obs over
    >=2 days), never clobbered on one snapshot. Also records liveScarcity/liveCheckedAt.

  python enrich_windows.py richmond            # one city
  python enrich_windows.py --all               # every city (the cron does this)
  python enrich_windows.py --all --dry-run     # preview, write nothing
"""
import argparse, json, sys, time
from datetime import date
from pathlib import Path

import resy_detect

SCR = Path(__file__).resolve().parent
CITIES = SCR.parent / "cities"
STATE_PATH = SCR / ".detect_state.json"
SKIP = {"index", "just-opened", "demand", "restaurant-queue", "_template"}
MAX_OBS = 48          # rolling per-venue history (a few days at ~4-6/day)
SCAN_DAYS = 95        # matches resy_detect.detect default; horizon at this = "unknown-large"


def load_manifest():
    man = json.loads((CITIES / "index.json").read_text(encoding="utf-8"))
    tz = {c["key"]: c.get("timezone", "America/New_York") for c in man.get("cities", [])}
    # only json-sourced cities are ours to correct; NYC is live-API-sourced
    # (hardtobook already provides authoritative windows) so we leave it alone.
    json_keys = [c["key"] for c in man.get("cities", [])
                 if (c.get("source") or {}).get("type") == "json"]
    return tz, json_keys


def city_keys(json_keys, only=None):
    if only:
        return [only]
    return sorted(k for k in json_keys if k not in SKIP)


def enrich_city(key, tz, state, dry=False, session=None, sleep=1.1):
    path = CITIES / f"{key}.json"
    if not path.exists():
        print(f"  {key}: no file"); return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    spots = data.get("spots") if isinstance(data, dict) else data
    changed = timed = flagged = checked = 0
    for s in spots:
        if (s.get("platform") or "") != "Resy" or not s.get("platformUrl"):
            continue
        d = resy_detect.detect(s, scan_days=SCAN_DAYS, session=session)
        checked += 1
        time.sleep(sleep)
        if not d or not d.get("venueId"):
            continue

        # --- accumulate the time series (venueId-keyed) ---
        vid = str(d["venueId"])
        rec = state["venues"].setdefault(vid, {"slug": d.get("slug"), "loc": d.get("loc"),
                                               "city": key, "obs": []})
        rec["city"] = key
        rec["obs"].append({"observedAt": d["observedAt"], "horizonRaw": d.get("horizonRaw"),
                           "scarcity": d.get("scarcity")})
        rec["obs"] = rec["obs"][-MAX_OBS:]

        # --- bookingWindowDays: authoritative, unless the horizon hit the scan cap ---
        bw, hr = d.get("bookingWindowDays"), d.get("horizonRaw")
        capped = hr is not None and hr >= SCAN_DAYS - 2
        if bw and not capped and bw != s.get("bookingWindowDays"):
            print(f"    {s['name']:26} window {s.get('bookingWindowDays')} -> {bw}")
            if not dry:
                s["bookingWindowDays"] = bw
                s["bookingWindow"] = f"{bw} days"
            changed += 1

        # --- releaseTime + schedule from the accumulated series ---
        rt = resy_detect.infer_release_local(rec["obs"], tz)
        sched = resy_detect.infer_schedule(rec["obs"])
        if rt:
            label, tzl, conf = rt
            newrt = f"{label} {tzl}"
            if newrt != s.get("releaseTime"):
                print(f"    {s['name']:26} releaseTime -> {newrt}  (conf {conf})")
                if not dry:
                    s["releaseTime"] = newrt
                    if sched == "daily" or s.get("releaseSchedule") in (None, "", "none"):
                        s["releaseSchedule"] = sched or "daily"
                timed += 1

        # --- difficulty: bounded ±1 nudge from repeated scarcity, else just flag ---
        # (live scarcity lives in .detect_state.json obs, NOT the served JSON — so
        # the city file only changes on a real correction, not every fluctuation.)
        if d.get("difficulty") is not None:
            cur = s.get("difficulty")
            nudged = resy_detect.difficulty_from_history(rec["obs"], cur)
            if nudged != cur:
                print(f"    {s['name']:26} difficulty {cur} -> {nudged} (repeated live scarcity)")
                if not dry:
                    s["difficulty"] = max(1, min(5, nudged))
                flagged += 1

    if (changed or timed or flagged) and not dry:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  {key}: {checked} Resy checked | {changed} windows | {timed} release-times | "
          f"{flagged} difficulty nudges" + ("  [dry-run]" if dry else ""))
    return changed + timed + flagged


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("city", nargs="?", help="city key; omit with --all")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.city and not args.all:
        ap.error("give a city key or --all")

    try:
        import requests
        sess = requests.Session()
    except ImportError:
        print("requests not available"); return 1

    tzmap, json_keys = load_manifest()
    state = {"venues": {}}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            state.setdefault("venues", {})
        except Exception:
            pass

    total = 0
    for k in city_keys(json_keys, None if args.all else args.city):
        total += enrich_city(k, tzmap.get(k, "America/New_York"), state, dry=args.dry_run, session=sess)

    if not args.dry_run:
        state["updated"] = date.today().isoformat()
        STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(f"\n{'would change' if args.dry_run else 'changed'} {total} fields; "
          f"state tracks {len(state['venues'])} venues")
    return 0


if __name__ == "__main__":
    sys.exit(main())
