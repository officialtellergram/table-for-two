# App spec — Table for Two iOS

Source of truth for what the app is. Distilled from the validated interactive
prototype + review deck (claude.ai design project "iOS app design system
exploration"); superseding notes at the end reflect decisions made since.

## The answered brief

| Question | Answer |
| --- | --- |
| Scope | Onboarding, city feed, detail sheet, map, radar, alerts, filters + search |
| #1 job on open | What's bookable right now (radar-first) |
| Tab bar | Tonight · Radar · Map · Alerts · Me |
| Push | Yes — lock screen + Live Activity countdown; this is the app's reason to exist (the browser can't wake you at 10:00:00) |
| Data | Real city data from this repo (start NYC) |
| Imagery | Photo-forward cards (per-venue `photo` field; generated fallback otherwise); one hero per detail sheet |
| iOS-only capabilities | Live Activity / Dynamic Island, home widget, haptic 10:00:00 assist, calendar handoff, Apple Maps walk-ins |
| Tone | Same as web: dry, confident, insider |

## Architecture: five tabs, two jobs

Acquisition job = the radar/alerts (impossible tables). Retention job = discovery.

### Tab bar
`Tonight · Radar · Map · Alerts · Me` — active `accent2`, inactive `faint`,
glass bar (`.ultraThinMaterial` over bg at ~0.8 opacity).

### Tonight (home — "the count is the headline")
1. Header: mark + wordmark + city pill (opens city sheet from `cities/index.json`).
2. "Open right now" — count of spots with `availability.open == true`, stamped
   `as of <checkedAt>`. Big number in `good` green, 40pt+, tabular.
3. Open cards: photo banner w/ name+platform overlaid, price, `✓ Booking Available`,
   `<openDays> of next 7 nights · party 2 · as of …`, vibe chips, Grab it + bell.
4. "Drops next" rows: thumbnail, name, `releaseTime · schedule · window out`,
   live countdown, bell. Row border warms (`soon` amber at 50% opacity) under one hour.
5. Footer disclaimer verbatim from web: countdowns run in the restaurant's local
   time; a snapshot, not a live seat map; always confirm.

### Radar (Just Opened)
Feed = `cities/just-opened.json` (shape in data-contracts). Row copy:
`<Day, Mon D> · <time> · <type>` + `spotted <ago>`. Items with `new: true` get the
`JUST OPENED` badge, green border + `0 0 0 1px good@22%` ring. Filters: All ·
Just opened · Prime time (18:00–21:00). Actions: **Grab it** (opens the prefilled
booking URL) + **Add to calendar** (EventKit).

### Map
Pins colored by state (green = open now, gold = counting down). Bottom sheet mirrors
the web popup (name / hood·cuisine·price / status line) plus **"Walk-ins nearby"**
handing off to Apple Maps. Use MapKit; venue coords are in every spot.

### Alerts ("a watch is a promise with a window")
Per-watch: night range + time window (defaults 17:30–21:30), party size (default 2),
toggle. Only offered where `watchable(spot)` is true — `platformUrl` present AND
platform ∈ {Resy, OpenTable} (the radar can only see those; never promise otherwise).
Recent-pings list keeps the losses ("Gone in 41 seconds") — honesty is retention.
Backed by the existing Supabase watches tables (see push-architecture).

### Me
Home city, default party, nights-out range, notification toggles, and one honest
switch each for: 10:00:00 haptic assist, add-drops-to-Calendar, Live Activity.
Links: Privacy (`/privacy/`), Terms (`/terms/`), support@tablefortwo.city.

### Detail sheet ("a briefing, not a listing")
Hero photo (`photo` or generated fallback) → **Vetted by** (`sources[]` name + tier,
links out — the anti-slop trust signal) → countdown box (or `✓ Booking available`) →
`dateNote` in italic gold → vibe chips → `signatureDish` → `tips[]` (checkmarked list)
→ **Arm the 10:00:00 assist** (primary, only when a countdown exists) → platform CTA
+ Alert me (if watchable) → Open in Maps / Add to calendar.

### Drop assist (full screen)
Venue name, giant `mm:ss`, haptic buzz at T-60 and T-3, then opens the platform
prefilled for two. Under a minute the whole screen flips to `good` green and the
button reads `Tap at 10:00:00`. This is the moment the product is for — polish it.

### Off-app (the product mostly happens on the lock screen)
- **Push**: "A table for two just opened at Carbone" + `date · time · room`.
- **Live Activity**: `mm:ss` to the next armed drop, venue · platform, progress bar;
  compact form in the Dynamic Island.
- **Widgets**: small = next-drop countdown; small = open-now count.

### Onboarding
Ports the web landing choreography: line-art mark draws in → wordmark →
"Any city. Any craving." → one ask: location (for auto-city). Notification
permission is deferred until the user arms their first watch (ask at the moment
of intent, not at boot).

## Copy rules

- Keep the web's exact strings: "Booked solid", "Check next 7 days",
  "✓ Booking Available".
- Platform-honest availability wording (post-Spain rule): a phone-first or walk-in
  venue reads "Reserve by phone" / "Walk right in" — **never** "Invitation only"
  (that label is only for `/invitation/i` platforms).
- Never imply live data: availability is a snapshot stamped "as of …".
- No emoji. `✌︎` and `✓` only.

## Decisions since the prototype (supersede it where they conflict)

1. **Cards are photo-forward** (shipped on web): full-bleed image top, scrim,
   name/platform overlaid, credit chip ("Photo · Resy" / source domain). The
   prototype's text-first card is obsolete.
2. **International platforms exist**: TheFork + CoverManager (Spain live now) with
   their own brand inks; unknown platforms get the neutral invite ink. No alert
   bells on them.
3. **Difficulty is data, not decoration** — dots come from the detection pipeline's
   nudged values; don't invent.
4. The one open design decision from the review deck that still stands: push copy
   cadence (how many alerts per night before a watch becomes noise). Decide with
   real usage.
