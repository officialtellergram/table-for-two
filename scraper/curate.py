#!/usr/bin/env python3
"""
curate.py — turn a simple seed file into a Drop Watch city dataset.

You supply the booking-policy facts that can't be scraped (release schedule /
time / window — the stuff hardtobook hand-verifies). This tool auto-enriches
the rest (coordinates, cuisine, price, phone, website) from each venue's
website JSON-LD, falling back to OpenStreetMap geocoding, and writes a
dashboard-ready cities/<key>.json (plus optionally updates cities/index.json).

Usage:
  python curate.py sources/la.csv --city la --label "Los Angeles" --region "Los Angeles, CA" --update-manifest
  python curate.py sources/la.csv --city la --no-fetch        # offline, schema only

Seed file: CSV (spreadsheet-friendly) or JSON (a bare list of objects).
Only `name` + `platform` + `releaseSchedule` + `releaseTime` are really needed;
everything else is optional and auto-filled when blank. See scraper/README.md.

No third-party API keys. Network use is best-effort and polite (cached,
rate-limited, identifiable User-Agent). Run with --no-fetch to stay offline.
"""
import argparse, csv, json, re, sys, time, html
from datetime import date
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

import resy_verify  # validate/repair Resy booking links (Resy SPA hides bad slugs)

ROOT = Path(__file__).resolve().parent.parent          # repo root (has cities/)
CITIES_DIR = ROOT / "cities"
UA = "DropWatchCurator/1.0 (personal restaurant dashboard; contact: local)"

# ---- the canonical spot schema the dashboard reads -------------------------
SPOT_FIELDS = [
    "id", "name", "neighborhood", "cuisine", "coordinates", "difficulty",
    "priceRange", "platform", "platformUrl", "website", "phoneNumber",
    "releaseSchedule", "releaseTime", "releaseDay", "bookingWindow",
    "bookingWindowDays", "walkIns", "walkIn", "tips", "signatureDish",
    "lastVerified", "availability",
]
TRUTHY = {"1", "true", "yes", "y", "t"}


def log(msg):
    print(msg, file=sys.stderr)


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def _tips(val):
    """Accept tips as a JSON list OR a pipe-separated string."""
    if isinstance(val, list):
        return [str(t).strip() for t in val if str(t).strip()]
    return [t.strip() for t in str(val or "").split("|") if t.strip()]


def hardness(spot):
    """Composite 'hard to book' score — see research_spec.md.
    Combines research difficulty with the live Resy scarcity signal."""
    diff = spot.get("difficulty") or 0
    av = spot.get("availability")
    if av is None:
        scar = 3                              # not auto-checkable (non-Resy) — neutral
    elif not av.get("open"):
        scar = 5                              # booked solid = hardest
    else:
        od = av.get("openDays", 14)
        scar = 4 if od <= 3 else 3 if od <= 7 else 2 if od <= 12 else 1
    return diff * 2 + scar * 1.5


# ---- seed loading ----------------------------------------------------------
def load_seed(path: Path):
    """Return a list of raw dict rows from a .csv or .json seed file."""
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        return data["spots"] if isinstance(data, dict) and "spots" in data else data
    rows = list(csv.DictReader(text.splitlines()))
    # drop fully-empty rows and comment rows (id/name starting with #)
    out = []
    for r in rows:
        if not any((v or "").strip() for v in r.values()):
            continue
        if (r.get("name") or r.get("id") or "").strip().startswith("#"):
            continue
        out.append(r)
    return out


