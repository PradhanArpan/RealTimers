"""
Fetch the real road network for the pilot area and cache it, so routing runs
on streets instead of drains.

Run this ONCE on a machine with internet, then commit the output:

    pip install osmnx
    python tools/ingest_roads.py
    git add data/roads.geojson && git commit -m "Add OSM road network"

Render never needs osmnx or network access -- it reads the cached file.

Data (c) OpenStreetMap contributors, ODbL. Credit it in the UI.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from config import BBOX  # noqa: E402

OUT = ROOT / "data" / "roads.geojson"


def main() -> int:
    try:
        import osmnx as ox
    except ImportError:
        print("osmnx not installed.  pip install osmnx", file=sys.stderr)
        return 2

    w, s, e, n = BBOX
    print(f"Fetching drivable roads for {BBOX} ...")
    try:
        g = ox.graph_from_bbox((w, s, e, n), network_type="drive")   # osmnx >= 2.0
    except TypeError:
        g = ox.graph_from_bbox(n, s, e, w, network_type="drive")      # osmnx 1.x

    nodes = {int(i): (float(d["y"]), float(d["x"])) for i, d in g.nodes(data=True)}
    feats = []
    unnamed = 0
    for u, v, d in g.edges(data=True):
        if "geometry" in d:
            coords = [[float(x), float(y)] for x, y in d["geometry"].coords]
        else:
            coords = [[nodes[int(u)][1], nodes[int(u)][0]],
                      [nodes[int(v)][1], nodes[int(v)][0]]]
        name = d.get("name", "")
        if isinstance(name, list):
            name = name[0] if name else ""
        if not name:
            unnamed += 1
            name = d.get("highway", "road")
            if isinstance(name, list):
                name = name[0]
            name = f"unnamed {name}"
        feats.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "u": int(u), "v": int(v),
                "length_m": round(float(d.get("length", 1.0)), 1),
                "name": str(name),
                "oneway": bool(d.get("oneway", False)),
            },
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "type": "FeatureCollection",
        "attribution": "Roads (c) OpenStreetMap contributors, ODbL",
        "bbox": list(BBOX),
        "nodes": {str(k): list(v) for k, v in nodes.items()},
        "features": feats,
    }, separators=(",", ":")))

    mb = OUT.stat().st_size / 1_048_576
    print(f"wrote {OUT}  ({len(feats):,} edges, {len(nodes):,} nodes, {mb:.1f} MB)")
    print(f"{unnamed:,} edges have no name in OSM and are labelled by road class.")
    if mb > 20:
        print("Over 20 MB. Consider narrowing BBOX in backend/config.py.")
    print("\nNext: point the Router at this file, and re-enable /api/route.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
