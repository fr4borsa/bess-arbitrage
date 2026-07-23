# Does this project need an AI layer?

Short answer: **dispatch doesn't, forecasting does — and this repo now
measures exactly how much.** Everything below is grounded in numbers you can
reproduce with one command.

## Where AI could plug in

A battery-arbitrage pipeline has three slots where "add AI" gets proposed:

1. **Dispatch** — decide when to charge/discharge, given prices.
2. **Price forecasting** — predict tomorrow's prices, which the dispatcher
   then optimizes against.
3. **Narration** — turn model output into prose (reports, summaries).

## Slot 1: dispatch — no. It's a solved problem.

Given a price series, optimal dispatch under battery constraints is a linear
program. HiGHS solves a month in milliseconds, and the answer is *provably
optimal* — a reinforcement-learning agent can at best tie it, at real cost:
training, non-determinism, and the loss of the hard upper bound every capture
ratio in this repo is measured against. RL becomes discussable only when the
problem stops being an LP (nonlinear degradation inside the horizon,
price-impact of your own bids, joint uncertainty across markets). At 1–10 MW
merchant scale, it isn't.

## Slot 2: forecasting — yes, and here is the measured value

Perfect foresight is the ceiling; every real strategy forecasts. The repo
ships four dispatch variants that differ *only* in what they know about
tomorrow (`--capture`):

| variant | knows | DE-LU H1 2026 | FR H1 2026 |
|---|---|---|---|
| rolling day-ahead | today's real prices (auction view) | **96.8%** | **94.9%** |
| isotonic **ex-ante** | TSO day-ahead load/RES *forecasts* through the curve | **91.7%** | **72.0%** |
| isotonic (realized) | realized residual load through a 2025-fitted merit order | **90.5%** | **73.8%** |
| learned linear | per-hour lag-1/lag-7 regression, 28d window | **86.2%** | **79.3%** |
| persistence | yesterday's prices | **84.2%** | **78.8%** |

Reproduce: `uv run python -m bess_arbitrage --bzn DE-LU --start 2026-01-01
--end 2026-06-30 --capture` (and `--bzn FR`). Capture = revenue / same-hours
perfect-foresight ceiling; 1 MW / 2 h battery throughout.

What these numbers actually say:

- **The whole prize for any forecaster is ~10–16 points of ceiling** (the gap
  from persistence to rolling day-ahead). On a 1 MW / 2 h battery in DE-LU
  that gap was ≈ €6.1k over six months. This bounds what *any* model — linear
  or transformer — can be worth here. Scale it by fleet size before deciding
  how much engineering it deserves.
- **Cheap learning buys little.** The learned-linear model (3 parameters per
  hour, `numpy lstsq`, no new dependency) beats persistence by +2.0 pp in
  DE-LU and +0.5 pp in FR. Autoregression on price history alone barely moves
  capture, because dispatch needs the *shape and timing* of the daily curve,
  and yesterday already encodes most of it.
- **Features beat model class — when the regime matches.** The isotonic
  supply-curve model (fundamentals: residual load through an empirical merit
  order) gains +6–7 pp over persistence in solar-driven DE-LU… and *loses*
  5–7 pp in nuclear-dominated FR, where a curve fitted on 2025 doesn't
  transfer. The lesson is not "fundamentals are good": it's that **input
  features and regime-awareness dominate model sophistication**, and a wrong
  fundamental model underperforms knowing nothing.
- **The ex-ante version is not a discount — in DE it's an upgrade.** Feeding
  the curve TSO *day-ahead forecasts* of load/solar/wind (published before
  the auction, so a genuinely operable strategy) scores 91.7% in DE-LU —
  *above* the 90.5% obtained with the realized residual load. That is not a
  fluke; it's market microstructure: **the auction itself clears on forecast
  fundamentals**, so the TSO forecast is the more coherent predictor of the
  day-ahead price than what the fundamentals later turned out to be. In FR
  the ex-ante variant scores 72.0% — the regime problem, not the forecast,
  is the binding constraint there.

So a *real* AI layer for this repo is not a bigger network — it is better
inputs, and the ex-ante result shows the pipeline for them now exists
end-to-end. What's left on top: fuel and CO₂ prices to condition the supply
curve by regime (the FR fix), and probabilistic output (quantiles instead of
a point forecast) so the bidder can trade expected revenue against risk —
something no point forecast can express. Anything fancier has to first beat
these baselines on the same two zones, out of sample.

## Slot 3: narration — optional, low stakes

The monthly report is generated from the same headline functions the UI uses
(`insights.py`) — deterministic, testable, numerically safe. An LLM pass
could make the prose nicer, at the cost of a non-deterministic step between
data and published numbers (and hallucination risk right where credibility
lives). If added, it should rewrite *around* machine-inserted numbers, never
produce them. Not before slots 1–2 are settled; the value is cosmetic.

## Summary

| slot | verdict | why |
|---|---|---|
| dispatch | no | LP is exactly optimal, milliseconds, hard bound |
| forecasting | yes — the only slot with measurable € value | 10–16 pp of ceiling at stake; features > model class |
| narration | later, maybe | cosmetic value, credibility risk |
