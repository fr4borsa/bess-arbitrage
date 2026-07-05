"""Control-room grid map: MapLibre GL embed for the Europe tab.

Real transmission infrastructure (OpenInfraMap vector tiles, styled to the
DESIGN.md tokens) under the bidding-zone choropleth (amber = ceiling value).
One-way embed: zone selection happens in Streamlit widgets, not by map click.
"""
from __future__ import annotations

import json
from pathlib import Path

ZONES_GEOJSON = Path(__file__).parent / "data_zones.geojson"

# DESIGN.md tokens (duplicated from app.py's C to keep this module standalone)
BG, SURFACE, BORDER = "#12161F", "#1B2230", "#2A3347"
TEXT, MUTED, AMBER, CYAN = "#D8DEE9", "#8A94A6", "#F2A93B", "#5BC8D8"
AMBER_DIM = "#5E451C"


def gridmap_url(values: dict[str, dict], height: int = 560) -> str:
    """Write the map page under ./static (Streamlit static serving) and return
    its URL. A plain page dodges the srcdoc-sandbox worker issue that stalls
    MapLibre inside components.html."""
    import hashlib
    html = gridmap_html(values, height)
    Path("static").mkdir(exist_ok=True)
    (Path("static") / "gridmap.html").write_text(html)
    v = hashlib.md5(html.encode()).hexdigest()[:8]
    return f"/app/static/gridmap.html?v={v}"


def gridmap_html(values: dict[str, dict], height: int = 560) -> str:
    """values: zone code -> {"rev": float, "payback": float, "capture": str|None}.
    Zones missing from `values` render as no-data (track color, low opacity)."""
    gj = json.loads(ZONES_GEOJSON.read_text())
    revs = [v["rev"] for v in values.values()]
    vmin, vmax = (min(revs), max(revs)) if revs else (0.0, 1.0)
    for f in gj["features"]:
        z = f["properties"]["zone"]
        v = values.get(z)
        if v:
            f["properties"] |= {
                "rev": v["rev"],
                "label": (f"{z} · {v['rev']:,.0f} €/MW/y · payback {v['payback']:.1f}y"
                          + (f" · capture {v['capture']}" if v.get("capture") else "")),
            }
        else:
            f["properties"]["label"] = f"{z} · no data in this period"

    return f"""<!doctype html>
<html><head><meta charset="utf-8"/>
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet"/>
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
  .maplibregl-popup-content {{ background: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 8px 10px; box-shadow: none; }}
  .maplibregl-popup-anchor-bottom .maplibregl-popup-tip {{ border-top-color: {BORDER}; }}
  .maplibregl-popup-anchor-top .maplibregl-popup-tip {{ border-bottom-color: {BORDER}; }}
  .maplibregl-ctrl-group {{ background: {SURFACE}; border: 1px solid {BORDER}; }}
  .maplibregl-ctrl-group button span {{ filter: invert(0.8); }}
  .maplibregl-ctrl-attrib {{ background: rgba(27,34,48,.8) !important;
    color: {MUTED}; font-size: 10px; }}
  .maplibregl-ctrl-attrib a {{ color: {MUTED}; }}
  html, body {{ margin: 0; background: {BG}; }}
</style>
</head><body>
<div id="gridmap" style="height:{height - 8}px;border:1px solid {BORDER};border-radius:6px;"></div>
<script>
const ZONES = {json.dumps(gj)};
const map = new maplibregl.Map({{
  container: "gridmap",
  center: [9.5, 51.0], zoom: 3.5, minZoom: 3, maxZoom: 12,
  attributionControl: {{compact: true, customAttribution: "© OpenStreetMap contributors · OpenInfraMap"}},
  style: {{
    version: 8,
    sources: {{
      zones: {{type: "geojson", data: ZONES}},
      power: {{type: "vector", tiles: ["https://openinframap.org/map/power/{{z}}/{{x}}/{{y}}.pbf"],
               minzoom: 0, maxzoom: 17}},
    }},
    layers: [
      {{id: "bg", type: "background", paint: {{"background-color": "{BG}"}}}},
      {{id: "zone-nodata", type: "fill", source: "zones",
        filter: ["!", ["has", "rev"]],
        paint: {{"fill-color": "{SURFACE}", "fill-opacity": 0.35}}}},
      {{id: "zone-fill", type: "fill", source: "zones",
        filter: ["has", "rev"],
        paint: {{
          "fill-color": ["interpolate", ["linear"], ["get", "rev"],
             {vmin}, "{AMBER_DIM}", {vmax}, "{AMBER}"],
          "fill-opacity": 0.62,
        }}}},
      {{id: "zone-line", type: "line", source: "zones",
        paint: {{"line-color": "{BG}", "line-width": 1.1}}}},
      {{id: "grid-low", type: "line", source: "power", "source-layer": "power_line",
        filter: ["<", ["coalesce", ["to-number", ["get", "voltage"]], 0], 300],
        minzoom: 5,
        paint: {{"line-color": "{MUTED}", "line-opacity": 0.35,
                 "line-width": ["interpolate", ["linear"], ["zoom"], 5, 0.3, 10, 0.8]}}}},
      {{id: "grid-hv", type: "line", source: "power", "source-layer": "power_line",
        filter: [">=", ["coalesce", ["to-number", ["get", "voltage"]], 0], 300],
        paint: {{"line-color": "{CYAN}", "line-opacity": 0.5,
                 "line-width": ["interpolate", ["linear"], ["zoom"], 3, 0.4, 10, 1.6]}}}},
      {{id: "substations", type: "circle", source: "power",
        "source-layer": "power_substation_point", minzoom: 7,
        paint: {{"circle-color": "{CYAN}", "circle-radius": 2, "circle-opacity": 0.55}}}},
    ],
  }},
}});
map.addControl(new maplibregl.NavigationControl({{showCompass: false}}), "top-right");
window._map = map;
window._mapErrors = [];
map.on("error", (e) => window._mapErrors.push(String(e && e.error && e.error.message || e)));

const popup = new maplibregl.Popup({{closeButton: false, closeOnClick: false, maxWidth: "340px"}});
map.on("mousemove", "zone-fill", (e) => {{
  map.getCanvas().style.cursor = "crosshair";
  popup.setLngLat(e.lngLat)
       .setHTML(`<div style="font-family:ui-monospace,monospace;font-size:12px;
                 color:{TEXT};">${{e.features[0].properties.label}}</div>`)
       .addTo(map);
}});
map.on("mouseleave", "zone-fill", () => {{
  map.getCanvas().style.cursor = ""; popup.remove();
}});
</script>
</body></html>
"""
