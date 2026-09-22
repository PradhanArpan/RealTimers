# Drainage physics — Chennai, with EPA SWMM

`tools/build_swmm_chennai.py` builds an EPA SWMM model of the Chennai pilot
straight from the Greater Chennai Corporation drain register and runs it with
the real SWMM engine (PySWMM).

```bash
pip install -r requirements-tools.txt
python tools/build_swmm_chennai.py --rain 100 --duration 120
```

Output in `data/swmm/chennai/`: `chennai.inp` (opens in EPA SWMM or PCSWMM),
the SWMM report, and `flooding.json` with every flooded junction.

## The network

| | |
|---|---:|
| Drains (conduits) | 4,129 — with the register's inverts, depth, width, cover |
| Junctions | 7,145, drain ends snapped within 5 m |
| Outfalls | 3,041 |
| Micro-catchments feeding in | 1,422 |
| Drains in "Bad" condition | 322 — modelled rougher, n 0.030 against 0.015 |

## Result: 100 mm in 2 hours

- **Continuity error −0.01% for runoff, 0.13% for routing** — the water budget
  closes; the build handout's gate is under 5%.
- **449 junctions flood**, 2.0 billion litres in total, for a median 1.9 h.
- By locality: Madipakkam, Saidapet, Perungudi, Mylapore, T. Nagar, Velachery,
  Pallikaranai, Guindy.

That list reads like Chennai's known flood areas — but tested, it is not.

## Validation against the corporation's records

Declared before any Chennai flood data was seen, run once
(`tools/validate_swmm_chennai.py`): a junction counts as flooded in reality if
a GCC-reported point lies within 150 m; junctions are scored by SWMM flood
volume; drain density alone is the baseline to beat.

| Against 570 unique GCC flooding, stagnation and hotspot points | AUC |
|---|---:|
| SWMM flood volume | **0.497 — chance** |
| Drain density alone | 0.542 |

29% of SWMM's flooded junctions lie near a reported flood, against 31% of all
junctions. **Where SWMM floods says nothing yet about where Chennai floods.**

The likely reason is structural, as in Bengaluru: Chennai's worst floods come
from rivers and canals backing up, and this network ends in 3,041 free
outfalls, as if every drain emptied into open air. The records also mix river
inundation, underpass stagnation and cyclone hotspots, while the model here is
pipe capacity under uniform rain.

A correction: an earlier count of 850 points included one dataset downloaded
twice. Each point now counts once — 570 unique points — and the AUCs are
unchanged, since duplicates mark the same junctions.

## Cyclone Michaung, on real rain

`tools/fetch_rain_event.py` gives 245.4 mm over 3–4 December 2023 from the
ERA5 archive, wettest hour 16.5 mm. SWMM floods only 75 junctions, with
continuity error 0.59%. That is right for the rain it was given, and shows the
archive's weakness: at 25 km and hourly it smooths a cyclone's bursts. Observed
rain — NASA IMERG, MOSDAC, KSNDMC gauges — is needed for real storms.

## What the two cities say together

Terrain is the validated signal (AUC 0.70 in Bengaluru). Pipe capacity alone
found floods no better than chance in both cities. Surface flow and river
backwater decide where streets flood — which is what HEC-RAS 2D and connecting
the drains to the canals address.

## Three findings about the data

**The register's levels and the terrain model don't share a datum.** Ground sits
a median 5.05 m above recorded inverts, though drains are only 0.84 m deep. So
the two are never mixed: street level is taken as the top of the deepest drain at
each junction, since most corporation drains are roadside drains. This is worth
raising with GCC — it decides whether their levels can be combined with any
national elevation data.

**The network is fragmented.** 3,041 of 7,145 junctions are dead ends where a
drain simply stops; in reality those drains discharge into canals and larger
drains not in this register. Each fragment drains freely, backwater from
downstream is missing, and **flooding is probably underestimated**.

**28% of the land has no drain within 250 m** — about 4,000 ha whose runoff
never enters the model.

## Assumptions, stated

Roughness 0.015, or 0.030 for "Bad" drains; street level at the top of the
deepest drain at a junction; hydrologic soil group C and WorldCover curve
numbers; free outfalls; uniform rain over the pilot; dynamic-wave routing.

## Next

1. A Chennai flood-spot list, to validate the way Bengaluru was.
2. Connect the fragments to the canals and rivers from the Chennai basin data
   already in `data/opencity/chennai/`, so backwater is represented.
3. Resolve the datum gap, then couple to the surface in HEC-RAS 2D.
