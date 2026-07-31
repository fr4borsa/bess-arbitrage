"""Il ventaglio paga? Mediana vs media vs CVaR sui quantili Chronos-2 +RL.

Protocollo: PROTOCOL-quantile-dispatch.md (69b483d). Stesso rito di
chronos2_capture.py (contesto 672 h, giorni dal #8, covariata RL, SOC
incatenato), ma il dispatch usa la distribuzione predittiva:

  - median : LP sulla mediana (controllo — deve riprodurre il CSV committato)
  - mean   : LP sulla media predittiva
  - CVaR   : LP a scenari (9 curve-quantile equiprobabili, comonotone —
             limite dichiarato nel protocollo), obiettivo
             (1-l)*mean(R_s) + l*CVaR_0.2(R_s), l in {0.5, 1.0}

    PYTHONPATH=. uv run --with chronos-forecasting python \
        experiments/chronos2_quantile_dispatch.py DE-LU
"""
import math
import sys

import numpy as np
import pandas as pd
import pulp
import torch

from bess_arbitrage.capture import _days
from bess_arbitrage.model import Battery, optimize
from bess_arbitrage.prices import fetch_day_ahead, fetch_residual_load_forecast

BZN = sys.argv[1] if len(sys.argv) > 1 else "DE-LU"
START, END = "2026-01-01", "2026-06-30"
CTX_H = 672
QL = [round(0.1 * k, 1) for k in range(1, 10)]  # 0.1 .. 0.9
ALPHA = 0.2

px = fetch_day_ahead(BZN, START, END)
rl = fetch_residual_load_forecast(BZN, START, END).to_frame("residual_load")
days = _days(px)
targets = [i for i in range(8, len(days))
           if not rl.reindex(days[i].index).isna().any().any()]
print(f"{BZN}: {len(targets)} target days", flush=True)

from chronos import Chronos2Pipeline  # noqa: E402

pipe = Chronos2Pipeline.from_pretrained(
    "amazon/chronos-2", device_map="cpu", torch_dtype=torch.float32)

# ── predizioni: quantili + media, per gruppi di lunghezza-giorno ──
by_len: dict[int, list[int]] = {}
for i in targets:
    by_len.setdefault(len(days[i]), []).append(i)
qcurves: dict[int, np.ndarray] = {}   # i -> (plen, 9)
mcurves: dict[int, np.ndarray] = {}   # i -> (plen,)
for plen, idxs in sorted(by_len.items()):
    inputs = []
    for i in idxs:
        day = days[i]
        hist = px[px.index < day.index[0]].iloc[-CTX_H:]
        past = rl.reindex(hist.index).ffill().bfill()
        fut = rl.reindex(day.index)
        inputs.append({
            "target": hist.to_numpy(np.float32),
            "past_covariates": {"residual_load":
                                past["residual_load"].to_numpy(np.float32)},
            "future_covariates": {"residual_load":
                                  fut["residual_load"].to_numpy(np.float32)},
        })
    q, mean = pipe.predict_quantiles(inputs, prediction_length=plen,
                                     quantile_levels=QL)
    for i, qt in zip(idxs, q, strict=True):
        qa = np.asarray(qt).squeeze()
        assert qa.shape == (plen, len(QL)), qa.shape
        qcurves[i] = qa.astype(float)
        # emendamento documentato nel protocollo: il "mean" nativo di Chronos-2
        # e' un alias della mediana (verificato: diff 0.0), quindi la media
        # predittiva si stima integrando i quantili (media delle 9 curve)
        mcurves[i] = qa.astype(float).mean(axis=1)
    print(f"  predizioni: {len(qcurves)}/{len(targets)}", flush=True)


