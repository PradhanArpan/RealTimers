# The real drain network — what we have, and what we don't

The BBMP stormwater drain network is **already in this repo**, ingested and
wired in. You don't need to download anything to run it.

Source: OpenCity, *Bengaluru Stormwater Drains Maps*, credited to BBMP,
sourced from KSRSAC, public domain.
<https://data.opencity.in/dataset/bengaluru-stormwater-drains-maps>

## What came out of the 27 MB KML

6,839 placemarks parsed, every one with valid line geometry.

| Class | Features | Length |
|---|---:|---:|
| Primary | 163 | 328.5 km |
| Secondary | 870 | 438.8 km |
| Tertiary | 5,806 | 1,221.1 km |
| **Total** | **6,839** | **1,988.4 km** |

Primary and secondary together come to 767 km, close to the 842 km figure
usually quoted for BBMP's drain network — a useful sanity check that we
parsed the whole thing.

764,446 vertices in, 44,998 out after per-class simplification. The result is
`data/drains.geojson` at 2.0 MB, covering the full BBMP extent, small enough
to hand straight to the browser.

## What the source does NOT contain

This is the important part, and it is now verified rather than assumed.

Every attribute in the file: `OBJECTID`, `OBJECTID_1`, `FID_`, `Type`,
`Length`, `SHAPE_Leng`, `Shape.STLength()`, `Shape_STLength__`, `Layer`,
`Linetype`, `LineWt`, `Color`, `Elevation`, `RefName`, and an entity field.

None of the following is present:

- **diameter or cross-section**
- **invert level**
- **slope**
- **node / manhole id**
- **flow direction**
- **material**

Two traps worth knowing before anyone stands up and speaks:

- `Elevation` exists but is **0 for all 5,806 tertiary records**. It is a CAD
  artefact, not terrain. Do not cite it as elevation data.
- `RefName` is **empty for all 5,806 tertiary records**. The network carries no
  drain names, so drains can only be identified by BBMP id and class.

## What this changes in the pitch

**Slide 4, Challenge 2** — replace "drainage data is restricted" with:

> The network geometry is public. We have all 6,839 BBMP drains, 1,988 km,
> under a public-domain licence. What is missing is the hydraulic attributes —
> diameter, invert, slope, node topology — which we synthesise from
> contributing catchment area to CPHEEO design standards, drape inverts from
> the DEM under a minimum-slope constraint, and flag as estimated everywhere
> they are shown.

That is a stronger position than the old one. It says we have the data, we
know exactly what it lacks, and we have a defensible method for the gap.

**Defence guide** — the answer to "what if you can't get the drainage data" is
no longer two fallbacks. It is: we already have it; here is the report.

## Re-running the ingester

Only needed if you change the bounding box or BBMP republishes.

```bash
python tools/ingest_drains.py data/bengaluru-stormwater-drains.kml
```

`BBOX` at the top of `tools/ingest_drains.py` currently spans the whole BBMP
area. The raw KML is gitignored — re-download it from the link above if you
need it. `data/drains_report.md` regenerates on every run, so it can never
drift from the data.

## The API

- `GET /v1/drains` — GeoJSON; `?kind=Primary,Secondary` and `?bbox=w,s,e,n`
- `GET /v1/drains/status` — counts, length, attribution, and the list of
  fields the source does not carry

The frontend reads `/v1/drains/status` to draw its provenance chip, so the
caveat appears on screen without anyone having to remember it.

## Next piece

Deriving the directed graph from this geometry: snapping endpoints into nodes,
inferring flow direction by draping the DEM, and emitting something SWMM can
read. That is where the estimated attributes actually get created, and it is
what the Drainage screen needs before it can show real nodes.
