# Cancellation radar — `sniper.py`

Turns Table for Two from a scoreboard into a radar: it watches slot-level Resy
availability for the tracked venues and surfaces the *freshest* openings (the
cancellations) in the site's **Just Opened ✨** feed.

## What it does each run
1. For each manifest city, take the top Resy venues (`--limit`).
2. Resolve each venue id once (cached in `.sniper_state.json`).
3. Pull slot-level openings via `resy_find.slots()` for the next `--days` days.
4. Diff against the previous run: a slot we hadn't seen at a venue we'd already
   scanned = **new** (a cancellation). A venue's first scan is a baseline.
5. Write `cities/just-opened.json` (+ the `deploy/` mirror): every current open
   slot with `firstSeen` and a `new` flag, newest first.

## Cadence
It's only a radar if it runs often. Run on a **short interval** — every 3–5 min
is a good balance of freshness vs. politeness to the public Resy key:

```bash
python sniper.py --days 4 --limit 8 --sleep 0.4
```

The longer it runs, the better — `firstSeen` is only as old as the first run
that saw a slot, so "spotted 2m ago" means it genuinely just appeared.

## Going live (pick a host)
- **Cloud routine** (`/schedule`) — simplest; cron in the cloud, commits the
  feed, the site auto-deploys. Good for a 5-min loop.
- **Netlify scheduled function** — runs next to the site; ~1/min ceiling.
- **Tiny always-on worker** — most control / fastest polling.

## Scope note
Polling *every* venue doesn't scale and risks rate-limiting. The honest
production shape is **per-user watchlists** (Phase 3): each person stars a few
spots + a window, and we only poll those. `--cities` / `--limit` keep the
current sweep modest in the meantime.
