# bess-arbitrage

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

Two views: a single market in detail (price series + optimal dispatch), and a
Europe map — click a bidding zone to place a battery there and get its revenue
ceiling, capture ratio, and payback.

## Checks

```bash
uv run python -m bess_arbitrage.model    # offline LP self-check
uv run python -m bess_arbitrage.capture  # offline capture-ratio self-check (synthetic days)
uv run python -m bess_arbitrage.prices   # live API smoke test (last 7 days DE-LU)
```

## Roadmap (building in public)

1. **Capture-ratio atlas** — the same LP engine across all EU bidding zones,
   with spread / ceiling / capture rankings on the map.
2. **Multi-market stack** — FCR and aFRR capacity alongside day-ahead arbitrage,
   toward an open, reproducible monthly BESS revenue benchmark (DE first) with a
   documented methodology.
3. **Battery realism** — degradation-aware dispatch; grid-fee and
   connection-constraint impacts on the business case.

Work in progress — numbers and interfaces evolve. Issues and feedback welcome.
