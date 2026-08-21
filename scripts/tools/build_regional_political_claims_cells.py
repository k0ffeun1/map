#!/usr/bin/env python3
"""Build the regional-table Political Claims layer for Iberia.

The regional table determines the target number of cells.  Geometry is built
offline by a capital-first, sequential *binary* claims process: every step
claims one connected part from the remaining raster, validates the remainder,
and keeps the best of 32 candidates.  It intentionally never performs an
N-way simultaneous growth.
"""
from __future__ import annotations

import heapq
import json
import math
import argparse
from collections import deque
from pathlib import Path
from typing import Any

from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point, Polygon, box
from shapely.ops import linemerge, nearest_points, polygonize, unary_union

import build_lacoruna_growth_cells as raster
import vector_boundary_partition as vector_partition


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "assets" / "provinces_iberia.json"
GEOMETRY = ROOT / "assets" / "map_geometry" / "provinces.json"
PROVINCE_DATA = ROOT / "assets" / "game_data" / "provinces.json"
PROFILES = ROOT / "assets" / "game_data" / "land_cell_generation_profiles.json"
OVERRIDES = ROOT / "assets" / "game_data" / "province_cell_generation_overrides.json"
CITIES = ROOT / "assets" / "province_cities_iberia.json"
WORLD_OCEAN = ROOT / "assets" / "world_ocean.json"
APPROVED_PARTITIONS = ROOT / "assets" / "cells_layer4_approved_partitions.json"
OUT = ROOT / "assets" / "cells_iberia_regional_political_claims.json"
REPORT = ROOT / "assets" / "cell_topology" / "iberia_regional_political_claims_validation.json"

# This resolution keeps the binary-claims candidate topology stable.  The
# exported shared borders, rather than a smaller grid, control visual smoothness.
GRID_STEP = 0.70
CANDIDATES_PER_SPLIT = 32
GENERATOR_VERSION = 3
MILESTONE_PROVINCE_ID = "province:2848"  # La Coruña: guide §65.
# Final vector borders use this tolerance to turn raster staircases into a
# handful of deliberate political bends. They are not curve-smoothed.
CONTOUR_SIMPLIFY = 0.28
BORDER_SMOOTHNESS = 0.0
MACRO_NOISE_STRENGTH = 0.50
MESO_NOISE_STRENGTH = 0.38
MICRO_NOISE_STRENGTH = 0.04
DIRECTION_STRENGTH = 0.16
TARGET_SPREAD = 0.36

