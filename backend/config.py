"""Pilot-area settings. Change these first."""

# Pilot bounding box (west, south, east, north) in WGS84.
# ~13 x 13 km over Koramangala, HSR, Silk Board, Agara and Bellandur -- chosen
# because the published BBMP drain network is dense here and several of BBMP's
# own vulnerable-location list sit inside it.
BBOX = (77.5800, 12.8800, 77.7000, 13.0000)

GRID = 240                       # mock depth grid is GRID x GRID cells (~55 m each here)
LEADS = list(range(0, 181, 15))  # forecast lead times in minutes: 0, 15, ... 180

# Depth (cm) above which each vehicle should not be routed. Tunable assumptions.
MODE_THRESHOLD_CM = {"twowheeler": 15, "car": 30, "emergency": 45}
FLOODED_CM = 10                  # a street counts as "flooded" at or above this depth
AVG_SPEED_KMPH = 22              # crude ETA only

# The map network is now the REAL BBMP drain network (backend/network.py).
# The synthetic grid in roads.py is dead code, kept only for reference.
ROADS_SOURCE = "drains"

# One colour scale used by the map overlay AND the frontend gauge legend: (depth cm, hex, opacity)
COLOR_SCALE = [
    (0,  "#cfe3f5", 0.00),
    (4,  "#cfe3f5", 0.00),
    (5,  "#a6cee3", 0.45),
    (15, "#3b8bd0", 0.70),
    (30, "#f2a33a", 0.78),
    (50, "#e0342c", 0.85),
    (80, "#7a0c1e", 0.92),
]
