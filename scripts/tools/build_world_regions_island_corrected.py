#!/usr/bin/env python3
"""Dissolve layer-8 provinces using island-corrected world assignments.

This produces the geometry shown by Godot's I overlay after island/family
corrections. No province geometry is edited: each region is only a union of
whole layer-8 province polygons.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
GEOMETRY_PATH = ROOT / "assets" / "map_geometry" / "provinces.json"
ASSIGNMENTS_PATH = ROOT / "assets" / "game_data" / "world_region_assignments_island_corrected.json"
OUT_PATH = ROOT / "assets" / "regions_world_island_corrected.json"
REPORT_PATH = ROOT / "reports" / "world_regions_island_corrected.json"
EXPECTED_PROVINCES = 4027


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def polygon_from_entry(entry: dict[str, Any]) -> Any:
    rings = entry.get("rings", [])
    if not rings:
        return Polygon()
    geometry = Polygon(rings[0], rings[1:])
    if not geometry.is_valid:
        geometry = geometry.buffer(0)
    return geometry


def polygon_parts(geometry: Any) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, (MultiPolygon, GeometryCollection)) or hasattr(geometry, "geoms"):
        return [g for g in geometry.geoms if isinstance(g, Polygon) and not g.is_empty and g.area > 1.0e-9]
    return []


def rings_payload(poly: Polygon) -> list[list[list[float]]]:
    def ring(coords):
        return [[round(float(x), 2), round(float(y), 2)] for x, y in coords]
    return [ring(poly.exterior.coords)] + [ring(interior.coords) for interior in poly.interiors]


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    geometry_doc = read_json(GEOMETRY_PATH)
    geometry_by_id: dict[str, Any] = {}
    for entry in geometry_doc.get("provinces", []):
        pid = str(entry.get("id", ""))
        geometry = polygon_from_entry(entry)
        if pid and not geometry.is_empty:
            geometry_by_id[pid] = geometry

    assignment_doc = read_json(ASSIGNMENTS_PATH)
    assignments = assignment_doc.get("assignments", [])
    if len(assignments) != EXPECTED_PROVINCES or len(geometry_by_id) != EXPECTED_PROVINCES:
        raise RuntimeError(f"coverage mismatch assignments={len(assignments)} geometry={len(geometry_by_id)}")

    grouped: dict[str, list[Any]] = defaultdict(list)
    names: dict[str, str] = {}
    methods: dict[str, set[str]] = defaultdict(set)
    missing: list[str] = []
    for assignment in assignments:
        pid = str(assignment.get("province_id", ""))
        rid = str(assignment.get("region_id", ""))
        name = str(assignment.get("region_name", rid))
        geometry = geometry_by_id.get(pid)
        if not rid or geometry is None:
            missing.append(pid)
            continue
        grouped[rid].append(geometry)
        names[rid] = name
        methods[rid].add(str(assignment.get("method", "")))

    if missing:
        raise RuntimeError(f"missing {len(missing)} assignment geometries")

    cells: list[dict[str, Any]] = []
    region_stats: list[dict[str, Any]] = []
    for rid in sorted(grouped):
        merged = unary_union(grouped[rid])
        if not merged.is_valid:
            merged = merged.buffer(0)
        parts = sorted(polygon_parts(merged), key=lambda p: (-p.area, p.centroid.x, p.centroid.y))
        for index, poly in enumerate(parts):
            minx, miny, maxx, maxy = poly.bounds
            cells.append({
                "id": f"{rid}__part_{index:03d}",
                "region_id": rid,
                "name": names[rid],
                "rings": rings_payload(poly),
                "bbox": [round(minx, 2), round(miny, 2), round(maxx, 2), round(maxy, 2)],
            })
        region_stats.append({
            "region_id": rid,
            "name": names[rid],
            "province_count": len(grouped[rid]),
            "polygon_part_count": len(parts),
            "methods": sorted(methods[rid]),
        })

    data = {
        "schema_version": 1,
        "format": "world_regions_island_corrected/v1",
        "world_px": geometry_doc.get("world_px", 8192),
        "source_geometry": str(GEOMETRY_PATH),
        "source_assignments": str(ASSIGNMENTS_PATH),
        "method": "dissolve_whole_layer8_provinces_after_island_family_correction",
        "province_count": len(assignments),
        "region_count": len(region_stats),
        "polygon_piece_count": len(cells),
        "cells": cells,
    }
    report = {
        "schema_version": 1,
        "format": "world_regions_island_corrected_report/v1",
        "province_count": len(assignments),
        "region_count": len(region_stats),
        "polygon_piece_count": len(cells),
        "atlantic_europe_province_count": sum(1 for a in assignments if a.get("region_name") == "Атлантические острова Европы"),
        "region_stats": region_stats,
        "hard_fail": False,
    }
    return data, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data, report = build()
    outputs = ((OUT_PATH, data), (REPORT_PATH, report))
    if args.check:
        for path, value in outputs:
            expected = json.dumps(value, ensure_ascii=False, separators=(",", ":")) if path == OUT_PATH else json.dumps(value, ensure_ascii=False, indent=2)
            if path == OUT_PATH:
                expected += "\n"
            else:
                expected += "\n"
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                raise RuntimeError(f"--check mismatch: {path}")
    else:
        OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("WORLD_REGIONS_ISLAND_CORRECTED_OK", f"provinces={report['province_count']}", f"regions={report['region_count']}", f"parts={report['polygon_piece_count']}", f"atlantic={report['atlantic_europe_province_count']}")


if __name__ == "__main__":
    main()
