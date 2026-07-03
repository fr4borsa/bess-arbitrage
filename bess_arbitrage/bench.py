"""Monthly DE revenue benchmark: day-ahead arbitrage alone vs stacked with
FCR / aFRR capacity, same battery, same window.

Methodology (v1 — honest floor):
- capacity revenue only, no aFRR activation energy (adds revenue in reality);
- FCR at the German clearing price (pay-as-cleared), aFRR at the MEAN accepted
  bid (pay-as-bid, conservative for a price-taker);
- capacity products are 4h blocks in German LOCAL time, so prices are
  converted to Europe/Berlin and only complete 24h days enter (the two DST
  days per year are skipped and reported);
- perfect foresight on all prices: this is the stacked revenue CEILING,
  consistent with the rest of the repo.

CLI:  uv run python -m bess_arbitrage.bench --start 2026-06-01 --end 2026-06-30
"""
from __future__ import annotations

import argparse
from collections.abc import Callable

import pandas as pd

from .balancing import fetch_products_de
from .model import Battery, optimize
from .prices import fetch_day_ahead


def run_bench(start: str, end: str, bat: Battery,
              fetch_px: Callable[..., pd.Series] = fetch_day_ahead,
              fetch_products: Callable[..., pd.DataFrame] = fetch_products_de,
              ) -> dict:
    """DA-only vs stacked ceiling on DE, per-MW-year normalized. Returns a dict
    with both revenues, the uplift, the per-market split and skipped days."""
    px = fetch_px("DE-LU", start, end).tz_convert("Europe/Berlin")
    days = [g for _, g in px.groupby(px.index.date)]
    full = [g for g in days if len(g) == 24]
    skipped = sorted({str(g.index[0].date()) for g in days if len(g) != 24})
    if not full:
        raise RuntimeError(f"no complete 24h local days in {start}..{end}")
    px_full = pd.concat(full)
    products = fetch_products(sorted(g.index[0].date() for g in full))

    da = optimize(px_full, bat)
    st = optimize(px_full, bat, products=products)
    per_mw_y = 8760 / da.hours / bat.power_mw
    return {
        "da_only_eur_mw_y": da.revenue_eur * per_mw_y,
        "stack_eur_mw_y": st.revenue_eur * per_mw_y,
        "uplift_pct": (st.revenue_eur / da.revenue_eur - 1) * 100 if da.revenue_eur else float("nan"),
        "split_eur": st.stack,
        "hours": da.hours,
        "skipped_days": skipped,
    }


