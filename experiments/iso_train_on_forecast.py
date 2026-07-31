"""Isotonica train-su-forecast, protocollo PROTOCOL-iso-train-on-forecast.md.

2x2 per zona: curva statica (anno 2025) / adattiva 60d, allenata su residual
load realizzato / forecast TSO. Valutazione SEMPRE ex-ante (stress = forecast
TSO H1 2026). Nessuna modifica al package: solo chiamate all'API esistente.

    PYTHONPATH=. uv run python experiments/iso_train_on_forecast.py
"""
import datetime as dt

from bess_arbitrage.capture import (
    isotonic_forecast,
    isotonic_rolling_forecast,
    persistence_forecast,
)
from bess_arbitrage.model import Battery
from bess_arbitrage.prices import (
    fetch_day_ahead,
    fetch_residual_load,
    fetch_residual_load_forecast,
)

START, END = "2026-01-01", "2026-06-30"
T0, T1 = "2025-01-01", "2025-12-31"          # train year (curva statica)
H0 = (dt.date.fromisoformat(START) - dt.timedelta(days=60)).isoformat()

bat = Battery()
for bzn in ("DE-LU", "FR", "NL"):
    print(f"\n=== {bzn} ===", flush=True)
    px = fetch_day_ahead(bzn, START, END)
    fc = fetch_residual_load_forecast(bzn, START, END)      # stress di valutazione
    pers = persistence_forecast(px, bat)
    print(f"  persistence           : {pers.ratio:6.1%}  ({pers.hours} h)", flush=True)

    train_px = fetch_day_ahead(bzn, T0, T1)
    rows = []
    for stress_name, train_stress, hist_stress in (
        ("realized", fetch_residual_load(bzn, T0, T1), fetch_residual_load(bzn, H0, END)),
        ("forecast", fetch_residual_load_forecast(bzn, T0, T1),
         fetch_residual_load_forecast(bzn, H0, END)),
    ):
        static = isotonic_forecast(px, fc, bat,
                                   train_prices=train_px, train_stress=train_stress)
        adapt = isotonic_rolling_forecast(px, fc, bat,
                                          hist_prices=fetch_day_ahead(bzn, H0, END),
                                          hist_stress=hist_stress)
        rows.append((stress_name, static, adapt))
        print(f"  static  train-{stress_name}: {static.ratio:6.1%}  ({static.hours} h)",
              flush=True)
        print(f"  60d     train-{stress_name}: {adapt.ratio:6.1%}  ({adapt.hours} h)",
              flush=True)
