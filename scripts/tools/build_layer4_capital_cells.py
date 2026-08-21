#!/usr/bin/env python3
"""Sequential province cell generation anchored at real provincial capitals."""
from __future__ import annotations

import heapq
import json
from collections import deque
from pathlib import Path
from typing import Any

from shapely.geometry import Point

import build_lacoruna_growth_cells as core


ROOT = Path(__file__).resolve().parents[2]
PROVINCES = ROOT / "assets" / "provinces_iberia.json"
CITIES = ROOT / "assets" / "province_cities_iberia.json"
OUTPUT = ROOT / "assets" / "cells_layer4_capital_sequential.json"
REPORT = ROOT / "assets" / "cell_topology" / "layer4_capital_validation.json"
GRID_STEP = 0.60
FINAL_CELL_COUNT = 4
NOISE_SCALE = 4.5
NOISE_STRENGTH = 0.38


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def city_by_province() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for city in read_json(CITIES).get("cities", []):
        result.setdefault(str(city.get("province", "")), city)
    return result


def neighbours(index_by_grid: dict[tuple[int, int], int]) -> tuple[dict[int, list[int]], dict[int, tuple[int, int]]]:
    reverse = {index: key for key, index in index_by_grid.items()}
    adjacency: dict[int, list[int]] = {index: [] for index in reverse}
    for index, (ix, iy) in reverse.items():
        for dx, dy in (
            (-1, 0), (1, 0), (0, -1), (0, 1),
            (-1, -1), (1, -1), (-1, 1), (1, 1),
        ):
            other = index_by_grid.get((ix + dx, iy + dy))
            if other is not None:
                adjacency[index].append(other)
    return adjacency, reverse


def connected(mask: set[int], adjacency: dict[int, list[int]]) -> bool:
    if not mask:
        return True
    start = next(iter(mask))
    seen = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for other in adjacency[current]:
            if other in mask and other not in seen:
                seen.add(other)
                queue.append(other)
    return len(seen) == len(mask)


def deepest_seed(mask: set[int], adjacency: dict[int, list[int]]) -> int:
    distance: dict[int, int] = {}
    queue: deque[int] = deque()
    for index in mask:
        if any(other not in mask for other in adjacency[index]) or len(adjacency[index]) < 8:
            distance[index] = 1
            queue.append(index)
    if not queue:
        return next(iter(mask))
    while queue:
        current = queue.popleft()
        for other in adjacency[current]:
            if other in mask and other not in distance:
                distance[other] = distance[current] + 1
                queue.append(other)
    return max(mask, key=lambda index: distance.get(index, 0))


def grow_candidate(
    seed: int,
    available: set[int],
    target: int,
    cells: list[tuple[float, float]],
    adjacency: dict[int, list[int]],
    salt: int,
) -> set[int]:
    owned: set[int] = set()
    costs = {seed: 0.0}
    queue: list[tuple[float, int]] = [(0.0, seed)]
    while queue and len(owned) < target:
        cost, current = heapq.heappop(queue)
        if current in owned or current not in available or cost != costs.get(current):
            continue
        owned.add(current)
        for other in adjacency[current]:
            if other not in available or other in owned:
                continue
            x, y = cells[other]
            cx, cy = cells[current]
            step = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / GRID_STEP
            coarse = core.value_noise(x, y, NOISE_SCALE, salt)
            medium = core.value_noise(x, y, NOISE_SCALE * 0.55, salt + 97) * 0.35
            terrain_cost = max(0.35, 1.0 + (coarse + medium) * NOISE_STRENGTH)
            next_cost = cost + step * terrain_cost
            if next_cost < costs.get(other, float("inf")):
                costs[other] = next_cost
                heapq.heappush(queue, (next_cost, other))
    return owned


