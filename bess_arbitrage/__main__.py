"""CLI: perfect-foresight BESS arbitrage revenue for a bidding zone.

    uv run python -m bess_arbitrage --bzn DE-LU --start 2025-01-01 --end 2025-12-31
"""
from __future__ import annotations

import argparse

from .model import Battery, optimize
from .prices import fetch_day_ahead


def main() -> None:
    ap = argparse.ArgumentParser(description="Perfect-foresight BESS arbitrage revenue (ceiling).")
    ap.add_argument("--bzn", default="DE-LU")
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--power", type=float, default=1.0, help="MW")
    ap.add_argument("--duration", type=float, default=2.0, help="hours")
    ap.add_argument("--rte", type=float, default=0.85)
    ap.add_argument("--capex", type=float, default=125.0, help="EUR/kWh")
    ap.add_argument("--cycles", type=float, default=1.5, help="max cycles/day (0 = unlimited)")
    ap.add_argument("--capture", action="store_true",
                    help="score rolling day-ahead and persistence-forecast dispatch vs the ceiling")
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args()

    px = fetch_day_ahead(a.bzn, a.start, a.end)
    bat = Battery(a.power, a.duration, a.rte, a.capex, a.cycles or None)
    res = optimize(px, bat)

    print(f"\n{a.bzn}  {a.start}..{a.end}   ({res.hours} h)")
    print(f"  price: mean {px.mean():.1f}  p5 {px.quantile(.05):.1f}  p95 {px.quantile(.95):.1f} EUR/MWh")
    print(f"  battery: {bat.power_mw} MW / {bat.duration_h} h ({bat.capacity_mwh} MWh), "
          f"RTE {bat.rte:.0%}, cap {a.cycles or 'inf'} cyc/d")
    print(f"  CEILING revenue: {res.revenue_per_mw_year:,.0f} EUR/MW/year  "
          f"(total {res.revenue_eur:,.0f} EUR)")
    print(f"  capex {bat.capex_eur:,.0f} EUR -> simple payback {res.simple_payback_years:.1f} y")
    print("  note: perfect-foresight = upper bound; real dispatch with forecasts earns less.")

    if a.capture:
        from .capture import persistence_forecast, rolling_day_ahead
        roll = rolling_day_ahead(px, bat)
        pers = persistence_forecast(px, bat)
        print("  capture vs ceiling:")
        print(f"    rolling day-ahead   : {roll.revenue_eur:,.0f} EUR -> {roll.ratio:.1%}")
        print(f"    persistence forecast: {pers.revenue_eur:,.0f} EUR -> {pers.ratio:.1%}"
              f"  (ceiling {pers.ceiling_eur:,.0f} EUR on same {pers.hours} h, day 1 skipped)")
    print()

    if a.plot:
        import matplotlib.pyplot as plt
        ax = px.plot(figsize=(12, 4), lw=0.5)
        ax.set_title(f"{a.bzn} day-ahead {a.start}..{a.end}")
        ax.set_ylabel("EUR/MWh")
        out = f"{a.bzn}_{a.start}_{a.end}.png"
        plt.tight_layout()
        plt.savefig(out, dpi=110)
        print(f"  saved {out}")


if __name__ == "__main__":
    main()
