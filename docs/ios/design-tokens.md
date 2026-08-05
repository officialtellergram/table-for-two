# Design tokens — lifted verbatim from production `index.html` `:root`

Generate `Theme.swift` from this file. The identity is **inherited, not invented**:
these are the live site's values. Where iOS needs a judgment call, match the web
rendering, not taste.

## Color — dark (default)

| Token | Hex | Use |
| --- | --- | --- |
| `bg` | `#0a0a0b` | app ground |
| `panel` | `#101011` | card fill |
| `panel2` | `#161618` | raised fill |
| `line` | `#212124` | hairline |
| `line2` | `#34343a` | hover hairline |
| `txt` | `#f4f3f1` | primary text |
| `muted` | `#8a8a90` | secondary text |
| `faint` | `#56565c` | labels, tertiary |
| `accent` | `#c9a86a` | gold — section labels, diff dots |
| `accent2` | `#dcc28c` | gold highlight, primary CTA fill |
| `good` | `#86b6a0` | booking available / armed / open pins |
| `soon` | `#cda766` | drop imminent (≤1h) |
| `onaccent` | `#15110a` | text on gold |
| `dot` | `#2c2c30` | empty difficulty dot |

Wordmark gradient: `linear-gradient(94°, #f4f3f1, #dcc28c 55%, #c9a86a)` clipped
to text. Uppercase, weight 500, tracking 3.5.

## Color — light

`bg #f4f3ef · panel #fffffe · panel2 #efece5 · line #e5e1d8 · line2 #d3cec3 ·
txt #1b1a1c · muted #6f6c74 · faint #a8a4ac · accent #a8843c · accent2 #937734 ·
good #3f8068 · soon #a8803a · onaccent #fffaf0 · dot #d9d5cc`
Light wordmark gradient: `94°, #2a2a2c → #9c7d3a 55% → #a8843c`.

## Platform inks (dark / light)

| Platform | Dark | Light |
| --- | --- | --- |
| Resy | `#c97078` | `#bf4651` |
| OpenTable | `#c87a68` | `#bf5641` |
| Tock | `#7d97bd` | `#3f6aa0` |
| SevenRooms | `#9b92c4` | `#6c60b4` |
| TheFork | `#4fbfa8` | `#0e8a72` |
| CoverManager | `#a8b46b` | `#74812f` |
| unknown/Invitation | `#9a9aa0` | `#7a7780` |

## Type (web values → SF equivalents)

Web uses Inter; on iOS use the system SF stack and match weights/tracking.

- Body: 15 / 1.55, letter-spacing −0.1
- Venue name: 17.5 / 600 / −0.3 (19 white over photo banners)
- Sub (hood · cuisine): 12, `muted`
- Section label: 11, tracking 0.18em, uppercase, `accent`
- Countdown: 23 / 600 / **monospaced digits** / −0.5 (assist screen: 66 / −3)
- Platform pill: 9.5 / 600 / tracking 1.4 / uppercase
- Date note: italic, `accent2`, 13
- Big count (Tonight headline): 44 / 600 / −1.5, `good`, monospaced digits

## Geometry & surfaces

- Card radius 14; border 1px `white@14%` (dark); shadow `0 8 30 black@34%`
- Glass: blur 13–22 + saturation 1.4 (`.ultraThinMaterial` approximates; tint toward `panel`)
- Diagonal sheen on cards: `135°, white@11% → transparent 44%`
- Photo banner: height ~170, scrim gradient to-top
  `#040406: 94% @0 → 88% @20% → 70% @38% → 36% @56% → 8% @76% → 28% @100%`;
  caption text needs BOTH shadows: tight (`0 1 3 black@95%`) + wide (`0 2 16 black@75%`).
  Scrim layers UNDER caption/pill (z-order bug we shipped once — don't repeat).
- Buttons: radius 10, padding 11×10, 12.5 / 600 / tracking 0.4
- Chips: radius 7, padding 3×8; only vibe chips take gold ink + capitalize
- Difficulty: five 5pt dots, filled with `accent`

## States

- `open` → good green, `✓ Booking Available`
- `countdown` → tabular timer; `soon` amber under 1h (card border warms too);
  flips green at ≤60s in the assist
- `booked` → "Booked solid", muted
- `unknown` → platform-honest copy (see app-spec copy rules)
