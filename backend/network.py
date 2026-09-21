"""
Build the flood network from the REAL BBMP stormwater drains.

Replaces the synthetic street grid. Everything the Router needs is the same
shape as before -- {"nodes": {...}, "edges": [...]} -- so depth sampling,
alerts, flooded-geometry and routing all work unchanged. The difference is
that every line on the map is now a drain BBMP actually published, in its
actual location.

Two honesty notes that matter for the pitch:

  * These are DRAIN corridors, not carriageways. Depth is modelled at the
    drain, which in Bengaluru usually runs alongside the road. Say "drain
    corridor", not "street", until a road network is ingested.
  * The source has no drain names at all -- RefName is empty in every
    record -- so labels are built from the BBMP id plus the nearest
    locality by straight-line distance. "near Koramangala" is computed,
    not published.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from config import BBOX

DATA = Path(__file__).resolve().parent.parent / "data" / "drains.geojson"

# Split long drains so a 7 km trunk is not a single edge. Metres.
SEGMENT_M = 260.0
# Endpoints within this distance become the same node, joining the network.
SNAP_M = 25.0

M_PER_DEG_LAT = 110_570.0

# Well-known localities, used only to make a drain id readable. Straight-line
# nearest, reported as "near X" because that is all it is.
LOCALITIES = [
    ("Koramangala", 12.9352, 77.6245), ("HSR Layout", 12.9116, 77.6389),
    ("Bellandur", 12.9260, 77.6762), ("BTM Layout", 12.9166, 77.6101),
    ("Silk Board", 12.9172, 77.6229), ("Madiwala", 12.9220, 77.6190),
    ("Ejipura", 12.9420, 77.6250), ("Domlur", 12.9611, 77.6387),
    ("Indiranagar", 12.9784, 77.6408), ("Marathahalli", 12.9591, 77.6974),
    ("Sarjapur Road", 12.9010, 77.6870), ("Agara", 12.9230, 77.6470),
    ("Iblur", 12.9260, 77.6600), ("Kudlu", 12.8880, 77.6480),
    ("Jakkasandra", 12.9300, 77.6200), ("Adugodi", 12.9410, 77.6060),
    ("Wilson Garden", 12.9450, 77.5930), ("Jayanagar", 12.9250, 77.5830),
    ("JP Nagar", 12.9080, 77.5850), ("Kasavanahalli", 12.9010, 77.6700),
    ("Haralur", 12.9050, 77.6650), ("Bommanahalli", 12.8990, 77.6180),
    ("Hongasandra", 12.8930, 77.6250), ("Carmelaram", 12.9080, 77.7000),
    ("Begur", 12.8730, 77.6280), ("Varthur", 12.9400, 77.7480),
]


def _m_per_deg_lon(lat: float) -> float:
    return 111_320.0 * math.cos(math.radians(lat))


def _dist_m(lon1, lat1, lon2, lat2) -> float:
    mx = _m_per_deg_lon((lat1 + lat2) / 2)
    return math.hypot((lon2 - lon1) * mx, (lat2 - lat1) * M_PER_DEG_LAT)


def _nearest_locality(lon: float, lat: float) -> str:
    best, bd = "", 1e18
    for name, la, lo in LOCALITIES:
        d = _dist_m(lon, lat, lo, la)
        if d < bd:
            best, bd = name, d
    return best


def _lines_of(feature: dict) -> list[list[list[float]]]:
    g = feature["geometry"]
    return [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]


def _clip(line, box):
    """Keep the runs of the line that fall inside the box."""
    w, s, e, n = box
    runs, cur = [], []
    for lon, lat in line:
        if w <= lon <= e and s <= lat <= n:
            cur.append((lon, lat))
        elif cur:
            if len(cur) >= 2:
                runs.append(cur)
            cur = []
    if len(cur) >= 2:
        runs.append(cur)
    return runs


def _chunk(line, target_m):
    """Cut a polyline into pieces of roughly target_m, keeping vertices."""
    pieces, cur, run = [], [line[0]], 0.0
    for a, b in zip(line, line[1:]):
        run += _dist_m(a[0], a[1], b[0], b[1])
        cur.append(b)
        if run >= target_m:
            pieces.append(cur)
            cur, run = [b], 0.0
    if len(cur) >= 2:
        pieces.append(cur)
    elif pieces:
        pieces[-1].extend(cur[1:])
    return pieces


def load_drain_network(bbox=None) -> dict:
    box = bbox or BBOX
    if not DATA.exists():
        raise FileNotFoundError(
            f"{DATA} missing. Run tools/ingest_drains.py on the OpenCity KML."
        )
    with DATA.open() as fh:
        data = json.load(fh)

    cell = SNAP_M / M_PER_DEG_LAT  # snapping grid in degrees
    node_of: dict[tuple[int, int], int] = {}
    nodes: dict[int, tuple[float, float]] = {}

    def node_id(lon: float, lat: float) -> int:
        key = (round(lon / cell), round(lat / cell))
        if key not in node_of:
            nid = len(nodes)
            node_of[key] = nid
            nodes[nid] = (lat, lon)
        return node_of[key]

    edges = []
    for feat in data["features"]:
        props = feat["properties"]
        kind, did = props["type"], props["id"]
        for raw in _lines_of(feat):
            for run in _clip(raw, box):
                for piece in _chunk(run, SEGMENT_M):
                    if len(piece) < 2:
                        continue
                    length = sum(
                        _dist_m(a[0], a[1], b[0], b[1])
                        for a, b in zip(piece, piece[1:])
                    )
                    if length < 15.0:
                        continue
                    u = node_id(*piece[0])
                    v = node_id(*piece[-1])
                    if u == v:
                        continue
                    mid = piece[len(piece) // 2]
                    name = f"{kind} drain {did} · near {_nearest_locality(mid[0], mid[1])}"
                    fwd = [(float(x), float(y)) for x, y in piece]
                    edges.append({"u": u, "v": v, "length": length,
                                  "coords": fwd, "name": name,
                                  "drain_id": did, "drain_type": kind})
                    edges.append({"u": v, "v": u, "length": length,
                                  "coords": list(reversed(fwd)), "name": name,
                                  "drain_id": did, "drain_type": kind})

    if not edges:
        raise ValueError(
            "No drains inside BBOX. Check config.BBOX against data/drains.geojson."
        )

    used = {e["u"] for e in edges} | {e["v"] for e in edges}
    return {"nodes": {i: nodes[i] for i in used}, "edges": edges}


def network_summary(net: dict) -> dict:
    undirected = len(net["edges"]) // 2
    km = sum(e["length"] for e in net["edges"]) / 2 / 1000
    by_type: dict[str, int] = {}
    drains: set[str] = set()
    for e in net["edges"]:
        drains.add(e["drain_id"])
        by_type[e["drain_type"]] = by_type.get(e["drain_type"], 0) + 1
    return {
        "source": "BBMP stormwater drains via OpenCity (KSRSAC), public domain",
        "drains": len(drains),
        "segments": undirected,
        "nodes": len(net["nodes"]),
        "length_km": round(km, 1),
        "segments_by_class": {k: v // 2 for k, v in by_type.items()},
        "note": (
            "Drain corridors, not carriageways. Depth is modelled at the drain. "
            "Locality labels are nearest-neighbour, not published names."
        ),
    }
