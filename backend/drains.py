"""
Serve the BBMP stormwater drain network.

Drop-in for the existing scaffold. In main.py:

    from drains import router as drains_router
    app.include_router(drains_router)

Endpoints:
    GET /v1/drains          GeoJSON, optionally filtered by class and bbox
    GET /v1/drains/status   what is loaded, and what it does not contain

The status endpoint exists so the dashboard can state its own provenance
rather than the team having to remember it on stage.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

DATA = Path(__file__).resolve().parent.parent / "data" / "drains.geojson"

ATTRIBUTION = "BBMP stormwater drains via OpenCity (KSRSAC), public domain"

# Stated plainly so it reaches the UI instead of living only in a slide.
DERIVED_FIELDS = [
    "diameter",
    "invert level",
    "slope",
    "node / manhole id",
    "flow direction",
    "material",
]

router = APIRouter(prefix="/v1/drains", tags=["drains"])


@lru_cache(maxsize=1)
def _load() -> dict:
    if not DATA.exists():
        return {}
    with DATA.open() as fh:
        return json.load(fh)


def _touches(geometry: dict, box: tuple[float, float, float, float]) -> bool:
    w, s, e, n = box
    lines = (
        [geometry["coordinates"]]
        if geometry["type"] == "LineString"
        else geometry["coordinates"]
    )
    for line in lines:
        for lon, lat in line:
            if w <= lon <= e and s <= lat <= n:
                return True
    return False


@router.get("")
def drains(
    kind: str | None = Query(None, description="Primary, Secondary or Tertiary"),
    bbox: str | None = Query(None, description="west,south,east,north"),
):
    data = _load()
    if not data:
        raise HTTPException(
            503,
            "Drain network not ingested. Run tools/ingest_drains.py on the "
            "OpenCity KML first.",
        )

    features = data["features"]

    if kind:
        wanted = {k.strip().lower() for k in kind.split(",")}
        features = [f for f in features if f["properties"]["type"].lower() in wanted]

    if bbox:
        try:
            box = tuple(float(v) for v in bbox.split(","))
            if len(box) != 4:
                raise ValueError
        except ValueError:
            raise HTTPException(400, "bbox must be west,south,east,north")
        features = [f for f in features if _touches(f["geometry"], box)]

    return {
        "type": "FeatureCollection",
        "attribution": ATTRIBUTION,
        "features": features,
    }


@router.get("/status")
def status():
    data = _load()
    if not data:
        return {"loaded": False, "attribution": ATTRIBUTION, "derived_fields": DERIVED_FIELDS}

    counts: dict[str, int] = {}
    length: dict[str, float] = {}
    for f in data["features"]:
        t = f["properties"]["type"]
        counts[t] = counts.get(t, 0) + 1
        length[t] = length.get(t, 0.0) + f["properties"].get("length_m", 0.0)

    return {
        "loaded": True,
        "attribution": ATTRIBUTION,
        "bbox": data.get("bbox"),
        "counts": counts,
        "length_km": {k: round(v / 1000, 1) for k, v in length.items()},
        "total_km": round(sum(length.values()) / 1000, 1),
        "source_provides": ["geometry", "class", "length", "source id", "reference name"],
        "derived_fields": DERIVED_FIELDS,
        "note": (
            "The published network is geometry only. Hydraulic attributes are "
            "synthesised to CPHEEO design standards and shown as estimated."
        ),
    }
