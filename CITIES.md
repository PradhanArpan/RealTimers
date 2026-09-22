# Four cities

The dashboard covers the four cities named in the problem statement. Switch
with the buttons in the title card, or add `?city=` to the address:
`?city=chennai`, `?city=mumbai`, `?city=delhi`. Bengaluru is the default.

| City | Pilot area | Corridors | Terrain | Validation | Routing |
|---|---|---|---|---|---|
| Bengaluru | Koramangala – HSR – Silk Board – Bellandur | 1,344 BBMP drains | ✅ | AUC 0.70 | ✅ OpenStreetMap |
| Chennai | Velachery – Pallikaranai – Adyar | 4,228 GCC drains | ✅ sea masked | — | — |
| Mumbai | Mithi river: Kurla – BKC – Andheri | 910 terrain flow paths | ✅ sea masked | — | — |
| Delhi | Minto Bridge – ITO – Yamuna | 942 terrain flow paths | ✅ | — | — |

Every city runs the same demonstration storm over its own real terrain.
The depths are labelled as demonstration in all four.

**Corridors.** Bengaluru uses BBMP's published drains. Chennai uses the Greater
Chennai Corporation register, which also records inverts, sizes and condition.
No drain data has been found for Mumbai or Delhi, so their corridors are
terrain flow paths of Strahler order 2 and above, and the screen says so.

**The sea.** In Chennai (16.6% of the box) and Mumbai (4.0%), open water at
or below 1 m is masked before any hydrology runs. Left in, it grew streams
across open water and flooded in the depth model.

**Why routing is Bengaluru-only.** Each city's road network has to sit in
memory, and the free server has 512 MB. With four cities and Bengaluru's
81,003 road segments, startup peaks at about 300 MB. A second road network
would need a larger plan.

**Locality labels** ("near Velachery") are nearest-neighbour against a short
list of well-known places per city, not published names.

Rebuild a city's terrain with `python tools/build_terrain.py --city chennai`.
