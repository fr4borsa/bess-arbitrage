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

*(empty at pre-registration — filled by the run, not edited afterwards)*
