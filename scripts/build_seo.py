#!/usr/bin/env python3
"""Prerender static, crawlable SEO pages — one per covered city — from the same
cities/*.json the app renders client-side. Crawlers see a real venue list with
provenance; humans get a wedge-first CTA into the alert funnel.

Output: /<city-key>/index.html  +  /sitemap.xml  +  /robots.txt
Runs in CI on any push touching cities/** (see .github/workflows/seo.yml), and
locally for testing. Idempotent — same data in, same bytes out.
"""
import html
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CITIES = ROOT / "cities"
BASE = "https://tablefortwo.city"
SKIP = {"index", "just-opened", "demand", "restaurant-queue", "_template"}

DIFF_WORD = {5: "near-impossible", 4: "very hard", 3: "hard", 2: "in-demand", 1: "gettable"}


def esc(x):
    return html.escape(str(x if x is not None else ""), quote=True)


def load_cities():
    man = json.loads((CITIES / "index.json").read_text(encoding="utf-8"))
    out = []
    for c in man.get("cities", []):
        if (c.get("source") or {}).get("type") != "json":
            continue
        f = CITIES / f"{c['key']}.json"
        if not f.exists():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        spots = data.get("spots") if isinstance(data, dict) else data
        if spots:
            out.append((c, spots))
    return out


def jsonld(city, spots):
    """ItemList of Restaurants — the structured data Google reads for rich results."""
    items = []
    for i, s in enumerate(spots, 1):
        r = {
            "@type": "Restaurant", "name": s.get("name"),
            "servesCuisine": s.get("cuisine"),
            "url": s.get("website") or s.get("platformUrl"),
        }
        if s.get("priceRange"):
            r["priceRange"] = s["priceRange"]
        co = s.get("coordinates") or {}
        if co.get("lat") and co.get("lng"):
            r["geo"] = {"@type": "GeoCoordinates", "latitude": co["lat"], "longitude": co["lng"]}
        r["address"] = {"@type": "PostalAddress", "addressLocality": city["label"],
                        "addressRegion": s.get("neighborhood", "")}
        items.append({"@type": "ListItem", "position": i, "item": {k: v for k, v in r.items() if v}})
    return json.dumps({
        "@context": "https://schema.org", "@type": "ItemList",
        "name": f"Hardest restaurant reservations in {city['label']}",
        "numberOfItems": len(spots), "itemListElement": items,
    }, ensure_ascii=False)


def venue_row(s):
    diff = int(s.get("difficulty") or 0)
    dots = "".join("●" if i < diff else "○" for i in range(5))
    plat = s.get("platform") or ""
    sched = s.get("releaseSchedule")
    drop = ""
    if sched and sched != "none":
        rt = s.get("releaseTime")
        drop = f'<span class="drop">{esc((rt + " · ") if rt else "")}{esc(sched)} drop</span>'
    sources = "".join(
        f'<a class="src" href="{esc(src.get("url"))}" rel="nofollow noopener" target="_blank">{esc(src.get("name"))}</a>'
        for src in (s.get("sources") or []) if src.get("url"))
    vetted = f'<div class="vetted"><span>Vetted by</span> {sources}</div>' if sources else ""
    book = ""
    if s.get("platformUrl"):
        book = f'<a class="book" href="{esc(s["platformUrl"])}" rel="nofollow noopener" target="_blank">Book on {esc(plat)}</a>'
    return f"""<li class="venue">
      <div class="v-head"><h3>{esc(s.get('name'))}</h3><span class="diffdots" title="{esc(DIFF_WORD.get(diff,''))}">{dots}</span></div>
      <div class="v-meta">{esc(s.get('neighborhood'))} · {esc(s.get('cuisine'))} · {esc(s.get('priceRange'))} · {esc(plat)}</div>
      {f'<p class="v-evi">{esc(s.get("evidence"))}</p>' if s.get('evidence') else ''}
      {drop}
      {vetted}
      {book}
    </li>"""


def page(city, spots):
    key, label = city["key"], city["label"]
    hardest = [s for s in spots if int(s.get("difficulty") or 0) >= 4]
    n = len(spots)
    title = f"The {n} Hardest Restaurant Reservations in {label} (2026) — Table for Two"
    desc = (f"The {n} hardest tables to book in {label}, vetted by real critics — with how "
            f"each reservation drops and a free alert the moment one opens up. No Yelp, no slop.")
    canonical = f"{BASE}/{key}/"
    rows = "\n".join(venue_row(s) for s in spots)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}" />
