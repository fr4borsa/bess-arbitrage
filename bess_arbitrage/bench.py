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


def main() -> None:
    ap = argparse.ArgumentParser(description="Monthly DE benchmark: DA-only vs FCR/aFRR stack")
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--power", type=float, default=1.0)
    ap.add_argument("--duration", type=float, default=2.0)
    ap.add_argument("--rte", type=float, default=0.85)
    ap.add_argument("--cycles", type=float, default=1.5)
    a = ap.parse_args()
    bat = Battery(a.power, a.duration, a.rte, max_cycles_per_day=a.cycles or None)

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


if __name__ == "__main__":
    import sys
    _demo() if "--demo" in sys.argv else main()
