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

- **Curve freshness is NOT the FR fix — tested and falsified.** The obvious
  hypothesis for FR ("the 2025 curve is stale, refit it on recent data") got
  its own variant: `isotonic_rolling_forecast` refits the curve every day on
  the trailing 60 *French* days. Result: 71.5%, marginally *below* the static
  curve's 72.0%. So FR's problem is not regime staleness — in a
  nuclear-dominated market, residual load is simply a weak predictor of the
  hourly price *ordering* (dispatchable nuclear, exports, hydro absorb it).
  The FR fix has to be different *features*, not a fresher curve. The useful
  positive from the same run: in DE the 60-day trailing curve matches the
  full-prior-year one (91.6% vs 91.7%) — **two months of history are enough**,
  which matters when sweeping 35 atlas zones.

So a *real* AI layer for this repo is not a bigger network — it is better
inputs, and the ex-ante result shows the pipeline for them now exists
end-to-end. What's left on top: features that carry price information in
non-solar regimes (nuclear availability, interconnector flows, fuel/CO₂
prices), and probabilistic output (quantiles instead of a point forecast) so
the bidder can trade expected revenue against risk — something no point
forecast can express. Anything fancier has to first beat these baselines on
the same two zones, out of sample.

## Benchmark: a time-series foundation model, measured (2026-07)

The "features beat model class" claim deserved a stress test against the
strongest price-history-only model available: **Chronos-Bolt-small** (Amazon's
pretrained time-series foundation model, ~48M parameters, zero-shot — no
training on our data, runs locally). Same harness, same days, same 672 h of
price history the learned-linear model gets (`experiments/chronos_capture.py`):

| variant | information | DE-LU | FR |
|---|---|---|---|
| rolling day-ahead | today's real prices | 96.8% | 94.9% |
| isotonic ex-ante | TSO fundamentals forecasts | **91.7%** | 72.0% |
| **chronos-bolt zero-shot** | price history only | **90.7%** | **85.2%** |
| learned linear | price history only | 86.2% | 79.3% |
| persistence | yesterday's prices | 84.2% | 78.8% |

Two lessons, one per zone:

- **DE-LU**: model capacity closes most — not all — of the feature gap.
  Chronos crushes the 3-parameter regression on identical information
  (+4.5 pp) and lands within 1 pp of the fundamentals model. Features still
  win, but the margin thinned from 5.5 pp to 1.0 pp.
- **FR**: the foundation model is the **most robust** strategy — best
  operable capture (85.2%, +6.4 pp over persistence) precisely where
  fundamentals collapse, because it assumes nothing about *why* prices move.

Updated verdict: fundamentals features and model capacity are complements,
not rivals — the obvious frontier is feeding the fundamentals (RL forecast)
to a capable model as a covariate. Chronos also outputs quantiles natively,
which is the on-ramp to the probabilistic/risk-aware roadmap item.

## The complement hypothesis, tested: Chronos-2 + TSO covariates (2026-07)

The frontier above was then measured, pre-registered before the run
(`experiments/PROTOCOL-chronos2.md`): **Chronos-2** (120M, zero-shot,
native known-future covariates) fed the same ex-ante TSO forecasts the
isotonic model uses, three arms per zone, all scored by
`bess_arbitrage.score` on identical hours:

| variant | information | DE-LU | FR |
|---|---|---|---|
| rolling day-ahead | today's real prices | 96.7% | 94.9% |
| **chronos-2 + residual load** | price history + TSO forecasts | **94.2%** | **87.6%** |
| chronos-2 + 4 components | price history + TSO forecasts | 94.1% | 87.1% |
| chronos-2 price-only | price history only | 91.4% | 84.1% |
| chronos-bolt zero-shot | price history only | 90.7% | 85.2% |
| isotonic ex-ante | TSO fundamentals forecasts | 91.7% | 72.0% |
| persistence | yesterday's prices | 84.6% | 79.0% |

The complement hypothesis is confirmed, and it is the largest single step
this repo has measured:

- **Covariates are worth ~4x scale.** Going Bolt→Chronos-2 on price history
  buys +0.7 pp in DE and *loses* 1.1 pp in FR; adding the residual-load
  forecast buys +2.8 pp (DE) and +3.5 pp (FR). Information beats parameters.
- **New best operable strategy in both zones**: 94.2% DE (2.5 pp below the
  perfect-information ceiling) and 87.6% FR — where every fundamentals-only
  model collapses (isotonic: 72.0%).
- **Aggregation is free**: the 4 disaggregated TSO series never beat the
  single residual-load covariate. The merit order responds to one number,
  and giving the model the parts adds noise, not signal.
- The rank-corr law holds: DE rank-corr 0.89 → 0.96 tracks the capture jump,
  RMSE nearly halves (27.6 → 18.2 EUR/MWh).

## The specialist, judged: PriceFM (2026-07)

Second external candidate through the judge, pre-registered
(`experiments/PROTOCOL-pricefm.md`): **PriceFM** (arXiv 2508.04875), a
Mixture-of-Experts + graph model built *specifically* for European day-ahead
prices, fed the TSO load/solar/wind forecasts it was trained on — the same
information class as Chronos-2 `+components`. Calibration first: the
published checkpoint reproduces the authors' fold-3 metrics to the third
decimal, and the input pipeline was gated against their own dataset on the
December 2025 overlap (r = 1.0000 on all 8 series). Zero-shot on H1 2026:

| variant | DE-LU | FR |
|---|---|---|
| chronos-2 + residual load | **94.2%** | **87.6%** |
| chronos-2 + 4 components | 94.1% | 87.1% |
| isotonic ex-ante | 91.7% | 72.0% |
| **pricefm (specialist, cov.)** | **90.4%** | **83.1%** |
| chronos-bolt price-only | 90.7% | 85.2% |
| persistence (same hours) | 84.1% | 78.8% |

