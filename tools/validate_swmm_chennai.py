"""
Test Chennai's SWMM flooding against the corporation's own flood records.

Download from data.opencity.in (Greater Chennai Corporation, public domain):
  * "Chennai Flooding Data"     -> Chennai Inundation Points with Depth of Inundation;
                                   Chennai Flooding Points in 2015
  * "Chennai Floods 2015 Data"  -> GCC Stagnation Locations in 2015
  * "Chennai Floods 2020 Data"  -> Chennai GCC Flood Hotspots 2020
Put the .kml files in data/opencity/chennai/validation/, then:

    python tools/validate_swmm_chennai.py

Method, declared before any Chennai flood data was seen, run once:
  * a junction is "flooded in reality" if a reported point lies within 150 m
  * score each junction by SWMM flood volume in the 100 mm / 2 h run
  * baseline: drain density alone -- junctions within 300 m -- because flood
    reports cluster where drains are dense. SWMM earns credit only by beating it.
"""
import json, re, sys
from pathlib import Path
import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from config import CITIES

RADIUS_M, DENSITY_M = 150.0, 300.0
W, S, E, N = CITIES["chennai"]["bbox"]
utm = Transformer.from_crs("EPSG:4326", "EPSG:32644", always_xy=True).transform

pts = []
for kml in sorted((ROOT / "data/opencity/chennai/validation").glob("*.kml")):
    n0 = len(pts)
    for block in re.findall(r"<Point>.*?<coordinates>(.*?)</coordinates>", kml.read_text(errors="ignore"), re.S):
        lon, lat = (float(v) for v in block.strip().split(",")[:2])
        if W <= lon <= E and S <= lat <= N: pts.append(utm(lon, lat))
    print(f"{kml.name}: {len(pts) - n0} points in the pilot box")
if not pts: sys.exit("No points found. Put the OpenCity .kml files in data/opencity/chennai/validation/")

net = json.loads((ROOT / "data/swmm/chennai/network.json").read_text())["nodes"]
fl = {f["node"]: f["volume_ml"] for f in json.loads((ROOT / "data/swmm/chennai/flooding.json").read_text())["flooded"]}
xy = np.array([utm(*n["lonlat"]) for n in net]); vol = np.array([fl.get(n["id"], 0.0) for n in net])
y = (cKDTree(np.array(pts)).query(xy, distance_upper_bound=RADIUS_M)[0] < np.inf).astype(int)
density = np.array([len(i) for i in cKDTree(xy).query_ball_point(xy, DENSITY_M)])
res = {"reported_points": len(pts), "junctions": len(xy), "junctions_near_reports": int(y.sum()),
       "auc_swmm_volume": round(float(roc_auc_score(y, vol)), 3), "auc_density_only": round(float(roc_auc_score(y, density)), 3),
       "flooded_junctions_near_reports": f"{int(y[vol > 0].sum())} of {int((vol > 0).sum())}",
       "all_junctions_near_reports": f"{int(y.sum())} of {len(y)}"}
(ROOT / "data/swmm/chennai/validation.json").write_text(json.dumps(res, indent=2))
print(json.dumps(res, indent=2))