# The regional table currently covers Iberia proper. Layer 4 also contains a
# narrow context rim. The guide explicitly allows P0-P8 defaults as fallback;
# keep that resolution visible in metadata instead of inventing fake regions.
COUNTRY_PROFILE_FALLBACK = {
    "france": "P3",
    "algeria": "P5",
    "morocco": "P4",
    "andorra": "P1",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def city_by_name() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for city in read_json(CITIES).get("cities", []):
        result.setdefault(str(city.get("province", "")), city)
    return result


def ocean_parts() -> list[Polygon]:
    parts: list[Polygon] = []
    for entry in read_json(WORLD_OCEAN).get("cells", []):
        rings = entry.get("rings", [])
        if not rings:
            continue
        geometry = Polygon(rings[0], rings[1:])
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        parts.extend(raster.polygon_parts(geometry))
    return parts


def is_coastal_province(province: Polygon, oceans: list[Polygon]) -> bool:
    """Return true only for a real sea coast, not the cropped layer-4 rim."""
    x0, y0, x1, y1 = province.bounds
    tolerance = GRID_STEP * 0.08
    for ocean in oceans:
        ox0, oy0, ox1, oy1 = ocean.bounds
        if ox1 < x0 - tolerance or ox0 > x1 + tolerance or oy1 < y0 - tolerance or oy0 > y1 + tolerance:
            continue
        if province.boundary.distance(ocean) <= tolerance:
            return True
    return False


def cover_grid_mask(province: Polygon) -> tuple[list[tuple[float, float]], dict[tuple[int, int], int]]:
    """Build a strict 4-connected cover from every square touching a province.

    Centre-only sampling left one-pixel islands in otherwise ordinary shapes
    (Navarra was the clearest case). The exact cover grid is 4-connected for
    every one of the 105 layer-4 polygons and is also the grid consumed by the
    final exact partition, so generation and export cannot disagree at coasts.
    """
    x0, y0, x1, y1 = province.bounds
    ix0 = math.floor(x0 / GRID_STEP) - 1
    iy0 = math.floor(y0 / GRID_STEP) - 1
    ix1 = math.ceil(x1 / GRID_STEP) + 1
    iy1 = math.ceil(y1 / GRID_STEP) + 1
    cells: list[tuple[float, float]] = []
    index_by_grid: dict[tuple[int, int], int] = {}
    for iy in range(iy0, iy1 + 1):
        for ix in range(ix0, ix1 + 1):
            square = box(ix * GRID_STEP, iy * GRID_STEP, (ix + 1) * GRID_STEP, (iy + 1) * GRID_STEP)
            clipped = square.intersection(province)
            if clipped.is_empty or clipped.area <= 1e-10:
                continue
            index_by_grid[(ix, iy)] = len(cells)
            cells.append(((ix + 0.5) * GRID_STEP, (iy + 0.5) * GRID_STEP))
    return cells, index_by_grid


def neighbours(index_by_grid: dict[tuple[int, int], int]) -> dict[int, list[int]]:
    result: dict[int, list[int]] = {index: [] for index in index_by_grid.values()}
    for (x, y), index in index_by_grid.items():
        # Four neighbours are deliberate: diagonal-only contact is not a
        # connected cell in the exported polygon topology.
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            other = index_by_grid.get((x + dx, y + dy))
            if other is not None:
                result[index].append(other)
    return result


def is_connected(indices: set[int], graph: dict[int, list[int]]) -> bool:
    if not indices:
        return False
    seen = {next(iter(indices))}
    queue: deque[int] = deque(seen)
    while queue:
        current = queue.popleft()
        for other in graph[current]:
            if other in indices and other not in seen:
                seen.add(other)
                queue.append(other)
    return len(seen) == len(indices)


def deepest_seed(indices: set[int], graph: dict[int, list[int]]) -> int:
    distance: dict[int, int] = {}
    queue: deque[int] = deque()
    for index in indices:
        if any(other not in indices for other in graph[index]) or len(graph[index]) < 4:
            distance[index] = 1
            queue.append(index)
    while queue:
        current = queue.popleft()
        for other in graph[current]:
            if other in indices and other not in distance:
                distance[other] = distance[current] + 1
                queue.append(other)
    return max(indices, key=lambda index: distance.get(index, 0))


def grow_binary_claim(
    seed: int,
    available: set[int],
    target: int,
    cells: list[tuple[float, float]],
    graph: dict[int, list[int]],
    salt: int,
) -> set[int]:
    """One side of one binary Political Claims split, grown as a cost field."""
    owned: set[int] = set()
    costs = {seed: 0.0}
    queue: list[tuple[float, int]] = [(0.0, seed)]
    while queue and len(owned) < target:
        cost, current = heapq.heappop(queue)
        if current in owned or current not in available or cost != costs.get(current):
            continue
        owned.add(current)
        for other in graph[current]:
            if other not in available or other in owned:
                continue
            x, y = cells[other]
            cx, cy = cells[current]
            step = math.hypot(x - cx, y - cy) / GRID_STEP
            macro = raster.value_noise(x, y, 4.8, salt)
            meso = raster.value_noise(x, y, 2.1, salt + 97) * 0.38
            micro = raster.value_noise(x, y, 0.72, salt + 211) * 0.10
            # A low-frequency directional bias makes claims feel political
            # rather than like evenly spaced Voronoi wedges.
            direction = math.sin((x * 0.31 + y * 0.17 + salt) * 0.65) * 0.16
            move_cost = max(0.30, 1.0 + macro * MACRO_NOISE_STRENGTH + meso * (MESO_NOISE_STRENGTH / 0.38) + micro * (MICRO_NOISE_STRENGTH / 0.10) + direction * (DIRECTION_STRENGTH / 0.16))
            next_cost = cost + step * move_cost
            if next_cost < costs.get(other, float("inf")):
                costs[other] = next_cost
                heapq.heappush(queue, (next_cost, other))
    return owned


def candidate_score(candidate: set[int], target: int, graph: dict[int, list[int]]) -> float:
    perimeter = sum(1 for index in candidate for other in graph[index] if other not in candidate)
    area_error = abs(len(candidate) - target) / max(1, target)
    compactness = perimeter / max(1.0, math.sqrt(len(candidate)))
    return area_error * 3.0 + compactness * 0.10


def _sequential_interior_claims(
    cells: list[tuple[float, float]],
    index_by_grid: dict[tuple[int, int], int],
    capital: Point,
    final_count: int,
    seed_base: int,
) -> tuple[list[int], int, list[dict[str, Any]]]:
    graph = neighbours(index_by_grid)
    available = set(range(len(cells)))
    owners = [-1] * len(cells)
    capital_index = min(available, key=lambda index: Point(cells[index]).distance(capital))
    decisions: list[dict[str, Any]] = []
    for order in range(final_count - 1):
        remaining_count = final_count - order
        target = max(1, round(len(available) / remaining_count))
        split_seed = capital_index if order == 0 else deepest_seed(available, graph)
        candidates: list[tuple[float, set[int], int]] = []
        for variant in range(CANDIDATES_PER_SPLIT):
            ratio = 1.0 - TARGET_SPREAD * 0.5 + TARGET_SPREAD * ((variant + 0.5) / CANDIDATES_PER_SPLIT)
            desired = max(1, min(len(available) - (remaining_count - 1), round(target * ratio)))
            salt = seed_base + order * 1009 + variant * 97
            candidate = grow_binary_claim(split_seed, available, desired, cells, graph, salt)
            remainder = available - candidate
            if not candidate or not is_connected(candidate, graph) or not is_connected(remainder, graph):
                continue
            candidates.append((candidate_score(candidate, target, graph), candidate, variant))
        if not candidates:
            raise ValueError("no valid binary Political Claims candidate")
        score, chosen, variant = min(candidates, key=lambda item: item[0])
        for index in chosen:
            owners[index] = order
        available -= chosen
        decisions.append({
            "split_id": f"split:{order + 1:02d}",
            "basis": ["capital_anchor" if order == 0 else "deepest_remaining_interior", "binary_claims", "shape_cost_field"],
            "candidate_count": CANDIDATES_PER_SPLIT,
            "selected_variant": variant,
            "score": round(score, 6),
            "target_raster_cells": target,
            "selected_raster_cells": len(chosen),
        })
    for index in available:
        owners[index] = final_count - 1
    return owners, capital_index, decisions


def boundary_seeds(
    available: set[int],
    graph: dict[int, list[int]],
    cells: list[tuple[float, float]],
    count: int,
) -> list[int]:
    """Choose deterministic, spatially separated lobe/edge seeds."""
    boundary = [
        index for index in available
        if sum(other in available for other in graph[index]) < 4
    ]
    if not boundary:
        boundary = sorted(available)
    first = min(boundary, key=lambda index: (cells[index][0], cells[index][1], index))
    chosen = [first]
    remaining = set(boundary) - {first}
    while remaining and len(chosen) < min(count, len(boundary)):
        next_seed = max(
            remaining,
            key=lambda index: (
                min(
                    (cells[index][0] - cells[other][0]) ** 2
                    + (cells[index][1] - cells[other][1]) ** 2
                    for other in chosen
                ),
                -index,
            ),
        )
        chosen.append(next_seed)
        remaining.remove(next_seed)
    return [chosen[index % len(chosen)] for index in range(count)]


def _sequential_boundary_claims(
    cells: list[tuple[float, float]],
    index_by_grid: dict[tuple[int, int], int],
    capital: Point,
    final_count: int,
    seed_base: int,
) -> tuple[list[int], int, list[dict[str, Any]]]:
    """Retry the same binary process with lobe-aware boundary seeds.

    A deepest-interior seed can plug a narrow province and make every later
    remainder invalid. Boundary seeds peel broad lobes and preserve a single
    capital-side remainder, which is also closer to real political divisions.
    """
    graph = neighbours(index_by_grid)
    available = set(range(len(cells)))
    owners = [-1] * len(cells)
    capital_index = min(available, key=lambda index: Point(cells[index]).distance(capital))
    decisions: list[dict[str, Any]] = []
    for order in range(final_count - 1):
        remaining_count = final_count - order
        target = max(1, round(len(available) / remaining_count))
        seeds = boundary_seeds(available, graph, cells, CANDIDATES_PER_SPLIT)
        candidates: list[tuple[float, set[int], int]] = []
        for variant, split_seed in enumerate(seeds):
            ratio_slot = variant % 8
            ratio = 1.0 - TARGET_SPREAD * 0.5 + TARGET_SPREAD * ((ratio_slot + 0.5) / 8.0)
            desired = max(1, min(len(available) - (remaining_count - 1), round(target * ratio)))
            salt = seed_base + 500_009 + order * 1009 + variant * 97
            candidate = grow_binary_claim(split_seed, available, desired, cells, graph, salt)
            remainder = available - candidate
            if order == 0 and capital_index not in candidate:
                continue
            if not candidate or not is_connected(candidate, graph) or not is_connected(remainder, graph):
                continue
            # Prefer a simple capital-side remainder so later binary splits do
            # not inherit a thin neck or a nearly enclosed hole.
            remainder_perimeter = sum(
                1 for index in remainder for other in graph[index] if other not in remainder
            )
            score = candidate_score(candidate, target, graph)
            score += 0.03 * remainder_perimeter / max(1.0, math.sqrt(len(remainder)))
            candidates.append((score, candidate, variant))
        if not candidates:
            raise ValueError("no valid boundary-seeded Political Claims candidate")
        score, chosen, variant = min(candidates, key=lambda item: item[0])
        for index in chosen:
            owners[index] = order
        available -= chosen
        decisions.append({
            "split_id": f"split:{order + 1:02d}",
            "basis": ["capital_anchor" if order == 0 else "boundary_lobe", "binary_claims", "shape_cost_field"],
            "strategy": "boundary_seed_retry",
            "candidate_count": CANDIDATES_PER_SPLIT,
            "selected_variant": variant,
            "score": round(score, 6),
            "target_raster_cells": target,
            "selected_raster_cells": len(chosen),
        })
    for index in available:
        owners[index] = final_count - 1
    return owners, capital_index, decisions


def _weighted_spanning_tree(
    available: set[int],
    root: int,
    cells: list[tuple[float, float]],
    graph: dict[int, list[int]],
    salt: int,
) -> tuple[dict[int, int | None], list[int]]:
    """Build one deterministic Political-Claims cost tree rooted at capital."""
    parent: dict[int, int | None] = {root: None}
    costs = {root: 0.0}
    queue: list[tuple[float, int]] = [(0.0, root)]
    order: list[int] = []
    settled: set[int] = set()
    while queue:
        cost, current = heapq.heappop(queue)
        if current in settled or current not in available or cost != costs.get(current):
            continue
        settled.add(current)
        order.append(current)
        for other in graph[current]:
            if other not in available or other in settled:
                continue
            x, y = cells[other]
            noise = raster.value_noise(x, y, 3.8, salt)
            move_cost = max(0.35, 1.0 + noise * 0.42)
            next_cost = cost + move_cost
            if next_cost < costs.get(other, float("inf")):
                costs[other] = next_cost
                parent[other] = current
                heapq.heappush(queue, (next_cost, other))
    if len(parent) != len(available):
        raise ValueError("working raster is disconnected")
    return parent, order


def _tree_subtree_candidate(
    parent: dict[int, int | None],
    order: list[int],
    root: int,
    target: int,
    maximum: int,
    graph: dict[int, list[int]],
) -> tuple[float, set[int]]:
    children: dict[int, list[int]] = {index: [] for index in parent}
    for index, ancestor in parent.items():
        if ancestor is not None:
            children[ancestor].append(index)
    sizes = {index: 1 for index in parent}
    for index in reversed(order):
        ancestor = parent[index]
        if ancestor is not None:
            sizes[ancestor] += sizes[index]
    possible = [index for index in parent if index != root and sizes[index] <= maximum]
    if not possible:
        raise ValueError("spanning tree has no detachable lobe")
    shortlist = sorted(possible, key=lambda index: (abs(sizes[index] - target), index))[:32]
    best: tuple[float, set[int]] | None = None
    for subtree_root in shortlist:
        candidate: set[int] = set()
        stack = [subtree_root]
        while stack:
            current = stack.pop()
            candidate.add(current)
            stack.extend(children[current])
        score = candidate_score(candidate, target, graph)
        if best is None or score < best[0]:
            best = (score, candidate)
    if best is None:
        raise ValueError("spanning tree produced no lobe candidate")
    return best


def _capital_protected_tree_claims(
    cells: list[tuple[float, float]],
    index_by_grid: dict[tuple[int, int], int],
    capital: Point,
    final_count: int,
    seed_base: int,
) -> tuple[list[int], int, list[dict[str, Any]]]:
    """Guaranteed connected fallback: peel tree sub-lobes, preserve capital.

    A descendant subtree and its complement are both connected in the same
    spanning tree. Rebuilding that tree after every peel therefore guarantees
    exactly N connected cells without an N-way star.
    """
    graph = neighbours(index_by_grid)
    available = set(range(len(cells)))
    capital_index = min(available, key=lambda index: Point(cells[index]).distance(capital))
    owners = [-1] * len(cells)
    decisions: list[dict[str, Any]] = []
    for peeled_order in range(1, final_count):
        remaining_cells = final_count - peeled_order + 1
        target = max(1, round(len(available) / remaining_cells))
        maximum = len(available) - (remaining_cells - 1)
        candidates: list[tuple[float, set[int], int]] = []
        for variant in range(CANDIDATES_PER_SPLIT):
            parent, tree_order = _weighted_spanning_tree(
                available, capital_index, cells, graph,
                seed_base + 900_001 + peeled_order * 1009 + variant * 97,
            )
            score, candidate = _tree_subtree_candidate(
                parent, tree_order, capital_index, target, maximum, graph,
            )
            candidates.append((score, candidate, variant))
        score, chosen, variant = min(candidates, key=lambda item: item[0])
        for index in chosen:
            owners[index] = peeled_order
        available -= chosen
        decisions.append({
            "split_id": f"split:{peeled_order:02d}",
            "basis": ["capital_protected_remainder", "spanning_tree_lobe", "binary_claims"],
            "strategy": "guaranteed_tree_fallback",
            "candidate_count": CANDIDATES_PER_SPLIT,
            "selected_variant": variant,
            "score": round(score, 6),
            "target_raster_cells": target,
            "selected_raster_cells": len(chosen),
        })
    for index in available:
        owners[index] = 0
    return owners, capital_index, decisions


def sequential_binary_claims(
    cells: list[tuple[float, float]],
    index_by_grid: dict[tuple[int, int], int],
    capital: Point,
    final_count: int,
    seed_base: int,
) -> tuple[list[int], int, list[dict[str, Any]]]:
    if final_count <= 1:
        capital_index = min(range(len(cells)), key=lambda index: Point(cells[index]).distance(capital))
        return [0] * len(cells), capital_index, []
    try:
        return _sequential_interior_claims(cells, index_by_grid, capital, final_count, seed_base)
    except ValueError:
        try:
            return _sequential_boundary_claims(cells, index_by_grid, capital, final_count, seed_base)
        except ValueError:
            return _capital_protected_tree_claims(cells, index_by_grid, capital, final_count, seed_base)


def shape_factor(polygon: Polygon) -> float:
    rectangle = polygon.minimum_rotated_rectangle
    coords = list(rectangle.exterior.coords)
    lengths = [Point(coords[i]).distance(Point(coords[i + 1])) for i in range(4)]
    ratio = max(lengths) / max(min(lengths), 0.001)
    compactness = 4.0 * math.pi * polygon.area / max(polygon.length ** 2, 0.001)
    if ratio >= 3.0 or compactness < 0.22:
        return 1.18
    if ratio >= 2.0 or compactness < 0.38:
        return 1.12
    if ratio >= 1.45 or compactness < 0.58:
        return 1.05
    return 1.0


def resolve_count(
    area_km2: float,
    rule: dict[str, Any],
    override: dict[str, Any],
    polygon: Polygon,
    coastal: bool,
) -> tuple[int, dict[str, Any]]:
    coast = 1.05 if coastal else 1.0
    shape = shape_factor(polygon)
    complexity = min(1.35, max(0.85, coast * shape))
    area_count = max(1, round(area_km2 / float(rule["target_cell_area_km2"]) * complexity))
    anchor_minimum = max(1, int(override.get("minimum_cell_count") or 1))
    count = max(area_count, anchor_minimum)
    count = max(int(rule["min_cells_per_province"]), min(int(rule["max_cells_per_province"]), count))
    if override.get("forced_cell_count") is not None:
        count = int(override["forced_cell_count"])
    return count, {
        "coast_factor": coast,
        "shape_factor": shape,
        "relief_factor": 1.0,
        "local_complexity": round(complexity, 6),
        "area_count": area_count,
        "anchor_minimum": anchor_minimum,
        "final_count": count,
    }


def absorb_boundary_fringe(parts: list[Polygon], province: Polygon) -> list[Polygon]:
    """Attach raster-edge fragments to their nearest connected cell.

    The raster is only the working field; the exported cells must cover the
    exact clipped province polygon.  These fragments live on the outer coast,
    never between two cells, so shared borders remain canonical raster edges.
    """
    fringe = province.difference(unary_union(parts))
    fringe_parts = [fringe] if isinstance(fringe, Polygon) else list(getattr(fringe, "geoms", []))
    repaired = list(parts)
    for fragment in fringe_parts:
        if fragment.is_empty or not isinstance(fragment, Polygon):
            continue
        index = min(range(len(repaired)), key=lambda candidate: repaired[candidate].distance(fragment))
        merged = repaired[index].union(fragment)
        if not isinstance(merged, Polygon):
            raise ValueError("boundary fringe would disconnect a cell")
        repaired[index] = merged
    return repaired


def smooth_border_chain(chain: list[list[float]]) -> list[list[float]]:
    """Chaikin smoothing of one already canonical shared border chain."""
    if BORDER_SMOOTHNESS <= 0.001 or len(chain) < 3:
        return chain
    points = [(float(point[0]), float(point[1])) for point in chain]
    for _pass in range(2):
        smoothed = [points[0]]
        for left, right in zip(points, points[1:]):
            q = (left[0] * 0.75 + right[0] * 0.25, left[1] * 0.75 + right[1] * 0.25)
            r = (left[0] * 0.25 + right[0] * 0.75, left[1] * 0.25 + right[1] * 0.75)
            smoothed.extend((q, r))
        smoothed.append(points[-1])
        points = smoothed
    original = [(float(point[0]), float(point[1])) for point in chain]
    # Same endpoint-preserving sampling is used for both owners of the edge.
    result: list[list[float]] = []
    for index, point in enumerate(points):
        source_index = min(len(original) - 1, round(index * (len(original) - 1) / max(1, len(points) - 1)))
        source = original[source_index]
        result.append([
            round(source[0] + (point[0] - source[0]) * BORDER_SMOOTHNESS, 6),
            round(source[1] + (point[1] - source[1]) * BORDER_SMOOTHNESS, 6),
        ])
    result[0] = [round(original[0][0], 6), round(original[0][1], 6)]
    result[-1] = [round(original[-1][0], 6), round(original[-1][1], 6)]
    return result


def smooth_borders(borders: list[list[list[list[float]]]]) -> list[list[list[list[float]]]]:
    return [[smooth_border_chain(chain) for chain in cell_borders] for cell_borders in borders]


def _line_parts(geometry: Any) -> list[LineString]:
    if isinstance(geometry, LineString):
        return [] if geometry.is_empty else [geometry]
    if isinstance(geometry, (MultiLineString, GeometryCollection)):
        return [
            line
            for part in geometry.geoms
            for line in _line_parts(part)
        ]
    return []


def _extend_outer_endpoints(line: LineString, province: Polygon) -> LineString:
    """Make near-coincident outer endpoints actually cross the outer edge.

    GEOS can leave an endpoint about 1e-13 away from the province boundary;
    polygonize then sees an open network. A tiny technical extension is clipped
    by the real outer contour and therefore has no visible effect.
    """
    points = [(float(x), float(y)) for x, y in line.coords]
    if len(points) < 2 or line.is_ring:
        return line
    extension = GRID_STEP * 0.10
    for endpoint_index, neighbour_index in ((0, 1), (-1, -2)):
        endpoint = points[endpoint_index]
        if Point(endpoint).distance(province.boundary) >= 1e-6:
            continue
        neighbour = points[neighbour_index]
        dx = endpoint[0] - neighbour[0]
        dy = endpoint[1] - neighbour[1]
        length = math.hypot(dx, dy)
        if length <= 1e-12:
            continue
        points[endpoint_index] = (
            endpoint[0] + dx / length * extension,
            endpoint[1] + dy / length * extension,
        )
    return LineString(points)


def exact_label_partition(
    province: Polygon,
    index_by_grid: dict[tuple[int, int], int],
    owners: list[int],
    cell_count: int,
    capital_anchor: Point | None = None,
) -> list[Polygon]:
    """Convert raster ownership to an exact, non-overlapping province cover.

    Border grid squares whose centres fall outside the mask are assigned by a
    deterministic flood from the nearest owned square. Every square is then
    clipped against the province once, so the pieces tile the province exactly
    instead of relying on overlapping epsilon-expanded boxes.
    """
    x0, y0, x1, y1 = province.bounds
    ix0 = math.floor(x0 / GRID_STEP) - 1
    iy0 = math.floor(y0 / GRID_STEP) - 1
    ix1 = math.ceil(x1 / GRID_STEP) + 1
    iy1 = math.ceil(y1 / GRID_STEP) + 1
    clipped_squares: dict[tuple[int, int], Any] = {}
    for iy in range(iy0, iy1 + 1):
        for ix in range(ix0, ix1 + 1):
            square = box(ix * GRID_STEP, iy * GRID_STEP, (ix + 1) * GRID_STEP, (iy + 1) * GRID_STEP)
            clipped = square.intersection(province)
            if not clipped.is_empty and clipped.area > 1e-10:
                polygonal = [part for part in raster.polygon_parts(clipped) if part.area > 1e-10]
                if polygonal:
                    clipped_squares[(ix, iy)] = unary_union(polygonal)

    labels: dict[tuple[int, int], int | None] = {
        key: owners[cell_index]
        for key, cell_index in index_by_grid.items()
        if key in clipped_squares
    }

    # Raster keys can be cardinal neighbours while their province-clipped
    # fragments do not actually share an edge. Build the real clipped graph,
    # retain one genuine component per owner, then flood only the detached
    # boundary fragments from those retained components. Every reassignment is
    # therefore connected in final vector geometry, not merely on integer keys.
    actual_graph: dict[tuple[int, int], list[tuple[int, int]]] = {
        key: [] for key in clipped_squares
    }
    for ix, iy in clipped_squares:
        key = (ix, iy)
        for dx, dy in ((1, 0), (0, 1)):
            other = (ix + dx, iy + dy)
            if other not in clipped_squares:
                continue
            shared = clipped_squares[key].boundary.intersection(clipped_squares[other].boundary)
            if shared is None or shared.is_empty or shared.length <= 1e-10:
                continue
            actual_graph[key].append(other)
            actual_graph[other].append(key)

    detached: set[tuple[int, int]] = set()
    for owner in range(cell_count):
        owner_keys = {key for key, label in labels.items() if label == owner}
        components: list[set[tuple[int, int]]] = []
        unseen = set(owner_keys)
        while unseen:
            start = next(iter(unseen))
            component = {start}
            queue: deque[tuple[int, int]] = deque([start])
            while queue:
                current = queue.popleft()
                for other in actual_graph[current]:
                    if other in unseen and other not in component:
                        component.add(other)
                        queue.append(other)
            unseen -= component
            components.append(component)
        if len(components) <= 1:
            continue
        keeper: set[tuple[int, int]] | None = None
        if owner == 0 and capital_anchor is not None:
            keeper = next((
                component for component in components
                if any(clipped_squares[key].covers(capital_anchor) for key in component)
            ), None)
        if keeper is None:
            keeper = max(
                components,
                key=lambda component: sum(clipped_squares[key].area for key in component),
            )
        for component in components:
            if component is not keeper:
                detached.update(component)

    for key in detached:
        labels[key] = None
    queue = deque(sorted((key for key, label in labels.items() if label is not None), key=lambda key: (int(labels[key]), key)))
    while queue:
        current = queue.popleft()
        for other in actual_graph[current]:
            if labels.get(other) is None:
                labels[other] = labels[current]
                queue.append(other)
    if any(label is None for label in labels.values()):
        raise ValueError("province clipped raster contains an unreachable component")

    pieces: list[list[Any]] = [[] for _ in range(cell_count)]
    for key, clipped in clipped_squares.items():
        pieces[int(labels[key])].append(clipped)
    geometries = [unary_union(owner_pieces) for owner_pieces in pieces]
    # A single grid square can itself contain two clipped polygon fragments.
    # The key-level graph cannot see that. Move only such detached geometric
    # fragments to the touching neighbour with the longest real shared edge.
    for _cleanup_pass in range(cell_count * 3 + 3):
        changed = False
        for owner in range(cell_count):
            parts = raster.polygon_parts(geometries[owner])
            if len(parts) <= 1:
                continue
            keeper: Polygon | None = None
            if owner == 0 and capital_anchor is not None:
                keeper = next((part for part in parts if part.covers(capital_anchor)), None)
            if keeper is None:
                keeper = max(parts, key=lambda part: part.area)
            fragments = [part for part in parts if part is not keeper]
            geometries[owner] = keeper
            for fragment in fragments:
                recipient = max(
                    (index for index in range(cell_count) if index != owner),
                    key=lambda index: (
                        fragment.boundary.intersection(geometries[index].boundary).length,
                        -fragment.distance(geometries[index]),
                        geometries[index].area,
                    ),
                )
                geometries[recipient] = unary_union([geometries[recipient], fragment])
            changed = True
        if not changed:
            break

    polygons: list[Polygon] = []
    for owner, geometry in enumerate(geometries):
        parts = raster.polygon_parts(geometry)
        if len(parts) != 1:
            raise ValueError(f"cell {owner} is disconnected after clipped-fragment cleanup")
        polygons.append(parts[0])

    if province.symmetric_difference(unary_union(polygons)).area > 1e-8:
        raise ValueError("exact raster partition does not cover the province")
    overlap = sum(
        left.intersection(right).area
        for index, left in enumerate(polygons)
        for right in polygons[index + 1:]
    )
    if overlap > 1e-8:
        raise ValueError("exact raster partition overlaps")
    return polygons


def vectorize_political_partition(province: Polygon, raster_polygons: list[Polygon]) -> list[Polygon]:
    """Replace staircase borders with 4-8-segment shared vector borders."""
    shared_lines: list[LineString] = []
    for left_index, left in enumerate(raster_polygons):
        for right in raster_polygons[left_index + 1:]:
            # Merge first. Short terminal pieces are what connect a shared
            # border to the exact outer province contour; dropping them here
            # used to create the visible/structural gaps seen in the full run.
            raw_parts = [
                part for part in _line_parts(left.boundary.intersection(right.boundary))
                if part.length > 1e-10
            ]
            if not raw_parts:
                continue
            merged = raw_parts[0] if len(raw_parts) == 1 else linemerge(unary_union(raw_parts))
            for line in _line_parts(merged):
                points = [(float(x), float(y)) for x, y in line.coords]
                # Low-pass the orthogonal raster steps once. Endpoints stay
                # fixed so T-junctions and exits to the province edge remain
                # topologically identical. One pass keeps political corners;
                # repeated Chaikin smoothing produced the unwanted blue arcs.
                if len(points) > 2:
                    filtered = [points[0]]
                    for index in range(1, len(points) - 1):
                        previous = points[index - 1]
                        current = points[index]
                        following = points[index + 1]
                        average = (
                            previous[0] * 0.25 + current[0] * 0.50 + following[0] * 0.25,
                            previous[1] * 0.25 + current[1] * 0.50 + following[1] * 0.25,
                        )
                        filtered.append((
                            current[0] * 0.35 + average[0] * 0.65,
                            current[1] * 0.35 + average[1] * 0.65,
                        ))
                    filtered.append(points[-1])
                    line = LineString(filtered)
                simplified = line.simplify(CONTOUR_SIMPLIFY, preserve_topology=False)
                if simplified.length > GRID_STEP * 0.2 and len(simplified.coords) >= 2:
                    shared_lines.append(_extend_outer_endpoints(simplified, province))

    network = unary_union([province.boundary, *shared_lines])
    faces = [
        face for face in polygonize(network)
        if province.covers(face.representative_point()) and face.area > 1e-6
    ]
    if len(faces) != len(raster_polygons):
        raise ValueError(f"vector borders produced {len(faces)} faces instead of {len(raster_polygons)}")

    rebuilt: list[Polygon] = []
    unused = set(range(len(faces)))
    for source_polygon in raster_polygons:
        face_index = max(
            unused,
            key=lambda index: source_polygon.intersection(faces[index]).area,
        )
        rebuilt.append(faces[face_index])
        unused.remove(face_index)

    union = unary_union(rebuilt)
    overlap = sum(
        left.intersection(right).area
        for index, left in enumerate(rebuilt)
        for right in rebuilt[index + 1:]
    )
    if province.symmetric_difference(union).area > 1e-8 or overlap > 1e-8:
        raise ValueError("vector political borders broke province topology")
    return rebuilt


def polygon_shared_borders(
    polygons: list[Polygon],
) -> tuple[list[list[list[list[float]]]], dict[str, list[str]]]:
    """Export each canonical vector edge identically for both neighbours."""
    borders: list[list[list[list[float]]]] = [[] for _ in polygons]
    neighbours: dict[str, list[str]] = {raster.SEEDS[index][0]: [] for index in range(len(polygons))}
    for left_index, left in enumerate(polygons):
        for right_index in range(left_index + 1, len(polygons)):
            parts = [
                part for part in _line_parts(left.boundary.intersection(polygons[right_index].boundary))
                if part.length > 1e-10
            ]
            if not parts:
                continue
            merged = parts[0] if len(parts) == 1 else linemerge(unary_union(parts))
            parts = [part for part in _line_parts(merged) if part.length > GRID_STEP * 0.2]
            if not parts:
                continue
            left_id = raster.SEEDS[left_index][0]
            right_id = raster.SEEDS[right_index][0]
            neighbours[left_id].append(right_id)
            neighbours[right_id].append(left_id)
            chains = [
                [[round(float(x), 9), round(float(y), 9)] for x, y in part.coords]
                for part in parts
            ]
            borders[left_index].extend(chains)
            borders[right_index].extend(chains)
    return borders, {cell_id: sorted(ids) for cell_id, ids in neighbours.items()}


def build(all_provinces: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    source = read_json(SOURCE)
    geometry_by_legacy = {item.get("legacy_id"): item for item in read_json(GEOMETRY)["provinces"]}
    province_data_by_legacy = {item.get("legacy_id"): item for item in read_json(PROVINCE_DATA)["provinces"]}
    profile_data = read_json(PROFILES)
    region_rules = profile_data["regions"]
    profile_defaults = profile_data["profiles"]
    overrides = {item["province_id"]: item for item in read_json(OVERRIDES).get("overrides", [])}
    approved = read_json(APPROVED_PARTITIONS) if APPROVED_PARTITIONS.exists() else {"cells": [], "province_reports": []}
    approved_legacy_ids = set(approved.get("legacy_ids", []))
    approved_cells_by_province: dict[str, list[dict[str, Any]]] = {}
    for approved_cell in approved.get("cells", []):
        approved_cells_by_province.setdefault(str(approved_cell["province_id"]), []).append(approved_cell)
    approved_reports_by_province = {
        str(item["province_id"]): item for item in approved.get("province_reports", [])
    }
    cities = city_by_name()
    oceans = ocean_parts()
    raster.GRID_STEP = GRID_STEP
    raster.CONTOUR_SIMPLIFY_PX = CONTOUR_SIMPLIFY
    output_cells: list[dict[str, Any]] = []
    province_reports: list[dict[str, Any]] = []
    warnings: list[str] = []

    for source_province in source.get("cells", []):
        legacy_id = str(source_province.get("id", ""))
        if not all_provinces and legacy_id != "spain__la_coru_a":
            continue
        identity = province_data_by_legacy.get(legacy_id)
        geometry = geometry_by_legacy.get(legacy_id)
        if identity is None or geometry is None:
            warnings.append(f"{legacy_id}: missing region identity or area")
            continue
        region_id = str(identity.get("region_id", ""))
        rule = region_rules.get(region_id)
        profile_resolution = "regional_table"
        if rule is None:
            country = legacy_id.split("__", 1)[0]
            fallback_profile_id = COUNTRY_PROFILE_FALLBACK.get(country, "P3")
            rule = dict(profile_defaults[fallback_profile_id])
            rule["profile_id"] = fallback_profile_id
            profile_resolution = "country_profile_fallback"
        polygon = raster.as_polygon(source_province)
        cells, index_by_grid = cover_grid_mask(polygon)
        if not cells:
            warnings.append(f"{legacy_id}: empty exact cover raster")
            continue
        province_id = str(identity["id"])
        if all_provinces and legacy_id in approved_legacy_ids:
            approved_cells = approved_cells_by_province.get(province_id, [])
            approved_report = approved_reports_by_province.get(province_id)
            if approved_cells and approved_report is not None:
                output_cells.extend(approved_cells)
                province_reports.append({
                    **approved_report,
                    "generation_strategy": "user_approved_partition_preserved",
                })
                continue
        override = overrides.get(province_id, {})
        coastal = is_coastal_province(polygon, oceans)
        final_count, count_details = resolve_count(
            float(geometry["area_km2"]), rule, override, polygon, coastal,
        )
        final_count = min(final_count, len(cells))
        name = str(source_province.get("name", legacy_id))
        city = cities.get(name)
        raw_anchor = Point(city["pos"]) if city and len(city.get("pos", [])) >= 2 else polygon.representative_point()
        anchor_resolution = "real_capital"
        anchor_source = raw_anchor
        if raw_anchor.distance(polygon) > GRID_STEP * 1.5:
            # Repeated names (Faro/Murcia/Lisboa/Baleares) are separate true
            # layer-4 geometries. A capital on the main part must not snap a
            # small detached part to an arbitrary outer vertex.
            anchor_source = polygon.representative_point()
            anchor_resolution = "interior_fallback_for_detached_part"
        safe_interior = polygon.buffer(-GRID_STEP * 0.80)
        if safe_interior.is_empty:
            safe_interior = polygon
            anchor_resolution = "interior_fallback_for_small_part"
        anchor = anchor_source if safe_interior.covers(anchor_source) else nearest_points(anchor_source, safe_interior)[1]
        raster.SEEDS = [
            (f"regional-claims:{province_id}:{index + 1:02d}", f"{name} {index + 1}", (anchor.x, anchor.y))
            for index in range(final_count)
        ]
        try:
            polygons, decisions = vector_partition.partition(
                polygon,
                final_count,
                anchor,
                int(identity.get("numeric_id", 0)) * 37,
                GRID_STEP,
            )
            borders, neighbour_map = polygon_shared_borders(polygons)
        except ValueError as error:
            warnings.append(f"{province_id}: recursive vector topology failed: {error}")
            continue
        union = unary_union(polygons)
        coverage_error = polygon.symmetric_difference(union).area / max(polygon.area, 0.001)
        if coverage_error > 0.000001 or len(polygons) != final_count or not polygons[0].covers(anchor):
            warnings.append(f"{province_id}: invalid coverage={coverage_error:.6f}, cells={len(polygons)}/{final_count}")
            continue
        for index, cell_polygon in enumerate(polygons):
            cell_id, cell_name, _seed = raster.SEEDS[index]
            label = cell_polygon.representative_point()
            area_km2 = float(geometry["area_km2"]) * cell_polygon.area / polygon.area
            output_cells.append({
                "id": cell_id,
                "name": cell_name,
                "province_id": province_id,
                "region_id": region_id,
                "profile_id": rule["profile_id"],
                "profile_resolution": profile_resolution,
                "cell_order": index + 1,
                "is_primary": index == 0,
                "capital_anchor": {
                    "raw": [round(raw_anchor.x, 4), round(raw_anchor.y, 4)],
                    "playable": [round(anchor.x, 4), round(anchor.y, 4)],
                } if index == 0 else {},
                "area_km2": round(area_km2, 2),
                "target_area_km2": rule["target_cell_area_km2"],
                "rings": [
                    [[round(float(x), 9), round(float(y), 9)] for x, y in cell_polygon.exterior.coords],
                    *[
                        [[round(float(x), 9), round(float(y), 9)] for x, y in ring.coords]
                        for ring in cell_polygon.interiors
                    ],
                ],
                "bbox": [round(value, 6) for value in cell_polygon.bounds],
                "center": [round(cell_polygon.centroid.x, 4), round(cell_polygon.centroid.y, 4)],
                "label_point": [round(label.x, 4), round(label.y, 4)],
                "brd_open": borders[index],
                "neighbours": neighbour_map[cell_id],
                "color": [0.92, 0.39, 0.20, 0.0],
            })
        province_reports.append({
            "province_id": province_id,
            "legacy_id": legacy_id,
            "region_id": region_id,
            "profile_id": rule["profile_id"],
            "profile_resolution": profile_resolution,
            "capital_anchor_resolution": anchor_resolution,
            "area_km2": geometry["area_km2"],
            "target_cell_area_km2": rule["target_cell_area_km2"],
            "real_capital_anchor": [round(raw_anchor.x, 4), round(raw_anchor.y, 4)],
            "playable_primary_anchor": [round(anchor.x, 4), round(anchor.y, 4)],
            **count_details,
            "splits": decisions,
        })

    return {
        "world_px": source["world_px"],
        "cells": output_cells,
        "provenance": {
            "method": "regional_table_recursive_boundary_to_boundary_political_claims_v3",
            "source": "assets/provinces_iberia.json",
            "coast_rule": "actual world-ocean contact; inland factor is 1.0",
            "working_raster": "all grid squares intersecting the exact layer-4 polygon",
            "generator_version": GENERATOR_VERSION,
            "candidates_per_binary_split": CANDIDATES_PER_SPLIT,
            "grid_step_px": GRID_STEP,
            "contour_simplify_px": CONTOUR_SIMPLIFY,
            "border_smoothness": BORDER_SMOOTHNESS,
            "macro_noise_strength": MACRO_NOISE_STRENGTH,
            "meso_noise_strength": MESO_NOISE_STRENGTH,
            "micro_noise_strength": MICRO_NOISE_STRENGTH,
            "direction_strength": DIRECTION_STRENGTH,
            "target_spread": TARGET_SPREAD,
            "approved_partitions_source": "assets/cells_layer4_approved_partitions.json",
        },
    }, {
        "ok": not warnings,
        "source_province_count": len(source.get("cells", [])) if all_provinces else 1,
        "province_count": len(province_reports),
        "cell_count": len(output_cells),
        "warnings": warnings,
        "provinces": province_reports,
        "profile_defaults_loaded": len(profile_defaults),
    }


def main() -> None:
    global GRID_STEP, CONTOUR_SIMPLIFY, BORDER_SMOOTHNESS, MACRO_NOISE_STRENGTH, MESO_NOISE_STRENGTH, MICRO_NOISE_STRENGTH, DIRECTION_STRENGTH, TARGET_SPREAD
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="build all 105 provinces displayed by layer 4")
    parser.add_argument("--grid-step", type=float, default=GRID_STEP)
    parser.add_argument("--contour-simplify", type=float, default=CONTOUR_SIMPLIFY)
    parser.add_argument("--border-smoothness", type=float, default=BORDER_SMOOTHNESS)
    parser.add_argument("--macro-noise", type=float, default=MACRO_NOISE_STRENGTH)
    parser.add_argument("--meso-noise", type=float, default=MESO_NOISE_STRENGTH)
    parser.add_argument("--micro-noise", type=float, default=MICRO_NOISE_STRENGTH)
    parser.add_argument("--direction", type=float, default=DIRECTION_STRENGTH)
    parser.add_argument("--target-spread", type=float, default=TARGET_SPREAD)
    args = parser.parse_args()
    GRID_STEP = max(0.45, min(1.10, args.grid_step))
    CONTOUR_SIMPLIFY = max(0.0, min(1.40, args.contour_simplify))
    BORDER_SMOOTHNESS = max(0.0, min(1.0, args.border_smoothness))
    MACRO_NOISE_STRENGTH = max(0.0, min(0.90, args.macro_noise))
    MESO_NOISE_STRENGTH = max(0.0, min(0.80, args.meso_noise))
    MICRO_NOISE_STRENGTH = max(0.0, min(0.30, args.micro_noise))
    DIRECTION_STRENGTH = max(0.0, min(0.45, args.direction))
    TARGET_SPREAD = max(0.05, min(0.70, args.target_spread))
    payload, report = build(args.all)
    write_json(OUT, payload)
    write_json(REPORT, report)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(payload['cells'])} cells in {report['province_count']} provinces")
    if report["warnings"]:
        print(f"warnings: {len(report['warnings'])}")


if __name__ == "__main__":
    main()
