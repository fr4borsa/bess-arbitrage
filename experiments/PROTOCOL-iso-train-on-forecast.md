# Pre-registered protocol — isotonic trained on forecasts

**Status: pre-registered**, committed before any run. All results reported.

## Question (stage-3 in its purest form)

The isotonic supply curve is today fit on **realized** residual load, then
evaluated ex-ante on the **TSO forecast** residual load — train and test see
different distributions of the same feature. Systematic forecast biases
(e.g. under-forecast solar ramps) shift the curve read-off point. Training
the curve directly on the historical *forecast* series aligns the two: the
model learns price = f(what the TSO says), which is exactly what it will be
fed. No package change — `isotonic_forecast` / `isotonic_rolling_forecast`
already accept any training stress series.

## Fixed design

- **Window**: H1 2026 (2026-01-01→2026-06-30), same judge-comparable setup
  as the existing capture table (day-1 handling per function, SOC chained).
- **Zones**: DE-LU (healthy data, baseline 91.7%), FR (fundamentals-broken
  regime, 72.0%), NL (realized series broken at the source — mean solar
  61 MW — so the realized-trained curve was never publishable).
- **Variants per zone** (2×2, all reported):
  - static curve: fit on full year 2025 — (realized RL, price) vs
    (forecast RL, price);
  - 60d adaptive curve: trailing 60 days — realized vs forecast history.
  Evaluation stress is ALWAYS the TSO day-ahead forecast (ex-ante).
- Battery, LP, ceiling: repo defaults, unchanged.

## Hypotheses

- **H1 (DE)**: forecast-trained ≥ realized-trained (91.7% static /
  91.6% 60d). Alignment can only remove a distribution mismatch.
- **H2 (FR)**: no material change (±1 pp) — residual load is a weak
  feature in the nuclear regime regardless of training alignment. A large
  jump would falsify the "weak feature" reading of the FR failure.
- **H3 (NL)**: the forecast-trained curve yields the first *valid*
  fundamentals baseline for NL (realized inputs are broken at the source);
  success criterion: beats persistence on the same hours.

Primary metric: capture. Secondary: intraday rank-corr of the price
prediction. Results below, filled by the run, not edited afterwards.

## Results

*(empty at pre-registration)*
