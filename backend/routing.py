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
        """depth[lead_idx, edge_idx] = max depth (cm) along that street segment."""
        self.depth = np.zeros((len(LEADS), len(self.edges)), dtype=np.float32)
        for k, ed in enumerate(self.edges):
            pts = np.array(ed["coords"])                      # (lon, lat)
            seg = np.hypot(np.diff(pts[:, 0]) * _m_per_deg_lon(pts[0, 1]),
                           np.diff(pts[:, 1]) * M_PER_DEG_LAT)
            cum = np.concatenate([[0], np.cumsum(seg)])
            total = max(cum[-1], 1e-6)
            m = max(2, int(total / 12) + 1)                   # a sample about every 12 m
            t = np.linspace(0, total, m)
            lon = np.interp(t, cum, pts[:, 0])
            lat = np.interp(t, cum, pts[:, 1])
            cols = np.clip(((lon - W) / (E - W) * GRID).astype(int), 0, GRID - 1)
            rows = np.clip(((N - lat) / (N - S) * GRID).astype(int), 0, GRID - 1)
            self.depth[:, k] = self.cube[:, rows, cols].max(axis=1)

    def _build_graph(self):
        self.g = nx.DiGraph()
        for k, ed in enumerate(self.edges):
            u, v = ed["u"], ed["v"]
            if self.g.has_edge(u, v) and self.g[u][v]["length"] <= ed["length"]:
                continue
            self.g.add_edge(u, v, eid=k, length=ed["length"])

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