def row_to_spot(r):
    """Normalize one raw seed row into the dashboard spot shape."""
    name = (r.get("name") or "").strip()
    spot = {
        "id": (r.get("id") or "").strip() or slugify(name),
        "name": name,
        "neighborhood": (r.get("neighborhood") or "").strip(),
        "cuisine": (r.get("cuisine") or "").strip(),
        "coordinates": None,
        "difficulty": int(r["difficulty"]) if str(r.get("difficulty") or "").strip().isdigit() else 0,
        "priceRange": (r.get("priceRange") or "").strip(),
        "platform": (r.get("platform") or "").strip(),
        "platformUrl": (r.get("platformUrl") or "").strip(),
        "website": (r.get("website") or "").strip(),
        "phoneNumber": (r.get("phoneNumber") or "").strip(),
        "releaseSchedule": (r.get("releaseSchedule") or "").strip().lower(),
        "releaseTime": (r.get("releaseTime") or "").strip(),
        "releaseDay": (r.get("releaseDay") or "").strip(),
        "bookingWindow": (r.get("bookingWindow") or "").strip(),
        "bookingWindowDays": None,
        "walkIns": (r.get("walkIns") is True) or str(r.get("walkIns") or "").strip().lower() in TRUTHY,
        "walkIn": None,
        "tips": _tips(r.get("tips")),
        "availability": r.get("availability"),  # filled by the Resy live check below
        "signatureDish": (r.get("signatureDish") or "").strip(),
        "lastVerified": (r.get("lastVerified") or "").strip(),
    }
    bwd = str(r.get("bookingWindowDays") or "").strip()
    if bwd.isdigit():
        spot["bookingWindowDays"] = int(bwd)
        if not spot["bookingWindow"]:
            spot["bookingWindow"] = f"{bwd} days"
    # walk-in detail (optional columns)
    doors = (r.get("walkInDoors") or "").strip()
    advice = (r.get("walkInAdvice") or "").strip()
    lineby = (r.get("walkInLineBy") or "").strip()
    if spot["walkIns"] and (doors or advice or lineby):
        spot["walkIn"] = {k: v for k, v in
                          (("doors", doors), ("lineBy", lineby), ("advice", advice)) if v}
    # explicit coordinates in the seed win over any fetch
    lat, lng = (r.get("lat") or "").strip(), (r.get("lng") or "").strip()
    if lat and lng:
        try:
            spot["coordinates"] = {"lat": float(lat), "lng": float(lng)}
        except ValueError:
            pass
    # allow a free-form address column purely to aid geocoding
    spot["_address"] = (r.get("address") or "").strip()
    return spot


# ---- enrichment ------------------------------------------------------------
def http_get(url, timeout=12):
    if not requests:
        raise RuntimeError("the 'requests' package is required for fetching; use --no-fetch")
    return requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en"}, timeout=timeout)


def iter_jsonld(htmltext):
    """Yield every JSON-LD object embedded in a page (flattening @graph)."""
    for block in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        htmltext, re.DOTALL | re.IGNORECASE):
        try:
            data = json.loads(html.unescape(block.strip()))
        except Exception:
            continue
        stack = [data]
        while stack:
            cur = stack.pop()
            if isinstance(cur, list):
                stack.extend(cur)
            elif isinstance(cur, dict):
                if "@graph" in cur and isinstance(cur["@graph"], list):
                    stack.extend(cur["@graph"])
                yield cur


def restaurant_ld(htmltext):
    """Pick the most restaurant-ish JSON-LD object from a page."""
    best = None
    for obj in iter_jsonld(htmltext):
        t = obj.get("@type", "")
        types = t if isinstance(t, list) else [t]
        is_food = any("Restaurant" in str(x) or "FoodEstablishment" in str(x) for x in types)
        if is_food and ("geo" in obj or "address" in obj):
            return obj
        if best is None and ("geo" in obj or "address" in obj):
            best = obj
    return best


