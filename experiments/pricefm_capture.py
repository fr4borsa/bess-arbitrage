"""PriceFM zero-shot su H1 2026, protocollo PROTOCOL-pricefm.md (ac5e893).

Fasi: (1) input 15-min DE-LU/FR da energy-charts; (2) sanity gate vs FINAL.csv
su dicembre 2025 (r > 0.99 per serie, pena stop); (3) scaler dal LORO codice
fittati sul LORO train fold-3; (4) predizione mediana, de-normalizzata,
resample orario; (5) CSV + bilancia (score.compare).

Setup (una tantum, fuori dal repo — dipendenze pesanti solo per esperimento):
  git clone https://github.com/runyao-yu/PriceFM.git $PRICEFM_DIR
  curl -L -o $PRICEFM_DIR/FINAL.csv \
      https://huggingface.co/datasets/RunyaoYu/PriceFM/resolve/main/FINAL.csv

Run (dalla root del repo bess-arbitrage):
  PRICEFM_DIR=/percorso/PriceFM PYTHONPATH=. uv run \
      --with tensorflow==2.18.0 --with scikit-learn \
      python experiments/pricefm_capture.py
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PRICEFM_DIR = Path(os.environ.get("PRICEFM_DIR", "PriceFM-upstream")).resolve()
sys.path.insert(0, str(PRICEFM_DIR))

from PriceFM.data import (  # noqa: E402
    make_rolling_window_samples,
    pack_dataset,
    read_dataset,
    scale_dataframe_per_country,
    separate_countries,
    split_dataframe,
)
from PriceFM.evaluation import inverse_scale_y_pred  # noqa: E402
from PriceFM.model import load_model  # noqa: E402

from bess_arbitrage.model import Battery  # noqa: E402
from bess_arbitrage.prices import (  # noqa: E402
    API,
    CACHE_DIR,
    FORECAST_API,
    _get_json,
    fetch_day_ahead,  # noqa: E402
)
from bess_arbitrage.score import compare  # noqa: E402

ZONES = {"DE-LU": "DE_LU", "FR": "FR"}
COUNTRIES = [
    "AT", "BE", "BG", "CZ", "DE_LU", "DK_1", "DK_2",
    "EE", "ES", "FI", "FR", "GR", "HR", "HU",
    "IT_CALA", "IT_CNOR", "IT_CSUD", "IT_NORD", "IT_SARD", "IT_SICI", "IT_SUD",
    "LT", "LV", "NL", "NO_1", "NO_2", "NO_3", "NO_4", "NO_5",
    "PL", "PT", "RO", "SE_1", "SE_2", "SE_3", "SE_4", "SI", "SK",
]
LABEL, LAG_F, LEAD_F = "price", ["price", "load", "solar", "wind"], ["load", "solar", "wind"]
FEATURES = sorted((set(LAG_F) | set(LEAD_F)) - {LABEL})
QUANTILES = [0.10, 0.25, 0.45, 0.50, 0.55, 0.75, 0.90]
MED = QUANTILES.index(0.50)
START, END = "2025-12-01", "2026-06-30"  # dicembre = mese di overlap per il gate


def fetch_raw_15min(bzn: str) -> pd.DataFrame:
    """price + forecast TSO load/solar/wind (on+off) alla granularita' nativa."""
    z = ZONES[bzn]
    country = bzn.split("-")[0].lower()
    j = _get_json(API, {"bzn": bzn, "start": START, "end": END},
                  CACHE_DIR / bzn / f"raw_{START}_{END}.json", END)
    idx = pd.to_datetime(j["unix_seconds"], unit="s", utc=True)
    out = {f"{z}-price": pd.Series(j["price"], index=idx, dtype=float)}
    parts = {}
    for pt in ("load", "solar", "wind_onshore", "wind_offshore"):
        try:
            jf = _get_json(FORECAST_API,
                           {"country": country, "production_type": pt,
                            "forecast_type": "day-ahead", "start": START, "end": END},
                           CACHE_DIR / country / f"rawfc_{pt}_{START}_{END}.json", END)
        except Exception:
            if pt == "wind_offshore":
                continue
            raise
        vals = jf.get("forecast_values") or []
        if not vals:
            if pt == "wind_offshore":
                continue
            raise RuntimeError(f"no {pt} forecast {country}")
        fidx = pd.to_datetime(jf["unix_seconds"], unit="s", utc=True)
        parts[pt] = pd.Series(vals, index=fidx, dtype=float)
    out[f"{z}-load"] = parts["load"]
    out[f"{z}-solar"] = parts["solar"]
    out[f"{z}-wind"] = parts["wind_onshore"]
    if "wind_offshore" in parts:
        out[f"{z}-wind_off"] = parts["wind_offshore"]
    df = pd.concat(out, axis=1)
    grid = pd.date_range(df.index.min(), df.index.max(), freq="15min", tz="UTC")
    df = df.reindex(grid)
    # fedelta' al loro preprocessing: i TRATTI a valori orari (blocchi da 4
    # ripetuti sulla griglia 15-min) vanno interpolati linearmente tra le
    # ancore HH:00, come in FINAL.csv (verificato su FR-solar dic 2025).
    # Rilevazione PER GIORNO sui blocchi orari non-zero: una serie puo'
    # diventare nativa 15-min a meta' finestra.
    assert grid[0].minute == 0  # blocchi da 4 allineati alle ore
    for col in df.columns:
        if col.endswith("-price"):  # i prezzi sono nativi 15-min, mai toccarli
            continue
        s = df[col]
        v = s.to_numpy()
        fix = np.zeros(len(s), bool)
        for d0 in range(0, len(v) - 95, 96):
            seg = v[d0:d0 + 96].reshape(24, 4)
            nz = ~np.isnan(seg).any(1) & (np.nanmax(np.abs(seg), axis=1) > 0)
            if nz.sum() >= 4 and float((seg[nz].std(1) == 0).mean()) > 0.9:
                fix[d0:d0 + 96] = True
        if fix.any():
            keep = s.copy()
            keep[fix & (s.index.minute != 0)] = np.nan
            df[col] = keep.interpolate(method="time", limit=4)
            print(f"  {col}: interpolati {int(fix.sum())}/{len(v)} step "
                  "(tratti a valori orari)", flush=True)
    df = df.ffill(limit=3)
    return df


