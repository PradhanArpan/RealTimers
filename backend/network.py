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
_BLR = [
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

# Well-known places in the other pilot boxes, only to make an ID readable.
# Straight-line nearest, shown as "near X" because that is all it is.
_CHN = [("Velachery", 12.9791, 80.2210), ("Adyar", 13.0063, 80.2574), ("Guindy", 13.0067, 80.2206),
        ("T. Nagar", 13.0418, 80.2341), ("Saidapet", 13.0213, 80.2231), ("Pallikaranai", 12.9349, 80.2137),
        ("Taramani", 12.9863, 80.2432), ("Thiruvanmiyur", 12.9830, 80.2594), ("Kotturpuram", 13.0170, 80.2410),
        ("Madipakkam", 12.9623, 80.1986), ("Perungudi", 12.9654, 80.2461), ("Mylapore", 13.0339, 80.2619)]
_MUM = [("Kurla", 19.0726, 72.8845), ("BKC", 19.0660, 72.8680), ("Andheri East", 19.1136, 72.8697),
        ("Sion", 19.0390, 72.8619), ("Dharavi", 19.0380, 72.8538), ("Bandra", 19.0544, 72.8406),
        ("Chembur", 19.0522, 72.9005), ("Ghatkopar", 19.0860, 72.9081), ("Powai", 19.1176, 72.9060),
        ("Santacruz", 19.0810, 72.8410), ("Mahim", 19.0390, 72.8400), ("Vile Parle", 19.0990, 72.8440)]
_DEL = [("Connaught Place", 28.6315, 77.2167), ("ITO", 28.6280, 77.2410), ("Minto Bridge", 28.6340, 77.2270),
        ("Pragati Maidan", 28.6180, 77.2440), ("Karol Bagh", 28.6519, 77.1909), ("Paharganj", 28.6448, 77.2167),
        ("Rajghat", 28.6406, 77.2495), ("Kashmere Gate", 28.6675, 77.2280), ("India Gate", 28.6129, 77.2295),
        ("Lodhi Road", 28.5910, 77.2270), ("Chandni Chowk", 28.6506, 77.2303)]
LOCALITIES = {"bengaluru": _BLR, "chennai": _CHN, "mumbai": _MUM, "delhi": _DEL}


def _m_per_deg_lon(lat: float) -> float:
    return 111_320.0 * math.cos(math.radians(lat))


def _dist_m(lon1, lat1, lon2, lat2) -> float:
    mx = _m_per_deg_lon((lat1 + lat2) / 2)
    return math.hypot((lon2 - lon1) * mx, (lat2 - lat1) * M_PER_DEG_LAT)


def _nearest_locality(lon: float, lat: float, city: str = "bengaluru") -> str:
    best, bd = "", 1e18
    for name, la, lo in LOCALITIES.get(city, _BLR):
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


def _corridor_features(city: str, corridors: str):
    """Yield (feature, kind, id, label) for the city's corridor source."""
    root = DATA.parent
    if corridors == "bbmp":
        src = DATA
    elif corridors == "gcc":
        src = root / "opencity" / "chennai" / "gcc_stormwater_drains.geojson"
    else:
        src = root / "terrain" / city / "streams.geojson"
    if not src.exists():
        raise FileNotFoundError(f"{src} missing for {city}")
    feats = json.loads(src.read_text())["features"]
    for i, f in enumerate(feats):
        p = f["properties"]
        if corridors == "bbmp":
            yield f, p["type"], p["id"], f"{p['type']} drain {p['id']}"
        elif corridors == "gcc":
            kind = (p.get("DRAIN_TYPE") or "Drain").strip()
            did = str(p.get("DRAIN_ID") or f"GCC-{i + 1:05d}").strip()
            readable = {"SWD": "stormwater drain"}.get(kind.upper(), kind.lower())
            yield f, kind, did, f"GCC {readable} {did}"
        else:
            order = int(p.get("strahler", 1))
            if order < 2:          # order 1 is mostly hillslope; leave it out
                continue
            yield f, f"Order {order} flow path", p["id"], f"Flow path {p['id']} (order {order})"


def load_drain_network(bbox=None, city: str = "bengaluru", corridors: str = "bbmp") -> dict:
    box = bbox or BBOX

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
    for feat, kind, did, label in _corridor_features(city, corridors):
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
                    name = f"{label} · near {_nearest_locality(mid[0], mid[1], city)}"
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
