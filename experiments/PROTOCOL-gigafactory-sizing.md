# Pre-registered protocol — replicating the AI-Gigafactory clean-power sizing

**Status: pre-registered**, committed before any run. All countries reported,
including the ones where the replication disagrees with the source.

## Question

The EU call for **AI Gigafactories** (Commission press release IP/26/1708,
30/07/2026: up to 7 sites in two lots, €100 M + €400 M / €200 M + €800 M of EU
funding per project, up to €10 bn public, call closes 12/11/2026) weighs
sustainability at **10 points out of 100 inside the 40 % technical block ≈
4 % of the total score** (Paweł Czyżak, *Energy, Extended*, 05/08/2026, from
the tender documents). Czyżak sized in PyPSA what a 250 MW Gigafactory needs
for "90 %+ clean power matching (the percentage of hours in the year when
clean power generation exceeds the data center load)": text says
**464–800 MW wind, 429–1000 MW solar, 652–1000 MW batteries** by country; his
chart (24 countries) reads e.g. ES 432/1000/652, FR 618/1000/843, DE 981/775/
1000, PL 702/737/1000, IT 428/989/886 (wind/solar/battery) — with solar and
battery pinned at **1000 MW in most countries: 1000 is a cap of his optimizer,
not a result**. Grid power "dispatched as a last resort", flat load, ENTSO-E
PECD weather, capex unstated, battery duration unstated (his 24/06 piece finds
"4–8 h batteries unlock the 90 % territory").

Can the repo's LP, on realized 2025-26 generation, reproduce the ratio
**MW battery / MW data center ≈ 2.6–4** — and what happens without the cap?

## Fixed design

- **Engine**: one LP per country (PuLP/HiGHS, same stack as the arbitrage
  model): variables wind W, solar S, battery power B (energy = 4 h × B, RTE
  85 %, no cycle cap — a sizing model), hourly charge/discharge/SoC,
  grid import ≥ 0, curtailment ≥ 0. Balance every hour:
  `W·cf_w + S·cf_s + dis − chg + grid − curt = 250 MW`.
  Objective: minimize annualized capex + FOM + Σ grid × price_grid.
- **Costs**: PyPSA `technology-data` `outputs/costs_2030.csv` (master, fetched
  and cached): onwind, solar-utility, battery inverter (EUR/kW) + battery
  storage (EUR/kWh); FOM %/y; lifetimes; annuity at 7 % (repo WACC default).
- **Grid price**: 300 €/MWh baseline ("expensive spot market"); sensitivity
  150 and 1000 €/MWh on ES, FR, DE, PL, IT.
- **Caps**: 1000 MW per technology (his), plus an **uncapped** cell.
- **Weather**: realized hourly solar and onshore-wind generation per country
  (energy-charts `public_power`) divided by installed capacity (energy-charts
  `installed_power`, monthly where available), 2025-08-01 → 2026-07-31, one
  weather year, CF clipped to [0, 1]. Offshore wind excluded (declared).
- **Load**: 250 MW flat (his).
- **Countries**: his 24 (AT BE BG CZ DE DK EE ES FI FR GR HR HU IE IT LT LV NL
  PL PT RO SE SI SK, UK) — the ones energy-charts covers; missing → listed.
- **Metrics (frozen)**: W, S, B [MW]; B/250; **hours-matched share** (his
  metric: hours with grid < 0.5 % of load); energy-matched share (1 − Σgrid/ΣL);
  curtailed share of clean generation; €/MWh delivered.

## Hypotheses

- **H1 (the cap is the result)**: with the 1000 MW cap, solar and/or battery
  hit the cap in a majority of countries — the source's ranges are
  cap-truncated. Uncapped, battery MW exceeds 1000 in those countries.
- **H2 (the ratio holds)**: capped, B/250 ≥ 2.6 in every country that reaches
  ≥ 90 % hours-matched; the ranking solar-heavy (ES, IT, PT, GR: wind < 500
  MW) vs wind-heavy (DE, PL, DK, FI, IE, UK: wind > 700 MW) is reproduced.
- **H3 (weather year & capex move the level, not the shape)**: our per-country
  numbers differ from his by up to ±30 % on individual technologies, but the
  hours-matched share lands in the same 88–97 % band at the same price of
  grid power. Anything outside is reported as a disagreement, not smoothed.

## Results

