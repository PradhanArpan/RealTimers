"""
Build the terrain layer for one city: the GIS half of the physics chain.

    python tools/build_terrain.py --city bengaluru

Reads the Earth Engine exports in data/ee/:
    <city>_dem_glo30.tif        Copernicus GLO-30, 30 m
    <city>_worldcover.tif       ESA WorldCover v200, 10 m
    <city>_buildings_2023.tif   Open Buildings 2.5D (presence, height), 10 m
and, if present, data/drains.geojson (BBMP drains) to burn into the terrain.

Writes to data/terrain/<city>/:
    streams.geojson      stream links with Strahler order, gradient, area, and
                         the downstream link -- a directed graph
    catchments.geojson   one micro-catchment per stream link (future SWMM
                         subcatchments)
    terrain_grid.npz     HAND, TWI, imperviousness regridded onto the
                         dashboard's lat/lon grid, for the depth model
    summary.json         counts, thresholds, and the method, stated plainly
and full-resolution GeoTIFFs to data/terrain/<city>/rasters/ (gitignored).

Method, in order:
  1. Resample the 30 m DEM onto the 10 m land-cover grid (bilinear). This adds
     no information; it aligns the terrain with drains, land cover and
     buildings.
  2. Burn in the BBMP drains (primary 5 m, secondary 3 m, tertiary 1.5 m) and
     water bodies from WorldCover, so flow follows the engineered network.
  3. Fill pits and depressions, resolve flats, D8 flow direction, flow
     accumulation (pysheds).
  4. Streams where contributing area exceeds a threshold; Strahler order;
     links split at every junction.
  5. Micro-catchment = every cell draining to the same stream link.
  6. HAND = height of a cell above the first stream cell on its flow path,
     measured on the UNBURNED terrain so burning never inflates it.
  7. TWI = ln(a / tan beta); imperviousness from WorldCover and buildings.

GLO-30 is a SURFACE model: buildings are already in it, smeared to 30 m.
Buildings are therefore NOT raised again here. FABDEM is the bare-earth fix.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import rasterize, shapes
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject, transform_geom
from scipy.ndimage import distance_transform_edt
from shapely.geometry import LineString, mapping, shape
from shapely.ops import transform as shp_transform, unary_union

ROOT = Path(__file__).resolve().parent.parent

# pysheds still calls np.in1d, which NumPy 2 removed. Same behaviour via isin.
if not hasattr(np, "in1d"):
    np.in1d = lambda a, b, *args, **kw: np.isin(np.asarray(a).ravel(), b, *args, **kw)

CITIES = {
    "bengaluru": (77.5800, 12.8800, 77.7000, 13.0000),
    "chennai":   (80.1700, 12.9300, 80.2900, 13.0500),
    "mumbai":    (72.8200, 19.0300, 72.9400, 19.1500),
    "delhi":     (77.1700, 28.5600, 77.2900, 28.6800),
}

# Burn depths. Deep on purpose: GLO-30 carries building and tree bumps of several
# metres, and a 5/3 m burn let flow escape the drains (primary alignment 76%).
# At 12/8/4 m it rises to 95%. HAND is measured on UNBURNED terrain, so the
# depth of the burn never inflates the flood-relevant heights.
BURN_M = {"Primary": 12.0, "Secondary": 8.0, "Tertiary": 4.0}
MAJOR_ORDER = 3
WATER_BURN_M = {80: 4.0, 90: 2.0}          # WorldCover: permanent water, wetland
LAKE_BURN_M = 4.0                           # BBMP lake master list: the real outfalls
STREAM_BURN_M = 8.0                         # BBMP natural stream network

# WorldCover class -> imperviousness. Planning-level assumptions, stated as such.
IMPERV = {10: 0.05, 20: 0.10, 30: 0.15, 40: 0.20, 50: 0.85, 60: 0.40,
          70: 0.00, 80: 0.00, 90: 0.00, 95: 0.00, 100: 0.05}

# D8 codes used by pysheds: N NE E SE S SW W NW
D8 = {64: (-1, 0), 128: (-1, 1), 1: (0, 1), 2: (1, 1),
      4: (1, 0), 8: (1, -1), 16: (0, -1), 32: (-1, -1)}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def read_on_grid(path, band, ref, resampling):
    """Read a raster band resampled onto the reference grid."""
    out = np.full((ref["height"], ref["width"]), np.nan, dtype="float32")
    with rasterio.open(path) as src:
        reproject(rasterio.band(src, band), out,
                  src_transform=src.transform, src_crs=src.crs,
                  dst_transform=ref["transform"], dst_crs=ref["crs"],
                  resampling=resampling, src_nodata=np.nan, dst_nodata=np.nan)
    return out


def fill_nan_nearest(a):
    bad = ~np.isfinite(a)
    if not bad.any():
        return a
    idx = distance_transform_edt(bad, return_distances=False, return_indices=True)
    return a[tuple(idx)]


def receivers(fdir):
    h, w = fdir.shape
    n = h * w
    rows, cols = np.divmod(np.arange(n), w)
    f = fdir.ravel().astype(np.int64)
    dr = np.zeros(n, np.int64)
    dc = np.zeros(n, np.int64)
    for code, (r, c) in D8.items():
        m = f == code
        dr[m], dc[m] = r, c
    rr, cc = rows + dr, cols + dc
    ok = (dr | dc).astype(bool) & (rr >= 0) & (rr < h) & (cc >= 0) & (cc < w)
    rec = np.arange(n)
    rec[ok] = rr[ok] * w + cc[ok]
    return rec


def jump(start, stop_mask):
    """Pointer jumping: follow `start` until a cell in stop_mask (or a fixed point)."""
    t = start.copy()
    for _ in range(64):
        nxt = np.where(stop_mask[t], t, t[t])
        if np.array_equal(nxt, t):
            break
        t = nxt
    return t


def build(city: str, threshold_ha: float, out_grid: int, lakes: bool = True,
          streams: bool = False, out_dir: str | None = None) -> dict:
    t0 = time.time()
    ee = ROOT / "data" / "ee"
    out = Path(out_dir) if out_dir else ROOT / "data" / "terrain" / city
    rdir = out / "rasters"
    rdir.mkdir(parents=True, exist_ok=True)
    bbox = CITIES[city]

    # ---- 1. reference grid = the 10 m land-cover grid -----------------------
    with rasterio.open(ee / f"{city}_worldcover.tif") as src:
        ref = {"crs": src.crs, "transform": src.transform,
               "width": src.width, "height": src.height}
        wc = src.read(1)
    h, w = ref["height"], ref["width"]
    cell = abs(ref["transform"].a)
    valid = wc > 0
    log(f"{city}: grid {w}x{h} at {cell:.0f} m, {ref['crs']}")

    dem = read_on_grid(ee / f"{city}_dem_glo30.tif", 1, ref, Resampling.bilinear)
    pres = read_on_grid(ee / f"{city}_buildings_2023.tif", 1, ref, Resampling.nearest)
    valid &= np.isfinite(dem)
    # The sea is the lowest, flattest ground in a coastal box: left in, it grows
    # "streams" across open water and floods in the depth model. Mask open water
    # at or below 1 m. Rivers, lakes and marshes above that stay in.
    sea = (wc == 80) & np.isfinite(dem) & (dem <= 1.0)
    valid &= ~sea
    dem = fill_nan_nearest(dem).astype("float64")
    pres = np.nan_to_num(pres, nan=0.0)

    # ---- 2. burn drains and water -------------------------------------------
    burn = np.zeros((h, w), "float32")
    drains_used = 0
    dpath = ROOT / "data" / "drains.geojson"
    if city == "bengaluru" and dpath.exists():
        drain_feats = json.loads(dpath.read_text())["features"]
        pairs = []
        for f in drain_feats:
            depth = BURN_M.get(f["properties"]["type"])
            if depth:
                g = transform_geom("EPSG:4326", ref["crs"].to_string(), f["geometry"])
                pairs.append((g, depth))
        pairs.sort(key=lambda p: p[1])          # deepest last, so it wins
        burn = rasterize(pairs, out_shape=(h, w), transform=ref["transform"],
                         fill=0.0, all_touched=True, dtype="float32")
        drains_used = len(pairs)
    # BBMP lakes (polygons) and natural streams (lines), if ingested.
    lakes_used = streams_used = 0
    lpath = ROOT / "data" / "opencity" / city / "lakes_streams.geojson"
    if (lakes or streams) and lpath.exists():
        lfe = json.loads(lpath.read_text())["features"]
        crs_s = ref["crs"].to_string()
        if lakes:
            lk = [(transform_geom("EPSG:4326", crs_s, f["geometry"]), LAKE_BURN_M) for f in lfe
                  if f["geometry"]["type"] in ("Polygon", "MultiPolygon")]
            if lk:
                burn = np.maximum(burn, rasterize(lk, out_shape=(h, w), transform=ref["transform"],
                                                  fill=0.0, dtype="float32"))
                lakes_used = len(lk)
        if streams:
            sk = [(transform_geom("EPSG:4326", crs_s, f["geometry"]), STREAM_BURN_M) for f in lfe
                  if "LineString" in f["geometry"]["type"]]
            if sk:
                burn = np.maximum(burn, rasterize(sk, out_shape=(h, w), transform=ref["transform"],
                                                  fill=0.0, all_touched=True, dtype="float32"))
                streams_used = len(sk)
        log(f"burned {lakes_used} BBMP lakes and {streams_used} BBMP streams")
    on_drain = burn > 0
    for code, depth in WATER_BURN_M.items():
        burn = np.where(wc == code, np.maximum(burn, depth), burn)
    log(f"burned {drains_used} drains and {int(np.isin(wc, list(WATER_BURN_M)).sum()):,} water cells")

    # ---- 3. condition and route (pysheds) ----------------------------------
    from pysheds.grid import Grid

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "burned.tif"
        prof = {"driver": "GTiff", "height": h, "width": w, "count": 1,
                "dtype": "float64", "crs": ref["crs"], "transform": ref["transform"],
                "nodata": -9999.0}
        with rasterio.open(p, "w", **prof) as dst:
            dst.write(dem - burn, 1)
        grid = Grid.from_raster(str(p))
        r = grid.read_raster(str(p))
        r = grid.fill_pits(r)
        r = grid.fill_depressions(r)
        r = grid.resolve_flats(r)
        fdir = np.asarray(grid.flowdir(r))
        acc = np.asarray(grid.accumulation(grid.flowdir(r))).astype("float64")
    log("conditioned: pits and depressions filled, flats resolved, D8 routed")

    n = h * w
    idx = np.arange(n)
    rec = receivers(fdir)
    accf = acc.ravel()
    area_ha = accf * cell * cell / 1e4

    # ---- 4. streams, links, Strahler ---------------------------------------
    stream = (area_ha >= threshold_ha) & valid.ravel()
    inflow = np.zeros(n, np.int32)
    s_idx = idx[stream]
    rs = rec[s_idx]
    ok = stream[rs] & (rs != s_idx)
    np.add.at(inflow, rs[ok], 1)
    is_term = stream & ((rec == idx) | ~stream[rec] | (inflow[rec] >= 2))
    term = jump(np.where(stream & ~is_term, rec, idx), is_term)

    terms = np.unique(term[stream])
    link_of = np.full(n, -1, np.int64)
    link_of[terms] = np.arange(len(terms))
    link = np.where(stream, link_of[term], -1)

    order = np.zeros(n, np.int16)
    maxin = np.zeros(n, np.int16)
    cnt = np.zeros(n, np.int16)
    for c in s_idx[np.argsort(accf[s_idx], kind="stable")]:
        m = maxin[c]
        o = 1 if m == 0 else (m + 1 if cnt[c] >= 2 else m)
        order[c] = o
        rc = rec[c]
        if rc != c and stream[rc]:
            if o > maxin[rc]:
                maxin[rc], cnt[rc] = o, 1
            elif o == maxin[rc]:
                cnt[rc] += 1
    log(f"streams: {int(stream.sum()):,} cells, {len(terms):,} links, max Strahler {int(order.max())}")

    # ---- 5. micro-catchments -----------------------------------------------
    tgt = jump(np.where(stream, idx, rec), stream)
    reached = stream[tgt] & valid.ravel()
    catch = np.where(reached, link[tgt], -1)

    # ---- 6. HAND on the unburned terrain; slope; TWI -----------------------
    demf = dem.ravel()
    hand = np.where(reached, np.maximum(demf - demf[tgt], 0.0), np.nan)

    # Valley HAND: height above the nearest MAJOR stream (Strahler 3+). Local HAND
    # above is referenced to every 4 ha headwater, so nearly everything looks low.
    # Drain overflow pools relative to the major network, so the depth model and
    # the map overlay use this one.
    major = stream & (order >= MAJOR_ORDER)
    tgt_major = jump(np.where(major, idx, rec), major)
    reached_major = major[tgt_major] & valid.ravel()
    hand_major = np.where(reached_major, np.maximum(demf - demf[tgt_major], 0.0), np.nan)
    gy, gx = np.gradient(dem, cell)
    slope_deg = np.degrees(np.arctan(np.hypot(gx, gy)))
    tanb = np.maximum(np.tan(np.radians(slope_deg)), 1e-3).ravel()
    twi = np.log(np.maximum(accf, 1) * cell / tanb)

    # ---- 7. imperviousness --------------------------------------------------
    lut = np.zeros(256, "float32")
    for k, v in IMPERV.items():
        lut[k] = v
    imperv = np.clip(np.maximum(lut[wc], pres), 0, 0.98).ravel()

    def g2(a):
        return a.reshape(h, w)

    V = valid.ravel()
    for name, arr in [("hand", hand), ("hand_valley", hand_major),
                      ("twi", np.where(V, twi, np.nan)),
                      ("slope_deg", np.where(V, slope_deg.ravel(), np.nan)),
                      ("imperviousness", np.where(V, imperv, np.nan)),
                      ("flow_acc_ha", np.where(V, area_ha, np.nan))]:
        prof = {"driver": "GTiff", "height": h, "width": w, "count": 1,
                "dtype": "float32", "crs": ref["crs"], "transform": ref["transform"],
                "nodata": np.nan, "compress": "deflate", "predictor": 3}
        with rasterio.open(rdir / f"{name}.tif", "w", **prof) as dst:
            dst.write(g2(arr).astype("float32"), 1)
    for name, arr, dt in [("strahler", np.where(stream, order, 0), "int16"),
                          ("catchment_id", catch, "int32")]:
        prof = {"driver": "GTiff", "height": h, "width": w, "count": 1, "dtype": dt,
                "crs": ref["crs"], "transform": ref["transform"],
                "nodata": 0 if dt == "int16" else -1, "compress": "deflate"}
        with rasterio.open(rdir / f"{name}.tif", "w", **prof) as dst:
            dst.write(g2(arr).astype(dt), 1)
    log("wrote full-resolution rasters")

    # ---- vectors ------------------------------------------------------------
    to_ll = Transformer.from_crs(ref["crs"], "EPSG:4326", always_xy=True).transform
    T = ref["transform"]

    def xy(i):
        r_, c_ = divmod(int(i), w)
        x, y = T * (c_ + 0.5, r_ + 0.5)
        return x, y

    link_cells: dict[int, list[int]] = {}
    for c in s_idx:
        link_cells.setdefault(int(link[c]), []).append(int(c))

    stream_feats = []
    for lid, cells in link_cells.items():
        cells.sort(key=lambda c: accf[c])
        t_cell = cells[-1]
        down = rec[t_cell]
        path = cells + ([int(down)] if down != t_cell and stream[down] else [])
        if len(path) < 2:
            continue
        line = LineString([xy(c) for c in path])
        length = line.length
        drop = float(demf[cells[0]] - demf[t_cell])
        downstream = int(link[down]) if (down != t_cell and stream[down]) else None
        geom = shp_transform(to_ll, line.simplify(cell * 0.6))
        stream_feats.append({"type": "Feature", "geometry": mapping(geom), "properties": {
            "id": f"L{lid:05d}", "strahler": int(order[t_cell]),
            "length_m": round(length, 1), "drop_m": round(drop, 2),
            "gradient": round(max(drop, 0) / length, 5) if length else 0.0,
            "area_ha": round(float(area_ha[t_cell]), 2),
            "on_drain_share": round(float(on_drain.ravel()[cells].mean()), 2),
            "downstream": f"L{downstream:05d}" if downstream is not None else None,
        }})

    # catchment attributes
    L = len(terms)
    cid = catch[catch >= 0]
    counts = np.bincount(cid, minlength=L).astype(float)

    def mean_by(v):
        s = np.bincount(cid, weights=np.nan_to_num(v[catch >= 0]), minlength=L)
        return np.divide(s, counts, out=np.zeros(L), where=counts > 0)

    m_hand, m_imp, m_slope = mean_by(hand), mean_by(imperv), mean_by(slope_deg.ravel())
    t_order = order[terms]

    polys: dict[int, list] = {}
    for geom, val in shapes(g2(catch).astype("int32"), mask=g2(catch) >= 0, transform=T):
        polys.setdefault(int(val), []).append(shape(geom))
    catch_feats = []
    for lid, parts in polys.items():
        g = unary_union(parts).simplify(cell * 0.8, preserve_topology=True)
        catch_feats.append({"type": "Feature",
                            "geometry": mapping(shp_transform(to_ll, g)),
                            "properties": {
                                "id": f"C{lid:05d}", "link": f"L{lid:05d}",
                                "strahler": int(t_order[lid]),
                                "area_ha": round(counts[lid] * cell * cell / 1e4, 2),
                                "mean_hand_m": round(float(m_hand[lid]), 2),
                                "mean_imperv": round(float(m_imp[lid]), 2),
                                "mean_slope_deg": round(float(m_slope[lid]), 2)}})
    log(f"vectorised {len(stream_feats):,} stream links, {len(catch_feats):,} micro-catchments")

    for name, fc in [("streams", stream_feats), ("catchments", catch_feats)]:
        (out / f"{name}.geojson").write_text(json.dumps(
            {"type": "FeatureCollection", "features": fc}, separators=(",", ":")))

    # ---- regrid onto the dashboard's lat/lon grid ---------------------------
    W_, S_, E_, N_ = bbox

    def to_latlon(arr, size, resampling=Resampling.average):
        dst = np.full((size, size), np.nan, "float32")
        reproject(g2(arr).astype("float32"), dst, src_transform=T, src_crs=ref["crs"],
                  dst_transform=from_bounds(W_, S_, E_, N_, size, size),
                  dst_crs="EPSG:4326", resampling=resampling,
                  src_nodata=np.nan, dst_nodata=np.nan)
        return dst

    np.savez_compressed(out / "terrain_grid.npz",
                        hand=to_latlon(hand, out_grid),
                        hand_valley=to_latlon(hand_major, out_grid),
                        imperv=to_latlon(np.where(V, imperv, np.nan), out_grid),
                        twi=to_latlon(np.where(V, twi, np.nan), out_grid),
                        bbox=np.array(bbox))

    hand_ll = to_latlon(hand_major, 1100)
    try:
        from PIL import Image
        stops = np.array([[0, 8, 48, 107, 230], [2, 33, 113, 181, 205],
                          [5, 66, 146, 198, 160], [9, 158, 202, 225, 90],
                          [14, 222, 235, 247, 0]], float)
        hv = np.clip(np.nan_to_num(hand_ll, nan=99), 0, 14)
        rgba = np.zeros(hv.shape + (4,), np.uint8)
        for ch in range(4):
            rgba[..., ch] = np.interp(hv, stops[:, 0], stops[:, ch + 1])
        rgba[~np.isfinite(hand_ll), 3] = 0
        png = (out / "hand.png") if out_dir else ROOT / "frontend" / "terrain" / f"{city}_hand.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rgba, "RGBA").save(png, optimize=True)
    except ImportError:
        png = None

    # How much of each drain class does the modelled flow actually follow?
    # Sampled along drain length every 5 m, within one cell of a stream.
    alignment = {}
    if drains_used:
        from scipy.ndimage import binary_dilation
        near = binary_dilation(g2(stream), iterations=1)
        inv = ~T
        for kind in ("Primary", "Secondary", "Tertiary"):
            tot = hit = 0
            for f in drain_feats:
                if f["properties"]["type"] != kind:
                    continue
                gg = shape(transform_geom("EPSG:4326", ref["crs"].to_string(), f["geometry"]))
                for ln in (gg.geoms if gg.geom_type == "MultiLineString" else [gg]):
                    k = max(int(ln.length // 5), 2)
                    for j in range(k):
                        px, py = ln.interpolate(j / (k - 1), normalized=True).coords[0]
                        cc_, rr_ = inv * (px, py)
                        cc_, rr_ = int(cc_), int(rr_)
                        if 0 <= rr_ < h and 0 <= cc_ < w:
                            tot += 1
                            hit += bool(near[rr_, cc_])
            if tot:
                alignment[kind] = round(hit / tot, 3)
        log(f"drain alignment by length: {alignment}")

    Hv = hand[np.isfinite(hand)]
    Hm = hand_major[np.isfinite(hand_major)]
    summary = {
        "city": city, "bbox": list(bbox), "crs": ref["crs"].to_string(),
        "cell_m": cell, "grid": [w, h],
        "stream_threshold_ha": threshold_ha,
        "stream_links": len(stream_feats), "micro_catchments": len(catch_feats),
        "max_strahler": int(order.max()),
        "strahler_links": {int(k): int(v) for k, v in zip(*np.unique(
            [f["properties"]["strahler"] for f in stream_feats], return_counts=True))},
        "stream_km": round(sum(f["properties"]["length_m"] for f in stream_feats) / 1000, 1),
        "streams_on_drains_share": round(float(on_drain.ravel()[stream].mean()), 3),
        "drain_alignment_by_length": alignment,
        "burn_depths_m": BURN_M,
        "drains_burned": drains_used,
        "lakes_burned": lakes_used,
        "streams_burned": streams_used,
        "hand_m": {"p10": round(float(np.percentile(Hv, 10)), 2),
                   "p50": round(float(np.percentile(Hv, 50)), 2),
                   "p90": round(float(np.percentile(Hv, 90)), 2)},
        "share_within_2m_hand": round(float((Hv <= 2).mean()), 3),
        "valley_hand_m": {"reference": f"Strahler {MAJOR_ORDER}+ streams",
                          "p10": round(float(np.percentile(Hm, 10)), 2),
                          "p50": round(float(np.percentile(Hm, 50)), 2),
                          "p90": round(float(np.percentile(Hm, 90)), 2)},
        "share_within_2m_valley_hand": round(float((Hm <= 2).mean()), 3),
        "mean_imperviousness": round(float(imperv[V].mean()), 3),
        "sea_masked_share": round(float(sea.mean()), 3),
        "sources": {
            "dem": "Copernicus GLO-30 (surface model), resampled 30 m -> 10 m",
            "land_cover": "ESA WorldCover v200, 10 m",
            "buildings": "Google Open Buildings 2.5D Temporal, 2023, 10 m",
            "drains": "BBMP stormwater drains via OpenCity (KSRSAC)" if drains_used else None,
            "lakes": "BBMP lakes master list via OpenCity" if lakes_used else None,
        },
        "caveats": [
            "GLO-30 is a surface model: buildings are already in it, smeared to 30 m, "
            "lifting built-up cells by roughly 0.3 to 0.9 m. FABDEM is the bare-earth fix.",
            "Resampling 30 m to 10 m aligns layers; it does not add terrain detail.",
            "Imperviousness per land-cover class is a planning assumption.",
            "Strahler order is a descriptor here: the network runs through an "
            "engineered drain and tank cascade, not a natural dendritic basin.",
        ],
        "hand_png": f"terrain/{city}_hand.png" if png else None,
        "build_seconds": round(time.time() - t0, 1),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    log(f"done in {summary['build_seconds']} s")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", default="bengaluru", choices=sorted(CITIES))
    ap.add_argument("--threshold-ha", type=float, default=4.0,
                    help="contributing area that starts a stream, hectares")
    ap.add_argument("--no-lakes", action="store_true", help="do not burn BBMP lake polygons")
    ap.add_argument("--streams", action="store_true", help="also burn the BBMP natural stream network")
    ap.add_argument("--out", default=None, help="write here instead of data/terrain/<city>")
    ap.add_argument("--grid", type=int, default=240,
                    help="size of the lat/lon grid handed to the depth model")
    a = ap.parse_args()
    print(json.dumps(build(a.city, a.threshold_ha, a.grid, lakes=not a.no_lakes,
                           streams=a.streams, out_dir=a.out), indent=2))
