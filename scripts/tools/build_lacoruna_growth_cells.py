#!/usr/bin/env python3
"""Build La Coruna cells by noisy region growth inside the playable mask.

This is a separate experiment from the topology graph layer.  The province
polygon is treated as a mask; four seed points grow through a raster grid with
a deterministic coarse noise field added to movement cost.  The result is
closer to "painted administrative regions" than to Voronoi or hand-drawn graph
edges.
"""
from __future__ import annotations

import heapq
import argparse
import json
import math
from pathlib import Path
from typing import Any

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon, box
from shapely.ops import linemerge, nearest_points, unary_union

ROOT = Path(__file__).resolve().parents[2]
PROVINCES = ROOT / "assets" / "map_geometry" / "provinces.json"
WORLD_OCEAN = ROOT / "assets" / "world_ocean.json"
OUT = ROOT / "assets" / "cells_lacoruna_growth.json"
REPORT = ROOT / "assets" / "cell_topology" / "lacoruna_growth_validation.json"

PROVINCE_ID = "province:2848"
WORLD_PX = 8192.0
EARTH_RADIUS_KM = 6371.0
COAST_OFFSET_KM = 2.0
GRID_STEP = 0.18
NOISE_SCALE = 3.2
NOISE_STRENGTH = 0.85
MIN_PART_AREA_PX2 = 0.05
CONTOUR_SIMPLIFY_PX = 0.14

SEEDS = [
    ("growth:2848:01", "northwest", (3894.4, 3007.3)),
    ("growth:2848:02", "northeast", (3910.9, 3000.6)),
    ("growth:2848:03", "southwest", (3895.8, 3017.0)),
    ("growth:2848:04", "southeast", (3907.6, 3012.3)),
]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def unproject_lat(y: float) -> float:
    n = math.pi - 2.0 * math.pi * y / WORLD_PX
    return math.degrees(math.atan(math.sinh(n)))


def km_per_world_px(y: float) -> float:
    return (2.0 * math.pi * EARTH_RADIUS_KM / WORLD_PX) * math.cos(math.radians(unproject_lat(y)))


def polygon_parts(geometry: Any) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [] if geometry.is_empty else [geometry]
    if isinstance(geometry, MultiPolygon):
        return [part for part in geometry.geoms if not part.is_empty]
    if isinstance(geometry, GeometryCollection):
        return [part for part in geometry.geoms if isinstance(part, Polygon) and not part.is_empty]
    return []


def line_parts(geometry: Any) -> list[LineString]:
    if isinstance(geometry, LineString):
        return [] if geometry.is_empty else [geometry]
    if isinstance(geometry, MultiLineString):
        return [part for part in geometry.geoms if not part.is_empty]
    if isinstance(geometry, GeometryCollection):
        return [part for part in geometry.geoms if isinstance(part, LineString) and not part.is_empty]
    return []


def as_polygon(entry: dict[str, Any]) -> Polygon:
    rings = entry.get("rings", [])
    polygon = Polygon(rings[0], rings[1:])
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if isinstance(polygon, MultiPolygon):
        polygon = max(polygon.geoms, key=lambda item: item.area)
    return polygon


def load_province() -> tuple[dict[str, Any], Polygon]:
    entry = next(item for item in load_json(PROVINCES)["provinces"] if item.get("id") == PROVINCE_ID)
    return entry, as_polygon(entry)


def load_world_ocean() -> list[Polygon]:
    out: list[Polygon] = []
    for cell in load_json(WORLD_OCEAN).get("cells", []):
        rings = cell.get("rings", [])
        if not rings:
            continue
        poly = Polygon(rings[0], rings[1:])
        if not poly.is_valid:
            poly = poly.buffer(0)
        out.extend(polygon_parts(poly))
    return out


def playable_polygon(province: Polygon) -> tuple[Polygon, float]:
    margin_px = COAST_OFFSET_KM / max(km_per_world_px(province.representative_point().y), 0.001)
    clip = box(*province.bounds).buffer(margin_px + 3.0)
    ocean_parts = []
    for ocean in load_world_ocean():
        if ocean.intersects(clip):
            part = ocean.intersection(clip)
            if not part.is_empty:
                ocean_parts.append(part)
    ocean_margin = unary_union(ocean_parts).buffer(margin_px, quad_segs=8)
    playable = province.difference(ocean_margin)
    if not playable.is_valid:
        playable = playable.buffer(0)
    parts = polygon_parts(playable)
    if not parts:
        raise ValueError("coast offset removed the province")
    return max(parts, key=lambda item: item.area), margin_px


