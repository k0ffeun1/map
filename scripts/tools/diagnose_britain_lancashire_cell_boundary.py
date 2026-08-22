#!/usr/bin/env python3
"""Diagnose suspicious internal cell boundaries in Lancashire/Manchester.

This inspects the generated Stage-6 cells that the Godot viewer actually draws.
Shared boundary fragments are line-merged before measuring so a visually single
hairpin cannot hide as dozens of two-point GEOS intersection segments.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, unary_union

ROOT = Path(__file__).resolve().parents[2]
CELLS_PATH = ROOT / "assets" / "subdivision_stage6" / "britain_north_atlantic_subdivisions.json"
REPORT_PATH = ROOT / "reports" / "britain_lancashire_cell_boundary_diagnostic.json"
PARENT_ID = "gb_england_lancashire_manchester"
EPS = 1.0e-8


def polygon_parts(geometry: Any) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [g for g in geometry.geoms if isinstance(g, Polygon) and not g.is_empty]
    return []


def line_parts(geometry: Any) -> list[LineString]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry] if geometry.length > EPS else []
    result: list[LineString] = []
    if hasattr(geometry, "geoms"):
        for item in geometry.geoms:
            result.extend(line_parts(item))
    return result


def merged_line_parts(geometry: Any) -> list[LineString]:
    raw = line_parts(geometry)
    if not raw:
        return []
    merged = linemerge(unary_union(raw))
    return sorted(line_parts(merged), key=lambda line: -line.length)


def cell_geometry(cell: dict[str, Any]) -> Any:
    parts: list[Any] = []
    for part in cell.get("parts", []):
        rings = part.get("rings", []) if isinstance(part, dict) else []
        if not rings or len(rings[0]) < 3:
            continue
        geom: Any = Polygon(rings[0], rings[1:])
        if not geom.is_valid:
            geom = geom.buffer(0)
        parts.extend(polygon_parts(geom))
    geometry = unary_union(parts) if parts else Polygon()
    if not geometry.is_valid:
        geometry = geometry.buffer(0)
    return geometry


def path_length(points: list[tuple[float, float]]) -> float:
    return sum(math.dist(points[i - 1], points[i]) for i in range(1, len(points)))


def closed_area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    total = 0.0
    for i, point in enumerate(points):
        other = points[(i + 1) % len(points)]
        total += point[0] * other[1] - other[0] * point[1]
    return abs(total) * 0.5


def max_deviation(coords: list[tuple[float, float]]) -> float:
    if len(coords) < 3:
        return 0.0
    chord = LineString([coords[0], coords[-1]])
    return max(chord.distance(Point(p)) for p in coords[1:-1])


def strongest_subpath(coords: list[tuple[float, float]]) -> dict[str, Any] | None:
    """Find the strongest thin out-and-back subpath with intentionally broad limits."""
    best: tuple[float, dict[str, Any]] | None = None
    n = len(coords)
    for i in range(n - 2):
        running = 0.0
        for j in range(i + 1, n):
            running += math.dist(coords[j - 1], coords[j])
            if running > 45.0:
                break
            if j <= i + 1 or running < 0.5:
                continue
            sub = coords[i : j + 1]
            chord = math.dist(sub[0], sub[-1])
            if chord < 0.01:
                continue
            stretch = running / chord
            excess = running - chord
            area = closed_area(sub)
            width = 2.0 * area / max(running, EPS)
            # Broad diagnostic criteria: final fixer will be much stricter.
            if stretch < 1.25 or excess < 0.25 or width > 1.5:
                continue
            severity = (stretch - 1.0) * excess / max(width + 0.02, 0.02)
            row = {
                "start_index": i,
                "end_index": j,
                "path_world_px": round(running, 6),
                "chord_world_px": round(chord, 6),
                "stretch": round(stretch, 6),
                "excess_world_px": round(excess, 6),
                "effective_width_world_px": round(width, 6),
                "start": [round(sub[0][0], 6), round(sub[0][1], 6)],
                "end": [round(sub[-1][0], 6), round(sub[-1][1], 6)],
                "coordinates": [[round(x, 6), round(y, 6)] for x, y in sub],
            }
            if best is None or severity > best[0]:
                best = (severity, row)
    return None if best is None else best[1]


def component_metrics(line: LineString) -> dict[str, Any]:
    coords = [(float(x), float(y)) for x, y in line.coords]
    start, end = coords[0], coords[-1]
    chord = math.dist(start, end)
    path = float(line.length)
    excess = path - chord
    stretch = path / max(chord, EPS)
    min_x, min_y, max_x, max_y = line.bounds
    return {
        "point_count": len(coords),
        "length_world_px": round(path, 6),
        "chord_world_px": round(chord, 6),
        "stretch": round(stretch, 6),
        "excess_world_px": round(excess, 6),
        "max_chord_deviation_world_px": round(max_deviation(coords), 6),
        "bbox": [round(float(v), 6) for v in (min_x, min_y, max_x, max_y)],
        "start": [round(start[0], 6), round(start[1], 6)],
        "end": [round(end[0], 6), round(end[1], 6)],
        "strongest_thin_subpath": strongest_subpath(coords),
        "coordinates": [[round(x, 6), round(y, 6)] for x, y in coords],
    }


def main() -> None:
    document = json.loads(CELLS_PATH.read_text(encoding="utf-8"))
    parent = next(
        (province for province in document.get("provinces", [])
         if isinstance(province, dict) and str(province.get("id", "")) == PARENT_ID),
        None,
    )
    if parent is None:
        raise RuntimeError(f"generated parent not found: {PARENT_ID}")
    cells = [cell for cell in parent.get("cells", []) if isinstance(cell, dict)]
    if len(cells) != 3:
        raise RuntimeError(f"expected exactly 3 Lancashire/Manchester cells, got {len(cells)}")

    geoms = {str(cell["id"]): cell_geometry(cell) for cell in cells}
    if any(g.is_empty for g in geoms.values()):
        raise RuntimeError("empty Lancashire/Manchester cell geometry")

    pair_rows: list[dict[str, Any]] = []
    ids = sorted(geoms)
    for index, left in enumerate(ids):
        for right in ids[index + 1:]:
            shared = geoms[left].boundary.intersection(geoms[right].boundary)
            raw_components = line_parts(shared)
            components = merged_line_parts(shared)
            pair_rows.append({
                "left": left,
                "right": right,
                "shared_length_world_px": round(float(shared.length), 6),
                "raw_component_count": len(raw_components),
                "merged_component_count": len(components),
                "components": [component_metrics(line) for line in components],
            })

    cell_rows = []
    for cell in sorted(cells, key=lambda item: str(item["id"])):
        geom = geoms[str(cell["id"])]
        cell_rows.append({
            "id": str(cell["id"]),
            "area_km2": cell.get("area_km2"),
            "bbox": [round(float(v), 6) for v in geom.bounds],
            "neighbor_cell_ids": cell.get("neighbor_cell_ids", []),
            "boundary_length_world_px": round(float(geom.boundary.length), 6),
        })

    report = {
        "format": "britain_lancashire_cell_boundary_diagnostic/v2",
        "parent_id": PARENT_ID,
        "cell_count": len(cells),
        "cells": cell_rows,
        "pairs": pair_rows,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("LANCASHIRE_CELL_BOUNDARY_DIAGNOSTIC=" + json.dumps(report, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
