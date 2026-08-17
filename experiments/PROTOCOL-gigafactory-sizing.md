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

_(filled after the run)_
