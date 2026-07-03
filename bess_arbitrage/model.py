"""Perfect-foresight battery arbitrage (LP). This is the revenue CEILING:
prices are known in advance, so real dispatch with forecasts earns less."""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd
import pulp


@dataclass
class Battery:
    power_mw: float = 1.0          # max charge/discharge power
    duration_h: float = 2.0        # energy / power -> capacity
    rte: float = 0.85             # round-trip efficiency (split sqrt on each leg)
    capex_eur_per_kwh: float = 125.0  # Ember all-in benchmark; IRENA installed ~192
    max_cycles_per_day: float | None = 1.5  # throughput cap; None = unlimited

    @property
    def capacity_mwh(self) -> float:
        return self.power_mw * self.duration_h

    @property
    def capex_eur(self) -> float:
        return self.capacity_mwh * 1000 * self.capex_eur_per_kwh


@dataclass
class Result:
    revenue_eur: float
    hours: int
    battery: Battery
    dispatch: pd.DataFrame | None = None  # hourly price/charge/discharge/soc, for the UI
    stack: dict | None = None  # revenue split per market (only when products passed)

    @property
    def revenue_per_mw_year(self) -> float:
        return self.revenue_eur / self.battery.power_mw / self.hours * 8760

    @property
    def simple_payback_years(self) -> float:
        annual = self.revenue_per_mw_year * self.battery.power_mw
        return self.battery.capex_eur / annual if annual > 0 else float("inf")


BLOCK_H = 4  # DE capacity products (FCR, aFRR) clear in 4h blocks


