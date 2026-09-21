"""Turns the depth cube into per-street depths, alerts, and flood-safe routes."""
import math
import numpy as np
import networkx as nx
from config import BBOX, GRID, LEADS, MODE_THRESHOLD_CM, FLOODED_CM, AVG_SPEED_KMPH

W, S, E, N = BBOX
M_PER_DEG_LAT = 111_320.0


def _m_per_deg_lon(lat):
    return 111_320.0 * math.cos(math.radians(lat))


def cell_of(lat, lon):
    col = int(np.clip((lon - W) / (E - W) * GRID, 0, GRID - 1))
    row = int(np.clip((N - lat) / (N - S) * GRID, 0, GRID - 1))
    return row, col


# Spacing of depth samples along each road or drain segment, metres. The depth
# grid cell is ~55 m; 6 m sampling tracks a 2 m reference closely (tested).
SAMPLE_STEP_M = 6.0


class Router:
    def __init__(self, cube, roads):
        self.cube = cube
        self.nodes = roads["nodes"]
        self.edges = roads["edges"]
        self.node_ids = list(self.nodes)
        self.node_xy = np.array([[self.nodes[i][0], self.nodes[i][1]] for i in self.node_ids])
        self._sample_edges()
        self._build_graph()

    # ---- street depths -------------------------------------------------
    def _sample_edges(self):
        """depth[lead_idx, edge_idx] = max depth (cm) along each segment.

        Vectorised: every segment is cut into steps of at most STEP_M metres
        and all sample points are looked up in the depth cube at once, then
        reduced per edge. Same samples as a per-edge loop, but seconds faster
        on a network of 80,000 road segments -- which matters on a small
        server where startup time is what a visitor waits through.
        """
        STEP_M = SAMPLE_STEP_M
        L = len(self.edges)
        self.depth = np.zeros((len(LEADS), L), dtype=np.float32)
        if L == 0:
            return
        counts = np.fromiter((len(ed["coords"]) for ed in self.edges), dtype=np.int64, count=L)
        flat = np.fromiter((v for ed in self.edges for pt in ed["coords"] for v in pt[:2]),
                           dtype=np.float64, count=int(counts.sum()) * 2).reshape(-1, 2)
        start = np.concatenate([[0], np.cumsum(counts)[:-1]])
        # segments: consecutive vertex pairs inside each edge
        seg_edge = np.repeat(np.arange(L), counts - 1)
        seg_a = np.concatenate([np.arange(s0, s0 + c - 1) for s0, c in zip(start, counts)])
        p0, p1 = flat[seg_a], flat[seg_a + 1]
        mx = _m_per_deg_lon(float(np.mean(flat[:, 1])))
        seg_len = np.hypot((p1[:, 0] - p0[:, 0]) * mx, (p1[:, 1] - p0[:, 1]) * M_PER_DEG_LAT)
        n = np.maximum(1, np.ceil(seg_len / STEP_M).astype(np.int64))
        # sample each segment at 0, 1/n, ..., (n-1)/n, plus every edge's last vertex
        rep = np.repeat(np.arange(len(n)), n)
        frac = np.arange(len(rep)) - np.repeat(np.cumsum(n) - n, n)
        frac = frac / n[rep]
        lon = np.concatenate([p0[rep, 0] + (p1[rep, 0] - p0[rep, 0]) * frac, flat[start + counts - 1, 0]])
        lat = np.concatenate([p0[rep, 1] + (p1[rep, 1] - p0[rep, 1]) * frac, flat[start + counts - 1, 1]])
        owner = np.concatenate([seg_edge[rep], np.arange(L)])
        cols = np.clip(((lon - W) / (E - W) * GRID).astype(np.int64), 0, GRID - 1)
        rows = np.clip(((N - lat) / (N - S) * GRID).astype(np.int64), 0, GRID - 1)
        vals = self.cube[:, rows, cols]                      # (leads, samples)
        order = np.argsort(owner, kind="stable")
        owner_sorted = owner[order]
        first = np.searchsorted(owner_sorted, np.arange(L))
        self.depth[:] = np.maximum.reduceat(vals[:, order], first, axis=1)

    def _build_graph(self):
        best = {}
        for k, ed in enumerate(self.edges):
            key = (ed["u"], ed["v"])
            if key not in best or ed["length"] < self.edges[best[key]]["length"]:
                best[key] = k
        self.g = nx.DiGraph()
        self.g.add_edges_from((u, v, {"eid": k, "length": self.edges[k]["length"]})
                              for (u, v), k in best.items())

    def lead_index(self, lead):
        if lead < LEADS[0] or lead > LEADS[-1]:
            raise ValueError(f"lead must be between {LEADS[0]} and {LEADS[-1]} minutes")
        return int(np.argmin(np.abs(np.array(LEADS) - lead)))

    # ---- queries ---------------------------------------------------------
    def depth_at(self, lat, lon, lead):
        r, c = cell_of(lat, lon)
        return float(self.cube[self.lead_index(lead), r, c])

    def flooded_geojson(self, lead, min_cm=5):
        li = self.lead_index(lead)
        seen, feats = set(), []
        for k, ed in enumerate(self.edges):
            key = frozenset((ed["u"], ed["v"]))
            d = float(self.depth[li, k])
            if key in seen or d < min_cm:
                continue
            seen.add(key)
            feats.append({"type": "Feature",
                          "geometry": {"type": "LineString", "coordinates": ed["coords"]},
                          "properties": {"name": ed["name"], "max_depth_cm": round(d, 1)}})
        return {"type": "FeatureCollection", "features": feats}

    def all_geojson(self):
        """Every street once (for map context)."""
        seen, feats = set(), []
        for ed in self.edges:
            key = frozenset((ed["u"], ed["v"]))
            if key in seen:
                continue
            seen.add(key)
            feats.append({"type": "Feature", "properties": {"name": ed["name"]},
                          "geometry": {"type": "LineString", "coordinates": ed["coords"]}})
        return {"type": "FeatureCollection", "features": feats}

    def alerts(self, top=10):
        """Worst streets over the whole 0-3 h window, grouped by street name."""
        best = {}
        for k, ed in enumerate(self.edges):
            series = self.depth[:, k]
            peak = float(series.max())
            if peak < FLOODED_CM:
                continue
            name = ed["name"]
            if name in best and best[name]["peak_cm"] >= peak:
                continue
            onset = next(LEADS[i] for i, d in enumerate(series) if d >= FLOODED_CM)
            c0, c1 = ed["coords"][0], ed["coords"][-1]
            mid = ((c0[0] + c1[0]) / 2, (c0[1] + c1[1]) / 2)
            best[name] = {"name": name, "peak_cm": round(peak, 1), "onset_min": onset,
                          "peak_min": LEADS[int(series.argmax())], "lat": mid[1], "lon": mid[0]}
        return sorted(best.values(), key=lambda a: -a["peak_cm"])[:top]

    # ---- routing -----------------------------------------------------------
    def _nearest_node(self, lat, lon):
        d = np.hypot((self.node_xy[:, 0] - lat) * M_PER_DEG_LAT,
                     (self.node_xy[:, 1] - lon) * _m_per_deg_lon(lat))
        return self.node_ids[int(d.argmin())]

    def _path_info(self, path, li, thr):
        coords, length, worst = [], 0.0, 0.0
        blocked = []
        for u, v in zip(path[:-1], path[1:]):
            eid = self.g[u][v]["eid"]
            ed = self.edges[eid]
            pts = ed["coords"]
            coords.extend(pts if not coords else pts[1:])
            length += ed["length"]
            d = float(self.depth[li, eid])
            worst = max(worst, d)
            if d >= thr:
                blocked.append({"type": "Feature",
                                "geometry": {"type": "LineString", "coordinates": pts},
                                "properties": {"name": ed["name"], "max_depth_cm": round(d, 1)}})
        return {"geometry": {"type": "LineString", "coordinates": coords},
                "length_m": round(length), "eta_min": round(length / 1000 / AVG_SPEED_KMPH * 60, 1),
                "max_depth_cm": round(worst, 1), "floods": worst >= thr}, blocked

    def route(self, lat1, lon1, lat2, lon2, mode, lead):
        thr = MODE_THRESHOLD_CM[mode]
        li = self.lead_index(lead)
        a, b = self._nearest_node(lat1, lon1), self._nearest_node(lat2, lon2)
        depth = self.depth[li]
        if a == b:
            return {"error": "Start and end snap to the same road junction. Pick points further apart."}

        try:
            normal_path = nx.shortest_path(self.g, a, b, weight="length")
        except nx.NetworkXNoPath:
            return {"error": "No road connection between these points."}
        normal, avoided = self._path_info(normal_path, li, thr)

        def safe_weight(u, v, d):
            dep = depth[d["eid"]]
            return None if dep >= thr else d["length"] * (1 + dep / thr)   # None hides the edge

        try:
            safe_path = nx.shortest_path(self.g, a, b, weight=safe_weight)
            safe, _ = self._path_info(safe_path, li, thr)
        except nx.NetworkXNoPath:
            safe = None

        if not normal["floods"]:
            msg = "The normal route stays clear at this time."
        elif safe is None:
            msg = f"No route stays below {thr} cm for this vehicle at T+{lead} min."
        else:
            extra = safe["length_m"] - normal["length_m"]
            msg = f"Normal route floods (up to {normal['max_depth_cm']} cm). Safe route adds {extra} m."
        return {"mode": mode, "threshold_cm": thr, "lead_min": lead,
                "normal": normal, "safe": safe,
                "avoided": {"type": "FeatureCollection", "features": avoided}, "message": msg}