def run_sequential(start: str, end: str, bat: Battery,
                   fetch_px: Callable[..., pd.Series] = fetch_day_ahead,
                   fetch_products: Callable[..., pd.DataFrame] = fetch_products_de,
                   ) -> dict:
    """Gate-by-gate operation with yesterday's information (the stack analogue
    of the persistence capture ratio):

    - plan day D with the co-optimizing LP run on D-1 prices (DA + capacity);
    - FCR: bid as a price-taker (0) -> always awarded, paid D's clearing price;
    - aFRR: bid yesterday's MEAN accepted price; awarded iff bid <= D's MAX
      accepted (the marginal bid), paid the bid (pay-as-bid);
    - dispatch D on its real DA prices with the awarded commitments as fixed
      constraints, SOC chained across days. Day 1 is skipped (no yesterday).

    Feasible by construction: the plan dispatch satisfies the same constraint
    set from the same soc0, and losing an award only relaxes it.
    """
    px = fetch_px("DE-LU", start, end).tz_convert("Europe/Berlin")
    days = [g for _, g in px.groupby(px.index.date) if len(g) == 24]
    if len(days) < 2:
        raise RuntimeError("need at least 2 complete days")
    dates = [g.index[0].date() for g in days]
    mean_all = fetch_products(dates, stat="mean")
    max_all = fetch_products(dates, stat="max")

    cols = ("fcr", "afrr_pos", "afrr_neg")
    soc = 0.0
    da_eur = fcr_eur = afrr_eur = 0.0
    for i in range(1, len(days)):
        yday_prod = mean_all.iloc[(i - 1) * 6: i * 6].reset_index(drop=True)
        today_mean = mean_all.iloc[i * 6: (i + 1) * 6].reset_index(drop=True)
        today_max = max_all.iloc[i * 6: (i + 1) * 6].reset_index(drop=True)
        plan = optimize(days[i - 1], bat, soc0=soc, products=yday_prod)
        mw = {c: [float(plan.dispatch[c].iloc[b * 4]) if c in plan.dispatch else 0.0
                  for b in range(6)] for c in cols}
        awarded = {c: list(mw[c]) for c in cols}
        for b in range(6):
            fcr_eur += mw["fcr"][b] * float(today_mean["fcr"].iloc[b])  # clearing, price-taker
            for c in ("afrr_pos", "afrr_neg"):
                bid = float(yday_prod[c].iloc[b])
                if bid <= float(today_max[c].iloc[b]) + 1e-9:
                    afrr_eur += awarded[c][b] * bid
                else:
                    awarded[c][b] = 0.0  # out of the auction: capacity freed for DA
        ex = optimize(days[i], bat, soc0=soc, committed=pd.DataFrame(awarded))
        da_eur += ex.revenue_eur
        soc = max(0.0, ex.dispatch["soc"].iloc[-1])

    settled = pd.concat(days[1:])
    ceiling = optimize(settled, bat, products=mean_all.iloc[6:].reset_index(drop=True))
    total = da_eur + fcr_eur + afrr_eur
    return {
        "seq_eur": total, "ceiling_eur": ceiling.revenue_eur,
        "capture": total / ceiling.revenue_eur if ceiling.revenue_eur else float("nan"),
        "split_eur": {"da": da_eur, "fcr": fcr_eur, "afrr": afrr_eur},
        "hours": len(settled),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Monthly DE benchmark: DA-only vs FCR/aFRR stack")
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--power", type=float, default=1.0)
    ap.add_argument("--duration", type=float, default=2.0)
    ap.add_argument("--rte", type=float, default=0.85)
    ap.add_argument("--cycles", type=float, default=1.5)
    ap.add_argument("--sequential", action="store_true",
                    help="also simulate gate-by-gate operation on yesterday's info")
    a = ap.parse_args()
    bat = Battery(a.power, a.duration, a.rte, max_cycles_per_day=a.cycles or None)

    if a.sequential:
        s = run_sequential(a.start, a.end, bat)
        split = {k: round(v) for k, v in s["split_eur"].items()}
        print(f"sequential DE {a.start}..{a.end} — {s['hours']} h settled (day 1 skipped)")
        print(f"  stacked ceiling : {s['ceiling_eur']:>10,.0f} EUR")
        print(f"  sequential ops  : {s['seq_eur']:>10,.0f} EUR  -> stack capture {s['capture']:.1%}")
        print(f"  split           : {split} EUR")
        return

    r = run_bench(a.start, a.end, bat)
    split = {k: round(v) for k, v in r["split_eur"].items()}
    print(f"bench DE {a.start}..{a.end} — {bat.power_mw:g} MW / {bat.duration_h:g}h, "
          f"RTE {bat.rte:.0%}, {a.cycles:g} cyc/d, {r['hours']} h")
    print(f"  DA-only ceiling : {r['da_only_eur_mw_y']:>10,.0f} EUR/MW/y")
    print(f"  stacked ceiling : {r['stack_eur_mw_y']:>10,.0f} EUR/MW/y  "
          f"(uplift {r['uplift_pct']:+.1f}%)")
    print(f"  split (window)  : {split} EUR")
    if r["skipped_days"]:
        print(f"  skipped days (not 24h local): {', '.join(r['skipped_days'])}")


def _demo() -> None:
    # ponytail: offline check — 2 synthetic days, arbitrage-worthless flat prices
    # but valuable FCR: the stack MUST pick up capacity revenue, DA-only ~0.
    idx = pd.date_range("2025-06-01", periods=48, freq="1h", tz="Europe/Berlin")
    flat = pd.Series([40.0] * 48, index=idx, name="fake")

    def fake_px(bzn: str, start: str, end: str) -> pd.Series:
        return flat

    def fake_products(days: list) -> pd.DataFrame:
        assert len(days) == 2, days
        return pd.DataFrame({"fcr": [100.0] * 12, "afrr_pos": [10.0] * 12,
                             "afrr_neg": [10.0] * 12})

    r = run_bench("2025-06-01", "2025-06-02", Battery(rte=1.0),
                  fetch_px=fake_px, fetch_products=fake_products)
    assert r["stack_eur_mw_y"] > r["da_only_eur_mw_y"] >= 0, r
    total = sum(r["split_eur"].values())
    assert abs(total * 8760 / r["hours"] - r["stack_eur_mw_y"]) < 1e-6, r
    print(f"demo ok: da {r['da_only_eur_mw_y']:.0f} -> stack {r['stack_eur_mw_y']:.0f} "
          f"EUR/MW/y, split {({k: round(v) for k, v in r['split_eur'].items()})}")

    # sequential: 3 identical days, mean < max -> plan is perfect and every bid
    # is awarded at the same price the ceiling uses => capture must be 1.0
    idx3 = pd.date_range("2025-06-01", periods=72, freq="1h", tz="Europe/Berlin")
    wave = pd.Series(([20.0] * 8 + [5.0] * 6 + [40.0] * 10) * 3, index=idx3)

    def px3(bzn, start, end):
        return wave

    def prod3(days, pause_s=0.3, stat="mean"):
        v = 10.0 if stat == "mean" else 12.0
        return pd.DataFrame({"fcr": [8.0] * 6 * len(days), "afrr_pos": [v] * 6 * len(days),
                             "afrr_neg": [v] * 6 * len(days)})

    s = run_sequential("2025-06-01", "2025-06-03", Battery(rte=1.0),
                       fetch_px=px3, fetch_products=prod3)
    assert abs(s["capture"] - 1.0) < 1e-6, s

    # award always lost (mean > max) -> zero aFRR money, DA + FCR still flow
    def prod_lost(days, pause_s=0.3, stat="mean"):
        v = 10.0 if stat == "mean" else 1.0
        return pd.DataFrame({"fcr": [8.0] * 6 * len(days), "afrr_pos": [v] * 6 * len(days),
                             "afrr_neg": [v] * 6 * len(days)})

    s2 = run_sequential("2025-06-01", "2025-06-03", Battery(rte=1.0),
                        fetch_px=px3, fetch_products=prod_lost)
    assert s2["split_eur"]["afrr"] == 0.0, s2      # every aFRR bid out of the auction
    assert s2["split_eur"]["da"] > 0, s2           # freed capacity flows back to DA
    assert s2["capture"] < 1.0, s2                 # ceiling still counts aFRR at mean
    print(f"demo ok: sequential capture {s['capture']:.1%} (identical days), "
          f"lost-award afrr {s2['split_eur']['afrr']:.0f} EUR")


if __name__ == "__main__":
    import sys
    _demo() if "--demo" in sys.argv else main()
