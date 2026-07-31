"""Score interface invariants on synthetic data — offline, fast. The judge must
agree with the existing capture harness wherever they measure the same thing."""
import numpy as np
import pandas as pd
import pytest

from bess_arbitrage.capture import persistence_forecast, rolling_day_ahead
from bess_arbitrage.model import Battery
from bess_arbitrage.score import compare, read_forecast_csv, score


@pytest.fixture
def prices() -> pd.Series:
    day = np.array([30, 25, 20, 15, 10, 12, 40, 80, 90, 60, 30, 10,
                    5, 8, 20, 45, 90, 140, 160, 120, 80, 60, 45, 35], dtype=float)
    px = np.concatenate([day * (1 + 0.1 * d) for d in range(6)])
    idx = pd.date_range("2025-03-01", periods=len(px), freq="1h", tz="UTC")
    return pd.Series(px, index=idx)


@pytest.fixture
def bat() -> Battery:
    return Battery(power_mw=1.0, duration_h=2.0, rte=0.85, max_cycles_per_day=1.5)


def test_perfect_forecast_matches_rolling(prices, bat):
    s = score(prices, prices, bat)
    roll = rolling_day_ahead(prices, bat)
    assert abs(s.capture.revenue_eur - roll.revenue_eur) < 1e-6
    assert s.rank_corr == pytest.approx(1.0)
    assert s.rmse_eur_mwh == pytest.approx(0.0)


def test_capture_bounded_by_ceiling(prices, bat):
    rng = np.random.default_rng(0)
    noisy = prices + pd.Series(rng.normal(0, 30, len(prices)), index=prices.index)
    s = score(noisy, prices, bat)
    assert 0 < s.capture.revenue_eur <= s.capture.ceiling_eur + 1e-6
    assert -1 <= s.rank_corr <= 1


def test_compare_same_hours_and_matches_capture(prices, bat):
    res = compare(prices, prices, bat)
    hours = {s.capture.hours for s in res.values()}
    assert hours == {len(prices) - 24}  # day 1 dropped for everyone
    # persistence through the scorer == the capture-harness persistence
    pers = persistence_forecast(prices, bat)
    assert abs(res["persistence"].capture.revenue_eur - pers.revenue_eur) < 1e-6
    assert abs(res["persistence"].capture.ceiling_eur - pers.ceiling_eur) < 1e-6
    # candidate == real prices -> identical to the rolling baseline
    assert abs(res["candidate"].capture.revenue_eur
               - res["rolling day-ahead"].capture.revenue_eur) < 1e-6


def test_anticorrelated_forecast_scores_low(prices, bat):
    s = score(-prices, prices, bat)
    assert s.rank_corr == pytest.approx(-1.0)
    assert s.capture.revenue_eur < score(prices, prices, bat).capture.revenue_eur


def test_partial_overlap_settles_common_hours_only(prices, bat):
    s = score(prices.iloc[24:72], prices, bat)
    assert s.capture.hours == 48


def test_read_forecast_csv_roundtrip(tmp_path, prices):
    p = tmp_path / "fc.csv"
    prices.rename("forecast").to_csv(p, header=True)
    fc = read_forecast_csv(str(p))
    assert np.allclose(fc.to_numpy(), prices.to_numpy())
    assert (fc.index == prices.index).all()
    # headerless variant
    p2 = tmp_path / "fc2.csv"
    prices.to_csv(p2, header=False)
    fc2 = read_forecast_csv(str(p2))
    assert np.allclose(fc2.to_numpy(), prices.to_numpy())
