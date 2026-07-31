"""Stack allocation 2x2: piano (persistence/forecast) x bid aFRR (cieco/EV).

Protocollo: PROTOCOL-stack-allocation.md (1345f40). DE, Q2 2026. Il forecast
del piano viene dal CSV committato di Chronos-2 +RL (nessun run del modello).

    PYTHONPATH=. uv run python experiments/stack_allocation.py
"""
import pandas as pd

from bess_arbitrage.bench import run_sequential
from bess_arbitrage.model import Battery

START, END = "2026-04-01", "2026-06-30"
HIST_DAYS = 28

fc = pd.read_csv("experiments/forecasts/chronos2-RL-DE-LU-2026H1.csv",
                 index_col=0, parse_dates=True).iloc[:, 0]

bat = Battery()
cells = [
    ("persistence + bid cieco", None, 0),
    ("forecast    + bid cieco", fc, 0),
    ("persistence + bid EV", None, HIST_DAYS),
    ("forecast    + bid EV", fc, HIST_DAYS),
]
print(f"=== stack allocation DE {START}..{END} — 2x2 pre-registrato ===", flush=True)
for label, plan, hist in cells:
    s = run_sequential(START, END, bat, plan_forecast=plan, afrr_bid_hist_days=hist)
    sp = {k: round(v) for k, v in s["split_eur"].items()}
    print(f"{label:24s}: {s['seq_eur']:>9,.0f} / {s['ceiling_eur']:,.0f} EUR "
          f"-> stack capture {s['capture']:6.1%}   split {sp}   "
          f"award-rate {s['award_rate']:.0%}", flush=True)
