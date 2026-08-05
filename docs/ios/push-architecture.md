# Push & alerts — what exists, what the app needs

The app's reason to exist is waking someone the moment a table opens or a drop
lands. This is the one area where server work is required before the app can
deliver its promise. Everything else in the app is a pure client.

## What exists today (all working, all on the web path)

| Piece | Where | What it does |
| --- | --- | --- |
| Radar sweeps | GitHub Actions `radar.yml`, every ~30 min | Diffs Resy slot snapshots per pinned city, writes `cities/just-opened.json`, commits |
| Local detect | Windows scheduled task + `detect.yml` cron | Keeps `bookingWindowDays`/release times authoritative; photo harvest rides along |
| Watches | Supabase (Postgres + RLS) | Signed-in users' per-spot watches; anon key ships in `web/config.js`; writes go through RLS |
| Alert fan-out | `scraper/notify_web.py` (radar step) | Matches new slots against watches, sends **email** via Resend (domain verified for tablefortwo.city). Secrets: `INGEST_URL`/`INGEST_SECRET` repo secrets |
| Demand sync | radar workflow step | Mirrors Supabase RPCs into `cities/demand.json` / `restaurant-queue.json` |

So: detection and matching already run on schedule. **The only missing piece for
the app is an APNs delivery leg next to the email leg.**

## What to build (in order)

1. **Device registration**: app requests notification permission at first
   watch-arm (not at boot), gets APNs device token, stores it in a new Supabase
   table (`device_tokens`: user_id, token, platform, updated_at; RLS: owner-only).
2. **APNs sender**: extend `notify_web.py` (or a sibling `notify_apns.py` invoked
   by the same radar step) to also push to tokens whose user has a matching watch.
   Token-based APNs auth (a `.p8` key from the Developer account — a repo secret,
   never committed). Payload: title "A table for two just opened at <name>",
   body `<Day, Mon D> · <time> · <type>`, deep-link URL into the app
   (`tablefortwo://spot/<city>/<id>`), collapse-id per spot to avoid stacking.
3. **Live Activities** (after basic push works): start an Activity when the user
   arms the 10:00:00 assist; update via APNs `liveactivity` pushes (or locally
   while foregrounded — the timer is client-computable, so local updates cover
   most of it; server push only needed to end/replace it).
4. **Widgets** read the same cached JSON — no server work.

## Constraints & cautions

- Push entitlements require the paid Apple Developer Program.
- The radar sees **Resy/OpenTable only** — the matching leg already enforces this;
  the app must too (no bells elsewhere).
- Cadence is the open product decision: cap pushes per watch per night (start: 3)
  and always include the loss follow-up pattern ("gone in 41s") in-app, not as push.
- Secrets live as GitHub repo secrets / Supabase function config — never in the
  app bundle. The anon key in the client is fine (RLS), the APNs key is not.
- Dry-run flag exists in `notify_web.py` (`--dry-run`) — added after a real-send
  incident. Keep the same discipline in the APNs leg from day one.
