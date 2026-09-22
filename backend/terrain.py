"""
Serve the terrain layer built by tools/build_terrain.py.

    GET /v1/terrain/status       what was built, from what, and its caveats
    GET /v1/terrain/streams      stream links; ?min_order=3 for the major network
    GET /v1/terrain/catchments   micro-catchments (the future SWMM subcatchments)

In main.py, before the static mount:
    from terrain import router as terrain_router
    app.include_router(terrain_router)
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from config import CITIES, DEFAULT_CITY

import mock_physics

ROOT = Path(__file__).resolve().parent.parent / "data" / "terrain"

router = APIRouter(prefix="/v1/terrain", tags=["terrain"])


@lru_cache(maxsize=16)
def _load(city: str, name: str) -> dict:
    if city not in CITIES:
        raise HTTPException(404, f"Unknown city {city}")
    p = ROOT / city / name
    if not p.exists():
        raise HTTPException(503, f"Terrain not built. Run tools/build_terrain.py --city {city}.")
    return json.loads(p.read_text())


@router.get("/status")
def status(city: str = Query(DEFAULT_CITY)):
    city = city.lower()
    try:
        s = dict(_load(city, "summary.json"))
    except HTTPException:
        return {"built": False, "depth_model_terrain": mock_physics.TERRAIN_SOURCE.get(city, "synthetic")}
    s["built"] = True
    v = ROOT / city / "validation.json"
    if v.exists():
        s["validation"] = json.loads(v.read_text())["all"]
    s["depth_model_terrain"] = mock_physics.TERRAIN_SOURCE.get(city, "synthetic")
    return s


@router.get("/streams")
def streams(min_order: int = Query(1, ge=1, le=12), city: str = Query(DEFAULT_CITY)):
    fc = _load(city.lower(), "streams.geojson")
    feats = [f for f in fc["features"] if f["properties"]["strahler"] >= min_order]
    return {"type": "FeatureCollection", "features": feats}


@router.get("/catchments")
def catchments(city: str = Query(DEFAULT_CITY)):
    return _load(city.lower(), "catchments.geojson")
