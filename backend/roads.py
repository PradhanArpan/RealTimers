"""
Road network loader. Returns plain dicts so the rest of the code doesn't care about the source.

    {"nodes": {node_id: (lat, lon)},
     "edges": [{"u": id, "v": id, "length": metres, "coords": [(lon, lat), ...], "name": str}]}

Edges are directed (two-way streets appear twice).
"""
import math
import numpy as np
import networkx as nx
from config import BBOX, ROADS_SOURCE


def _haversine(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def synthetic_roads(n=12, seed=3):
    """A slightly wobbly street grid so the demo works offline with no data."""
    rng = np.random.default_rng(seed)
    w, s, e, nn = BBOX
    nodes = {}
    for r in range(n):
        for c in range(n):
            jx, jy = rng.uniform(-0.18, 0.18, 2) / (n - 1)
            lon = w + (e - w) * min(max(c / (n - 1) + jx, 0.01), 0.99)
            lat = nn - (nn - s) * min(max(r / (n - 1) + jy, 0.01), 0.99)
            nodes[r * n + c] = (lat, lon)
    g = nx.Graph()
    for r in range(n):
        for c in range(n):
            i = r * n + c
            if c + 1 < n and rng.random() > 0.06:
                g.add_edge(i, i + 1, name=f"Cross Rd {r + 1}")
            if r + 1 < n and rng.random() > 0.06:
                g.add_edge(i, i + n, name=f"Main St {c + 1}")
    keep = max(nx.connected_components(g), key=len)
    edges = []
    for u, v, d in g.subgraph(keep).edges(data=True):
        (la1, lo1), (la2, lo2) = nodes[u], nodes[v]
        ln = _haversine(la1, lo1, la2, lo2)
        edges.append({"u": u, "v": v, "length": ln, "coords": [(lo1, la1), (lo2, la2)], "name": d["name"]})
        edges.append({"u": v, "v": u, "length": ln, "coords": [(lo2, la2), (lo1, la1)], "name": d["name"]})
    return {"nodes": {i: nodes[i] for i in keep}, "edges": edges}


def osm_roads():
    """Real streets. NOT tested in the sandbox this was written in (no internet) - try it first."""
    import osmnx as ox
    w, s, e, n = BBOX
    try:
        g = ox.graph_from_bbox((w, s, e, n), network_type="drive")   # osmnx >= 2.0
    except TypeError:
        g = ox.graph_from_bbox(n, s, e, w, network_type="drive")      # osmnx 1.x
    nodes = {i: (d["y"], d["x"]) for i, d in g.nodes(data=True)}
    edges = []
    for u, v, d in g.edges(data=True):
        if "geometry" in d:
            coords = [(x, y) for x, y in d["geometry"].coords]
        else:
            coords = [(nodes[u][1], nodes[u][0]), (nodes[v][1], nodes[v][0])]
        name = d.get("name", "")
        if isinstance(name, list):
            name = name[0]
        edges.append({"u": u, "v": v, "length": float(d.get("length", 1.0)),
                      "coords": coords, "name": name or f"Segment {u}-{v}"})
    return {"nodes": nodes, "edges": edges}


def load_roads():
    return osm_roads() if ROADS_SOURCE == "osm" else synthetic_roads()
