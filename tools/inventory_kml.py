"""
Read every KML in a folder, say what each one is, and pack the useful ones.

    python tools/inventory_kml.py ".."

For each KML it reports placemark count, geometry types, the layer name the
publisher gave it, attribute field names, a sample record and the extent --
enough to tell "lakes" from "bus stops" without opening it. Files with
identical content are caught by hash, whatever they are named.

Writes <folder>/opencity_clean.zip: the distinct KMLs, any OpenCity CSVs and
the flood-hazard paper found in Downloads, plus inventory.txt.

Standard library only, so it runs in the project's .venv as-is.
"""
from __future__ import annotations

import hashlib
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

# Already in the repo, so not packed again.
SKIP_PREFIXES = ("e42be0cb",)          # BBMP stormwater drains
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def inspect(path: Path) -> dict:
    info = {"placemarks": 0, "geoms": {}, "name": "", "folders": [], "fields": [],
            "sample": {}, "bbox": [180.0, 90.0, -180.0, -90.0], "error": ""}
    in_pm = False
    try:
        for ev, el in ET.iterparse(str(path), events=("start", "end")):
            t = local(el.tag)
            if ev == "start":
                if t == "Placemark":
                    in_pm = True
                continue
            if t == "name" and not in_pm and el.text:
                txt = el.text.strip()
                if not info["name"]:
                    info["name"] = txt
                elif len(info["folders"]) < 4 and txt not in info["folders"]:
                    info["folders"].append(txt)
            elif t == "SimpleField":
                n = el.get("name")
                if n and n not in info["fields"]:
                    info["fields"].append(n)
            elif t in ("SimpleData", "Data") and in_pm and info["placemarks"] == 0:
                key = el.get("name")
                val = (el.text or "").strip()
                if t == "Data":
                    v = el.find("{*}value")
                    val = (v.text or "").strip() if v is not None else val
                if key and val:
                    info["sample"][key] = val[:40]
            elif t in ("Point", "LineString", "Polygon") and in_pm:
                info["geoms"][t] = info["geoms"].get(t, 0) + 1
            elif t == "coordinates" and el.text:
                b = info["bbox"]
                for tok in el.text.split():
                    parts = tok.split(",")
                    try:
                        x, y = float(parts[0]), float(parts[1])
                    except (ValueError, IndexError):
                        continue
                    b[0], b[1] = min(b[0], x), min(b[1], y)
                    b[2], b[3] = max(b[2], x), max(b[3], y)
            elif t == "Placemark":
                info["placemarks"] += 1
                in_pm = False
                el.clear()
    except ET.ParseError as err:
        info["error"] = f"not valid XML: {err}"
    return info


def main() -> int:
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "..").resolve()
    downloads = Path.home() / "Downloads"
    # originals before browser copies like "name (1).kml"
    kmls = sorted(folder.glob("*.kml"), key=lambda q: (" (" in q.name, q.name))
    if not kmls:
        print(f"No .kml files in {folder}")
        return 1

    seen: dict[str, str] = {}
    lines, pack = [], []
    for p in kmls:
        short = p.name[:8]
        mb = p.stat().st_size / 1_048_576
        if p.stat().st_size == 0:
            lines.append(f"{short}  {mb:5.1f} MB  EMPTY FILE (download failed?) -- skipped")
            continue
        digest = hashlib.sha1(p.read_bytes()).hexdigest()
        if digest in seen:
            lines.append(f"{short}  {mb:5.1f} MB  DUPLICATE of {seen[digest]} -- skipped")
            continue
        seen[digest] = short
        if p.name.lower().startswith(SKIP_PREFIXES):
            lines.append(f"{short}  {mb:5.1f} MB  BBMP drains, already in the repo -- skipped")
            continue

        i = inspect(p)
        geoms = ", ".join(f"{k} {v}" for k, v in i["geoms"].items()) or "no geometry"
        b = i["bbox"]
        ext = (f"lon {b[0]:.3f}..{b[2]:.3f}  lat {b[1]:.3f}..{b[3]:.3f}"
               if b[0] <= b[2] else "no coordinates")
        lines.append(f"{short}  {mb:5.1f} MB  {i['placemarks']:6,d} placemarks  {geoms}")
        lines.append(f"          name    : {i['name'] or '-'}"
                     + (f"  | folders: {'; '.join(i['folders'])}" if i["folders"] else ""))
        lines.append(f"          fields  : {', '.join(i['fields'][:12]) or '-'}")
        if i["sample"]:
            lines.append("          sample  : " + "; ".join(f"{k}={v}" for k, v in list(i["sample"].items())[:6]))
        lines.append(f"          extent  : {ext}")
        if i["error"]:
            lines.append(f"          ERROR   : {i['error']}")
        pack.append(p)

    extras = [c for c in downloads.glob("*.csv") if UUID.match(c.name)]
    extras += list(downloads.glob("Urban_Flood_Hazard_Zonation*.pdf"))
    for e in extras:
        lines.append(f"extra     {e.stat().st_size / 1_048_576:5.1f} MB  {e.name}")

    report = "\n".join(lines)
    print(report)

    out = folder / "opencity_clean.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in pack + extras:
            z.write(p, p.name)
        z.writestr("inventory.txt", report)
    print(f"\n{len(pack)} distinct KMLs + {len(extras)} extras packed -> {out}  "
          f"({out.stat().st_size / 1_048_576:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
