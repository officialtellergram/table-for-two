#!/usr/bin/env python3
"""Harvest venue photos from sources we already integrate with — no Google, no key.

Two passes per spot, first hit wins:
  1. Resy venues — the /3/venue endpoint (same auth as the radar) returns the
     venue's own photo set on image.resy.com; we take the first.
  2. Everyone else (Tock, SevenRooms, OpenTable, own sites) — fetch the page the
     card already links to and read its og:image / twitter:image. That's the
     image each site explicitly publishes for third parties that link to it,
     which is exactly what a card is.

We hotlink (never copy) and the frontend falls back to the generated banner if
an image ever 404s or gets hotlink-blocked. photoAttr records the source
("Resy" or the site's domain) and renders as the card's credit chip.

Resy pacing matters: the local detect task shares this IP's rate budget, so we
sweep gently (0.9s) and abort the Resy pass on a 429 rather than digging in.

Usage:
  python harvest_photos.py --city nyc --dry-run    # review matches, write nothing
  python harvest_photos.py --city nyc              # write photo/photoAttr
  python harvest_photos.py --all
  python harvest_photos.py --all --refresh         # re-resolve existing photos
"""
import argparse, json, re, sys, time
from pathlib import Path
from urllib.parse import urlparse

import requests

from resy_verify import _H, _SLUG_RE

ROOT = Path(__file__).resolve().parent.parent
CITIES = ROOT / "cities"

PAGE_H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
OG_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image|og:image:secure_url|twitter:image)["\'][^>]+content=["\']([^"\']+)["\']'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|og:image:secure_url|twitter:image)["\']',
    re.I)
BAD_IMG = re.compile(r'logo|favicon|icon|placeholder|default|sprite|social-share|share-image|fb-share|og-share|error-page|/social/|[-_](?:facebook|twitter|og)?[-_]?preview\.|og-image-default', re.I)

resy_limited = False   # set on 429 — stop touching Resy for the rest of the run


def resy_photo(spot, session):
    """First venue photo from Resy's own API, or None."""
    global resy_limited
    if resy_limited or (spot.get("platform") or "") != "Resy":
        return None
    m = _SLUG_RE.search(spot.get("platformUrl") or "")
    if not m:
        return None
    loc, slug = m.group(1), m.group(2)
    try:
        r = session.get("https://api.resy.com/3/venue",
                        params={"url_slug": slug, "location": loc},
                        headers=_H, timeout=20)
        if r.status_code == 429:
            resy_limited = True
            print(">> Resy 429 — stopping Resy pass, og:image only from here")
            return None
        if r.status_code != 200:
            return None
        imgs = (r.json() or {}).get("images") or []
        return imgs[0] if imgs else None
    except Exception:
        return None


def og_photo(url, session):
    """og:image / twitter:image from a venue page, or None."""
    if not url or not url.startswith("http"):
        return None
    try:
        r = session.get(url, headers=PAGE_H, timeout=20, allow_redirects=True)
        if r.status_code != 200 or "text/html" not in (r.headers.get("Content-Type") or ""):
            return None
        for m in OG_RE.finditer(r.text[:200_000]):
            u = (m.group(1) or m.group(2) or "").strip()
            if u.startswith("//"):
                u = "https:" + u
            if u.startswith("http") and not BAD_IMG.search(u):
                u = re.sub(r"^http://", "https://", u)      # mixed-content safety
                host = (urlparse(u).hostname or "")
                if "squarespace" in host and "format=" not in u:
                    u += ("&" if "?" in u else "?") + "format=1000w"   # web-size, not the original
                return u
    except Exception:
        return None
    return None


def source_label(url):
    host = (urlparse(url).hostname or "").replace("www.", "")
    return host or "source"


def url_ok(url, session):
    """Confirm the URL really serves an image before we commit it to a card.

    Without this, a page that advertises an og:image which 404s gets harvested
    forever: we purge the dead link, the next sweep reads the same stale tag and
    puts it right back. Validating here breaks that loop at the source."""
    try:
        r = session.head(url, timeout=12, allow_redirects=True,
                         headers={"User-Agent": PAGE_H["User-Agent"]})
        if r.status_code >= 400 or "image" not in (r.headers.get("Content-Type") or ""):
            # some CDNs refuse HEAD; confirm with a ranged GET before believing it
            r = session.get(url, timeout=15, stream=True, allow_redirects=True,
                            headers={"User-Agent": PAGE_H["User-Agent"], "Range": "bytes=0-2047"})
            ok = r.status_code < 400 and "image" in (r.headers.get("Content-Type") or "")
            r.close()
            return ok
        return True
    except Exception:
        return False


def harvest_city(city, dry=False, refresh=False, limit=0, resy_sleep=0.9, og_sleep=0.4,
                 deadline=None):
    path = CITIES / f"{city}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    spots = data.get("spots", [])
    s_http = requests.Session()
    hit = miss = skip = 0
    out_of_time = False
    for s in spots:
        if limit and hit + miss >= limit:
            break
        # Bounded sweeps: the cloud cron shares a 25-minute job with the window
        # detector, so we stop cleanly on budget and keep whatever we resolved.
        # Coverage converges over runs instead of dying at the timeout.
        if deadline and time.monotonic() > deadline:
            out_of_time = True
            break
        if s.get("photo") and not refresh:
            skip += 1
            continue
        photo = attr = None
        u = resy_photo(s, s_http)
        if u:
            photo, attr = u, "Resy"
            time.sleep(resy_sleep)
        else:
            if (s.get("platform") or "") == "Resy" and not resy_limited:
                time.sleep(resy_sleep)          # the miss still spent a Resy call
            for page in (s.get("platformUrl"), s.get("website")):
                u = og_photo(page, s_http)
                if u:
                    photo, attr = u, source_label(page)
                    break
                if page:
                    time.sleep(og_sleep)
        if photo and not url_ok(photo, s_http):
            print(f"  DEAD  {s.get('name')}  advertises a broken image; leaving fallback")
            photo = attr = None
        if photo:
            hit += 1
            print(f"  OK    {s.get('name')}  [{attr}]  {photo[:96]}")
            if not dry:
                s["photo"] = photo
                s["photoAttr"] = attr
        else:
            miss += 1
            print(f"  MISS  {s.get('name')}  ({s.get('platform') or 'no platform'})")
    if not dry and hit:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f">> {city}: {hit} photos, {miss} misses, {skip} already had one"
          + ("  [dry run — nothing written]" if dry else "")
          + ("  [out of time budget]" if out_of_time else ""))
    return hit, miss, out_of_time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-seconds", type=int, default=0,
                    help="wall-clock budget for the whole sweep (0 = unbounded)")
    args = ap.parse_args()

    index = json.loads((CITIES / "index.json").read_text(encoding="utf-8"))
    cities = [c["key"] for c in index["cities"]
              if (c.get("source") or {}).get("type") == "json"]
    targets = [args.city] if args.city else (cities if args.all else None)
    if not targets:
        sys.exit("pass --city <key> or --all")

    deadline = time.monotonic() + args.max_seconds if args.max_seconds else None
    th = tm = 0
    for ckey in targets:
        if ckey not in cities:
            print(f">> unknown or non-json city: {ckey}"); continue
        if deadline and time.monotonic() > deadline:
            print(">> time budget spent; remaining cities resume next sweep"); break
        print(f">> {ckey}")
        h, m, _ = harvest_city(ckey, dry=args.dry_run, refresh=args.refresh,
                               limit=args.limit, deadline=deadline)
        th += h; tm += m
    print(f">> done — {th} photos, {tm} misses" + (" (dry run)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
