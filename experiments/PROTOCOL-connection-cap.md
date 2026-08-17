# Pre-registered protocol — the battery that buys the grid connection (stage 1)

**Status: pre-registered**, committed before any run. All cells reported,
infeasible cells included.

## Question

The thesis (BESS × data center): the bottleneck of a data center is the grid
connection, not the energy. A battery behind the meter that keeps the site
under a connection cap "buys" MW of connection the site would otherwise have
to queue for — and the same dispatch software keeps earning on the market.
Nobody publishes the trade-off reproducibly:

> **How many MW of connection does a given battery buy, and how much
> arbitrage revenue does buying them cost?**

Stage 1 answers it at **perfect foresight** (prices and load known). That is
deliberate: it is the ceiling and the experimental control for stage 2
(dispatch on forecasts), which must not start before this is published.

## Fixed design

- **Engine**: `optimize(prices, bat, load=, cap_mw=)` — the existing LP with
  two extra constraints per hour, `|load + charge − discharge| ≤ cap_mw`
  (import and export capped). Objective unchanged (Σ p·(dis − chg)): a
  discharge that serves the load is an avoided purchase at the same price, so
  cap = ∞ reproduces the standalone ceiling to the euro (test).
- **Window**: 2025-08-01 → 2026-07-31 (12 months, latest complete, includes
  a full summer — the cooling profile needs one). Hourly day-ahead,
  energy-charts.info, all `atlas.ZONES` (zones missing data are skipped and
  listed).
- **Battery**: repo defaults — 1 MW, RTE 85 %, 1.5 cycles/day, no cycle
  cost — at **2 h and 4 h**. Everything is reported per unit of battery
  power, so the numbers scale to any site (LP is linear).
- **Data center**: peak load = **5 × P_bat** (battery = 20 % of the site
  peak; Czyżak's stated on-site sizing anchor "say 20 % of peak load",
  *Energy, Extended* 24/06/2026, there for ramping — used here only as an
  anchor). Sensitivity peak = 2 × and 10 × P_bat on DE-LU, ES, CH.
- **Load profiles** (declared, `connection.dc_load`), IT power flat:
  - `flat`: PUE 1.35 all year — the peak-designed site, and the profile
    Czyżak used in PyPSA (load == peak every hour);
  - `cooling`: PUE 1.10 → 1.35, cosine in the day (peak 15:00 local, CET
    for every zone) × cosine in the year (peak 15 July). Band from Ren, Islam,
    Wierman, *Maximizing Compute Capacity in AI Data Centers…* (arXiv
    2606.00457, 06/2026): hourly PUE of an optimized dry-cooled AI DC ~1.0–1.25
    over the year, peak 1.35 vs 1.10 with evaporative assistance in a
    Central-European climate. **The band is sourced, the cosines are ours.**
- **Cap grid**: cap = peak + k·P_bat, k ∈ {+1, +¾, +½, +¼, 0, −0.1, …, −1.0}.
  k = +1: the battery adds its full power to the connection request (nothing
  binds); k = 0: the battery adds nothing (buys 0 MW); k < 0: the battery
  buys −k·P_bat MW of connection. Infeasible = the battery cannot keep the
  firm load under the cap → reported as such, curve ends there.
- **Metrics (frozen)**: `loss_frac` = 1 − revenue(cap)/ceiling; MW bought
  (peak − cap) per P_bat; **max feasible MW bought**; MW bought at ≤ 10 % and
  ≤ 25 % loss; average price of a bought MW = loss [€/y] / MW bought.
  Feasibility depends on load and battery only, not on prices → the max MW
  bought must be identical across zones (internal check).

## Hypotheses

- **H1 (flat load — Czyżak's claim, quantified)**: for the flat profile every
  cap ≤ peak is either infeasible (k < 0) or earns **zero** (k = 0: no
  headroom to charge). A flat data center buys **0 MW** with any battery;
  the only trade is how much extra connection the battery needs for its own
  arbitrage. Pre-registered expectation for that trade: at k = +½ (half
  power headroom) the 2 h battery loses **< 20 %** of the ceiling in every
  zone (charging at half power over the cheap-hour block still fills 2 h).
- **H2 (cooling load — energy-limited, not power-limited)**: with the
  cooling profile the max feasible MW bought is **< 0.5 P_bat for 2 h**
  (the summer-afternoon excursion above the cap lasts longer than the
  battery) and strictly larger for 4 h. Corollary: loss is convex in MW
  bought — the last MW costs far more than the first.
- **H3 (where the trade is expensive)**: at k = 0 the loss is **< 15 %** in
  DE-LU (the profile's troughs leave 0.55–0.9 P_bat of headroom, enough to
  charge most days) and **higher in solar-heavy zones** (ES, PT, IT-South,
  GR): there the cheapest hours are the summer midday, exactly when the
  cooling peak eats the headroom.

## Results

_(filled after the run, same commit discipline as `1345f40` → `29aa8d2`)_
