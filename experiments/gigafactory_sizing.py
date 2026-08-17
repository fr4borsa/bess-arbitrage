"""Replicate the AI-Gigafactory clean-power sizing (Czyzak, Energy Extended 05/08/2026)
with the repo's LP stack. Protocol: PROTOCOL-gigafactory-sizing.md.

    uv run python experiments/gigafactory_sizing.py               # 24 countries, capped + uncapped
    uv run python experiments/gigafactory_sizing.py --countries es de --quick

Writes reports/gigafactory-sizing-<window>.csv/.md.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import pandas as pd
import pulp
import requests

from bess_arbitrage.prices import CACHE_DIR, _get_json

START, END = "2025-08-01", "2026-07-31"
DC_MW = 250.0
DURATION_H = 4.0
RTE = 0.85
WACC = 0.07
GRID_EUR_MWH = 300.0
CAP_MW = 1000.0
COUNTRIES = ["at", "be", "bg", "cz", "de", "dk", "ee", "es", "fi", "fr", "gr", "hr", "hu",
             "ie", "it", "lt", "lv", "nl", "pl", "pt", "ro", "se", "si", "sk", "uk"]
SENS = ("es", "fr", "de", "pl", "it")
COSTS_URL = "https://raw.githubusercontent.com/PyPSA/technology-data/master/outputs/costs_2030.csv"
INSTALLED_API = "https://api.energy-charts.info/installed_power"
POWER_API = "https://api.energy-charts.info/public_power"
OUT = Path("reports")

# Czyzak's chart, read off the 24/06 image (MW wind / solar / battery, hours-matched %).
# The five he named in the text; the rest of the chart is only in bar form.
CZYZAK = {"es": (432, 1000, 652, 96.7), "fr": (618, 1000, 843, 95.1),
          "de": (981, 775, 1000, 93.2), "pl": (702, 737, 1000, 97.0),
          "it": (428, 989, 886, 96.6)}


def costs() -> dict:
    """Annualized EUR/MW-year (or EUR/MWh-year for storage) from technology-data."""
    f = CACHE_DIR / "technology-data" / "costs_2030.csv"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(requests.get(COSTS_URL, timeout=60).content)
    df = pd.read_csv(f).set_index(["technology", "parameter"])["value"]

    def ann(tech: str) -> float:
        inv, life = df[(tech, "investment")], df[(tech, "lifetime")]
        fom = df.get((tech, "FOM"), 0.0)  # battery storage has no FOM row (it sits on the inverter)
        crf = WACC / (1 - (1 + WACC) ** -life)
        return inv * 1000 * (crf + fom / 100)  # EUR/kW -> EUR/MW (or kWh -> MWh)

    return {"wind": ann("onwind"), "solar": ann("solar-utility"),
            "bat_power": ann("battery inverter"), "bat_energy": ann("battery storage")}


def capacity_factors(country: str) -> pd.DataFrame:
    """Hourly CF of solar and onshore wind: realized generation / installed capacity."""
    j = _get_json(POWER_API, {"country": country, "start": START, "end": END},
                  CACHE_DIR / country / f"pp_{START}_{END}.json", END)
    idx = pd.to_datetime(j["unix_seconds"], unit="s", utc=True)
    gen = {}
    for p in j["production_types"]:
        if p["name"] == "Solar":
            gen["solar"] = pd.Series(p["data"], index=idx, dtype=float)
        elif p["name"] == "Wind onshore":
            gen["wind"] = pd.Series(p["data"], index=idx, dtype=float)
    if len(gen) < 2:
        raise RuntimeError(f"{country}: no solar/wind onshore series")
    gen = pd.DataFrame(gen).resample("1h").mean().dropna()

    inst_file = CACHE_DIR / country / "installed.json"
    if inst_file.exists():
        ji = json.loads(inst_file.read_text())
    else:  # monthly where energy-charts has it (DE...), yearly elsewhere (declared)
        ji = None
        for step in ("monthly", "yearly"):
            r = requests.get(INSTALLED_API, params={"country": country, "time_step": step,
                             "installation_decommission": False}, timeout=60)
            try:
                cand = r.json()
            except ValueError:
                continue
            if cand.get("time"):
                ji = cand | {"time_step": step}
                break
        if ji is None:
            raise RuntimeError(f"{country}: installed capacity unavailable")
        inst_file.write_text(json.dumps(ji))
    fmt = "%m.%Y" if ji["time_step"] == "monthly" else "%Y"
    months = pd.to_datetime(ji["time"], format=fmt, utc=True)
    inst = {}
    for p in ji["production_types"]:
        key = ("solar" if p["name"].startswith("Solar")
               else "wind" if p["name"] == "Wind onshore" else None)
        if key:
            s = pd.Series(p["data"], index=months, dtype=float) * 1000  # GW -> MW
            inst[key] = s.reindex(gen.index, method="ffill").bfill()
    cf = pd.DataFrame({k: (gen[k] / inst[k]).clip(0, 1) for k in ("solar", "wind")})
    return cf.dropna()


def size(cf: pd.DataFrame, cost: dict, grid_price: float, cap: float | None) -> dict:
    n = len(cf)
    scale = 8760 / n  # annualize the operating term to the window
    m = pulp.LpProblem("gigafactory", pulp.LpMinimize)
    W = m.add_variable("W", 0, cap)
    S = m.add_variable("S", 0, cap)
    B = m.add_variable("B", 0, cap)
    chg = [m.add_variable(f"c{t}", 0) for t in range(n)]
    dis = [m.add_variable(f"d{t}", 0) for t in range(n)]
    soc = [m.add_variable(f"s{t}", 0) for t in range(n)]
    grid = [m.add_variable(f"g{t}", 0) for t in range(n)]
    curt = [m.add_variable(f"x{t}", 0) for t in range(n)]
    eff = math.sqrt(RTE)
    cfw, cfs = cf["wind"].to_list(), cf["solar"].to_list()
    for t in range(n):
        m += W * cfw[t] + S * cfs[t] + dis[t] - chg[t] + grid[t] - curt[t] == DC_MW
        m += chg[t] <= B
        m += dis[t] <= B
        m += soc[t] <= DURATION_H * B
        prev = soc[t - 1] if t > 0 else 0.5 * DURATION_H * B
        m += soc[t] == prev + eff * chg[t] - dis[t] / eff
    m += (cost["wind"] * W + cost["solar"] * S
          + (cost["bat_power"] + DURATION_H * cost["bat_energy"]) * B
          + scale * grid_price * pulp.lpSum(grid))
    m.solve(pulp.HiGHS(msg=False))
    if pulp.LpStatus[m.status] != "Optimal":
        raise RuntimeError(pulp.LpStatus[m.status])
    g = pd.Series([v.value() for v in grid])
    x = sum(v.value() for v in curt)
    clean = W.value() * sum(cfw) + S.value() * sum(cfs)
    return {
        "wind_mw": W.value(), "solar_mw": S.value(), "battery_mw": B.value(),
        "battery_per_dc": B.value() / DC_MW,
        "hours_matched": float((g < 0.005 * DC_MW).mean()),
        "energy_matched": 1 - g.sum() / (DC_MW * n),
        "curtailed_share": x / clean if clean > 0 else math.nan,
        "eur_per_mwh": pulp.value(m.objective) / scale / (DC_MW * n),
        "grid_price": grid_price, "cap_mw": cap if cap is not None else math.inf,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--countries", nargs="*", default=COUNTRIES)
    ap.add_argument("--quick", action="store_true", help="skip grid-price sensitivity")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    cost = costs()
    print("annualized costs EUR/MW-y:", {k: round(v) for k, v in cost.items()}, flush=True)
    rows, skipped = [], []
    for c in a.countries:
        try:
            cf = capacity_factors(c)
        except Exception as e:
            print(f"{c}: skipped ({e})", flush=True)
            skipped.append(c)
            continue
        cells = [(GRID_EUR_MWH, CAP_MW), (GRID_EUR_MWH, None)]
        if c in SENS and not a.quick:
            cells += [(150.0, CAP_MW), (1000.0, CAP_MW)]
        for gp, cap in cells:
            t0 = time.time()
            r = {"country": c, "cf_wind": cf["wind"].mean(), "cf_solar": cf["solar"].mean(),
                 "hours": len(cf)} | size(cf, cost, gp, cap)
            rows.append(r)
            print(f"{c}  grid {gp:5.0f}  cap {str(cap):>6}  W {r['wind_mw']:6.0f}  "
                  f"S {r['solar_mw']:6.0f}  B {r['battery_mw']:6.0f} ({r['battery_per_dc']:.2f}x)  "
                  f"hours {r['hours_matched']:.1%}  energy {r['energy_matched']:.1%}  "
                  f"({time.time() - t0:.0f}s)", flush=True)
        time.sleep(0.8)
    df = pd.DataFrame(rows)
    tag = f"gigafactory-sizing-{START}_{END}"
    df.to_csv(OUT / f"{tag}.csv", index=False)
    base = df[(df["grid_price"] == GRID_EUR_MWH) & (df["cap_mw"] == CAP_MW)].copy()
    for k, col in enumerate(("cz_wind", "cz_solar", "cz_battery", "cz_hours")):
        base[col] = base["country"].map(lambda c, k=k: CZYZAK.get(c, (None,) * 4)[k])
    unc = df[(df["grid_price"] == GRID_EUR_MWH) & (df["cap_mw"] == math.inf)]
    md = [f"# Gigafactory sizing replication {START} → {END}\n",
          f"Protocol: experiments/PROTOCOL-gigafactory-sizing.md. 250 MW flat DC, 4 h battery, "
          f"RTE 85 %, grid {GRID_EUR_MWH:.0f} €/MWh, technology-data 2030 costs annualized at "
          f"{WACC:.0%}: " + ", ".join(f"{k} {v:,.0f} €/MW-y" for k, v in cost.items())
          + f". Skipped: {skipped or 'none'}.\n",
          "\n### Capped at 1000 MW per technology (his design) vs Czyżak's chart\n",
          base[["country", "cf_wind", "cf_solar", "wind_mw", "solar_mw", "battery_mw",
                "battery_per_dc", "hours_matched", "energy_matched", "curtailed_share",
                "eur_per_mwh", "cz_wind", "cz_solar", "cz_battery", "cz_hours"]]
          .to_markdown(index=False, floatfmt=("", ".2f", ".2f", ".0f", ".0f", ".0f", ".2f", ".1%",
                                              ".1%", ".1%", ".0f", ".0f", ".0f", ".0f", ".1f")),
          "\n### Uncapped\n",
          unc[["country", "wind_mw", "solar_mw", "battery_mw", "battery_per_dc",
               "hours_matched", "energy_matched", "curtailed_share", "eur_per_mwh"]]
          .to_markdown(index=False, floatfmt=("", ".0f", ".0f", ".0f", ".2f", ".1%", ".1%",
                                              ".1%", ".0f"))]
    sens = df[df["grid_price"] != GRID_EUR_MWH]
    if len(sens):
        md += ["\n### Grid-price sensitivity (capped)\n",
               sens[["country", "grid_price", "wind_mw", "solar_mw", "battery_mw",
                     "battery_per_dc", "hours_matched", "energy_matched", "eur_per_mwh"]]
               .to_markdown(index=False, floatfmt=("", ".0f", ".0f", ".0f", ".0f", ".2f",
                                                   ".1%", ".1%", ".0f"))]
    (OUT / f"{tag}.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
