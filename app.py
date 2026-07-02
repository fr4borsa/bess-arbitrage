"""Streamlit UI — arbitraggio BESS sui mercati day-ahead europei.
Tab 1: un mercato nel dettaglio (prezzo + dispatch).
Tab 2: mappa Europa — dove conviene posizionare il BESS.
Run:  uv run streamlit run app.py
"""
from __future__ import annotations

import altair as alt
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from bess_arbitrage.capture import persistence_forecast
from bess_arbitrage.model import Battery, optimize
from bess_arbitrage.prices import fetch_day_ahead

st.set_page_config(page_title="BESS · sala controllo", layout="wide")

# Token di DESIGN.md — ogni colore a schermo viene da qui.
C = {"bg": "#12161F", "surface": "#1B2230", "border": "#2A3347", "track": "#232B3B",
     "text": "#D8DEE9", "muted": "#8A94A6", "amber": "#F2A93B", "cyan": "#5BC8D8",
     "green": "#59B26B", "red": "#E06456"}

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono:wght@400;600&display=swap');
html, body, [data-testid="stAppViewContainer"] *:not([data-testid="stIconMaterial"]) {{
  font-family: 'IBM Plex Sans', sans-serif; }}
[data-testid="stMetricValue"], [data-testid="stMetricDelta"], code, .mono {{
  font-family: 'IBM Plex Mono', monospace !important; }}
[data-testid="stMetric"] {{ background: {C['surface']}; border: 1px solid {C['border']};
  border-radius: 6px; padding: 12px 16px; }}
[data-testid="stMetricValue"] {{ font-size: clamp(1.02rem, 1.6vw, 1.45rem); }}
[data-testid="stMetricLabel"] p {{ color: {C['muted']}; text-transform: uppercase;
  letter-spacing: .08em; font-size: .72rem; }}
[data-testid="stWidgetLabel"] p {{ color: {C['muted']}; }}
@media (max-width: 900px) {{
  [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; }}
  [data-testid="stHorizontalBlock"] [data-testid="stColumn"] {{ min-width: 150px; flex: 1 1 30%; }}
}}
.eyebrow {{ font-family: 'IBM Plex Mono', monospace; color: {C['muted']};
  text-transform: uppercase; letter-spacing: .14em; font-size: .75rem; }}
h1 {{ font-weight: 600; letter-spacing: -.01em; }}
</style>
<div class="eyebrow">mercati day-ahead · EU · prezzi reali energy-charts</div>
""", unsafe_allow_html=True)
st.title("BESS — sala controllo arbitraggio")


def capture_instrument(ceiling_y: float, real_y: float, ratio: float) -> str:
    """Signature element (DESIGN.md): ceiling → reale, gauge flat ambra."""
    return f"""
<div style="background:{C['surface']};border:1px solid {C['border']};border-radius:6px;
            padding:18px 22px;margin:6px 0 14px;">
  <div class="eyebrow">strumento capture — quanto del tetto porta a casa una strategia reale (persistence)</div>
  <div style="display:flex;align-items:baseline;gap:14px;margin-top:10px;flex-wrap:wrap;
              font-family:'IBM Plex Mono',monospace;">
    <span style="color:{C['muted']};font-size:1.05rem;">ceiling {ceiling_y:,.0f}</span>
    <span style="color:{C['cyan']};">→</span>
    <span style="color:{C['amber']};font-size:1.9rem;font-weight:600;">{real_y:,.0f} €/MW·anno</span>
    <span style="color:{C['amber']};font-size:1.2rem;margin-left:auto;">{ratio:.1%}</span>
  </div>
  <div style="height:10px;background:{C['track']};border-radius:5px;margin-top:12px;overflow:hidden;">
    <div style="height:100%;width:{ratio * 100:.1f}%;background:{C['amber']};"></div>
  </div>
