"""Chronos-Bolt (zero-shot time-series foundation model) as a price forecaster
inside the capture harness. Same protocol as every other variant: per day,
context = price history up to midnight (672 h, the learned-linear window),
median 24h forecast, LP on the forecast, settled at real prices, SOC chained,
days from #8 onward. Capture is directly comparable with the README table.

Not part of the package (torch is a heavy, experiment-only dependency). Run:

    PYTHONPATH=. uv run --with chronos-forecasting python experiments/chronos_capture.py DE-LU

Measured H1 2026: DE-LU 90.7% (learned linear 86.2%, isotonic ex-ante 91.7%),
FR 85.2% — the best operable strategy there. See docs/ai-layer.md.
"""
import sys

import numpy as np
import pandas as pd
import torch

from bess_arbitrage.capture import _days
from bess_arbitrage.model import Battery, optimize
from bess_arbitrage.prices import fetch_day_ahead

BZN = sys.argv[1] if len(sys.argv) > 1 else "DE-LU"
CTX_H = 672  # 28 giorni di contesto, come la finestra del learned linear

from chronos import BaseChronosPipeline  # noqa: E402

pipe = BaseChronosPipeline.from_pretrained(
    "amazon/chronos-bolt-small", device_map="cpu", torch_dtype=torch.float32)

px = fetch_day_ahead(BZN, "2026-01-01", "2026-06-30")
days = _days(px)
bat = Battery()

# contesti per ogni giorno target (storia fino alla mezzanotte del giorno)
targets = list(range(8, len(days)))
contexts = []
for i in targets:
    t0 = days[i].index[0]
    hist = px[px.index < t0].to_numpy()[-CTX_H:]
    contexts.append(torch.tensor(hist, dtype=torch.float32))

# forecast a lotti (mediana = quantile 0.5)
preds = []
B = 32
for k in range(0, len(contexts), B):
    _, mean = pipe.predict_quantiles(contexts[k:k + B], prediction_length=25,
                                     quantile_levels=[0.5])
    preds.extend(mean.numpy())
    print(f"forecast {min(k + B, len(contexts))}/{len(contexts)}", flush=True)

revenue, soc0, settled = 0.0, 0.0, []
for j, i in enumerate(targets):
    day = days[i]
    n = min(len(day), len(preds[j]))
    fc = pd.Series(preds[j][:n], index=day.index[:n])
    plan = optimize(fc, bat, soc0=soc0).dispatch
    revenue += float((day.to_numpy()[:n] * (plan["discharge"] - plan["charge"])).sum())
    soc0 = max(0.0, plan["soc"].iloc[-1])
    settled.append(day.iloc[:n])

real = pd.concat(settled)
ceiling = optimize(real, bat).revenue_eur
print(f"\n{BZN} chronos-bolt-small zero-shot: {revenue:,.0f} / {ceiling:,.0f} EUR "
      f"-> capture {revenue / ceiling:.1%}  ({len(real)} h settled)")

# qualita' statistica per confronto: RMSE medio del forecast vs reale
errs = []
for j, i in enumerate(targets):
    day = days[i]
    n = min(len(day), len(preds[j]))
    errs.append(float(np.sqrt(np.mean((preds[j][:n] - day.to_numpy()[:n]) ** 2))))
print(f"RMSE medio giornaliero forecast: {np.mean(errs):.1f} EUR/MWh")
