"""
resy_verify.py — validate & repair Resy booking links.

Resy is a client-rendered SPA: every venue URL (valid or not) returns the same
200 HTML shell, so a guessed-wrong slug silently renders an EMPTY page instead
of erroring. That's the "Resy link shows nothing" bug. We can't tell good from
bad by scraping the page — but Resy's own venue API can:

  GET  https://api.resy.com/3/venue?url_slug=..&location=..   -> 200 valid / 404 not found
  POST https://api.resy.com/3/venuesearch/search             -> resolve name -> correct slug

Both use the public web api_key that resy.com itself ships in-browser. We use it
read-only and at low volume, purely to validate links — no booking, no account.
"""
import re, time, json
from datetime import date as _date, timedelta
try:
    import requests
except ImportError:
    requests = None

RESY_KEY = 'VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5'  # public web key shipped by resy.com
_H = {
    "Authorization": f'ResyAPI api_key="{RESY_KEY}"',
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Origin": "https://resy.com", "Referer": "https://resy.com/",
    "X-Origin": "https://resy.com", "Accept": "application/json",
}
_SLUG_RE = re.compile(r'resy\.com/cities/([^/]+)/venues/([^/?#]+)', re.I)


def _norm(s):
    return re.sub(r'[^a-z0-9]+', '', (s or '').lower())


def venue_info(slug, loc, session=None):
    """Resy venue record {id, slug} if the venue exists, else None."""
    if not requests:
        return None
    s = session or requests
    try:
        r = s.get("https://api.resy.com/3/venue",
                  params={"url_slug": slug, "location": loc}, headers=_H, timeout=20)
        if r.status_code != 200:
            return None
        d = r.json()
        return {"id": (d.get("id") or {}).get("resy"), "slug": d.get("url_slug") or slug}
    except Exception:
        return None


def validate(slug, loc, session=None):
    """True if the Resy venue page exists; None if it couldn't be checked."""
    if not requests:
        return None
    return venue_info(slug, loc, session) is not None


def availability(spot, party_size=2, window_days=14, today=None, session=None):
    """Real Resy availability for a spot over the next `window_days`.
    Returns a snapshot dict (or None if not a checkable Resy venue)."""
    if not requests or (spot.get("platform") or "") != "Resy":
        return None
    m = _SLUG_RE.search(spot.get("platformUrl") or "")
    if not m:
        return None
    info = venue_info(m.group(2), m.group(1), session)
    if not info or not info.get("id"):
        return None
    today = today or _date.today()
    end = today + timedelta(days=window_days - 1)
    s = session or requests
    try:
        r = s.get("https://api.resy.com/4/venue/calendar",
                  params={"venue_id": info["id"], "num_seats": party_size,
                          "start_date": today.isoformat(), "end_date": end.isoformat()},
                  headers=_H, timeout=20)
        if r.status_code != 200:
            return None
        days = r.json().get("scheduled", [])
    except Exception:
        return None
    open_days = [d["date"] for d in days
                 if (d.get("inventory") or {}).get("reservation") == "available"]
    return {"checkedAt": today.isoformat(), "source": "resy", "partySize": party_size,
            "windowDays": window_days, "openDays": len(open_days),
            "open": len(open_days) > 0, "dates": open_days}


def slug_candidates(name):
    """Plausible Resy url_slugs for a venue name (Resy joins inconsistently:
    'La' Shukran' -> 'lashukran', 'Don Angie' -> 'don-angie')."""
    import unicodedata
    base = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    toks = re.findall(r'[a-z0-9]+', base)
    if not toks:
        return []
    out = []
    def add(t):
        for v in (''.join(t), '-'.join(t)):
            if v and v not in out:
                out.append(v)
    add(toks)
    if toks[0] in ("the", "le", "la", "el"):   # try without a leading article too
        add(toks[1:])
    return out


def search_slug(name, lat, lng, session=None):
    """Resolve a venue name near (lat,lng) to a Resy url_slug via search, or None."""
    if not requests or lat is None or lng is None:
        return None
    s = session or requests
    # Resy's search changed contract (2026): it now wants a form-encoded POST with
    # a single stringified `struct_data` holding query+geo+types. A JSON body 400s
    # ("missing struct_data parameter"). Verified working 2026-07-24.
    struct = {"query": name, "geo": {"latitude": lat, "longitude": lng}, "types": ["venue"]}
    try:
        r = s.post("https://api.resy.com/3/venuesearch/search",
                   headers={**_H, "Content-Type": "application/x-www-form-urlencoded"},
                   data={"struct_data": json.dumps(struct)}, timeout=20)
        if r.status_code != 200:
            return None
        hits = (r.json().get("search") or {}).get("hits", [])
    except Exception:
        return None
    want = _norm(name)
    for h in hits:                      # hits are geo-ranked; take the first real name match
        hn = _norm(h.get("name"))
        if hn and (hn == want or want in hn or hn in want):
            return h.get("url_slug")
    return None


def resolve_slug(name, loc, lat, lng, session=None):
    """Find the venue's real Resy slug in `loc`: try name-derived slug variants
    (authoritative direct lookups), then fall back to geo search. None if not on Resy."""
    for cand in slug_candidates(name):
        if validate(cand, loc, session):
            return cand
        time.sleep(0.25)
    hit = search_slug(name, lat, lng, session)
    if hit and validate(hit, loc, session):
        return hit
    return None


def repair_spot(spot, log=lambda m: None, session=None):
    """Validate/repair one spot's Resy link in place. Returns a status string."""
    if (spot.get("platform") or "") != "Resy":
        return "skip"
    m = _SLUG_RE.search(spot.get("platformUrl") or "")
    if not m:
        return "skip"
    loc, slug = m.group(1), m.group(2)
    ok = validate(slug, loc, session)
    if ok:
        return "ok"
    if ok is None:
        return "unchecked"            # network/requests unavailable — leave as-is
    time.sleep(0.3)
    coord = spot.get("coordinates") or {}
    fixed = resolve_slug(spot.get("name"), loc, coord.get("lat"), coord.get("lng"), session)
    if fixed and fixed != slug:
        spot["platformUrl"] = f"https://resy.com/cities/{loc}/venues/{fixed}"
        log(f"    Resy slug fixed: {slug} -> {fixed}")
        return "fixed"
    # genuinely not on Resy — point the booking link somewhere real
    log(f"    NOT on Resy: {slug} — falling back to website")
    tip = "Not bookable on Resy — reserve via the website or by phone"
    if tip not in spot.get("tips", []):
        spot.setdefault("tips", []).append(tip)
    if spot.get("website"):
        spot["platform"] = "Website"
        spot["platformUrl"] = spot["website"]
    else:
        spot["platformUrl"] = ""
    return "not_on_resy"