</div>"""


def panel(text: str, accent: str) -> str:
    """Sostituto on-token di st.info/st.success (i default Streamlit sono bannati)."""
    return (f'<div style="background:{C["surface"]};border:1px solid {C["border"]};'
            f'border-left:3px solid {accent};border-radius:6px;padding:12px 16px;'
            f'color:{C["text"]};font-size:.92rem;">{text}</div>')

# Bidding zone -> (lat, lon) centroide, per la mappa.
ZONES = {
    "DE-LU": (51.0, 9.0), "FR": (46.6, 2.4), "BE": (50.6, 4.7),
    "NL": (52.1, 5.3), "AT": (47.6, 14.1), "CH": (46.8, 8.2),
    "ES": (40.2, -3.7), "PL": (52.1, 19.4), "IT-North": (45.5, 9.5),
    "DK1": (56.0, 9.2),
}

s = st.sidebar
s.header("Batteria")
power = s.number_input("Potenza (MW)", 0.1, 100.0, 1.0, 0.5)
duration = s.number_input("Durata (h)", 0.5, 12.0, 2.0, 0.5)
rte = s.slider("RTE (round-trip)", 0.5, 1.0, 0.85)
capex = s.number_input("Capex (€/kWh)", 10.0, 1000.0, 125.0, 5.0)
cycles = s.number_input("Cicli/giorno (0 = illimitati)", 0.0, 10.0, 1.5, 0.5)
bat = Battery(power, duration, rte, capex, cycles or None)


@st.cache_data(show_spinner="Scarico i prezzi…")
def load_prices(bzn: str, start: str, end: str) -> pd.Series:
    return fetch_day_ahead(bzn, start, end)


tab_mkt, tab_map = st.tabs(["Mercato (dettaglio)", "Mappa Europa"])

# ---------------------------------------------------------------------------
# TAB 1 — un mercato nel dettaglio
# ---------------------------------------------------------------------------
with tab_mkt:
    c = st.columns(3)
    bzn = c[0].selectbox("Zona", list(ZONES), 0)
    start = c[1].date_input("Inizio", pd.Timestamp("2026-06-22")).isoformat()
    end = c[2].date_input("Fine", pd.Timestamp("2026-06-28")).isoformat()

    try:
        px = load_prices(bzn, start, end)
    except Exception as e:
        st.error(f"Niente prezzi per {bzn} {start}..{end}: {e}")
        st.stop()

    res = optimize(px, bat)
    d = res.dispatch

    h = px.index.hour
    evening = px[(h >= 17) & (h <= 21)].resample("1D").max()
    midday = px[(h >= 10) & (h <= 15)].resample("1D").min()
    spread = (evening - midday).mean()

    m = st.columns(5)
    m[0].metric("Ceiling €/MW/anno", f"{res.revenue_per_mw_year:,.0f}")
    m[1].metric("Payback (anni)", f"{res.simple_payback_years:.1f}")
    m[2].metric("Prezzo medio €/MWh", f"{px.mean():.0f}")
    m[3].metric("Picco €/MWh", f"{px.max():.0f}")
    m[4].metric("Spread serale", f"{spread:.0f} €")

    @st.cache_data(show_spinner="Eseguo la strategia realistica (persistence)…")
    def run_capture(bzn: str, start: str, end: str, p: float, dur: float, r: float,
                    cx: float, cyc: float) -> tuple[float, float, int]:
        d0 = (pd.Timestamp(start) - pd.Timedelta(days=1)).date().isoformat()
        c = persistence_forecast(fetch_day_ahead(bzn, d0, end), Battery(p, dur, r, cx, cyc or None))
        return c.ceiling_eur, c.revenue_eur, c.hours

    try:
        ceil_eur, real_eur, hours = run_capture(bzn, start, end, power, duration, rte, capex, cycles)
        per_mw_y = 8760 / hours / power
        st.markdown(capture_instrument(ceil_eur * per_mw_y, real_eur * per_mw_y,
                                       real_eur / ceil_eur), unsafe_allow_html=True)
    except Exception:
        st.caption("Strategia realistica non calcolabile sul periodo (serve almeno il giorno precedente).")

    st.subheader("Prezzo e punti di guadagno — verde compra basso · ambra vendi alto")
    df = d.reset_index()
    df.columns = ["t", "price", "charge", "discharge", "soc"]
    base = alt.Chart(df).encode(x=alt.X("t:T", title=None))
    price_line = base.mark_line(color=C["muted"], strokeWidth=1.2, opacity=0.7).encode(
        y=alt.Y("price:Q", title="€/MWh"))
    buy = (base.transform_filter("datum.charge > 0.001")
           .mark_circle(color=C["green"], opacity=0.9)
           .encode(y="price:Q", size=alt.Size("charge:Q", legend=None, scale=alt.Scale(range=[30, 300])),
                   tooltip=[alt.Tooltip("t:T", title="ora"), alt.Tooltip("price:Q", format=".0f"),
                            alt.Tooltip("charge:Q", title="carica MWh", format=".2f")]))
    sell = (base.transform_filter("datum.discharge > 0.001")
            .mark_circle(color=C["amber"], opacity=0.9)
            .encode(y="price:Q", size=alt.Size("discharge:Q", legend=None, scale=alt.Scale(range=[30, 300])),
                    tooltip=[alt.Tooltip("t:T", title="ora"), alt.Tooltip("price:Q", format=".0f"),
                             alt.Tooltip("discharge:Q", title="scarica MWh", format=".2f")]))
    chart = ((price_line + buy + sell).interactive()
             .configure_axis(labelFont="IBM Plex Mono", titleFont="IBM Plex Mono",
                             labelColor=C["muted"], titleColor=C["muted"]))
    st.altair_chart(chart, use_container_width=True)

    st.subheader("Stato di carica (SOC)")
    st.area_chart(d["soc"], height=170, color=C["cyan"])

# ---------------------------------------------------------------------------
# TAB 2 — mappa Europa: dove conviene il BESS
# ---------------------------------------------------------------------------
with tab_map:
    cc = st.columns(2)
    mstart = cc[0].date_input("Inizio periodo", pd.Timestamp("2026-04-01"), key="ms").isoformat()
    mend = cc[1].date_input("Fine periodo", pd.Timestamp("2026-06-28"), key="me").isoformat()

    @st.cache_data(show_spinner="Calcolo il ceiling per zona…")
    def zone_revenue(start: str, end: str, p: float, dur: float, r: float, cx: float, cyc: float) -> pd.DataFrame:
        import time as _t
        rows, errs = [], []
        b = Battery(p, dur, r, cx, cyc or None)
        for z, (lat, lon) in ZONES.items():
            try:
                px = fetch_day_ahead(z, start, end)
                res = optimize(px, b)
                rows.append({"zona": z, "lat": lat, "lon": lon,
                             "rev": res.revenue_per_mw_year, "payback": res.simple_payback_years})
            except Exception:
                errs.append(z)
            _t.sleep(0.8)  # gentile col rate-limit di energy-charts
        return pd.DataFrame(rows), errs

    dfm, errs = zone_revenue(mstart, mend, power, duration, rte, capex, cycles)
    if dfm.empty:
        st.error("Nessuna zona ha restituito dati per il periodo scelto.")
        st.stop()

    lo, hi = dfm["rev"].min(), dfm["rev"].max()
    dfm["norm"] = (dfm["rev"] - lo) / (hi - lo + 1e-9)
    best = dfm.loc[dfm["rev"].idxmax()]

    st.subheader("Clicca sulla mappa per piazzare una batteria — vedi quanto renderebbe lì")
    st.caption("Ambra intensa = arbitraggio più redditizio · raggio ∝ ricavo. "
               "Il click viene assegnato alla bidding zone più vicina.")

    ss = st.session_state
    ss.setdefault("placements", [])
    ss.setdefault("done_clicks", set())

    def zone_color(norm: float) -> str:
        # scala mono-ambra: ambra spenta -> ambra piena (stessa tonalità, solo intensità)
        lo, hi = (0x5E, 0x45, 0x1C), (0xF2, 0xA9, 0x3B)
        return "#" + "".join(f"{int(a + (b - a) * norm):02x}" for a, b in zip(lo, hi))

    fmap = folium.Map(location=[49.5, 8.0], zoom_start=4, tiles="CartoDB dark_matter")
    # il CSS della pagina non entra nell'iframe: tema di popup/tooltip iniettato nella mappa
    fmap.get_root().header.add_child(folium.Element(f"""<style>
      @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&display=swap');
      .leaflet-tooltip, .leaflet-popup-content-wrapper, .leaflet-popup-tip {{
        background: {C['surface']}; color: {C['text']};
        font-family: 'IBM Plex Mono', monospace; border: 1px solid {C['border']};
      }}
      .leaflet-tooltip {{ box-shadow: none; }}
      .leaflet-popup-close-button {{ color: {C['muted']}; }}
    </style>"""))
    for z in dfm.itertuples():
        folium.CircleMarker(
            [z.lat, z.lon], radius=8 + z.norm * 16, color="#D8DEE9", weight=1,
            fill=True, fill_color=zone_color(z.norm), fill_opacity=0.9,
            tooltip=f"{z.zona}: {z.rev:,.0f} €/MW/anno · payback {z.payback:.1f}y",
        ).add_to(fmap)
    for p in ss.placements:
        folium.Marker(
            [p["lat"], p["lon"]], icon=folium.Icon(color="orange", icon="bolt", prefix="fa"),
            popup=f"{power:g} MW / {duration:g}h → {p['zona']}<br>"
                  f"<b>{p['rev']:,.0f} €/MW/anno</b> · payback {p['payback']:.1f}y",
        ).add_to(fmap)

    out = st_folium(fmap, height=520, use_container_width=True, key="mappa_eu")

    click = out.get("last_clicked")
    if click:
        key = (round(click["lat"], 5), round(click["lng"], 5))
        if key not in ss.done_clicks:
            ss.done_clicks.add(key)
            # ponytail: zona = centroide più vicino, niente poligoni; geojson zone se servirà precisione ai confini
            zrow = dfm.loc[((dfm.lat - key[0]) ** 2 + (dfm.lon - key[1]) ** 2).idxmin()]
            ss.placements.append({"lat": key[0], "lon": key[1], "zona": zrow.zona,
                                  "rev": zrow.rev, "payback": zrow.payback})
            st.rerun()

    if ss.placements:
        last = ss.placements[-1]
        tot = sum(p["rev"] for p in ss.placements) * power
        c = st.columns(3)
        c[0].metric(f"Ultima: {last['zona']} — €/MW/anno", f"{last['rev']:,.0f}",
                    f"{(last['rev'] / best.rev - 1) * 100:+.0f}% vs migliore ({best.zona})")
        c[1].metric("Portafoglio", f"{len(ss.placements)} BESS", f"{tot:,.0f} €/anno totali")
        if last["zona"] == best.zona:
            c[2].markdown(panel("Zona migliore trovata: qui il capture conta di più.",
                                C["green"]), unsafe_allow_html=True)
        else:
            c[2].markdown(panel(f"La zona migliore è <b>{best.zona}</b> — vale "
                                f"<span class='mono'>{best.rev - last['rev']:,.0f}</span> €/MW/anno in più.",
                                C["amber"]), unsafe_allow_html=True)
        if st.button("Svuota portafoglio"):
            ss.placements, ss.done_clicks = [], set()
            st.rerun()

    st.dataframe(
        dfm[["zona", "rev", "payback"]].sort_values("rev", ascending=False)
        .rename(columns={"rev": "€/MW/anno", "payback": "payback (anni)"})
        .style.format({"€/MW/anno": "{:,.0f}", "payback (anni)": "{:.1f}"}),
        use_container_width=True, hide_index=True,
    )
    if errs:
        st.caption(f"Zone senza dati nel periodo (saltate): {', '.join(errs)}")
    st.caption("Ceiling perfect-foresight per zona: stesso BESS, stesso periodo. "
               "Prossima vista: capture-ratio (reale vs tetto).")
