#!/usr/bin/env python3
"""
concierge.py — the date-night lens. Enriches each city dataset with the
soft, human signals a couple actually picks a table on: a `vibe` (romantic /
intimate / lively / special-occasion / cozy), the `occasion` it suits (first
date / anniversary / celebration / impress), and a one-line `dateNote` blurb.

These are derived deterministically from what we already know about each spot
(cuisine, price, difficulty, name, tips, signature dish) — no network, no keys.
It's a curation pass, so it runs AFTER curate.py and rewrites cities/<key>.json
(and the deploy/ mirror) in place. Re-running is safe and idempotent.

  python concierge.py                 # enrich every cities/*.json (+ deploy mirror)
  python concierge.py --city dc       # just one city
  python concierge.py --no-deploy     # skip the deploy/ mirror copy
"""
import argparse, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CITIES_DIR = ROOT / "cities"
DEPLOY_CITIES = ROOT / "deploy" / "cities"

# vibe -> keyword triggers (matched against the spot's combined text). Order here
# is also the tie-break priority when several vibes score equally.
VIBE_RULES = [
    ("special-occasion", ["tasting menu", "tasting", "prix fixe", "multi-course", "kaiseki",
                          "michelin", "james beard", "world's 50", "fine dining", "degustation",
                          "chef's table", "omakase"]),
    ("intimate",        ["omakase", "counter", "handroll", "hand roll", "sushi", "sashimi",
                          "nikkei", "seats", "10 seats", "12 seats", "chef's counter", "tiny",
                          "intimate", "small"]),
    ("romantic",        ["italian", "french", "trattoria", "osteria", "bistro", "wine bar",
                          "wine", "mediterranean", "candle", "date", "romantic", "trat"]),
    ("lively",          ["cocktail", "bar", "live-fire", "live fire", "bbq", "barbecue",
                          "taqueria", "izakaya", "natural wine", "buzzy", "scene", "loud",
                          "tavern", "raw bar", "oyster"]),
    ("cozy",            ["neighborhood", "cafe", "café", "warm", "cozy", "bakery", "deli",
                          "comfort", "homestyle", "family"]),
]

NOTE = {
    "romantic":         "Low-lit and date-perfect — made for a lingering two-top.",
    "intimate":         "An intimate counter — just you, them, and the chef.",
    "lively":           "Buzzy and fun — a lively night out for two.",
    "special-occasion": "A special-occasion table worth the wait.",
    "cozy":             "Warm neighborhood charm — easy and unhurried.",
}
DEFAULT_NOTE = "A memorable table for two."


def price_tier(spot):
    """Number of $ signs (0–4)."""
    return (spot.get("priceRange") or "").count("$")


def corpus(spot):
    parts = [spot.get("name"), spot.get("cuisine"), spot.get("neighborhood"),
             spot.get("signatureDish"), " ".join(spot.get("tips") or [])]
    return " ".join(p for p in parts if p).lower()


def classify_vibes(spot):
    text = corpus(spot)
    scored = []
    for vibe, kws in VIBE_RULES:
        hits = sum(1 for k in kws if k in text)
        if hits:
            scored.append((hits, vibe))
    # price/difficulty nudges
    tier = price_tier(spot)
    diff = spot.get("difficulty") or 0
    bump = {}
    if tier >= 4:
        bump["special-occasion"] = bump.get("special-occasion", 0) + 2
    if diff >= 5:
        bump["special-occasion"] = bump.get("special-occasion", 0) + 1
    if tier and tier <= 2:
        bump["cozy"] = bump.get("cozy", 0) + 1
    for vibe, b in bump.items():
        for i, (h, v) in enumerate(scored):
            if v == vibe:
                scored[i] = (h + b, v); break
        else:
            scored.append((b, vibe))
    if not scored:                                  # never leave a spot untagged
        scored = [(1, "special-occasion")] if tier >= 4 else [(1, "romantic")]
    prio = {v: i for i, (v, _) in enumerate(VIBE_RULES)}
    scored.sort(key=lambda x: (-x[0], prio.get(x[1], 99)))
    return [v for _, v in scored][:3]


def classify_occasions(spot, vibes):
    tier = price_tier(spot)
    diff = spot.get("difficulty") or 0
    text = corpus(spot)
    occ = []
    marquee = diff >= 5 or any(k in text for k in
                               ("michelin", "james beard", "world's 50", "tasting menu"))
    special = "special-occasion" in vibes or tier >= 4
    if marquee:
        occ.append("impress")
    if special or "romantic" in vibes:
        occ.append("anniversary")
    if special or diff >= 4:
        occ.append("celebration")
    # first-date: approachable, conversational — not a 3-hour $$$$ tasting
    if tier and tier <= 3 and "special-occasion" not in vibes:
        occ.append("first-date")
    if not occ:
        occ.append("celebration" if special else "first-date")
    # de-dup, keep order, cap at 3
    seen, out = set(), []
    for o in occ:
        if o not in seen:
            seen.add(o); out.append(o)
    return out[:3]


def enrich_spot(spot):
    vibes = classify_vibes(spot)
    spot["vibe"] = vibes
    spot["occasion"] = classify_occasions(spot, vibes)
    spot["dateNote"] = NOTE.get(vibes[0], DEFAULT_NOTE)
    return spot


def enrich_file(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    spots = data.get("spots") or []
    for s in spots:
        enrich_spot(s)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(spots)


def main():
    ap = argparse.ArgumentParser(description="Add date-night vibe/occasion tags to city datasets.")
    ap.add_argument("--city", help="only this city key (else all cities/*.json)")
    ap.add_argument("--no-deploy", action="store_true", help="don't also write the deploy/ mirror")
    args = ap.parse_args()

    files = ([CITIES_DIR / f"{args.city}.json"] if args.city
             else sorted(p for p in CITIES_DIR.glob("*.json") if p.name != "index.json"))
    for path in files:
        if not path.exists():
            print(f"-- skip {path.name}: not found"); continue
        n = enrich_file(path)
        print(f"enriched {n} spots in {path.name}")
        if not args.no_deploy and DEPLOY_CITIES.exists():
            dep = DEPLOY_CITIES / path.name
            dep.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    print("done.")


if __name__ == "__main__":
    main()
