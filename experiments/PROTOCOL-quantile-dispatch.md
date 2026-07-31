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

*(empty at pre-registration)*
