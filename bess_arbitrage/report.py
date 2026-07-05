"""Auto-published monthly report: the bench, the sequential reality check and
the atlas headlines for one calendar month, rendered to markdown.

Written by the GitHub Action on the 2nd of each month (previous month), or by
hand:  uv run python -m bess_arbitrage.report --month 2026-06
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from .atlas import ZONES, run_atlas
from .bench import run_bench, run_sequential
from .insights import atlas_headlines, monthly_spread
from .model import Battery
from .prices import fetch_day_ahead

# Same shortlist the UI uses for headlines: representative, fast, rate-limit friendly.
HEADLINE_ZONES = ("DE-LU", "FR", "NL", "BE", "ES", "HU", "RO", "PL", "IT-North", "NO1")


def month_bounds(month: str) -> tuple[str, str]:
    """'2026-06' -> ('2026-06-01', '2026-06-30')."""
    y, m = int(month[:4]), int(month[5:7])
    last = (date(y + (m == 12), m % 12 + 1, 1) - pd.Timedelta(days=1)).day
    return f"{month}-01", f"{month}-{last:02d}"


def previous_month(today: date | None = None) -> str:
    t = today or date.today()
    y, m = (t.year - 1, 12) if t.month == 1 else (t.year, t.month - 1)
    return f"{y}-{m:02d}"


def build_report(month: str, bat: Battery) -> str:
    start, end = month_bounds(month)
    bench = run_bench(start, end, bat)
    seq = run_sequential(start, end, bat)

    # Spread trend: 6 months of context ending with the report month.
    trend_start = f"{previous_month(date(int(month[:4]), int(month[5:7]), 1) - pd.Timedelta(days=150))}-01"
    spread = monthly_spread(fetch_day_ahead("DE-LU", trend_start, end))

    zones = {z: ZONES[z] for z in HEADLINE_ZONES}
    atlas, skipped = run_atlas(start, end, bat, zones)
    headlines = atlas_headlines(atlas)

    split_b = {k: f"{v:,.0f}" for k, v in bench["split_eur"].items()}
    split_s = {k: f"{v:,.0f}" for k, v in seq["split_eur"].items()}
    tbl = atlas.drop(columns=["lat", "lon"]).copy()
    tbl["ceiling_eur_mw_y"] = tbl["ceiling_eur_mw_y"].round(0).map("{:,.0f}".format)
    for c in ("capture_rolling", "capture_persistence"):
        tbl[c] = (tbl[c] * 100).round(1)

    lines = [
        f"# BESS monthly report — {month}",
        "",
        f"Auto-generated from settled day-ahead (energy-charts.info) and German FCR/aFRR "
        f"capacity prices (regelleistung.net). Battery: {bat.power_mw:g} MW / "
        f"{bat.duration_h:g} h, RTE {bat.rte:.0%}, {bat.max_cycles_per_day:g} cycles/day.",
        "",
        "## Headlines",
        "",
        *[f"- {h}" for h in headlines],
        f"- Operating gate-by-gate on yesterday's information kept "
        f"**{seq['capture']:.0%}** of the stacked perfect-foresight ceiling this month.",
        "",
        "## Germany: day-ahead vs FCR/aFRR stack (perfect-foresight ceiling)",
        "",
        "| metric | EUR/MW/year |",
        "|---|---:|",
        f"| Day-ahead arbitrage only | {bench['da_only_eur_mw_y']:,.0f} |",
        f"| Stacked with FCR/aFRR capacity | {bench['stack_eur_mw_y']:,.0f} |",
        f"| Uplift | {bench['uplift_pct']:+.1f}% |",
        "",
        f"Window split (EUR, {bench['hours']} h): {split_b}",
        "",
        "## Reality check: gate-by-gate operation (no hindsight)",
        "",
        "| metric | EUR |",
        "|---|---:|",
        f"| Stacked ceiling (settled days) | {seq['ceiling_eur']:,.0f} |",
        f"| Sequential operation | {seq['seq_eur']:,.0f} |",
        f"| **Stack capture** | **{seq['capture']:.1%}** |",
        "",
        f"Split: {split_s}. FCR bid as price-taker at the clearing price; aFRR pay-as-bid "
        f"at yesterday's mean, awarded only when in merit.",
        "",
        "## Evening spread trend (DE-LU, evening peak minus midday trough)",
        "",
        spread.round(1).to_markdown(),
        "",
        f"## Zone snapshot — {month}",
        "",
        tbl.to_markdown(index=False),
        "",
    ]
    if skipped:
        lines += [f"Zones skipped (no data): {', '.join(skipped)}", ""]
    lines += [
        "---",
        "*Method: perfect-foresight LP ceiling (HiGHS); capacity revenue only, aFRR "
        "activation energy not modeled yet; capture ratios show what realistic "
        "information keeps of that ceiling. Details in the repo README.*",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the monthly markdown report")
    ap.add_argument("--month", default=previous_month(), help="YYYY-MM (default: last month)")
    ap.add_argument("--out", default="reports", help="output directory")
    a = ap.parse_args()

    md = build_report(a.month, Battery())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{a.month}.md"
    path.write_text(md)
    print(f"report -> {path}")


if __name__ == "__main__":
    main()
