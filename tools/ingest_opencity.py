"""
Convert the OpenCity KML downloads into clean, named GeoJSON.

    python tools/ingest_opencity.py <folder-with-the-kmls>

OpenCity names files by resource ID, so MANIFEST maps each ID prefix to what
the file actually is (identified by tools/inventory_kml.py). Output goes to
data/opencity/<city>/<slug>.geojson, with coordinates rounded to ~10 cm and
only the fields worth keeping.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "opencity"

# prefix: (city, slug, description, fields to keep -- None keeps all)
MANIFEST = {
    "6b3c63b0": ("bengaluru", "flood_vulnerable_locations",
                 "BBMP flood-vulnerable locations (200 points)",
                 ["WARD_NAME", "WARDNO", "LocationName", "ZONE"]),
    "00fb1229": ("bengaluru", "flood_prone_locations",
                 "BBMP flood-prone locations (70 points)", []),
    "8e87a2fc": ("bengaluru", "lowlying_locations",
                 "BBMP low-lying locations (129 points)", []),
    "dae235c7": ("bengaluru", "lakes_streams",
                 "BBMP lakes master list and stream network", None),
    "8e04a22c": ("bengaluru", "ksrsac_natural_drainage",
                 "KSRSAC Bengaluru Urban natural drainage", ["category", "dr_code", "status"]),
    "53329777": ("bengaluru", "gba_boundary", "Greater Bengaluru Authority boundary", []),
    "790f6df1": ("bengaluru", "corporations", "GBA corporations (5), from 19 July 2025", ["corporatio"]),
    "e7ad0eac": ("bengaluru", "zones", "GBA zones within corporations", ["Corporatio", "Zone"]),
    "632f5209": ("bengaluru", "corporations_c2", "Layer published as 'wards'; 5 polygons", ["NewCorp"]),
    "c4907fed": ("chennai", "gcc_stormwater_drains", "Greater Chennai Corporation stormwater drains", None),
    "9434de03": ("chennai", "dss_rivers_streams", "Chennai basin DSS: rivers and streams", None),
    "80b07b87": ("chennai", "dss_macro_drains", "Chennai basin DSS: macro drains", None),
    "4d6437e5": ("chennai", "dss_micro_drains", "Chennai basin DSS: micro drains", None),
    "1bb30ede": ("chennai", "dss_buckingham_canal", "Chennai basin DSS: Buckingham canal", None),
    "b5264c56": ("chennai", "dss_krishna_canal", "Chennai basin DSS: Krishna water canal", None),
}


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def coords(el) -> list:
    out = []
    for tok in (el.text or "").split():
        p = tok.split(",")
        try:
            x, y = float(p[0]), float(p[1])
        except (ValueError, IndexError):
            continue
        # Drop "nan" and out-of-range pairs: one BBMP point has no real
        # coordinates, and a NaN makes the whole layer invalid JSON.
        if math.isfinite(x) and math.isfinite(y) and -180 <= x <= 180 and -90 <= y <= 90:
            out.append([round(x, 6), round(y, 6)])
    return out


def child(el, name):
    for c in el:
        if local(c.tag) == name:
            return c
    return None


def geometry_of(pm) -> dict | None:
    pts, lines, polys = [], [], []
    for g in pm.iter():
        t = local(g.tag)
        if t == "Point":
            c = child(g, "coordinates")
            if c is not None and coords(c):
                pts.append(coords(c)[0])
        elif t == "LineString":
            c = child(g, "coordinates")
            if c is not None and len(coords(c)) >= 2:
                lines.append(coords(c))
        elif t == "Polygon":
            rings = []
            for b in g:
                if local(b.tag) in ("outerBoundaryIs", "innerBoundaryIs"):
                    for lr in b.iter():
                        if local(lr.tag) == "coordinates":
                            r = coords(lr)
                            if len(r) >= 4:
                                (rings.insert(0, r) if local(b.tag) == "outerBoundaryIs" else rings.append(r))
            if rings:
                polys.append(rings)
    if polys:
        return {"type": "Polygon", "coordinates": polys[0]} if len(polys) == 1 else \
               {"type": "MultiPolygon", "coordinates": polys}
    if lines:
        return {"type": "LineString", "coordinates": lines[0]} if len(lines) == 1 else \
               {"type": "MultiLineString", "coordinates": lines}
    if pts:
        return {"type": "Point", "coordinates": pts[0]} if len(pts) == 1 else \
               {"type": "MultiPoint", "coordinates": pts}
    return None


def props_of(pm) -> dict:
    out = {}
    for el in pm.iter():
        t = local(el.tag)
        if t == "SimpleData" and el.get("name"):
            out[el.get("name")] = (el.text or "").strip()
        elif t == "Data" and el.get("name"):
            v = child(el, "value")
            out[el.get("name")] = ((v.text if v is not None else el.text) or "").strip()
    return out


def convert(path: Path) -> list[dict]:
    """Walk the KML keeping track of the enclosing Folder name."""
    feats = []
    tree = ET.parse(str(path))

    def walk(node, folder):
        for c in node:
            t = local(c.tag)
            if t == "Folder":
                nm = child(c, "name")
                walk(c, (nm.text or "").strip() if nm is not None and nm.text else folder)
            elif t == "Document":
                walk(c, folder)
            elif t == "Placemark":
                g = geometry_of(c)
                if g:
                    p = props_of(c)
                    if folder:
                        p["_folder"] = folder
                    feats.append({"type": "Feature", "geometry": g, "properties": p})
    walk(tree.getroot(), "")
    return feats


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "..").resolve()
    index = {}
    for kml in sorted(src.glob("*.kml")):
        key = kml.name[:8]
        if key not in MANIFEST:
            continue
        city, slug, desc, keep = MANIFEST[key]
        feats = convert(kml)
        for f in feats:
            p = f["properties"]
            if keep is not None:
                f["properties"] = {k: p[k] for k in keep if k in p and p[k] != ""}
                if "_folder" in p:
                    f["properties"]["_folder"] = p["_folder"]
            else:
                f["properties"] = {k: v for k, v in p.items() if v not in ("", "<Null>", "Null")}
        d = OUT / city
        d.mkdir(parents=True, exist_ok=True)
        out = d / f"{slug}.geojson"
        out.write_text(json.dumps({"type": "FeatureCollection", "name": slug,
                                   "source": f"OpenCity resource {kml.stem}",
                                   "description": desc, "features": feats},
                                  separators=(",", ":"), allow_nan=False))
        types = {}
        for f in feats:
            types[f["geometry"]["type"]] = types.get(f["geometry"]["type"], 0) + 1
        index[f"{city}/{slug}"] = {"description": desc, "features": len(feats),
                                   "geometry": types, "source_id": kml.stem,
                                   "kb": round(out.stat().st_size / 1024)}
        print(f"{city:9s} {slug:28s} {len(feats):6,d} features  {types}  {out.stat().st_size/1024:8.0f} kB")
    (OUT / "index.json").write_text(json.dumps(index, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
