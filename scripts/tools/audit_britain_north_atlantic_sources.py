#!/usr/bin/env python3
"""Audit the existing Layer-8 source geometry for Britain and North Atlantic islands.

This is deliberately read-only with respect to gameplay data.  It produces a compact
report before we build a dedicated regional cell/province pipeline, so the new work can
be additive and we do not have to delete or repurpose any existing world/debug layer.

Temporary PR runs this exact audit against the feature branch source data.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGETS = ROOT / "assets" / "game_data" / "world_province_cell_targets.json"
GEOMETRY = ROOT / "assets" / "provinces.json"
REPORT_JSON = ROOT / "reports" / "britain_north_atlantic_source_audit.json"
REPORT_MD = ROOT / "reports" / "britain_north_atlantic_source_audit.md"
WORLD_PX = 8192.0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def world_to_lonlat(x: float, y: float) -> tuple[float, float]:
    lon = x / WORLD_PX * 360.0 - 180.0
    mercator_n = math.pi - 2.0 * math.pi * y / WORLD_PX
    lat = math.degrees(math.atan(math.sinh(mercator_n)))
    return lon, lat


def bbox_from_cell(cell: dict[str, Any]) -> list[float]:
    raw = cell.get("bbox")
    if isinstance(raw, list) and len(raw) >= 4:
        return [float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])]
    xs: list[float] = []
    ys: list[float] = []
    for ring in cell.get("rings", []):
        if not isinstance(ring, list):
            continue
        for p in ring:
            if isinstance(p, list) and len(p) >= 2:
                xs.append(float(p[0])); ys.append(float(p[1]))
    return [min(xs), min(ys), max(xs), max(ys)] if xs else []


def strip_piece_suffix(legacy_id: str) -> str:
    return re.sub(r"_\d+$", "", legacy_id)


def geo_bucket(lon: float, lat: float, prefix: str, name: str) -> str:
    # Explicit island boxes first. These are only for the audit/report and do not
    # decide final gameplay ownership or merge policy.
    if -25.5 <= lon <= -12.0 and 62.5 <= lat <= 67.5:
        return "Iceland"
    if -8.2 <= lon <= -5.8 and 61.0 <= lat <= 63.0:
        return "Faroe Islands"
    if -11.5 <= lon <= -5.0 and 51.0 <= lat <= 56.2:
        return "Ireland"
    if -5.2 <= lon <= -4.0 and 53.9 <= lat <= 54.6:
        return "Isle of Man"
    if -3.2 <= lon <= -1.7 and 48.9 <= lat <= 50.1:
        return "Channel Islands"
    if -8.8 <= lon <= 2.5 and 49.4 <= lat <= 61.5:
        # Scotland/England/Wales are intentionally not inferred from country prefix:
        # Natural Earth names can vary, and this audit should reveal what we actually have.
        if lat >= 55.55:
            return "Scotland candidate"
        if lon <= -2.6 and lat <= 53.8:
            return "Wales candidate"
        return "England candidate"
    return ""


def main() -> None:
    targets_doc = read_json(TARGETS)
    geometry_doc = read_json(GEOMETRY)
    target_records = targets_doc.get("provinces", [])
    geom_by_legacy = {str(c.get("id", "")): c for c in geometry_doc.get("cells", []) if isinstance(c, dict)}

    rows: list[dict[str, Any]] = []
    missing_geometry: list[str] = []
    for raw in target_records:
        if not isinstance(raw, dict):
            continue
        legacy = str(raw.get("legacy_id", ""))
        cell = geom_by_legacy.get(legacy)
        if cell is None:
            continue
        bbox = bbox_from_cell(cell)
        if not bbox:
            missing_geometry.append(legacy)
            continue
        cx = (bbox[0] + bbox[2]) * 0.5
        cy = (bbox[1] + bbox[3]) * 0.5
        lon, lat = world_to_lonlat(cx, cy)
        prefix = str(raw.get("country_prefix", ""))
        name = str(raw.get("name", legacy))
        bucket = geo_bucket(lon, lat, prefix, name)
        if not bucket:
            continue
        rows.append({
            "bucket": bucket,
            "province_id": str(raw.get("province_id", "")),
            "legacy_id": legacy,
            "source_family_key": f"{prefix}|{strip_piece_suffix(legacy)}|{name}",
            "country_prefix": prefix,
            "name": name,
            "region_name": str(raw.get("region_name", "")),
            "area_km2": round(float(raw.get("area_km2", 0.0)), 1),
            "current_target_cell_count": int(raw.get("target_cell_count", 0)),
            "centroid_lon": round(lon, 4),
            "centroid_lat": round(lat, 4),
        })

    rows.sort(key=lambda r: (r["bucket"], r["country_prefix"], r["centroid_lat"], r["centroid_lon"], r["legacy_id"]))
    by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_bucket[row["bucket"]].append(row)

    family_members: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        family_members[row["source_family_key"]].append(row)

    bucket_summary: dict[str, Any] = {}
    for bucket, items in sorted(by_bucket.items()):
        family_keys = {i["source_family_key"] for i in items}
        bucket_summary[bucket] = {
            "render_record_count": len(items),
            "source_family_count": len(family_keys),
            "area_km2_sum": round(sum(float(i["area_km2"]) for i in items), 1),
            "current_target_cells_sum": sum(int(i["current_target_cell_count"]) for i in items),
            "country_prefixes": sorted({str(i["country_prefix"]) for i in items}),
            "region_names": sorted({str(i["region_name"]) for i in items if i["region_name"]}),
        }

    prefix_counts = Counter(str(r["country_prefix"]) for r in rows)
    multipart_families = [
        {
            "source_family_key": key,
            "piece_count": len(items),
            "bucket": items[0]["bucket"],
            "name": items[0]["name"],
            "country_prefix": items[0]["country_prefix"],
            "legacy_ids": [i["legacy_id"] for i in items],
            "area_km2_sum": round(sum(float(i["area_km2"]) for i in items), 1),
        }
        for key, items in sorted(family_members.items()) if len(items) > 1
    ]

    report = {
        "format": "britain_north_atlantic_source_audit/v1",
        "source_target_record_count": len(target_records),
        "selected_render_record_count": len(rows),
        "selected_source_family_count": len(family_members),
        "bucket_summary": bucket_summary,
        "country_prefix_counts": dict(sorted(prefix_counts.items())),
        "multipart_source_families": multipart_families,
        "rows": rows,
        "notes": [
            "Geographic buckets are audit-only and must not be used as final gameplay borders.",
            "Scotland hard gameplay design target from user: 7-10 gameplay provinces, generally 2-3 cells each.",
            "No existing layer/data is modified by this audit.",
        ],
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Britain + North Atlantic source audit",
        "",
        f"Selected render records: **{len(rows)}**",
        f"Selected logical source families (simple piece reconstruction): **{len(family_members)}**",
        "",
        "## Summary by geographic audit bucket",
        "",
        "| Bucket | Render records | Families | Area km² | Current target cells | Prefixes |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for bucket, s in bucket_summary.items():
        lines.append(f"| {bucket} | {s['render_record_count']} | {s['source_family_count']} | {s['area_km2_sum']:.1f} | {s['current_target_cells_sum']} | {', '.join(s['country_prefixes'])} |")
    lines += ["", "## Source records", ""]
    for bucket, items in sorted(by_bucket.items()):
        lines += [f"### {bucket}", "", "| Name | Legacy id | Prefix | Area km² | Current cells | Region | Lon/Lat |", "|---|---|---|---:|---:|---|---|"]
        for r in items:
            lines.append(f"| {r['name']} | `{r['legacy_id']}` | `{r['country_prefix']}` | {r['area_km2']:.1f} | {r['current_target_cell_count']} | {r['region_name']} | {r['centroid_lon']}, {r['centroid_lat']} |")
        lines.append("")
    lines += ["## Multipart/source-family candidates", ""]
    if multipart_families:
        for item in multipart_families:
            lines.append(f"- **{item['bucket']} / {item['name']}** — {item['piece_count']} render pieces, {item['area_km2_sum']:.1f} km²: " + ", ".join(f"`{x}`" for x in item["legacy_ids"]))
    else:
        lines.append("- None in selected audit scope.")
    lines += ["", "## Design constraint", "", "- Scotland: **7–10 gameplay provinces**, normally **2–3 cells per gameplay province**.", "- Existing layers remain untouched; the next build must be a separate regional test pipeline.", ""]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")

    print("BRITAIN_NA_AUDIT", json.dumps({
        "render_records": len(rows),
        "families": len(family_members),
        "buckets": bucket_summary,
        "prefixes": dict(sorted(prefix_counts.items())),
        "multipart_families": len(multipart_families),
    }, ensure_ascii=False))
    for bucket, s in bucket_summary.items():
        print("BUCKET", bucket, s)


if __name__ == "__main__":
    main()
