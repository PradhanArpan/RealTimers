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

That list reads like Chennai's known flood areas, but it is **not validated** —
there is no Chennai flood-spot list in the repo yet to score against.

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
