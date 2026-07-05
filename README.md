# bess-arbitrage

[![ci](https://github.com/fr4borsa/bess-arbitrage/actions/workflows/ci.yml/badge.svg)](https://github.com/fr4borsa/bess-arbitrage/actions/workflows/ci.yml)

Perfect-foresight battery-storage (BESS) arbitrage revenue for European day-ahead
power markets. Given real spot prices, it computes the **revenue ceiling** an
optimally-dispatched battery could have earned — the upper bound any forecast-based
strategy is measured against.

Data: [energy-charts.info](https://energy-charts.info) (Fraunhofer ISE, no API key).
Optimizer: linear program solved with [HiGHS](https://highs.dev).

## Quick start

```bash
uv sync
uv run python -m bess_arbitrage --bzn DE-LU --start 2025-01-01 --end 2025-12-31
```

```
DE-LU  2025-01-01..2025-12-31   (8760 h)
  price: mean 89.3  p5 -0.1  p95 162.4 EUR/MWh
  battery: 1.0 MW / 2.0 h (2.0 MWh), RTE 85%, cap 1.5 cyc/d
  CEILING revenue: 84,901 EUR/MW/year  (total 84,901 EUR)
  capex 250,000 EUR -> simple payback 2.9 y
```

Past date windows are cached as raw JSON in `.cache/energy-charts/`; `rm -rf .cache` clears it.

## Model

A 1-hour-resolution LP over the price series. Decision variables per hour: charge,
discharge, state-of-charge. Maximizes `Σ price·(discharge − charge)` subject to
SOC dynamics, power/energy limits, round-trip efficiency (split √RTE per leg), and
an optional cycles-per-day throughput cap.

Perfect foresight (prices known in advance) makes the result an **upper bound**:
real dispatch with day-ahead forecasts earns less. This is the right benchmark for
"how much value is on the table" and for scoring an optimizer's performance — which
is exactly what BESS revenue/optimisation analysis is about.

Flags: `--power` (MW) `--duration` (h) `--rte` `--capex` (EUR/kWh) `--cycles` (/day,
`0` = unlimited) `--capture` `--plot`. Capex defaults to the Ember $125/kWh all-in benchmark.

## Capture ratio (`--capture`)

How much of the ceiling a realistic dispatch keeps. Two variants, both reusing the
same LP day by day (SOC carried across midnight, cycles cap pro-rata per day):

- **rolling day-ahead** — LP on each day's own (known) prices, the day-ahead auction
  view. Isolates the pure horizon effect: no cross-day positioning.
- **persistence forecast** — LP on *yesterday's* prices used as today's forecast,
  schedule settled at today's *real* prices. Standard industry baseline.

Both dispatches are feasible for the full-period LP, so revenue ≤ ceiling by
construction. Real example (DE-LU, H1 2026, default 1 MW / 2 h battery):

```
DE-LU  2026-01-01..2026-06-30   (4343 h)
  CEILING revenue: 96,580 EUR/MW/year  (total 47,882 EUR)
  capture vs ceiling:
    rolling day-ahead   : 46,334 EUR -> 96.8%
    persistence forecast: 40,268 EUR -> 84.2%  (ceiling 47,832 EUR on same 4319 h, day 1 skipped)
```

Reading: the daily horizon alone costs ~3%; a naive persistence forecast still
captures ~84% of perfect foresight — the gap a real price forecast has to close.

## UI (Streamlit)

```bash
uv run streamlit run app.py
```

Four insight-first tabs: **Today** (yesterday's DE stack, atlas headlines, the
information ladder), **Day replay** (any settled day: price, optimal dispatch,
committed capacity, SoC), **Europe map** (click a bidding zone to place a
battery and get ceiling, capture and payback; optional per-zone capture sweep)
and **Trends** (monthly evening-spread trend per zone).

## Atlas — every zone at once

```bash
uv run python -m bess_arbitrage.atlas --start 2026-01-01 --end 2026-06-30
```

Runs the same LP engine across ~35 EU bidding zones and ranks them: ceiling
€/MW/year, payback, rolling day-ahead capture, persistence capture. Flags:
`--zones DE-LU FR CH` (subset), `--no-capture` (ceiling only, much faster),
`--csv atlas.csv` (export).

```
atlas 2026-06-01..2026-06-30 — 1 MW / 2h, RTE 85%, 1.5 cyc/d
 zona  ceiling_eur_mw_y  payback_y  price_mean  hours  capture_rolling  capture_persistence
DE-LU          135667.0        1.8       109.5    720             99.0                 89.5
   FR           88160.0        2.8        66.1    720             96.6                 83.8
   CH           76743.0        3.3       102.1    720             99.2                 87.2
```

## Multi-market stack — FCR / aFRR capacity (DE)

```bash
uv run python -m bess_arbitrage.bench --start 2026-06-01 --end 2026-06-30
```

Co-optimizes day-ahead dispatch with FCR and aFRR **capacity** commitments —
4h blocks, German auctions from
[regelleistung.net](https://www.regelleistung.net/apps/datacenter/tenders/)
(public API, no key). The LP reserves power headroom in the committed direction
plus SOC headroom to actually deliver: FCR 15 min both ways, aFRR 1 h in the
product's direction (both are `optimize()` kwargs).

```
bench DE 2026-06-01..2026-06-30 — 1 MW / 2h, RTE 85%, 1.5 cyc/d, 720 h
  DA-only ceiling :    135,667 EUR/MW/y
  stacked ceiling :    313,303 EUR/MW/y  (uplift +130.9%)
  split (window)  : {'da_eur': 4281, 'fcr_eur': 2860, 'afrr_pos_eur': 7485, 'afrr_neg_eur': 11126} EUR
```

Methodology — an honest floor with stated limits: capacity revenue only (no
aFRR activation energy, which adds revenue in reality); FCR at the German
pay-as-cleared clearing price; aFRR at the **mean** accepted bid (the market is
pay-as-bid — conservative for a 1 MW price-taker); perfect foresight on all
prices, consistent with the ceiling framing everywhere else in this repo.

`--sequential` drops the hindsight and simulates the real gate sequence:
plan each day with the LP run on *yesterday's* prices, bid aFRR capacity at
yesterday's mean (pay-as-bid: awarded only if the bid clears today's marginal
accepted price), take FCR as a price-taker at the clearing, then dispatch the
real day with the awarded commitments as fixed constraints, SOC chained.

```
sequential DE 2026-06-01..2026-06-30 — 696 h settled (day 1 skipped)
  stacked ceiling :     24,879 EUR
  sequential ops  :     17,670 EUR  -> stack capture 71.0%
  split           : {'da': 5512, 'fcr': 4293, 'afrr': 7865} EUR
```

That 71% is the stack's analogue of the capture ratio: the cost of bidding
with yesterday's information in a pay-as-bid market. Even operated this
naively, the stack beats the *perfect-foresight* DA-only ceiling for the same
month by a wide margin.

## Checks

```bash
uv run python -m bess_arbitrage.model    # offline LP self-check (arbitrage + stack co-optimization)
uv run python -m bess_arbitrage.capture  # offline capture-ratio self-check (synthetic days)
uv run python -m bess_arbitrage.prices   # live API smoke test (last 7 days DE-LU)
uv run python -m bess_arbitrage.atlas --demo  # offline atlas self-check (synthetic zones)
uv run python -m bess_arbitrage.bench --demo  # offline stack-benchmark self-check
uv run python -m bess_arbitrage.balancing     # live API smoke test (regelleistung.net, one day)
uv run pytest -q                              # LP invariants on synthetic data (offline)
uv run python -m bess_arbitrage.report --month 2026-06  # regenerate a monthly report
```

CI runs the offline checks and the invariant tests on every push.

## Roadmap (building in public)

1. ~~**Capture-ratio atlas**~~ — shipped 2026-07: the LP engine across ~35 EU
   bidding zones, ceiling / capture rankings on the map, CLI + CSV export.
2. ~~**Multi-market stack**~~ — shipped 2026-07: FCR + aFRR capacity co-optimized
   with day-ahead arbitrage (capacity-only floor, documented methodology), a
   monthly DE benchmark CLI, and a gate-by-gate sequential simulation (stack
   capture ratio). ~~Auto-published monthly report~~ — shipped 2026-07: a
   GitHub Action writes `reports/YYYY-MM.md` on the 2nd of each month
   (bench + sequential + atlas headlines + spread trend).
   ~~aFRR activation energy~~ — shipped 2026-07 (v1): the ENERGY-market merit
   order from regelleistung.net (bid-level, sign-normalized to
   price-received-by-provider) prices a hypothetical bid at 5% of the MOL,
   settled at the marginal price at a parametric activation depth
   (5/15/30% scenarios — depth needs activated-volume data to become a fact).
   `bench --sequential --activation` and a report section carry the band.
3. **Battery realism** — degradation-aware dispatch; grid-fee and
   connection-constraint impacts on the business case.

Work in progress — numbers and interfaces evolve. Issues and feedback welcome.
