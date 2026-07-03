"""DE balancing capacity prices (FCR + aFRR) from regelleistung.net.

CRDS v2 — the datacenter app's own API: public JSON, no key. FCR clears
pay-as-cleared: `local-marginal-prices` is EUR/MW **per 4h block** for the
German control block. aFRR capacity is pay-as-bid: we take the MEAN accepted
bid price (EUR/MW/h, x4 -> per block) as a conservative revenue estimate.
Products are 4h blocks in German local time (Europe/Berlin).
"""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import pandas as pd
import requests

API = "https://www.regelleistung.net/apps/crds/api/v2"
DE_EIC = "10Y1001A1001A82H"  # Germany in local-marginal-prices (demands uses another EIC)
HEADERS = {"User-Agent": "Mozilla/5.0 (bess-arbitrage)"}
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "regelleistung"
BLOCKS = ("00_04", "04_08", "08_12", "12_16", "16_20", "20_24")


def _get(path: str, cacheable: bool) -> list:
    cache_file = CACHE_DIR / (path.strip("/").replace("/", "_") + ".json")
    if cacheable and cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    for attempt in range(5):
        r = requests.get(API + path, headers=HEADERS, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        break
    r.raise_for_status()
    j = r.json()
    if cacheable:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(j))
    return j


def fetch_fcr_de(day: dt.date) -> list[float]:
    """FCR clearing price for Germany, EUR/MW per 4h block (6 values).

    ponytail: always tender iteration _D1; rare _D2 re-tenders are ignored.
    """
    j = _get(f"/tenders/PRL_{day:%Y%m%d}_D1/local-marginal-prices",
             cacheable=day < dt.date.today())
    px = {r["productName"]: float(r["localMarginalCapacityPrice"])
          for r in j if r["controlBlock"] == DE_EIC}
    return [px[f"NEGPOS_{b}"] for b in BLOCKS]


def fetch_afrr_de(day: dt.date, stat: str = "mean") -> tuple[list[float], list[float]]:
    """aFRR capacity price DE (pos, neg), EUR/MW per 4h block.

    Pay-as-bid market: `mean` accepted price is a conservative estimate of what
    a price-taker earns; `max` is the marginal accepted bid (the award threshold
    for a bidding simulation). The API reports EUR/MW/h, we return per-block (x4).
    """
    j = _get(f"/tenders/SRL_{day:%Y%m%d}_D1/aggregated-results/de",
             cacheable=day < dt.date.today())
    px = {}
    for r in j:
        f = r["fourHourResult"]
        if f.get("capacityPrice"):
            px[f["productName"]] = float(f["capacityPrice"][stat]) * 4
    return ([px[f"POS_{b}"] for b in BLOCKS], [px[f"NEG_{b}"] for b in BLOCKS])


def fetch_products_de(days: list[dt.date], pause_s: float = 0.3,
                      stat: str = "mean") -> pd.DataFrame:
    """Products frame for optimize(): 6 rows per day (fcr, afrr_pos, afrr_neg),
    EUR/MW per 4h block, in day order — block i of day d = local hours 4i..4i+3.
    stat picks the aFRR statistic (mean/max/min); FCR is always the clearing price."""
    rows = []
    for d in days:
        fcr = fetch_fcr_de(d)
        pos, neg = fetch_afrr_de(d, stat)
        rows += [{"fcr": fcr[i], "afrr_pos": pos[i], "afrr_neg": neg[i]}
                 for i in range(len(BLOCKS))]
        if pause_s:
            time.sleep(pause_s)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    # ponytail: live smoke check — one settled day, 8 days ago
    day = dt.date.today() - dt.timedelta(days=8)
    fcr = fetch_fcr_de(day)
    pos, neg = fetch_afrr_de(day)
    for name, v in (("fcr", fcr), ("afrr_pos", pos), ("afrr_neg", neg)):
        assert len(v) == 6, (name, v)
        assert all(0 <= x < 50_000 for x in v), (name, v)
    print(f"{day} DE  fcr {fcr}  afrr_pos {[round(x, 1) for x in pos]}  "
          f"afrr_neg {[round(x, 1) for x in neg]}  [EUR/MW/4h-block]")