print("== fase 1: input 15-min ==", flush=True)
mine = pd.concat([fetch_raw_15min(b) for b in ZONES], axis=1)
final = read_dataset(str(PRICEFM_DIR / "FINAL.csv"))

# composizione wind per zona: onshore-only vs onshore+offshore — si sceglie
# sul mese di overlap (dic 2025) la variante col mean-ratio piu' vicino a 1
dec = slice("2025-12-01", "2025-12-31")
for z in ZONES.values():
    if f"{z}-wind_off" not in mine.columns:
        continue
    on = mine.loc[dec, f"{z}-wind"]
    tot = on.add(mine.loc[dec, f"{z}-wind_off"], fill_value=0.0)
    ref = final.loc[dec, f"{z}-wind"]
    r_on = abs(float(on.mean() / ref.mean()) - 1)
    r_tot = abs(float(tot.mean() / ref.mean()) - 1)
    use_tot = r_tot < r_on
    print(f"  {z}-wind: |ratio-1| onshore={r_on:.3f} on+off={r_tot:.3f} "
          f"-> uso {'on+off' if use_tot else 'onshore'}", flush=True)
    if use_tot:
        mine[f"{z}-wind"] = mine[f"{z}-wind"].add(mine[f"{z}-wind_off"], fill_value=0.0)
    mine = mine.drop(columns=f"{z}-wind_off")
print(mine.describe().loc[["count", "mean"]].T, flush=True)

