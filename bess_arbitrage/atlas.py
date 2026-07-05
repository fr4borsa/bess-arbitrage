"""Capture-ratio atlas: the same LP engine across EU bidding zones.

For each zone, same battery and same window: perfect-foresight ceiling,
rolling day-ahead capture, persistence-forecast capture. The ranking answers
two questions at once: WHERE a battery earns most, and HOW MUCH of that
ceiling a realistic dispatch actually keeps.

CLI:  uv run python -m bess_arbitrage.atlas --start 2026-01-01 --end 2026-06-30
"""
from __future__ import annotations

import argparse
import time
from collections.abc import Callable

import pandas as pd

from .capture import persistence_forecast, rolling_day_ahead
from .model import Battery, optimize
from .prices import fetch_day_ahead

# Bidding zone -> (lat, lon) centroid, for the map and the atlas.
# Codes as accepted by the energy-charts.info API; unknown/failing zones are skipped.
ZONES: dict[str, tuple[float, float]] = {
    "DE-LU": (51.0, 9.0), "FR": (46.6, 2.4), "BE": (50.6, 4.7),
    "NL": (52.1, 5.3), "AT": (47.6, 14.1), "CH": (46.8, 8.2),
    "ES": (40.2, -3.7), "PT": (39.6, -8.0), "PL": (52.1, 19.4),
    "CZ": (49.8, 15.5), "SK": (48.7, 19.7), "HU": (47.2, 19.5),
    "SI": (46.1, 14.8), "HR": (45.5, 16.0), "RO": (45.9, 24.9),
    "BG": (42.7, 25.5), "GR": (39.0, 22.0),
    "IT-North": (45.5, 9.5), "IT-Centre-North": (43.4, 11.5),
    "IT-Centre-South": (41.9, 13.8), "IT-South": (40.6, 16.0),
    "IT-Sicily": (37.5, 14.2), "IT-Sardinia": (40.0, 9.0),
    "DK1": (56.0, 9.2), "DK2": (55.5, 11.8),
    "NO1": (60.1, 10.8), "NO2": (58.3, 7.5), "NO5": (60.5, 6.0),
    "SE2": (63.2, 16.0), "SE3": (59.5, 15.0), "SE4": (56.5, 14.5),
    "FI": (62.9, 26.0), "EE": (58.7, 25.5), "LT": (55.2, 23.9), "LV": (56.9, 24.9),
}


def zone_metrics(px: pd.Series, bat: Battery, capture: bool = True) -> dict:
    """Atlas metrics for one zone's hourly price series."""
    ceil = optimize(px, bat)
    per_mw_y = 8760 / ceil.hours / bat.power_mw
    row = {
        "ceiling_eur_mw_y": ceil.revenue_eur * per_mw_y,
        "payback_y": ceil.simple_payback_years,
        "price_mean": float(px.mean()),
        "hours": ceil.hours,
    }
    if capture:
        row["capture_rolling"] = rolling_day_ahead(px, bat).ratio
        row["capture_persistence"] = persistence_forecast(px, bat).ratio
    return row


def run_atlas(start: str, end: str, bat: Battery,
              zones: dict[str, tuple[float, float]] = ZONES,
              capture: bool = True,
              fetch: Callable[..., pd.Series] = fetch_day_ahead,
              pause_s: float = 0.8) -> tuple[pd.DataFrame, list[str]]:
    """Run the atlas over the given zones. Returns (dataframe, skipped_zones).

    Zones with no data in the window are skipped, never fatal. pause_s keeps
    the energy-charts rate limiter happy on cold caches.
    """
    rows, skipped = [], []
    for z, (lat, lon) in zones.items():
        try:
            px = fetch(z, start, end)
            rows.append({"zone": z, "lat": lat, "lon": lon} | zone_metrics(px, bat, capture))
        except Exception:
            skipped.append(z)
        if pause_s:
            time.sleep(pause_s)
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("ceiling_eur_mw_y", ascending=False).reset_index(drop=True)
    return df, skipped


def main() -> None:
    ap = argparse.ArgumentParser(description="Capture-ratio atlas across EU bidding zones")
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--zones", nargs="*", default=None, help="subset, e.g. DE-LU FR CH")
    ap.add_argument("--power", type=float, default=1.0)
    ap.add_argument("--duration", type=float, default=2.0)
    ap.add_argument("--rte", type=float, default=0.85)
    ap.add_argument("--cycles", type=float, default=1.5)
    ap.add_argument("--no-capture", action="store_true", help="ceiling only (much faster)")
    ap.add_argument("--csv", default=None, help="also write the table to this CSV path")
    a = ap.parse_args()

    zones = {z: ZONES[z] for z in a.zones} if a.zones else ZONES
    bat = Battery(a.power, a.duration, a.rte, max_cycles_per_day=a.cycles or None)
    df, skipped = run_atlas(a.start, a.end, bat, zones, capture=not a.no_capture)
    if df.empty:
        raise SystemExit("no zone returned data for this window")

    out = df.drop(columns=["lat", "lon"]).copy()
    out["ceiling_eur_mw_y"] = out["ceiling_eur_mw_y"].round(0)
    for c in ("capture_rolling", "capture_persistence"):
        if c in out:
            out[c] = (out[c] * 100).round(1)
    print(f"atlas {a.start}..{a.end} — {bat.power_mw:g} MW / {bat.duration_h:g}h, "
          f"RTE {bat.rte:.0%}, {a.cycles:g} cyc/d")
    print(out.to_string(index=False))
    if skipped:
        print(f"skipped (no data): {', '.join(skipped)}")
    if a.csv:
        df.to_csv(a.csv, index=False)
        print(f"csv -> {a.csv}")


def _demo() -> None:
    # ponytail: offline check — 2 fake zones, 4 synthetic days; the volatile zone
    # must rank first and every capture must be within (0, 1].
    import numpy as np

    def fake_fetch(bzn: str, start: str, end: str) -> pd.Series:
        spread = {"VOLATILE": 300.0, "FLAT": 40.0}[bzn]
        day = [10.0] * 6 + [50.0] * 6 + [10.0] * 6 + [spread] * 6
        idx = pd.date_range("2025-01-01", periods=96, freq="1h", tz="UTC")
        return pd.Series(np.tile(day, 4), index=idx)

    zones = {"VOLATILE": (50.0, 10.0), "FLAT": (45.0, 5.0)}
    df, skipped = run_atlas("2025-01-01", "2025-01-04", Battery(), zones,
                            fetch=fake_fetch, pause_s=0.0)
    assert not skipped, skipped
    assert list(df["zone"]) == ["VOLATILE", "FLAT"], list(df["zone"])
    for c in ("capture_rolling", "capture_persistence"):
        assert ((df[c] > 0) & (df[c] <= 1 + 1e-9)).all(), df[c]
    print("demo ok:")
    print(df[["zone", "ceiling_eur_mw_y", "capture_rolling", "capture_persistence"]]
          .to_string(index=False))


if __name__ == "__main__":
    import sys
    _demo() if "--demo" in sys.argv else main()
