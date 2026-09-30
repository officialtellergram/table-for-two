# Design references — the standing rubric for the reframe

Distilled from six reference reels Karen supplied (2026-09-29), ingested via a
split→explore→merge graph (three parallel vision agents over 118 extracted
frames). This file is the arbiter for visual/UX decisions on the `reframe`
branch. When in doubt, this beats taste.

## The one-line synthesis

One expressive display serif moment per screen, everything else quiet, solid,
and instrumented — technical-luxury, not template glass — with the match
reveal engineered as the peak, and honesty as a hard constraint.

## Sources

| # | Account | Content | Governs |
| --- | --- | --- | --- |
| A | @markynv | Font pairings that demand attention | Typography |
| B | @millee.md | 20 reasons your app looks vibecoded | Anti-default audit |
| C | @millee.md | 20 things so your app doesn't get sued | Trust/compliance |
| D | @kenny.kenray | 7 friction laws (Hick/Fitts/Jacob/Miller/Peak-End/Proximity/Von Restorff) | Conversion UX |
| E | @sambit.ai.tech | Graph engineering (diamond pattern) | Build process |
| F | @zacharywinterton | "Design Department" motion identity | Visual identity |
| G | @verycoolentrepreneur | Agentic engineering (11 production layers) | Definition of done |

## Type system (A + B)

- **Two voices, always.** Display serif (Fraunces, high optical size) for the
  emotional word: restaurant names, headlines, the match reveal. Tracked
  micro-caps for functional labels (already our signature — keep).
- **Scale contrast does the work**: display words 5–10× the label size.
- A third **mono voice** for instrumentation (F): spec plates, coordinates,
  counters, footers.
- Banned: Inter-as-identity (B4), Space Grotesk + Instrument Serif (B19 — the
  fashionable escape route is already the next cliché), decorative italic
  sprinkles (B18; one deliberate hero italic is fine).

## Surfaces & color (B + F)

- **No glassmorphism** (B6). Solid near-black panels, 1px hairline borders
  (gold at low alpha), real shadows.
- **Gold #c9a86a on near-black stays** — it's a deliberate luxury choice, not
  on the vibecoded list. No gradients added to it (B1/B2/B20).
- Photo scrims stay (editorial necessity) — black-to-transparent only,
  disciplined stops, never tinted.
- **Contrast floor 4.5:1 for all text** (B7 + C14): audit every muted/faint
  token; secondary text is where dark modes fail.

## Instrumentation idiom (F)

- One cinematic hero per screen + a halo of small mono metadata: coordinates
  in DMS, card №, platform/difficulty spec plates (`RESY · DIFF 5/5`).
- Badges as certification stamps: capsule/boxed, hairline, uppercase, no
  emoji ever. Swipe verdicts land as rotated rubber stamps.
- Decode/scramble-settle text animation for the reveal moments only —
  restraint is the point. Respect reduced-motion.
- Dry aphorism register for footers/empty states, in mono micro-caps.

## Conversion mechanics (D)

- Hick: one card, one decision; quiz ≤4 questions, ≤2 primary actions per view.
- Fitts: **Book is the biggest tappable element in the entire flow**,
  bottom-anchored.
- Jacob: Tinder grammar exactly; platform-native booking pills at the end.
- Miller/Proximity: metadata chunked into ≤3-item clusters.
- Peak-End: the match reveal is the designed peak (decode animation, hero
  photo, gold moment); end on a clean confirmation. Von Restorff: gold
  highlight reserved for the one thing that matters per screen.

## Trust constraints (C) — non-negotiable

- Scarcity/availability cues must be real pipeline data, never manufactured.
- Real alt text on venue imagery; full keyboard path for the deck (←/→/Z).
- Privacy/Terms/contact reachable; quiz collects only what ranking uses;
  sessions work without accounts.
- Photos and fonts licensed (Fraunces = OFL; photos via the harvest
  pipeline's source-credit rules).

## Process (E + G) — how we build, and what "done" means

- **Diamond (E)**: split → parallel explore → reviewer node → merge. Karen is
  the human gate on anything expensive to undo (prod deploys, main pushes,
  spend).
- **Stop rule**: sequential work gets one agent; fan out only where slices are
  independent.
- One job per node; pass clean written contracts between nodes, not raw
  transcripts; review before merge, not after deploy.
- **Definition of done (G) — the 11-layer board.** "Build me an app, make no
  mistakes" is a wish, not a spec; done = every production layer checked:
  1. Frontend hygiene (minified, no exposed secrets/source maps)
  2. Database with RLS on
  3. Auth with real permissions
  4. Version control discipline
  5. APIs
  6. Hosting/deploy
  7. Security
  8. Rate limiting ("so people can't take your money")
  9. Caching ("so your thing isn't slow")
  10. Scaling/load balancing
  11. Error tracking ("so you know what's going wrong")
- Prompt nodes **by failure mode**, not feature ("rate-limit X so a scraper
  can't drain Y") — that's what makes one-job-per-node evaluable.
- The two compose: G's board is the payload of the evaluate/merge gates; E's
  diamond is the machinery that builds each layer. G alone would ship
  unverified single-path agent output — the reviewer node stays.
- Merge criterion for the paid wedge: "would I charge for this today?"
