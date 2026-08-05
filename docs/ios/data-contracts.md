# Data contracts — everything the app consumes

All data is static JSON on GitHub Pages (same origin as the site). No auth needed
for reads. Poll politely; the radar refreshes `just-opened.json` roughly every
30 min, detection sweeps city files a few times a day.

Base URL: `https://tablefortwo.city/`

## 1. City manifest — `cities/index.json`

```json
{ "cities": [ {
    "key": "nyc", "label": "New York City", "short": "NYC",
    "center": [40.792, -74.0475], "zoom": 12,
    "source": { "type": "json", "url": "cities/nyc.json" },
    "timezone": "America/New_York"
} ] }
```

- 21 cities live (US + `malaga`, `nerja`; more Spain parked mid-pipeline).
- **Auto-locate rule (verified in prod): strict nearest-center-wins within 500 km,
  else no auto pick.** Nerja resolves Nerja (0.2 km) even though Málaga is 48 km
  away. Don't add metro-radius logic; nearest wins.
- `timezone` is IANA; drives all countdown math for that city's venues.

## 2. City spots — `cities/<key>.json`

`{ "meta": {...}, "spots": [Spot] }` where Spot is:

```jsonc
{
  "id": "carbone",                    // stable slug — the identity key everywhere
  "name": "Carbone",
  "neighborhood": "Greenwich Village",
  "cuisine": "Italian",
  "coordinates": { "lat": 40.7554, "lng": -73.9930 },
  "difficulty": 5,                    // 1-5, pipeline-nudged; render as dots
  "priceRange": "$$$$",
  "platform": "Resy",                 // enum below
  "platformUrl": "https://resy.com/cities/new-york-ny/venues/carbone",
  "website": "https://carbonenewyork.com",
  "phoneNumber": "+1 212 …",          // may be empty
  "releaseSchedule": "daily",         // daily | weekly | calendar-month | monthly | none
  "releaseTime": "10:00 AM ET",       // parse rules in countdown-engine.md
  "releaseDay": "",                   // weekly only, e.g. "Saturday"
  "bookingWindow": "28 days",
  "bookingWindowDays": 28,            // authoritative (detection pipeline)
  "walkIns": false,
  "walkIn": { "doors": "5:00 PM", "lineBy": "…", "advice": "…" },  // or null
  "tips": ["…"],
  "signatureDish": "Spicy Rigatoni Vodka",
  "lastVerified": "2026-07-30",
  "availability": {                   // Resy venues only; null elsewhere
    "checkedAt": "2026-06-25", "source": "resy", "partySize": 2,
    "windowDays": 7, "openDays": 1, "open": true, "dates": ["2026-06-25"]
  },
  "vibe": ["special-occasion", "romantic"],       // chips (kebab-case)
  "occasion": ["impress", "anniversary"],         // incl. meal tags for Spain:
                                                  // breakfast|brunch|lunch|dinner|tapas|drinks
  "dateNote": "A special-occasion table worth the wait.",
  "sources": [ { "name": "Michelin", "tier": "1★",
                 "url": "https://guide.michelin.com/…", "note": "…" } ],
  "evidence": "…",
  "photo": "https://image.resy.com/…",   // OPTIONAL — real venue photo (hotlinked)
  "photoAttr": "Resy",                   // credit chip text ("Resy" or source domain)
  "photoChecked": "2026-07-28"           // pipeline bookkeeping; ignore in app
}
```

**Rules the app must honor**

- `platform` enum: `Resy | OpenTable | Tock | SevenRooms | TheFork | CoverManager |
  Website | Phone | Invitation Only` (treat unknown as neutral).
- `watchable(spot) = platformUrl != empty AND platform ∈ {Resy, OpenTable}` —
  the ONLY venues that may show an alert bell. The radar cannot see anything else.
- Photos are **hotlinked**; on image load failure fall back to the generated banner
  (deterministic gradient art seeded by `id`, hue by cuisine — port `drawPhoto`
  from `index.html` if fidelity matters, or any stable per-id art) and hide the
  credit chip.
- Availability is a stamped snapshot. Drop `dates` entries before today when
  displaying; if none survive, treat as not-open.
- Prefill deep links: only inject `date`/party params on hosts that understand
  them (`resy.com` seats=N, `opentable.com` covers=N + dateTime, `exploretock.com`
  size=N, `sevenrooms.com` party_size=N). TheFork/CoverManager/websites get the
  URL untouched.

## 3. Radar feed — `cities/just-opened.json`

```jsonc
{ "generated": "2026-07-26T19:11:25+00:00", "party": 2, "windowDays": 3,
  "count": 200, "new": 4,
  "items": [ {
    "city": "nyc", "spotId": "lilia", "name": "Lilia",
    "neighborhood": "Williamsburg", "cuisine": "Italian",
    "date": "2026-07-26", "time": "21:15", "type": "Patio", "party": 2,
    "url": "https://resy.com/…?date=2026-07-26&seats=2",
    "firstSeen": "2026-07-26T19:11:25+00:00", "new": true
} ] }
```

- `new: true` = first sweep that saw it → JUST OPENED badge.
- `time` is 24h venue-local. `url` is already prefilled — use as-is.
- Feed covers the radar's pinned city set (a subset), not all cities.

## 4. Accounts / watches (Supabase)

The web app uses Supabase (`web/config.js` has URL + anon key — safe to ship,
RLS enforced) for signups + per-spot watches, and fires a `t42-watches` event
pattern worth mirroring: optimistic bell state, server reconciles. Watch schema
and alert fan-out live server-side; see push-architecture.md before touching.

## 5. SEO/static pages

`/<citykey>/` static pages + `/privacy/` + `/terms/` exist — link, don't rebuild.
