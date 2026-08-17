"""Stage 1 — connection cap sweep across zones. Protocol: PROTOCOL-connection-cap.md.

    uv run python experiments/connection_cap.py            # all zones, both profiles/durations
    uv run python experiments/connection_cap.py --zones DE-LU ES CH --quick

Writes reports/connection-cap-<window>.csv (every cell) and .md (tables), and
reports/connection-cap-<window>.png (the curve per profile/duration).
"""
from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import pandas as pd

from bess_arbitrage.atlas import ZONES
from bess_arbitrage.connection import cap_curve, dc_load
from bess_arbitrage.model import Battery
from bess_arbitrage.prices import fetch_day_ahead

START, END = "2025-08-01", "2026-07-31"
PEAK_PER_PBAT = 5.0                 # battery = 20 % of the site peak
DURATIONS = (2.0, 4.0)
PROFILES = ("flat", "cooling")
SENS_ZONES = ("DE-LU", "ES", "CH")  # peak = 2x and 10x P_bat
OUT = Path("reports")


def _at_k(df: pd.DataFrame, k: float, col: str = "loss_frac") -> float:
    """Value of `col` at cap = peak + k·P_bat (mw_bought = -k)."""
    return float(df.loc[(df["mw_bought_per_pbat"] + k).abs() < 1e-9, col].iloc[0])


def run(zones: list[str], quick: bool) -> pd.DataFrame:
    rows = []
    for z in zones:
        try:
            px = fetch_day_ahead(z, START, END)
        except Exception as e:  # zone without data in the window: skipped, listed
            print(f"{z}: skipped ({e})", flush=True)
            continue
        peaks = [PEAK_PER_PBAT] + ([2.0, 10.0] if z in SENS_ZONES and not quick else [])
        for dur in DURATIONS:
            bat = Battery(power_mw=1.0, duration_h=dur)
            for prof in PROFILES:
                for peak in peaks:
                    load = dc_load(px.index, peak / 1.35, prof)  # PUE_MAX = 1.35 -> peak
                    t0 = time.time()
                    df = cap_curve(px, bat, load)
                    df["zone"], df["duration_h"] = z, dur
                    df["profile"], df["peak_per_pbat"] = prof, peak
                    df["ceiling_eur"], df["hours"] = df.attrs["ceiling_eur"], len(px)
                    rows.append(df)
                    feas = df[df["feasible"]]
                    print(f"{z:16s} {dur:.0f}h {prof:8s} peak={peak:4.0f}xPbat  "
                          f"max MW bought {feas['mw_bought_per_pbat'].max():+.2f} Pbat  "
                          f"loss@k=0 {_at_k(df, 0):.1%}  ({time.time() - t0:.0f}s)", flush=True)
        time.sleep(0.8)  # energy-charts rate limiter
    return pd.concat(rows, ignore_index=True)


def _zone_row(gz: pd.DataFrame) -> dict:
    gz = gz.sort_values("cap_mw", ascending=False)
    bought = gz[gz["feasible"] & (gz["mw_bought_per_pbat"] > 1e-9)]

    def at_most(lim: float) -> float:
        ok = bought[bought["loss_frac"] <= lim]
        return float(ok["mw_bought_per_pbat"].max()) if len(ok) else 0.0

    mx = bought.iloc[-1] if len(bought) else None
    return {
        "ceiling_eur_mw_y": gz["ceiling_eur"].iloc[0] * 8760 / gz["hours"].iloc[0],
        "loss_k0": _at_k(gz, 0), "loss_k+0.5": _at_k(gz, 0.5),
        "max_mw_bought_per_pbat": float(mx["mw_bought_per_pbat"]) if mx is not None else 0.0,
        "mw_bought_le10pct": at_most(0.10), "mw_bought_le25pct": at_most(0.25),
        "loss_at_max": mx["loss_frac"] if mx is not None else math.nan,
        "eur_per_mw_bought_y": (mx["loss_eur_mw_y"] / mx["mw_bought_per_pbat"])
        if mx is not None else math.nan,
    }


