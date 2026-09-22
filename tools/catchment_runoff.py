"""
Runoff and waterlogging for every micro-catchment -- HEC-HMS's method, in Python.

    python tools/catchment_runoff.py --city bengaluru                    # demonstration storm
    python tools/catchment_runoff.py --uniform 80 --duration 120         # 80 mm over 2 h, everywhere
    python tools/catchment_runoff.py --hyetograph gauge.csv              # minutes,mm_per_h from a gauge

Chain, per micro-catchment (the terrain layer's 2,651 in Bengaluru):
  1. RAIN      areal rainfall each 5 min -- the demo storm at the catchment's
               centroid, a uniform depth, or a gauge hyetograph (CSV).
  2. LOSS      SCS curve number. Impervious share at CN 98; the pervious rest
               from ESA WorldCover classes, assuming hydrologic soil group C.
  3. TRANSFORM SCS triangular unit hydrograph. Lag from the NRCS TR-55 lag
               equation; hydraulic length from Hack's law.
  4. ROUTE     down the catchment graph (each stream link knows the link it
               flows into), lagged by travel time along the link.
  5. CAPACITY  what each link can carry, sized by the Rational method to a
               design intensity -- because BBMP publishes no pipe sizes.
  6. WATERLOG  flow above capacity cannot get away: it ponds on the
               catchment's low-lying ground (valley HAND <= 1 m), giving an
               indicative ponding depth.

Everything marked ASSUMPTION below is a stated planning value, not a
measurement, and is written into the output so it travels with the result.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from config import CITIES, GRID  # noqa: E402

DT_MIN = 5
T_END_MIN = 360            # 3 h of rain window plus recession

# ASSUMPTIONS -- planning values, stated in the output
HSG = "C"
CN_IMPERVIOUS = 98
CN_BY_CLASS_C = {10: 70, 20: 73, 30: 74, 40: 85, 50: 79, 60: 91, 70: 74, 80: 100,
                 90: 85, 95: 70, 100: 74}          # NRCS TR-55, soil group C
DESIGN_INTENSITY_MMH = 40.0      # drains sized to carry this (Rational method)
V_CHANNEL_MS = 1.0               # travel velocity along a stream link
LOW_HAND_M = 1.0                 # ground this close to the major drainage takes the ponding


def scs_q(p_mm: np.ndarray, cn: float) -> np.ndarray:
    """Cumulative runoff (mm) from cumulative rainfall (mm), SCS curve number."""
    s = 25400.0 / cn - 254.0
    ia = 0.2 * s
    return np.where(p_mm > ia, (p_mm - ia) ** 2 / (p_mm - ia + s), 0.0)


def lag_hours(area_ha: float, cn: float, slope_pct: float) -> float:
    """NRCS TR-55 lag, with hydraulic length from Hack's law."""
    a_mi2 = area_ha / 259.0
    l_ft = 1.4 * (a_mi2 ** 0.6) * 5280.0
    s_in = 1000.0 / cn - 10.0
    y = max(slope_pct, 0.5)
    return max((l_ft ** 0.8) * ((s_in + 1) ** 0.7) / (1900.0 * math.sqrt(y)), DT_MIN / 60.0)


def unit_hydrograph(area_ha: float, lag_h: float, dt_h: float) -> np.ndarray:
    """SCS triangular UH: m3/s per mm of excess in one time step."""
    tp = dt_h / 2 + lag_h
    tb = 2.67 * tp
    qp = 0.208 * (area_ha / 100.0) / tp
    t = np.arange(0, tb + dt_h, dt_h) + dt_h / 2
    uh = np.where(t <= tp, qp * t / tp, np.maximum(qp * (tb - t) / (tb - tp), 0))
    vol = uh.sum() * dt_h * 3600.0
    target = area_ha * 1e4 * 1e-3          # 1 mm over the catchment, m3
    return uh * (target / vol) if vol > 0 else uh


def rainfall(mode: str, n_steps: int, centroids_xy: np.ndarray, args) -> np.ndarray:
    """Rain rate mm/h per step, per catchment: shape (catchments, steps)."""
    t = np.arange(n_steps) * DT_MIN
    if mode == "uniform":
        r = np.where(t < args.duration, args.uniform / (args.duration / 60.0), 0.0)
        return np.repeat(r[None, :], len(centroids_xy), axis=0)
    if mode == "hyetograph":
        rows = [l.split(",") for l in Path(args.hyetograph).read_text().strip().splitlines()]
        rows = [(float(a), float(b)) for a, b in rows if a.strip().replace(".", "").isdigit()]
        tm, mmh = zip(*rows)
        r = np.interp(t, tm, mmh, right=0.0)
        return np.repeat(r[None, :], len(centroids_xy), axis=0)
    # demonstration storm -- the same cell the dashboard uses, at each centroid
    x, y = centroids_xy[:, 0][:, None], centroids_xy[:, 1][:, None]
    tt = t[None, :].astype(float)
    cx, cy = 0.15 + 0.70 * tt / 180, 0.55 + 0.05 * np.sin(tt / 40)
    g = np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * 0.22 ** 2)))
    r = 6 + 145 * g * np.exp(-((tt - 70) / 70) ** 2)
    return np.where(tt <= 180, r, 0.0)


