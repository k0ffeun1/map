#!/usr/bin/env python3
"""Diagnose suspicious internal cell boundaries in Lancashire/Manchester.

This inspects the generated Stage-6 cells that the Godot viewer actually draws.
Shared boundary fragments are line-merged before measuring so a visually single
hairpin cannot hide as dozens of two-point GEOS intersection segments.

V3 follows the individual cell rings across tiny gaps between merged shared
components. V4 also classifies those detour arcs against the authoritative
macro-province boundary, so an internal-cell defect cannot be confused with a
narrow parent-boundary indentation.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, substring, unary_union

ROOT = Path(__file__).resolve().parents[2]
CELLS_PATH = ROOT / "assets" / "subdivision_stage6" / "britain_north_atlantic_subdivisions.json"
MACRO_PATH = ROOT / "assets" / "game_data" / "britain_north_atlantic_gameplay_provinces.json"
REPORT_PATH = ROOT / "reports" / "britain_lancashire_cell_boundary_diagnostic.json"
PARENT_ID = "gb_england_lancashire_manchester"
EPS = 1.0e-8
GAP_LINK_LIMIT_WORLD_PX = 0.75
RING_MATCH_TOLERANCE_WORLD_PX = 1.0e-5
PARENT_BOUNDARY_BUFFER_WORLD_PX = 1.0e-5


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


def parts_geometry(parts_payload: Any) -> Any:
    parts: list[Any] = []
    for part in parts_payload if isinstance(parts_payload, list) else []:
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


def cell_geometry(cell: dict[str, Any]) -> Any:
    return parts_geometry(cell.get("parts", []))


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
    min_x, min_y, max_x, max_y = line.bounds
    return {
        "point_count": len(coords),
        "length_world_px": round(path, 6),
        "chord_world_px": round(chord, 6),
        "stretch": round(path / max(chord, EPS), 6),
        "excess_world_px": round(path - chord, 6),
        "max_chord_deviation_world_px": round(max_deviation(coords), 6),
        "bbox": [round(float(v), 6) for v in (min_x, min_y, max_x, max_y)],
        "start": [round(start[0], 6), round(start[1], 6)],
        "end": [round(end[0], 6), round(end[1], 6)],
        "strongest_thin_subpath": strongest_subpath(coords),
        "coordinates": [[round(x, 6), round(y, 6)] for x, y in coords],
    }


def endpoint_options(line: LineString) -> list[tuple[float, float]]:
    coords = list(line.coords)
    return [(float(coords[0][0]), float(coords[0][1])), (float(coords[-1][0]), float(coords[-1][1]))]


def component_gap_candidates(components: list[LineString]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for first in range(len(components)):
        for second in range(first + 1, len(components)):
            best: tuple[float, tuple[float, float], tuple[float, float]] | None = None
            for left in endpoint_options(components[first]):
                for right in endpoint_options(components[second]):
                    distance = math.dist(left, right)
                    if best is None or distance < best[0]:
                        best = (distance, left, right)
            if best is None or best[0] > GAP_LINK_LIMIT_WORLD_PX:
                continue
            rows.append({
                "component_a": first,
                "component_b": second,
                "gap_world_px": round(best[0], 9),
                "a_endpoint": [round(best[1][0], 9), round(best[1][1], 9)],
                "b_endpoint": [round(best[2][0], 9), round(best[2][1], 9)],
                "_a": best[1],
                "_b": best[2],
            })
    rows.sort(key=lambda row: row["gap_world_px"])
    return rows


def geometry_rings(geometry: Any) -> list[tuple[str, LineString]]:
    result: list[tuple[str, LineString]] = []
    for part_index, polygon in enumerate(polygon_parts(geometry)):
        result.append((f"part:{part_index}:exterior", LineString(list(polygon.exterior.coords))))
        for hole_index, ring in enumerate(polygon.interiors):
            result.append((f"part:{part_index}:hole:{hole_index}", LineString(list(ring.coords))))
    return result


def concatenate_coords(first: list[tuple[float, float]], second: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not first:
        return second
    if not second:
        return first
    if math.dist(first[-1], second[0]) <= RING_MATCH_TOLERANCE_WORLD_PX:
        return first + second[1:]
    return first + second


def parent_boundary_share(line: LineString, parent_boundary: Any) -> dict[str, Any]:
    if line.is_empty or line.length <= EPS or parent_boundary is None or parent_boundary.is_empty:
        return {"length_world_px": 0.0, "share": 0.0, "max_distance_world_px": None}
    buffered = parent_boundary.buffer(PARENT_BOUNDARY_BUFFER_WORLD_PX)
    on_parent = line.intersection(buffered)
    sample_count = max(3, min(33, int(math.ceil(line.length / 0.1)) + 1))
    max_distance = 0.0
    for index in range(sample_count):
        point = line.interpolate(line.length * index / max(1, sample_count - 1))
        max_distance = max(max_distance, float(parent_boundary.distance(point)))
    length = float(on_parent.length)
    return {
        "length_world_px": round(length, 9),
        "share": round(min(1.0, length / max(float(line.length), EPS)), 6),
        "max_distance_world_px": round(max_distance, 9),
    }


def arc_payload(line: LineString, parent_boundary: Any) -> dict[str, Any]:
    coords = [(float(x), float(y)) for x, y in line.coords]
    if len(coords) < 2:
        return {"point_count": len(coords), "length_world_px": 0.0, "coordinates": []}
    start, end = coords[0], coords[-1]
    chord = math.dist(start, end)
    path = float(line.length)
    return {
        "point_count": len(coords),
        "length_world_px": round(path, 9),
        "chord_world_px": round(chord, 9),
        "stretch": round(path / max(chord, EPS), 6),
        "excess_world_px": round(path - chord, 9),
        "max_chord_deviation_world_px": round(max_deviation(coords), 9),
        "parent_boundary": parent_boundary_share(line, parent_boundary),
        "strongest_thin_subpath": strongest_subpath(coords),
        "coordinates": [[round(x, 9), round(y, 9)] for x, y in coords],
    }


def ring_arcs_between(geometry: Any, first: tuple[float, float], second: tuple[float, float], parent_boundary: Any) -> dict[str, Any] | None:
    p1 = Point(first)
    p2 = Point(second)
    best: tuple[float, str, LineString] | None = None
    for ring_id, ring in geometry_rings(geometry):
        distance_score = float(ring.distance(p1) + ring.distance(p2))
        if best is None or distance_score < best[0]:
            best = (distance_score, ring_id, ring)
    if best is None or best[0] > RING_MATCH_TOLERANCE_WORLD_PX * 2.0:
        return None

    _score, ring_id, ring = best
    total = float(ring.length)
    d1 = float(ring.project(p1))
    d2 = float(ring.project(p2))
    low, high = sorted((d1, d2))
    direct_geom = substring(ring, low, high)
    direct_lines = line_parts(direct_geom)
    direct = direct_lines[0] if direct_lines else LineString()

    tail_geom = substring(ring, high, total)
    head_geom = substring(ring, 0.0, low)
    tail_lines = line_parts(tail_geom)
    head_lines = line_parts(head_geom)
    tail_coords = [(float(x), float(y)) for x, y in tail_lines[0].coords] if tail_lines else []
    head_coords = [(float(x), float(y)) for x, y in head_lines[0].coords] if head_lines else []
    wrap_coords = concatenate_coords(tail_coords, head_coords)
    wrap = LineString(wrap_coords) if len(wrap_coords) >= 2 else LineString()

    arcs = [arc_payload(direct, parent_boundary), arc_payload(wrap, parent_boundary)]
    arcs.sort(key=lambda item: item.get("length_world_px", 0.0))
    return {
        "ring_id": ring_id,
        "ring_length_world_px": round(total, 9),
        "endpoint_ring_distance_sum_world_px": round(best[0], 12),
        "shorter_arc": arcs[0],
        "longer_arc": arcs[1],
    }


def gap_ring_diagnostics(components: list[LineString], left_geometry: Any, right_geometry: Any, parent_boundary: Any) -> list[dict[str, Any]]:
    rows = component_gap_candidates(components)
    result: list[dict[str, Any]] = []
    for row in rows:
        first = row.pop("_a")
        second = row.pop("_b")
        left_arc = ring_arcs_between(left_geometry, first, second, parent_boundary)
        right_arc = ring_arcs_between(right_geometry, first, second, parent_boundary)
        gap = float(row["gap_world_px"])
        row["left_cell_ring_arcs"] = left_arc
        row["right_cell_ring_arcs"] = right_arc
        short_lengths = []
        parent_shares = []
        for arcs in (left_arc, right_arc):
            if arcs:
                short = arcs["shorter_arc"]
                short_lengths.append(float(short.get("length_world_px", 0.0)))
                parent_shares.append(float(short.get("parent_boundary", {}).get("share", 0.0)))
        row["max_shorter_arc_to_gap_ratio"] = round(max(short_lengths, default=0.0) / max(gap, EPS), 6)
        row["shorter_arcs_parent_boundary_share"] = [round(value, 6) for value in parent_shares]
        result.append(row)
    return result


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

    macro_document = json.loads(MACRO_PATH.read_text(encoding="utf-8"))
    macro_parent = next(
        (province for province in macro_document.get("provinces", [])
         if isinstance(province, dict) and str(province.get("id", "")) == PARENT_ID),
        None,
    )
    if macro_parent is None:
        raise RuntimeError(f"macro parent not found: {PARENT_ID}")
    parent_geometry = parts_geometry(macro_parent.get("parts", []))
    if parent_geometry.is_empty:
        raise RuntimeError("empty Lancashire/Manchester macro geometry")
    parent_boundary = parent_geometry.boundary

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
                "component_gaps": gap_ring_diagnostics(components, geoms[left], geoms[right], parent_boundary),
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
        "format": "britain_lancashire_cell_boundary_diagnostic/v4",
        "parent_id": PARENT_ID,
        "parent_boundary_length_world_px": round(float(parent_boundary.length), 9),
        "cell_count": len(cells),
        "cells": cell_rows,
        "pairs": pair_rows,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("LANCASHIRE_CELL_BOUNDARY_DIAGNOSTIC=" + json.dumps(report, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
