# Table for Two — city research & ranking spec

This is the canonical definition of "the list." The weekly refresh (and any
manual run) follows it so results stay consistent over time.

## What qualifies
A restaurant is eligible if it:
- is **currently open** and **takes reservations** (skip pure walk-in-only and fast-casual),
- is a real sit-down restaurant (no food halls, pop-ups under ~3 months old unless major),
- is in the target city or its immediate close-in neighborhoods.

## List size & tiers (protocol v2, 2026-07)
Each city ships up to **50 spots**, researched as two independent tiers and
merged hardest-first:

- **Tier A — impossible tables** (difficulty 4–5): the reservations people
  scheme over. Instant sellouts, ticketed/monthly drops, tiny counters. ~22–28
  candidates researched.
- **Tier B — beloved & bookable** (difficulty 2–3, honestly rated): critic-vetted
  favorites you can actually get — the "Any craving" discovery layer. Same
  provenance covenant, booking mechanics still required (walk-in strategy is
  first-class data here). ~26–34 candidates researched.

Tiers are verified separately, deduped (same venue in both tiers keeps the
higher-difficulty entry), capped at 50. Small markets ship honestly fewer —
minimum 8 verified spots or the city doesn't ship at all. Never pad.

## How we rank "hardest to book"
Ranked on a composite, highest signal first:

1. **Reservation scarcity (objective).** Measured live via Resy's calendar for a
   party of 2 over the next 14 days. **Booked solid = hardest.** Wide-open = easiest.
   This is the strongest, freshest signal and is recomputed every refresh.
2. **Difficulty / demand (1–5).** Set during research from: tiny-room/counter size,
   instant sellouts, long booking windows, monthly/ticketed drops, waitlist sizes.
3. **Acclaim.** Michelin stars, James Beard, credible "best of" / "hardest reservation"
   lists (Eater, The Infatuation, city magazines).
4. **Buzz / recency.** Recently opened hot spots rank up; faded spots rank down.

The composite score used by the pipeline (`curate.py --top N`):

```
score = difficulty*2  +  scarcity*1.5
scarcity = 5 if booked-solid           (availability.open == false)
           4 if 1–3 open days
           3 if 4–7 open days  OR  not auto-checkable (non-Resy)
           2 if 8–12 open days
           1 if wide open (13–14 days)
```
Sort by score desc; tie-break difficulty desc, then name. Keep the top N (25).

## Source of truth per city
- **NYC** — the hardtobook.xyz API (`sources/nyc.json`, refreshed from the API).
- **DC / Richmond / Boston / Houston** — AI web research against Eater, The Infatuation,
  city magazines (Washingtonian, Richmond Mag, Boston Mag, Texas Monthly), Michelin,
  and the venues' own Resy/Tock/OpenTable pages. Candidate pool ~32, ranked, cut to 25.

## Honesty rules
- Never invent release times or platforms — verify or flag "VERIFY".
- Smaller markets (Richmond) may not have 25 *brutal* tables; the tail will be
  "very popular" rather than "near-impossible." That's expected; `evidence` should say so.
- Availability is a **snapshot** (stamped per spot); it goes stale between refreshes.

## The research prompt (used per city, parameterized)
See `refresh.md` / the cloud-routine prompt. Each agent returns a JSON array (~32)
of candidate objects in the dashboard schema plus `difficulty` and a one-line `evidence`,
ordered hardest-first. The pipeline then enriches, checks availability, scores, and trims to 25.