def cvar_day_plan(scen: np.ndarray, bat: Battery, soc0: float, lam: float) -> pd.DataFrame:
    """LP a scenari per un giorno: stessi vincoli di model.optimize (potenza,
    dinamica SOC con sqrt(RTE) per gamba, cap cicli pro-rata), obiettivo
    (1-lam)*mean(R_s) + lam*CVaR_alpha(R_s) alla Rockafellar-Uryasev."""
    n, k = scen.shape[0], scen.shape[1]
    eff = math.sqrt(bat.rte)
    cap, pmax = bat.capacity_mwh, bat.power_mw
    m = pulp.LpProblem("cvar_day", pulp.LpMaximize)
    chg = [m.add_variable(f"c{t}", 0, pmax) for t in range(n)]
    dis = [m.add_variable(f"d{t}", 0, pmax) for t in range(n)]
    soc = [m.add_variable(f"s{t}", 0, cap) for t in range(n)]
    zeta = m.add_variable("zeta", -1e9, 1e9)
    u = [m.add_variable(f"u{s}", 0, 1e9) for s in range(k)]
    rev = [pulp.lpSum(float(scen[t, s]) * (dis[t] - chg[t]) for t in range(n))
           for s in range(k)]
    for s in range(k):
        m += u[s] >= zeta - rev[s]
    cvar = zeta - (1.0 / (ALPHA * k)) * pulp.lpSum(u)
    m += (1 - lam) * (1.0 / k) * pulp.lpSum(rev) + lam * cvar
    for t in range(n):
        prev = soc[t - 1] if t > 0 else soc0
        m += soc[t] == prev + eff * chg[t] - dis[t] / eff
    if bat.max_cycles_per_day is not None:
        m += pulp.lpSum(dis) <= bat.max_cycles_per_day * cap * max(1, n // 24)
    m.solve(pulp.HiGHS(msg=False))
    if pulp.LpStatus[m.status] != "Optimal":
        raise RuntimeError(pulp.LpStatus[m.status])
    return pd.DataFrame({"charge": [c.value() for c in chg],
                         "discharge": [d.value() for d in dis],
                         "soc": [s.value() for s in soc]})


def run_arm(label: str, plan_fn) -> None:
    revenue, soc0, settled, daily = 0.0, 0.0, [], []
    for i in targets:
        day = days[i]
        plan = plan_fn(i, soc0)
        r = float((day.to_numpy() * (plan["discharge"] - plan["charge"])).sum())
        revenue += r
        daily.append(r)
        soc0 = max(0.0, plan["soc"].iloc[-1])
        settled.append(day)
    real = pd.concat(settled)
    ceiling = optimize(real, bat).revenue_eur
    d = np.sort(np.array(daily))
    worst5 = d[: max(1, int(len(d) * 0.05))]
    print(f"{label:12s}: {revenue:>10,.0f} / {ceiling:,.0f} EUR -> capture "
          f"{revenue / ceiling:6.1%}   std/g {d.std():6.0f}  worst5% "
          f"{worst5.mean():7.0f}  min {d.min():7.0f} EUR", flush=True)


bat = Battery()
mid = QL.index(0.5)
print(f"\n=== {BZN} — il ventaglio paga? ({len(targets)} giorni) ===", flush=True)
run_arm("median", lambda i, s0: optimize(
    pd.Series(qcurves[i][:, mid], index=days[i].index), bat, soc0=s0).dispatch)
run_arm("mean", lambda i, s0: optimize(
    pd.Series(mcurves[i], index=days[i].index), bat, soc0=s0).dispatch)
run_arm("cvar l=0.5", lambda i, s0: cvar_day_plan(qcurves[i], bat, s0, 0.5))
run_arm("cvar l=1.0", lambda i, s0: cvar_day_plan(qcurves[i], bat, s0, 1.0))

# validazione interna: la mediana rigenerata coincide col CSV committato?
csv = pd.read_csv(f"experiments/forecasts/chronos2-RL-{BZN}-2026H1.csv",
                  index_col=0, parse_dates=True).iloc[:, 0]
regen = pd.concat([pd.Series(qcurves[i][:, mid], index=days[i].index) for i in targets])
both = pd.concat([csv, regen], axis=1, join="inner").dropna()
diff = float((both.iloc[:, 0] - both.iloc[:, 1]).abs().max())
print(f"validazione mediana vs CSV committato: max|diff| = {diff:.3f} EUR/MWh "
      f"su {len(both)} h", flush=True)