print("\n== fase 2: sanity gate su dicembre 2025 vs FINAL.csv ==", flush=True)
gate_ok = True
for z in ZONES.values():
    for f in ("price", "load", "solar", "wind"):
        col = f"{z}-{f}"
        a = mine.loc[dec, col].dropna()
        b = final.loc[dec, col].dropna()
        ab = pd.concat([a, b], axis=1, join="inner").dropna()
        r = float(np.corrcoef(ab.iloc[:, 0], ab.iloc[:, 1])[0, 1])
        ratio = float(ab.iloc[:, 0].mean() / ab.iloc[:, 1].mean())
        status = "ok" if r > 0.99 else "FAIL"
        gate_ok &= r > 0.99
        print(f"  {col:12s} r={r:.4f}  mean-ratio={ratio:.3f}  n={len(ab)}  {status}",
              flush=True)
if not gate_ok:
    sys.exit("SANITY GATE FALLITO — stop, indagare prima di ogni run H1 (da protocollo).")

print("\n== fase 3: scaler dal loro fold-3 train ==", flush=True)
tr, va, te = split_dataframe(final, "2022-01-01", "2025-05-01", "2025-05-01",
                             "2025-09-01", "2025-09-01", "2026-01-01")
targets = list(ZONES.values())
h1 = mine.loc["2026-01-01":]
_, _, h1_s, x_scalers, y_scalers = scale_dataframe_per_country(
    tr, va, h1, targets, FEATURES, LABEL)

print("== fase 4: finestre, predizione, mediana ==", flush=True)
model = load_model(str(PRICEFM_DIR / "Model" / "PhaseI_best.keras"))
h1_sep = separate_countries(h1_s, targets, FEATURES, LABEL)
bat = Battery()
for bzn, z in ZONES.items():
    X_lag, X_lead, Y, t = make_rolling_window_samples(
        h1_sep[z], z, LAG_F, LEAD_F, LABEL, 96, 96)
    ok = ~(np.isnan(X_lag).any((1, 2)) | np.isnan(X_lead).any((1, 2)) | np.isnan(Y).any(1))
    X_lag, X_lead, Y = X_lag[ok], X_lead[ok], Y[ok]
    anchors = [a for a, k in zip(t, ok, strict=True) if k]
    print(f"{bzn}: {len(anchors)} giorni eleggibili ({int((~ok).sum())} scartati)", flush=True)

    # pack: zona target reale, altre 37 a zero (gate isolation verificata)
    zero = {"X_lag": np.zeros_like(X_lag), "X_lead": np.zeros_like(X_lead),
            "Y": np.zeros_like(Y), "t": anchors}
    split = {c: ({"X_lag": X_lag, "X_lead": X_lead, "Y": Y, "t": anchors}
                 if c == z else zero) for c in COUNTRIES}
    X1, X2, G, _ = pack_dataset(split, COUNTRIES, [z], lambda tgt: [tgt])
    pred = model.predict({"X_lag_all": X1, "X_lead_all": X2, "graph_gate": G},
                         batch_size=256, verbose=0)
    eur = inverse_scale_y_pred(pred, y_scalers[z])[:, :, MED]  # (N, 96) EUR/MWh

    q15 = pd.concat([
        pd.Series(eur[i], index=pd.date_range(a, periods=96, freq="15min", tz="UTC"))
        for i, a in enumerate(anchors)])
    hourly = q15.resample("1h").mean().dropna()
    csv = Path("experiments/forecasts") / f"pricefm-{bzn}-2026H1.csv"
    hourly.rename("forecast_eur_mwh").to_csv(csv, header=True)

    px = fetch_day_ahead(bzn, "2026-01-01", "2026-06-30")
    res = compare(hourly, px, bat)
    print(f"\n=== {bzn} — PriceFM zero-shot H1 2026 ===")
    for name, s in res.items():
        c = s.capture
        print(f"  {name:18s}: {c.revenue_eur:>10,.0f} / {c.ceiling_eur:,.0f} EUR "
              f"-> capture {c.ratio:6.1%}   rank-corr {s.rank_corr:5.2f}   "
              f"RMSE {s.rmse_eur_mwh:5.1f}   ({c.hours} h)", flush=True)
    print(f"  csv: {csv}", flush=True)
