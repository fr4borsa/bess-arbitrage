"""CLI: perfect-foresight BESS arbitrage revenue for a bidding zone.

    uv run python -m bess_arbitrage --bzn DE-LU --start 2025-01-01 --end 2025-12-31
"""
from __future__ import annotations

import argparse
import math

from .model import CAPEX_TURNKEY_EUR_KWH, Battery, optimize
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
    ap.add_argument("--cycle-cost", type=float, default=0.0,
                    help="EUR/MWh discharged degradation cost (0 = off; ~8 for merchant LFP)")
    ap.add_argument("--capture", action="store_true",
                    help="score rolling day-ahead and persistence-forecast dispatch vs the ceiling")
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args()

    px = fetch_day_ahead(a.bzn, a.start, a.end)
    bat = Battery(a.power, a.duration, a.rte, a.capex, a.cycles or None,
                  cycle_cost_eur_per_mwh=a.cycle_cost or None)
    res = optimize(px, bat)

    print(f"\n{a.bzn}  {a.start}..{a.end}   ({res.hours} h)")
    print(f"  price: mean {px.mean():.1f}  p5 {px.quantile(.05):.1f}"
          f"  p95 {px.quantile(.95):.1f} EUR/MWh")
    print(f"  battery: {bat.power_mw} MW / {bat.duration_h} h ({bat.capacity_mwh} MWh), "
          f"RTE {bat.rte:.0%}, cap {a.cycles or 'inf'} cyc/d")
    tag = "NET (post-wear)" if bat.cycle_cost_eur_per_mwh else "CEILING"
    print(f"  {tag} revenue: {res.revenue_per_mw_year:,.0f} EUR/MW/year  "
          f"(total {res.revenue_eur:,.0f} EUR)")
    if bat.cycle_cost_eur_per_mwh:
        print(f"    gross {res.gross_revenue_eur:,.0f} - wear {res.degradation_eur:,.0f} "
              f"@ {bat.cycle_cost_eur_per_mwh:g}/MWh = net {res.revenue_eur:,.0f} EUR")
    print(f"  payback band: {res.payback_years(a.capex):.1f} y (equipment {a.capex:g}/kWh) "
          f".. {res.payback_years(CAPEX_TURNKEY_EUR_KWH):.1f} y "
          f"(turnkey {CAPEX_TURNKEY_EUR_KWH:g}/kWh)")
    irr = res.irr()
    irr_s = f"{irr:.0%}" if not math.isnan(irr) else "n/a (never breaks even)"
    print(f"  investment (turnkey, 15y, 7% WACC, 2% opex, 1.5%/y fade): "
          f"NPV {res.npv():,.0f} EUR, IRR {irr_s} (merchant hurdle ~10%)")
    print("  note: perfect-foresight = upper bound; real dispatch with forecasts earns less.")

    if a.capture:
        from .capture import (
            isotonic_forecast,
            learned_forecast,
            persistence_forecast,
            rolling_day_ahead,
        )
        from .prices import fetch_residual_load, fetch_residual_load_forecast
        roll = rolling_day_ahead(px, bat)
        pers = persistence_forecast(px, bat)
        print("  capture vs ceiling:")
        print(f"    rolling day-ahead   : {roll.revenue_eur:,.0f} EUR -> {roll.ratio:.1%}")
        print(f"    persistence forecast: {pers.revenue_eur:,.0f} EUR -> {pers.ratio:.1%}"
              f"  (ceiling {pers.ceiling_eur:,.0f} EUR on same {pers.hours} h, day 1 skipped)")
        lrn = learned_forecast(px, bat)
        print(f"    learned linear      : {lrn.revenue_eur:,.0f} EUR -> {lrn.ratio:.1%}"
              f"  (per-hour lag-1/lag-7 lstsq, 28d window, {lrn.hours} h settled)")
        # supply curve trained on the year before the window, evaluated in it
        t0, t1 = f"{int(a.start[:4]) - 1}{a.start[4:]}", f"{int(a.end[:4]) - 1}{a.end[4:]}"
        train_px = fetch_day_ahead(a.bzn, t0, t1)
        train_rl = fetch_residual_load(a.bzn, t0, t1)
        iso = isotonic_forecast(px, fetch_residual_load(a.bzn, a.start, a.end), bat,
                                train_prices=train_px, train_stress=train_rl)
        print(f"    isotonic supply crv : {iso.revenue_eur:,.0f} EUR -> {iso.ratio:.1%}"
              f"  (residual-load curve fit on {t0[:4]}, realized residual load)")
        iso_x = isotonic_forecast(px, fetch_residual_load_forecast(a.bzn, a.start, a.end), bat,
                                  train_prices=train_px, train_stress=train_rl)
        print(f"    isotonic EX-ANTE    : {iso_x.revenue_eur:,.0f} EUR -> {iso_x.ratio:.1%}"
              f"  (same curve, TSO day-ahead load/RES forecasts — a real strategy)")
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