def sequential_owners(
    cells: list[tuple[float, float]],
    index_by_grid: dict[tuple[int, int], int],
    capital: Point,
    count: int,
) -> tuple[list[int], int]:
    adjacency, _reverse = neighbours(index_by_grid)
    available = set(range(len(cells)))
    owners = [-1] * len(cells)
    capital_index = min(available, key=lambda index: Point(cells[index]).distance(capital))
    for cell_id in range(count - 1):
        remaining_cells = count - cell_id
        target = max(1, round(len(available) / remaining_cells))
        seed = capital_index if cell_id == 0 else deepest_seed(available, adjacency)
        candidates: list[tuple[float, set[int]]] = []
        for variant, ratio in enumerate((0.88, 1.0, 1.12)):
            candidate = grow_candidate(
                seed,
                available,
                max(1, min(len(available) - (remaining_cells - 1), round(target * ratio))),
                cells,
                adjacency,
                101 + cell_id * 17 + variant * 43,
            )
            remainder = available - candidate
            if not remainder or not connected(remainder, adjacency):
                continue
            area_error = abs(len(candidate) - target) / max(1, target)
            perimeter = sum(1 for index in candidate for other in adjacency[index] if other not in candidate)
            compactness_penalty = perimeter / max(1.0, len(candidate) ** 0.5)
            candidates.append((area_error * 4.0 + compactness_penalty * 0.08, candidate))
        if not candidates:
            candidate = grow_candidate(seed, available, target, cells, adjacency, 101 + cell_id * 17)
        else:
            candidate = min(candidates, key=lambda item: item[0])[1]
        for index in candidate:
            owners[index] = cell_id
        available -= candidate
    for index in available:
        owners[index] = count - 1
    return owners, capital_index


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    source = read_json(PROVINCES)
    capitals = city_by_province()
    core.GRID_STEP = GRID_STEP
    output_cells: list[dict[str, Any]] = []
    warnings: list[str] = []
    capital_cells = 0

    for province in source.get("cells", []):
        province_id = str(province.get("id", ""))
        province_name = str(province.get("name", province_id))
        polygon = core.as_polygon(province)
        cells, index_by_grid, _origin = core.grid_mask(polygon)
        if not cells:
            warnings.append(f"{province_id}: empty raster")
            continue
        count = min(FINAL_CELL_COUNT, len(cells))
        city = capitals.get(province_name)
        if city and len(city.get("pos", [])) >= 2:
            raw_position = Point(float(city["pos"][0]), float(city["pos"][1]))
            capital_name = str(city.get("name", province_name))
        else:
            raw_position = polygon.representative_point()
            capital_name = province_name
            warnings.append(f"{province_id}: capital fallback")
        capital = raw_position if polygon.covers(raw_position) else polygon.exterior.interpolate(
            polygon.exterior.project(raw_position)
        )
        owners, capital_index = sequential_owners(cells, index_by_grid, capital, count)
        core.SEEDS = [
            (f"capital-growth:{province_id}:{index + 1:02d}", f"{province_name} {index + 1}", cells[capital_index])
            for index in range(count)
        ]
        polygons = core.region_polygons(polygon, cells, owners)
        borders, neighbour_map = core.grid_shared_borders(index_by_grid, owners)
        for index, cell_polygon in enumerate(polygons):
            cell_id, cell_name, _seed = core.SEEDS[index]
            label = cell_polygon.representative_point()
            is_capital = index == 0
            if is_capital:
                capital_cells += 1
            output_cells.append({
                "id": cell_id,
                "name": cell_name,
                "parent_province_id": province_id,
                "parent_province_name": province_name,
                "profile_id": "P5-capital-sequential",
                "cell_order": index,
                "is_capital_candidate": is_capital,
                "real_capital_anchor": {
                    "name": capital_name,
                    "pos": [round(raw_position.x, 4), round(raw_position.y, 4)],
                    "snapped_pos": [round(cells[capital_index][0], 4), round(cells[capital_index][1], 4)],
                } if is_capital else {},
                "area_km2": round(cell_polygon.area * core.km_per_world_px(label.y) ** 2, 2),
                "rings": core.rings_from_polygon(cell_polygon),
                "bbox": [round(value, 4) for value in cell_polygon.bounds],
                "center": [round(cell_polygon.centroid.x, 4), round(cell_polygon.centroid.y, 4)],
                "label_point": [round(label.x, 4), round(label.y, 4)],
                "brd_open": borders[index],
                "neighbours": neighbour_map[cell_id],
                "color": [0.42, 0.82, 0.95, 0.0],
            })

    payload = {
        "world_px": float(source.get("world_px", core.WORLD_PX)),
        "cells": output_cells,
        "provenance": {
            "method": "capital_anchored_sequential_region_growth_v1",
            "source": "assets/provinces_iberia.json",
            "capital_source": "assets/province_cities_iberia.json",
            "final_cell_count": FINAL_CELL_COUNT,
            "grid_step_px": GRID_STEP,
            "noise_scale_px": NOISE_SCALE,
            "noise_strength": NOISE_STRENGTH,
        },
    }
    report = {
        "ok": not warnings,
        "source_provinces": len(source.get("cells", [])),
        "generated_cells": len(output_cells),
        "capital_cells": capital_cells,
        "warnings": warnings,
    }
    return payload, report


def main() -> None:
    payload, report = build()
    write_json(OUTPUT, payload)
    write_json(REPORT, report)
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {len(payload['cells'])} cells, capitals={report['capital_cells']}")
    if report["warnings"]:
        print(f"warnings: {len(report['warnings'])}")


if __name__ == "__main__":
    main()
