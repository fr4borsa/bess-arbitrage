"""Streamlit UI — BESS revenue insights on European power markets.

Insight-first: the app opens on live answers (what a battery earned yesterday,
which zone leads, what information is worth), the calculator is the sidebar.
Tabs: Today · Day replay · Europe map · Trends.
Run:  uv run streamlit run app.py
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from app_map import gridmap_url
from bess_arbitrage.activation import activation_margin, fetch_afrr_mol_de
from bess_arbitrage.atlas import ZONES, run_atlas
from bess_arbitrage.balancing import fetch_products_de
from bess_arbitrage.bench import run_sequential
from bess_arbitrage.capture import persistence_forecast, rolling_day_ahead
from bess_arbitrage.insights import atlas_headlines, day_stack, monthly_spread
from bess_arbitrage.model import Battery
from bess_arbitrage.prices import fetch_day_ahead

st.set_page_config(page_title="BESS · control room", layout="wide")

# Tokens from DESIGN.md — every color on screen comes from here.
C = {"bg": "#12161F", "surface": "#1B2230", "border": "#2A3347", "track": "#232B3B",
     "text": "#D8DEE9", "muted": "#8A94A6", "amber": "#F2A93B", "cyan": "#5BC8D8",
     "green": "#59B26B", "red": "#E06456"}
# Per-market colors, used consistently in every view: DA = neutral ink,
# FCR = cyan, aFRR POS = dim amber (the pure amber #F2A93B stays reserved for
# revenue figures — the signature), aFRR NEG = green (charge side).
MKT = {"da": C["muted"], "fcr": C["cyan"], "afrr_pos": "#C08430", "afrr_neg": C["green"]}
MKT_LABEL = {"da": "day-ahead", "fcr": "FCR", "afrr_pos": "aFRR pos", "afrr_neg": "aFRR neg"}

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono:wght@400;600&display=swap');
html, body, [data-testid="stAppViewContainer"] *:not([data-testid="stIconMaterial"]) {{
  font-family: 'IBM Plex Sans', sans-serif; }}
[data-testid="stMetricValue"], [data-testid="stMetricDelta"], code, .mono, .mono * {{
  font-family: 'IBM Plex Mono', monospace !important; }}
[data-testid="stMetricDelta"] {{ border-radius: 6px !important; }}
[data-testid="stMetric"] {{ background: {C['surface']}; border: 1px solid {C['border']};
  border-radius: 6px; padding: 12px 16px; }}
[data-testid="stMetricValue"] {{ font-size: clamp(1.02rem, 1.6vw, 1.45rem); }}
[data-testid="stMetricLabel"] p {{ color: {C['muted']}; text-transform: uppercase;
  letter-spacing: .08em; font-size: .72rem;
  font-family: 'IBM Plex Mono', monospace !important; }}
[data-testid="stWidgetLabel"] p {{ color: {C['muted']}; }}
@media (max-width: 900px) {{
  [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; }}
  [data-testid="stHorizontalBlock"] [data-testid="stColumn"] {{ min-width: 150px; flex: 1 1 30%; }}
}}
.eyebrow {{ font-family: 'IBM Plex Mono', monospace !important; color: {C['muted']};
  text-transform: uppercase; letter-spacing: .14em; font-size: .75rem; }}
h1 {{ font-weight: 600; letter-spacing: -.01em; }}
</style>
<div class="eyebrow">EU power markets · real auction data · energy-charts + regelleistung</div>
""", unsafe_allow_html=True)
st.title("BESS — revenue control room")


