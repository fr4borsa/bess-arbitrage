"""Stage 1 of the BESS x data-center thesis: the battery that buys the grid connection.

A firm site load (a data center) sits behind a grid connection of cap_mw. The
battery can shave the load's peaks (buying connection MW the site would
otherwise have to request) and, with whatever headroom is left, still do
arbitrage. This module answers, at perfect foresight:

    how many MW of connection does a given battery buy, and how much
    arbitrage revenue does buying them cost?

Two sides are kept apart on purpose, so stage 2 (dispatch without foresight)
does not have to redo the plumbing:
  * what the dispatcher KNOWS  -> `optimize(..., load=, cap_mw=)` plans on it;
  * what actually HAPPENS      -> `settle()` scores a plan on realized data.
At stage 1 the two coincide (perfect foresight, declared).

Load profiles are NOT invented per zone: two declared shapes, flat and
cooling-peaked, with the PUE band from Ren, Islam, Wierman (arXiv 2606.00457,
2026): hourly PUE of a highly-optimized dry-cooled AI data center between
~1.0-1.25 over the year, peak 1.35 in a Central-European climate vs 1.10 with
evaporative assistance. See experiments/PROTOCOL-connection-cap.md.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .model import Battery, Infeasible, optimize

PUE_MIN = 1.10  # evaporative-assisted / cool-season floor (Ren et al. 2026, [8])
PUE_MAX = 1.35  # dry-cooled summer-afternoon peak, Central Europe (Ren et al. 2026, [8])


def dc_load(index: pd.DatetimeIndex, p_it_mw: float, profile: str = "flat",
            pue_min: float = PUE_MIN, pue_max: float = PUE_MAX,
            local_offset_h: int = 1) -> pd.Series:
    """Hourly site load [MW] of a data center with flat IT power p_it_mw.

    flat    : PUE = pue_max all year (peak-designed, the conservative sizing —
              and the profile Czyzak used in PyPSA). Load == peak every hour.
    cooling : PUE = pue_min + (pue_max - pue_min) * season * diurnal, with
              season = cos-shaped 0..1 peaking on 15 July, diurnal = cos-shaped
              0..1 peaking at 15:00 local (UTC + local_offset_h; CET for every
              zone — one hour of phase is immaterial for a cosine). Winter
              nights sit at pue_min, summer afternoons at pue_max. Declared
              synthetic shape; the BAND is sourced, the cosines are ours.
    """
    if profile == "flat":
        return pd.Series(p_it_mw * pue_max, index=index, name="load_mw")
    if profile != "cooling":
        raise ValueError(f"unknown profile {profile!r}: flat | cooling")
    doy = index.dayofyear.to_numpy() + index.hour.to_numpy() / 24
    hour = (index.hour.to_numpy() + local_offset_h) % 24
    season = (1 + np.cos(2 * math.pi * (doy - 196) / 365.25)) / 2   # 196 = 15 July
    diurnal = (1 + np.cos(2 * math.pi * (hour - 15) / 24)) / 2      # 15:00 local
    pue = pue_min + (pue_max - pue_min) * season * diurnal
    return pd.Series(p_it_mw * pue, index=index, name="load_mw")


def default_caps(peak_mw: float, bat: Battery, below: int = 10) -> list[float]:
    """Cap grid in units of battery power: from peak + P_bat (battery adds its
    full power to the connection request, no constraint binds) down through
    peak (battery buys 0 MW) to peak - P_bat (battery buys its full power)."""
    above = [1.0, 0.75, 0.5, 0.25]
    steps = above + [-k / below for k in range(0, below + 1)]
    return [peak_mw + k * bat.power_mw for k in steps]


def cap_curve(prices: pd.Series, bat: Battery, load: pd.Series,
              caps: list[float] | None = None) -> pd.DataFrame:
    """The stage-1 curve: for each connection cap, arbitrage revenue kept vs the
    unconstrained ceiling and MW of connection bought (peak load - cap).

    Infeasible caps (the battery cannot keep the firm load under the cap) are
    kept as rows with feasible=False and NaN revenue — the curve's end is a
    result, not an error.
    """
    peak = float(load.max())
    caps = default_caps(peak, bat) if caps is None else caps
    ceiling = optimize(prices, bat).revenue_eur
    per_mw_y = 8760 / len(prices) / bat.power_mw
    rows = []
    for c in caps:
        row = {"cap_mw": c, "mw_bought": peak - c, "mw_bought_per_pbat": (peak - c) / bat.power_mw,
               "feasible": True, "revenue_eur": math.nan, "loss_frac": math.nan,
               "loss_eur_mw_y": math.nan, "peak_grid_mw": math.nan}
        try:
            r = optimize(prices, bat, load=load, cap_mw=c)
        except Infeasible:
            row["feasible"] = False
        else:
            row["revenue_eur"] = r.revenue_eur
            row["loss_frac"] = 1 - r.revenue_eur / ceiling if ceiling > 0 else math.nan
            row["loss_eur_mw_y"] = (ceiling - r.revenue_eur) * per_mw_y
            row["peak_grid_mw"] = float(r.dispatch["grid"].max())
        rows.append(row)
    df = pd.DataFrame(rows)
    df.attrs["ceiling_eur"] = ceiling
    df.attrs["peak_load_mw"] = peak
    return df


def settle(dispatch: pd.DataFrame, prices: pd.Series, load: pd.Series,
           cap_mw: float) -> dict:
    """Score a PLAN (charge/discharge columns) on what actually happened.

    Stage 1: realized == planned, so this reproduces the LP objective and zero
    violation. Stage 2 will pass a plan made on forecasts and realized
    prices/load here — the cap violation is the number that decides whether
    the battery really bought the connection.
    """
    grid = load.to_numpy() + dispatch["charge"].to_numpy() - dispatch["discharge"].to_numpy()
    over = np.clip(np.abs(grid) - cap_mw, 0, None)
    return {
        "revenue_eur": float((prices.to_numpy()
                              * (dispatch["discharge"].to_numpy()
                                 - dispatch["charge"].to_numpy())).sum()),
        "peak_grid_mw": float(np.abs(grid).max()),
        "violation_hours": int((over > 1e-6).sum()),
        "violation_mwh": float(over.sum()),
    }


def _demo() -> None:
    # ponytail: synthetic 2 days, 1 MW / 2 h battery behind a 5 MW site.
    idx = pd.date_range("2025-07-01", periods=48, freq="1h", tz="UTC")
    base = np.tile([10] * 6 + [50] * 6 + [10] * 6 + [200] * 6, 2)[:48].astype(float)
    px = pd.Series(base, index=idx)
    bat = Battery(power_mw=1, duration_h=2, rte=1.0, max_cycles_per_day=1)
    ceil = optimize(px, bat).revenue_eur

    # flat load: cap = peak + P_bat -> nothing binds, revenue == ceiling;
    # cap = peak -> the battery can never charge, revenue 0 (Czyzak's "no surplus")
    flat = dc_load(idx, 5 / PUE_MAX, "flat")
    assert abs(flat.max() - 5) < 1e-9
    r_free = optimize(px, bat, load=flat, cap_mw=5 + 1)
    assert abs(r_free.revenue_eur - ceil) < 1e-6, (r_free.revenue_eur, ceil)
    r_tight = optimize(px, bat, load=flat, cap_mw=5.0)
    assert abs(r_tight.revenue_eur) < 1e-6
    assert (r_tight.dispatch["grid"] <= 5 + 1e-6).all()
    # cap below a flat peak: infeasible, reported not raised by cap_curve
    df = cap_curve(px, bat, flat, caps=[6.0, 5.5, 5.0, 4.9])
    assert df["feasible"].tolist() == [True, True, True, False]
    assert abs(df["loss_frac"].iloc[0]) < 1e-9 and abs(df["loss_frac"].iloc[2] - 1) < 1e-9

    # cooling profile: peak == p_it * PUE_MAX only in a July afternoon; here the
    # 2 days ARE July, so the peak sits at 15:00 local and the battery can buy MW
    cool = dc_load(idx, 5 / PUE_MAX, "cooling")
    assert cool.max() <= 5 + 1e-9 and cool.min() < cool.max()
    assert cool.idxmax().hour == 14  # 15:00 CET == 14:00 UTC
    r_buy = optimize(px, bat, load=cool, cap_mw=cool.max() - 0.2)  # buys 0.2 MW
    assert (r_buy.dispatch["grid"] <= cool.max() - 0.2 + 1e-6).all()
    assert r_buy.revenue_eur <= ceil + 1e-6
    # settle on the plan itself reproduces the LP and shows zero violation
    s = settle(r_buy.dispatch, px, cool, cool.max() - 0.2)
    assert abs(s["revenue_eur"] - r_buy.revenue_eur) < 1e-6 and s["violation_hours"] == 0
    # settle on the SAME plan under a tighter cap must show violations
    s2 = settle(r_buy.dispatch, px, cool, cool.max() - 0.6)
    assert s2["violation_hours"] > 0
    print(f"demo ok: ceiling {ceil:.0f}, cap=peak -> {r_tight.revenue_eur:.0f}, "
          f"buy 0.2 MW -> {r_buy.revenue_eur:.0f} EUR ({1 - r_buy.revenue_eur / ceil:.0%} lost)")


if __name__ == "__main__":
    _demo()
