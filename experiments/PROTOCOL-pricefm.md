# Pre-registered protocol — PriceFM zero-shot on the judge

**Status: pre-registered.** Committed BEFORE any H1 2026 run; the commit hash
is the timestamp. All results are reported whatever they turn out to be.
Second external candidate through `bess_arbitrage.score`, after Chronos-2
(`PROTOCOL-chronos2.md`) — the specialist vs the generalist.

## Candidate

**PriceFM** (`runyao-yu/PriceFM`, arXiv 2508.04875): Mixture-of-Experts +
graph-topology model built specifically for European day-ahead electricity
prices, 38 bidding zones, probabilistic (7 quantiles). Pretrained checkpoint
`Model/PhaseI_best.keras` as published (April 2026). Inputs per zone:
price history (lag, 96 rows) + TSO day-ahead load/solar/wind forecasts
(known-future lead, 96 rows) — the same information class as our Chronos-2
`+components` arm, which is therefore the primary comparison.

## Evidence gathered BEFORE this protocol (calibration phase)

1. **Faithful driving**: the published checkpoint, run with the authors' own
   code on their fold-3 test split (2025-09-01→2026-01-01), reproduces their
   published `Result/phase1_pretraining.csv` to the third decimal
   (DE_LU RMSE 24.339 vs 24.339, MAE 14.212 vs 14.212; FR RMSE 18.803 vs
   18.802, MAE 13.895 vs 13.894). We know how to drive the model fairly.
2. **Gate isolation**: in the zero-shot configuration (Phase I,
   `gate = [target]`), strong random perturbation of all 37 non-target zones
   leaves predictions bit-identical (max |Δ| = 0.0). The H1 2026 input
   therefore only needs the target zone's data; other slots are zero-filled.

## Contamination

The PriceFM dataset spans 2022-01-01 → **2026-01-01** (paper, §Rolling
Evaluation: last fold ends 1 Jan 2026). Our window 2026-01-01 → 2026-06-30
is entirely outside it. Same clean-window standard as Chronos-2.

## Fixed design (frozen before any H1 2026 run)

- **Checkpoint**: `PhaseI_best.keras`, zero-shot, no fine-tuning, CPU.
- **Scalers**: RobustScaler per zone, refit with the authors' code on their
  fold-3 training split (2022-01-01→2025-05-01) from `FINAL.csv` — frozen
  as part of "the model", then applied unchanged to H1 2026 inputs.
- **H1 2026 inputs**: quarter-hourly price + TSO day-ahead load/solar/wind
  forecasts for the target zone from energy-charts (ENTSO-E provenance,
  same as the authors' dataset). No hourly resampling on input.
- **Input sanity gate (pre-registered)**: before any H1 run, our
  energy-charts-built inputs are compared against the authors' own
  `FINAL.csv` on the overlap month **December 2025** (DE_LU and FR, all 4
  series). Requirement: Pearson r > 0.99 per series. Failure = stop and
  investigate (it would mean our series are not what the model was trained
  on — e.g. realized vs forecast); the investigation is reported either way.
- **Per-day protocol**: anchors at 00:00 UTC (the authors' convention);
  lag = the 96 quarter-hours before midnight (= previous UTC day, ex-ante:
  those prices cleared in earlier auctions); lead = the target day's 96
  quarter-hour TSO forecasts (published before the auction). Median
  (q = 0.50) as the point forecast, inverse-scaled, then **resampled to
  hourly mean** and scored by `bess_arbitrage.score.compare` — the same
  judge as every candidate. A day enters only if its inputs are complete.
- **Zones**: DE-LU and FR. Window: 2026-01-01 → 2026-06-30.

## Hypotheses (thresholds from measured numbers)

- **H1 (floor)**: PriceFM > persistence on its own settled hours (the
  baselines are re-scored by `compare` on exactly those hours).
- **H2 (the duel, primary)**: PriceFM vs Chronos-2 `+components`
  (94.1% DE-LU / 87.1% FR) — specialist vs generalist at the same
  information class. Settled-hour sets may differ slightly between the two
  runs (different drop rules); deltas under ~0.2 pp are reported as a tie.
- **H3 (DE, vs fundamentals)**: PriceFM > 91.7% (isotonic ex-ante).
- **H4 (statistical cross-check)**: H1 2026 RMSE in the same range as the
  authors' fold-3 test RMSE (DE_LU 24.3, FR 18.8 EUR/MWh) — a drastic
  degradation would suggest an input-pipeline problem, not a model verdict,
  and triggers investigation before publication.

Primary metric: capture ratio. Secondary: intraday rank-corr. Context: RMSE.

## Outputs

Forecast CSVs per zone committed under `experiments/forecasts/`
(re-scoreable via the CLI without TensorFlow). Results table below, filled
by the run and not edited afterwards; analysis in `docs/ai-layer.md`.

## Results

Run 2026-07-31 (pre-registration commit `ac5e893`). Input sanity gate on the
December 2025 overlap: first attempt **failed as designed** (FR-solar
r = 0.980 — energy-charts serves stretches of hourly values on the 15-min
grid where the authors interpolated linearly; FR wind additionally excludes
offshore in their dataset while DE includes it). Inputs rebuilt to match
their preprocessing (per-day hourly-stretch detection → linear
interpolation; wind composition chosen per zone on the overlap month), gate
re-run: **all 8 series r = 1.0000, mean-ratio 1.000**. Then H1 2026:
DE-LU 179 eligible days (4,296 h), FR 177 (4,248 h); baselines re-scored by
the judge on the same hours.

| | capture | rank-corr | RMSE | persistence | rolling |
|---|---|---|---|---|---|
| DE-LU | 90.4% | 0.93 | 21.2 | 84.1% | 96.7% |
| FR | 83.1% | 0.86 | 21.3 | 78.8% | 94.8% |

Hypotheses, as pre-registered:

- **H1 (floor): confirmed.** +6.3 pp (DE) and +4.3 pp (FR) over persistence.
- **H2 (the duel, primary): falsified.** PriceFM loses to Chronos-2
  `+components` at the same information class by 3.7 pp (DE-LU, 90.4 vs
  94.1) and 4.0 pp (FR, 83.1 vs 87.1). The specialist does not beat the
  generalist; in FR it does not even beat price-only Chronos-Bolt (85.2%).
- **H3 (DE, vs fundamentals): falsified.** 90.4% < 91.7% (isotonic
  ex-ante).
- **H4 (statistical cross-check): passed.** H1 2026 RMSE (21.2 / 21.3) is
  in the same range as the authors' fold-3 test RMSE (24.3 / 18.8) — no
  drastic degradation, so the result is a model verdict, not an input
  artifact. Notably PriceFM's DE RMSE (21.2) is *better* than Chronos-2
  +RL's (18.2 is better still) — but its capture is 3.8 pp worse: euros
  follow hour *ranking*, not average error, and PriceFM's rank-corr (0.93)
  trails Chronos-2's (0.96).

Forecast CSVs in `experiments/forecasts/` — re-score with
`uv run python -m bess_arbitrage.score <csv> --bzn <zone>`.