# ---------------------------------------------------------------------------
# shared HTML instruments (DESIGN.md signature language)
# ---------------------------------------------------------------------------
def instrument(eyebrow: str, main: str, side: str, bar: list[tuple[str, float]],
               legend: list[tuple[str, str, str]] | None = None) -> str:
    """Panel with big amber mono number + segmented flat gauge (share-of-total)."""
    total = sum(v for _, v in bar) or 1.0
    segs = "".join(
        f'<div style="height:100%;width:{max(0.0, v) / total * 100:.2f}%;'
        f'background:{c};float:left;"></div>' for c, v in bar)
    leg = ""
    if legend:
        # each swatch+label pair is nowrap so wraps happen between pairs, never inside
        leg = ('<div class="mono" style="display:flex;gap:16px;flex-wrap:wrap;margin-top:8px;'
               'font-size:.8rem;">'
               + "".join(f'<span style="white-space:nowrap;color:{C["muted"]};">'
                         f'<span style="color:{c};">■</span> {n} '
                         f'<span style="color:{C["text"]};">{v}</span></span>'
                         for n, c, v in legend) + "</div>")
    return f"""
<div style="background:{C['surface']};border:1px solid {C['border']};border-radius:6px;
            padding:18px 22px;margin:6px 0 14px;">
  <div class="eyebrow">{eyebrow}</div>
  <div class="mono"
       style="display:flex;align-items:baseline;gap:14px;margin-top:10px;flex-wrap:wrap;">
    <span style="color:{C['amber']};font-size:1.9rem;font-weight:600;">{main}</span>
    <span style="color:{C['muted']};font-size:1.0rem;margin-left:auto;">{side}</span>
  </div>
  <div style="height:10px;background:{C['track']};border-radius:5px;
              margin-top:12px;overflow:hidden;">{segs}</div>
  {leg}
</div>"""


def gauge_row(label: str, value: str, ratio: float, color: str) -> str:
    return f"""
<div class="mono" style="display:grid;grid-template-columns:180px 1fr 90px;gap:12px;
            align-items:center;margin:7px 0;font-size:.85rem;">
  <span style="color:{C['muted']};">{label}</span>
  <div style="height:8px;background:{C['track']};border-radius:4px;overflow:hidden;">
    <div style="height:100%;width:{ratio * 100:.1f}%;background:{color};"></div>
  </div>
  <span style="color:{C['text']};text-align:right;">{value}</span>
</div>"""


def panel(text: str, accent: str) -> str:
    """On-token substitute for st.info/st.success (Streamlit defaults are banned)."""
    return (f'<div style="background:{C["surface"]};border:1px solid {C["border"]};'
            f'border-left:3px solid {accent};border-radius:6px;padding:12px 16px;'
            f'color:{C["text"]};font-size:.92rem;margin:4px 0;">{text}</div>')


def headline_list(lines: list[str]) -> str:
    rows = "".join(
        f'<div style="display:flex;gap:12px;margin:9px 0;align-items:baseline;">'
        f'<span style="color:{C["amber"]};font-family:\'IBM Plex Mono\',monospace;">▸</span>'
        f'<span style="color:{C["text"]};font-size:.95rem;">{ln}</span></div>' for ln in lines)
    return (f'<div style="background:{C["surface"]};border:1px solid {C["border"]};'
            f'border-radius:6px;padding:12px 18px;">'
            f'<div class="eyebrow">what the atlas says — auto-generated from the ranking</div>'
            f'{rows}</div>')


# ---------------------------------------------------------------------------
# sidebar — the calculator, demoted but always available
# ---------------------------------------------------------------------------
s = st.sidebar
s.header("Battery")
power = s.number_input("Power (MW)", 0.1, 100.0, 1.0, 0.5)
duration = s.number_input("Duration (h)", 0.5, 12.0, 2.0, 0.5)
rte = s.slider("RTE (round-trip)", 0.5, 1.0, 0.85)
capex = s.number_input("Capex (€/kWh)", 10.0, 1000.0, 125.0, 5.0)
cycles = s.number_input("Cycles/day (0 = unlimited)", 0.0, 10.0, 1.5, 0.5)
bat = Battery(power, duration, rte, capex, cycles or None)

YESTERDAY = (pd.Timestamp.now(tz="Europe/Berlin") - pd.Timedelta(days=1)).date()


@st.cache_data(show_spinner="Fetching prices…")
def load_prices(bzn: str, start: str, end: str) -> pd.Series:
    return fetch_day_ahead(bzn, start, end)


@st.cache_data(show_spinner="Fetching German capacity auctions…")
def load_products(day_iso: str) -> pd.DataFrame:
    return fetch_products_de([dt.date.fromisoformat(day_iso)])


def local_day(bzn: str, day: dt.date) -> pd.Series:
    """One complete local (Europe/Berlin) day of hourly prices."""
    px = load_prices(bzn, (day - dt.timedelta(days=1)).isoformat(),
                     (day + dt.timedelta(days=1)).isoformat()).tz_convert("Europe/Berlin")
    return px[px.index.date == day]


