# Data register

Every dataset in the repo: what it is, where it came from, and what it's used
for. OpenCity files are named by resource ID, so the ID is recorded here.

Rebuild the converted layers from the raw KMLs with:

```bash
python tools/inventory_kml.py <folder>      # identify what each KML is
python tools/ingest_opencity.py <folder>    # convert to data/opencity/
```

## Bengaluru

| Layer | Features | OpenCity ID | Used for |
|---|---:|---|---|
| BBMP stormwater drains | 6,839 | `e42be0cb` | Drain network; burned into terrain; flood corridors |
| **Flood-vulnerable locations** | 200 | `6b3c63b0` | Validation — with ward, place name and zone |
| **Flood-prone locations** | 70 | `00fb1229` | Validation |
| **Low-lying locations** | 128 | `8e87a2fc` | Validation — one of 129 published points has no valid coordinates and is dropped |
| Lakes master list | 181 | `dae235c7` | Outfalls, burned into terrain; map layer |
| BBMP stream network | 3,927 | `dae235c7` | Comparison only — burning it made things worse |
| KSRSAC natural drainage | 2,193 | `8e04a22c` | Comparison |
| GBA boundary | 1 | `53329777` | Map outline |
| GBA corporations | 5 | `790f6df1` | Operator view |
| GBA zones | 10 | `e7ad0eac` | Operator view |
| "Wards" layer | 5 | `632f5209` | Published as wards but holds 5 polygons — kept, not used |

The vulnerable-locations file holds **200** points with no severity class or
buffer radius. An earlier note said 211 with grades; that was wrong.

## Chennai

| Layer | Features | OpenCity ID | Notes |
|---|---:|---|---|
| **GCC stormwater drains** | 10,255 | `c4907fed` | **Inverts at both ends, depth, width, material, condition, obstacles** |
| DSS rivers and streams | 876 | `9434de03` | Chennai basin, by sub-basin |
| DSS macro drains | 15 | `80b07b87` | |
| DSS micro drains | 37 | `4d6437e5` | |
| Buckingham canal | 5 | `1bb30ede` | |
| Krishna water canal | 1 | `b5264c56` | |

The GCC drains are close to a SWMM asset register. Invert levels are filled for
99.5% of drains; 94.5% fall from start to end; median slope is about 1 in 400;
824 drains are marked "Bad" condition and many record obstacles inside them.
Bengaluru's published network has none of this. **4,304 of these drains fall
inside the Chennai pilot box.**

## Not used

Two CSVs downloaded alongside (`b04cc181`, `be6efc3d`) are **Pune** data —
ward drainage coverage and nallah basins — and don't belong to this project.

## Earth Engine exports

Terrain (Copernicus GLO-30), land cover (ESA WorldCover v200) and buildings
(Open Buildings 2.5D, 2023) for all four pilot boxes, in `data/ee/`
(gitignored). The export script is in the build notes.

## Literature

Dwarakish, Pai & Rajeesh (2024). Urban flood hazard zonation in Bengaluru Urban
District, India. *Journal of Landscape Ecology* 17(1).
doi:10.2478/jlecol-2024-0006 — see TERRAIN.md for how our result compares.
