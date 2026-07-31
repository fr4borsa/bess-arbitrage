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

Run 2026-07-31 (pre-registration commit `bc9118f`), evaluation stress
always the TSO day-ahead forecast:

| zone | persistence | static/realized | static/forecast | 60d/realized | 60d/forecast |
|---|---|---|---|---|---|
| DE-LU | 84.2% | 92.8% | 92.4% | 91.6% | 91.8% |
| FR | 78.8% | 70.7% | 71.3% | 71.5% | 72.6% |
| NL | 82.9% | 69.9% | 77.9% | 68.6% | 76.8% |

- **H1 (DE): falsified.** Static −0.4 pp, 60d +0.2 pp — noise. Where the
  TSO forecasts are accurate, the two training distributions are already
  aligned and there is no mismatch to remove.
- **H2 (FR): confirmed.** Changes of +0.6/+1.1 pp, still 6+ pp below
  persistence — residual load stays a weak feature in the nuclear regime;
  training alignment does not rescue it.
- **H3 (NL): falsified on the pre-registered criterion, diagnosis
  confirmed.** Forecast-training repairs **+8.0/+8.2 pp** over the
  broken-realized curve — the largest single training fix measured in this
  repo, confirming the realized series is broken at the source — but the
  result (77.9%) still does not beat persistence (82.9%), so NL has no
  publishable fundamentals baseline yet.
- **Cross-finding (the real lesson):** the value of training on forecasts
  scales with how corrupted the realized series is — DE ≈ 0, FR ≈ +1,
  NL ≈ +8. Alignment is not a free lunch; it is insurance against bad
  realized data.
- **Side-finding:** the static DE curve fit on the FULL year 2025 scores
  92.8% vs the published 91.7% (CLI trains on H1-2025 only, the
  same-window-previous-year convention): +1.1 pp from training-window
  length alone, and above the 60d adaptive (91.6%). Candidate CLI change,
  left to the roadmap — it would shift published table numbers and
  deserves its own diff.
