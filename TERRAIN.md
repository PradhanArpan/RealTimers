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
2. Burn in the BBMP drains — primary 12 m, secondary 8 m, tertiary 4 m — and
   water bodies from WorldCover.
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

- **2,654 stream links, 2,661 micro-catchments**, 688 km of stream network
- **Strahler order up to 6.** Links per order: 1,373 · 646 · 333 · 203 · 83 ·
  16 — roughly halving at each order, the branching ratio real networks show
- **The modelled flow follows 94% of primary drain length**, 78% of secondary
  and 43% of tertiary. Tertiary is low because most roadside drains carry less
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