def run(city: str, args) -> dict:
    tdir = ROOT / "data" / "terrain" / city
    rdir = tdir / "rasters"
    W, S, E, N = CITIES[city]["bbox"]

    # ---- per-catchment attributes from the rasters -----------------------
    with rasterio.open(rdir / "catchment_id.tif") as r:
        cid = r.read(1).astype(np.int64); T = r.transform; crs = r.crs
    with rasterio.open(rdir / "hand_valley.tif") as r:
        hv = r.read(1)
    with rasterio.open(rdir / "imperviousness.tif") as r:
        imp = r.read(1)
    with rasterio.open(rdir / "slope_deg.tif") as r:
        slope = r.read(1)
    with rasterio.open(ROOT / "data" / "ee" / f"{city}_worldcover.tif") as r:
        wc = r.read(1)
    assert wc.shape == cid.shape, "land cover must be on the terrain grid"
    cell_m2 = abs(T.a * T.e)

    m = cid >= 0
    ids = cid[m]; L = int(ids.max()) + 1
    count = np.bincount(ids, minlength=L).astype(float)
    area_ha = count * cell_m2 / 1e4
    mean = lambda a: np.divide(np.bincount(ids, weights=np.nan_to_num(a[m]), minlength=L), count,
                               out=np.zeros(L), where=count > 0)
    f_imp = np.clip(mean(imp), 0, 0.98)
    slope_pct = np.tan(np.radians(mean(slope))) * 100
    lut = np.zeros(256); [lut.__setitem__(k, v) for k, v in CN_BY_CLASS_C.items()]
    cn_perv = np.clip(mean(lut[wc]), 30, 99)
    water_share = mean(np.isin(wc, (80, 90)).astype(float))   # lakes and wetlands
    low = m & np.isfinite(hv) & (hv <= LOW_HAND_M)
    low_ha = np.bincount(cid[low], minlength=L) * cell_m2 / 1e4
    # fall back to the lowest tenth of the catchment where nothing is within 1 m
    rows, cols = np.nonzero(m)
    xs, ys = rasterio.transform.xy(T, rows, cols)
    from pyproj import Transformer
    to_ll = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    lon, lat = to_ll(np.array(xs), np.array(ys))
    clon = np.bincount(ids, weights=lon, minlength=L) / np.maximum(count, 1)
    clat = np.bincount(ids, weights=lat, minlength=L) / np.maximum(count, 1)
    cxy = np.column_stack([(clon - W) / (E - W), (N - clat) / (N - S)])

    # ---- topology from the stream links ----------------------------------
    streams = json.loads((tdir / "streams.geojson").read_text())["features"]
    info = {}
    for f in streams:
        p = f["properties"]
        k = int(p["id"][1:])
        info[k] = {"down": int(p["downstream"][1:]) if p.get("downstream") else None,
                   "length_m": p["length_m"], "area_contrib_ha": p["area_ha"],
                   "on_drain": p.get("on_drain_share", 0.0), "strahler": p["strahler"]}

    n_steps = T_END_MIN // DT_MIN + 1
    dt_h = DT_MIN / 60.0
    mode = "hyetograph" if args.hyetograph else ("uniform" if args.uniform else "demo")
    rain = rainfall(mode, n_steps, cxy, args)                       # mm/h
    p_cum = np.cumsum(rain * dt_h, axis=1)                          # mm

    local = np.zeros((L, n_steps)); runoff_mm = np.zeros(L); lag_min = np.zeros(L)
    for k in range(L):
        if count[k] == 0:
            continue
        q = f_imp[k] * scs_q(p_cum[k], CN_IMPERVIOUS) + (1 - f_imp[k]) * scs_q(p_cum[k], cn_perv[k])
        excess = np.diff(np.concatenate([[0.0], q]))                # mm per step
        runoff_mm[k] = q[-1]
        cn_comp = f_imp[k] * CN_IMPERVIOUS + (1 - f_imp[k]) * cn_perv[k]
        lg = lag_hours(area_ha[k], cn_comp, slope_pct[k]); lag_min[k] = lg * 60
        local[k] = np.convolve(excess, unit_hydrograph(area_ha[k], lg, dt_h))[:n_steps]

    # ---- route downstream: upstream first (smaller contributing area) ----
    order = sorted(info, key=lambda k: info[k]["area_contrib_ha"])
    inflow = np.zeros((L, n_steps)); outflow = np.zeros((L, n_steps))
    overflow_m3 = np.zeros(L); peak_flow = np.zeros(L); capacity = np.zeros(L)
    area_acc = area_ha.copy(); imp_acc = f_imp * area_ha     # grow as water arrives from upstream
    for k in order:
        if k >= L:
            continue
        q = local[k] + inflow[k]
        # Rational method: a drain is sized for its WHOLE contributing area, with
        # that area's runoff coefficient -- not the local catchment's. ASSUMPTION
        c_run = 0.3 + 0.6 * imp_acc[k] / max(area_acc[k], 1e-9)
        capacity[k] = c_run * DESIGN_INTENSITY_MMH * area_acc[k] / 360.0
        peak_flow[k] = q.max()
        passed = np.minimum(q, capacity[k])
        overflow_m3[k] = np.maximum(q - capacity[k], 0).sum() * DT_MIN * 60
        outflow[k] = passed
        d = info[k]["down"]
        if d is not None and d < L:
            area_acc[d] += area_acc[k]; imp_acc[d] += imp_acc[k]
            shift = int(round(info[d]["length_m"] / V_CHANNEL_MS / 60 / DT_MIN)) if d in info else 0
            inflow[d, shift:] += passed[: n_steps - shift] if shift else passed

    ponding_cm = np.where(low_ha > 0, overflow_m3 / np.maximum(low_ha * 1e4, 1) * 100,
                          overflow_m3 / np.maximum(area_ha * 0.1 * 1e4, 1) * 100)
    ponding_cm = np.minimum(ponding_cm, 150.0)
    t_peak = np.argmax(local + inflow, axis=1) * DT_MIN

    lake = water_share >= 0.3
    ponding_cm = np.where(lake, 0.0, ponding_cm)          # a lake filling is storage, not waterlogging
    cls = np.select([lake, ponding_cm >= 45, ponding_cm >= 15, ponding_cm >= 5],
                    ["lake storage", "high", "moderate", "low"], "none")
    out = {"city": city, "rainfall": {"mode": mode, "areal_mean_total_mm": round(float(p_cum[:, -1][count > 0].mean()), 1)},
           "assumptions": {"hydrologic_soil_group": HSG, "cn_impervious": CN_IMPERVIOUS,
                           "design_intensity_mm_per_h": DESIGN_INTENSITY_MMH, "channel_velocity_m_s": V_CHANNEL_MS,
                           "low_lying_hand_m": LOW_HAND_M, "lag": "NRCS TR-55 with Hack's-law length",
                           "capacity": "Rational method; BBMP publishes no pipe sizes"},
           "catchments": {}}
    for k in range(L):
        if count[k] == 0:
            continue
        out["catchments"][f"C{k:05d}"] = {
            "area_ha": round(float(area_ha[k]), 2), "imperv": round(float(f_imp[k]), 2),
            "cn_pervious": round(float(cn_perv[k]), 1), "lag_min": round(float(lag_min[k]), 1),
            "runoff_mm": round(float(runoff_mm[k]), 1), "peak_flow_m3s": round(float(peak_flow[k]), 3),
            "capacity_m3s": round(float(capacity[k]), 3), "overflow_m3": round(float(overflow_m3[k]), 0),
            "ponding_cm": round(float(ponding_cm[k]), 1), "t_peak_min": int(t_peak[k]), "waterlogging": str(cls[k])}
    (tdir / "runoff.json").write_text(json.dumps(out))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", default="bengaluru", choices=sorted(CITIES))
    ap.add_argument("--uniform", type=float, default=0, help="total rainfall, mm, spread evenly over --duration")
    ap.add_argument("--duration", type=float, default=120, help="minutes, for --uniform")
    ap.add_argument("--hyetograph", default="", help="CSV of minutes,mm_per_h from a gauge")
    a = ap.parse_args()
    res = run(a.city, a)
    c = res["catchments"].values()
    tally = {k: sum(1 for x in c if x["waterlogging"] == k) for k in ("high", "moderate", "low", "none")}
    print(f"{a.city}: {len(res['catchments']):,} micro-catchments | rain {res['rainfall']['mode']}, "
          f"areal mean {res['rainfall']['areal_mean_total_mm']} mm | waterlogging {tally}")
