# The terrain layer — built

The GIS half of the physics chain now exists for Bengaluru: conditioned
terrain, flow routing, a stream network with Strahler order, micro-catchments,
HAND, TWI and imperviousness. And the depth model now runs on it — the
synthetic hill is gone.

Rebuild any time, in about 25 seconds:

```bash
pip install -r requirements-tools.txt
python tools/build_terrain.py --city bengaluru
```

The same script takes `--city chennai`, `mumbai` or `delhi`. Without a drain
network to burn in, those cities get terrain-only streams.

## Inputs

| Layer | Source | Resolution |
|---|---|---|
| Terrain | Copernicus GLO-30 | 30 m, resampled to 10 m |
| Land cover | ESA WorldCover v200 | 10 m |
| Buildings | Google Open Buildings 2.5D Temporal, 2023 | 10 m |
| Drains | BBMP stormwater drains via OpenCity (KSRSAC) | vector |

The Earth Engine export script for all four cities is in the build handout
thread; files go in `data/ee/` (gitignored).

## Method

1. Resample the 30 m DEM onto the 10 m land-cover grid. This aligns layers; it
   does not add terrain detail.
2. Burn in the BBMP drains — primary 12 m, secondary 8 m, tertiary 4 m — plus
   BBMP's 181 lakes and water bodies from WorldCover.
3. Fill pits and depressions, resolve flats, D8 flow direction, accumulation.
4. A stream starts where contributing area reaches 4 ha. Links split at every
   junction; Strahler order assigned upstream to downstream.
5. Micro-catchment = every cell draining to the same stream link. Each
   records the link it drains to, and each link records the link downstream —
   so together they form a directed graph ready for SWMM.
6. HAND measured on the **unburned** terrain, so burn depth never inflates it.
   Two versions:
   - **Local HAND**, above the nearest stream of any order — for ponding
   - **Valley HAND**, above the nearest Strahler 3+ stream — where drain
     overflow pools. The depth model and the map overlay use this one.
7. TWI = ln(a / tan β). Imperviousness from WorldCover classes and building
   presence.

## Results, Bengaluru pilot (13 × 13 km)

- **2,646 stream links, 2,651 micro-catchments**, 688 km of stream network
- **Strahler order up to 6.** Links per order: 1,369 · 651 · 329 · 202 · 78 ·
  17 — roughly halving at each order, the branching ratio real networks show
- **The modelled flow follows 92% of primary drain length**, 77% of secondary
  and 42% of tertiary. Tertiary is low because most roadside drains carry less
  than the 4 ha stream threshold — a threshold effect, not a mismatch
- **Valley HAND:** median 8.3 m; 20% of the area lies within 2 m of the major
  drainage
- **Mean imperviousness 58%**
- Lakes land where they should: Bellandur and Madiwala appear as the deepest
  low-lying bodies

With real terrain in the depth model, the worst corridors in the demo storm
fall near **Madiwala and Silk Board** — two of the city's best-known flood
spots. The rainfall is still mock, so treat that as encouraging, not as
validation.

## Does it know where Bengaluru floods?

`tools/validate_terrain.py` samples valley HAND at BBMP's own published flood
locations and compares them with random built-up land. Of the 398 published
points with valid coordinates, 121 fall inside the pilot box.

- BBMP's flood-vulnerable locations sit at a **median valley HAND of 2.2 m**,
  against 8.5 m for built-up land generally
- Half of them lie within 2 m of the major drainage, against 16% of built-up land
- Across all 121 points, **AUC 0.70** against built-up background (p ≈ 10⁻¹⁴)
- **Valley HAND beats local HAND**, 0.70 against 0.61 — the design choice holds

The capture curve shows the trade-off honestly:

| Flag this share of built-up land | Catches this share of BBMP flood spots |
|---:|---:|
| 10% | 28% |
| 20% | 44% |
| 30% | 60% |
| 50% | 79% |
| 70% | 91% |

**What this is:** terrain susceptibility against sites the city lists as
chronic problems. **What it is not:** forecast skill for any storm. Terrain
alone gets to 0.70; the rest is what the drains and the rain add — which is the
argument for the coupled model.

**Robustness.** Adding BBMP's 181 lakes as outfalls moved AUC from 0.701 to
0.699; also burning BBMP's natural stream network moved it to 0.693 and pulled
flow off the engineered drains. The result is stable across reasonable choices.
Lakes are kept, because they are the real outfalls; streams are not, because
many were converted into drains or built over. These choices were made on
physical grounds, not by picking the best score on the same points.

**Against the published zonation.** Dwarakish, Pai & Rajeesh (2024) combine
seven factors with AHP weights into Low/Moderate/High classes and report "more
than 95% accuracy" against BBMP data, without saying how it was computed. A
class map that labels much of the city Moderate or High catches most spots by
construction; the question is how much land it flags. AUC penalises flagging
everything, so 0.70 is the stricter measure. Note also that the paper describes
its CartoDEM as 2.5 m — that is Cartosat's image resolution; the free DEM on
Bhuvan is 30 m. Cite the paper's method, not that figure.

## Two findings worth knowing

**GLO-30 is a surface model, not bare earth.** Buildings are already in it,
smeared to 30 m, lifting built-up cells by roughly 0.3 to 0.9 m — the same order
as the flood depths we care about. So buildings are *not* raised again here;
that would count them twice. **FABDEM**, the bare-earth version of the same
data, is the fix, and moves up the checklist.

**Burn depth matters, and it was tested.** A 5 m / 3 m burn let flow escape the
drains: only 76% of primary drain length carried a stream. At 12 m / 8 m it
rises to 94%. So the drains do sit in the valleys; it was the surface noise
that pulled flow off them. Because HAND is measured on unburned terrain, the
deeper burn costs nothing downstream.

## Caveats to say out loud

- 30 m terrain resampled to 10 m, not a survey. BDA's 1 m contours would change
  this materially.
- Imperviousness per land-cover class is a planning assumption.
- Strahler order is a descriptor here: the network runs through an engineered
  drain and tank cascade, not a natural dendritic basin.
- The rainfall driving the depth model is still mock. Terrain is real; the
  storm is not.

## On the dashboard

A **Layers** card beside the depth scale toggles the BBMP drains, streams by
Strahler order, micro-catchments and the valley HAND overlay. Click a stream
for its order, contributing area, gradient, share on a BBMP drain and the link
it flows into. Click inside a micro-catchment for its area, mean HAND,
imperviousness and slope.

API: `/v1/terrain/status`, `/v1/terrain/streams?min_order=3`,
`/v1/terrain/catchments`.

## What this changes in the pitch

"The terrain layer is built" is now true, with numbers behind it. The micro-
catchments are the SWMM subcatchments; the stream links and their downstream
pointers are the network topology; the drain alignment figure is evidence that
the published BBMP drains and the terrain agree. That is Phase A of the build
handout, done for the pilot.
