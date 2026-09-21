# RealTimers flood nowcast dashboard (scaffold)

Runs today on mock depth data. Each real phase replaces one mock piece without touching the rest.

## Run it
```bash
pip install -r requirements.txt
cd backend
uvicorn main:app --reload --port 8000
# open http://localhost:8000
```
Needs internet in the browser (MapLibre and fonts load from CDNs).

## What you get
- Map with flood-depth overlay, 0-180 min time slider (15-min steps), play button
- Staff-gauge legend; click the map to read depth in cm at that point
- "Worst streets" list (click to fly there and jump to its peak time)
- "Safe route": click start and end, choose vehicle; normal vs flood-safe route at the chosen time
- Mock badge on screen so nobody mistakes demo data for a forecast

## Files
| File | Job | Replace when |
|---|---|---|
| `backend/config.py` | pilot bbox, lead times, depth limits per vehicle, colour scale | day 1: set your pilot area |
| `backend/mock_physics.py` | fake depth cube | Phase E: load real surrogate output (same shape, see docstring) |
| `backend/roads.py` | street network | set `ROADS_SOURCE = "osm"` for real streets |
| `backend/routing.py` | depth per street, alerts, routing | rarely; tune thresholds in config |
| `backend/main.py` | API + serves frontend | add endpoints (nodes, validation, areas) |
| `frontend/index.html` | whole UI | add Area builder and Validation screens |

## Swapping in real depth (Phase E)
`load_depth_cube()` must return a float32 array shaped `(13, GRID, GRID)`: water depth in cm,
row 0 = north edge of `BBOX`, column 0 = west edge, index i = `LEADS[i]` minutes ahead.
Read your GeoTIFFs with rasterio, resample to GRID x GRID, stack, return. Nothing else changes.
For large areas, replace the PNG overlay with TiTiler tiles.

## Real data in the build

The BBMP stormwater drain network is ingested and live: 6,839 drains, 1,988 km,
served at `/v1/drains` and drawn on the map. See [DRAINS.md](DRAINS.md) for what
the source contains, what it does not, and how that changes the pitch.

## Deploying

`render.yaml` is a Render blueprint — New > Blueprint > pick the repo, nothing
else to configure. It pins Python, installs from `requirements.txt`, starts
uvicorn on `$PORT` and health-checks `/v1/drains/status`.

The free plan spins down after 15 minutes idle and takes about a minute to
wake. Switch `plan: free` to `plan: starter` for the pitch window so a judge
clicking the link doesn't wait through a cold start.

## Known limits (be honest about these)
- Depth here is a made-up function of rain, terrain lowness and drain capacity. It is not physics.
- Tested: API endpoints, routing, JS syntax. NOT tested: the page in a real browser, and `ROADS_SOURCE = "osm"`
  (no internet where this was written). Try both first and fix whatever breaks.
- Routing ignores one-way rules only in the synthetic grid (OSM edges keep direction), uses a flat ETA speed,
  and treats depth at one lead time as the whole trip.
- Vehicle depth limits (15 / 30 / 45 cm) are assumptions. Cite a source or label them tunable.
