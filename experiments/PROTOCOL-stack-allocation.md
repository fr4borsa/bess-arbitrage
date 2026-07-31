# Pre-registered protocol — forecast & probabilistic bidding in the stack

**Status: pre-registered**, committed before any run. All cells reported.

## Question

The DA-only layer is mapped: forecasts are saturated, the predictive
distribution buys nothing there (`PROTOCOL-quantile-dispatch.md`). The
remaining lever is **allocation**: the gate-by-gate stack simulation
(`bench.run_sequential`, DE) plans with pure persistence and bids aFRR
blindly at yesterday's mean. Two independent upgrades, a 2×2 design (D5):

- **plan axis**: plan day D's co-optimization on (a) yesterday's prices
  [persistence, current] vs (b) the Chronos-2 `+RL` median forecast for
  day D — taken from the committed `chronos2-RL-DE-LU-2026H1.csv`, no new
  model run, fully reproducible.
- **bid axis**: aFRR capacity bid per product×block at (a) yesterday's
  MEAN accepted price [blind, current] vs (b) the EV-optimal bid: given
  the empirical distribution of the *marginal* accepted price (max) over
  the trailing **28 days** for that product×block, choose the candidate
  bid (the empirical marginals themselves) maximizing
  `bid × P̂(award | bid)` with `P̂ = fraction of trailing marginals ≥ bid`.
  This is the genuinely non-linear decision the LP cannot compress.

## Fixed design

- **Market**: DE (only zone with capacity-price data wired). **Window:
  Q2 2026** (2026-04-01→2026-06-30), one quarter — sized to the
  regelleistung API load; extension to H1 is future work.
- Award settle rule unchanged: awarded iff bid ≤ day-D marginal (+1e-9),
  paid the bid (pay-as-bid). FCR: price-taker, unchanged. Lost awards
  free capacity for DA re-dispatch, unchanged.
- **Declared simplification**: the EV bid maximizes expected *capacity*
  revenue only — the DA opportunity value of freed capacity is not in the
  bid objective (it IS honestly settled in the simulation either way).
- Cell (persistence, blind) must reproduce the current `run_sequential`
  behavior — internal validation of the refactor (hooks default to
  current behavior; existing tests must stay green).
- **Metrics (frozen)**: stack capture (vs the stacked ceiling, as today),
  revenue split (da / fcr / afrr), aFRR award rate, total EUR.

## Hypotheses

- **H1 (forecast in the stack)**: forecast-plan > persistence-plan on
  stack capture, both bid rules — but by LESS than the pure-DA delta
  (94.2 vs 84.2 ≈ +10 pp), because capacity revenue dilutes the DA share.
- **H2 (probabilistic bidding)**: EV-bid > blind-bid, both plans. This is
  the experiment's core: uncertainty pays where the structure is
  non-linear (an auction), after it failed to pay where it is linear
  (the LP).
- **H3 (interaction)**: effects roughly additive; super-additivity would
  be a finding worth its own follow-up.

## Results

*(empty at pre-registration)*
