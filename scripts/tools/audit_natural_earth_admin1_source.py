#!/usr/bin/env python3
"""Audit raw Natural Earth 10m Admin-1 source before project merge heuristics.

Input is the official ne_10m_admin_1_states_provinces shapefile. The script is
read-only and emits a compact report proving what names/types/areas exist in
Natural Earth before build_provinces.py transforms them.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import shapefile
from pyproj import Geod
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[2]
OUT_JSON = ROOT / "reports/natural_earth_admin1_source_audit.json"
OUT_MD = ROOT / "reports/natural_earth_admin1_source_audit.md"
GEOD = Geod(ellps="WGS84")

WATCH = {
    ("Switzerland", "Appenzell Innerrhoden"),
    ("Latvia", "Jekabpils"),
    ("United Kingdom", "Northumberland"),
}


def geodesic_area_km2(geom: Any) -> float:
    if geom.is_empty:
        return 0.0
    area_m2, _ = GEOD.geometry_area_perimeter(geom)
    return abs(float(area_m2)) / 1_000_000.0


def fix_mojibake(value: Any) -> str:
    s = "" if value is None else str(value)
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("shp", type=Path)
    args = ap.parse_args()

    reader = shapefile.Reader(str(args.shp), encoding="utf-8")
    fields = [f[0] for f in reader.fields[1:]]
    rows = []
    type_counts = Counter()
    country_counts = Counter()
    exact_name_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for sr in reader.iterShapeRecords():
        props = dict(zip(fields, sr.record))
        admin = fix_mojibake(props.get("admin"))
        name = fix_mojibake(props.get("name") or props.get("name_en") or admin)
        region = fix_mojibake(props.get("region"))
        type_en = fix_mojibake(props.get("type_en"))
        adm1_code = fix_mojibake(props.get("adm1_code"))
        iso_3166_2 = fix_mojibake(props.get("iso_3166_2"))
        geom = shape(sr.shape.__geo_interface__)
        area = geodesic_area_km2(geom)
        row = {
            "admin": admin,
            "name": name,
            "region": region,
            "type_en": type_en,
            "adm1_code": adm1_code,
            "iso_3166_2": iso_3166_2,
            "geodesic_area_km2": round(area, 6),
            "geometry_type": geom.geom_type,
            "part_count": len(getattr(geom, "geoms", [geom])),
        }
        rows.append(row)
        exact_name_groups[(admin, name)].append(row)
        type_counts[type_en] += 1
        country_counts[admin] += 1

    watch_rows = []
    for key in sorted(WATCH):
        watch_rows.extend(exact_name_groups.get(key, []))

    duplicate_name_groups = [
        {
            "admin": admin,
            "name": name,
            "feature_count": len(items),
            "combined_area_km2": round(sum(x["geodesic_area_km2"] for x in items), 6),
            "adm1_codes": sorted({x["adm1_code"] for x in items if x["adm1_code"]}),
            "types": sorted({x["type_en"] for x in items if x["type_en"]}),
        }
        for (admin, name), items in exact_name_groups.items()
        if len(items) > 1
    ]
    duplicate_name_groups.sort(key=lambda x: (-x["feature_count"], x["admin"], x["name"]))

    report = {
        "schema_version": 1,
        "format": "natural_earth_admin1_source_audit/v1",
        "source_shapefile": str(args.shp),
        "summary": {
            "feature_count": len(rows),
            "country_count": len(country_counts),
            "exact_country_name_group_count": len(exact_name_groups),
            "duplicate_exact_country_name_group_count": len(duplicate_name_groups),
            "watch_row_count": len(watch_rows),
        },
        "watch_rows": watch_rows,
        "duplicate_exact_country_name_groups_top100": duplicate_name_groups[:100],
        "type_en_counts": dict(type_counts.most_common()),
        "notes": [
            "Areas are WGS84 geodesic areas of raw Natural Earth features.",
            "No project merge, simplify, crop, overlap cleanup or island filtering is applied.",
            "adm1_code/iso_3166_2 are retained here because they are better logical-parent keys than a generated polygon-piece suffix.",
        ],
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Raw Natural Earth Admin-1 source audit",
        "",
        f"- Features: **{len(rows)}**",
        f"- Countries: **{len(country_counts)}**",
        f"- Exact `(admin,name)` groups: **{len(exact_name_groups)}**",
        f"- Repeated exact `(admin,name)` groups in source: **{len(duplicate_name_groups)}**",
        "",
        "## Diagnostic names before project processing",
        "",
        "| Admin | Name | type_en | adm1_code | ISO | WGS84 km² | geometry | parts |",
        "|---|---|---|---|---|---:|---|---:|",
    ]
    for x in watch_rows:
        lines.append(
            f"| {x['admin']} | {x['name']} | {x['type_en']} | {x['adm1_code']} | {x['iso_3166_2']} | "
            f"{x['geodesic_area_km2']:.1f} | {x['geometry_type']} | {x['part_count']} |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "If a watched raw feature is normal-sized here but enormous in `world_province_identity_geometry_audit.md`, "
        "the corruption is introduced by the project preprocessing stage rather than by the source dataset or area formula.",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print("NATURAL_EARTH_ADMIN1_SOURCE_AUDIT", json.dumps(report["summary"], ensure_ascii=False))
    for x in watch_rows:
        print("WATCH", json.dumps(x, ensure_ascii=False))


if __name__ == "__main__":
    main()
