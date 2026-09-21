"""
Load the OpenStreetMap road network written by tools/ingest_roads.py into the
shape the Router expects: {"nodes": {id: (lat, lon)}, "edges": [...]}.

Two-way streets are stored once in the file and expanded to both directions
here. Returns None when the file is absent, so the server can say plainly that
routing is waiting on it rather than fail.
"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "roads.geojson"


def load_osm_roads() -> dict | None:
    if not DATA.exists():
        return None
    fc = json.loads(DATA.read_text())
    nodes = {int(k): (float(v[0]), float(v[1])) for k, v in fc["nodes"].items()}
    edges = []
    for f in fc["features"]:
        p = f["properties"]
        u, v = int(p["u"]), int(p["v"])
        if u not in nodes or v not in nodes:
            continue
        coords = [tuple(c) for c in f["geometry"]["coordinates"]]
        if len(coords) < 2:
            continue
        length = float(p.get("length_m") or 1.0)
        name = p.get("name") or "unnamed road"
        edges.append({"u": u, "v": v, "length": length, "coords": coords, "name": name})
        if not p.get("oneway", False):
            edges.append({"u": v, "v": u, "length": length, "coords": coords[::-1], "name": name})
    return {"nodes": nodes, "edges": edges,
            "attribution": fc.get("attribution", "Roads (c) OpenStreetMap contributors, ODbL")}
