# Pre-registered protocol — Chronos-2 zero-shot with TSO covariates

**Status: pre-registered.** This file is committed BEFORE the experiment runs;
the commit hash is the timestamp. Whatever the numbers turn out to be, all
arms are reported — in this file's results section, in `docs/ai-layer.md`
and in the README roadmap. No arm is added, dropped or re-tuned after seeing
results.

## Question

Does a time-series foundation model given the *same ex-ante fundamentals the
isotonic baseline uses* close the gap to it (DE) or extend its lead (FR)?
Chronos-Bolt (price-only) measured 90.7% in DE-LU (vs isotonic ex-ante 91.7%)
and 85.2% in FR (best operable strategy there). Chronos-2 natively supports
known-future covariates — the TSO day-ahead forecasts are exactly that.

## Fixed design (frozen before any run)

- **Model**: `amazon/chronos-2` (120M, encoder-only), `chronos-forecasting`
  2.3.1, zero-shot, **no fine-tuning**, CPU, float32, median (q=0.5) as the
  point forecast.
- **Window**: 2026-01-01 .. 2026-06-30. Contamination argument: the Chronos-2
  technical report is dated 2025-10-17 (arXiv 2510.15821), so H1 2026 data
  did not exist when the model was frozen. (The model card states no explicit
  training-data cutoff; the report date is the verifiable bound.)
- **Zones**: DE-LU and FR.
- **Per-day protocol** (identical to `experiments/chronos_capture.py`):
  context = hourly price history up to the target day's midnight, 672 h
  (28 days); forecast the day's hours; settled days from day 8 onward.
  Everything downstream (LP dispatch, settlement at real prices, SOC
  chaining, ceiling on the same hours) is delegated to
  `bess_arbitrage.score.compare` — the same judge any external forecast gets.
- **Arms** (3 per zone, all pre-registered, all reported):
  1. `price-only` — control: target history only.
  2. `+RL` — one known-future covariate: ex-ante residual load
     (`fetch_residual_load_forecast`), the isotonic baseline's feature.
  3. `+components` — four known-future covariates: TSO day-ahead load,
     solar, wind_onshore, wind_offshore forecasts
     (`fetch_dayahead_forecast_components`).
- **Covariate semantics**: past AND future covariate values both come from
  the TSO *day-ahead forecast* series (homogeneous, fully ex-ante — the
  forecast for day D is published before D's auction). Realized series are
  never shown to the model.
- **Missing data**: a target day enters ONLY if all three arms can run it
  (full price context AND complete covariate coverage on the day for both
  covariate sets) — so all arms settle identical hours, per zone. Gaps in the
  covariate *history* are forward-filled (history only conditions the model);
  gaps in the covariate *future* (the target day) drop the day for everyone.
- **Batching**: days grouped by day length (23/24/25 h, DST) and predicted
  with `prediction_length = day length`, so future covariates align exactly.

## Hypotheses (thresholds from measured numbers in the README)

- **H1 (scale)**: Chronos-2 price-only ≥ Chronos-Bolt price-only
  (DE-LU 90.7%, FR 85.2%).
- **H2 (covariates)**: each covariate arm > price-only arm, same zone.
- **H3 (DE, vs fundamentals)**: best covariate arm > 91.7%
  (isotonic ex-ante, the best operable DE strategy).
- **H4 (FR, vs best operable)**: best covariate arm > 85.2% (Bolt).

Primary metric: capture ratio (euros). Secondary: mean intraday Spearman
rank-corr. Context only: RMSE. A hypothesis not met is reported as falsified.

## Outputs

- Forecast CSVs per zone × arm committed under `experiments/forecasts/`, so
  anyone can re-score them with
  `uv run python -m bess_arbitrage.score <csv> --bzn <zone>` without a GPU
  or the model.
- Results table appended below this line after the run; analysis in
  `docs/ai-layer.md`.

## Results

Run 2026-07-31 (pre-registration commit `2dec721`). 174 target days per zone,
0 dropped for covariate gaps, 4,174 h settled — identical across arms and
zones. Baselines re-scored by the judge on the same hours.

| arm | DE-LU capture | rank-corr | RMSE | FR capture | rank-corr | RMSE |
|---|---|---|---|---|---|---|
| price-only (control) | 91.4% | 0.89 | 27.6 | 84.1% | 0.86 | 25.2 |
| **+RL (1 covariate)** | **94.2%** | 0.96 | 18.2 | **87.6%** | 0.90 | 18.8 |
| +components (4 covariates) | 94.1% | 0.95 | 19.6 | 87.1% | 0.90 | 19.6 |
| persistence (same hours) | 84.6% | | | 79.0% | | |
| rolling day-ahead (same hours) | 96.7% | | | 94.9% | | |

Hypotheses, as pre-registered:

- **H1 (scale): DE confirmed, FR falsified.** Price-only 91.4% > Bolt 90.7%
  in DE, but 84.1% < Bolt 85.2% in FR — the 120M model is not uniformly
  better than the 48M one on price history alone.
- **H2 (covariates): confirmed in both zones.** +2.8 pp (DE) and +3.5 pp
  (FR) over the control — worth ~4x what scale bought.
- **H3 (DE, vs fundamentals): confirmed.** 94.2% > 91.7% (isotonic
  ex-ante). New best operable DE strategy, 2.5 pp below the rolling ceiling.
- **H4 (FR, vs best operable): confirmed.** 87.6% > 85.2% (Bolt). New best
  operable FR strategy.
- **Side-finding**: the 4 disaggregated components never beat the aggregate
  residual load (94.1 vs 94.2 DE, 87.1 vs 87.6 FR) — the model extracts
  nothing extra from the split, consistent with residual load being the
  sufficient statistic the merit order actually responds to.

Forecast CSVs in `experiments/forecasts/` — re-score any of them with
`uv run python -m bess_arbitrage.score <csv> --bzn <zone>`.