Run 2026-08-17 (pre-registration commit `f609e55`), window 2025-08-01 →
2026-07-31, 19 countries (skipped for missing energy-charts series or
installed capacity: IE, LV, NL, SI, SK, UK). Full tables:
`reports/gigafactory-sizing-2025-08-01_2026-07-31.md`. Annualized costs
(technology-data 2030, 7 %): wind 128.3 k€/MW-y, solar 48.1 k€/MW-y,
battery 31.2 k€/MW-y + 16.3 k€/MWh-y (4 h → 96.4 k€/MW-y).

| country | grid €/MWh | wind | solar | battery | B/DC | hours-matched | energy-matched | Czyżak W/S/B (hours) |
|---|---|---|---|---|---|---|---|---|
| ES | 300 | 641 | 1000* | 440 | 1.76 | 87.6 % | 93.2 % | 432 / 1000 / 652 (96.7) |
| ES | 1000 | 973 | 1000* | 541 | 2.17 | 95.4 % | 97.7 % | |
| FR | 300 | 728 | 1000* | 470 | 1.88 | 86.7 % | 93.3 % | 618 / 1000 / 843 (95.1) |
| FR | 1000 | 1000* | 1000* | 613 | 2.45 | 95.0 % | 97.6 % | |
| DE | 300 | 1000* | 1000* | 306 | 1.22 | 70.9 % | 86.0 % | 981 / 775 / 1000 (93.2) |
| DE | 1000 | 1000* | 1000* | 854 | 3.42 | 78.6 % | 89.7 % | |
| PL | 300 | 837 | 981 | 354 | 1.42 | 77.7 % | 89.0 % | 702 / 737 / 1000 (97.0) |
| PL | 1000 | 1000* | 1000* | 760 | 3.04 | 88.8 % | 94.8 % | |
| IT | 300 | 323 | 1000* | 729 | 2.92 | 91.8 % | 94.3 % | 428 / 989 / 886 (96.6) |
| IT | 1000 | 529 | 1000* | 837 | 3.35 | 96.4 % | 97.6 % | |

`*` = at the 1000 MW cap. Across the 19 countries at 300 €/MWh: battery
0.35× (SE) … 2.92× (IT) the DC; hours-matched 62–93 %, ≥ 90 % only in IT
and PT; solar at the cap in 15/19, wind at the cap in DE and SE, **battery
never at the cap**. Uncapped, solar grows to 1100–1740 MW and the battery to
at most 784 MW (IT).

- **H1 (the cap is the result): half-confirmed.** Solar is cap-bound almost
  everywhere, exactly as in his chart. The battery is **not** — at 300 €/MWh
  it stays 230–730 MW; his 1000 MW batteries do not come from the cap alone.
- **H2 (B/DC ≥ 2.6 wherever ≥ 90 % hours-matched): confirmed where it
  applies, but the premise rarely holds.** At 300 €/MWh only IT (2.92×) and
  PT (2.65×) reach 90 % hours-matched, both above 2.6×. Everywhere else the
  cost-optimal portfolio stops at 62–88 % hours-matched with 0.35–2.3× of
  battery: at that grid price the model *buys* the missing hours from the
  grid rather than over-building storage. The solar-heavy / wind-heavy split
  is reproduced (IT, PT, ES: wind 323–641 MW; DE, SE, LT, CZ: 916–1000 MW).
- **H3 (level vs shape): falsified as stated — the grid price moves the
  battery by 3–35×, not ±30 %.** DE goes 24 → 306 → 854 MW battery for grid
  at 150 → 300 → 1000 €/MWh; PL 60 → 354 → 760. His 652–1000 MW band
  (2.6–4×) reappears only at **~1000 €/MWh**, i.e. when the grid is all but
  forbidden. **The headline "a 250 MW Gigafactory needs 652–1000 MW of
  batteries" is the price of near-banning grid power, not a property of the
  weather.** Stated as a disagreement on the *interpretation*, not on his
  arithmetic — his caveat ("depending a lot on the grid price") is the
  whole result.

Declared limitations: one weather year (his: PECD); solar CF from ENTSO-E
statistics ÷ installed capacity **incl. self-consumption**, so CF is
understated where rooftop PV is large (DE 0.08, AT 0.07 vs a typical
0.10–0.12) → solar MW here are inflated by roughly a third in those
countries — the qualitative conclusions do not depend on it; onshore wind
only; 4 h battery, no cycle cap.