def enrich_from_website(spot):
    """Fill blanks from the venue website's schema.org JSON-LD. Returns True if anything found."""
    url = spot.get("website") or spot.get("platformUrl")
    if not url:
        return False
    try:
        resp = http_get(url)
        if resp.status_code != 200:
            return False
        ld = restaurant_ld(resp.text)
    except Exception as e:
        log(f"    website fetch failed ({e})")
        return False
    if not ld:
        return False
    found = False
    geo = ld.get("geo") or {}
    if not spot["coordinates"] and geo.get("latitude") and geo.get("longitude"):
        try:
            spot["coordinates"] = {"lat": float(geo["latitude"]), "lng": float(geo["longitude"])}
            found = True
        except (TypeError, ValueError):
            pass
    if not spot["cuisine"] and ld.get("servesCuisine"):
        c = ld["servesCuisine"]
        spot["cuisine"] = ", ".join(c) if isinstance(c, list) else str(c); found = True
    if not spot["priceRange"] and ld.get("priceRange"):
        spot["priceRange"] = str(ld["priceRange"]); found = True
    if not spot["phoneNumber"] and ld.get("telephone"):
        spot["phoneNumber"] = str(ld["telephone"]); found = True
    addr = ld.get("address") or {}
    if not spot["neighborhood"] and isinstance(addr, dict):
        hood = addr.get("addressLocality") or addr.get("addressNeighborhood")
        if hood:
            spot["neighborhood"] = str(hood); found = True
    if not spot["website"] and ld.get("url"):
        spot["website"] = str(ld["url"])
    return found


def geocode(spot, region, cache):
    """Last-resort coordinates from OpenStreetMap Nominatim (free, rate-limited)."""
    if spot["coordinates"]:
        return
    query = spot["_address"] or f'{spot["name"]}, {region}'
    if not query.strip().strip(","):
        return
    if query in cache:
        spot["coordinates"] = cache[query]
        return
    try:
        resp = http_get("https://nominatim.openstreetmap.org/search?" +
                        requests.compat.urlencode({"q": query, "format": "json", "limit": 1}))
        time.sleep(1.1)  # Nominatim policy: <=1 req/sec
        hits = resp.json()
        if hits:
            coord = {"lat": float(hits[0]["lat"]), "lng": float(hits[0]["lon"])}
            spot["coordinates"] = coord
            cache[query] = coord
            log(f"    geocoded via OSM: {query}")
        else:
            log(f"    no geocode result: {query}")
    except Exception as e:
        log(f"    geocode failed ({e})")


# ---- manifest --------------------------------------------------------------
def update_manifest(city, label, short, center, zoom, tz, out_rel):
    path = CITIES_DIR / "index.json"
    man = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"cities": []}
    cities = man.setdefault("cities", [])
    entry = next((c for c in cities if c.get("key") == city), None)
    new = {
        "key": city,
        "label": label,
        "short": short,
        "center": center,
        "zoom": zoom,
        "timezone": tz,
        "source": {"type": "json", "url": out_rel},
    }
    if entry:
        entry.update({k: v for k, v in new.items() if k != "key" and (k != "center" or center)})
        entry["source"] = new["source"]
    else:
        cities.append(new)
    path.write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
    log(f"  manifest updated: {path}")


