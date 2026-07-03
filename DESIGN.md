# DESIGN.md — bess-arbitrage · "Control room" direction

Subject: BESS arbitrage analysis tool for EU day-ahead markets.
Audience: Francesco (analysis), then public screenshots (LinkedIn).
Page job: make tangible how much a battery is worth — and how much of that
value a real strategy takes home (capture ratio).

Vibe: overnight grid monitoring — SCADA, instrument panels, mono numbers.
Quiet everywhere, boldness spent on a single spot (signature).

## Tokens

| Role | Hex | Use |
|---|---|---|
| bg | `#12161F` | app background (carbon-blue, NEVER pure black) |
| surface | `#1B2230` | panels, metric cards, instrument |
| border | `#2A3347` | panel borders, 1px |
| track | `#232B3B` | gauge tracks, empty rows |
| text | `#D8DEE9` | primary text |
| muted | `#8A94A6` | labels, eyebrow, axes |
| amber | `#F2A93B` | **the signal**: prices, sales, real revenue, accent |
| cyan | `#5BC8D8` | instrumental: SOC, flow arrows |
| green | `#59B26B` | buy (charge at low price) |
| red | `#E06456` | errors/negative only |

## Type

- Display + body: **IBM Plex Sans** (400/600)
- Numbers and data: **IBM Plex Mono** (400/600), always — every figure on
  screen is mono
- Eyebrow: Plex Mono, uppercase, letter-spacing .14em, muted

## Spacing / shape

- Radius 6px, 1px `border` borders, no shadows
- Panels: padding 12–22px; a single surface hierarchy (surface on bg)

## Signature (one only)

**The capture instrument**: a panel with ceiling → real revenue in large
amber mono + a flat horizontal gauge marking the capture ratio. It's the
only large, warm element on the page; everything else stays quiet.

## Banned

Inter, blue/indigo Tailwind default, purple gradients, cream+terracotta
(#F4F1EA/#D97757), pure black + acid green, broadsheet hairline, centered
hero + 3 cards, soft shadows, emoji in numbers.
