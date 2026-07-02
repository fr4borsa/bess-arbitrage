"""Day-ahead spot prices from energy-charts.info (Fraunhofer ISE, no API key)."""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import pandas as pd
import requests

API = "https://api.energy-charts.info/price"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "energy-charts"


def fetch_day_ahead(bzn: str = "DE-LU", start: str = "2025-01-01", end: str = "2025-12-31") -> pd.Series:
    """Hourly day-ahead price [EUR/MWh] for a bidding zone, indexed by timestamp (UTC).

    bzn: bidding zone, e.g. DE-LU, BE, NL, FR. start/end: ISO dates inclusive.
    Past windows (end < today) are cached as raw JSON under .cache/energy-charts/.
    """
    past = end < dt.date.today().isoformat()
    cache_file = CACHE_DIR / bzn / f"{start}_{end}.json"
    j = None
    if past and cache_file.exists():
        try:
            j = json.loads(cache_file.read_text())
        except (json.JSONDecodeError, OSError):
            j = None
    if j is None:
        # energy-charts rate-limits bursts: 429, but under load also transient 5xx.
        # Back off and retry on both; only non-transient errors surface immediately.
        for attempt in range(5):
            r = requests.get(API, params={"bzn": bzn, "start": start, "end": end}, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** attempt)  # 1,2,4,8,16s
                continue
            break
        r.raise_for_status()
        j = r.json()
        if past:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(j))
    if "price" not in j or not j["price"]:
        raise RuntimeError(f"no price data for {bzn} {start}..{end}: {j.get('license_info', j)}")
    idx = pd.to_datetime(j["unix_seconds"], unit="s", utc=True)
    s = pd.Series(j["price"], index=idx, name=f"{bzn}_da_eur_mwh")
    # energy-charts may return 15-min granularity for recent data; resample to hourly mean.
    return s.resample("1h").mean().dropna()


if __name__ == "__main__":
    # ponytail: smoke check against live API — last 7 days of DE-LU
    end = dt.date.today()
    start = end - dt.timedelta(days=7)
    px = fetch_day_ahead("DE-LU", start.isoformat(), end.isoformat())
    assert len(px) > 100, f"expected >100 hourly points, got {len(px)}"
    assert -500 < px.min() and px.max() < 5000, f"prices out of sane range: {px.min()}..{px.max()}"
    print(f"DE-LU {start}..{end}: {len(px)} h, mean {px.mean():.1f} EUR/MWh, "
          f"min {px.min():.1f}, max {px.max():.1f}")
