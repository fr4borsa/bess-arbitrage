"""DE aFRR ENERGY market (activation/merit-order) data from regelleistung.net.

Same API as balancing.py (capacity/tender side); this module covers the ENERGY
side of aFRR: the merit order of activation bids and its daily summary.

energy-market-summaries reports the OFFERED merit order per quarter-hour, not
what was actually activated: meanEnergyPrice is inflated by bids parked at the
+-15000 EUR/MWh cap (used to price the residual/unmatched tail), so it is not
a realistic average activation price.

tenders/results/anonymous (market=ENERGY) is the underlying bid-level merit
order (~100k rows/day). Bids there are NOT sorted by activation order: rows
are sorted by |ENERGY_PRICE| ascending, ignoring ENERGY_PRICE_PAYMENT_DIRECTION.
Activation order (cheapest-for-the-TSO first) requires normalizing each bid to
the price the PROVIDER receives (GRID_TO_PROVIDER = positive, PROVIDER_TO_GRID
= provider pays = negative) and sorting ascending on that signed value -- this
holds for both POS and NEG products, since signed-price-received-by-provider
equals cost-to-the-system in both directions.
"""
from __future__ import annotations

import datetime as dt
import time

import pandas as pd
import requests

from .balancing import API, CACHE_DIR, HEADERS

DEFAULT_GRID = (0.02, 0.05, 0.10, 0.15, 0.25, 0.30, 0.50, 0.75, 1.0)


def _product_to_qh_direction(product: str) -> tuple[int, str]:
    direction, idx = product.split("_")
    return int(idx) - 1, ("pos" if direction == "POS" else "neg")


