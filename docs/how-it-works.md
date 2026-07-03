# How `bess-arbitrage` works — a guide for people coming from financial markets

> A conversational walkthrough of the project, written for people who know
> financial markets well but not energy or code. A calm ~10-minute read.
> Every technical concept is translated into a financial analogy.

---

## 1. In one sentence

It's a **trading desk for a battery**. A battery connected to the power grid
can buy energy when it's cheap and sell it back when it's expensive. This
program takes real electricity prices and computes **the maximum a
perfectly-managed battery could possibly have earned**.

In finance-speak: it's a **storage arbitrage model** on a commodity
(electricity), computing the strategy's **theoretical maximum profit**.

---

## 2. Why the opportunity exists: the intraday spread

The starting point is a quirk of modern power markets. Electricity **can't be
stored easily** — it has to be produced and consumed in the same instant. So
the price moves enormously over the course of a day, far more than any stock
or commodity.

What happens on a typical day in a market full of solar panels (Germany):

- **Midday** — the sun is out, millions of panels are producing at once.
  Supply explodes, demand doesn't → the price **crashes**, sometimes going
  **negative** (you get *paid* to consume; in our June 2025 run the 5th
  percentile is **−15.6 €/MWh**).
- **Evening (19–22)** — the sun sets but people get home, turn everything
  on, and in summer the air conditioners stay on. Demand stays high, supply
  doesn't → the price **spikes**. During the June 23, 2026 heat wave,
  Belgium hit **1,038 €/MWh** in the evening.

This "U"-shaped curve between midday and evening is called the **duck
curve**. The gap between the midday low and the evening peak is the
**intraday spread** — and it's the raw material of the business.

**Financial analogy.** It's essentially a *contango/backwardation* pattern,
compressed into 24 hours and highly predictable in shape (always low at
midday, high in the evening). Buy the midday future and sell it in the
evening, every day. The battery is the vehicle that lets you physically run
this carry trade — it's your **warehouse**.

And the spread is **widening every year** as more solar comes online: it's
not a one-off event, it's a structural trend. That's why storage is *the*
business of the energy transition.

---

## 3. The asset: the battery as a warehouse with constraints

A battery is an energy warehouse, and like any warehouse it has limits.
Modeling it takes four parameters — each with a financial equivalent:

| Parameter | What it means | Finance analogy |
|---|---|---|
| **Power** (MW) | how fast it can charge/discharge | execution speed / size per tick |
| **Duration** (hours) → **Capacity** (MWh) | how much energy it holds in total | max position size / inventory cap |
| **Efficiency** (RTE, ~85%) | you lose energy on every cycle | transaction cost / slippage |
| **Cycles/day** | how many times per day you can use it (usage wears it out) | turnover limit to avoid burning the asset |

Our default example: **1 MW / 2 hours = 2 MWh** of capacity. That means it
can deliver 1 MW for 2 hours before running out. 85% efficiency means that if
you put in 100, you get back 85 (the rest is lost as heat — the physical
"commission" of the trade).

---

## 4. What the program actually does

Given the **real historical hourly prices** (one year = 8,760 hours), the
program decides, for every single hour, whether the battery should
**charge, discharge, or sit idle**, so as to maximize total profit — while
respecting all the warehouse's constraints.

It doesn't do this by trial and error. It formulates it as an
**optimization problem** and solves it exactly.

**What a linear program (LP) is, in plain terms.** Imagine having to choose
8,760 decisions (one per hour) to maximize PnL, but under rigid rules: you
can't discharge more energy than you have stored, you can't exceed capacity,
you can't exceed a set number of cycles per day. An **LP solver** is a
mathematical engine that finds *the* optimal combination of all these
decisions together, guaranteed to be the best possible one.

**Financial analogy.** It's identical to portfolio optimization (think
Markowitz): you maximize an objective (here, profit; there, return) subject
to a set of constraints (here, capacity and efficiency; there, budget and
risk limits). Same math, same type of solver.

Written out in full, the objective it maximizes is simply:

> the sum, over every hour, of **(price × energy sold − price × energy
> bought)**

that is: revenue from discharging minus the cost of charging. Buy low, sell
high, 8,760 times, optimized in one shot.

---

## 5. The key concept: "perfect foresight" = the theoretical ceiling

There's an important catch. The program **knows all the year's prices in
advance**. So it plays with its cards face up: it already knows exactly when
the low and the peak will be.