The pre-registered duel — specialist vs generalist at the same information
class — goes to the generalist by 3.7–4.0 pp. Two readings:

- **Scale and breadth beat domain architecture.** Chronos-2's 120M
  parameters pretrained on everything outperform a purpose-built
  price model with graph priors — even on the market it was designed for.
  In FR, PriceFM (83.1%) trails even price-only Chronos-Bolt (85.2%).
- **RMSE ranks models wrong, again.** PriceFM's DE RMSE (21.2) beats
  Bolt's (27.6-class) and sits near Chronos-2's, but its capture is
  3.8 pp behind: the judge pays for hour *ranking* (rank-corr 0.93 vs
  0.96), not average error. A dispatch-blind leaderboard would have
  called this duel wrong.

## Train on what you'll be fed: the alignment experiment (2026-07)

The isotonic curve was trained on *realized* residual load but evaluated on
the *TSO forecast* — a textbook train/test distribution mismatch. The
pre-registered fix (`experiments/PROTOCOL-iso-train-on-forecast.md`):
train on the historical forecast series instead. Measured verdict, H1 2026:
worth **≈ 0 pp in DE-LU** (falsified: TSO forecasts are accurate there, so
the distributions were already aligned), **≈ +1 pp in FR** (still 6+ pp
below persistence — weak feature, not misalignment), and **+8 pp in NL** —
where the realized series is broken at the source, training on forecasts
is the difference between a garbage curve (69.9%) and a plausible one
(77.9%, still short of persistence's 82.9%). The law: alignment pays in
proportion to how corrupted the realized data are. Side-finding: a full
prior-year training window beats the CLI's half-year convention in DE by
+1.1 pp (92.8% vs 91.7%) — window length was quietly load-bearing.

## Saturation: why the next point of accuracy buys less (2026-07)

Line up everything this repo has measured on the same window (DE-LU H1 2026)
and the shape of the curve is the finding:

| step | capture | marginal gain | RMSE | rank-corr |
|---|---|---|---|---|
| persistence (free) | 84.6% | — | 39.0 | 0.78 |
| chronos-2 price-only | 91.4% | +6.8 pp | 27.6 | 0.89 |
| chronos-2 + RL covariate | 94.2% | +2.8 pp | 18.2 | 0.96 |
| rolling (perfect info) | 96.7% | +2.5 pp | 0.0 | 1.00 |

The first step is free and captures ~85% of everything. A frontier
foundation model buys 7 more points. The best ex-ante information buys 3.
And the entire remaining budget — infinitely better forecasting — is worth
2.5 points. **Every euro of forecast improvement costs more than the last.**

Three independent 2026 results say this is structural, not a quirk of ours:

- **Falezza (ETH, arXiv 2604.12082)** finds a *τ-sufficiency threshold* on
  German markets: forecasts with Kendall rank correlation ≈ 0.85–0.95
  already capture 97–100% of perfect-foresight revenue, and halving MAE
  from an already-good level buys ~0.5 pp of decision quality. This is an
  external replication of the rank-corr law we measured on the 10-zone
  sensitivity screen (intraday Spearman predicts the iso−pers capture
  delta) — and of why we report rank-corr on every scorecard.
- **Maciejowska, Lipiecki & Uniejewski (arXiv 2511.13616)**: on German
  data 2020–24, the statistically most accurate model (NARX, best
  RMSE/MAE) is *not* the most profitable (LEAR earns more). Accuracy
  leaderboards rank models wrong — our PriceFM result reproduced exactly
  this inversion (better RMSE than Bolt, fewer euros).
- **Hirsch & Ziel (arXiv 2604.19580)** give the mechanism: the battery
  optimization *compresses* distributional information — materially
  different forecasts can produce identical optimal bids. Past a quality
  threshold, the LP literally cannot see the improvement.

Consequences for this repo, stated as policy: (1) the scoreboard is euros,
never RMSE — a statistical leaderboard would have called our
specialist-vs-generalist duel backwards; (2) **rank-corr is the primary
statistical diagnostic** — it is the accuracy dimension the LP can still
see; (3) marginal forecast work should target hour *ranking* (peak timing,
regime days like the May 1st holiday miss), not average error — that is
where euros still live between 94.2% and 96.7%.

## The distribution, judged: quantile dispatch buys nothing (2026-07)

The last open forecast question — does the predictive *distribution* pay,
beyond its median? — was pre-registered
(`experiments/PROTOCOL-quantile-dispatch.md`) and measured with Chronos-2
`+RL` quantiles on H1 2026: dispatch on the integrated mean (asymmetry) and
on CVaR scenario-LPs (risk aversion) vs the median control. Verdict: **every
arm within 0.8 pp, and the risk-averse arms make the worst days *worse***.
The structural reason is worth stating: a day-ahead-only battery can always
do nearly nothing, so its worst settled day is already ≈ 0 (DE min +18 EUR,
FR min −7 EUR over 174 days) — there is no downside to insure, and paying
expected euros for "safety" buys negative value. This is Hirsch & Ziel's
information-compression measured live, and it closes the probabilistic
question *at this layer*: the quantiles' real leverage is upstream, in
cross-market allocation (DA vs FCR/aFRR), where uncertainty actually binds
— the right home for the next probabilistic experiment.

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
| forecasting | yes — the only slot with measurable € value | 10–16 pp of ceiling at stake; features *through* a capable model beat either alone (94.2% DE / 87.6% FR) |
| narration | later, maybe | cosmetic value, credibility risk |
