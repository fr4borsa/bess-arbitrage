"""Behind-the-meter invariants (stage 1): synthetic, offline, fast."""
import numpy as np
import pandas as pd
import pytest

from bess_arbitrage.connection import PUE_MAX, cap_curve, dc_load, settle
from bess_arbitrage.model import Battery, Infeasible, optimize


@pytest.fixture
def px() -> pd.Series:
    idx = pd.date_range("2025-07-01", periods=48, freq="1h", tz="UTC")
    base = np.tile([10] * 6 + [50] * 6 + [10] * 6 + [200] * 6, 2)[:48].astype(float)
    return pd.Series(base, index=idx)


@pytest.fixture
def bat() -> Battery:
    return Battery(power_mw=1, duration_h=2, rte=1.0, max_cycles_per_day=1)


def test_no_cap_equals_ceiling(px, bat):
    flat = dc_load(px.index, 5 / PUE_MAX, "flat")
    ceil = optimize(px, bat).revenue_eur
    assert abs(optimize(px, bat, load=flat, cap_mw=6.0).revenue_eur - ceil) < 1e-6


def test_flat_load_at_peak_cap_cannot_charge(px, bat):
    flat = dc_load(px.index, 5 / PUE_MAX, "flat")
    r = optimize(px, bat, load=flat, cap_mw=5.0)
    assert abs(r.revenue_eur) < 1e-6
    assert (r.dispatch["grid"] <= 5 + 1e-6).all()


def test_cap_below_flat_peak_is_infeasible(px, bat):
    flat = dc_load(px.index, 5 / PUE_MAX, "flat")
    with pytest.raises(Infeasible):
        optimize(px, bat, load=flat, cap_mw=4.9)
    df = cap_curve(px, bat, flat, caps=[6.0, 5.0, 4.9])
    assert df["feasible"].tolist() == [True, True, False]
    assert abs(df["loss_frac"].iloc[0]) < 1e-9 and abs(df["loss_frac"].iloc[1] - 1) < 1e-9


def test_cooling_profile_shape(px):
    cool = dc_load(px.index, 1.0, "cooling")
    assert cool.max() <= PUE_MAX + 1e-9 and cool.min() < cool.max()
    assert cool.idxmax().hour == 14  # 15:00 CET
    year = pd.date_range("2025-01-01", periods=8760, freq="1h", tz="UTC")
    y = dc_load(year, 1.0, "cooling")
    assert y.idxmax().month == 7 and y.idxmin().month in (1, 12)


def test_grid_respects_cap_and_settle_matches_lp(px, bat):
    cool = dc_load(px.index, 5 / PUE_MAX, "cooling")
    cap = float(cool.max()) - 0.2
    r = optimize(px, bat, load=cool, cap_mw=cap)
    assert (r.dispatch["grid"].abs() <= cap + 1e-6).all()
    assert r.revenue_eur <= optimize(px, bat).revenue_eur + 1e-6
    s = settle(r.dispatch, px, cool, cap)
    assert abs(s["revenue_eur"] - r.revenue_eur) < 1e-6 and s["violation_hours"] == 0
    assert settle(r.dispatch, px, cool, cap - 0.4)["violation_hours"] > 0


def test_loss_monotone_in_cap(px, bat):
    cool = dc_load(px.index, 5 / PUE_MAX, "cooling")
    df = cap_curve(px, bat, cool)
    ok = df[df["feasible"]]
    assert (np.diff(ok["loss_frac"].to_numpy()) >= -1e-9).all()  # tighter cap never earns more


def test_cap_and_products_are_exclusive(px, bat):
    with pytest.raises(ValueError):
        optimize(px, bat, cap_mw=5.0, products=pd.DataFrame({"fcr": [0.0] * 12}))
