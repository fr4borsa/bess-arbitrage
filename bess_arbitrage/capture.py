"""Capture ratio: how much of the perfect-foresight ceiling a realistic
dispatch keeps. Two variants, both reusing the arbitrage LP day by day:

- rolling day-ahead: LP on each day's own (known) prices — the day-ahead
  auction view — with SOC carried across midnight. Isolates the horizon effect.
- persistence forecast: LP on YESTERDAY's prices used as today's forecast,
  schedule settled at TODAY's real prices. Standard industry baseline.

Both dispatches are feasible for the full-period LP, so revenue <= ceiling
by construction; capture_ratio = revenue / ceiling on the same hours.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .model import Battery, optimize


@dataclass
class Capture:
    ceiling_eur: float   # perfect foresight over this variant's settled hours
    revenue_eur: float
    hours: int

    @property
    def ratio(self) -> float:
        return self.revenue_eur / self.ceiling_eur if self.ceiling_eur > 0 else float("nan")


def _days(prices: pd.Series) -> list[pd.Series]:
    return [g for _, g in prices.groupby(prices.index.date)]


def rolling_day_ahead(prices: pd.Series, bat: Battery) -> Capture:
    """Day-by-day LP on each day's real prices, SOC carried between days.
    The cycles cap is already pro-rata per day inside optimize()."""
    revenue, soc0 = 0.0, 0.0
    for day in _days(prices):
        res = optimize(day, bat, soc0=soc0)
        revenue += res.revenue_eur
        soc0 = max(0.0, res.dispatch["soc"].iloc[-1])
    return Capture(optimize(prices, bat).revenue_eur, revenue, len(prices))


def persistence_forecast(prices: pd.Series, bat: Battery) -> Capture:
    """Optimize on yesterday's prices, settle at today's real prices.
    Day 1 has no yesterday and is skipped — ceiling uses the same hours."""
    days = _days(prices)
    revenue, soc0, settled = 0.0, 0.0, []
    for prev, today in zip(days, days[1:]):
        n = min(len(prev), len(today))  # partial edge days: align by position
        forecast = pd.Series(prev.to_numpy()[:n], index=today.index[:n])
        plan = optimize(forecast, bat, soc0=soc0).dispatch
        revenue += float((today.to_numpy()[:n] * (plan["discharge"] - plan["charge"])).sum())
        soc0 = max(0.0, plan["soc"].iloc[-1])
        settled.append(today.iloc[:n])
    real = pd.concat(settled)
    return Capture(optimize(real, bat).revenue_eur, revenue, len(real))


def _demo() -> None:
    # ponytail: 6 synthetic days, valley/peak shape whose peak level AND hour
    # drift day to day — persistence keeps the shape but mistimes the peak.
    import numpy as np

    def day(pk: float, shift: int) -> list[float]:
        return list(np.roll([10] * 6 + [50] * 6 + [10] * 6 + [pk] * 6, shift))

    vals = np.concatenate([day(pk, sh) for pk, sh in
                           zip([200, 160, 240, 120, 220, 180], [0, 1, -1, 1, 0, -1])]).astype(float)
    idx = pd.date_range("2025-01-01", periods=len(vals), freq="1h", tz="UTC")
    px = pd.Series(vals, index=idx)
    bat = Battery(power_mw=1, duration_h=2, rte=0.85, max_cycles_per_day=1.5)
    for name, c in [("rolling", rolling_day_ahead(px, bat)),
                    ("persistence", persistence_forecast(px, bat))]:
        assert c.ceiling_eur > 0, (name, c)
        assert 0 < c.revenue_eur <= c.ceiling_eur + 1e-6, (name, c)  # ceiling dominates
        assert 0 < c.ratio <= 1 + 1e-9, (name, c.ratio)
        print(f"demo ok: {name:11s} {c.revenue_eur:7.0f} / {c.ceiling_eur:.0f} EUR "
              f"ceiling ({c.hours} h) -> capture {c.ratio:.1%}")


if __name__ == "__main__":
    _demo()
