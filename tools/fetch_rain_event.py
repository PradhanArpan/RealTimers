"""
Rain from a real past storm, from Open-Meteo's archive (ERA5 reanalysis;
free for non-commercial use, no key, data CC BY 4.0).

    python tools/fetch_rain_event.py --city chennai --start 2023-12-03 --end 2023-12-04
    python tools/fetch_rain_event.py --city bengaluru --start 2022-09-04 --end 2022-09-05

Writes data/rain/<city>_<start>_<end>.csv as minutes,mm_per_h -- the format
tools/catchment_runoff.py --hyetograph and tools/build_swmm_chennai.py
--hyetograph read. ERA5 is ~25 km and hourly, so it smooths the short, intense
bursts that flood streets; treat event totals as more reliable than peaks.
"""
import argparse, json, sys, urllib.parse, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from config import CITIES

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--city", required=True, choices=sorted(CITIES)); ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
a = ap.parse_args()
W, S, E, N = CITIES[a.city]["bbox"]
q = urllib.parse.urlencode({"latitude": f"{(S + N) / 2:.4f}", "longitude": f"{(W + E) / 2:.4f}", "start_date": a.start,
                            "end_date": a.end, "hourly": "precipitation", "timezone": "Asia/Kolkata"})
with urllib.request.urlopen(f"https://archive-api.open-meteo.com/v1/archive?{q}", timeout=30) as r:
    d = json.load(r)
mm = [v or 0.0 for v in d["hourly"]["precipitation"]]
out = ROOT / "data" / "rain" / f"{a.city}_{a.start}_{a.end}.csv"; out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("minutes,mm_per_h\n" + "".join(f"{h * 60},{v}\n" for h, v in enumerate(mm)) + f"{len(mm) * 60},0\n")
peak = max(range(len(mm)), key=lambda i: mm[i])
print(f"{a.city} {a.start} to {a.end}: {sum(mm):.1f} mm in total; wettest hour {mm[peak]:.1f} mm at {d['hourly']['time'][peak]} -> {out.relative_to(ROOT)}")
print("Source: Open-Meteo archive (ERA5), ~25 km, hourly. Weather data by Open-Meteo.com (CC BY 4.0).")
