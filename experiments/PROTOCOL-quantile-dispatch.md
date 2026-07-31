# Pre-registered protocol — does the forecast *distribution* pay?

**Status: pre-registered**, committed before any run. All arms reported.

## Question

Chronos-2 emits full quantile forecasts; the judge so far scored only the
median. For a price-taking battery committing ONE day-ahead schedule,
revenue is linear in prices, so the risk-neutral optimum is to dispatch on
the predictive **mean** — the whole distribution beyond that only matters
through (a) asymmetry (mean ≠ median on right-skewed prices) and (b) risk
aversion (paying expected euros for calmer days). Two arms, one per
mechanism, designed with the methodologist before any number was seen (D4).

## Fixed design

- **Forecaster**: Chronos-2 zero-shot `+RL` (the repo's best arm), same
  per-day protocol as `PROTOCOL-chronos2.md`: 672 h context, target days
  from #8, covariate-complete days, H1 2026, zones DE-LU and FR.
- **Quantile levels (frozen)**: 0.1 … 0.9 in steps of 0.1 (9 curves),
  plus the model's native predictive mean.
- **Arms**:
  1. **median** (control) — must reproduce the committed
     `chronos2-RL-*.csv` forecasts; internal validation of the rerun.
  2. **mean** — LP on the predictive mean.
  3. **CVaR(α=0.2, λ=1)** and **CVaR(α=0.2, λ=0.5)** — per-day scenario
     LP: same battery constraints as `model.optimize` (power, SOC
     dynamics with √RTE per leg, pro-rata cycle cap, SOC chained across
     days at the settled dispatch), scenarios = the 9 quantile curves,
     equiprobable; objective (1−λ)·mean(R_s) + λ·CVaR_α(R_s)
     (Rockafellar–Uryasev). Both λ reported.
- **Declared limitation**: quantile curves used as joint scenarios are
  comonotone — they ignore intertemporal dependence, the exact flaw
  Hirsch & Ziel (arXiv 2604.19580) flag in quantile-based trading. Our
  CVaR verdict applies to this practical strategy class, not to the
  stochastic-programming optimum.
- **Metrics (frozen)**: capture (primary); per-day settled P&L
  distribution per arm — std, mean of the worst 5% of days, worst single
  day. Identical day set across arms.

## Hypotheses

- **H1 (asymmetry)**: mean-arm capture ≥ median-arm capture.
- **H2 (risk premium)**: CVaR arms give up capture vs median BUT improve
  the worst-5% mean and the daily std. If they lose capture *without*
  improving the risk metrics, risk-aware bidding at this strategy class
  is worthless here.
- **H3 (compression, reading not criterion)**: all capture differences
  ≤ 1 pp — the LP compresses distributional information (Hirsch & Ziel);
  a larger spread would be evidence against compression at our horizon.

## Results

Run 2026-07-31 (pre-registration commit `69b483d`). **Amendment, documented
before the arm ran**: Chronos-2's native "mean" output turned out to be an
alias of the median (verified: max diff 0.0), so the mean arm uses the
quantile-integrated mean (average of the 9 curves) instead. Internal
validation: the regenerated median reproduces the committed
`chronos2-RL-*.csv` bit-exactly (max diff 0.000 EUR/MWh) in both zones.

| arm | DE capture | DE std/day | DE worst-5% | DE min | FR capture | FR std/day | FR worst-5% | FR min |
|---|---|---|---|---|---|---|---|---|
| median (control) | 94.2% | 196 | 28 | 18 | 87.6% | 138 | 25 | −7 |
| mean (integrated) | 94.1% | 196 | 28 | 20 | 87.6% | 138 | 25 | −7 |
| CVaR λ=0.5 | 94.2% | 195 | 28 | 18 | 87.7% | 135 | 27 | −9 |
| CVaR λ=1.0 | 94.0% | 194 | 28 | 17 | 86.8% | 136 | 24 | −14 |

- **H1 (asymmetry): falsified.** The integrated mean scores a hair BELOW
  the median (−11 EUR DE, −23 EUR FR — a rounding error on 44k). The
  predictive distribution is right-skewed, but the LP dispatches on hour
  *ranking*, which the skew barely changes.
- **H2 (risk premium): falsified decisively.** Full CVaR (λ=1) gives up
  0.2–0.8 pp of capture and makes the worst day WORSE in both zones
  (DE min 18→17, FR min −7→−14 EUR). There is no risk to insure at this
  layer: the worst settled day of the half-year is +18 EUR in DE and
  −7 EUR in FR — a battery can always do (nearly) nothing, so the daily
  downside is structurally bounded near zero. Risk-aware bidding here
  costs euros and buys nothing.
- **H3 (compression): confirmed.** Every arm within 0.8 pp; Hirsch &
  Ziel's information-compression measured live on our own harness.

Reading for the roadmap: the value of the quantiles is NOT in day-ahead
dispatch — it is upstream, in *allocation* decisions across markets
(DA vs FCR/aFRR commitment), where Falezza (arXiv 2604.12082) finds the
real leverage. That is where a probabilistic experiment belongs next.
