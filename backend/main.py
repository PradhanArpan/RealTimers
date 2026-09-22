"""
RealTimers flood dashboard API.   Run:  uvicorn main:app --reload --port 8000   (from /backend)

Endpoints (the plug points for each phase):
  GET /api/meta                     bbox, leads, colour scale, thresholds
  GET /api/flood/{lead}.png         depth overlay image                   <- Phase E output
  GET /api/roads                    all streets (map context)
  GET /api/roads/flooded?lead=      flooded streets as GeoJSON            <- Phase F
  GET /api/alerts                   worst streets in the next 3 h         <- Phase F
  GET /api/point?lat&lon&lead       depth at one location                 <- Phase E output
  GET /api/route?...                flood-safe route                      <- Phase F
  GET /v1/drains                    BBMP stormwater drain network (real data)
  GET /v1/drains/status             what the network contains, and what it does not
"""
import io
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

import os

from config import BBOX, LEADS, COLOR_SCALE, MODE_THRESHOLD_CM, FLOODED_CM, GRID, ROADS_SOURCE, CITIES, DEFAULT_CITY
from mock_physics import load_depth_cube        # <- swap for your real depth loader later
from network import load_drain_network, network_summary
from roads_osm import load_osm_roads
from routing import Router
from drains import router as drains_router
from terrain import router as terrain_router
from opencity import router as opencity_router

app = FastAPI(title="RealTimers Urban Flood Nowcast")

# One depth cube and one corridor router per city in the problem statement.
# Routing on streets needs a road network, which is loaded for Bengaluru only:
# it is the largest object in memory, and the free server has 512 MB.
CITY = {}
for _c, _cfg in CITIES.items():
    _cube = load_depth_cube(_c, _cfg["bbox"])
    _net = load_drain_network(_cfg["bbox"], _c, _cfg["corridors"])
    CITY[_c] = {"cube": _cube, "router": Router(_cube, _net, _cfg["bbox"]),
                "summary": network_summary(_net)}
_ROADS = load_osm_roads()
ROAD_ROUTER = Router(CITY[DEFAULT_CITY]["cube"], _ROADS, CITIES[DEFAULT_CITY]["bbox"]) if _ROADS else None
CUBE = CITY[DEFAULT_CITY]["cube"]          # kept for anything still expecting one city
ROUTER = CITY[DEFAULT_CITY]["router"]
ISSUED_AT = datetime.now(timezone.utc)
MAPTILER_KEY = os.environ.get("MAPTILER_KEY", "").strip()
_png_cache = {}


def _city(city: str) -> dict:
    c = (city or DEFAULT_CITY).lower()
    if c not in CITY:
        raise HTTPException(404, f"Unknown city '{city}'. Choose from {list(CITY)}.")
    return CITY[c]


def _lead(lead: int) -> int:
    try:
        return ROUTER.lead_index(lead)
    except ValueError as e:
        raise HTTPException(422, str(e))


def _rgba(depth_cm):
    stops = np.array([s[0] for s in COLOR_SCALE], dtype=float)
    rgb = [[int(s[1][i:i + 2], 16) for i in (1, 3, 5)] for s in COLOR_SCALE]
    rgb = np.array(rgb, dtype=float)
    alpha = np.array([s[2] for s in COLOR_SCALE]) * 255
    out = np.zeros(depth_cm.shape + (4,), dtype=np.uint8)
    for ch in range(3):
        out[..., ch] = np.interp(depth_cm, stops, rgb[:, ch])
    out[..., 3] = np.interp(depth_cm, stops, alpha)
    return out


@app.get("/api/meta")
def meta(city: str = Query(DEFAULT_CITY)):
    c = _city(city); key = city.lower(); cfg = CITIES[key]
    has_routing = key == DEFAULT_CITY and ROAD_ROUTER is not None
    return {"city": key, "label": cfg["label"], "area": cfg["area"], "subtitle": cfg["subtitle"],
            "note": cfg["note"], "corridors": cfg["corridors"],
            "cities": [{"id": k, "label": v["label"]} for k, v in CITIES.items()],
            "bbox": cfg["bbox"], "leads": LEADS, "grid": GRID, "roads_source": ROADS_SOURCE,
            "routing": has_routing,
            "road_edges": len(ROAD_ROUTER.edges) if has_routing else 0,
            "corridor_count": c["summary"]["drains"],
            "maptiler_key": MAPTILER_KEY,
            "issued_at": ISSUED_AT.isoformat(), "flooded_cm": FLOODED_CM,
            "mode_threshold_cm": MODE_THRESHOLD_CM,
            "color_scale": [{"cm": cm, "hex": h, "alpha": a} for cm, h, a in COLOR_SCALE],
            "max_depth_cm": round(float(c["cube"].max()), 1)}


@app.get("/api/flood/{lead}.png")
def flood_png(lead: int, city: str = Query(DEFAULT_CITY)):
    c = _city(city); li = _lead(lead); key = (city.lower(), li)
    if key not in _png_cache:
        img = Image.fromarray(_rgba(c["cube"][li]), "RGBA").resize((GRID * 3, GRID * 3), Image.BICUBIC)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        _png_cache[key] = buf.getvalue()
    return Response(_png_cache[key], media_type="image/png", headers={"Cache-Control": "no-cache"})


@app.get("/api/roads")
def roads_all(city: str = Query(DEFAULT_CITY)):
    return _city(city)["router"].all_geojson()


@app.get("/api/roads/flooded")
def roads_flooded(lead: int = Query(0), city: str = Query(DEFAULT_CITY)):
    _lead(lead)
    return _city(city)["router"].flooded_geojson(lead)


@app.get("/api/alerts")
def alerts(city: str = Query(DEFAULT_CITY)):
    return _city(city)["router"].alerts()


@app.get("/api/point")
def point(lat: float, lon: float, lead: int = 0, city: str = Query(DEFAULT_CITY)):
    _lead(lead)
    return {"lat": lat, "lon": lon, "lead_min": lead,
            "depth_cm": round(_city(city)["router"].depth_at(lat, lon, lead), 1)}


@app.get("/api/route")
def route(from_lat: float, from_lon: float, to_lat: float, to_lon: float,
          mode: str = "car", lead: int = 0, city: str = Query(DEFAULT_CITY)):
    if mode not in MODE_THRESHOLD_CM:
        raise HTTPException(422, f"mode must be one of {list(MODE_THRESHOLD_CM)}")
    _lead(lead); _city(city)
    if city.lower() != DEFAULT_CITY:
        raise HTTPException(501, f"Flood-safe routing runs for {CITIES[DEFAULT_CITY]['label']} only on this "
                                 "server: each city's road network needs its own memory.")
    if ROAD_ROUTER is None:
        raise HTTPException(
            501,
            "Routing needs the road network. Run tools/ingest_roads.py once, commit "
            "data/roads.geojson and push; routing then runs on real OpenStreetMap streets.",
        )
    res = ROAD_ROUTER.route(from_lat, from_lon, to_lat, to_lon, mode, lead)
    if "error" in res:
        raise HTTPException(404, res["error"])
    return res

# Serve the dashboard from the same server (keep this LAST so /api/* wins).
# Real BBMP stormwater drain network. Must be registered before the
# static mount below, which swallows every unmatched path.
app.include_router(drains_router)
app.include_router(terrain_router)
app.include_router(opencity_router)

app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "frontend", html=True), name="ui")
