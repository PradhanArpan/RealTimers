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

from config import BBOX, LEADS, COLOR_SCALE, MODE_THRESHOLD_CM, FLOODED_CM, GRID, ROADS_SOURCE
from mock_physics import load_depth_cube        # <- swap for your real depth loader later
from network import load_drain_network, network_summary
from routing import Router
from drains import router as drains_router
from terrain import router as terrain_router

app = FastAPI(title="RealTimers Urban Flood Nowcast")

CUBE = load_depth_cube()
NETWORK = load_drain_network()
ROUTER = Router(CUBE, NETWORK)
ISSUED_AT = datetime.now(timezone.utc)
_png_cache = {}


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
def meta():
    return {"bbox": BBOX, "leads": LEADS, "grid": GRID, "roads_source": ROADS_SOURCE,
            "issued_at": ISSUED_AT.isoformat(), "flooded_cm": FLOODED_CM,
            "mode_threshold_cm": MODE_THRESHOLD_CM,
            "color_scale": [{"cm": c, "hex": h, "alpha": a} for c, h, a in COLOR_SCALE],
            "max_depth_cm": round(float(CUBE.max()), 1)}


@app.get("/api/flood/{lead}.png")
def flood_png(lead: int):
    li = _lead(lead)
    if li not in _png_cache:
        img = Image.fromarray(_rgba(CUBE[li]), "RGBA").resize((GRID * 3, GRID * 3), Image.BICUBIC)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        _png_cache[li] = buf.getvalue()
    return Response(_png_cache[li], media_type="image/png",
                    headers={"Cache-Control": "no-cache"})


@app.get("/api/roads")
def roads_all():
    return ROUTER.all_geojson()


@app.get("/api/roads/flooded")
def roads_flooded(lead: int = Query(0)):
    _lead(lead)
    return ROUTER.flooded_geojson(lead)


@app.get("/api/alerts")
def alerts():
    return ROUTER.alerts()


@app.get("/api/point")
def point(lat: float, lon: float, lead: int = 0):
    _lead(lead)
    return {"lat": lat, "lon": lon, "lead_min": lead,
            "depth_cm": round(ROUTER.depth_at(lat, lon, lead), 1)}


@app.get("/api/route")
def route(from_lat: float, from_lon: float, to_lat: float, to_lon: float,
          mode: str = "car", lead: int = 0):
    if mode not in MODE_THRESHOLD_CM:
        raise HTTPException(422, f"mode must be one of {list(MODE_THRESHOLD_CM)}")
    _lead(lead)
    # The network is BBMP's drain linework, not a road graph: it is topologically
    # disconnected and you cannot drive down a drain. Routing returns once a real
    # road network is ingested (tools/ingest_roads.py). Saying so is better than
    # returning a path along stormwater drains.
    raise HTTPException(
        501,
        "Routing needs a road network. The map currently carries BBMP's drain "
        "network, which is not routable. Run tools/ingest_roads.py to add OSM "
        "roads, then this endpoint returns flood-safe routes.",
    )


# Serve the dashboard from the same server (keep this LAST so /api/* wins).
# Real BBMP stormwater drain network. Must be registered before the
# static mount below, which swallows every unmatched path.
app.include_router(drains_router)
app.include_router(terrain_router)

app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "frontend", html=True), name="ui")
