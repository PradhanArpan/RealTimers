"""
Does the terrain layer know where Bengaluru floods?

    python tools/validate_terrain.py [--terrain data/terrain/bengaluru]

Samples valley HAND and local HAND at BBMP's published flood locations
(vulnerable, flood-prone, low-lying) and compares them with random background
points -- across the whole pilot, and across built-up land only, because the
flood spots are all in built-up areas and a fair test must compare like with
like. Reports AUC: the chance a flood spot sits lower than a random point.

What this is: a test of terrain SUSCEPTIBILITY against locations the city lists
as chronic problems. What it is not: forecast skill for any storm. Writes
validation.json next to the terrain.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from scipy.stats import mannwhitneyu

ROOT = Path(__file__).resolve().parent.parent
SETS = {"vulnerable": "flood_vulnerable_locations",
        "flood_prone": "flood_prone_locations",
        "low_lying": "lowlying_locations"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--terrain", default=str(ROOT / "data" / "terrain" / "bengaluru"))
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    tdir = Path(a.terrain)
    rdir = tdir / "rasters"
    rng = np.random.default_rng(a.seed)

    with rasterio.open(rdir / "hand_valley.tif") as r:
        hv, T, crs = r.read(1), r.transform, r.crs
    with rasterio.open(rdir / "hand.tif") as r:
        hl = np.nan_to_num(r.read(1), nan=99.0)
    with rasterio.open(rdir / "imperviousness.tif") as r:
        imp = r.read(1)
    H, W = hv.shape
    to_utm = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform

    valid = np.isfinite(hv)
    built = valid & (imp >= 0.5)
    pick = lambda m: np.argwhere(m)[rng.choice(int(m.sum()), 20000, replace=False)]
    bg_all, bg_built = pick(valid), pick(built)

    def cells(name):
        out, skipped = [], 0
        path = ROOT / "data" / "opencity" / "bengaluru" / f"{name}.geojson"
        for f in json.loads(path.read_text())["features"]:
            lon, lat = f["geometry"]["coordinates"][:2]
            x, y = to_utm(lon, lat)
            if not (math.isfinite(x) and math.isfinite(y)):
                skipped += 1
                continue
            c, r_ = ~T * (x, y)
            r_, c = int(r_), int(c)
            if 0 <= r_ < H and 0 <= c < W and np.isfinite(hv[r_, c]):
                out.append((r_, c))
        return np.array(out), skipped

    def score(pts, bg, arr):
        p, b = arr[pts[:, 0], pts[:, 1]], arr[bg[:, 0], bg[:, 1]]
        u = mannwhitneyu(p, b, alternative="less")
        return p, b, float(1 - u.statistic / (len(p) * len(b))), float(u.pvalue)

    result = {"what": "terrain susceptibility vs BBMP-listed flood locations; not forecast skill",
              "background": "20,000 random cells; 'built_up' = imperviousness >= 0.5",
              "sets": {}}
    allpts, skipped_total = [], 0
    for key, name in SETS.items():
        pts, sk = cells(name)
        skipped_total += sk
        allpts.append(pts)
        p, _, auc_all, _ = score(pts, bg_all, hv)
        _, b, auc_b, pv = score(pts, bg_built, hv)
        result["sets"][key] = {"n_in_pilot": int(len(pts)),
                               "median_valley_hand_m": round(float(np.median(p)), 2),
                               "auc_vs_area": round(auc_all, 3), "auc_vs_built_up": round(auc_b, 3),
                               "p_value": pv,
                               "share_within_2m": round(float(np.mean(p <= 2)), 3)}
    pts = np.vstack(allpts)
    p, _, auc_all, _ = score(pts, bg_all, hv)
    _, b, auc_b, pv = score(pts, bg_built, hv)
    _, _, auc_local, _ = score(pts, bg_built, hl)
    thr = float(np.quantile(hv[built], 0.2))
    result["all"] = {
        "n_in_pilot": int(len(pts)), "skipped_bad_coordinates": skipped_total,
        "median_valley_hand_m": round(float(np.median(p)), 2),
        "median_built_up_m": round(float(np.median(b)), 2),
        "auc_vs_area": round(auc_all, 3), "auc_vs_built_up": round(auc_b, 3), "p_value": pv,
        "auc_local_hand_vs_built_up": round(auc_local, 3),
        "share_within_2m": round(float(np.mean(p <= 2)), 3),
        "built_up_share_within_2m": round(float(np.mean(b <= 2)), 3),
        "lowest20_built_up_threshold_m": round(thr, 2),
        "lowest20_holds_share_of_spots": round(float(np.mean(p <= thr)), 3),
        # flag this share of built-up land (lowest valley HAND first) -> share of spots caught
        "capture_curve": {f"{int(q * 100)}%": round(float(np.mean(p <= np.quantile(hv[built], q))), 3)
                          for q in (0.1, 0.2, 0.3, 0.5, 0.7)},
    }
    (tdir / "validation.json").write_text(json.dumps(result, indent=2))
    A = result["all"]
    print(f"{A['n_in_pilot']} flood spots in the pilot | valley HAND AUC {A['auc_vs_built_up']} vs built-up "
          f"(local HAND {A['auc_local_hand_vs_built_up']}) | lowest 20% of built-up land holds "
          f"{A['lowest20_holds_share_of_spots']*100:.0f}% of spots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
