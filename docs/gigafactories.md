# EU AI Gigafactories × clean power — deep dive and replication

Companion to stage 1 of the BESS × data-center work
(`experiments/PROTOCOL-connection-cap.md`). Two questions, one document:
what the EU call actually asks for on energy, and whether the widely-shared
"250 MW data center → 652–1000 MW of batteries" sizing reproduces with an
open LP on realized 2025-26 weather.

## 1. The call, from the primary sources

**European Commission, IP/26/1708, 30 July 2026** — "EU launches AI
Gigafactories call to boost Europe's computing capacity and unlock more than
€30 billion in investment":

- up to **seven** AI Gigafactories, two lots, two development phases; up to
  **€10 bn** in EU and national funding, expected to unlock ≥ **€20 bn** private;
- **lot 1**: up to 4 projects, up to **€100 M** EU funding in phase one and up
  to an additional **€400 M** per project in phase two; each must deploy at
  least as many top AI processors as Europe's most powerful AI Factory, ×3 in
  phase two;
- **lot 2**: up to 3 projects, up to **€200 M** + **€800 M**; up to twice the
  processors of the most powerful AI Factory, ×4 in phase two;
- 18 Member States in the joint procurement (HR CZ DK EE FI FR DE GR HU IE IT
  LV LT PL PT SK ES SE); the call **closes 12 November 2026**, awards early
  2027, operations within 18 months of signature;
- energy language in the release: "energy-efficient data centres". No number.

**Tender specifications, primary source** (EUROHPC/2026/OP/0008, call ID
EUROHPC-2026-CEI-AIGF-01, 133 pp., on the Funding & Tenders portal — read
19/08/2026): the Gigafactory must be *"supported by an environmentally
sustainable infrastructure, in particular for energy and water supply
systems"*. Sustainability and energy efficiency = **10 points out of 100 in
the technical table**; *"The Technical Evaluation criteria shall carry an
overall weighting of 40%"*; and the final ranking is *"0.5 X1 + 0.25 X2 +
0.25 X3"*. So sustainability is **4 % of the Part-1 score but ≈ 2 % of the
final ranking**, and *"Grid flexibility (10%)"* inside it — *"demand
response + time-shifting + storage (excellent)"* — is worth **≈ 0.2 % of the
award**. Czyżak's "4 %" (05/08/2026) is the Part-1 figure. By contrast
*"Adequacy of power infrastructure (0–8 points)"* is a separate technical
criterion: **firm grid access is worth roughly 8× what demand flexibility is
worth** in this tender.

What the tender does require on power (verbatim): *"a minimum IT load of
120 MW for Lot 1 and 150 MW for Lot 2, fully operational within Phase 2"*
(Phase 1 indicative 15–30 / 20–50 MW); *"85–90% of grid capacity to IT (net
of auxiliaries)"*; *"interconnection agreements covering, within Phase 2,
firm capacity … including POI voltage, allocated MVA, and energization
milestones"*; system impact / feasibility studies; *"reliable backup power
(batteries and generators) … 48–72 hours without the grid"*; and grid-aware
operation: *"time-shifting of non-urgent training jobs, demand response
participation, and/or on-site storage to reduce peak stress"*. Scoring guide
for renewables: *"100% with hourly matching (excellent), ≥80% annual (good),
50–79% (acceptable), <50% (poor)"*; PUE ≤ 1.10 excellent, > 1.25 poor.
Processors: Lot 1 ≥ 25,000 H100-equivalent → ≥ 75,000 in Phase 2; Lot 2
≥ 40,000 → ≥ 100,000. Purchase of compute time capped at 17 % of the CAPEX;
"up to EUR 5 billion" total, of which up to €1 bn under the current MFF.
(Earlier draft of this note carried "≥ 100,000 GPUs", "120–150 MW",
"up to 1 GW" second-hand — superseded by the text above.)

What this means for the thesis: the tender prices flexibility at ~0.2 % of
the award and firm MVA at ~8× that — the **connection**, not the
sustainability score, is what decides where these sites can physically be
built in 18 months. That is stage 1's question, and the 48–72 h battery +
genset the tender already forces every bidder to buy is the asset stage 1
prices against the connection.