<link rel="canonical" href="{canonical}" />
<meta name="theme-color" content="#0d0a0e" />
<meta property="og:type" content="website" />
<meta property="og:site_name" content="Table for Two" />
<meta property="og:title" content="{esc(title)}" />
<meta property="og:description" content="{esc(desc)}" />
<meta property="og:url" content="{canonical}" />
<meta property="og:image" content="{BASE}/icons/og-square.png" />
<meta name="twitter:card" content="summary" />
<link rel="icon" type="image/png" href="/icons/favicon.png" />
<script type="application/ld+json">{jsonld(city, spots)}</script>
<style>
  :root{{color-scheme:dark;--bg:#0a0a0b;--txt:#f4f3f1;--muted:#8a8a90;--gold:#d8b47c;--line:#212124;--good:#86b6a0}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--txt);font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5}}
  a{{color:var(--gold)}}
  .wrap{{max-width:820px;margin:0 auto;padding:32px 20px 64px}}
  header a.brand{{color:var(--gold);font-weight:600;letter-spacing:2px;text-transform:uppercase;text-decoration:none;font-size:14px}}
  h1{{font-size:clamp(26px,5vw,40px);line-height:1.15;margin:24px 0 8px;text-wrap:balance}}
  .lede{{color:var(--muted);font-size:17px;max-width:60ch}}
  .cta{{display:inline-flex;align-items:center;gap:8px;margin:22px 0 8px;padding:13px 22px;border-radius:999px;
    background:color-mix(in srgb,var(--good) 15%,transparent);border:1px solid color-mix(in srgb,var(--good) 55%,transparent);
    color:var(--good);font-weight:600;text-decoration:none}}
  .covenant{{color:var(--muted);font-size:13px;margin:6px 0 28px}}
  ul.venues{{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:14px}}
  .venue{{border:1px solid var(--line);border-radius:14px;padding:16px 18px;background:#101011}}
  .v-head{{display:flex;justify-content:space-between;align-items:baseline;gap:12px}}
  .v-head h3{{margin:0;font-size:19px}}
  .diffdots{{color:var(--gold);letter-spacing:2px;font-size:12px;white-space:nowrap}}
  .v-meta{{color:var(--muted);font-size:13.5px;margin-top:2px}}
  .v-evi{{margin:8px 0 0;font-size:14.5px}}
  .drop{{display:inline-block;margin-top:8px;font-size:12.5px;color:var(--gold)}}
  .vetted{{margin-top:10px;font-size:12px;color:var(--muted);display:flex;flex-wrap:wrap;gap:6px;align-items:center}}
  .vetted .src{{border:1px solid var(--line);border-radius:999px;padding:2px 9px;text-decoration:none;font-size:11.5px}}
  .book{{display:inline-block;margin-top:12px;padding:8px 15px;border-radius:999px;border:1px solid color-mix(in srgb,var(--gold) 40%,transparent);color:var(--gold);text-decoration:none;font-size:13.5px;font-weight:600}}
  footer{{margin-top:40px;color:var(--muted);font-size:13px;border-top:1px solid var(--line);padding-top:20px}}
</style>
</head>
<body>
<div class="wrap">
  <header><a class="brand" href="/">← Table for Two</a></header>
  <h1>The hardest tables in {esc(label)} — and how to actually get them</h1>
  <p class="lede">{esc(len(hardest))} near-impossible reservations and {esc(n - len(hardest))} more beloved rooms,
    each vetted against real critics. We watch the ones that never have availability and
    <strong>alert you the second a table for two opens up</strong>.</p>
  <a class="cta" href="/?city={esc(key)}">Get free alerts for {esc(label)} →</a>
  <p class="covenant">Every spot below is endorsed by a named critic or publication — never Yelp, Google reviews, or SEO listicles.</p>
  <ul class="venues">
{rows}
  </ul>
  <footer>
    Reservation mechanics and availability change constantly — always confirm with the restaurant.
    <a href="/?city={esc(key)}">Open {esc(label)} in Table for Two →</a> for live countdowns and cancellation alerts.
  </footer>
</div>
</body>
</html>
"""


def main():
    cities = load_cities()
    if not cities:
        print("no city data found", file=sys.stderr)
        return 1
    written = []
    for city, spots in cities:
        d = ROOT / city["key"]
        d.mkdir(exist_ok=True)
        (d / "index.html").write_text(page(city, spots), encoding="utf-8")
        written.append((city, spots))

    # sitemap: root + every city page
    urls = [f"  <url><loc>{BASE}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>"]
    for city, _ in written:
        urls.append(f"  <url><loc>{BASE}/{city['key']}/</loc><changefreq>daily</changefreq><priority>0.8</priority></url>")
    for legal in ("privacy", "terms"):   # static red-tape pages
        urls.append(f"  <url><loc>{BASE}/{legal}/</loc><changefreq>monthly</changefreq><priority>0.3</priority></url>")
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls) + "\n</urlset>\n", encoding="utf-8")
    (ROOT / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n", encoding="utf-8")

    print(f"SEO: wrote {len(written)} city pages + sitemap.xml + robots.txt")
    for city, spots in written:
        print(f"  /{city['key']}/  ({len(spots)} venues)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