def summarize(all_: pd.DataFrame) -> str:
    """Per zone × profile × duration: max MW bought, MW bought at <=10/25 % loss,
    loss at k=0, average price of a bought MW at the max."""
    out = []
    base = all_[all_["peak_per_pbat"] == PEAK_PER_PBAT]
    fmt = (".0f", ",.0f", ".1%", ".1%", ".2f", ".2f", ".2f", ".1%", ",.0f")
    for (prof, dur), g in base.groupby(["profile", "duration_h"]):
        t = pd.DataFrame([{"zone": z} | _zone_row(gz) for z, gz in g.groupby("zone")])
        t = t.sort_values("ceiling_eur_mw_y", ascending=False)
        out.append(f"\n### {prof} load, {dur:.0f} h battery (peak = {PEAK_PER_PBAT:.0f} × P_bat)\n")
        out.append(t.to_markdown(index=False, floatfmt=fmt))
    sens = all_[all_["peak_per_pbat"] != PEAK_PER_PBAT]
    if len(sens):
        out.append("\n### Sensitivity — site peak vs battery power (DE-LU / ES / CH)\n")
        keys = ["zone", "duration_h", "profile", "peak_per_pbat"]
        rows = [dict(zip(keys, k, strict=True)) | _zone_row(g) for k, g in sens.groupby(keys)]
        cols = keys + ["loss_k0", "max_mw_bought_per_pbat", "loss_at_max"]
        out.append(pd.DataFrame(rows)[cols].to_markdown(
            index=False, floatfmt=("", ".0f", "", ".0f", ".1%", ".2f", ".1%")))
    return "\n".join(out)


def plot(all_: pd.DataFrame, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    base = all_[(all_["peak_per_pbat"] == PEAK_PER_PBAT) & (all_["profile"] == "cooling")]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
    for ax, dur in zip(axes, DURATIONS, strict=True):
        g = base[base["duration_h"] == dur]
        for z, gz in g.groupby("zone"):
            gz = gz[gz["feasible"]].sort_values("mw_bought_per_pbat")
            lw, alpha = (2.2, 1.0) if z in SENS_ZONES else (0.8, 0.35)
            ax.plot(gz["mw_bought_per_pbat"], gz["loss_frac"] * 100, lw=lw, alpha=alpha,
                    label=z if z in SENS_ZONES else None)
        ax.axvline(0, color="k", lw=0.6, ls="--")
        ax.set_title(f"cooling-peaked DC, {dur:.0f} h battery, peak = 5 × P_bat")
        ax.set_xlabel("MW of connection bought [× P_bat]  (negative: extra MW requested)")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("arbitrage revenue lost vs ceiling  [%]")
    axes[0].legend(title="highlighted", loc="upper left")
    fig.suptitle(f"Stage 1 — what a MW of connection costs in arbitrage ({START} → {END})")
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zones", nargs="*", default=list(ZONES))
    ap.add_argument("--quick", action="store_true", help="skip the peak sensitivity")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    tag = f"connection-cap-{START}_{END}"
    all_ = run(a.zones, a.quick)
    all_.to_csv(OUT / f"{tag}.csv", index=False)
    md = summarize(all_)
    (OUT / f"{tag}.md").write_text(
        f"# Stage 1 — connection cap sweep {START} → {END}\n\n"
        f"Protocol: experiments/PROTOCOL-connection-cap.md. Battery 1 MW, RTE 85 %, 1.5 cyc/d; "
        f"site peak = {PEAK_PER_PBAT:.0f} × P_bat; profiles flat (PUE 1.35) and cooling "
        f"(PUE 1.10–1.35). MW bought = site peak − cap, per unit of battery power. "
        f"Zones: {all_['zone'].nunique()}.\n" + md + "\n")
    plot(all_, OUT / f"{tag}.png")
    print(md)
    print(f"\nwrote {OUT / tag}.csv/.md/.png")


if __name__ == "__main__":
    main()
