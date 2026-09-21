"""
Turn OpenCity's BBMP stormwater-drain KML into a GeoJSON the dashboard can serve,
and report honestly on what the source does and does not contain.

    python tools/ingest_drains.py data/bengaluru-stormwater-drains.kml

Source: OpenCity, "Bengaluru Stormwater Drains Maps", credited to BBMP,
sourced from KSRSAC, public domain.
https://data.opencity.in/dataset/bengaluru-stormwater-drains-maps

Writes:
    data/drains.geojson    clipped to BBOX, simplified for the browser
    data/drains_report.md  what was found, what is missing, what we synthesise

Nothing here invents a hydraulic attribute. If the source has no diameter,
the report says so, and SWMM attributes get derived later in a separate,
clearly labelled step.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

KML_NS = "{http://www.opengis.net/kml/2.2}"

# Pilot area. Widen to the whole BBMP extent once the pilot works.
BBOX = (77.3800, 12.7200, 77.8800, 13.2200)

# Douglas-Peucker tolerance in degrees, per drain class. Primary drains carry
# the flow that matters, so they keep the most shape.
TOLERANCE = {"Primary": 0.000018, "Secondary": 0.000028, "Tertiary": 0.000040}
PREFIX = {"Primary": "PRI", "Secondary": "SEC", "Tertiary": "TER"}

# Attributes SWMM needs that this source is not expected to carry. Presence is
# checked rather than assumed, so the report stays true if BBMP publishes more.
HYDRAULIC_FIELDS = [
    ("diameter", ("diameter", "dia", "width", "size", "section")),
    ("invert level", ("invert", "inv_lvl", "il_us", "il_ds", "bed_level")),
    ("slope", ("slope", "gradient")),
    ("node / manhole id", ("node", "manhole", "mh_id", "from_node", "to_node")),
    ("flow direction", ("direction", "flow_dir", "downstream")),
    ("material", ("material", "matl")),
]


def local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def parse_coords(raw: str) -> list[list[float]]:
    pts: list[list[float]] = []
    for token in (raw or "").split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            lon, lat = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        if math.isfinite(lon) and math.isfinite(lat):
            pts.append([lon, lat])
    return pts


def placemark_props(pm: ET.Element) -> dict[str, str]:
    """Read ExtendedData in both shapes KML uses: SimpleData and Data/value."""
    props: dict[str, str] = {}
    for el in pm.iter():
        name = local(el.tag)
        if name == "SimpleData":
            key = el.get("name")
            if key:
                props[key] = (el.text or "").strip()
        elif name == "Data":
            key = el.get("name")
            if not key:
                continue
            for child in el:
                if local(child.tag) == "value":
                    props[key] = (child.text or "").strip()
    return props


def placemark_lines(pm: ET.Element) -> list[list[list[float]]]:
    lines = []
    for ls in pm.iter(f"{KML_NS}LineString"):
        node = ls.find(f"{KML_NS}coordinates")
        if node is None:
            continue
        pts = parse_coords(node.text or "")
        if len(pts) >= 2:
            lines.append(pts)
    if not lines:  # namespace-free KML
        for ls in pm.iter():
            if local(ls.tag) != "LineString":
                continue
            for child in ls:
                if local(child.tag) == "coordinates":
                    pts = parse_coords(child.text or "")
                    if len(pts) >= 2:
                        lines.append(pts)
    return lines


def seg_dist_sq(p, a, b) -> float:
    x, y = a[0], a[1]
    dx, dy = b[0] - x, b[1] - y
    if dx or dy:
        t = ((p[0] - x) * dx + (p[1] - y) * dy) / (dx * dx + dy * dy)
        if t > 1:
            x, y = b[0], b[1]
        elif t > 0:
            x, y = x + dx * t, y + dy * t
    dx, dy = p[0] - x, p[1] - y
    return dx * dx + dy * dy


def simplify(points: list[list[float]], tol: float) -> list[list[float]]:
    if len(points) <= 2:
        return points
    tol_sq = tol * tol
    keep = [True] + [False] * (len(points) - 2) + [True]
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        worst, index = tol_sq, -1
        for i in range(first + 1, last):
            d = seg_dist_sq(points[i], points[first], points[last])
            if d > worst:
                worst, index = d, i
        if index > 0:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [p for p, k in zip(points, keep) if k]


def in_bbox(lon: float, lat: float) -> bool:
    return BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]


def length_m(props: dict[str, str]) -> float:
    for key in ("Shape.STLength()", "Shape_STLength__", "SHAPE_Leng", "Shape_Length"):
        try:
            v = float(props.get(key, ""))
            if v > 0:
                return v
        except ValueError:
            pass
    try:  # some exports carry kilometres
        v = float(props.get("Length", ""))
        if v > 0:
            return v * 1000.0
    except ValueError:
        pass
    return 0.0


def haversine_len(lines) -> float:
    total = 0.0
    for line in lines:
        for (lon1, lat1), (lon2, lat2) in zip(line, line[1:]):
            p1, p2 = math.radians(lat1), math.radians(lat2)
            dp = p2 - p1
            dl = math.radians(lon2 - lon1)
            a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
            total += 6371000.0 * 2 * math.asin(math.sqrt(a))
    return total


def run(kml_path: Path, out_dir: Path) -> int:
    if not kml_path.exists():
        print(f"KML not found: {kml_path}", file=sys.stderr)
        print("Download it first — see the header of this file.", file=sys.stderr)
        return 2

    features = []
    counters: Counter[str] = Counter()
    kept: Counter[str] = Counter()
    length_by_type: defaultdict[str, float] = defaultdict(float)
    attr_seen: Counter[str] = Counter()
    attr_nonempty: Counter[str] = Counter()
    attr_example: dict[str, str] = {}
    type_values: Counter[str] = Counter()
    placemarks = 0
    no_geometry = 0
    verts_in = verts_out = 0

    for event, elem in ET.iterparse(str(kml_path), events=("end",)):
        if local(elem.tag) != "Placemark":
            continue
        placemarks += 1
        props = placemark_props(elem)

        for key, value in props.items():
            attr_seen[key] += 1
            if value:
                attr_nonempty[key] += 1
                attr_example.setdefault(key, value)

        drain_type = (props.get("Type") or props.get("type") or "").strip()
        type_values[drain_type or "(blank)"] += 1
        lines = placemark_lines(elem)
        elem.clear()

        if not lines:
            no_geometry += 1
            continue
        if drain_type not in TOLERANCE:
            continue

        counters[drain_type] += 1

        if not any(in_bbox(lon, lat) for line in lines for lon, lat in line):
            continue

        kept[drain_type] += 1
        idx = kept[drain_type]
        verts_in += sum(len(l) for l in lines)
        simple = [
            [[round(lon, 6), round(lat, 6)] for lon, lat in simplify(l, TOLERANCE[drain_type])]
            for l in lines
        ]
        verts_out += sum(len(l) for l in simple)

        metres = length_m(props) or haversine_len(lines)
        length_by_type[drain_type] += metres

        geometry = (
            {"type": "LineString", "coordinates": simple[0]}
            if len(simple) == 1
            else {"type": "MultiLineString", "coordinates": simple}
        )
        properties = {
            "id": f"{PREFIX[drain_type]}-{idx:05d}",
            "type": drain_type,
            "length_m": round(metres, 1),
            "source_id": props.get("OBJECTID_1") or props.get("OBJECTID") or props.get("FID_") or str(idx),
        }
        ref = props.get("RefName", "").strip()
        if ref:
            properties["ref_name"] = ref

        features.append({"type": "Feature", "geometry": geometry, "properties": properties})

    out_dir.mkdir(parents=True, exist_ok=True)
    geo_path = out_dir / "drains.geojson"
    geo_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "attribution": "BBMP stormwater drains via OpenCity (KSRSAC), public domain",
                "bbox": list(BBOX),
                "features": features,
            },
            separators=(",", ":"),
        )
    )

    # ---- report -------------------------------------------------------
    missing, present = [], []
    lowered = {k.lower(): k for k in attr_seen}
    for label, needles in HYDRAULIC_FIELDS:
        hit = next((orig for low, orig in lowered.items() if any(n in low for n in needles)), None)
        (present if hit else missing).append((label, hit))

    lines_out = [
        "# BBMP stormwater drain network — what the source actually contains",
        "",
        f"Parsed `{kml_path.name}` · {placemarks:,} placemarks.",
        "",
        "Source: OpenCity, *Bengaluru Stormwater Drains Maps*, credited to BBMP,",
        "sourced from KSRSAC, public domain.",
        "",
        "## Features by class",
        "",
        "| Class | In file | Inside pilot bbox | Length in bbox |",
        "|---|---:|---:|---:|",
    ]
    for t in ("Primary", "Secondary", "Tertiary"):
        lines_out.append(
            f"| {t} | {counters[t]:,} | {kept[t]:,} | {length_by_type[t] / 1000:.1f} km |"
        )
    lines_out += [
        "",
        f"Placemarks with no line geometry: {no_geometry:,}.",
        f"Vertices {verts_in:,} in, {verts_out:,} out after simplification.",
        "",
        "## Attributes present",
        "",
        "| Attribute | Filled | Example |",
        "|---|---:|---|",
    ]
    for key, seen in attr_seen.most_common():
        ex = attr_example.get(key, "")
        ex = (ex[:40] + "…") if len(ex) > 40 else ex
        lines_out.append(f"| `{key}` | {attr_nonempty[key]:,}/{seen:,} | {ex} |")

    lines_out += ["", "## Hydraulic attributes needed by SWMM", ""]
    for label, hit in present:
        lines_out.append(f"- **{label}** — present as `{hit}`")
    for label, _ in missing:
        lines_out.append(f"- **{label}** — NOT IN SOURCE, must be derived")
    lines_out += [
        "",
        "> The published network is geometry. Every line above marked *NOT IN SOURCE*",
        "> is synthesised downstream from contributing catchment area to CPHEEO design",
        "> standards, with inverts draped from the DEM under a minimum-slope constraint,",
        "> and is flagged as estimated wherever it is displayed.",
        "",
    ]
    report_path = out_dir / "drains_report.md"
    report_path.write_text("\n".join(lines_out))

    size_kb = geo_path.stat().st_size / 1024
    print(f"wrote {geo_path}  ({len(features):,} features, {size_kb:,.0f} kB)")
    print(f"wrote {report_path}")
    if missing:
        print("missing hydraulic attributes: " + ", ".join(m[0] for m in missing))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("kml", type=Path, help="path to the downloaded OpenCity KML")
    ap.add_argument("--out", type=Path, default=Path("data"), help="output directory")
    raise SystemExit(run(ap.parse_args().kml, ap.parse_args().out))
