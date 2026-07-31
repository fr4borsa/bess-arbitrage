"""Chronos-2 zero-shot with TSO known-future covariates, scored by the judge.

Runs the pre-registered protocol in PROTOCOL-chronos2.md: 3 arms (price-only /
+residual-load / +4 components), identical settled hours across arms, scoring
delegated to bess_arbitrage.score.compare — the same treatment any external
forecast gets. Forecast CSVs are written to experiments/forecasts/ so the run
is re-scoreable without the model.

Not part of the package (torch is a heavy, experiment-only dependency). Run:

    PYTHONPATH=. uv run --with chronos-forecasting python experiments/chronos2_capture.py DE-LU
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from bess_arbitrage.capture import _days
from bess_arbitrage.model import Battery
from bess_arbitrage.prices import (
    fetch_day_ahead,
    fetch_dayahead_forecast_components,
    fetch_residual_load_forecast,
)
from bess_arbitrage.score import compare

BZN = sys.argv[1] if len(sys.argv) > 1 else "DE-LU"
START, END = "2026-01-01", "2026-06-30"
CTX_H = 672  # 28 giorni di contesto, come Bolt e il learned linear
OUT = Path(__file__).parent / "forecasts"
OUT.mkdir(exist_ok=True)

px = fetch_day_ahead(BZN, START, END)
rl = fetch_residual_load_forecast(BZN, START, END).to_frame("residual_load")
comp = fetch_dayahead_forecast_components(BZN, START, END)

days = _days(px)
# giorni eleggibili: dal #8, copertura covariate COMPLETA in entrambi i set
# (protocollo: tutte le braccia settlano le stesse ore)
targets = [i for i in range(8, len(days))
           if not comp.reindex(days[i].index).isna().any().any()
           and not rl.reindex(days[i].index).isna().any().any()]
print(f"{BZN}: {len(targets)} target days "
      f"({len(days) - 8 - len(targets)} dropped for covariate gaps)", flush=True)

from chronos import Chronos2Pipeline  # noqa: E402

pipe = Chronos2Pipeline.from_pretrained(
    "amazon/chronos-2", device_map="cpu", torch_dtype=torch.float32)


def run_arm(cov: pd.DataFrame | None, label: str) -> pd.Series:
    # gruppi per lunghezza del giorno (23/24/25 h, DST) cosi' le covariate
    # future combaciano esattamente con prediction_length
    by_len: dict[int, list[int]] = {}
    for i in targets:
        by_len.setdefault(len(days[i]), []).append(i)
    out = []
    for plen, idxs in sorted(by_len.items()):
        inputs = []
        for i in idxs:
            day = days[i]
            hist = px[px.index < day.index[0]].iloc[-CTX_H:]
            item: dict = {"target": hist.to_numpy(np.float32)}
            if cov is not None:
                # storia: ffill sui buchi (condiziona soltanto); futuro: completo
                # per costruzione (selezione dei target)
                past = cov.reindex(hist.index).ffill().bfill()
                fut = cov.reindex(day.index)
                item["past_covariates"] = {c: past[c].to_numpy(np.float32) for c in cov}
                item["future_covariates"] = {c: fut[c].to_numpy(np.float32) for c in cov}
            inputs.append(item)
        q, _ = pipe.predict_quantiles(inputs, prediction_length=plen,
                                      quantile_levels=[0.5])
        for i, t in zip(idxs, q, strict=True):
            med = np.asarray(t).squeeze()
            assert med.shape == (plen,), (label, med.shape, plen)
            out.append(pd.Series(med.astype(float), index=days[i].index))
        print(f"  {label}: {len(out)}/{len(targets)} days", flush=True)
    return pd.concat(out).sort_index()


bat = Battery()
arms = [("price-only", None), ("+RL", rl), ("+components", comp)]
print(f"\n=== {BZN} {START}..{END} — chronos-2 zero-shot, 3 pre-registered arms ===")
for label, cov in arms:
    fc = run_arm(cov, label)
    csv = OUT / f"chronos2-{label.strip('+')}-{BZN}-2026H1.csv"
    fc.rename("forecast_eur_mwh").to_csv(csv, header=True)
    res = compare(fc, px, bat)
    c = res["candidate"].capture
    s = res["candidate"]
    print(f"{label:12s}: {c.revenue_eur:>10,.0f} / {c.ceiling_eur:,.0f} EUR "
          f"-> capture {c.ratio:6.1%}   rank-corr {s.rank_corr:5.2f}   "
          f"RMSE {s.rmse_eur_mwh:5.1f}   ({c.hours} h, csv: {csv.name})", flush=True)
p = res["persistence"].capture
r = res["rolling day-ahead"].capture
print(f"{'persistence':12s}: capture {p.ratio:6.1%}   (same hours)")
print(f"{'rolling DA':12s}: capture {r.ratio:6.1%}   (same hours)")
