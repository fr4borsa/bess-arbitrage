"""Insight layer: turns model outputs into the headline numbers and sentences
served by both the Streamlit UI and the monthly report. Pure functions, no I/O:
callers fetch, these compute.
"""
from __future__ import annotations

import pandas as pd

from .model import Battery, optimize


def day_stack(px_day: pd.Series, products_day: pd.DataFrame, bat: Battery) -> dict:
    """One real day, twice: DA-only vs co-optimized stack. The numbers behind
    'yesterday a battery earned X' and the day-replay view."""
    da = optimize(px_day, bat)
    st = optimize(px_day, bat, products=products_day)
    return {
        "date": str(px_day.index[0].date()),
        "da_eur": da.revenue_eur,
        "stack_eur": st.revenue_eur,
        "uplift_pct": (st.revenue_eur / da.revenue_eur - 1) * 100 if da.revenue_eur > 0 else float("nan"),
        "split_eur": st.stack,
        "dispatch": st.dispatch,          # hourly, incl. fcr/afrr MW columns
        "dispatch_da": da.dispatch,
    }


def atlas_headlines(df: pd.DataFrame, ref: str = "DE-LU") -> list[str]:
    """Auto-generated one-liners from an atlas ranking (as returned by
    run_atlas: zone / ceiling_eur_mw_y / price_mean, capture_* optional)."""
    out: list[str] = []
    if df.empty:
        return out
    d = df.sort_values("ceiling_eur_mw_y", ascending=False).reset_index(drop=True)
    top = d.iloc[0]
    if ref in set(d.zone) and top.zone != ref:
        ref_rev = float(d.loc[d.zone == ref, "ceiling_eur_mw_y"].iloc[0])
        out.append(f"{top.zone} leads at {top.ceiling_eur_mw_y / 1e3:,.0f}k €/MW/y — "
                   f"{(top.ceiling_eur_mw_y / ref_rev - 1) * 100:+.0f}% vs {ref}. "
                   f"Batteries earn the spread, not the price level.")
    else:
        out.append(f"{top.zone} leads at {top.ceiling_eur_mw_y / 1e3:,.0f}k €/MW/y.")
    priciest = d.loc[d.price_mean.idxmax()]
    if priciest.zone != top.zone:
        rank = int(d.index[d.zone == priciest.zone][0]) + 1
        out.append(f"Highest average price ≠ best battery zone: {priciest.zone} averages "
                   f"{priciest.price_mean:.0f} €/MWh but ranks #{rank} — flat days pay nothing.")
    if "capture_persistence" in d and d.capture_persistence.notna().all():
        out.append(f"A naive forecast (yesterday = tomorrow) keeps "
                   f"{d.capture_persistence.min():.0%}–{d.capture_persistence.max():.0%} "
                   f"of the ceiling depending on the zone: the value of forecasting, in euros.")
    return out


def monthly_spread(px: pd.Series) -> pd.DataFrame:
    """Average daily evening-peak minus midday-trough spread, by month —
    the widening-duck-curve trend behind all storage value."""
    h = px.index.hour
    evening = px[(h >= 17) & (h <= 21)].resample("1D").max()
    midday = px[(h >= 10) & (h <= 15)].resample("1D").min()
    daily = (evening - midday).dropna()
    out = daily.resample("MS").mean().to_frame("spread_eur")
    out["days"] = daily.resample("MS").count()
    return out[out.days >= 15].drop(columns="days")  # partial months mislead


def _demo() -> None:
    # ponytail: offline check on synthetic data — headlines must fire and the
    # spread trend must recover a constructed widening.
    import numpy as np
    idx = pd.date_range("2025-01-01", periods=24 * 60, freq="1h", tz="Europe/Berlin")
    grow = 1 + idx.month / 12.0
    day_shape = np.array([50] * 10 + [10] * 6 + [50] * 1 + [150] * 5 + [50] * 2)
    px = pd.Series(np.tile(day_shape, 60) * np.repeat(grow[::24], 24), index=idx)

    sp = monthly_spread(px)
    assert len(sp) == 2 and sp.spread_eur.iloc[1] > sp.spread_eur.iloc[0], sp

    atlas = pd.DataFrame({
        "zone": ["HU", "DE-LU", "NO1"],
        "ceiling_eur_mw_y": [156_000.0, 126_000.0, 40_000.0],
        "price_mean": [106.0, 94.0, 120.0],
        "capture_rolling": [.985, .978, .99],
        "capture_persistence": [.886, .898, .93],
    })
    hl = atlas_headlines(atlas)
    assert len(hl) == 3 and "HU" in hl[0] and "+24%" in hl[0], hl
    assert "NO1" in hl[1], hl

    day = px.iloc[:24]
    prod = pd.DataFrame({"fcr": [30.0] * 6, "afrr_pos": [15.0] * 6, "afrr_neg": [5.0] * 6})
    ds = day_stack(day, prod, Battery(rte=1.0))
    assert ds["stack_eur"] >= ds["da_eur"] > 0, ds
    assert abs(sum(ds["split_eur"].values()) - ds["stack_eur"]) < 1e-6, ds
    print(f"demo ok: {len(hl)} headlines · spread {sp.spread_eur.iloc[0]:.0f}→"
          f"{sp.spread_eur.iloc[1]:.0f} € · day {ds['da_eur']:.0f}→{ds['stack_eur']:.0f} €")
    for s in hl:
        print("  ·", s)


if __name__ == "__main__":
    _demo()
