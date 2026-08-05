# Table for Two — iOS handoff pack

This folder is the complete brief for building the native iOS app on a Mac.
It was written on the Windows machine that runs the data pipelines, so a fresh
Claude Code session on the Mac inherits every decision without reconstructing
them. Read this file first; the rest in any order.

| Doc | What it holds |
| --- | --- |
| [app-spec.md](app-spec.md) | The full product spec — tabs, screens, off-app moments, copy rules. Source of truth. |
| [design-tokens.md](design-tokens.md) | Exact colors/type/geometry lifted from production `index.html`. Inherited, not invented. |
| [data-contracts.md](data-contracts.md) | Every JSON shape the app consumes, the platform enums, and the honesty rules. |
| [countdown-engine.md](countdown-engine.md) | The reservation-drop countdown logic with a reference implementation to port. |
| [push-architecture.md](push-architecture.md) | What alert infrastructure exists today and what the app's push path still needs. |

## Where this project stands

- **Web app is live** at [tablefortwo.city](https://tablefortwo.city) (repo root `index.html`,
  GitHub Pages). 21 cities including Málaga + Nerja (Spain). Photo-forward cards, live
  countdowns, per-card alert signups, map, PWA.
- **An interactive iOS prototype already exists** — a full tappable mock (5 tabs, live
  countdowns, detail sheets, lock-screen Live Activity, widgets, drop assist) built as a
  Claude artifact, plus a 12-slide review deck and `outline.md` in the claude.ai design
  project "iOS app design system exploration". Log into claude.ai from the Mac to view
  them; `app-spec.md` here captures everything they decided.
- **The data pipelines stay on the Windows PC** (radar sweeps, booking-window detection,
  photo harvest). The app is a pure consumer of their output — nothing here needs to move.

## Framework decision (made, don't relitigate)

**Native SwiftUI.** The app's differentiators — lock-screen Live Activity countdown,
Dynamic Island, home-screen widgets (WidgetKit), the 10:00:00 haptic assist
(CoreHaptics), calendar handoff — are native-only APIs. Any wrapper stack would need
Swift extensions for exactly these, so we go straight to Swift.

## First-session sequence on the Mac

1. Prereqs done outside Claude: Xcode installed, `xcode-select --install`, Apple ID
   signed into Xcode. (Developer Program $99/yr needed only when TestFlight/push
   entitlements enter the picture.)
2. `git clone` this repo → open in VSCode → `claude` → build in a new `ios/` folder
   at repo root (keep the app in this repo; it shares the data contracts).
3. Scaffold: SwiftUI app, five-tab shell per `app-spec.md`, design tokens as a
   `Theme.swift` generated from `design-tokens.md`.
4. Port the countdown engine first (`countdown-engine.md`) — pure logic, unit-testable,
   no UI dependencies. Write the tests before the views.
5. Wire the Tonight tab to live data (`https://tablefortwo.city/cities/nyc.json`) and
   run in the simulator.
6. Iterate visually: build with `xcodebuild`, drive the simulator with `xcrun simctl`
   (boot, install, launch, `simctl io screenshot`) so Claude can verify its own UI work
   the way the web side uses Playwright.
7. Live Activities / push / widgets last — they need the paid account, entitlements,
   and the server work described in `push-architecture.md`.

## Working agreements that carry over from the web side

- Verify before push: run it, screenshot it, then ship. Report failures plainly.
- Never promise an alert on a platform the radar can't see (Resy/OpenTable only).
- Copy tone: dry, confident, insider. No emoji in product copy (`✌︎` and `✓` are the
  only marks in use). Availability is always a stamped snapshot, never implied-live.
- The photo pipeline owns imagery; a spot without `photo` gets the generated fallback
  banner, deterministic per venue id (see data-contracts).
