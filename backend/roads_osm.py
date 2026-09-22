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


def _iter_features(text: str):
    """Decode the features one at a time instead of the whole file at once.

    json.loads on the 10 MB road file briefly holds every feature as Python
    objects -- a spike that nearly doubles the server's memory at startup.
    Decoding feature by feature keeps only the compact edges.
    """
    dec = json.JSONDecoder()
    i = text.index("[", text.index('"features"')) + 1
    n = len(text)
    while True:
        while i < n and text[i] in " \n\r\t,":
            i += 1
        if i >= n or text[i] == "]":
            return
        obj, i = dec.raw_decode(text, i)
        yield obj


def load_osm_roads() -> dict | None:
    if not DATA.exists():
        return None
    text = DATA.read_text()
    dec = json.JSONDecoder()
    raw_nodes, _ = dec.raw_decode(text, text.index("{", text.index('"nodes"')))
    nodes = {int(k): (float(v[0]), float(v[1])) for k, v in raw_nodes.items()}
    del raw_nodes
    names: dict[str, str] = {}              # share one string per street name
    edges = []
    for f in _iter_features(text):
        p = f["properties"]
        u, v = int(p["u"]), int(p["v"])
        if u not in nodes or v not in nodes:
            continue
        coords = tuple((float(c[0]), float(c[1])) for c in f["geometry"]["coordinates"])
        if len(coords) < 2:
            continue
        length = float(p.get("length_m") or 1.0)
        nm = p.get("name") or "unnamed road"
        nm = names.setdefault(nm, nm)
        edges.append({"u": u, "v": v, "length": length, "coords": coords, "name": nm})
        if not p.get("oneway", False):
            edges.append({"u": v, "v": u, "length": length, "coords": coords[::-1], "name": nm})
    del text
    return {"nodes": nodes, "edges": edges,
            "attribution": "Roads (c) OpenStreetMap contributors, ODbL"}