def hash01(ix: int, iy: int, salt: int) -> float:
    value = (ix * 374761393 + iy * 668265263 + salt * 1442695041) & 0xFFFFFFFF
    value = (value ^ (value >> 13)) * 1274126177 & 0xFFFFFFFF
    value ^= value >> 16
    return value / 0xFFFFFFFF


def smoothstep(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def value_noise(x: float, y: float, scale: float, salt: int) -> float:
    gx = x / scale
    gy = y / scale
    x0 = math.floor(gx)
    y0 = math.floor(gy)
    tx = smoothstep(gx - x0)
    ty = smoothstep(gy - y0)
    a = hash01(x0, y0, salt)
    b = hash01(x0 + 1, y0, salt)
    c = hash01(x0, y0 + 1, salt)
    d = hash01(x0 + 1, y0 + 1, salt)
    ab = a + (b - a) * tx
    cd = c + (d - c) * tx
    return (ab + (cd - ab) * ty) * 2.0 - 1.0


def terrain_cost(x: float, y: float) -> float:
    coarse = value_noise(x, y, NOISE_SCALE, 17)
    mid = value_noise(x, y, NOISE_SCALE * 0.48, 41) * 0.45
    noise = max(-1.0, min(1.0, coarse + mid))
    return max(0.18, 1.0 + noise * NOISE_STRENGTH)


def grid_mask(playable: Polygon) -> tuple[list[tuple[float, float]], dict[tuple[int, int], int], tuple[int, int]]:
    x0, y0, x1, y1 = playable.bounds
    ix0 = math.floor(x0 / GRID_STEP) - 1
    iy0 = math.floor(y0 / GRID_STEP) - 1
    ix1 = math.ceil(x1 / GRID_STEP) + 1
    iy1 = math.ceil(y1 / GRID_STEP) + 1
    cells: list[tuple[float, float]] = []
    index_by_grid: dict[tuple[int, int], int] = {}
    for iy in range(iy0, iy1 + 1):
        y = (iy + 0.5) * GRID_STEP
        for ix in range(ix0, ix1 + 1):
            x = (ix + 0.5) * GRID_STEP
            if playable.covers(Point(x, y)):
                index_by_grid[(ix, iy)] = len(cells)
                cells.append((x, y))
    return cells, index_by_grid, (ix0, iy0)


def nearest_grid_index(point: Point, cells: list[tuple[float, float]]) -> int:
    return min(range(len(cells)), key=lambda index: Point(cells[index]).distance(point))


def grow_regions(playable: Polygon, cells: list[tuple[float, float]], index_by_grid: dict[tuple[int, int], int]) -> list[int]:
    owner = [-1] * len(cells)
    costs = [float("inf")] * len(cells)
    queue: list[tuple[float, int, int]] = []
    for seed_index, (_, _, raw_seed) in enumerate(SEEDS):
        seed_point = Point(raw_seed)
        if not playable.covers(seed_point):
            seed_point = nearest_points(seed_point, playable)[1]
        cell_index = nearest_grid_index(seed_point, cells)
        owner[cell_index] = seed_index
        costs[cell_index] = 0.0
        heapq.heappush(queue, (0.0, seed_index, cell_index))

    offsets = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)]
    reverse_index = {index: key for key, index in index_by_grid.items()}
    while queue:
        cost, seed_index, cell_index = heapq.heappop(queue)
        if cost != costs[cell_index] or owner[cell_index] != seed_index:
            continue
        ix, iy = reverse_index[cell_index]
        x, y = cells[cell_index]
        for dx, dy in offsets:
            neighbor_key = (ix + dx, iy + dy)
            neighbor = index_by_grid.get(neighbor_key)
            if neighbor is None:
                continue
            nx, ny = cells[neighbor]
            step = math.hypot(nx - x, ny - y)
            next_cost = cost + step * terrain_cost(nx, ny)
            if next_cost < costs[neighbor]:
                costs[neighbor] = next_cost
                owner[neighbor] = seed_index
                heapq.heappush(queue, (next_cost, seed_index, neighbor))
    return owner