## 2. Czyżak's sizing, precisely

- 250 MW **flat** load; PyPSA; expand wind, solar, batteries; grid power
  "dispatched as a last resort" (expensive spot); weather ENTSO-E PECD; capex
  and battery duration unstated (his 24/06 piece: "with 1–2 h storage it was
  quite difficult to reach 80 %+ of hourly matching … 4–8 h batteries unlock
  the 90 % territory").
- Metric: "**the percentage of hours in the year when clean power generation
  exceeds the data center load**" — hours-matched, not energy-matched.
- Text: 464–800 MW wind, 429–1000 MW solar, 652–1000 MW batteries. Chart
  (24 countries, read off the image): ES 432/1000/652 (96.7 %),
  FR 618/1000/843 (95.1 %), DE 981/775/1000 (93.2 %), PL 702/737/1000 (97.0 %),
  IT 428/989/886 (96.6 %); solar and battery sit at **exactly 1000 MW in most
  countries** — 1000 MW is a bound of his optimizer, so "652–1000" is a
  truncated range, and the wind range in the text (464–800) does not match
  the chart (432–1000, DK at 1000).
- The line that stage 1 tests: *"typically, a data center developer will max
  out the grid connection with the compute load. So there's no surplus of
  power that can be drawn to charge the battery."* (24/06/2026)

## 3. Replication with the repo's LP

Protocol: `experiments/PROTOCOL-gigafactory-sizing.md`; results:
`reports/gigafactory-sizing-2025-08-01_2026-07-31.md`.

One LP per country, same PuLP/HiGHS stack as the arbitrage model: expand
wind, solar and a 4 h battery (technology-data 2030 costs, 7 %), 250 MW flat
load, grid import at a penalty price, 1000 MW cap per technology like his,
plus an uncapped cell; realized 2025-08 → 2026-07 capacity factors from
energy-charts (generation ÷ installed capacity). 19 of his 24 countries had
the data.

What reproduces:

- **solar sits at the 1000 MW cap** in 15/19 countries — his chart's
  flat-top solar bars are the cap, as suspected;
- the split **solar-heavy south (IT, PT, ES: 320–640 MW wind) vs wind-heavy
  north/east (DE, SE, LT, CZ: 920–1000 MW)**;
- **battery/DC ≈ 2.6–4** where the portfolio reaches ≥ 90 % hours-matched
  (IT 2.92×, PT 2.65× at 300 €/MWh grid).

What does not:

- at a grid price of 300 €/MWh (≈ 3× the 2025 DE-LU average of 89 €/MWh) the
  cost-optimal portfolio stops at **62–93 % hours-matched with 0.35–2.9×
  of battery**, and buys the rest from the grid; only IT and PT clear 90 %;
- his **652–1000 MW battery band reappears only at ~1000 €/MWh** (DE 3.42×,
  PL 3.04×, IT 3.35×, FR 2.45×, ES 2.17×), i.e. when grid power is all but
  forbidden. At 150 €/MWh the battery nearly vanishes in DE and PL
  (24 and 60 MW).

Reading: "a 250 MW Gigafactory needs 652–1000 MW of batteries" is the price
of *near-banning grid power*, not a property of European weather. His own
caveat says so ("depending a lot on the grid price"); the replication puts a
number on it: the battery moves by **3–35×** across a plausible range of
grid penalties, the wind and solar by less than 2×. For a tender that
weighs clean power at ~2 % of the final award, the relevant question is what penalty a bidder
implicitly sets — and nobody has published that.

Limitations declared in the protocol: one weather year; solar capacity
factors understated where rooftop PV is large (statistics miss it, installed
capacity counts it: DE 0.08, AT 0.07) → solar MW inflated by roughly a third
there; onshore wind only; 4 h battery, no cycle cap.

## 4. How it connects to stage 1

Czyżak sizes batteries **beside** the generation (matching); stage 1 sizes
the battery **behind the meter** (connection). Same machine, opposite
constraint: matching wants energy over days, the connection wants power over
hours. Both say the same thing about a flat data center: it needs a bigger
connection than its load, or a battery that never charges.
