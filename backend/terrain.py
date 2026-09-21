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

import mock_physics

CITY = "bengaluru"
DIR = Path(__file__).resolve().parent.parent / "data" / "terrain" / CITY

router = APIRouter(prefix="/v1/terrain", tags=["terrain"])


@lru_cache(maxsize=4)
def _load(name: str) -> dict:
    p = DIR / name
    if not p.exists():
        raise HTTPException(503, f"Terrain not built. Run tools/build_terrain.py --city {CITY}.")
    return json.loads(p.read_text())


@router.get("/status")
def status():
    try:
        s = dict(_load("summary.json"))
    except HTTPException:
        return {"built": False, "depth_model_terrain": mock_physics.TERRAIN_SOURCE}
    s["built"] = True
    v = DIR / "validation.json"
    if v.exists():
        s["validation"] = json.loads(v.read_text())["all"]
    s["depth_model_terrain"] = mock_physics.TERRAIN_SOURCE
    return s


@router.get("/streams")
def streams(min_order: int = Query(1, ge=1, le=12)):
    fc = _load("streams.geojson")
    feats = [f for f in fc["features"] if f["properties"]["strahler"] >= min_order]
    return {"type": "FeatureCollection", "features": feats}


@router.get("/catchments")
def catchments():
    return _load("catchments.geojson")
