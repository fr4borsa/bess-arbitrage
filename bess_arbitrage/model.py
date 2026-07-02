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

    @property
    def revenue_per_mw_year(self) -> float:
        return self.revenue_eur / self.battery.power_mw / self.hours * 8760

    @property
    def simple_payback_years(self) -> float:
        annual = self.revenue_per_mw_year * self.battery.power_mw
        return self.battery.capex_eur / annual if annual > 0 else float("inf")


def optimize(prices: pd.Series, bat: Battery, soc0: float = 0.0) -> Result:
    """Maximize arbitrage revenue over the given hourly price series [EUR/MWh].

    soc0: initial state of charge [MWh] — lets capture.py chain daily windows.
    """
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
    m += pulp.lpSum(p[t] * (dis[t] - chg[t]) for t in range(n))

    for t in range(n):
        prev = soc[t - 1] if t > 0 else soc0
        m += soc[t] == prev + eff * chg[t] - dis[t] / eff
    if bat.max_cycles_per_day is not None:
        days = max(1, n // 24)
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
    return Result(revenue_eur=pulp.value(m.objective), hours=n, battery=bat, dispatch=disp)


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


if __name__ == "__main__":
    _demo()
