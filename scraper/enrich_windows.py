#!/usr/bin/env python3
"""enrich_windows.py — keep Resy venues' booking mechanics live-accurate, city by
city, with NO hand research and NO LLM. Uses resy_detect.detect() to read each
venue's real booking window straight off its Resy calendar.

What it writes back (per Resy spot in cities/<key>.json):
  * bookingWindowDays / bookingWindow  — AUTHORITATIVE. It's a live fact, so we
    overwrite whatever was hand-guessed.
  * releaseSchedule='daily' + a VERIFY-releaseTime tip — only when the schedule
    was 'none'/blank and we found a clean daily-style rolling window. We never
    fabricate a releaseTime (that needs the intraday time series; see resy_detect).
  * liveScarcity / liveCheckedAt  — observed sold-out fraction, as a SIGNAL. We
    deliberately do NOT overwrite the curated `difficulty` (that blends acclaim +
    demand holistically); we only FLAG a large divergence for a human/agent.

  python enrich_windows.py richmond            # one city
  python enrich_windows.py --all --dry-run     # preview every city
"""
import argparse, json, sys, time
from datetime import date
from pathlib import Path

import resy_detect

SCR = Path(__file__).resolve().parent
CITIES = SCR.parent / "cities"
SKIP = {"index", "just-opened", "demand", "restaurant-queue", "_template"}


def city_keys(only=None):
    if only:
        return [only]
    return sorted(p.stem for p in CITIES.glob("*.json") if p.stem not in SKIP)


def enrich_city(key, dry=False, session=None, sleep=1.1):
    path = CITIES / f"{key}.json"
    if not path.exists():
        print(f"  {key}: no file"); return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    spots = data.get("spots") if isinstance(data, dict) else data
    changed = flagged = checked = 0
    for s in spots:
        if (s.get("platform") or "") != "Resy" or not s.get("platformUrl"):
            continue
        d = resy_detect.detect(s, session=session)
        checked += 1
        time.sleep(sleep)
        if not d:
            continue
        bw = d.get("bookingWindowDays")
        if bw and bw != s.get("bookingWindowDays"):
            print(f"    {s['name']:26} window {s.get('bookingWindowDays')} -> {bw}")
            if not dry:
                s["bookingWindowDays"] = bw
                s["bookingWindow"] = f"{bw} days"
                if s.get("releaseSchedule") in (None, "", "none") and d.get("openDates") is not None:
                    s["releaseSchedule"] = "daily"
                    tip = "VERIFY exact daily release time (window detected live from Resy)"
                    if tip not in s.get("tips", []):
                        s.setdefault("tips", []).append(tip)
            changed += 1
        # scarcity as a signal only; flag a big gap from the curated difficulty
        ld = d.get("difficulty")
        if ld is not None:
            if not dry:
                s["liveScarcity"] = d.get("scarcity")
                s["liveCheckedAt"] = date.today().isoformat()
            cur = s.get("difficulty")
            if cur and abs(ld - cur) >= 2:
                print(f"    ~ {s['name']:24} curated diff {cur} vs live {ld} (scarcity {d.get('scarcity')}) — review")
                flagged += 1
    if changed and not dry:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  {key}: checked {checked} Resy venues, {changed} windows updated, {flagged} flagged"
          + ("  [dry-run]" if dry else ""))
    return changed


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

    total = 0
    for k in city_keys(None if args.all else args.city):
        total += enrich_city(k, dry=args.dry_run, session=sess)
    print(f"\n{'would update' if args.dry_run else 'updated'} {total} venue windows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
