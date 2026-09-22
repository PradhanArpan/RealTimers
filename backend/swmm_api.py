"""
EPA SWMM results as map layers.

    GET /v1/swmm/chennai/flooding   flooded junctions as GeoJSON points

Built by tools/build_swmm_chennai.py from the Greater Chennai Corporation
drain register. Not yet validated -- the layer says so.
"""
import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/v1/swmm", tags=["swmm"])
ROOT = Path(__file__).resolve().parent.parent / "data" / "swmm"


@lru_cache(maxsize=4)
def _flooding(city: str) -> dict:
    p = ROOT / city / "flooding.json"
    if not p.exists():
        raise HTTPException(404, f"No SWMM run for {city}. Run tools/build_swmm_chennai.py.")
    r = json.loads(p.read_text())
    meta = json.loads((ROOT / city / "network.json").read_text())["meta"]
    return {"type": "FeatureCollection",
            "properties": {"storm": f"{meta['rain_mm']:g} mm in {meta['duration_min']:g} min", "conduits": meta["conduits"],
                           "routing_continuity_pct": r["routing_continuity_pct"], "validated": False},
            "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [f["lon"], f["lat"]]},
                          "properties": {"node": f["node"], "volume_ml": f["volume_ml"], "hours": f["hours"],
                                         "near": f["near"], "bad_drain": f["bad_drain"]}} for f in r["flooded"]]}


@router.get("/{city}/flooding")
def flooding(city: str):
    return _flooding(city.lower())
