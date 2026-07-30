#!/usr/bin/env python3
"""Browser pass for venue photos the plain harvester can't reach.

harvest_photos.py covers Resy (API) and any site that publishes a real
og:image to plain HTTP. The remainder — Tock (Cloudflare 403), OpenTable
(Akamai), SevenRooms (JS shell) — serve their pages, with og:image and hero
imagery intact, only to a real browser. This is that browser: the same
headful-Edge + persistent-profile + human-pacing recipe opentable_find.py
proved out (see its docstring for the lessons), reused for a one-time sweep
of the photo misses.

Per spot (no photo yet): load the page the card links to, then take the first
of og:image / twitter:image / JSON-LD image / biggest rendered hero <img>
that isn't a logo. Hotlinked like everything else; t42PhotoFail covers rot.

Run while the OT radar task is paused — they share the .ot_profile browser
profile and must not run concurrently.

  python harvest_photos_browser.py --city nyc --dry-run
  python harvest_photos_browser.py --all
"""
import argparse, json, random, sys, time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

import requests

from harvest_photos import BAD_IMG, url_ok  # same filter + link validation
from opentable_find import PROFILE_DIR, _ARGS

ROOT = Path(__file__).resolve().parent.parent
CITIES = ROOT / "cities"

PLATFORM_LABEL = {"exploretock.com": "Tock", "opentable.com": "OpenTable",
                  "sevenrooms.com": "SevenRooms", "resy.com": "Resy"}

# In-page extractor: runs in the rendered DOM, returns the best candidate URL.
# Raw string: the JS regexes below own their backslashes (\/ \. \( \)) and Python
# must not reinterpret them — an unraw string makes these invalid escapes.
EXTRACT_JS = r"""
() => {
  const bad = /logo|favicon|icon|placeholder|default|sprite|social-share|share-image|fb-share|og-share|error-page|\/social\/|[-_](?:facebook|twitter|og)?[-_]?preview\.|og-image-default/i;
  const ok = u => u && /^https?:/.test(u) && !bad.test(u);
  const meta = sel => { const el = document.querySelector(sel); return el && el.content; };
  for (const sel of ['meta[property="og:image"]','meta[property="og:image:secure_url"]',
                     'meta[name="twitter:image"]','meta[itemprop="image"]']) {
    const u = meta(sel); if (ok(u)) return {url:u, how:'meta'};
  }
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const walk = x => {
        if (!x) return null;
        if (typeof x === 'string') return ok(x) && /\.(jpe?g|png|webp)|image/i.test(x) ? x : null;
        if (Array.isArray(x)) { for (const y of x) { const r = walk(y); if (r) return r; } return null; }
        if (typeof x === 'object') {
          if (x.image) { const r = walk(x.image); if (r) return r; }
          if (x['@type'] === 'ImageObject' && ok(x.url)) return x.url;
        }
        return null;
      };
      const r = walk(JSON.parse(s.textContent)); if (r) return {url:r, how:'ld+json'};
    } catch (e) {}
  }
  // Rendered hero: biggest real <img> that's plausibly a venue photo.
  let best = null, bestA = 0;
  for (const im of document.querySelectorAll('img')) {
    const u = im.currentSrc || im.src;
    const a = (im.naturalWidth||0) * (im.naturalHeight||0);
    if (!ok(u) || im.naturalWidth < 500 || a <= bestA) continue;
    best = u; bestA = a;
  }
  if (best) return {url:best, how:'hero-img'};
  // CSS background-image heroes (BentoBox et al): biggest painted block wins.
  let bg = null, bgA = 0;
  for (const el of document.querySelectorAll('div,section,header,figure,a')) {
    const r = el.getBoundingClientRect();
    if (r.width < 500 || r.height < 260 || r.width * r.height <= bgA) continue;
    const m = /url\(["']?(https?:[^"')]+)["']?\)/.exec(getComputedStyle(el).backgroundImage || '');
    if (m && ok(m[1])) { bg = m[1]; bgA = r.width * r.height; }
  }
  return bg ? {url:bg, how:'bg-img'} : null;
}
"""


def source_for(page_url):
    host = (urlparse(page_url).hostname or "").replace("www.", "")
    return PLATFORM_LABEL.get(host, host or "source")


def harvest_city(page, city, dry=False, limit=0):
    path = CITIES / f"{city}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    stale = (date.today() - timedelta(days=14)).isoformat()
    todo = [s for s in data.get("spots", []) if not s.get("photo")
            and (s.get("photoChecked") or "") < stale]
    if limit:
        todo = todo[:limit]
    hit = miss = 0
    for s in todo:
        target = s.get("platformUrl") or s.get("website")
        if not target or not target.startswith("http"):
            miss += 1
            print(f"  MISS  {s.get('name')}  (no page to visit)")
            continue
        got = None
        try:
            time.sleep(random.uniform(1.5, 3.5))          # human-ish gap
            page.goto(target, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(random.uniform(2500, 4500))
            got = page.evaluate(EXTRACT_JS)
            if not got:                                   # nudge lazy-loaded heroes
                page.evaluate("window.scrollBy(0,700)")
                page.wait_for_timeout(1400)
                got = page.evaluate(EXTRACT_JS)
            if not got and s.get("website") and target != s.get("website"):
                page.goto(s["website"], wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(random.uniform(2000, 3500))
                got = page.evaluate(EXTRACT_JS)
                if not got:
                    page.evaluate("window.scrollBy(0,700)")
                    page.wait_for_timeout(1400)
                    got = page.evaluate(EXTRACT_JS)
                if got:
                    target = s["website"]
        except Exception as e:
            print(f"  ERR   {s.get('name')}  {str(e)[:80]}")
        s["photoChecked"] = date.today().isoformat()
        if got and got.get("url"):
            u = got["url"].replace("http://", "https://", 1)
            if not url_ok(u, requests):          # never store a link that 404s
                print(f"  DEAD  {s.get('name')}  page advertises a broken image")
                got = None
        if got and got.get("url"):
            hit += 1
            s["photo"], s["photoAttr"] = u, source_for(target)
            print(f"  OK    {s.get('name')}  [{s['photoAttr']} · {got['how']}]  {u[:90]}")
        else:
            miss += 1
            print(f"  MISS  {s.get('name')}  ({s.get('platform')})")
    if not dry and todo:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f">> {city}: {hit} photos, {miss} still missing"
          + ("  [dry run — nothing written]" if dry else ""))
    return hit, miss


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    index = json.loads((CITIES / "index.json").read_text(encoding="utf-8"))
    cities = [c["key"] for c in index["cities"]
              if (c.get("source") or {}).get("type") == "json"]
    targets = [args.city] if args.city else (cities if args.all else None)
    if not targets:
        sys.exit("pass --city <key> or --all")

    from playwright.sync_api import sync_playwright
    th = tm = 0
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR), channel="msedge", headless=False,
            args=_ARGS, viewport={"width": 1280, "height": 900}, locale="en-US")
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            for ckey in targets:
                if ckey not in cities:
                    print(f">> unknown city: {ckey}"); continue
                print(f">> {ckey}")
                h, m = harvest_city(page, ckey, dry=args.dry_run, limit=args.limit)
                th += h; tm += m
        finally:
            ctx.close()
    print(f">> done — {th} photos, {tm} still missing" + (" (dry run)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
