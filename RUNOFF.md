# Runoff and waterlogging by micro-catchment

`tools/catchment_runoff.py` applies HEC-HMS's method to every micro-catchment
from the terrain layer: SCS curve-number loss from WorldCover land cover, the
SCS unit hydrograph with NRCS TR-55 lag, routing down the catchment graph,
drain capacity by the Rational method, and ponding where flow exceeds capacity.

```bash
python tools/catchment_runoff.py --uniform 60 --duration 120    # 60 mm over 2 h
python tools/catchment_runoff.py --hyetograph gauge.csv         # minutes,mm_per_h
python tools/catchment_runoff.py                                # the demonstration storm
```

Output: `data/terrain/<city>/runoff.json` — per micro-catchment runoff depth,
lag, peak flow, assumed capacity, overflow volume, ponding depth and time to peak.

## What works

**Runoff at micro-catchment level.** Mass balance holds: for 60 mm over
Bengaluru's pilot, 10.2 million m³ of rain gives 6.6 million m³ of runoff (64%,
consistent with ground that is 58% impervious), and no catchment yields more
runoff than the rain that fell on it. Hydrographs, peaks and timing per
catchment are the "how much, and when" half of the problem.

## What failed, and why it matters

**Waterlogging location did not beat terrain alone.** Tested against BBMP's
flood spots (119 micro-catchments hold at least one), with catchment size
controlled because larger catchments contain more spots by chance:

| Storm | Runoff model | Terrain alone |
|---|---:|---:|
| 60 mm in 2 h | 0.47 — only 5 catchments overflow | 0.59 |
| 100 mm in 2 h, pre-declared stress case | 0.43 — 85% of land overflows | 0.59 |

Two physics errors were corrected before the second test — drain capacity must
come from the whole contributing area, and lakes store water rather than
waterlog — and the storm was fixed in advance. It still failed.

**The reason is structural.** BBMP publishes no drain sizes, so capacity is
estimated by the Rational method, in proportion to the area each drain serves.
That makes every drain equally adequate by construction. The model can say how
much water there is, but it has no information about *which* drain fails —
and so no information about where streets flood. Spreading each catchment's
overflow over its own low ground then gave the deepest ponding to catchments
with the *least* low ground, inverting the terrain signal.

Further adjustments were not made: each would be tested against the same 119
catchments, which is how a result gets fitted rather than found.

## What this means for the build

1. **Where water collects is still the terrain's answer** — valley HAND, AUC
   0.70 at cell level. The runoff model supplies how much and when.
2. **Drainage physics needs real drain capacities to add skill.** This is the
   strongest argument yet for running the SWMM step in **Chennai**, whose
   corporation register records invert levels, sizes and condition.
3. **Overflow does not stay in its catchment.** It runs downhill to low
   ground, which is what HEC-RAS 2D computes. The next honest test is to route
   overflow onto the valley floor downstream — with the method declared before
   it is scored.

## Assumptions, stated

Hydrologic soil group C everywhere; curve numbers per WorldCover class from
NRCS TR-55; drains sized for 40 mm/h; 1 m/s travel along stream links;
ponding spread over ground within 1 m of the major drainage. All are written
into `runoff.json` alongside the results.
