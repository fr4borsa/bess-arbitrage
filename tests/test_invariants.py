"""LP invariants on synthetic data — offline, fast. These are the properties
that must hold no matter what the prices look like; if one breaks, the engine
is wrong, not the market.
"""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from bess_arbitrage.capture import (
    fit_supply_curve,
    isotonic_forecast,
    learned_forecast,
    persistence_forecast,
    rolling_day_ahead,
)
from bess_arbitrage.model import Battery, optimize


@pytest.fixture
def prices() -> pd.Series:
    # 6 synthetic days with a two-peak shape and day-to-day drift
    day = np.array([30, 25, 20, 15, 10, 12, 40, 80, 90, 60, 30, 10,
                    5, 8, 20, 45, 90, 140, 160, 120, 80, 60, 45, 35], dtype=float)
    px = np.concatenate([day * (1 + 0.1 * d) for d in range(6)])
    idx = pd.date_range("2025-03-01", periods=len(px), freq="1h", tz="UTC")
    return pd.Series(px, index=idx)


@pytest.fixture
def bat() -> Battery:
    return Battery(power_mw=1.0, duration_h=2.0, rte=0.85, max_cycles_per_day=1.5)


def test_dispatch_within_bounds(prices, bat):
    r = optimize(prices, bat)
    d = r.dispatch
    assert (d["soc"] >= -1e-6).all() and (d["soc"] <= bat.capacity_mwh + 1e-6).all()
    assert (d["charge"] >= -1e-6).all() and (d["charge"] <= bat.power_mw + 1e-6).all()
    assert (d["discharge"] >= -1e-6).all() and (d["discharge"] <= bat.power_mw + 1e-6).all()


def test_cycle_cap_respected(prices, bat):
    r = optimize(prices, bat)
    days = r.hours // 24
    assert r.dispatch["discharge"].sum() <= bat.max_cycles_per_day * bat.capacity_mwh * days + 1e-6


def test_capture_ratios_bounded(prices, bat):
    # Both variants are feasible for the whole-window LP => revenue <= ceiling.
    assert 0 < rolling_day_ahead(prices, bat).ratio <= 1 + 1e-9
    assert persistence_forecast(prices, bat).ratio <= 1 + 1e-9


def test_stack_never_below_da_only(prices, bat):
    products = pd.DataFrame({
        "fcr": [25.0] * 36, "afrr_pos": [8.0] * 36, "afrr_neg": [4.0] * 36,
    })
    da = optimize(prices, bat)
    stack = optimize(prices, bat, products=products)
    # Capacity prices are >= 0, so co-optimization can only add revenue.
    assert stack.revenue_eur >= da.revenue_eur - 1e-6
    assert abs(sum(stack.stack.values()) - stack.revenue_eur) < 1e-6


def test_more_cycles_never_earn_less(prices):
    tight = optimize(prices, Battery(max_cycles_per_day=1.0)).revenue_eur
    loose = optimize(prices, Battery(max_cycles_per_day=2.0)).revenue_eur
    assert loose >= tight - 1e-6


def test_isotonic_curve_and_capture(prices, bat):
    rng = np.random.default_rng(0)
    stress = pd.Series(rng.normal(50, 20, len(prices)), index=prices.index)
    xs, fit = fit_supply_curve(stress, prices)
    # the fit is a non-decreasing step function bounded by the observed prices
    assert (np.diff(fit) >= -1e-9).all()
    assert prices.min() - 1e-9 <= fit.min() and fit.max() <= prices.max() + 1e-9
    # noisy signal: still feasible for the full LP => ceiling dominates
    c = isotonic_forecast(prices, stress, bat, train_prices=prices, train_stress=stress)
    assert c.ratio <= 1 + 1e-9
    # perfectly informative signal (stress == price): matches rolling day-ahead
    perfect = isotonic_forecast(prices, prices, bat, train_prices=prices, train_stress=prices)
    assert abs(perfect.revenue_eur - rolling_day_ahead(prices, bat).revenue_eur) < 1e-6


def test_learned_forecast_bounded_and_exact_on_repeats(bat):
    day = np.array([30, 25, 20, 15, 10, 12, 40, 80, 90, 60, 30, 10,
                    5, 8, 20, 45, 90, 140, 160, 120, 80, 60, 45, 35], dtype=float)
    # 12 drifting days: still feasible for the full LP => ceiling dominates
    px = np.concatenate([day * (1 + 0.05 * d) for d in range(12)])
    idx = pd.date_range("2025-03-01", periods=len(px), freq="1h", tz="UTC")
    drifting = pd.Series(px, index=idx)
    assert 0 < learned_forecast(drifting, bat).ratio <= 1 + 1e-9
    # 12 identical days: lags predict exactly => matches rolling day-ahead
    flat = pd.Series(np.tile(day, 12), index=idx)
    lrn = learned_forecast(flat, bat)
    roll = rolling_day_ahead(flat[flat.index >= idx[8 * 24]], bat)
    assert abs(lrn.revenue_eur - roll.revenue_eur) < 1e-6


def test_degradation_reduces_net_and_throughput(prices, bat):
    base = optimize(prices, bat)
    deg = optimize(prices, replace(bat, cycle_cost_eur_per_mwh=8.0))
    # pricing wear can only lower net revenue and throughput, never raise them
    assert deg.revenue_eur <= base.revenue_eur + 1e-6
    assert deg.dispatch["discharge"].sum() <= base.dispatch["discharge"].sum() + 1e-6
    # book-keeping: net = gross - wear, wear >= 0, and it's genuinely off by default
    assert deg.degradation_eur >= 0
    assert abs(deg.revenue_eur + deg.degradation_eur - deg.gross_revenue_eur) < 1e-6
    assert base.degradation_eur == 0.0
