"""Bring-your-own-forecast scorer: the judge's front door.

Any hourly day-ahead price forecast — a CSV, a foundation model, a spreadsheet —
is scored with the same protocol as every baseline in this repo: per day, LP on
the forecast, settled at the REAL prices, SOC chained across midnight, capture =
revenue / perfect-foresight ceiling on the same hours. Alongside capture it
reports the mean intraday Spearman rank correlation (the dispatch-relevant
statistic: rank-corr predicts the capture delta, see docs/ai-layer.md) and the
mean daily RMSE (the classic statistic, for context).

Baselines (persistence, rolling day-ahead) are scored THROUGH THE SAME function
on the SAME settled hours as the candidate, so the comparison is fair by
construction, not by care.

Ex-ante contract (NOT verifiable by the scorer, stated so it can be held):
the forecast for day D must be produced using only information available
before D's day-ahead auction (~12:00 CET on D-1). A forecast that peeks at
D's prices scores as "rolling day-ahead" — that ratio is the tell.

API:  score(forecast, prices, bat) / compare(forecast, prices, bat)
CLI:  uv run python -m bess_arbitrage.score forecast.csv --bzn DE-LU
      CSV = timestamp column + value column (naive timestamps read as UTC).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .capture import Capture, _days
from .model import Battery, optimize


@dataclass
class Scorecard:
    capture: Capture
    rank_corr: float      # mean intraday Spearman(forecast, real) over settled days
    rmse_eur_mwh: float   # mean daily RMSE


def score(forecast: pd.Series, prices: pd.Series, bat: Battery) -> Scorecard:
    """LP on the forecast, settled at real prices, SOC chained. Only hours
    where forecast and prices overlap are settled; the ceiling uses the same
    hours, so capture <= 1 by construction."""
    aligned = pd.concat([prices.rename("px"), forecast.rename("fc")],
                        axis=1, join="inner").dropna()
    if aligned.empty:
        raise ValueError("forecast and prices share no timestamps")
    revenue, soc0, settled, dcorr, derr = 0.0, 0.0, [], [], []
    for day in _days(aligned["px"]):
        fc = aligned["fc"].loc[day.index]
        plan = optimize(fc, bat, soc0=soc0).dispatch
        revenue += float((day.to_numpy() * (plan["discharge"] - plan["charge"])).sum())
        soc0 = max(0.0, plan["soc"].iloc[-1])
        settled.append(day)
        if day.nunique() > 1 and fc.nunique() > 1:  # constant day: rank-corr undefined
            dcorr.append(float(np.corrcoef(day.rank(), fc.rank())[0, 1]))
        derr.append(float(np.sqrt(np.mean((fc.to_numpy() - day.to_numpy()) ** 2))))
    real = pd.concat(settled)
    cap = Capture(optimize(real, bat).revenue_eur, revenue, len(real))
    return Scorecard(cap, float(np.mean(dcorr)) if dcorr else float("nan"),
                     float(np.mean(derr)))


def compare(forecast: pd.Series, prices: pd.Series, bat: Battery) -> dict[str, Scorecard]:
    """Candidate vs the two reference baselines, all three restricted to the
    COMMON settled hours (candidate ∩ persistence — persistence loses day 1,
    so day 1 is excluded for everyone). rolling = forecast == real prices:
    its gap to 100% is the pure horizon effect, the candidate's headroom."""
    days = _days(prices)
    pers = pd.concat(
        [pd.Series(prev.to_numpy()[:min(len(prev), len(today))],
                   index=today.index[:min(len(prev), len(today))])
         for prev, today in zip(days, days[1:], strict=False)])
    common = forecast.dropna().index.intersection(prices.index).intersection(pers.index)
    if common.empty:
        raise ValueError("no common hours between forecast, prices and persistence baseline")
    sub = prices.loc[common]
    return {
        "candidate": score(forecast.loc[common], sub, bat),
        "rolling day-ahead": score(sub, sub, bat),
        "persistence": score(pers.loc[common], sub, bat),
    }


def read_forecast_csv(path: str) -> pd.Series:
    """First column = timestamps (naive -> UTC), second = forecast EUR/MWh.
    Header row optional."""
    df = pd.read_csv(path)
    try:  # headerless file: the "header" itself parses as a timestamp
        pd.to_datetime(df.columns[0])
        df = pd.read_csv(path, header=None)
    except (ValueError, TypeError):
        pass
    idx = pd.DatetimeIndex(pd.to_datetime(df.iloc[:, 0], utc=True))
    return pd.Series(df.iloc[:, 1].astype(float).to_numpy(), index=idx).sort_index()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Score a day-ahead price forecast in euros captured by a battery.")
    ap.add_argument("csv", help="forecast CSV: timestamp column + EUR/MWh column")
    ap.add_argument("--bzn", default="DE-LU")
    ap.add_argument("--start", default=None, help="default: first forecast day")
    ap.add_argument("--end", default=None, help="default: last forecast day")
    ap.add_argument("--power", type=float, default=1.0, help="MW")
    ap.add_argument("--duration", type=float, default=2.0, help="hours")
    ap.add_argument("--rte", type=float, default=0.85)
    ap.add_argument("--cycles", type=float, default=1.5, help="max cycles/day (0 = unlimited)")
    a = ap.parse_args()

    from pathlib import Path
    if not Path(a.csv).is_file():
        ap.error(f"file not found: {a.csv} — expected a CSV with a timestamp column "
                 "and a EUR/MWh forecast column (header optional)")
    from .prices import fetch_day_ahead
    fc = read_forecast_csv(a.csv)
    start = a.start or str(fc.index[0].date())
    end = a.end or str(fc.index[-1].date())
    px = fetch_day_ahead(a.bzn, start, end)
    bat = Battery(a.power, a.duration, a.rte, max_cycles_per_day=a.cycles or None)
    res = compare(fc, px, bat)

    hours = res["candidate"].capture.hours
    print(f"\nscore {a.bzn} {start}..{end} — {hours} h settled "
          f"(common hours: candidate ∩ persistence)")
    for name, s in res.items():
        c = s.capture
        print(f"  {name:18s}: {c.revenue_eur:>10,.0f} / {c.ceiling_eur:,.0f} EUR "
              f"-> capture {c.ratio:6.1%}   rank-corr {s.rank_corr:5.2f}   "
              f"RMSE {s.rmse_eur_mwh:5.1f} EUR/MWh")
    print("  reminder: the scorer cannot verify the ex-ante contract — a capture at "
          "rolling-day-ahead level usually means the forecast peeked at the answer.\n")


if __name__ == "__main__":
    main()
