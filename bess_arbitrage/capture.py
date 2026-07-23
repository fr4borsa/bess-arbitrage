"""Capture ratio: how much of the perfect-foresight ceiling a realistic
dispatch keeps. Three variants, all reusing the arbitrage LP day by day:

- rolling day-ahead: LP on each day's own (known) prices — the day-ahead
  auction view — with SOC carried across midnight. Isolates the horizon effect.
- persistence forecast: LP on YESTERDAY's prices used as today's forecast,
  schedule settled at TODAY's real prices. Standard industry baseline.
- isotonic forecast: today's prices predicted from residual load through an
  empirical step-wise supply curve (isotonic regression fit on a training
  window, Sunairio-style), settled at real prices. Explainable fundamentals
  baseline.

All dispatches are feasible for the full-period LP, so revenue <= ceiling
by construction; capture_ratio = revenue / ceiling on the same hours.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
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
    for prev, today in zip(days, days[1:], strict=False):
        n = min(len(prev), len(today))  # partial edge days: align by position
        forecast = pd.Series(prev.to_numpy()[:n], index=today.index[:n])
        plan = optimize(forecast, bat, soc0=soc0).dispatch
        revenue += float((today.to_numpy()[:n] * (plan["discharge"] - plan["charge"])).sum())
        soc0 = max(0.0, plan["soc"].iloc[-1])
        settled.append(today.iloc[:n])
    real = pd.concat(settled)
    return Capture(optimize(real, bat).revenue_eur, revenue, len(real))


def fit_supply_curve(stress: pd.Series, price: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Empirical supply curve: non-decreasing step fit price = f(stress) via PAVA.

    stress is any supply-demand tension proxy (here: residual load, MW). The
    monotonicity constraint is the techno-economic truth — more stress never
    means a lower price — and the step shape falls out of it, mirroring the
    merit order. Returns (sorted stress, fitted price) for _step_predict.
    """
    df = pd.concat([stress, price], axis=1, join="inner").dropna()
    if len(df) < 24:
        raise ValueError(f"too few aligned hours to fit: {len(df)}")
    order = np.argsort(df.iloc[:, 0].to_numpy(), kind="stable")
    xs = df.iloc[:, 0].to_numpy()[order]
    ys = df.iloc[:, 1].to_numpy()[order]
    # PAVA: merge adjacent blocks while decreasing, block value = weighted mean
    val, w, cnt = [], [], []
    for y in ys:
        val.append(float(y))
        w.append(1.0)
        cnt.append(1)
        while len(val) > 1 and val[-2] > val[-1]:
            y2, w2, c2 = val.pop(), w.pop(), cnt.pop()
            y1, w1, c1 = val.pop(), w.pop(), cnt.pop()
            val.append((y1 * w1 + y2 * w2) / (w1 + w2))
            w.append(w1 + w2)
            cnt.append(c1 + c2)
    return xs, np.repeat(val, cnt)


def _step_predict(curve: tuple[np.ndarray, np.ndarray], stress: pd.Series) -> pd.Series:
    """Read prices off the step curve (piecewise-constant, clamped at the ends)."""
    xs, fitted = curve
    i = np.clip(np.searchsorted(xs, stress.to_numpy(), side="right") - 1, 0, len(xs) - 1)
    return pd.Series(fitted[i], index=stress.index)


def isotonic_forecast(prices: pd.Series, stress: pd.Series, bat: Battery,
                      train_prices: pd.Series, train_stress: pd.Series) -> Capture:
    """Optimize on prices predicted from residual load via the supply curve
    fit on the training window, settle at real prices. SOC chained across days.

    ponytail: v1 uses the REALIZED residual load of the day (not a forecast),
    so it isolates the price-model error; swap in TSO day-ahead load/RES
    forecasts for a true ex-ante number. Single curve for the whole window:
    condition by gas-price regime / season when it plateaus.
    """
    curve = fit_supply_curve(train_stress, train_prices)
    aligned = pd.concat([prices, stress], axis=1, join="inner").dropna()
    revenue, soc0, settled = 0.0, 0.0, []
    for day in _days(aligned.iloc[:, 0]):
        pred = _step_predict(curve, aligned.iloc[:, 1].loc[day.index])
        plan = optimize(pred, bat, soc0=soc0).dispatch
        revenue += float((day.to_numpy() * (plan["discharge"] - plan["charge"])).sum())
        soc0 = max(0.0, plan["soc"].iloc[-1])
        settled.append(day)
    real = pd.concat(settled)
    return Capture(optimize(real, bat).revenue_eur, revenue, len(real))


def _demo() -> None:
    # ponytail: 6 synthetic days, valley/peak shape whose peak level AND hour
    # drift day to day — persistence keeps the shape but mistimes the peak.
    import numpy as np

    def day(pk: float, shift: int) -> list[float]:
        return list(np.roll([10] * 6 + [50] * 6 + [10] * 6 + [pk] * 6, shift))

    vals = np.concatenate([day(pk, sh) for pk, sh in
                           zip([200, 160, 240, 120, 220, 180], [0, 1, -1, 1, 0, -1],
                               strict=True)]).astype(float)
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

    # PAVA: violators pool to the weighted mean, mean is preserved
    xs, fit = fit_supply_curve(pd.Series([1.0, 2, 3] * 8), pd.Series([3.0, 1, 2] * 8))
    assert (np.diff(fit) >= 0).all() and abs(fit.mean() - 2.0) < 1e-9, fit

    # stress == price (a perfectly informative signal): the fitted curve is the
    # identity, predictions are exact, so isotonic must match rolling day-ahead
    iso = isotonic_forecast(px, px, bat, train_prices=px, train_stress=px)
    roll = rolling_day_ahead(px, bat)
    assert abs(iso.revenue_eur - roll.revenue_eur) < 1e-6, (iso, roll)
    print(f"demo ok: isotonic on perfect signal matches rolling ({iso.ratio:.1%})")


if __name__ == "__main__":
    _demo()