def _get_bytes(path: str, params: dict) -> bytes:
    """Like balancing._get but for binary (xlsx) responses, no disk cache:
    the ENERGY merit-order export is ~100k rows/day, too large to keep raw
    (fetch_afrr_mol_de caches its compact reduction instead)."""
    for attempt in range(5):
        r = requests.get(API + path, params=params, headers=HEADERS, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        break
    r.raise_for_status()
    return r.content


def fetch_afrr_energy_summary_de(day: dt.date) -> pd.DataFrame:
    """Daily aFRR ENERGY merit-order summary, 192 rows (96 qh x pos/neg).

    Columns: qh (0..95), direction (pos/neg), demand_mw, offered_mw,
    min_px, mean_px, max_px [EUR/MWh]. This is the OFFERED merit order, not
    activation: see module docstring for why mean_px is not a real average.
    """
    from .balancing import _get  # local import: avoid module-level private coupling
    params = f"?deliveryDate={day:%Y-%m-%d}&productType=aFRR"
    j = _get(f"/energy-market-summaries{params}", cacheable=day < dt.date.today())
    rows = []
    for r in j:
        qh, direction = _product_to_qh_direction(r["productName"])
        rows.append({
            "qh": qh,
            "direction": direction,
            "demand_mw": r["demand"],
            "offered_mw": r["offeredCapacity"],
            "min_px": r["minEnergyPrice"],
            "mean_px": r["meanEnergyPrice"],
            "max_px": r["maxEnergyPrice"],
        })
    return pd.DataFrame(rows).sort_values(["direction", "qh"]).reset_index(drop=True)


def fetch_afrr_mol_de(day: dt.date, grid: tuple = DEFAULT_GRID) -> pd.DataFrame:
    """Compact daily aFRR ENERGY merit-order curve, sampled at `grid` depths.

    Downloads the ~100k-row bid-level xlsx, normalizes each bid's price to
    EUR/MWh received by the provider (GRID_TO_PROVIDER positive,
    PROVIDER_TO_GRID negative), sorts ascending per (qh, direction) -- the true
    activation order -- and samples the price at each fraction of total
    allocated capacity in `grid`.

    Columns: qh, direction, depth_frac, price_eur_mwh, cum_mw. Cached as the
    compact result (not the raw xlsx) under .cache/regelleistung/, since only
    past days are stable.
    """
    cacheable = day < dt.date.today()
    cache_file = CACHE_DIR / f"mol_{day:%Y%m%d}_aFRR_ENERGY.parquet"
    if cacheable and cache_file.exists():
        return pd.read_parquet(cache_file)

    content = _get_bytes("/tenders/results/anonymous", {
        "deliveryDate": day.isoformat(), "productType": "aFRR",
        "market": "ENERGY", "exportFormat": "xlsx",
    })
    df = pd.read_excel(pd.io.common.BytesIO(content), engine="openpyxl")
    df = df[df["COUNTRY"] == "DE"]
    price = df["ENERGY_PRICE_[EUR/MWh]"]
    to_provider = df["ENERGY_PRICE_PAYMENT_DIRECTION"] == "GRID_TO_PROVIDER"
    df = df.assign(
        signed_px=price.where(to_provider, -price),
        qh_direction=df["PRODUCT"].map(_product_to_qh_direction),
    )
    df["qh"] = [q for q, _ in df["qh_direction"]]
    df["direction"] = [d for _, d in df["qh_direction"]]

    rows = []
    for (qh, direction), g in df.groupby(["qh", "direction"]):
        g = g.sort_values("signed_px")
        cum = g["ALLOCATED_CAPACITY_[MW]"].cumsum()
        total_mw = cum.iloc[-1]
        for frac in grid:
            idx = (cum >= frac * total_mw).idxmax()
            rows.append({
                "qh": qh, "direction": direction, "depth_frac": frac,
                "price_eur_mwh": g.loc[idx, "signed_px"], "cum_mw": cum.loc[idx],
            })
    out = pd.DataFrame(rows).sort_values(["direction", "qh", "depth_frac"]).reset_index(drop=True)

    if cacheable:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(cache_file)
    return out


def _demo() -> None:
    """Offline check: synthetic merit order, hand-verified sign/depth sampling."""
    synth = pd.DataFrame([
        # qh 0, pos: cheap GRID_TO_PROVIDER bids, one expensive PROVIDER_TO_GRID
        # bid mixed in raw (unsorted by activation order, like the real xlsx).
        {"PRODUCT": "POS_001", "COUNTRY": "DE", "ENERGY_PRICE_[EUR/MWh]": 100.0,
         "ENERGY_PRICE_PAYMENT_DIRECTION": "GRID_TO_PROVIDER", "ALLOCATED_CAPACITY_[MW]": 5},
        {"PRODUCT": "POS_001", "COUNTRY": "DE", "ENERGY_PRICE_[EUR/MWh]": 50.0,
         "ENERGY_PRICE_PAYMENT_DIRECTION": "PROVIDER_TO_GRID", "ALLOCATED_CAPACITY_[MW]": 5},
        {"PRODUCT": "POS_001", "COUNTRY": "DE", "ENERGY_PRICE_[EUR/MWh]": 15000.0,
         "ENERGY_PRICE_PAYMENT_DIRECTION": "GRID_TO_PROVIDER", "ALLOCATED_CAPACITY_[MW]": 90},
    ])
    price = synth["ENERGY_PRICE_[EUR/MWh]"]
    to_provider = synth["ENERGY_PRICE_PAYMENT_DIRECTION"] == "GRID_TO_PROVIDER"
    synth = synth.assign(signed_px=price.where(to_provider, -price))
    # activation order must be: -50 (provider pays 50) < 100 < 15000
    ordered = synth.sort_values("signed_px")["signed_px"].tolist()
    assert ordered == [-50.0, 100.0, 15000.0], ordered

    cum = synth.sort_values("signed_px")["ALLOCATED_CAPACITY_[MW]"].cumsum()
    total_mw = cum.iloc[-1]
    assert total_mw == 100
    # 5% depth -> still within first (cheapest) bid, 5 MW
    idx_5pct = (cum >= 0.05 * total_mw).idxmax()
    assert synth.loc[idx_5pct, "signed_px"] == -50.0
    # 100% depth -> last (most expensive) bid, the +15000 cap
    idx_100pct = (cum >= 1.0 * total_mw).idxmax()
    assert synth.loc[idx_100pct, "signed_px"] == 15000.0
    print("activation._demo: sign normalization + depth sampling OK")


if __name__ == "__main__":
    _demo()
    day = dt.date.today() - dt.timedelta(days=8)
    summary = fetch_afrr_energy_summary_de(day)
    mol = fetch_afrr_mol_de(day)
    print(f"\n{day} DE aFRR energy summary ({len(summary)} rows):")
    print(summary.head(6).to_string(index=False))
    print(f"\n{day} DE aFRR MOL, compact ({len(mol)} rows):")
    print(mol.head(len(DEFAULT_GRID)).to_string(index=False))


# ---------------------------------------------------------------------------
# v1 activation model: MOL-based, parametric depth
# ---------------------------------------------------------------------------

def activation_margin(mol: pd.DataFrame, px_day: pd.Series,
                      awarded_pos: list[float], awarded_neg: list[float],
                      bid_frac: float = 0.05, depth_frac: float = 0.15) -> dict:
    """Expected aFRR activation margin for one day, EUR.

    `depth_frac` plays a DOUBLE role, deliberately coupled: it is the average
    activated fraction of the merit order (duty: how much of the committed MW
    is actually called, time-averaged) AND the settlement depth (the marginal
    price the activation clears at, PICASSO-style). Expected energy per
    quarter-hour is therefore awarded_MW x 0.25h x depth_frac. The battery's
    own bid sits at `bid_frac` of the MOL and only earns when
    bid_frac <= depth_frac. SoC is assumed restored within the block at the
    day-ahead price.

    Per activated MWh the margin vs pure arbitrage is:
      POS (discharge): + cbmp_pos - DA   (sell at CBMP, buy back at DA)
      NEG (charge):    + cbmp_neg + DA   (receive cbmp_neg, may be negative,
                                          and resell the absorbed MWh at DA)

    mol: as returned by fetch_afrr_mol_de. px_day: 24 hourly DA prices, local
    time. awarded_*: aFRR MW per 4h block (6 values). depth_frac is UNKNOWN
    without activated-volume data (netztransparenz/ENTSO-E, token required) --
    treat it as a scenario knob, not a fact.
    """
    if not (mol["depth_frac"] == depth_frac).any():
        raise ValueError(f"depth_frac {depth_frac} not in MOL grid")
    activated = bid_frac <= depth_frac
    out = {"pos_eur": 0.0, "neg_eur": 0.0, "throughput_mwh": 0.0}
    if not activated:
        return out
    cbmp = mol[mol.depth_frac == depth_frac].set_index(["direction", "qh"]).price_eur_mwh
    for qh in range(96):
        h = qh // 4
        b = qh // 16
        da = float(px_day.iloc[h])
        e_pos = awarded_pos[b] * 0.25 * depth_frac  # expected MWh this quarter-hour
        e_neg = awarded_neg[b] * 0.25 * depth_frac
        if e_pos:
            out["pos_eur"] += e_pos * (float(cbmp.loc[("pos", qh)]) - da)
            out["throughput_mwh"] += e_pos
        if e_neg:
            out["neg_eur"] += e_neg * (float(cbmp.loc[("neg", qh)]) + da)
            out["throughput_mwh"] += e_neg
    return out


def sequential_activation_band(awards: dict, px: pd.Series,
                               bid_frac: float = 0.05,
                               depths: tuple = (0.05, 0.15, 0.30),
                               pause_s: float = 0.5) -> dict:
    """Activation-margin band on top of a sequential run.

    awards: {date -> {"afrr_pos": [6], "afrr_neg": [6]}} as returned by
    bench.run_sequential. px: hourly DA prices covering those days, local time.
    Returns {depth_frac -> {"uplift_eur", "throughput_mwh"}}. One MOL download
    per day on cold cache (~2-5 MB xlsx each): pause between days.
    """
    out = {d: {"uplift_eur": 0.0, "throughput_mwh": 0.0} for d in depths}
    for day, aw in awards.items():
        if not any(aw["afrr_pos"]) and not any(aw["afrr_neg"]):
            continue
        mol = fetch_afrr_mol_de(day)
        px_day = px[px.index.date == day]
        for d in depths:
            m = activation_margin(mol, px_day, aw["afrr_pos"], aw["afrr_neg"],
                                  bid_frac=bid_frac, depth_frac=d)
            out[d]["uplift_eur"] += m["pos_eur"] + m["neg_eur"]
            out[d]["throughput_mwh"] += m["throughput_mwh"]
        if pause_s:
            time.sleep(pause_s)
    return out
