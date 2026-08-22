#!/usr/bin/env python3
"""Diagnose suspicious internal cell boundaries in Lancashire/Manchester.

This is intentionally narrow: it inspects the *generated Stage-6 cells* that the
Godot Britain/North-Atlantic viewer actually draws, rather than macro province or
coast geometry.  The report makes every shared component auditable by cell pair.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

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


def max_deviation(coords: list[tuple[float, float]]) -> float:
    if len(coords) < 3:
        return 0.0
    chord = LineString([coords[0], coords[-1]])
    return max(chord.distance(__import__("shapely").geometry.Point(p)) for p in coords[1:-1])


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
        "coordinates": [[round(x, 6), round(y, 6)] for x, y in coords],
    }


def main() -> None:
    document = json.loads(CELLS_PATH.read_text(encoding="utf-8"))
    cells = [
        cell for cell in document.get("cells", [])
        if isinstance(cell, dict) and str(cell.get("gameplay_province_id", "")) == PARENT_ID
    ]
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
            components = sorted(line_parts(shared), key=lambda line: -line.length)
            row = {
                "left": left,
                "right": right,
                "shared_length_world_px": round(float(shared.length), 6),
                "component_count": len(components),
                "components": [component_metrics(line) for line in components],
            }
            pair_rows.append(row)

    # A hairpin can also appear on a single exterior ring as two near-parallel
    # portions. Include every cell's bbox/area so the final fix can be matched to
    # the screenshot and regression-checked without relying on colour again.
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
        "format": "britain_lancashire_cell_boundary_diagnostic/v1",
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