# ---- main ------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Generate a Drop Watch city dataset from a seed file.")
    ap.add_argument("seed", help="seed file (.csv or .json)")
    ap.add_argument("--city", required=True, help="city key, e.g. la")
    ap.add_argument("--label", help="display name, e.g. 'Los Angeles'")
    ap.add_argument("--short", help="short tag, e.g. LA")
    ap.add_argument("--region", default="", help="geocoding hint, e.g. 'Los Angeles, CA'")
    ap.add_argument("--center", help="map center 'lat,lng' (else averaged from spots)")
    ap.add_argument("--zoom", type=int, default=12)
    ap.add_argument("--timezone", default="America/New_York",
                    help="IANA tz release times are interpreted in (e.g. America/Chicago for Houston)")
    ap.add_argument("--party", type=int, default=2, help="party size for the Resy availability check (default 2)")
    ap.add_argument("--top", type=int, default=0, help="rank by hardness and keep only the top N (0 = keep all)")
    ap.add_argument("--out", help="output path (default cities/<city>.json)")
    ap.add_argument("--no-fetch", action="store_true", help="skip all network enrichment")
    ap.add_argument("--update-manifest", action="store_true", help="register the city in cities/index.json")
    args = ap.parse_args()

    label = args.label or args.city.upper()
    short = args.short or args.city.upper()
    out = Path(args.out) if args.out else CITIES_DIR / f"{args.city}.json"
    cache_path = Path(__file__).resolve().parent / ".geocache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    rows = load_seed(Path(args.seed))
    log(f"Loaded {len(rows)} seed rows from {args.seed}")
    today = date.today().isoformat()

    spots = []
    for i, r in enumerate(rows, 1):
        spot = row_to_spot(r)
        if not spot["name"]:
            log(f"  [{i}] skipped: no name"); continue
        log(f"  [{i}] {spot['name']}")
        if not args.no_fetch:
            complete = spot["coordinates"] and spot["cuisine"] and spot["priceRange"]
            if not complete and enrich_from_website(spot):    # skip web fetch when already filled
                log("    enriched from website JSON-LD")
            geocode(spot, args.region or label, cache)   # coords first (Resy search needs them); no-ops if set
            time.sleep(0.15)                             # be gentle on the Resy API
            resy_verify.repair_spot(spot, log)            # validate/fix the Resy booking link
            av = resy_verify.availability(spot, party_size=args.party, window_days=7, today=date.today())
            if av is not None:
                spot["availability"] = av
                log(f"    Resy availability: {av['openDays']}/{av['windowDays']} days open (party {args.party})")
        if not spot["coordinates"]:
            log("    ! no coordinates (won't show on map) — add lat,lng or address to the seed")
        if not spot["lastVerified"]:
            spot["lastVerified"] = today
        spots.append({k: spot[k] for k in SPOT_FIELDS})  # drop private _address/_*

    # rank by hardness (live scarcity + difficulty) and keep the top N
    if args.top and len(spots) > args.top:
        spots.sort(key=lambda s: (-hardness(s), -(s.get("difficulty") or 0), s.get("name", "")))
        log(f"  ranked {len(spots)} candidates, kept top {args.top} (dropped {len(spots) - args.top})")
        spots = spots[:args.top]

    # map center: explicit, else average of geocoded spots, else None
    if args.center:
        lat, lng = (float(x) for x in args.center.split(","))
        center = [lat, lng]
    else:
        pts = [s["coordinates"] for s in spots if s["coordinates"]]
        center = ([round(sum(p["lat"] for p in pts) / len(pts), 4),
                   round(sum(p["lng"] for p in pts) / len(pts), 4)] if pts else None)

    payload = {
        "meta": {"source": "curate.py", "city": label, "count": len(spots),
                 "generated": today, "disclaimer": "Always confirm release times with the restaurant."},
        "spots": spots,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    cache_path.write_text(json.dumps(cache, indent=2))

    n_geo = sum(1 for s in spots if s["coordinates"])
    n_drop = sum(1 for s in spots if s["releaseSchedule"] and s["releaseSchedule"] != "none" and s["releaseTime"])
    log(f"\nWrote {len(spots)} spots -> {out}")
    log(f"  {n_geo}/{len(spots)} have coordinates · {n_drop}/{len(spots)} have a working countdown")
    if n_drop < len(spots):
        log("  (spots without releaseSchedule+releaseTime show 'invite/varies' — fill those in to get a timer)")

    if args.update_manifest:
        rel = f"cities/{out.name}"
        update_manifest(args.city, label, short, center, args.zoom, args.timezone, rel)
    else:
        log("\nManifest snippet (paste into cities/index.json -> cities[]):")
        print(json.dumps({"key": args.city, "label": label, "short": short,
                          "center": center, "zoom": args.zoom, "timezone": args.timezone,
                          "source": {"type": "json", "url": f"cities/{out.name}"}}, indent=2))


if __name__ == "__main__":
    main()