def region_polygons(
    playable: Polygon,
    cells: list[tuple[float, float]],
    owners: list[int],
) -> list[Polygon]:
    out: list[Polygon] = []
    # Floating-point grid coordinates can leave microscopic gaps between
    # nominally adjacent raster squares.  The overlap is far below the grid
    # resolution and is clipped to the playable mask; it preserves topology.
    half = GRID_STEP * 0.5 + 1e-6
    for seed_index in range(len(SEEDS)):
        boxes = [
            box(x - half, y - half, x + half, y + half)
            for (x, y), owner in zip(cells, owners)
            if owner == seed_index
        ]
        merged = unary_union(boxes).intersection(playable)
        if not merged.is_valid:
            merged = merged.buffer(0)
        parts = [part for part in polygon_parts(merged) if part.area >= MIN_PART_AREA_PX2]
        if not parts:
            raise ValueError(f"seed {seed_index} produced no polygon")
        out.append(max(parts, key=lambda item: item.area))
    return out


def rings_from_polygon(poly: Polygon) -> list[list[list[float]]]:
    def pts(coords: Any) -> list[list[float]]:
        return [[round(float(x), 6), round(float(y), 6)] for x, y in coords]
    return [pts(poly.exterior.coords)] + [pts(ring.coords) for ring in poly.interiors]


def line_coordinates(line: LineString) -> list[list[float]]:
    return [[round(float(x), 6), round(float(y), 6)] for x, y in line.coords]


def join_border_parts(parts: list[LineString]) -> list[LineString]:
    """Join raster fragments whose endpoints are within one grid cell."""
    remaining = [list(part.coords) for part in parts if len(part.coords) > 1]
    chains: list[list[tuple[float, float]]] = []
    # Polygon clipping can leave sub-cell gaps at diagonal raster joins.
    # Bridge those endpoints, while staying far below the scale of a province.
    tolerance = GRID_STEP * 20.0
    while remaining:
        chain = remaining.pop(0)
        changed = True
        while changed and remaining:
            changed = False
            best_index = -1
            best_mode = ""
            best_distance = tolerance
            start = Point(chain[0])
            end = Point(chain[-1])
            for index, candidate in enumerate(remaining):
                c_start = Point(candidate[0])
                c_end = Point(candidate[-1])
                options = [(end.distance(c_start), "append"), (end.distance(c_end), "append_reverse"),
                           (start.distance(c_end), "prepend"), (start.distance(c_start), "prepend_reverse")]
                distance, mode = min(options, key=lambda item: item[0])
                if distance < best_distance:
                    best_index, best_mode, best_distance = index, mode, distance
            if best_index < 0:
                continue
            candidate = remaining.pop(best_index)
            if best_mode == "append":
                chain.extend(candidate)
            elif best_mode == "append_reverse":
                chain.extend(reversed(candidate))
            elif best_mode == "prepend":
                chain = candidate + chain
            else:
                chain = list(reversed(candidate)) + chain
            changed = True
        chains.append(chain)
    return [LineString(chain) for chain in chains if len(chain) > 1]


def shared_borders(polys: list[Polygon]) -> tuple[list[list[list[list[float]]]], dict[str, list[str]]]:
    borders: list[list[list[list[float]]]] = [[] for _ in polys]
    neighbours: dict[str, list[str]] = {SEEDS[i][0]: [] for i in range(len(polys))}
    for left_index, left in enumerate(polys):
        for right_index in range(left_index + 1, len(polys)):
            shared = left.boundary.intersection(polys[right_index].boundary)
            # Coverage simplification keeps both sides of every shared edge
            # identical, so a normal line merge is sufficient here.
            raw_parts = [part for part in line_parts(shared) if part.length > GRID_STEP * 0.7]
            if len(raw_parts) > 1:
                merged = linemerge(unary_union(raw_parts))
                parts = line_parts(merged)
            else:
                parts = raw_parts
            parts = [
                part.simplify(CONTOUR_SIMPLIFY_PX, preserve_topology=False)
                for part in parts
                if part.length > GRID_STEP * 0.7
            ]
            if not parts:
                continue
            left_id = SEEDS[left_index][0]
            right_id = SEEDS[right_index][0]
            neighbours[left_id].append(right_id)
            neighbours[right_id].append(left_id)
            chains = [line_coordinates(part) for part in parts]
            borders[left_index].extend(chains)
            borders[right_index].extend(chains)
    return borders, {key: sorted(value) for key, value in neighbours.items()}


