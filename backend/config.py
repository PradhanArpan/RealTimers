"""Pilot-area settings. Change these first."""

# Pilot bounding box (west, south, east, north) in WGS84.
# Placeholder: ~2 km x 2 km around Bellandur, Bengaluru. Replace with your pilot area.
BBOX = (77.6700, 12.9210, 77.6884, 12.9390)

GRID = 200                       # mock depth grid is GRID x GRID cells (~10 m each)
LEADS = list(range(0, 181, 15))  # forecast lead times in minutes: 0, 15, ... 180

# Depth (cm) above which each vehicle should not be routed. Tunable assumptions.
MODE_THRESHOLD_CM = {"twowheeler": 15, "car": 30, "emergency": 45}
FLOODED_CM = 10                  # a street counts as "flooded" at or above this depth
AVG_SPEED_KMPH = 22              # crude ETA only

# "synthetic" = built-in grid of streets (always works, offline)
# "osm"       = real streets via osmnx (needs `pip install osmnx` and internet)
ROADS_SOURCE = "synthetic"

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