This is **deliberate**. The result isn't what a real operator would earn —
it's the **absolute maximum** the battery could have extracted from that
market. The **ceiling**.

**Financial analogy — and here a trader gets it instantly.** It's a
**backtest with lookahead**, a *perfect-information upper bound*. It's the
number you get if you know the future. No real strategy beats it; they all
capture some **percentage** of it.

And that's exactly why it's useful, in two ways:

1. **How much value is on the table.** The ceiling tells you the maximum
   potential of that market for that type of battery. It's the size of the
   opportunity.
2. **How you measure an operator.** If a real trader (who uses price
   *forecasts*, not the actual future) takes home 80% of the ceiling, they
   have an **80% capture ratio**. This is *exactly* the metric used to
   evaluate the performance of a battery operator — the job of a "revenue &
   optimisation analyst" in storage.

---

## 6. The technology behind it, piece by piece

Three components, nothing exotic:

- **The data — `energy-charts.info`.** Hourly spot prices come from a free,
  public API run by the Fraunhofer Institute (the German research
  organization). It plays the same role as a Bloomberg/Refinitiv feed for
  historical prices, but open. Market coordinates: the **"bidding zone"**
  (e.g. `DE-LU` = Germany-Luxembourg) is the equivalent of a *ticker*.
- **The solver — HiGHS.** The open-source mathematical engine that solves
  the linear optimization. A standard library, the same category of solver
  used on quant desks.
- **The language — Python.** The code is ~85 lines for the model plus the
  data layer. Three files: one fetches prices, one builds and solves the
  optimization, one is the command-line interface.

Run it like this:

```bash
uv run python -m bess_arbitrage --bzn DE-LU --start 2025-01-01 --end 2025-12-31
```

---

## 7. How to read the result

Real output for Germany, full year 2025:

```
DE-LU  2025-01-01..2025-12-31   (8760 h)
  price: mean 89.3  p5 -0.1  p95 162.4 EUR/MWh
  battery: 1.0 MW / 2.0 h (2.0 MWh), RTE 85%, cap 1.5 cyc/d
  CEILING revenue: 84,901 EUR/MW/year  (total 84,901 EUR)
  capex 250,000 EUR -> simple payback 2.9 y
```

Reading it, line by line:

- **price** — the average price was 89 €/MWh, but the 5th percentile is ~0
  and the 95th is 162: that's the spread the business runs on. The
  dispersion *is* the opportunity.
- **CEILING revenue: 84,901 €/MW/year** — the key number. A perfectly
  managed 1 MW battery could have earned ~85 thousand euros in 2025 from
  day-ahead arbitrage alone. (For June 2025, the most volatile month, the
  same calculation annualized gives **114 thousand** — more midday solar =
  wider spreads = more margin.)
- **payback 2.9 years** — with a cost of ~250 thousand € for that battery
  (market benchmark of $125/kWh), the ceiling pays it back in ~3 years. This
  is a **perfect-foresight payback**: the real one is longer, because a real
  operator only captures a fraction of the ceiling.

**Reality check.** ~85k €/MW/year from arbitrage alone is consistent with
published market figures (Modo Energy estimates ~100k €/MW/year in Germany
in 2025, but that also includes grid services on top of pure arbitrage).
Same order of magnitude → the model isn't talking nonsense.

---

## 8. What it does NOT do yet (intellectual honesty)

To avoid overselling, here are the stated limits — they're also the roadmap:

- **It doesn't use real forecasts.** Today it knows the future (that's the
  ceiling). The next step is to run the strategy with price *forecasts* and
  measure the capture ratio against the ceiling. That's where real skill
  shows up.
- **Day-ahead arbitrage only.** A real battery also earns from other markets
  (balancing/frequency services). Adding them ("revenue stacking") raises
  the numbers.
- **Simplified degradation.** It models wear with a cycles-per-day cap, not
  with a detailed degradation curve based on battery chemistry.
- **A single asset, a single market at a time.** No multi-site portfolio
  yet.

---

## 9. Why this project matters

Storage is the piece that makes the energy transition possible: without
batteries, midday solar goes to waste and evenings stay fossil-powered. The
value of a battery **is** its ability to capture the intraday spread — and
this program is the minimal engine that **measures** that value, on real
data.

From here it scales in every direction: comparing markets (Germany vs.
Belgium vs. UK), strategies with real forecasts, evaluating a whole
portfolio. But the core — *"given a market, how much is a battery worth and
how do you measure whoever operates it"* — is already here, in ~85 lines
running on real prices.
