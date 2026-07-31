"""Calibrazione PriceFM: il checkpoint pubblicato, sul LORO fold-3 di test,
con il LORO codice — dobbiamo riprodurre Result/phase1_pretraining.csv prima
di portare il modello su H1 2026. Se i numeri tornano, il nostro modo di
guidare il modello è fedele."""
import os
import sys
from pathlib import Path

import pandas as pd

BASE = Path(os.environ.get("PRICEFM_DIR", "PriceFM-upstream")).resolve()
sys.path.insert(0, str(BASE))
os.chdir(BASE)  # load_model usa path relativi "Model/..."

from PriceFM.data import (  # noqa: E402
    make_rolling_window_samples,
    read_dataset,
    scale_dataframe_per_country,
    separate_countries,
    split_dataframe,
)
from PriceFM.evaluation import evaluate_countries  # noqa: E402
from PriceFM.model import load_model  # noqa: E402

COUNTRIES = [
    "AT", "BE", "BG", "CZ", "DE_LU", "DK_1", "DK_2",
    "EE", "ES", "FI", "FR", "GR", "HR", "HU",
    "IT_CALA", "IT_CNOR", "IT_CSUD", "IT_NORD", "IT_SARD", "IT_SICI", "IT_SUD",
    "LT", "LV", "NL", "NO_1", "NO_2", "NO_3", "NO_4", "NO_5",
    "PL", "PT", "RO", "SE_1", "SE_2", "SE_3", "SE_4", "SI", "SK",
]
LABEL = "price"
LAG_F = ["price", "load", "solar", "wind"]
LEAD_F = ["load", "solar", "wind"]
FEATURES = sorted((set(LAG_F) | set(LEAD_F)) - {LABEL})
LAG_W = LEAD_W = 96
QUANTILES = [0.10, 0.25, 0.45, 0.50, 0.55, 0.75, 0.90]

# fold 3 (quello del checkpoint pubblicato, ultimo del rolling)
TR0, TR1, VA0, VA1, TE0, TE1 = ("2022-01-01", "2025-05-01", "2025-05-01",
                                "2025-09-01", "2025-09-01", "2026-01-01")

print("read FINAL.csv ...", flush=True)
df = read_dataset(str(BASE / "FINAL.csv"))
print(f"  {len(df):,} righe, {df.index[0]} .. {df.index[-1]}", flush=True)

df_train, df_val, df_test = split_dataframe(df, TR0, TR1, VA0, VA1, TE0, TE1)
df_train_s, df_val_s, df_test_s, x_scalers, y_scalers = scale_dataframe_per_country(
    df_train, df_val, df_test, COUNTRIES, FEATURES, LABEL)
test_sep = separate_countries(df_test_s, COUNTRIES, FEATURES, LABEL)

rolling_test = {}
for c in COUNTRIES:
    X_lag, X_lead, Y, t = make_rolling_window_samples(
        test_sep[c], c, LAG_F, LEAD_F, LABEL, LAG_W, LEAD_W)
    rolling_test[c] = {"X_lag": X_lag, "X_lead": X_lead, "Y": Y, "t": t}
print(f"finestre test: {rolling_test['DE_LU']['Y'].shape} (DE_LU)", flush=True)

model = load_model("Model/PhaseI_best.keras")
res = evaluate_countries(model=model, split=rolling_test,
                         input_countries=COUNTRIES, output_countries=["DE_LU", "FR"],
                         gate_fn=lambda t: [t], quantiles=QUANTILES, y_scalers=y_scalers)

pub = pd.read_csv("Result/phase1_pretraining.csv").set_index("target_country")
print("\n=== CALIBRAZIONE: nostro run vs pubblicato ===")
for c in ("DE_LU", "FR"):
    ours, theirs = res[c], pub.loc[c]
    for k in ("AQL", "RMSE", "MAE"):
        print(f"{c:6s} {k:5s}  nostro {ours[k]:8.3f}   pubblicato {theirs[k]:8.3f}   "
              f"delta {ours[k] - theirs[k]:+7.3f}")
