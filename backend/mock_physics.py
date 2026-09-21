"""
MOCK depth generator. This file stands in for Phases A-E until the real pipeline exists.

Contract to keep when you replace it:
    load_depth_cube() -> float32 array, shape (len(LEADS), GRID, GRID), water depth in cm,
    row 0 = north edge of BBOX, column 0 = west edge, lead index i = LEADS[i] minutes ahead.

The real version just reads the depth rasters written by the surrogate (Phase E).
"""
import numpy as np
from scipy.ndimage import gaussian_filter
from config import GRID, LEADS


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


def load_depth_cube():
    rng = np.random.default_rng(7)
    x, y, lowness = _terrain(rng)
    imperv = 0.78 - 0.30 * np.exp(-(((x - 0.7) ** 2 + (y - 0.25) ** 2) / (2 * 0.08 ** 2)))
    cap = np.full((GRID, GRID), 32.0)                                     # drain capacity (mm)
    for bx, by in [(0.35, 0.62), (0.62, 0.55), (0.45, 0.20)]:             # blocked drains
        cap -= 24 * np.exp(-(((x - bx) ** 2 + (y - by) ** 2) / (2 * 0.04 ** 2)))

    minutes = np.arange(0, LEADS[-1] + 1, 5)
    acc = np.full((GRID, GRID), 22.0)                                     # rain already fallen (mm)
    acc_at = {}
    for t in minutes:
        cx, cy = 0.15 + 0.70 * t / 180, 0.55 + 0.05 * np.sin(t / 40)      # storm cell drifts east
        g = np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * 0.22 ** 2)))
        intensity = 5 + 75 * g * np.exp(-((t - 70) / 70) ** 2)             # mm/h
        acc = acc + intensity * (5 / 60)
        acc_at[t] = acc.copy()

    cube = []
    for lead in LEADS:
        excess = np.maximum(0, acc_at[lead] * imperv - cap)                # mm of surface water
        depth_cm = excess * 0.42 * (0.12 + 2.0 * lowness ** 1.3)
        cube.append(gaussian_filter(depth_cm, 1.2))
    return np.clip(np.array(cube, dtype=np.float32), 0, 150)