def optimize(prices: pd.Series, bat: Battery, soc0: float = 0.0,
             products: pd.DataFrame | None = None,
             committed: pd.DataFrame | None = None,
             fcr_reserve_h: float = 0.25, afrr_reserve_h: float = 1.0) -> Result:
    """Maximize arbitrage revenue over the given hourly price series [EUR/MWh].

    soc0: initial state of charge [MWh] — lets capture.py chain daily windows.
    products: optional capacity prices [EUR/MW per 4h block], one row per block
      (block i = hours 4i..4i+3), columns among {fcr, afrr_pos, afrr_neg}.
      Co-optimizes capacity commitment with dispatch. Capacity-only floor:
      no activation energy is modeled.
    committed: optional FIXED capacity commitments [MW per block, same columns]
      already awarded in earlier auctions — enforced as headroom constraints
      only; capacity revenue is settled outside the LP. Mutually exclusive
      with products.
    fcr_reserve_h / afrr_reserve_h: SOC headroom [h × MW committed]. FCR: DE
      prequalification requires full power for 15 min, both directions. aFRR:
      activations persist, 1 h in the product's own direction is conservative.
    """
    if products is not None and committed is not None:
        raise ValueError("pass either products (co-optimize) or committed (fixed), not both")
    p = prices.to_list()
    n = len(p)
    eff = math.sqrt(bat.rte)  # per-leg efficiency
    cap = bat.capacity_mwh
    pmax = bat.power_mw  # 1h steps -> power [MW] == energy/step [MWh]

    m = pulp.LpProblem("arbitrage", pulp.LpMaximize)
    chg = [pulp.LpVariable(f"c{t}", 0, pmax) for t in range(n)]   # grid -> battery [MWh]
    dis = [pulp.LpVariable(f"d{t}", 0, pmax) for t in range(n)]   # battery -> grid [MWh]
    soc = [pulp.LpVariable(f"s{t}", 0, cap) for t in range(n)]    # state of charge [MWh]

    # revenue = sell discharge, pay for charge, at the hourly price
    da_rev = pulp.lpSum(p[t] * (dis[t] - chg[t]) for t in range(n))

    # ── capacity products (only complete 4h blocks; trailing hours stay DA-only)
    cvars: dict[str, list] = {}
    if products is not None:
        nb = n // BLOCK_H
        if len(products) != nb:
            raise ValueError(f"products has {len(products)} rows, expected {nb} "
                             f"(one per complete {BLOCK_H}h block of {n} hours)")
        for col in ("fcr", "afrr_pos", "afrr_neg"):
            if col in products and products[col].notna().all():
                cvars[col] = [pulp.LpVariable(f"{col}{b}", 0, pmax) for b in range(nb)]
        fcr = cvars.get("fcr")
        ap, an = cvars.get("afrr_pos"), cvars.get("afrr_neg")
        zero = pulp.LpAffineExpression()
        for b in range(nb):
            up = (fcr[b] if fcr else zero) + (ap[b] if ap else zero)
            dn = (fcr[b] if fcr else zero) + (an[b] if an else zero)
            for t in range(b * BLOCK_H, (b + 1) * BLOCK_H):
                m += dis[t] + up <= pmax        # power headroom, up direction
                m += chg[t] + dn <= pmax        # power headroom, down direction
                # energy headroom: stored MWh to deliver up, empty room to absorb down
                m += soc[t] >= fcr_reserve_h * (fcr[b] if fcr else zero) \
                    + afrr_reserve_h * (ap[b] if ap else zero)
                m += cap - soc[t] >= fcr_reserve_h * (fcr[b] if fcr else zero) \
                    + afrr_reserve_h * (an[b] if an else zero)
    if committed is not None:
        nb = n // BLOCK_H
        if len(committed) != nb:
            raise ValueError(f"committed has {len(committed)} rows, expected {nb}")
        for b in range(nb):
            row = committed.iloc[b]
            fc = float(row.get("fcr", 0.0) or 0.0)
            po = float(row.get("afrr_pos", 0.0) or 0.0)
            ne = float(row.get("afrr_neg", 0.0) or 0.0)
            e_up = fcr_reserve_h * fc + afrr_reserve_h * po
            e_dn = fcr_reserve_h * fc + afrr_reserve_h * ne
            for t in range(b * BLOCK_H, (b + 1) * BLOCK_H):
                m += dis[t] <= pmax - (fc + po)
                m += chg[t] <= pmax - (fc + ne)
                m += soc[t] >= e_up
                m += soc[t] <= cap - e_dn

    cap_rev = pulp.lpSum(
        float(products[col].iloc[b]) * cvars[col][b]
        for col in cvars for b in range(len(cvars[col]))) if cvars else 0.0
    m += da_rev + cap_rev

    for t in range(n):
        prev = soc[t - 1] if t > 0 else soc0
        m += soc[t] == prev + eff * chg[t] - dis[t] / eff
    if bat.max_cycles_per_day is not None:
        days = max(1, n // 24)
        # capacity commitment consumes no cycles: activation is not modeled
        m += pulp.lpSum(dis) <= bat.max_cycles_per_day * cap * days

    # ponytail: HiGHS in-process — PuLP's bundled CBC is x86, breaks on Apple Silicon.
    m.solve(pulp.HiGHS(msg=False))
    if pulp.LpStatus[m.status] != "Optimal":
        raise RuntimeError(f"solver status: {pulp.LpStatus[m.status]}")
    disp = pd.DataFrame(
        {
            "price": prices.to_numpy(),
            "charge": [chg[t].value() for t in range(n)],
            "discharge": [dis[t].value() for t in range(n)],
            "soc": [soc[t].value() for t in range(n)],
        },
        index=prices.index,
    )
    stack = None
    if cvars:
        for col, vs in cvars.items():  # committed MW, block broadcast to hours
            disp[col] = [vs[min(t // BLOCK_H, len(vs) - 1)].value() if t // BLOCK_H < len(vs)
                         else 0.0 for t in range(n)]
        # split from solved values (da_rev aliases nothing here, but dispatch is
        # the ground truth either way)
        stack = {"da_eur": float((disp["price"] * (disp["discharge"] - disp["charge"])).sum())} | {
            f"{col}_eur": sum(float(products[col].iloc[b]) * vs[b].value()
                              for b in range(len(vs)))
            for col, vs in cvars.items()}
    return Result(revenue_eur=pulp.value(m.objective), hours=n, battery=bat,
                  dispatch=disp, stack=stack)


def _demo() -> None:
    # ponytail: synthetic 48h, two cheap nights + two expensive evenings.
    # A 1MW/2h battery must buy low, sell high; revenue must be positive and
    # below the perfect spread ceiling (cap * Ndays * spread).
    import numpy as np
    idx = pd.date_range("2025-01-01", periods=48, freq="1h", tz="UTC")
    base = np.tile([10] * 6 + [50] * 6 + [10] * 6 + [200] * 6, 2)[:48]
    prices = pd.Series(base, index=idx, dtype=float)
    bat = Battery(power_mw=1, duration_h=2, rte=1.0, max_cycles_per_day=1)
    res = optimize(prices, bat)
    # with rte=1, 1 cycle/day, 2 MWh: buy 2MWh@10, sell 2MWh@200 -> ~380/day, 2 days
    assert 700 < res.revenue_eur < 800, res.revenue_eur
    assert res.simple_payback_years > 0
    print(f"demo ok: revenue {res.revenue_eur:.0f} EUR / 2 days, "
          f"payback {res.simple_payback_years:.1f} y")


def _demo_stack() -> None:
    # ponytail: co-optimization self-checks on the same synthetic 48h shape.
    import numpy as np
    idx = pd.date_range("2025-01-01", periods=48, freq="1h", tz="UTC")
    base = np.tile([10] * 6 + [50] * 6 + [10] * 6 + [200] * 6, 2)[:48].astype(float)
    px = pd.Series(base, index=idx)
    bat = Battery(power_mw=1, duration_h=2, rte=1.0, max_cycles_per_day=1)
    nb = len(px) // BLOCK_H

    # A) all capacity prices at zero -> revenue identical to pure arbitrage
    zeros = pd.DataFrame({"fcr": [0.0] * nb, "afrr_pos": [0.0] * nb, "afrr_neg": [0.0] * nb})
    pure = optimize(px, bat).revenue_eur
    assert abs(optimize(px, bat, products=zeros).revenue_eur - pure) < 1e-6

    # B) flat prices + huge FCR price -> full-FCR every block, revenue = sum of blocks
    flat = pd.Series([40.0] * 48, index=idx)
    big = pd.DataFrame({"fcr": [1000.0] * nb})
    res = optimize(flat, bat, soc0=0.5, products=big)  # soc0 covers the 15-min reserve
    assert abs(res.revenue_eur - bat.power_mw * 1000.0 * nb) < 1e-6, res.revenue_eur
    assert abs(res.stack["da_eur"]) < 1e-6, res.stack

    # C+D) mixed run: SOC/power headroom invariants hold hour by hour, stack >= DA-only
    mix = pd.DataFrame({"fcr": [30.0] * nb, "afrr_pos": [15.0] * nb, "afrr_neg": [5.0] * nb})
    r = optimize(px, bat, products=mix)
    d = r.dispatch
    assert r.revenue_eur >= pure - 1e-6  # co-optimization never hurts
    for t in range(len(d)):
        row = d.iloc[t]
        assert row["soc"] >= 0.25 * row["fcr"] + 1.0 * row["afrr_pos"] - 1e-6, (t, dict(row))
        assert bat.capacity_mwh - row["soc"] >= 0.25 * row["fcr"] + 1.0 * row["afrr_neg"] - 1e-6
        assert row["discharge"] + row["fcr"] + row["afrr_pos"] <= bat.power_mw + 1e-6
        assert row["charge"] + row["fcr"] + row["afrr_neg"] <= bat.power_mw + 1e-6
    split = {k: round(v) for k, v in r.stack.items()}
    print(f"demo ok: stack {r.revenue_eur:.0f} EUR (DA-only {pure:.0f}, "
          f"uplift {(r.revenue_eur / pure - 1):.0%}) split {split}")


if __name__ == "__main__":
    _demo()
    _demo_stack()
