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

Run 2026-08-17 (pre-registration commit `5be987f`), 2025-08-01 → 2026-07-31,
**34 zones** (LV skipped: energy-charts unreachable at run time — re-run
with `--zones LV --append`). Full tables and the curve:
`reports/connection-cap-2025-08-01_2026-07-31.{md,csv,png}`. Cells: 34 zones ×
2 profiles × 2 durations × 15 caps, + peak sensitivity on DE-LU/ES/CH.

| | 2 h battery | 4 h battery |
|---|---|---|
| **flat**, loss at cap = peak (k = 0) | **100 %** in every zone | 100 % |
| flat, any cap < peak | infeasible, every zone | infeasible |
| flat, loss at k = +½ (half power headroom) | 3.0 % (ES) – 10.9 % (IT-Sardinia), median 5.7 % | 10.0 % – 23.8 %, median 15.9 % |
| **cooling**, max MW bought | **0.30 P_bat, identical in all 34 zones** | **0.40 P_bat**, all zones |
| cooling, loss at k = 0 (0 MW bought) | 3.8 % (GR) – 17.8 % (CH), median 9.5 % | 7.8 % (FI) – 32.3 % (CH), median 21.1 % |
| cooling, loss at 0.1 P_bat bought | 8 – 29 %, median 17 % | 11 – 43 %, median 29 % |
| cooling, loss at 0.2 P_bat bought | 14 – 46 %, median 31 % | 15 – 56 %, median 40 % |
| cooling, loss at the max MW bought | 23 % (FI) – 67 % (CH), median 49 % | 31 % – 87 %, median 66 % |
| cooling, MW bought at ≤ 10 % loss | 0 in 31/34 zones (0.1 in GR, FI, EE) | 0 everywhere |
| average price of a bought MW at the max, €/MW-bought/y | 22 k (SE2) – 165 k (HU), median 123 k | 34 k – 281 k, median 212 k |

Worked example, a 250 MW Gigafactory-scale site with a 50 MW battery
(peak = 5 × P_bat): a 2 h battery can keep the site under **235 MW** (buys
15 MW, −6 %) at the cost of about half its arbitrage revenue; a 4 h battery
under **230 MW** (−8 %) at two thirds. Anything below is infeasible — the
summer-afternoon excursion above the cap outlasts the battery. With a flat
profile, nothing: the site needs 250 MW plus whatever the battery wants.

- **H1 (flat load — Czyżak's "no surplus" claim): confirmed, and
  quantified.** A flat data center buys **0 MW** with any battery; at
  cap = peak the battery earns exactly zero because it can never charge; the
  extra headroom it needs for its own arbitrage is cheap for a 2 h battery
  (half its power costs 3–11 % of the ceiling, as pre-registered < 20 %) but
  not for a 4 h one (10–24 %: it needs twice the charging energy through the
  same door).
- **H2 (cooling load — energy-limited): confirmed.** Max MW bought is
  **0.30 P_bat (2 h) and 0.40 P_bat (4 h)**, identical across zones as
  required (feasibility does not see prices); doubling the energy buys only
  a third more MW. Loss is convex: the first 0.1 P_bat costs a median 17 %
  (2 h), the last 0.1 costs ~18 pp more on top of 31 %. The site-peak
  sensitivity confirms the mechanism: with peak = 10 × P_bat the same
  battery buys 0.30/0.60 P_bat (relatively smaller excursion), with peak =
  2 × P_bat only 0.10.
- **H3 (where the trade is expensive): first half confirmed, second half
  falsified.** DE-LU loses 11.1 % at k = 0 (< 15 % ✓). But the solar-heavy
  zones lose **less**, not more: GR 3.8 %, BG 4.8 %, ES 6.8 %, PT 7.2 %,
  IT-South 10.1 % vs DE-LU 11.1 %; the expensive zones are **CH 17.8 %,
  IT-Sardinia 14.7 %, NO2 13.6 %, IT-North 13.5 %, IT-Centre-North 13.2 %**
  — hydro/nuclear-shaped markets — and the cheapest are GR, EE, BG, FI, RO,
  LT, SE2, ES. The pre-registered mechanism (cooling peak eats the headroom
  exactly at the solar-cheap midday) is real but second-order: at k = 0 the
  headroom is < 1 P_bat in *every* hour (0.93 at night, 0 at the summer
  peak), so charging is throttled everywhere and the loss tracks how much of
  a zone's ceiling comes from *fast, single-hour* charging (spiky, few-hour
  spreads: CH, IT, NO) versus broad cheap blocks that a throttled battery can
  still fill (Nordics, South-East). Reported as falsified; the mechanism is a
  candidate, not a finding.

Side-finding, not pre-registered: for the flat-vs-cooling comparison the
cooling profile with 0 MW bought (k = 0) is *itself* the honest baseline
for a peak-designed site — a real data center behind its nameplate
connection already forfeits 4–18 % (2 h) / 8–32 % (4 h) of the standalone
ceiling before buying a single MW. Stage 2 must measure capture against
**this** number, not against the standalone ceiling.