def replay_views(ds: dict) -> None:
    """Shared day view: split metrics, price+dispatch chart, capacity bands, SOC."""
    sp = ds["split_eur"]
    m = st.columns(5)
    m[0].metric("Stack total €", f"{ds['stack_eur']:,.0f}", f"{ds['uplift_pct']:+.0f}% vs DA-only")
    m[1].metric("Day-ahead €", f"{sp.get('da_eur', 0):,.0f}")
    m[2].metric("FCR €", f"{sp.get('fcr_eur', 0):,.0f}")
    m[3].metric("aFRR pos €", f"{sp.get('afrr_pos_eur', 0):,.0f}")
    m[4].metric("aFRR neg €", f"{sp.get('afrr_neg_eur', 0):,.0f}")

    d = ds["dispatch"]
    idle = int(((d[["fcr", "afrr_pos", "afrr_neg"]].sum(axis=1) > 0.01)
                & (d["charge"] + d["discharge"] < 0.01)).sum()) if "fcr" in d else 0
    if idle:
        st.markdown(panel(f"<b>{idle} of {len(d)} hours</b> earning capacity while standing "
                          f"still — paid for headroom, not for energy.", C["amber"]),
                    unsafe_allow_html=True)

    df = d.reset_index()
    df = df.rename(columns={df.columns[0]: "t"})
    base = alt.Chart(df).encode(x=alt.X("t:T", title=None))
    price_line = base.mark_line(color=C["muted"], strokeWidth=1.2, opacity=0.7).encode(
        y=alt.Y("price:Q", title="€/MWh"))
    buy = (base.transform_filter("datum.charge > 0.001")
           .mark_circle(color=C["green"], opacity=0.9)
           .encode(y="price:Q",
                   size=alt.Size("charge:Q", legend=None, scale=alt.Scale(range=[30, 300])),
                   tooltip=[alt.Tooltip("t:T", title="hour"), alt.Tooltip("price:Q", format=".0f"),
                            alt.Tooltip("charge:Q", title="charge MWh", format=".2f")]))
    sell = (base.transform_filter("datum.discharge > 0.001")
            .mark_circle(color=C["amber"], opacity=0.9)
            .encode(y="price:Q",
                    size=alt.Size("discharge:Q", legend=None, scale=alt.Scale(range=[30, 300])),
                    tooltip=[alt.Tooltip("t:T", title="hour"), alt.Tooltip("price:Q", format=".0f"),
                             alt.Tooltip("discharge:Q", title="discharge MWh", format=".2f")]))
    st.subheader("Price and dispatch — green buys low · amber sells high")
    st.altair_chart((price_line + buy + sell).interactive()
                    .configure_axis(labelFont="IBM Plex Mono", titleFont="IBM Plex Mono",
                                    labelColor=C["muted"], titleColor=C["muted"]),
                    use_container_width=True)

    if "fcr" in d.columns:
        st.subheader("Committed capacity per 4h block (MW)")
        long = df.melt(id_vars="t", value_vars=[c for c in ("fcr", "afrr_pos", "afrr_neg")
                                                if c in df.columns],
                       var_name="market", value_name="mw")
        long["market"] = long["market"].map(MKT_LABEL)
        band = (alt.Chart(long)
                .mark_area(interpolate="step-after", opacity=0.55)
                .encode(x=alt.X("t:T", title=None),
                        y=alt.Y("mw:Q", stack=True, title="MW"),
                        color=alt.Color("market:N", legend=alt.Legend(orient="top", title=None),
                                        scale=alt.Scale(domain=[MKT_LABEL["fcr"],
                                                                MKT_LABEL["afrr_pos"],
                                                                MKT_LABEL["afrr_neg"]],
                                                        range=[MKT["fcr"], MKT["afrr_pos"],
                                                               MKT["afrr_neg"]])),
                        tooltip=["t:T", "market:N", alt.Tooltip("mw:Q", format=".2f")]))
        st.altair_chart(band.configure_axis(labelFont="IBM Plex Mono", titleFont="IBM Plex Mono",
                                            labelColor=C["muted"], titleColor=C["muted"]),
                        use_container_width=True)

    st.subheader("State of charge (SOC)")
    soc_ch = (alt.Chart(df).mark_area(color=C["cyan"], opacity=0.8)
              .encode(x=alt.X("t:T", title=None), y=alt.Y("soc:Q", title="MWh"))
              .properties(height=170)
              .configure_axis(labelFont="IBM Plex Mono", titleFont="IBM Plex Mono",
                              labelColor=C["muted"], titleColor=C["muted"]))
    st.altair_chart(soc_ch, use_container_width=True)


