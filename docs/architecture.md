# Architecture

What runs where, why each piece was chosen, and where the numbers come from.
Companion doc: [ai-layer.md](ai-layer.md) (where machine learning helps this
project and where it doesn't, with measured numbers).

## The one-paragraph version

Public market data comes in over two HTTP APIs (no keys), gets cached on disk
as raw responses, and feeds a linear program that computes what a battery
could have earned. Everything else — capture ratios, the multi-zone atlas,
the FCR/aFRR stack, the Streamlit UI, the monthly report — is a different
way of framing or re-running that same LP. One engine, many views.

```
energy-charts.info ──┐                        ┌─> __main__.py   CLI (one zone)
(spot, residual load)│   .cache/ (raw JSON)   ├─> atlas.py      ~35 zones ranked
                     ├─> prices.py ──┐        ├─> bench.py      DA + FCR/aFRR stack
regelleistung.net ───┘               ├─> model.py (LP, HiGHS)   ├─> app.py  Streamlit UI
(FCR/aFRR auctions) ──> balancing.py ┘        │                 └─> report.py monthly md
                        activation.py ────────┴─> capture.py    4 forecast variants
```

## Module map

| Module | Responsibility | Depends on |
|---|---|---|
| `model.py` | The LP: arbitrage + capacity co-optimization + degradation cost; investment view (payback, NPV, IRR) | pulp/HiGHS |
| `prices.py` | Day-ahead prices + residual load from energy-charts.info, disk cache | requests |
| `balancing.py` | FCR/aFRR capacity auction results from regelleistung.net | requests |
| `activation.py` | aFRR ENERGY merit-order list; activation margin at parametric depth | balancing |
| `capture.py` | Capture-ratio variants: rolling, persistence, learned linear, isotonic | model |
| `bench.py` | DA-only vs stacked ceiling; `--sequential` gate-by-gate simulation | model, balancing |
| `atlas.py` | The same LP swept across ~35 bidding zones, ranked | model, capture |
| `insights.py` | Headline generators shared by the UI and the report | atlas, bench |
| `report.py` | Monthly markdown report (`reports/YYYY-MM.md`) | insights |
| `app.py` / `app_map.py` | Streamlit control-room UI / Europe map | all of the above |

Dependency direction is strictly downward: `model.py` imports nothing from
this package, the apps import everything. No circular imports, no plugin
system, no config files — parameters are function arguments with defaults.

## Stack choices, and why

- **Python + pandas** — the whole domain is "hourly time series in, hourly
  time series out". Everything indexes by UTC timestamps.
- **PuLP + HiGHS** (`highspy`) — the dispatch problem is a *linear program*
  (continuous charge/discharge/SOC, linear objective and constraints), so an
  LP solver gives the *provably optimal* answer in milliseconds. HiGHS runs
  in-process; PuLP's bundled CBC binary is x86-only and breaks on Apple
  Silicon. This choice is load-bearing: because the optimum is exact, every
  "capture ratio" in the repo has a hard denominator. A heuristic dispatcher
  would make every number soft.
- **uv** — lockfile (`uv.lock`) pins the exact dependency set; `uv sync` on
  any machine (or in CI) reproduces the same environment. The `.python-version`
  file pins the interpreter.
- **energy-charts.info / regelleistung.net** — both public, no API keys, so
  anyone can clone and reproduce every number in the README. That constraint
  (reproducibility without credentials) shaped the data layer more than any
  technical preference.
- **Disk cache of raw responses** (`.cache/`) — raw JSON/parquet per
  request-window, so re-runs are offline and fast, and a model change never
  requires re-downloading. Cache key = endpoint + parameters; `rm -rf .cache`
  is the only invalidation. Deliberately not a database.
- **Streamlit + Altair + Folium** — the UI is a viewer over library
  functions; it holds no logic of its own. If Streamlit disappeared tomorrow,
  every number would still come out of the CLI.

## Testing: invariants over golden values

Real prices change daily, so asserting exact outputs would be brittle. The
test suite (`tests/`) asserts *properties that must hold for any price
series*: dispatch stays within power/energy bounds, revenue never exceeds the
perfect-foresight ceiling, co-optimization never earns less than DA-only,
more allowed cycles never earn less, pricing degradation never raises net
revenue. If one of these breaks, the engine is wrong — not the market.

Each module also carries an offline `_demo()` self-check on synthetic data
(`python -m bess_arbitrage.model` etc.) with hand-computable expected values;
CI runs all of them. Live-API smoke tests (`prices`, `balancing`) exist but
are *not* in CI — CI must not depend on third-party uptime.

## CI/CD (GitHub Actions)

- **`ci.yml`** — on every push/PR: `ruff check` (lint), `pytest`
  (warnings-as-errors: a new dependency deprecation fails the build instead
  of scrolling by), and the offline demo suite. uv's cache is keyed on
  `uv.lock`, so unchanged dependencies restore in seconds. A `concurrency`
  group cancels superseded runs on the same branch.
- **`monthly-report.yml`** — a scheduled workflow (2nd of each month, when
  the previous month is fully settled) that regenerates `reports/YYYY-MM.md`
  and commits it back with the built-in `GITHUB_TOKEN`. The repo publishes
  its own analysis without anyone at the keyboard.
- **`dependabot.yml`** — weekly PRs for dependency and Action updates; each
  PR runs the full CI, so an update that breaks an invariant is caught at the
  PR, not on `main`.

## Deliberate non-features

- No database, no Docker, no web backend — a lockfile plus disk cache covers
  reproducibility at this scale.
- No abstract solver interface, no strategy registry — one solver, one
  `optimize()`, variants are plain functions.
- No 15-minute resolution yet: the LP is hourly because the source data is
  hourly. When MTU-15 data lands in the source APIs the LP constraint
  structure is unchanged (`pmax` scales by step length).
