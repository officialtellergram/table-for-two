# Countdown engine — port spec

The single most important pure-logic component. Port it first, with unit tests,
before any UI. Reference implementations: `index.html` (functions `nextDrop`,
`fmtCountdown`, `spotState`, `parseRelease`-equivalent, `etWallToUtc`) and the
prototype's JS (same math, condensed).

## Inputs (per spot)

`releaseSchedule ∈ daily | weekly | calendar-month | monthly | none`,
`releaseTime` (string), `releaseDay` (weekly only), plus the city's IANA
`timezone` from the manifest.

## Parsing `releaseTime`

Accept: `"10:00 AM ET"`, `"9:00 AM"`, `"12:00 AM (Midnight) ET"`,
`"12:00 PM (Noon) ET"`. Rules:
- `/midnight/i` → 00:00 · `/noon/i` → 12:00
- else regex `(\d{1,2}):(\d{2})\s*(AM|PM)` (12 AM → 0, PM adds 12)
- The trailing zone label is cosmetic — the authoritative zone is the CITY's
  manifest `timezone`. (Spain venues are schedule `none`; their releaseTime is "".)

## Next-drop computation (all in the city's wall clock, DST-safe)

Work in the venue city's timezone via a proper calendar (Swift:
`Calendar(identifier: .gregorian)` with `timeZone = TimeZone(identifier: tz)`).

- `daily`: today at release time; if past, tomorrow.
- `weekly`: next occurrence of `releaseDay` at release time (if today is that day
  but past the time, next week). Default day = Thursday when releaseDay is junk.
- `calendar-month` / `monthly`: the 1st of the current month at release time;
  if past, the 1st of next month.
- `none` → no countdown.

## Spot state machine

```
open      availability.open == true (after dropping past dates)
countdown schedule != none and a next-drop exists
booked    availability exists, checked recently, open == false
unknown   everything else (incl. all TheFork/Website/Phone venues)
```

Display rules per state are in app-spec (copy rules) — notably the platform-honest
`unknown` wording shipped for Spain.

## Formatting

- `< 1 day`: `HH:MM:SS` (monospaced digits, always 2-digit fields)
- `≥ 1 day`: `Nd HH:MM` (web shows `2d 21h 14m` style on cards — match web)
- Intensities: normal → **soon** (amber) under 1 hour → **imminent** (green) at
  ≤ 60 s. Card border warms with `soon`.
- Tick once per second; only countdown cards repaint (perf rule from web).

## The 10:00:00 assist (extends the engine)

Full-screen mode targeting one armed spot: haptics at T-60 and T-3
(CoreHaptics; pre-warm the engine), screen flips `good` green at ≤60 s, button
becomes `Tap at 10:00:00`, tap opens the prefilled platform URL. If the app is
backgrounded, the Live Activity carries the countdown (see push-architecture).

## Test cases to write first

1. Daily 10:00 AM, now 09:59:59 city time → 1 s remaining; now 10:00:01 → ~24 h.
2. Weekly Saturday midnight, queried on Saturday 00:00:30 → 7 days minus 30 s.
3. calendar-month on the 31st at 23:59 → 1st of next month, handles 30-day months.
4. DST transition week in America/New_York — countdown must not jump an hour
   (this is why all math happens in the city calendar, never UTC offsets).
5. `12:00 AM (Midnight) ET` parses to 00:00; `(Noon)` to 12:00.
6. Spain spot (`schedule none`, tz Europe/Madrid) → no countdown, state `unknown`.
7. Stale availability with all `dates` in the past → not `open`.
