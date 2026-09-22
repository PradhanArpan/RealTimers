"""
Observed rain from a past storm: NASA GPM IMERG Final, half-hourly, ~10 km.

    pip install earthaccess h5py
    python tools/fetch_imerg_event.py --city chennai --start 2023-12-03 --end 2023-12-04

The first run asks for your NASA Earthdata login and saves it on this computer
(in your home folder's .netrc) -- never in the repo. Only the cells over the
pilot box are read from each file, so a two-day storm is a small download.

Writes data/rain/<city>_<start>_<end>_imerg.csv as minutes,mm_per_h, the format
tools/build_swmm_chennai.py --hyetograph and tools/catchment_runoff.py read.
Dates are Indian dates; IMERG runs in UTC, so the window is shifted by 5 h 30 m.
IMERG Final is gauge-corrected and appears about 3.5 months after the month ends.
"""
import argparse, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from config import CITIES

IST = timedelta(hours=5, minutes=30)


def cells(axis, lo, hi):
    """Indices of IMERG cells overlapping [lo, hi]; at least the nearest one."""
    idx = np.where((axis + 0.05 >= lo) & (axis - 0.05 <= hi))[0]
    return idx if idx.size else np.array([int(np.argmin(np.abs(axis - (lo + hi) / 2)))])


def read_box(h5, W, S, E, N):
    g = h5["Grid"]
    var = "precipitation" if "precipitation" in g else "precipitationCal"   # V07 / V06
    lon, lat = g["lon"][:], g["lat"][:]
    i, j = cells(lon, W, E), cells(lat, S, N)
    p = g[var][0, i.min():i.max() + 1, j.min():j.max() + 1].astype(float)
    p[p < 0] = np.nan                                                       # fill value
    return float(np.nanmean(p)), float(np.nanmax(p))


def begin(granule):
    t = granule["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"]
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


def main():
    import earthaccess, h5py
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", required=True, choices=sorted(CITIES)); ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    a = ap.parse_args()
    W, S, E, N = CITIES[a.city]["bbox"]
    t0 = datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc) - IST          # IST midnight, in UTC
    t1 = datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc) + timedelta(days=1) - IST
    earthaccess.login(persist=True)
    res = earthaccess.search_data(short_name="GPM_3IMERGHH", version="07", bounding_box=(W, S, E, N),
                                  temporal=(t0.strftime("%Y-%m-%dT%H:%M:%SZ"), (t1 - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")))
    if not res:
        sys.exit("No IMERG Final files for these dates yet (Final appears ~3.5 months after the month).")
    res = sorted(res, key=begin)
    rows = []
    for g, f in zip(res, earthaccess.open(res)):
        with h5py.File(f, "r") as h:
            mean, peak = read_box(h, W, S, E, N)
        rows.append((int((begin(g) - t0).total_seconds() // 60), mean, peak))
    out = ROOT / "data" / "rain" / f"{a.city}_{a.start}_{a.end}_imerg.csv"; out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("minutes,mm_per_h\n" + "".join(f"{m},{v:.3f}\n" for m, v, _ in rows) + f"{rows[-1][0] + 30},0\n")
    total = sum(v for _, v, _ in rows) * 0.5
    k = max(range(len(rows)), key=lambda i: rows[i][1])
    print(f"{a.city} {a.start} to {a.end}: {len(rows)} half-hours, {total:.1f} mm over the pilot box; "
          f"wettest half-hour {rows[k][1]:.1f} mm/h at {(t0 + timedelta(minutes=rows[k][0]) + IST):%Y-%m-%d %H:%M} IST -> {out.relative_to(ROOT)}")
    print("Source: NASA GPM IMERG Final V07, half-hourly, 0.1 degree (GES DISC).")


if __name__ == "__main__":
    main()
