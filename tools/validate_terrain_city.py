"""
The Bengaluru terrain test, run unchanged on another city's flood records.

    python tools/validate_terrain_city.py --city chennai

Declared before scoring, identical to tools/validate_terrain.py for Bengaluru:
  * valley HAND sampled at every reported flood point in the pilot box
  * exact duplicate points counted once; points on masked sea or missing
    terrain skipped
  * compared with 20,000 random built-up cells (WorldCover class 50)
  * AUC = chance a flood point sits lower than a random built-up cell;
    medians, share within 2 m, and the capture curve
Points come from data/opencity/<city>/validation/*.kml. Per-file results are
printed too, but only the pooled result is the test; the split is exploratory.
"""
import argparse, json, math, re, sys
from pathlib import Path
import numpy as np, rasterio
from pyproj import Transformer
from scipy.stats import mannwhitneyu

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from config import CITIES

ap = argparse.ArgumentParser(); ap.add_argument("--city", default="chennai"); a = ap.parse_args()
W, S, E, N = CITIES[a.city]["bbox"]; R = ROOT / "data" / "terrain" / a.city / "rasters"
with rasterio.open(R / "hand_valley.tif") as r: hv = r.read(1).astype(float); T = r.transform; crs = r.crs
with rasterio.open(ROOT / "data" / "ee" / f"{a.city}_worldcover.tif") as r: wc = r.read(1)
to = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform

def sample(lonlat):
    out = []
    for lon, lat in lonlat:
        x, y = to(lon, lat); c, rr = ~T * (x, y); rr, c = int(rr), int(c)
        if 0 <= rr < hv.shape[0] and 0 <= c < hv.shape[1] and math.isfinite(hv[rr, c]): out.append(hv[rr, c])
    return np.array(out)

seen, pooled, per_file = set(), [], {}
for kml in sorted((ROOT / "data" / "opencity" / a.city / "validation").glob("*.kml")):
    txt = kml.read_text(errors="ignore"); title = (re.findall(r"<name>([^<]*)</name>", txt) or [kml.stem])[0]
    pts = []
    for blk in re.findall(r"<Point>.*?<coordinates>(.*?)</coordinates>", txt, re.S):
        lon, lat = (float(v) for v in blk.strip().split(",")[:2])
        if W <= lon <= E and S <= lat <= N and (round(lon, 6), round(lat, 6)) not in seen:
            seen.add((round(lon, 6), round(lat, 6))); pts.append((lon, lat))
    if pts: per_file[title] = sample(pts); pooled += pts
spots = sample(pooled)
bg_all = hv[(wc == 50) & np.isfinite(hv)]
bg = np.random.default_rng(0).choice(bg_all, size=min(20000, bg_all.size), replace=False)
def auc(s): return float(mannwhitneyu(-s, -bg, alternative="two-sided").statistic / (s.size * bg.size))
thr20 = float(np.quantile(bg, 0.20))
res = {"city": a.city, "source": "Greater Chennai Corporation flood records via OpenCity" if a.city == "chennai" else "",
       "unique_points_in_box": len(pooled), "n_in_pilot": int(spots.size),
       "median_valley_hand_m": round(float(np.median(spots)), 2), "median_built_up_m": round(float(np.median(bg)), 2),
       "auc_vs_built_up": round(auc(spots), 3), "p_value": float(mannwhitneyu(spots, bg, alternative="less").pvalue),
       "share_within_2m": round(float(np.mean(spots <= 2)), 3), "built_up_share_within_2m": round(float(np.mean(bg <= 2)), 3),
       "lowest20_built_up_threshold_m": round(thr20, 2), "lowest20_holds_share_of_spots": round(float(np.mean(spots <= thr20)), 3),
       "capture_curve": {f"{int(q*100)}%": round(float(np.mean(spots <= np.quantile(bg, q))), 3) for q in (0.1, 0.2, 0.3, 0.5, 0.7)},
       "exploratory_by_file": {k: {"n": int(v.size), "auc": round(auc(v), 3)} for k, v in per_file.items() if v.size >= 5}}
out = ROOT / "data" / "terrain" / a.city / "validation.json"
out.write_text(json.dumps({"all": res}, indent=2)); print(json.dumps(res, indent=2))
