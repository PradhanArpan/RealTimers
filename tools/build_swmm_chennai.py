"""
Drainage physics for Chennai: an EPA SWMM model built from the Greater Chennai
Corporation drain register, run with the real SWMM engine (PySWMM).

    python tools/build_swmm_chennai.py --rain 100 --duration 120

Network, from the register (inside the Chennai pilot box):
  * conduits   each drain; RECT_OPEN, or RECT_CLOSED where COVER = Yes;
               depth DRAIN_DEP, width DRAIN_WID, length DRAIN_LEN
  * inverts    INVERT_SP / INVERT_EP -- the register's own levels
  * junctions  drain ends snapped within 5 m
  * outfalls   a dead-end node that is the lower end of its only drain
  * roughness  n = 0.015 concrete; 0.030 where STATUS = Bad       ASSUMPTION
  * street     top of the deepest drain meeting at a junction        ASSUMPTION
               (the register's levels sit ~4 m below the GLO-30 surface, so
               the two are never mixed)
Subcatchments: the terrain layer's micro-catchments, each to its nearest
junction within 250 m; SCS curve-number infiltration from WorldCover.
Routing: dynamic wave. Output: data/swmm/chennai/ -- the .inp, the SWMM
report, and flooding.json (every node SWMM reports flooded).
"""
from __future__ import annotations

import argparse, json, math, re, sys
from pathlib import Path

import numpy as np, rasterio
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from config import CITIES  # noqa: E402
from network import _nearest_locality  # noqa: E402

CITY = "chennai"; SNAP_M = 5.0; N_OK, N_BAD = 0.015, 0.030; MAX_OUTLET_M = 250.0
CN_BY_CLASS_C = {10: 70, 20: 73, 30: 74, 40: 85, 50: 79, 60: 91, 70: 74, 80: 100, 90: 85, 95: 70, 100: 74}


