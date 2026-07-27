#!/usr/bin/env python3
"""Enrich city spots with real venue photos via Google Places API (New).

Curation-time only — the browser never talks to Google. For each spot we
text-search "name, city" biased to the spot's coordinates, verify the match
(name similarity + distance guard), then resolve the first photo to its
direct googleusercontent CDN URL (skipHttpRedirect → photoUri, no API key
embedded). The frontend swaps a card's generated <canvas> for an <img>
whenever spot.photo exists; spot.photoAttr carries Google's required
photographer attribution.

Cost shape: 2 calls per spot (search + photo media), one-time + occasional
--refresh. ~800 spots across all cities sits inside the monthly free tier.

Usage:
  python enrich_photos.py --city nyc --dry-run     # review matches, write nothing
  python enrich_photos.py --city nyc               # write photo/photoAttr into nyc.json
  python enrich_photos.py --all                    # every json-sourced city
  python enrich_photos.py --all --refresh          # re-resolve even existing photos

Env: GOOGLE_PLACES_KEY (API-restricted to Places API (New); never committed).
"""
import argparse, difflib, json, math, os, re, sys, time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CITIES = ROOT / "cities"

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
MEDIA_URL = "https://places.googleapis.com/v1/{name}/media"
FIELD_MASK = "places.id,places.displayName,places.location,places.photos"

MAX_WIDTH = 960          # plenty for a 560px card banner on 2x displays
MATCH_RATIO = 0.55       # normalized-name similarity floor
MAX_KM = 2.0             # place must sit within 2 km of the curated coords


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"\b(the|restaurant|nyc|new york)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def km(lat1, lng1, lat2, lng2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def search_place(key, query, lat, lng):
    body = {"textQuery": query, "pageSize": 3}
    if lat is not None:
        body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lng},
                                           "radius": 3000.0}}
    r = requests.post(SEARCH_URL, json=body, timeout=30,
                      headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELD_MASK})
    r.raise_for_status()
    return (r.json() or {}).get("places", [])


def resolve_photo_uri(key, photo_name):
    r = requests.get(MEDIA_URL.format(name=photo_name), timeout=30,
                     params={"maxWidthPx": MAX_WIDTH, "skipHttpRedirect": "true", "key": key})
    r.raise_for_status()
    return (r.json() or {}).get("photoUri")


def best_match(spot, places):
    """Pick the first place that passes both guards; None if nothing does."""
    want = norm(spot.get("name"))
    lat = (spot.get("coordinates") or {}).get("lat")
    lng = (spot.get("coordinates") or {}).get("lng")
    for p in places:
        got = norm(((p.get("displayName") or {}).get("text")) or "")
        ratio = difflib.SequenceMatcher(None, want, got).ratio()
        if ratio < MATCH_RATIO:
            continue
        loc = p.get("location") or {}
        if lat is not None and loc.get("latitude") is not None:
            if km(lat, lng, loc["latitude"], loc["longitude"]) > MAX_KM:
                continue
        if not p.get("photos"):
            continue
        return p, ratio
    return None, 0.0


def enrich_city(key, city, label, center, dry=False, refresh=False, limit=0, sleep=0.15):
    path = CITIES / f"{city}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    spots = data.get("spots", [])
    hit = miss = skip = 0
    for s in spots:
        if limit and hit + miss >= limit:
            break
        if s.get("photo") and not refresh:
            skip += 1
            continue
        lat = (s.get("coordinates") or {}).get("lat") or (center or [None, None])[0]
        lng = (s.get("coordinates") or {}).get("lng") or (center or [None, None])[1]
        try:
            places = search_place(key, f"{s.get('name')}, {label}", lat, lng)
            place, ratio = best_match(s, places)
            if not place:
                miss += 1
                print(f"  MISS  {s.get('name')}  (no confident match with photos)")
                continue
            uri = resolve_photo_uri(key, place["photos"][0]["name"])
            if not uri:
                miss += 1
                print(f"  MISS  {s.get('name')}  (photo media gave no URI)")
                continue
            attrs = place["photos"][0].get("authorAttributions") or []
            hit += 1
            tag = "would set" if dry else "set"
            print(f"  OK    {s.get('name')}  ({ratio:.2f})  {tag} photo"
                  + (f" · credit {attrs[0].get('displayName')}" if attrs else ""))
            if not dry:
                s["photo"] = uri
                if attrs and attrs[0].get("displayName"):
                    s["photoAttr"] = attrs[0]["displayName"]
                else:
                    s.pop("photoAttr", None)
        except requests.HTTPError as e:
            miss += 1
            print(f"  ERR   {s.get('name')}  HTTP {e.response.status_code}: {e.response.text[:120]}")
            if e.response.status_code in (401, 403):
                print(">> key rejected — aborting city"); break
        except Exception as e:                                    # noqa: BLE001
            miss += 1
            print(f"  ERR   {s.get('name')}  {e}")
        time.sleep(sleep)
    if not dry and hit:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f">> {city}: {hit} photos, {miss} misses, {skip} already had one"
          + ("  [dry run — nothing written]" if dry else ""))
    return hit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="re-resolve spots that already have a photo")
    ap.add_argument("--limit", type=int, default=0, help="max lookups per city (0 = no cap)")
    ap.add_argument("--sleep", type=float, default=0.15)
    args = ap.parse_args()

    key = os.environ.get("GOOGLE_PLACES_KEY")
    if not key:
        sys.exit("GOOGLE_PLACES_KEY is not set (setx GOOGLE_PLACES_KEY \"AIza...\" then reopen the shell)")

    index = json.loads((CITIES / "index.json").read_text(encoding="utf-8"))
    cities = {c["key"]: c for c in index["cities"]
              if (c.get("source") or {}).get("type") == "json"}

    if args.city:
        targets = [args.city]
    elif args.all:
        targets = list(cities)
    else:
        sys.exit("pass --city <key> or --all")

    total = 0
    for ckey in targets:
        c = cities.get(ckey)
        if not c:
            print(f">> unknown or non-json city: {ckey}"); continue
        print(f">> {c['label']} ({ckey})")
        total += enrich_city(key, ckey, c["label"], c.get("center"),
                             dry=args.dry_run, refresh=args.refresh,
                             limit=args.limit, sleep=args.sleep)
    print(f">> done — {total} photos" + (" (dry run)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