def grid_shared_borders(
    index_by_grid: dict[tuple[int, int], int],
    owners: list[int],
) -> tuple[list[list[list[list[float]]]], dict[str, list[str]]]:
    """Extract canonical internal borders directly from the province ID map."""
    segments_by_pair: dict[tuple[int, int], list[LineString]] = {}
    for (ix, iy), cell_index in index_by_grid.items():
        owner = owners[cell_index]
        for dx, dy in ((1, 0), (0, 1)):
            neighbour_index = index_by_grid.get((ix + dx, iy + dy))
            if neighbour_index is None:
                continue
            other = owners[neighbour_index]
            if owner == other:
                continue
            pair = tuple(sorted((owner, other)))
            if dx == 1:
                x = (ix + 1) * GRID_STEP
                segment = LineString(((x, iy * GRID_STEP), (x, (iy + 1) * GRID_STEP)))
            else:
                y = (iy + 1) * GRID_STEP
                segment = LineString(((ix * GRID_STEP, y), ((ix + 1) * GRID_STEP, y)))
            segments_by_pair.setdefault(pair, []).append(segment)

    borders: list[list[list[list[float]]]] = [[] for _ in SEEDS]
    neighbours: dict[str, list[str]] = {seed[0]: [] for seed in SEEDS}
    for (left_index, right_index), segments in sorted(segments_by_pair.items()):
        merged = segments[0] if len(segments) == 1 else linemerge(unary_union(segments))
        parts = [
            part.simplify(CONTOUR_SIMPLIFY_PX, preserve_topology=False)
            for part in line_parts(merged)
            if part.length > GRID_STEP * 0.7
        ]
        chains = [line_coordinates(part) for part in parts]
        borders[left_index].extend(chains)
        borders[right_index].extend(chains)
        left_id = SEEDS[left_index][0]
        right_id = SEEDS[right_index][0]
        neighbours[left_id].append(right_id)
        neighbours[right_id].append(left_id)
    return borders, {key: sorted(value) for key, value in neighbours.items()}


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    province_entry, province = load_province()
    playable, coast_offset_px = playable_polygon(province)
    cells, index_by_grid, _origin = grid_mask(playable)
    if len(cells) < len(SEEDS):
        raise ValueError("raster mask is too small")
    owners = grow_regions(playable, cells, index_by_grid)
    polys = region_polygons(playable, cells, owners)
    # Keep the raster ownership polygons untouched. Only the canonical shared
    # border chains are simplified in shared_borders(), once per neighbour pair.
    # This preserves selection/cell coverage and cannot split the two sides.
    borders, neighbours = grid_shared_borders(index_by_grid, owners)
    source_area_km2 = float(province_entry["area_km2"])

    out_cells = []
    for index, poly in enumerate(polys):
        cell_id, role, _seed = SEEDS[index]
        area = source_area_km2 * poly.area / province.area
        label = poly.representative_point()
        out_cells.append({
            "id": cell_id,
            "name": f"La Coruna growth {role}",
            "province_id": PROVINCE_ID,
            "profile_id": "P3-growth",
            "cell_role": role,
            "area_km2": round(area, 2),
            "target_area_km2": round(source_area_km2 / len(SEEDS), 2),
            "rings": rings_from_polygon(poly),
            "bbox": [round(value, 4) for value in poly.bounds],
            "center": [round(poly.centroid.x, 4), round(poly.centroid.y, 4)],
            "label_point": [round(label.x, 4), round(label.y, 4)],
            "brd_open": borders[index],
            "neighbours": neighbours[cell_id],
            "color": [0.42, 0.82, 0.95, 0.0],
        })

    payload = {
        "world_px": WORLD_PX,
        "cells": out_cells,
        "provenance": {
            "method": "noisy_region_growth_v1",
            "province_id": PROVINCE_ID,
            "grid_step_px": GRID_STEP,
            "noise_scale_px": NOISE_SCALE,
            "noise_strength": NOISE_STRENGTH,
            "coast_offset_km": COAST_OFFSET_KM,
            "coast_offset_px": round(coast_offset_px, 6),
        },
    }
    report = {
        "ok": True,
        "method": "noisy_region_growth_v1",
        "grid_cells": len(cells),
        "coast_offset_px": round(coast_offset_px, 6),
        "areas_km2": {cell["id"]: cell["area_km2"] for cell in out_cells},
        "neighbours": neighbours,
    }
    return payload, report


def main() -> None:
    global NOISE_SCALE, NOISE_STRENGTH
    parser = argparse.ArgumentParser()
    parser.add_argument("--noise-scale", type=float, default=NOISE_SCALE)
    parser.add_argument("--noise-strength", type=float, default=NOISE_STRENGTH)
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    NOISE_SCALE = max(0.5, args.noise_scale)
    NOISE_STRENGTH = max(0.0, args.noise_strength)
    payload, report = build()
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    write_json(output_path, payload)
    write_json(REPORT, report)
    print(f"wrote {output_path.relative_to(ROOT)}: {len(payload['cells'])} cells, raster={report['grid_cells']}")


if __name__ == "__main__":
    main()
