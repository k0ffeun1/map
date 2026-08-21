#!/usr/bin/env python3
"""Build stage 3 of the visible La-Coruna subdivision pipeline.

Stage 2 creates 600 atomic microcells.  This tool never redraws their
geometry and does not create final administrative borders.  Instead, four
sources competitively claim neighbouring atoms over the real adjacency graph.
Every claim has a parent and a turn number, so the in-game preview can replay
the growth rather than hiding a direct polygon split behind a final result.
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
import sys
from collections import deque
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Polygon
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "assets" / "game_data" / "subdivision_contracts" / "lacoruna.json"
DEFAULT_MESH = ROOT / "assets" / "subdivision_stages" / "lacoruna_microcells.json"
DEFAULT_OUTPUT = ROOT / "assets" / "subdivision_stages" / "lacoruna_competitive_growth.json"

ZONE_COLORS = [
    [0.94, 0.30, 0.39, 0.52],
    [0.28, 0.76, 0.44, 0.52],
    [0.35, 0.56, 0.96, 0.52],
    [0.70, 0.37, 0.90, 0.52],
]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_project_path(raw: str) -> Path:
    if raw.startswith("res://"):
        return ROOT / raw.removeprefix("res://")
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def polygon_parts(geometry: Any) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [] if geometry.is_empty else [geometry]
    if isinstance(geometry, MultiPolygon):
        return [part for part in geometry.geoms if not part.is_empty and part.area > 1e-10]
    if isinstance(geometry, GeometryCollection):
        return [part for part in geometry.geoms if isinstance(part, Polygon) and not part.is_empty and part.area > 1e-10]
    return []


def line_parts(geometry: Any) -> list[LineString]:
    if isinstance(geometry, LineString):
        return [] if geometry.is_empty or geometry.length <= 1e-7 else [geometry]
    if isinstance(geometry, MultiLineString):
        return [part for part in geometry.geoms if not part.is_empty and part.length > 1e-7]
    if isinstance(geometry, GeometryCollection):
        result: list[LineString] = []
        for part in geometry.geoms:
            result.extend(line_parts(part))
        return result
    return []


def polygon_from_rings(rings: list[Any], label: str) -> Polygon:
    if not rings or len(rings[0]) < 3:
        raise ValueError("%s has no usable rings" % label)
    polygon = Polygon(rings[0], rings[1:])
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    parts = polygon_parts(polygon)
    if len(parts) != 1:
        raise ValueError("%s must be one connected polygon" % label)
    return parts[0]


def edge_cost(positions: list[tuple[float, float]], first: int, second: int) -> float:
    ax, ay = positions[first]
    bx, by = positions[second]
    return max(math.hypot(ax - bx, ay - by), 1e-8)


def dijkstra_distances(
    adjacency: list[list[int]], positions: list[tuple[float, float]], source: int
) -> list[float]:
    distances = [math.inf] * len(adjacency)
    distances[source] = 0.0
    queue: list[tuple[float, int]] = [(0.0, source)]
    while queue:
        distance, current = heapq.heappop(queue)
        if distance != distances[current]:
            continue
        for neighbour in adjacency[current]:
            candidate = distance + edge_cost(positions, current, neighbour)
            if candidate < distances[neighbour] - 1e-12:
                distances[neighbour] = candidate
                heapq.heappush(queue, (candidate, neighbour))
    return distances


def graph_is_connected(adjacency: list[list[int]]) -> bool:
    if not adjacency:
        return False
    visited = {0}
    queue: deque[int] = deque([0])
    while queue:
        current = queue.popleft()
        for neighbour in adjacency[current]:
            if neighbour not in visited:
                visited.add(neighbour)
                queue.append(neighbour)
    return len(visited) == len(adjacency)


def choose_seeds(
    adjacency: list[list[int]], positions: list[tuple[float, float]], capital_index: int, count: int
) -> tuple[list[int], list[list[float]]]:
    """Capital plus graph-distance farthest points, avoiding coast dead ends."""
    seeds = [capital_index]
    distance_fields = [dijkstra_distances(adjacency, positions, capital_index)]
    eligible = [index for index, neighbours in enumerate(adjacency) if len(neighbours) > 1]
    if capital_index not in eligible:
        eligible.append(capital_index)
    while len(seeds) < count:
        candidates = [index for index in eligible if index not in seeds]
        if not candidates:
            candidates = [index for index in range(len(adjacency)) if index not in seeds]
        next_seed = max(
            candidates,
            key=lambda index: (min(field[index] for field in distance_fields), -index),
        )
        seeds.append(next_seed)
        distance_fields.append(dijkstra_distances(adjacency, positions, next_seed))
    return seeds, distance_fields


def choose_contract_shape_anchors(
    settings: dict[str, Any],
    cell_ids: list[str],
    index_by_id: dict[str, int],
    adjacency: list[list[int]],
    positions: list[tuple[float, float]],
    capital_index: int,
    count: int,
) -> tuple[list[int], list[list[float]], list[dict[str, Any]], str]:
    """Resolve named sources from the visible subdivision contract.

    The old farthest-point seeds were useful for testing graph growth, but
    could put a source at the end of a thin coastal arm.  Shape anchors are
    deliberately part of the contract: the four fronts start from meaningful
    positions and their relative speed is balanced later by the assignment.
    """
    raw_anchors = settings.get("seed_anchors", [])
    if not isinstance(raw_anchors, list) or len(raw_anchors) != count:
        seeds, distances = choose_seeds(adjacency, positions, capital_index, count)
        fallback = [
            {
                "id": "capital" if zone == 0 else "fallback_%d" % (zone + 1),
                "name": "Capital growth zone" if zone == 0 else "Growth zone %d" % (zone + 1),
                "microcell_id": cell_ids[seed],
            }
            for zone, seed in enumerate(seeds)
        ]
        return seeds, distances, fallback, "capital_plus_farthest_graph_anchors"

    seeds: list[int] = []
    anchors: list[dict[str, Any]] = []
    for zone, raw_anchor in enumerate(raw_anchors):
        if not isinstance(raw_anchor, dict):
            raise ValueError("competitive-growth seed anchor must be an object")
        requested_id = str(raw_anchor.get("microcell_id", ""))
        if zone == 0:
            if requested_id and requested_id != cell_ids[capital_index]:
                raise ValueError("capital growth anchor must use the capital microcell")
            seed = capital_index
        else:
            seed = index_by_id.get(requested_id, -1)
            if seed < 0:
                raise ValueError("growth anchor points to an unknown microcell: %s" % requested_id)
        if seed in seeds:
            raise ValueError("growth anchors must use different microcells")
        seeds.append(seed)
        anchors.append(
            {
                "id": str(raw_anchor.get("id", "source_%d" % (zone + 1))),
                "name": str(raw_anchor.get("name", "Growth zone %d" % (zone + 1))),
                "microcell_id": cell_ids[seed],
            }
        )
    distances = [dijkstra_distances(adjacency, positions, seed) for seed in seeds]
    return seeds, distances, anchors, "capital_plus_contract_shape_anchors"


def shared_length(
    first: int, second: int, shared_edges: dict[tuple[int, int], float]
) -> float:
    return shared_edges.get((min(first, second), max(first, second)), 0.0)


def assign_weighted_graph_voronoi(
    cell_ids: list[str],
    areas: list[float],
    adjacency: list[list[int]],
    seed_indices: list[int],
    distance_fields: list[list[float]],
    shared_edges: dict[tuple[int, int], float],
    iterations: int,
    gain: float,
) -> tuple[list[int], list[float], list[float], int]:
    """Balance additive graph-Voronoi fronts without producing skinny arms.

    Each microcell belongs to the source with the smallest
    ``graph_distance - source_priority``.  The priorities are iteratively
    adjusted toward equal real area.  Unlike round-robin frontier grabbing,
    this keeps every source's natural compact catchment instead of allowing a
    late source to thread a one-cell corridor between two earlier fronts.
    """
    zone_count = len(seed_indices)
    target_area = sum(areas) / float(zone_count)
    biases = [0.0] * zone_count
    best: tuple[tuple[float, float, float, int], list[int], list[float], list[float], int] | None = None
    for iteration in range(max(1, iterations)):
        owners = [
            min(
                range(zone_count),
                key=lambda zone: (distance_fields[zone][index] - biases[zone], zone),
            )
            for index in range(len(cell_ids))
        ]
        # A source is an immutable anchor.  In the normal case it already owns
        # itself; forcing this explicitly makes that contract true even if a
        # future tuning value becomes too aggressive.
        for zone, seed in enumerate(seed_indices):
            owners[seed] = zone
        zone_areas = [0.0] * zone_count
        for index, owner in enumerate(owners):
            zone_areas[owner] += areas[index]

        if all(zone_is_connected(adjacency, owners, zone, seed_indices[zone]) for zone in range(zone_count)):
            max_deviation = max(abs(area - target_area) / target_area for area in zone_areas)
            perimeter = sum(
                length for (first, second), length in shared_edges.items() if owners[first] != owners[second]
            )
            total_deviation = sum(abs(area - target_area) / target_area for area in zone_areas)
            objective = (max_deviation, perimeter, total_deviation, iteration)
            candidate = (objective, owners, zone_areas, biases.copy(), iteration)
            if best is None or objective < best[0]:
                best = candidate

        # A zone below target gets a higher priority on the next iteration;
        # subtracting the mean changes no pairwise comparison and avoids drift.
        for zone in range(zone_count):
            biases[zone] += gain * (target_area - zone_areas[zone]) / target_area
        bias_mean = sum(biases) / float(zone_count)
        biases = [bias - bias_mean for bias in biases]

    if best is None:
        raise RuntimeError("balanced weighted growth did not produce connected zones")
    _, owners, zone_areas, selected_biases, selected_iteration = best
    return owners, zone_areas, selected_biases, selected_iteration


def zone_is_connected(adjacency: list[list[int]], owners: list[int], zone: int, seed: int) -> bool:
    expected = {index for index, owner in enumerate(owners) if owner == zone}
    visited = {seed}
    queue: deque[int] = deque([seed])
    while queue:
        current = queue.popleft()
        for neighbour in adjacency[current]:
            if owners[neighbour] == zone and neighbour not in visited:
                visited.add(neighbour)
                queue.append(neighbour)
    return visited == expected


def build_growth_replay(
    cell_ids: list[str],
    adjacency: list[list[int]],
    owners: list[int],
    seed_indices: list[int],
    distance_fields: list[list[float]],
) -> tuple[list[int], list[str | None]]:
    """Turn the final compact assignment into four real adjacent wavefronts."""
    steps = [-1] * len(cell_ids)
    parents: list[str | None] = [None] * len(cell_ids)
    for zone, seed in enumerate(seed_indices):
        if owners[seed] != zone:
            raise RuntimeError("a protected growth seed was assigned to another zone")
        steps[seed] = 0
        queue: deque[int] = deque([seed])
        while queue:
            current = queue.popleft()
            children = sorted(
                (node for node in adjacency[current] if owners[node] == zone and steps[node] < 0),
                key=lambda node: (distance_fields[zone][node], cell_ids[node]),
            )
            for child in children:
                steps[child] = steps[current] + 1
                parents[child] = cell_ids[current]
                queue.append(child)
        if any(owner == zone and steps[index] < 0 for index, owner in enumerate(owners)):
            raise RuntimeError("growth replay cannot reach every microcell in a zone")
    return steps, parents


def find_material_necks(
    adjacency: list[list[int]],
    owners: list[int],
    areas: list[float],
    zone_count: int,
    minimum_tail_cells: int,
    minimum_tail_area_ratio: float,
) -> list[dict[str, Any]]:
    """Find one-atom gates that detach a material part of a zone.

    A degree-one coastal tip is normal.  A gate is rejected only when removing
    one internal atom detaches at least two atoms or at least a configured
    fraction of a zone.  This is a topology quality constraint, not a draw
    trick, so a corridor cannot silently return after a rebuild.
    """
    problems: list[dict[str, Any]] = []
    for zone in range(zone_count):
        members = {index for index, owner in enumerate(owners) if owner == zone}
        zone_area = sum(areas[index] for index in members)
        for gate in sorted(members):
            local_neighbours = [node for node in adjacency[gate] if node in members]
            if len(local_neighbours) < 2:
                continue
            remaining = members - {gate}
            unseen = set(remaining)
            components: list[list[int]] = []
            while unseen:
                start = min(unseen)
                component = [start]
                unseen.remove(start)
                queue: deque[int] = deque([start])
                while queue:
                    current = queue.popleft()
                    for neighbour in adjacency[current]:
                        if neighbour in unseen:
                            unseen.remove(neighbour)
                            component.append(neighbour)
                            queue.append(neighbour)
                components.append(component)
            if len(components) < 2:
                continue
            tail = min(components, key=lambda component: (sum(areas[index] for index in component), len(component)))
            tail_area = sum(areas[index] for index in tail)
            if len(tail) >= minimum_tail_cells or tail_area >= minimum_tail_area_ratio * zone_area:
                problems.append(
                    {
                        "zone": zone,
                        "gate": gate,
                        "tail_cell_count": len(tail),
                        "tail_area_km2": tail_area,
                    }
                )
    return problems


def coordinates(line: LineString) -> list[list[float]]:
    return [[round(float(x), 6), round(float(y), 6)] for x, y in line.coords]


def build(contract_path: Path, mesh_path: Path, output_path: Path) -> dict[str, Any]:
    contract = load_json(contract_path)
    if contract.get("format") != "province_subdivision_contract/v1":
        raise ValueError("unsupported subdivision contract")
    mesh = load_json(mesh_path)
    if mesh.get("format") != "province_microcell_mesh/v1":
        raise ValueError("stage 3 requires province_microcell_mesh/v1 input")
    if mesh.get("contract_id") != contract.get("id"):
        raise ValueError("microcell mesh belongs to a different subdivision contract")

    settings: dict[str, Any] = contract.get("generation", {}).get("competitive_growth_stage", {})
    zone_count = int(settings.get("target_zone_count", contract.get("generation", {}).get("target_cell_count", 4)))
    if zone_count != 4:
        raise ValueError("the La-Coruna visible pilot currently requires exactly four growth zones")
    cells: list[dict[str, Any]] = list(mesh.get("cells", []))
    if len(cells) < zone_count:
        raise ValueError("microcell mesh has fewer cells than requested zones")

    cell_ids = [str(cell.get("id", "")) for cell in cells]
    if any(not cell_id for cell_id in cell_ids) or len(set(cell_ids)) != len(cell_ids):
        raise ValueError("microcell ids must be present and unique")
    index_by_id = {cell_id: index for index, cell_id in enumerate(cell_ids)}
    areas = [float(cell.get("area_km2", 0.0)) for cell in cells]
    if any(area <= 0.0 for area in areas):
        raise ValueError("every microcell must have a positive area")
    positions: list[tuple[float, float]] = []
    for cell in cells:
        centroid = cell.get("centroid", [])
        if not isinstance(centroid, list) or len(centroid) != 2:
            raise ValueError("microcell has no centroid")
        positions.append((float(centroid[0]), float(centroid[1])))
    polygons = [polygon_from_rings(list(cell.get("rings", [])), cell_ids[index]) for index, cell in enumerate(cells)]
    adjacency: list[list[int]] = []
    for cell in cells:
        neighbours: list[int] = []
        for raw_neighbour in cell.get("neighbors", []):
            neighbour_id = str(raw_neighbour)
            if neighbour_id not in index_by_id:
                raise ValueError("microcell neighbour is absent from mesh: %s" % neighbour_id)
            neighbours.append(index_by_id[neighbour_id])
        adjacency.append(sorted(set(neighbours)))
    if not graph_is_connected(adjacency):
        raise ValueError("microcell adjacency graph is disconnected")
    for index, neighbours in enumerate(adjacency):
        if not neighbours:
            raise ValueError("microcell has no graph neighbour: %s" % cell_ids[index])
        for neighbour in neighbours:
            if index not in adjacency[neighbour]:
                raise ValueError("microcell graph is not symmetric")

    capital_indices = [index for index, cell in enumerate(cells) if bool(cell.get("is_capital_microcell", False))]
    if len(capital_indices) != 1:
        raise ValueError("stage 3 requires exactly one capital microcell")
    capital_index = capital_indices[0]
    seed_indices, distance_fields, seed_anchors, seed_strategy = choose_contract_shape_anchors(
        settings, cell_ids, index_by_id, adjacency, positions, capital_index, zone_count
    )

    shared_edges: dict[tuple[int, int], float] = {}
    for first, neighbours in enumerate(adjacency):
        for second in neighbours:
            if second <= first:
                continue
            length = polygons[first].boundary.intersection(polygons[second].boundary).length
            if length > 1e-7:
                shared_edges[(first, second)] = length
    if not shared_edges:
        raise ValueError("microcell graph has no geometric shared edges")

    bias_iterations = max(1, int(settings.get("bias_balance_iterations", 128)))
    bias_gain = float(settings.get("bias_balance_gain", 1.5))
    owners, zone_areas, source_biases, selected_iteration = assign_weighted_graph_voronoi(
        cell_ids,
        areas,
        adjacency,
        seed_indices,
        distance_fields,
        shared_edges,
        bias_iterations,
        bias_gain,
    )
    if any(owner < 0 for owner in owners):
        raise RuntimeError("competitive growth left unassigned microcells")
    if owners[capital_index] != 0:
        raise RuntimeError("capital microcell left its protected growth zone")
    steps, parents = build_growth_replay(cell_ids, adjacency, owners, seed_indices, distance_fields)

    zones: list[dict[str, Any]] = []
    zone_polygons: list[Polygon] = []
    zone_compactness: list[float] = []
    zone_ids = ["growth_zone:2848:%02d" % (index + 1) for index in range(zone_count)]
    for zone in range(zone_count):
        members = [index for index, owner in enumerate(owners) if owner == zone]
        if not zone_is_connected(adjacency, owners, zone, seed_indices[zone]):
            raise RuntimeError("growth zone %d is disconnected" % (zone + 1))
        geometry = unary_union([polygons[index] for index in members])
        parts = polygon_parts(geometry)
        hole_count = sum(len(part.interiors) for part in parts)
        if len(parts) != 1 or hole_count:
            raise RuntimeError("growth zone %d has a disconnected part or a hole" % (zone + 1))
        zone_polygon = parts[0]
        zone_polygons.append(zone_polygon)
        compactness = 4.0 * math.pi * zone_polygon.area / max(zone_polygon.length * zone_polygon.length, 1e-12)
        zone_compactness.append(compactness)
        point = zone_polygon.representative_point()
        zones.append(
            {
                "id": zone_ids[zone],
                "name": seed_anchors[zone]["name"],
                "role": "capital" if zone == 0 else "growth_source",
                "color": ZONE_COLORS[zone],
                "source_id": seed_anchors[zone]["id"],
                "seed_microcell_id": cell_ids[seed_indices[zone]],
                "seed_point": [round(positions[seed_indices[zone]][0], 6), round(positions[seed_indices[zone]][1], 6)],
                "label_point": [round(point.x, 6), round(point.y, 6)],
                "microcell_ids": [cell_ids[index] for index in members],
                "microcell_count": len(members),
                "area_km2": round(zone_areas[zone], 4),
                "compactness": round(compactness, 6),
            }
        )

    minimum_compactness = float(settings.get("minimum_zone_compactness", 0.0))
    if min(zone_compactness) < minimum_compactness:
        raise RuntimeError(
            "competitive growth produced an over-elongated zone: %.4f < %.4f"
            % (min(zone_compactness), minimum_compactness)
        )
    material_necks = find_material_necks(
        adjacency,
        owners,
        areas,
        zone_count,
        max(2, int(settings.get("material_neck_min_tail_microcells", 2))),
        float(settings.get("material_neck_min_tail_area_ratio", 0.03)),
    )
    if material_necks:
        first_neck = material_necks[0]
        raise RuntimeError(
            "competitive growth produced a material one-cell corridor in zone %d at %s"
            % (first_neck["zone"] + 1, cell_ids[first_neck["gate"]])
        )

    interzone: dict[tuple[int, int], dict[str, Any]] = {}
    boundary_segments: list[dict[str, Any]] = []
    for (first, second), length in shared_edges.items():
        first_zone = owners[first]
        second_zone = owners[second]
        if first_zone == second_zone:
            continue
        pair = (min(first_zone, second_zone), max(first_zone, second_zone))
        record = interzone.setdefault(pair, {"edge_count": 0, "shared_length_world_px": 0.0})
        record["edge_count"] += 1
        record["shared_length_world_px"] += length
        shared_geometry = polygons[first].boundary.intersection(polygons[second].boundary)
        for line in line_parts(shared_geometry):
            boundary_segments.append(
                {
                    "zones": [zone_ids[pair[0]], zone_ids[pair[1]]],
                    "microcells": [cell_ids[first], cell_ids[second]],
                    "points": coordinates(line),
                }
            )
    interzone_adjacency = [
        {
            "zones": [zone_ids[first], zone_ids[second]],
            "microcell_edge_count": data["edge_count"],
            "shared_length_world_px": round(float(data["shared_length_world_px"]), 6),
        }
        for (first, second), data in sorted(interzone.items())
    ]

    province = polygon_from_rings(list(mesh.get("province_rings", [])), "source province")
    complete_union = unary_union(polygons)
    source_area = max(province.area, 1e-12)
    missing_ratio = province.difference(complete_union).area / source_area
    extra_ratio = complete_union.difference(province).area / source_area
    overlap_ratio = max(0.0, (sum(polygon.area for polygon in polygons) - complete_union.area) / source_area)
    # Stage 2 stores coordinates rounded to six decimals.  Reconstructing
    # polygons from that visible JSON produces a tiny seam (~1e-8), well below
    # the contract's explicit 1e-6 coverage allowance.
    coverage_tolerance = float(
        contract.get("constraints", {}).get("topology", {}).get("maximum_uncovered_area_ratio", 1e-6)
    )
    overlap_tolerance = float(
        contract.get("constraints", {}).get("topology", {}).get("maximum_overlap_area_ratio", 1e-6)
    )
    if missing_ratio > coverage_tolerance or extra_ratio > coverage_tolerance or overlap_ratio > overlap_tolerance:
        raise RuntimeError("source microcell coverage is invalid")

    effective_target = sum(areas) / float(zone_count)
    max_deviation = max(abs(area - effective_target) / effective_target for area in zone_areas)
    balance_ratio = max(zone_areas) / min(zone_areas)
    profile_target = float(contract.get("generation", {}).get("target_cell_area_km2", effective_target))
    minimum_ratio, maximum_ratio = [float(value) for value in contract.get("constraints", {}).get("area_ratio_limits", [0.0, math.inf])]
    contract_area_ok = all(minimum_ratio <= area / profile_target <= maximum_ratio for area in zone_areas)
    tolerance = float(settings.get("effective_area_tolerance_ratio", 0.05))
    if max_deviation > tolerance or not contract_area_ok:
        raise RuntimeError("competitive growth failed the area-balance contract")

    claims = [
        {
            "microcell_id": cell_ids[index],
            "zone_id": zone_ids[owners[index]],
            "growth_step": steps[index],
            "parent_microcell_id": parents[index],
            "is_seed": index in seed_indices,
        }
        for index in range(len(cell_ids))
    ]
    payload = {
        "format": "province_competitive_growth/v1",
        "stage": {"number": 3, "name": "Конкурентный рост четырёх зон"},
        "contract_id": contract["id"],
        "source_mesh_path": "res://assets/subdivision_stages/lacoruna_microcells.json",
        "province_id": mesh["province_id"],
        "province_name": mesh["province_name"],
        "capital_anchor": mesh["capital_anchor"],
        "generation": {
            "method": "balanced_additive_weighted_graph_growth",
            "target_zone_count": zone_count,
            "seed_strategy": seed_strategy,
            "source_priority_biases": [round(value, 6) for value in source_biases],
            "bias_balance_iterations": bias_iterations,
            "bias_balance_gain": bias_gain,
            "selected_balance_iteration": selected_iteration,
            "effective_target_area_km2": round(effective_target, 5),
            "profile_target_area_km2": profile_target,
            "deterministic_seed": contract.get("generation", {}).get("deterministic_seed"),
            "growth_step_count": max(steps),
        },
        "zones": zones,
        "claims": claims,
        "interzone_adjacency": interzone_adjacency,
        "boundary_segments": boundary_segments,
        "validation": {
            "all_microcells_assigned": len(claims) == len(cells),
            "assigned_microcell_count": len(claims),
            "unique_assignment_count": len({claim["microcell_id"] for claim in claims}),
            "capital_zone_id": zone_ids[owners[capital_index]],
            "all_zones_connected": True,
            "all_zones_without_holes": True,
            "source_coverage_complete": True,
            "missing_area_ratio": missing_ratio,
            "extra_area_ratio": extra_ratio,
            "overlap_area_ratio": overlap_ratio,
            "effective_area_tolerance_ratio": tolerance,
            "maximum_effective_area_deviation_ratio": round(max_deviation, 8),
            "zone_area_balance_ratio": round(balance_ratio, 8),
            "all_zones_within_contract_area_limits": contract_area_ok,
            "interzone_microcell_edge_count": sum(item["microcell_edge_count"] for item in interzone_adjacency),
            "minimum_zone_compactness_required": minimum_compactness,
            "minimum_zone_compactness_observed": round(min(zone_compactness), 8),
            "material_one_cell_corridor_count": len(material_necks),
        },
    }
    write_json(output_path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--mesh", type=Path, default=DEFAULT_MESH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    contract_path = resolve_project_path(str(args.contract))
    mesh_path = resolve_project_path(str(args.mesh))
    output_path = resolve_project_path(str(args.output))
    try:
        payload = build(contract_path, mesh_path, output_path)
    except (OSError, json.JSONDecodeError, TypeError, KeyError, ValueError, RuntimeError) as exc:
        print("COMPETITIVE GROWTH BUILD FAILED: %s" % exc, file=sys.stderr)
        return 1
    print(
        "COMPETITIVE GROWTH BUILD OK: %d zones, %d claims, balance %.4f -> %s"
        % (
            len(payload["zones"]),
            len(payload["claims"]),
            payload["validation"]["zone_area_balance_ratio"],
            output_path,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
