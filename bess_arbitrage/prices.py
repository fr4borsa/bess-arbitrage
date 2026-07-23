"""Day-ahead spot prices from energy-charts.info (Fraunhofer ISE, no API key)."""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import pandas as pd
import requests

API = "https://api.energy-charts.info/price"
PUBLIC_POWER_API = "https://api.energy-charts.info/public_power"
FORECAST_API = "https://api.energy-charts.info/public_power_forecast"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "energy-charts"


def _get_json(url: str, params: dict, cache_file: Path, end: str) -> dict:
    """GET with retry/backoff; past windows (end < today) cached as raw JSON."""
    past = end < dt.date.today().isoformat()
    if past and cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    # energy-charts rate-limits bursts: 429, but under load also transient 5xx.
    # Back off and retry on both; only non-transient errors surface immediately.
    for attempt in range(5):
        r = requests.get(url, params=params, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** attempt)  # 1,2,4,8,16s
            continue
        break
    r.raise_for_status()
    j = r.json()
    if past:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(j))
    return j


def fetch_day_ahead(bzn: str = "DE-LU", start: str = "2025-01-01",
                    end: str = "2025-12-31") -> pd.Series:
    """Hourly day-ahead price [EUR/MWh] for a bidding zone, indexed by timestamp (UTC).

    bzn: bidding zone, e.g. DE-LU, BE, NL, FR. start/end: ISO dates inclusive.
    Past windows (end < today) are cached as raw JSON under .cache/energy-charts/.
    """
    j = _get_json(API, {"bzn": bzn, "start": start, "end": end},
                  CACHE_DIR / bzn / f"{start}_{end}.json", end)
    if "price" not in j or not j["price"]:
        raise RuntimeError(f"no price data for {bzn} {start}..{end}: {j.get('license_info', j)}")
    idx = pd.to_datetime(j["unix_seconds"], unit="s", utc=True)
    s = pd.Series(j["price"], index=idx, name=f"{bzn}_da_eur_mwh")
    # energy-charts may return 15-min granularity for recent data; resample to hourly mean.
    return s.resample("1h").mean().dropna()


def fetch_residual_load(bzn: str = "DE-LU", start: str = "2025-01-01",
                        end: str = "2025-12-31") -> pd.Series:
    """Hourly residual load [MW] (load - wind - solar) from public_power, UTC-indexed.

    The endpoint is per country, not per bidding zone: DE-LU -> "de".
    """
    country = bzn.split("-")[0].lower()
    j = _get_json(PUBLIC_POWER_API, {"country": country, "start": start, "end": end},
                  CACHE_DIR / country / f"rl_{start}_{end}.json", end)
    rl = next((p["data"] for p in j.get("production_types", ())
               if p["name"] == "Residual load"), None)
    if not rl:
        raise RuntimeError(f"no residual-load data for {country} {start}..{end}")
    idx = pd.to_datetime(j["unix_seconds"], unit="s", utc=True)
    s = pd.Series(rl, index=idx, name=f"{country}_residual_load_mw", dtype=float)
    return s.resample("1h").mean().dropna()


def fetch_residual_load_forecast(bzn: str = "DE-LU", start: str = "2025-01-01",
                                 end: str = "2025-12-31") -> pd.Series:
    """Hourly EX-ANTE residual load [MW]: TSO day-ahead load forecast minus
    day-ahead solar and wind forecasts. All series are published before the
    day-ahead auction closes, so a dispatch driven by this is a true ex-ante
    strategy — unlike fetch_residual_load, which is the realized outcome.

    Offshore wind is optional (some countries have none); the other three
    series are required. Per country, like public_power: DE-LU -> "de".
    """
    country = bzn.split("-")[0].lower()
    parts: dict[str, pd.Series] = {}
    for pt in ("load", "solar", "wind_onshore", "wind_offshore"):
        j = _get_json(FORECAST_API,
                      {"country": country, "production_type": pt,
                       "forecast_type": "day-ahead", "start": start, "end": end},
                      CACHE_DIR / country / f"fc_{pt}_{start}_{end}.json", end)
        vals = j.get("forecast_values") or []
        if not vals:
            if pt == "wind_offshore":
                continue  # no offshore fleet is normal; missing load/solar/wind is not
            raise RuntimeError(f"no day-ahead {pt} forecast for {country} {start}..{end}")
        idx = pd.to_datetime(j["unix_seconds"], unit="s", utc=True)
        parts[pt] = pd.Series(vals, index=idx, dtype=float).resample("1h").mean()
    s = parts["load"] - parts["solar"] - parts["wind_onshore"]
    if "wind_offshore" in parts:
        s = s - parts["wind_offshore"]
    return s.dropna().rename(f"{country}_residual_load_forecast_mw")


if __name__ == "__main__":
    # ponytail: smoke check against live API — last 7 days of DE-LU
    end = dt.date.today()
    start = end - dt.timedelta(days=7)
    px = fetch_day_ahead("DE-LU", start.isoformat(), end.isoformat())
    assert len(px) > 100, f"expected >100 hourly points, got {len(px)}"
    assert px.min() > -500 and px.max() < 5000, f"prices out of sane range: {px.min()}..{px.max()}"
    print(f"DE-LU {start}..{end}: {len(px)} h, mean {px.mean():.1f} EUR/MWh, "
          f"min {px.min():.1f}, max {px.max():.1f}")
    fc = fetch_residual_load_forecast("DE-LU", start.isoformat(), end.isoformat())
    rl = fetch_residual_load("DE-LU", start.isoformat(), end.isoformat())
    both = pd.concat([fc, rl], axis=1, join="inner").dropna()
    mape = (both.iloc[:, 0] - both.iloc[:, 1]).abs().mean() / both.iloc[:, 1].abs().mean()
    assert len(both) > 100, f"expected >100 overlapping hours, got {len(both)}"
    assert mape < 0.25, f"forecast vs realized residual load off by {mape:.0%}"
    print(f"residual-load day-ahead forecast: {len(fc)} h, "
          f"vs realized MAPE-ish {mape:.1%} on {len(both)} overlapping h")