tab_today, tab_replay, tab_map, tab_trends, tab_report = st.tabs(
    ["Today", "Day replay", "Europe map", "Trends", "Report"])

# ---------------------------------------------------------------------------
# TAB 1 — Today: live answers, zero input
# ---------------------------------------------------------------------------
with tab_today:
    try:
        px_yd = local_day("DE-LU", YESTERDAY)
        prod_yd = load_products(YESTERDAY.isoformat())
        if len(px_yd) != 24:
            raise RuntimeError("DST day — 23/25 local hours")
        ds = day_stack(px_yd, prod_yd, bat)
        sp = ds["split_eur"]
        bar = [(MKT[k], max(0.0, sp.get(f"{k}_eur", 0.0))) for k in MKT]
        legend = [(MKT_LABEL[k], MKT[k], f"{sp.get(f'{k}_eur', 0):,.0f} €") for k in MKT]
        st.markdown(instrument(
            f"yesterday · {ds['date']} · germany (DE-LU) · {power:g} MW / "
            f"{bat.capacity_mwh:g} MWh · real auction prices",
            f"{ds['stack_eur']:,.0f} €",
            f"arbitrage alone {ds['da_eur']:,.0f} € → stack {ds['uplift_pct']:+.0f}%",
            bar, legend), unsafe_allow_html=True)
    except Exception as e:
        st.markdown(panel(f"Yesterday's stack unavailable ({e}) — markets data may lag.",
                          C["red"]), unsafe_allow_html=True)

    # ponytail: headline zones only — a full 35-zone sweep on first paint gets
    # rate-limited by energy-charts; the complete ranking lives in Europe map.
    HEADLINE_ZONES = {z: ZONES[z] for z in
                      ("DE-LU", "FR", "NL", "BE", "ES", "HU", "RO", "PL", "IT-North", "NO1")}

    @st.cache_data(show_spinner="Atlas: last 90 days, headline zones (first run ~1 min)…")
    def atlas_90d(end_iso: str, p: float, dur: float, r: float, cx: float, cyc: float):
        start = (dt.date.fromisoformat(end_iso) - dt.timedelta(days=90)).isoformat()
        df, _ = run_atlas(start, end_iso, Battery(p, dur, r, cx, cyc or None),
                          zones=HEADLINE_ZONES, capture=False)
        return df

    try:
        df90 = atlas_90d(YESTERDAY.isoformat(), power, duration, rte, capex, cycles)
        st.markdown(headline_list(atlas_headlines(df90)), unsafe_allow_html=True)
    except Exception as e:
        st.markdown(panel(f"Atlas headlines unavailable: {e}", C["red"]), unsafe_allow_html=True)

    st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)
    st.markdown('<div class="eyebrow">what information is worth — DE-LU, last 30 days, '
                'this battery</div>', unsafe_allow_html=True)

    @st.cache_data(show_spinner="Computing the information ladder (≈1 min, then cached)…")
    def info_ladder(end_iso: str, p: float, dur: float, r: float, cx: float, cyc: float):
        b = Battery(p, dur, r, cx, cyc or None)
        start = (dt.date.fromisoformat(end_iso) - dt.timedelta(days=30)).isoformat()
        px = fetch_day_ahead("DE-LU", start, end_iso)
        roll = rolling_day_ahead(px, b)
        pers = persistence_forecast(px, b)
        seq = run_sequential(start, end_iso, b)
        return roll.ratio, pers.ratio, seq["capture"]

    try:
        r_roll, r_pers, r_seq = info_ladder(YESTERDAY.isoformat(), power, duration, rte,
                                            capex, cycles)
        rows = (gauge_row("perfect foresight", "100%", 1.0, C["muted"])
                + gauge_row("day-ahead horizon", f"{r_roll:.1%}", r_roll, C["cyan"])
                + gauge_row("naive forecast", f"{r_pers:.1%}", r_pers, C["cyan"])
                + gauge_row("stack, operated", f"{r_seq:.1%}", r_seq, C["amber"]))
        st.markdown(f'<div style="background:{C["surface"]};border:1px solid {C["border"]};'
                    f'border-radius:6px;padding:14px 18px;">{rows}</div>',
                    unsafe_allow_html=True)
        st.caption("Each step down is the price of less information: the day-ahead horizon "
                   "costs a few percent, a naive price forecast ~15%, and bidding reserve "
                   "capacity pay-as-bid with yesterday's information leaves ~30% of the "
                   "stacked ceiling on the table.")
        with st.expander("+ aFRR activation band on the operated stack (30 days)"):
            @st.cache_data(show_spinner="Merit orders for 30 days (first run only)…")
            def ladder_band(end_iso: str, p_: float, dur: float, r_: float,
                            cx: float, cyc: float) -> dict:
                from bess_arbitrage.activation import sequential_activation_band
                start = (dt.date.fromisoformat(end_iso) - dt.timedelta(days=29)).isoformat()
                s = run_sequential(start, end_iso,
                                   Battery(p_, dur, r_, cx, cyc or None))
                return {"band": sequential_activation_band(s["awards"], s["px"],
                                                           pause_s=0.3),
                        "seq_eur": s["seq_eur"]}
            if st.session_state.get("band_go") or st.button(
                    "Compute (downloads ~30 merit orders on first run)"):
                st.session_state["band_go"] = True
                b = ladder_band(YESTERDAY.isoformat(), power, duration, rte, capex, cycles)
                cols = st.columns(3)
                for col, (depth, m) in zip(cols, b["band"].items(), strict=True):
                    col.metric(f"depth {depth:.0%}", f"{m['uplift_eur']:+,.0f} €",
                               f"{m['uplift_eur'] / b['seq_eur']:+.1%} vs operated stack")
                st.caption("The operated stack above earns capacity only; activation adds "
                           "this band depending on how deep the TSO calls the merit order. "
                           "Scenario, not data — see the monthly report for the method.")
    except Exception as e:
        st.markdown(panel(f"Information ladder unavailable: {e}", C["red"]),
                    unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# TAB 2 — Day replay: watch the co-optimized battery work a real day
# ---------------------------------------------------------------------------
with tab_replay:
    c = st.columns(3)
    rday = c[0].date_input("Day (DE-LU + German reserve auctions)", YESTERDAY,
                           min_value=dt.date(2020, 7, 1), max_value=YESTERDAY)
    try:
        px_day = local_day("DE-LU", rday)
        if len(px_day) != 24:
            st.markdown(panel("DST switch day (23/25 local hours) — replay needs a plain "
                              "24h day.", C["red"]), unsafe_allow_html=True)
        else:
            ds = day_stack(px_day, load_products(rday.isoformat()), bat)
            replay_views(ds)
            st.caption("Co-optimized with hindsight: the ceiling view of this day. FCR at the "
                       "German clearing price; aFRR at the mean accepted bid (pay-as-bid), "
                       "capacity revenue in the split — activation margin below.")

            disp = ds["dispatch"]
            aw_pos = [float(disp["afrr_pos"].iloc[b * 4]) if "afrr_pos" in disp else 0.0
                      for b in range(6)]
            aw_neg = [float(disp["afrr_neg"].iloc[b * 4]) if "afrr_neg" in disp else 0.0
                      for b in range(6)]
            if any(aw_pos) or any(aw_neg):
                with st.expander("aFRR activation margin — v1 scenario band", expanded=False):
                    @st.cache_data(show_spinner="Merit order for this day…")
                    def load_mol(day_iso: str) -> pd.DataFrame:
                        return fetch_afrr_mol_de(dt.date.fromisoformat(day_iso))
                    try:
                        mol = load_mol(rday.isoformat())
                        cols = st.columns(3)
                        for col, depth in zip(cols, (0.05, 0.15, 0.30), strict=True):
                            m = activation_margin(mol, px_day, aw_pos, aw_neg,
                                                  depth_frac=depth)
                            tot = m["pos_eur"] + m["neg_eur"]
                            col.metric(f"depth {depth:.0%}", f"{tot:+,.0f} €",
                                       f"+{m['throughput_mwh']:.1f} MWh cycled")
                        st.caption("Depth = activated share of the merit order (duty) and "
                                   "settlement depth, coupled; bid at 5% of the MOL, SoC "
                                   "restored at DA. Scenario, not data.")
                    except Exception as e:
                        st.markdown(panel(f"Merit order unavailable: {e}", C["red"]),
                                    unsafe_allow_html=True)
            else:
                st.caption("No aFRR capacity committed this day — no activation margin.")
    except Exception as e:
        st.markdown(panel(f"No data for {rday}: {e}", C["red"]), unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# TAB 3 — Europe map: where the BESS pays off
# ---------------------------------------------------------------------------
with tab_map:
    cc = st.columns(3)
    mstart = cc[0].date_input("Period start", pd.Timestamp("2026-04-01"), key="ms").isoformat()
    mend = cc[1].date_input("Period end", pd.Timestamp(YESTERDAY), key="me").isoformat()
    cap_on = cc[2].toggle("Capture per zone", value=False,
                          help="Rolling day-ahead and persistence for every zone: "
                               "the first computation can take ~2 minutes.")

    @st.cache_data(show_spinner="Atlas: fetching prices and optimizing zone by zone…")
    def zone_atlas(start: str, end: str, p: float, dur: float, r: float, cx: float,
                   cyc: float, capture: bool) -> tuple[pd.DataFrame, list[str]]:
        return run_atlas(start, end, Battery(p, dur, r, cx, cyc or None), capture=capture)

    ss0 = st.session_state
    ss0.setdefault("atlas_requested", False)
    # ponytail: ~35 zones on page load starves the tabs below and trips the
    # energy-charts rate limiter — the full sweep runs only on explicit request.
    if st.button("Run the atlas for this period (~35 zones, minutes on first run)"):
        ss0["atlas_requested"] = True
    dfm = pd.DataFrame()
    if ss0["atlas_requested"]:
        dfm, errs = zone_atlas(mstart, mend, power, duration, rte, capex, cycles, cap_on)
        if dfm.empty:
            st.markdown(panel("No zone returned data for the selected period.", C["red"]),
                        unsafe_allow_html=True)
    else:
        st.markdown(panel("The full European sweep is on demand — press the button. "
                          "The headline zones are already on the Today tab.", C["amber"]),
                    unsafe_allow_html=True)

if not dfm.empty:
  with tab_map:
    st.markdown(headline_list(atlas_headlines(dfm)), unsafe_allow_html=True)

    dfm = dfm.rename(columns={"ceiling_eur_mw_y": "rev", "payback_y": "payback"})
    lo, hi = dfm["rev"].min(), dfm["rev"].max()
    dfm["norm"] = (dfm["rev"] - lo) / (hi - lo + 1e-9)
    best = dfm.loc[dfm["rev"].idxmax()]

    st.subheader("The grid under the numbers — real transmission lines, amber = value")
    st.caption("Choropleth: perfect-foresight ceiling per zone. Cyan lines: 300 kV+ "
               "transmission (OpenInfraMap); zoom in for the lower grid and substations.")

    vals = {z.zone: {"rev": z.rev, "payback": z.payback,
                     "capture": (f"{z.capture_rolling:.0%} / {z.capture_persistence:.0%}"
                                 if cap_on else None)}
            for z in dfm.itertuples()}
    components.iframe(gridmap_url(vals, height=560), height=568)

    ss = st.session_state
    ss.setdefault("placements", [])
    pc = st.columns([2, 1, 1])
    pick = pc[0].selectbox("Place a battery in…", dfm.sort_values("rev", ascending=False).zone)
    if pc[1].button("Add to portfolio"):
        zrow = dfm.loc[dfm.zone == pick].iloc[0]
        ss.placements.append({"zone": zrow.zone, "rev": zrow.rev, "payback": zrow.payback})
        st.rerun()
    if ss.placements and pc[2].button("Clear portfolio"):
        ss.placements = []
        st.rerun()

    if ss.placements:
        last = ss.placements[-1]
        tot = sum(pl["rev"] for pl in ss.placements) * power
        c = st.columns(3)
        c[0].metric(f"Last: {last['zone']} — €/MW/year", f"{last['rev']:,.0f}",
                    f"{(last['rev'] / best.rev - 1) * 100:+.0f}% vs best ({best.zone})")
        c[1].metric("Portfolio", f"{len(ss.placements)} BESS", f"{tot:,.0f} €/year total")
        if last["zone"] == best.zone:
            c[2].markdown(panel("Best zone found: here capture matters most.",
                                C["green"]), unsafe_allow_html=True)
        else:
            c[2].markdown(panel(f"The best zone is <b>{best.zone}</b> — worth "
                                f"<span class='mono'>{best.rev - last['rev']:,.0f}</span> "
                                f"€/MW/year more.",
                                C["amber"]), unsafe_allow_html=True)

    tbl_cols = ["zone", "rev", "payback"] + (
        ["capture_rolling", "capture_persistence"] if cap_on else [])
    names = {"rev": "€/MW/year", "payback": "payback (years)",
             "capture_rolling": "capture rolling", "capture_persistence": "capture persistence"}
    fmt = {"€/MW/year": "{:,.0f}", "payback (years)": "{:.1f}",
           "capture rolling": "{:.1%}", "capture persistence": "{:.1%}"}
    df2 = dfm[tbl_cols].sort_values("rev", ascending=False).rename(columns=names)
    st.dataframe(df2.style.format({c: fmt[c] for c in df2.columns if c in fmt}),
                 use_container_width=True, hide_index=True)
    st.download_button("Download atlas (CSV)",
                       dfm.drop(columns=["lat", "lon", "norm"]).to_csv(index=False),
                       file_name=f"bess-atlas_{mstart}_{mend}.csv")
    if errs:
        st.caption(f"Zones with no data in this period (skipped): {', '.join(errs)}")
    st.caption("Perfect-foresight ceiling per zone: same BESS, same period. "
               "Capture: rolling = LP on same-day prices (day-ahead auction view); "
               "persistence = yesterday's prices as forecast, settled against today's real prices.")

# ---------------------------------------------------------------------------
# TAB 4 — Trends: the widening duck curve
# ---------------------------------------------------------------------------
with tab_trends:
    tz = st.selectbox("Zone", list(ZONES), 0, key="trend_zone")
    try:
        px_hist = load_prices(tz, "2026-01-01", YESTERDAY.isoformat()).tz_convert("Europe/Berlin")
        sp = monthly_spread(px_hist).reset_index()
        sp.columns = ["month", "spread_eur"]
        # string labels: Vega would re-read tz-aware timestamps as UTC and
        # shift every month label back by one
        sp["month"] = sp["month"].dt.strftime("%b %Y")
        st.subheader("Evening peak minus midday trough — average daily spread by month")
        ch = (alt.Chart(sp).mark_bar(color=C["amber"], size=34)
              .encode(x=alt.X("month:N", title=None, sort=None,
                              axis=alt.Axis(labelAngle=0)),
                      y=alt.Y("spread_eur:Q", title="€/MWh"),
                      tooltip=[alt.Tooltip("month:N", title="month"),
                               alt.Tooltip("spread_eur:Q", format=".0f", title="spread €")])
              .configure_axis(labelFont="IBM Plex Mono", titleFont="IBM Plex Mono",
                              labelColor=C["muted"], titleColor=C["muted"]))
        st.altair_chart(ch, use_container_width=True)
        st.caption("The spread — not the price level — is what a battery earns. More solar "
                   "pushes middays toward zero and steepens evening ramps, so this bar is "
                   "the structural tailwind behind every number in this app. Months with "
                   "fewer than 15 complete days are hidden.")
    except Exception as e:
        st.markdown(panel(f"No trend data for {tz}: {e}", C["red"]), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# TAB 5 — Report: the auto-published monthly numbers, readable in-app
# ---------------------------------------------------------------------------
with tab_report:
    reps = sorted(Path("reports").glob("*.md"), reverse=True)
    if not reps:
        st.markdown(panel("No report yet — the GitHub Action publishes one on the 2nd "
                          "of each month, or run: uv run python -m bess_arbitrage.report",
                          C["amber"]), unsafe_allow_html=True)
    else:
        which = st.selectbox("Month", [r.stem for r in reps])
        st.markdown((Path("reports") / f"{which}.md").read_text())
        st.caption("Generated by bess_arbitrage.report — also on GitHub under reports/.")
