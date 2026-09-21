# BBMP stormwater drain network — what the source actually contains

Parsed `bengaluru-stormwater-drains.kml` · 6,839 placemarks.

Source: OpenCity, *Bengaluru Stormwater Drains Maps*, credited to BBMP,
sourced from KSRSAC, public domain.

## Features by class

| Class | In file | Inside pilot bbox | Length in bbox |
|---|---:|---:|---:|
| Primary | 163 | 163 | 328.5 km |
| Secondary | 870 | 870 | 438.8 km |
| Tertiary | 5,806 | 5,806 | 1221.1 km |

Placemarks with no line geometry: 0.
Vertices 764,446 in, 44,998 out after simplification.

## Attributes present

| Attribute | Filled | Example |
|---|---:|---|
| `tessellate` | 6,839/6,839 | -1 |
| `extrude` | 6,839/6,839 | 0 |
| `visibility` | 6,839/6,839 | -1 |
| `OBJECTID_1` | 6,839/6,839 | 1 |
| `OBJECTID` | 6,839/6,839 | 1 |
| `Length` | 6,839/6,839 | 7.53637565 |
| `SHAPE_Leng` | 6,839/6,839 | 7536.37574677 |
| `Type` | 6,839/6,839 | Primary |
| `path` | 6,839/6,839 | D:/OpenCity/Files to Upload/Uploaded Fil… |
| `Bengaluru_GIS_DBO_SWD_Tertiary_Entity` | 5,806/5,806 | LWPolyline |
| `Color` | 5,806/5,806 | 130 |
| `Elevation` | 5,806/5,806 | 0 |
| `FID_` | 5,806/5,806 | 0 |
| `Layer` | 5,806/5,806 | Line_Water |
| `LineWt` | 5,806/5,806 | 25 |
| `Linetype` | 5,806/5,806 | Continuous |
| `RefName` | 0/5,806 |  |
| `Shape_STLength__` | 5,806/5,806 | 51.9663117557 |
| `Shape.STLength()` | 1,033/1,033 | 7536.37574677131 |
| `Bengaluru_GIS.DBO.SWD_Secondary.area` | 870/870 | 0.01507481 |

## Hydraulic attributes needed by SWMM

- **diameter** — NOT IN SOURCE, must be derived
- **invert level** — NOT IN SOURCE, must be derived
- **slope** — NOT IN SOURCE, must be derived
- **node / manhole id** — NOT IN SOURCE, must be derived
- **flow direction** — NOT IN SOURCE, must be derived
- **material** — NOT IN SOURCE, must be derived

> The published network is geometry. Every line above marked *NOT IN SOURCE*
> is synthesised downstream from contributing catchment area to CPHEEO design
> standards, with inverts draped from the DEM under a minimum-slope constraint,
> and is flagged as estimated wherever it is displayed.
