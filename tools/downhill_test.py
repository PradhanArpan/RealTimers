"""
Downhill routing test: does overflow, sent down to the valley floor, find
Bengaluru's flood spots better than terrain alone?

Method, declared before scoring and run once:
  * runoff model with the pre-declared stress storm, 100 mm in 2 h
  * each catchment's overflow travels down the catchment graph to the first
    catchment with >= 20% of its ground within 1 m of the major drainage
    (valley HAND), or leaves the area
  * lakes (>= 30% water) that receive water store it -- not waterlogging
  * ponding = arriving volume / that catchment's low-lying area
  * score: AUC against BBMP flood spots within catchment-size fifths
"""
import json, math, sys, types
from pathlib import Path
import numpy as np, rasterio
from pyproj import Transformer
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import catchment_runoff as cr

RECEIVER_LOW_SHARE, LOW_HAND_M, LAKE_SHARE = 0.20, 1.0, 0.30
city = "bengaluru"; T_DIR = ROOT / "data" / "terrain" / city; R = T_DIR / "rasters"

run = cr.run(city, types.SimpleNamespace(uniform=100.0, duration=120.0, hyetograph=""))["catchments"]
with rasterio.open(R / "catchment_id.tif") as r: cid = r.read(1).astype(np.int64); T = r.transform; crs = r.crs
with rasterio.open(R / "hand_valley.tif") as r: hv = r.read(1)
with rasterio.open(ROOT / "data" / "ee" / f"{city}_worldcover.tif") as r: wc = r.read(1)
m = cid >= 0; L = int(cid.max()) + 1; ids = cid[m]; cnt = np.bincount(ids, minlength=L).astype(float)
share = lambda b: np.bincount(ids, weights=b[m].astype(float), minlength=L) / np.maximum(cnt, 1)
low_share = share(np.nan_to_num(hv, nan=99) <= LOW_HAND_M); water = share(np.isin(wc, (80, 90)))
low_ha = low_share * cnt * abs(T.a * T.e) / 1e4

down = {}
for f in json.loads((T_DIR / "streams.geojson").read_text())["features"]:
    p = f["properties"]; down[int(p["id"][1:])] = int(p["downstream"][1:]) if p.get("downstream") else None

arrive = np.zeros(L)
for k in range(L):
    v = run.get(f"C{k:05d}", {}).get("overflow_m3", 0.0)
    if v <= 0: continue
    j, hops = k, 0
    while j is not None and low_share[j] < RECEIVER_LOW_SHARE and hops < 500:
        j = down.get(j); hops += 1
    if j is not None and j < L: arrive[j] += v                   # otherwise it leaves the area
pond = np.where(water >= LAKE_SHARE, 0.0, arrive / np.maximum(low_ha * 1e4, 1) * 100)

to = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
spot = np.zeros(L, bool)
for name in ["flood_vulnerable_locations", "flood_prone_locations", "lowlying_locations"]:
    for ft in json.loads((ROOT / "data" / "opencity" / city / f"{name}.geojson").read_text())["features"]:
        x, y = to(*ft["geometry"]["coordinates"][:2])
        if not (math.isfinite(x) and math.isfinite(y)): continue
        c, r_ = ~T * (x, y); r_, c = int(r_), int(c)
        if 0 <= r_ < cid.shape[0] and 0 <= c < cid.shape[1] and cid[r_, c] >= 0: spot[cid[r_, c]] = True

keys = np.array([k for k in range(L) if f"C{k:05d}" in run]); y = spot[keys].astype(int); area = cnt[keys]
def strat(s):
    e = np.quantile(area, np.linspace(0, 1, 6)); out = []
    for a, b in zip(e, e[1:]):
        sel = (area >= a) & (area <= b)
        if y[sel].min() != y[sel].max(): out.append(roc_auc_score(y[sel], s[sel]))
    return float(np.mean(out))
res = {"terrain_alone": strat(low_share[keys]), "downhill_routing": strat(pond[keys]),
       "receivers": int((pond[keys] > 0).sum()), "spot_catchments": int(y.sum()),
       "spot_catchments_in_receivers": int(y[pond[keys] > 0].sum()),
       "receiver_land_share": float(cnt[keys][pond[keys] > 0].sum() / cnt[keys].sum())}
(T_DIR / "downhill_test.json").write_text(json.dumps(res, indent=2))
print(json.dumps(res, indent=2))
