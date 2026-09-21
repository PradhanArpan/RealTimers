"""
Serve the OpenCity layers converted by tools/ingest_opencity.py.

    GET /v1/opencity                          what is available
    GET /v1/opencity/{city}/{slug}            one layer as GeoJSON
        ?geom=Point|LineString|Polygon        keep one geometry family
        ?bbox=w,s,e,n                         keep features touching the box

In main.py, before the static mount:
    from opencity import router as opencity_router
    app.include_router(opencity_router)
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

DIR = Path(__file__).resolve().parent.parent / "data" / "opencity"
router = APIRouter(prefix="/v1/opencity", tags=["opencity"])


@lru_cache(maxsize=1)
def _index() -> dict:
    p = DIR / "index.json"
    return json.loads(p.read_text()) if p.exists() else {}


@lru_cache(maxsize=16)
def _layer(key: str) -> dict:
    city, slug = key.split("/")
    return json.loads((DIR / city / f"{slug}.geojson").read_text())


def _points(g):
    t, c = g["type"], g["coordinates"]
    if t == "Point":
        yield c
    elif t in ("LineString", "MultiPoint"):
        yield from c
    elif t in ("Polygon", "MultiLineString"):
        for part in c:
            yield from part
    elif t == "MultiPolygon":
        for poly in c:
            for ring in poly:
                yield from ring


@router.get("")
def index():
    return _index()


@router.get("/{city}/{slug}")
def layer(city: str, slug: str,
          geom: str | None = Query(None, pattern="^(Point|LineString|Polygon)$"),
          bbox: str | None = None):
    key = f"{city}/{slug}"
    if key not in _index():
        raise HTTPException(404, f"No layer {key}. See /v1/opencity for what exists.")
    fc = _layer(key)
    feats = fc["features"]
    if geom:
        feats = [f for f in feats if f["geometry"]["type"].replace("Multi", "") == geom]
    if bbox:
        try:
            w, s, e, n = (float(v) for v in bbox.split(","))
        except ValueError:
            raise HTTPException(400, "bbox must be west,south,east,north")
        feats = [f for f in feats
                 if any(w <= x <= e and s <= y <= n for x, y in _points(f["geometry"]))]
    return {"type": "FeatureCollection", "name": fc.get("name"),
            "description": fc.get("description"), "features": feats}
