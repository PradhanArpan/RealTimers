"""
MOCK depth generator. This file stands in for Phases A-E until the real pipeline exists.

Contract to keep when you replace it:
    load_depth_cube() -> float32 array, shape (len(LEADS), GRID, GRID), water depth in cm,
    row 0 = north edge of BBOX, column 0 = west edge, lead index i = LEADS[i] minutes ahead.

The real version just reads the depth rasters written by the surrogate (Phase E).
"""
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter, zoom
from config import BBOX, GRID, LEADS

TERRAIN_DIR = Path(__file__).resolve().parent.parent / "data" / "terrain"

# Which terrain fed the last cube -- reported by /v1/terrain/status so the
# dashboard can say whether it is showing real ground or the synthetic stand-in.
TERRAIN_SOURCE: dict = {}      # city -> "real" or "synthetic"


def _real_terrain(city="bengaluru", bbox=None):
    """
    REAL terrain from tools/build_terrain.py: valley HAND (height above the
    nearest Strahler 3+ stream) and imperviousness from WorldCover plus
    buildings. Returns None if the file is missing or built for another box.
    """
    path = TERRAIN_DIR / city / "terrain_grid.npz"
    if not path.exists():
        return None
    z = np.load(path)
    if not np.allclose(z["bbox"], bbox or BBOX, atol=1e-4):
        return None
    hv, hl, imp = z["hand_valley"], z["hand"], z["imperv"]
    if hv.shape != (GRID, GRID):
        f = GRID / hv.shape[0]
        hv, hl, imp = (zoom(np.nan_to_num(a, nan=np.nanmedian(a)), f, order=1) for a in (hv, hl, imp))
    hv = np.nan_to_num(hv, nan=30.0)          # not reaching a major stream = not low-lying
    hl = np.nan_to_num(hl, nan=10.0)
    imp = np.nan_to_num(imp, nan=float(np.nanmean(imp)))
    # Valley position dominates; local ponding adds a little.
    lowness = np.clip(np.exp(-hv / 2.5) + 0.25 * np.exp(-hl / 0.8), 0, 1.3)
    # Open water (imperviousness 0) generates no runoff: lakes and rivers are not
    # 'flooded streets'. Land keeps a small floor so it always sheds some rain.
    return lowness, np.where(imp <= 0.01, 0.0, np.clip(imp, 0.05, 0.98))


def _terrain(rng):
    y, x = np.mgrid[0:GRID, 0:GRID] / (GRID - 1)
    valley_y = 0.55 + 0.12 * np.sin(2 * np.pi * x * 1.3 + 0.5)          # buried valley line
    dist = np.abs(y - valley_y)
    z = 900 + 25 * dist ** 1.2 + 3 * (1 - x)
    z += gaussian_filter(rng.normal(0, 1, (GRID, GRID)), 12) * 6          # rolling relief
    hand = z - z.min(axis=0)[None, :]                                     # crude HAND proxy (m)
    sinks = np.zeros_like(z)                                              # underpasses / low spots
    for cx, cy, s in [(0.28, 0.30, 0.035), (0.72, 0.42, 0.03), (0.50, 0.80, 0.04)]:
        sinks += np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * s ** 2)))
    lowness = np.clip(np.exp(-hand / 1.6) + 0.9 * sinks, 0, 1.4)
    return x, y, lowness


def load_depth_cube(city="bengaluru", bbox=None, rain=None):
    """Depth cube for a city.

    rain=None runs the demonstration storm: a cell drifting east across the box.
    rain=(minutes, mm_per_h) runs a real rain series instead, uniform over the
    box -- which is all a kilometre-scale forecast can honestly say about where
    it falls inside a 13 km pilot.
    """
    rng = np.random.default_rng(7)
    x, y, lowness = _terrain(rng)
    imperv = 0.78 - 0.30 * np.exp(-(((x - 0.7) ** 2 + (y - 0.25) ** 2) / (2 * 0.08 ** 2)))
    real = _real_terrain(city, bbox)
    if real is not None:
        lowness, imperv = real
        TERRAIN_SOURCE[city] = "real"
    else:
        TERRAIN_SOURCE[city] = "synthetic"
    cap = np.full((GRID, GRID), 32.0)                                     # drain drawdown rate (mm/h)
    for bx, by in [(0.35, 0.62), (0.62, 0.55), (0.45, 0.20)]:             # blocked drains
        cap -= 24 * np.exp(-(((x - bx) ** 2 + (y - by) ** 2) / (2 * 0.04 ** 2)))

    minutes = np.arange(0, LEADS[-1] + 1, 5)
    dt_h = 5 / 60

    # Surface storage balance, in mm. Rain that the drains cannot take away
    # accumulates; once the cell passes, the drains draw it down again. This is
    # what makes depth peak and then recede instead of climbing forever.
    # `cap` is read as a drawdown RATE in mm/h, reduced where drains are blocked.
    storage = np.zeros((GRID, GRID))
    depth_at = {}
    for t in minutes:
        if rain is None:
            cx, cy = 0.15 + 0.70 * t / 180, 0.55 + 0.05 * np.sin(t / 40)  # storm cell drifts east
            g = np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * 0.22 ** 2)))
            intensity = 6 + 145 * g * np.exp(-((t - 70) / 70) ** 2)         # mm/h
        else:
            intensity = float(np.interp(t, rain[0], rain[1], right=0.0))    # mm/h, uniform over the box
        inflow = intensity * imperv * dt_h
        outflow = cap * dt_h
        storage = np.maximum(0.0, storage + inflow - outflow)
        depth_at[t] = storage.copy()

    cube = []
    for lead in LEADS:
        depth_cm = depth_at[lead] * 0.42 * (0.12 + 2.0 * lowness ** 1.3)
        cube.append(gaussian_filter(depth_cm, 1.2))
    return np.clip(np.array(cube, dtype=np.float32), 0, 150)