def fnum(v, lo=None, hi=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or (lo is not None and x < lo) or (hi is not None and x > hi):
        return None
    return x


def build(rain_mm: float, duration_min: float, hyetograph: str = "") -> Path:
    W, S, E, N = CITIES[CITY]["bbox"]
    out = ROOT / "data" / "swmm" / CITY; out.mkdir(parents=True, exist_ok=True)
    utm = Transformer.from_crs("EPSG:4326", "EPSG:32644", always_xy=True).transform
    ll = Transformer.from_crs("EPSG:32644", "EPSG:4326", always_xy=True).transform

    # ---- drains -> conduits ------------------------------------------------
    feats = json.loads((ROOT / "data/opencity/chennai/gcc_stormwater_drains.geojson").read_text())["features"]
    node_of, nodes, links = {}, [], []

    def node(x, y):
        key = (round(x / SNAP_M), round(y / SNAP_M))
        if key not in node_of:
            node_of[key] = len(nodes); nodes.append({"x": x, "y": y, "inv": [], "top": []})
        return node_of[key]

    for f in feats:
        g = f["geometry"]; p = f["properties"]
        line = g["coordinates"] if g["type"] == "LineString" else [c for part in g["coordinates"] for c in part]
        (lon0, lat0), (lon1, lat1) = line[0][:2], line[-1][:2]
        if not all(W <= lo <= E and S <= la <= N for lo, la in ((lon0, lat0), (lon1, lat1))):
            continue
        a, b = fnum(p.get("INVERT_SP"), -5, 60), fnum(p.get("INVERT_EP"), -5, 60)
        d, w = fnum(p.get("DRAIN_DEP"), 0.1, 6), fnum(p.get("DRAIN_WID"), 0.1, 12)
        if None in (a, b, d, w):
            continue
        x0, y0 = utm(lon0, lat0); x1, y1 = utm(lon1, lat1)
        if (round(x0 / SNAP_M), round(y0 / SNAP_M)) == (round(x1 / SNAP_M), round(y1 / SNAP_M)):
            continue                      # both ends snap together: no drain to model
        u, v = node(x0, y0), node(x1, y1)
        L = fnum(p.get("DRAIN_LEN"), 1, 5000) or math.hypot(x1 - x0, y1 - y0)
        nodes[u]["inv"].append(a); nodes[v]["inv"].append(b)
        nodes[u]["top"].append(a + d); nodes[v]["top"].append(b + d)
        links.append({"u": u, "v": v, "a": a, "b": b, "d": d, "w": w, "L": max(L, 1.0),
                      "closed": str(p.get("COVER", "")).strip().lower() == "yes",
                      "bad": str(p.get("STATUS", "")).strip().lower() == "bad"})

    deg = np.zeros(len(nodes), int)
    for l in links:
        deg[l["u"]] += 1; deg[l["v"]] += 1
    for n in nodes:
        n["elev"] = min(n["inv"]); n["street"] = max(n["top"])
    outfall = set()
    for l in links:
        for me, other, my_inv, other_inv in ((l["u"], l["v"], l["a"], l["b"]), (l["v"], l["u"], l["b"], l["a"])):
            if deg[me] == 1 and my_inv <= other_inv:
                outfall.add(me)

    # ---- micro-catchments -> subcatchments ---------------------------------
    R = ROOT / "data" / "terrain" / CITY / "rasters"
    with rasterio.open(R / "catchment_id.tif") as r: cid = r.read(1).astype(np.int64); T = r.transform; tcrs = r.crs
    with rasterio.open(R / "imperviousness.tif") as r: imp = r.read(1)
    with rasterio.open(R / "slope_deg.tif") as r: slope = r.read(1)
    with rasterio.open(ROOT / "data" / "ee" / f"{CITY}_worldcover.tif") as r: wc = r.read(1)
    m = cid >= 0; ids = cid[m]; K = int(ids.max()) + 1; cnt = np.bincount(ids, minlength=K).astype(float)
    mean = lambda a: np.bincount(ids, weights=np.nan_to_num(a[m]), minlength=K) / np.maximum(cnt, 1)
    lut = np.zeros(256); [lut.__setitem__(k, v) for k, v in CN_BY_CLASS_C.items()]
    f_imp, slp, cn = mean(imp), np.tan(np.radians(mean(slope))) * 100, np.clip(mean(lut[wc]), 30, 99)
    rows, cols = np.nonzero(m); xs, ys = rasterio.transform.xy(T, rows, cols)
    to_utm44 = Transformer.from_crs(tcrs, "EPSG:32644", always_xy=True).transform
    X, Y = to_utm44(np.array(xs), np.array(ys))
    cx, cy = np.bincount(ids, weights=X, minlength=K) / np.maximum(cnt, 1), np.bincount(ids, weights=Y, minlength=K) / np.maximum(cnt, 1)
    nxy = np.array([[n["x"], n["y"]] for n in nodes])
    area_ha = cnt * abs(T.a * T.e) / 1e4
    subs, unserved_ha = [], 0.0
    for k in range(K):
        if cnt[k] == 0:
            continue
        dist = np.hypot(nxy[:, 0] - cx[k], nxy[:, 1] - cy[k]); j = int(np.argmin(dist))
        if dist[j] > MAX_OUTLET_M:
            unserved_ha += area_ha[k]; continue
        l_m = 1.4 * ((area_ha[k] / 259.0) ** 0.6) * 1609.34
        subs.append((k, j, area_ha[k], f_imp[k] * 100, max(area_ha[k] * 1e4 / max(l_m, 10), 5), max(slp[k], 0.3), cn[k]))

    # ---- write the .inp -----------------------------------------------------
    if hyetograph:                     # a real storm: minutes,mm_per_h (tools/fetch_rain_event.py)
        rows = [l.split(",") for l in Path(hyetograph).read_text().strip().splitlines()[1:]]
        series = [(int(float(t)), float(v)) for t, v in rows]
        rain_mm = sum(v * (t1 - t0) / 60 for (t0, v), (t1, _) in zip(series, series[1:])); duration_min = series[-1][0]
    else:
        steps = int(duration_min // 5); inten = rain_mm / (duration_min / 60.0)
        series = [(t * 5, inten if t < steps else 0.0) for t in range(steps + 2)]
    end_min = int(duration_min) + 180
    end_date, end_time = f"01/{1 + end_min // 1440:02d}/2026", f"{end_min % 1440 // 60:02d}:{end_min % 60:02d}:00"
    J = lambda i: f"N{i}"
    lines = ["[TITLE]", f"RealTimers Chennai pilot: {rain_mm:g} mm in {duration_min:g} min, from the GCC drain register", "",
             "[OPTIONS]", "FLOW_UNITS CMS", "INFILTRATION CURVE_NUMBER", "FLOW_ROUTING DYNWAVE", "LINK_OFFSETS DEPTH",
             "START_DATE 01/01/2026", "START_TIME 00:00:00", "REPORT_START_DATE 01/01/2026", "REPORT_START_TIME 00:00:00",
             f"END_DATE {end_date}", f"END_TIME {end_time}", "REPORT_STEP 00:05:00", "WET_STEP 00:01:00", "DRY_STEP 00:05:00",
             "ROUTING_STEP 0:00:05", "ALLOW_PONDING NO", "INERTIAL_DAMPING PARTIAL", "VARIABLE_STEP 0.75",
             "LENGTHENING_STEP 10", "MIN_SURFAREA 1.167", "NORMAL_FLOW_LIMITED BOTH", "HEAD_TOLERANCE 0.0015",
             "MAX_TRIALS 8", "MINIMUM_STEP 0.5", "THREADS 1", "",
             "[RAINGAGES]", "RG1 INTENSITY 0:05 1.0 TIMESERIES STORM", "",
             "[SUBCATCHMENTS]"]
    lines += [f"S{k} RG1 {J(j)} {a:.4f} {pi:.1f} {w:.1f} {s:.2f} 0" for k, j, a, pi, w, s, _ in subs]
    lines += ["", "[SUBAREAS]"] + [f"S{k} 0.013 0.15 1.27 5.08 25 OUTLET" for k, *_ in subs]
    lines += ["", "[INFILTRATION]"] + [f"S{k} {c:.1f} 0.5 7" for k, *_, c in subs]
    lines += ["", "[JUNCTIONS]"] + [f"{J(i)} {n['elev']:.3f} {max(n['street'] - n['elev'], 0.2):.3f} 0 0 0"
                                     for i, n in enumerate(nodes) if i not in outfall]
    lines += ["", "[OUTFALLS]"] + [f"{J(i)} {nodes[i]['elev']:.3f} FREE NO" for i in sorted(outfall)]
    lines += ["", "[CONDUITS]"]
    for i, l in enumerate(links):
        lines.append(f"C{i} {J(l['u'])} {J(l['v'])} {l['L']:.1f} {N_BAD if l['bad'] else N_OK} "
                     f"{l['a'] - nodes[l['u']]['elev']:.3f} {l['b'] - nodes[l['v']]['elev']:.3f} 0 0")
    lines += ["", "[XSECTIONS]"] + [f"C{i} {'RECT_CLOSED' if l['closed'] else 'RECT_OPEN'} {l['d']:.3f} {l['w']:.3f} 0 0 1"
                                     for i, l in enumerate(links)]
    lines += ["", "[TIMESERIES]"] + [f"STORM {t // 60}:{t % 60:02d} {v:.3f}" for t, v in series]
    lines += ["", "[REPORT]", "INPUT NO", "CONTROLS NO", "SUBCATCHMENTS NONE", "NODES NONE", "LINKS NONE", "",
              "[COORDINATES]"] + [f"{J(i)} {n['x']:.2f} {n['y']:.2f}" for i, n in enumerate(nodes)]
    inp = out / "chennai.inp"; inp.write_text("\n".join(lines) + "\n")

    meta = {"rain_mm": rain_mm, "duration_min": duration_min, "conduits": len(links), "nodes": len(nodes),
            "outfalls": len(outfall), "subcatchments": len(subs), "unserved_ha": round(unserved_ha, 1),
            "bad_condition_drains": sum(l["bad"] for l in links), "closed_drains": sum(l["closed"] for l in links)}
    (out / "network.json").write_text(json.dumps({"meta": meta, "nodes": [
        {"id": J(i), "lonlat": ll(n["x"], n["y"]), "bad_drain": any(l["bad"] for l in links if i in (l["u"], l["v"]))}
        for i, n in enumerate(nodes)]}))
    print(json.dumps(meta))
    return inp


def run(inp: Path) -> dict:
    from pyswmm import Simulation
    with Simulation(str(inp)) as sim:
        for _ in sim:
            pass
    rpt = inp.with_suffix(".rpt").read_text()
    cont = [float(x) for x in re.findall(r"Continuity Error \(%\) \.+\s+(-?[\d.]+)", rpt)]
    flooded = []
    blk = re.search(r"Node Flooding Summary\s*\n\s*\*+\n(.*?)(?:\n\s*\n\s*\*{5,}|\Z)", rpt, re.S)
    if blk:
        for row in blk.group(1).splitlines():
            t = row.split()
            if len(t) >= 6 and re.match(r"N\d+$", t[0]):
                flooded.append({"node": t[0], "hours": float(t[1]), "max_cms": float(t[2]),
                                "volume_ml": float(t[5])})
    return {"runoff_continuity_pct": cont[0] if cont else None,
            "routing_continuity_pct": cont[1] if len(cont) > 1 else None, "flooded": flooded}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rain", type=float, default=100.0, help="total rainfall, mm")
    ap.add_argument("--duration", type=float, default=120.0, help="minutes")
    ap.add_argument("--hyetograph", default="", help="CSV minutes,mm_per_h from tools/fetch_rain_event.py")
    a = ap.parse_args()
    inp = build(a.rain, a.duration, a.hyetograph)
    res = run(inp)
    net = {n["id"]: n for n in json.loads((inp.parent / "network.json").read_text())["nodes"]}
    for fl in res["flooded"]:
        lon, lat = net[fl["node"]]["lonlat"]
        fl.update(lon=round(lon, 6), lat=round(lat, 6), bad_drain=net[fl["node"]]["bad_drain"],
                  near=_nearest_locality(lon, lat, CITY))
    res["flooded"].sort(key=lambda f: -f["volume_ml"])
    (inp.parent / "flooding.json").write_text(json.dumps(res, indent=1))
    print(f"continuity error: runoff {res['runoff_continuity_pct']}%, routing {res['routing_continuity_pct']}% | "
          f"flooded nodes: {len(res['flooded'])}")
