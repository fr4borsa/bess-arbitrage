"""Activation-model invariants on synthetic merit orders — offline."""
import pandas as pd
import pytest

from bess_arbitrage.activation import activation_margin


@pytest.fixture
def flat_mol() -> pd.DataFrame:
    # cbmp: pos = 200, neg = -50 at 15% depth, every quarter-hour
    rows = [{"qh": q, "direction": d, "depth_frac": 0.15,
             "price_eur_mwh": 200.0 if d == "pos" else -50.0, "cum_mw": 100.0}
            for q in range(96) for d in ("pos", "neg")]
    return pd.DataFrame(rows)


@pytest.fixture
def px_flat() -> pd.Series:
    return pd.Series([100.0] * 24)


def test_margin_arithmetic(flat_mol, px_flat):
    r = activation_margin(flat_mol, px_flat, [1.0] * 6, [1.0] * 6)
    # expected energy = 24 MWh x duty(0.15) per direction
    # pos: 3.6 MWh x (200 - 100); neg: 3.6 MWh x (-50 + 100)
    assert r["pos_eur"] == pytest.approx(360.0)
    assert r["neg_eur"] == pytest.approx(180.0)
    assert r["throughput_mwh"] == pytest.approx(7.2)


def test_bid_beyond_depth_never_activates(flat_mol, px_flat):
    r = activation_margin(flat_mol, px_flat, [1.0] * 6, [1.0] * 6,
                          bid_frac=0.5, depth_frac=0.15)
    assert r["pos_eur"] == r["neg_eur"] == r["throughput_mwh"] == 0.0


def test_margin_linear_in_awarded_mw(flat_mol, px_flat):
    r1 = activation_margin(flat_mol, px_flat, [1.0] * 6, [0.0] * 6)
    r2 = activation_margin(flat_mol, px_flat, [2.0] * 6, [0.0] * 6)
    assert r2["pos_eur"] == pytest.approx(2 * r1["pos_eur"])


def test_unknown_depth_raises(flat_mol, px_flat):
    with pytest.raises(ValueError):
        activation_margin(flat_mol, px_flat, [1.0] * 6, [1.0] * 6, depth_frac=0.33)
