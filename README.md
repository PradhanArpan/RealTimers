# RealTimers — urban flood nowcasting

**Smart India Hackathon 2026 · SIH26085 · Ministry of Earth Sciences / NCMRWF**

**Live: https://realtimers.onrender.com** — Bengaluru, Chennai, Mumbai and Delhi

RealTimers follows rain across the ground, into the drains and onto the streets,
zero to three hours ahead: which drain corridors flood, when, how deep, and
which way a two-wheeler, car or ambulance can still get through.

## What is real, and what is not yet

| | Status |
|---|---|
| Drain networks — BBMP's 6,839 drains; Chennai corporation register, 10,255 | ✅ real, public |
| Terrain for all four cities — streams, micro-catchments, height above drainage | ✅ real, 10 m |
| Bengaluru terrain vs BBMP's own flood spots | ✅ **AUC 0.70** |
| Same test, unchanged, on 499 Chennai GCC records | ✅ **AUC 0.58** — weaker in a flat city, still far from chance |
| Flood-safe routing on 81,003 OpenStreetMap road segments | ✅ live, Bengaluru |
| Runoff per micro-catchment, HEC-HMS method | ✅ built and tested — see `RUNOFF.md` |
| EPA SWMM on Chennai's real drains | ✅ runs, continuity 0.13% — tested against 850 GCC records: **no location skill yet**, see `SWMM.md` |
| Real rain: Open-Meteo forecast shown live; past storms for the models | ✅ model rain, not radar |
| **Depths on the map** | ⚠️ **a demonstration storm over real ground — labelled on screen** |
| Radar nowcast, HEC-RAS 2D, surrogate model | planned |

We report tests as they came out, including one that failed: in Bengaluru,
without published drain sizes, runoff modelling could not beat terrain at
locating flood spots. That is why the drainage physics runs in Chennai.

## Run it

```bash
python -m venv .venv && .venv/Scripts/activate      # Windows; source .venv/bin/activate elsewhere
pip install -r requirements.txt
cd backend && uvicorn main:app --reload --port 8000  # http://localhost:8000/?city=chennai
```

Optional: set `MAPTILER_KEY` for the MapTiler basemap; without it the map uses OpenStreetMap tiles.

## Rebuild and test

```bash
pip install -r requirements-tools.txt
python tools/build_terrain.py --city bengaluru          # terrain layer (needs data/ee/ exports)
python tools/validate_terrain.py                        # AUC against BBMP flood spots
python tools/catchment_runoff.py --uniform 60 --duration 120
python tools/downhill_test.py                           # declared test, run once
python tools/fetch_rain_event.py --city chennai --start 2023-12-03 --end 2023-12-04
python tools/build_swmm_chennai.py --hyetograph data/rain/chennai_2023-12-03_2023-12-04.csv
python tools/validate_swmm_chennai.py                   # needs the GCC flood KMLs, see the script
python tools/validate_terrain_city.py --city chennai     # the Bengaluru terrain test on Chennai's records
```

## API

`/v1/drains` · `/v1/terrain/status|streams|catchments?city=` · `/v1/opencity/{city}/{layer}` ·
`/v1/rain/now?city=` · `/v1/swmm/chennai/flooding` · `/api/alerts|point|route?city=`

## Data and credits

BBMP, Greater Chennai Corporation and GBA data via OpenCity (public domain) ·
Copernicus GLO-30 · ESA WorldCover (CC BY 4.0) · Google Open Buildings ·
OpenStreetMap contributors (ODbL) · © MapTiler · Weather data by Open-Meteo.com (CC BY 4.0) ·
EPA SWMM via PySWMM. Notes: `DATA.md`, `TERRAIN.md`, `CITIES.md`, `RUNOFF.md`, `SWMM.md`.
