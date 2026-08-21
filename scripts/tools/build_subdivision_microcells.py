#!/usr/bin/env python3
"""Build the visible microcell substrate for a province subdivision contract.

This is deliberately *not* a generator of final administrative districts.
It produces small, connected atomic polygons and their adjacency graph.  The
next stage will grow the contract's four districts by assigning these atoms,
so every future border remains inspectable and cannot create a hidden gap or
an enclave between raster pixels.

The default target is the stage-2 La-Coruna pilot.  It is deterministic: the
same contract, source geometry, and seed yield byte-stable geometry ordering.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import GeometryCollection, MultiPoint, MultiPolygon, Point, Polygon
from shapely.ops import unary_union, voronoi_diagram
from shapely.strtree import STRtree


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "assets" / "game_data" / "subdivision_contracts" / "lacoruna.json"
DEFAULT_OUTPUT = ROOT / "assets" / "subdivision_stages" / "lacoruna_microcells.json"
EARTH_RADIUS_KM = 6371.0088


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
        return [item for item in geometry.geoms if not item.is_empty and item.area > 1e-10]
    if isinstance(geometry, GeometryCollection):
        return [item for item in geometry.geoms if isinstance(item, Polygon) and not item.is_empty and item.area > 1e-10]
    return []


def polygon_from_entry(entry: dict[str, Any]) -> Polygon:
    rings = entry.get("rings", [])
    if not rings or len(rings[0]) < 3:
        raise ValueError("province has no usable rings")
    polygon = Polygon(rings[0], rings[1:])
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    parts = polygon_parts(polygon)
    if len(parts) != 1:
        raise ValueError("stage-2 pilot requires one connected province polygon")
    return parts[0]


def rings_from_polygon(polygon: Polygon) -> list[list[list[float]]]:
    def points(coords: Iterable[tuple[float, float]]) -> list[list[float]]:
        return [[round(float(x), 6), round(float(y), 6)] for x, y in coords]

    return [points(polygon.exterior.coords)] + [points(ring.coords) for ring in polygon.interiors]


def km_per_world_px(y: float, world_px: float) -> float:
    mercator_n = math.pi - 2.0 * math.pi * y / world_px
    latitude = math.degrees(math.atan(math.sinh(mercator_n)))
    return 2.0 * math.pi * EARTH_RADIUS_KM / world_px * math.cos(math.radians(latitude))


def area_km2(polygon: Polygon, world_px: float) -> float:
    scale = km_per_world_px(polygon.representative_point().y, world_px)
    return polygon.area * scale * scale


def poisson_disk_samples(
    polygon: Polygon,
    desired_count: int,
    requested_min_distance: float,
    seed: int,
    capital: Point | None,
) -> tuple[list[Point], float]:
    """Deterministic dart throwing with a spatial hash and safe retries.

    The small retry sequence is only a density safeguard for very thin
    provinces.  La-Coruna's requested density succeeds at the first value,
    but retaining the fallback makes the contract reusable.
    """
    min_x, min_y, max_x, max_y = polygon.bounds
    for retry in range(7):
        min_distance = requested_min_distance * (0.94**retry)
        rng = random.Random(seed + retry * 104729)
        bucket_size = min_distance / math.sqrt(2.0)
        buckets: dict[tuple[int, int], list[Point]] = {}
        samples: list[Point] = []

        def key(point: Point) -> tuple[int, int]:
            return (math.floor(point.x / bucket_size), math.floor(point.y / bucket_size))

        def can_add(point: Point) -> bool:
            if not polygon.covers(point):
                return False
            bx, by = key(point)
            for iy in range(by - 2, by + 3):
                for ix in range(bx - 2, bx + 3):
                    for other in buckets.get((ix, iy), []):
                        if point.distance(other) < min_distance:
                            return False
            return True

        def append(point: Point) -> None:
            samples.append(point)
            buckets.setdefault(key(point), []).append(point)

        if capital is not None and polygon.covers(capital):
            append(capital)
        attempts = 0
        max_attempts = desired_count * 2500
        while len(samples) < desired_count and attempts < max_attempts:
            attempts += 1
            candidate = Point(rng.uniform(min_x, max_x), rng.uniform(min_y, max_y))
            if can_add(candidate):
                append(candidate)
        if len(samples) == desired_count:
            return samples, min_distance
    raise RuntimeError(
        "Could not place %d Poisson samples; lower microcell density or minimum seed distance" % desired_count
    )


def build_clipped_voronoi_cells(province: Polygon, seeds: list[Point]) -> list[tuple[int, Polygon]]:
    diagram = voronoi_diagram(
        MultiPoint(seeds), envelope=province.envelope.buffer(max(province.length, 1.0)), edges=False
    )
    by_seed: dict[int, list[Polygon]] = {index: [] for index in range(len(seeds))}
    for region in polygon_parts(diagram):
        owner = next((index for index, seed in enumerate(seeds) if region.covers(seed)), None)
        if owner is None:
            owner = min(range(len(seeds)), key=lambda index: region.distance(seeds[index]))
        clipped = region.intersection(province)
        if not clipped.is_valid:
            clipped = clipped.buffer(0)
        by_seed[owner].extend(polygon_parts(clipped))

    cells: list[tuple[int, Polygon]] = []
    for owner, pieces in by_seed.items():
        for piece in sorted(pieces, key=lambda item: (-item.area, item.centroid.x, item.centroid.y)):
            cells.append((owner, piece))
    if not cells:
        raise RuntimeError("Voronoi clipping produced no microcells")
    return cells


def merge_tiny_fragments(
    cells: list[tuple[int, Polygon]],
    minimum_area_px2: float,
    target_count: int,
    protected_point: Point | None,
) -> list[tuple[int, Polygon]]:
    """Absorb coastline crumbs into the neighbour with the longest shared edge.

    Clipping a Voronoi face against a high-detail coast can occasionally split
    off a centimetre-sized sliver.  It is not useful as an atomic unit and
    would make the visual stage look broken.  Merging through a real shared
    edge preserves coverage and leaves every resulting microcell connected.
    """
    result = cells.copy()
    while True:
        tiny_candidates = [
            index
            for index, (_, polygon) in enumerate(result)
            if polygon.area < minimum_area_px2 and (protected_point is None or not polygon.covers(protected_point))
        ]
        if tiny_candidates:
            tiny_index = min(tiny_candidates, key=lambda index: result[index][1].area)
        elif len(result) > target_count:
            # A concave coast can split a full-size Voronoi face in two.  We
            # still keep the contract's exact requested atom count by joining
            # the smallest non-capital fragment to its real neighbour.
            mergeable = [
                index
                for index, (_, polygon) in enumerate(result)
                if protected_point is None or not polygon.covers(protected_point)
            ]
            if not mergeable:
                raise RuntimeError("only protected capital microcell remains")
            tiny_index = min(mergeable, key=lambda index: result[index][1].area)
        else:
            break
        tiny_owner, tiny = result[tiny_index]
        polygons = [polygon for _, polygon in result]
        tree = STRtree(polygons)
        best: tuple[float, int] | None = None
        for raw_candidate in tree.query(tiny):
            candidate_index = int(raw_candidate)
            if candidate_index == tiny_index:
                continue
            shared_length = tiny.boundary.intersection(polygons[candidate_index].boundary).length
            if shared_length > 1e-7 and (best is None or shared_length > best[0]):
                best = (shared_length, candidate_index)
        if best is None:
            raise RuntimeError("tiny microcell has no shared boundary to merge through")
        _, target_index = best
        target_owner, target = result[target_index]
        merged = target.union(tiny)
        if not merged.is_valid:
            merged = merged.buffer(0)
        parts = polygon_parts(merged)
        if len(parts) != 1:
            raise RuntimeError("merging a coastline fragment would make a disconnected microcell")
        result[target_index] = (target_owner, parts[0])
        del result[tiny_index]
    return sorted(result, key=lambda item: (item[0], item[1].centroid.x, item[1].centroid.y))


def adjacency(polygons: list[Polygon]) -> list[list[int]]:
    tree = STRtree(polygons)
    result: list[set[int]] = [set() for _ in polygons]
    for index, polygon in enumerate(polygons):
        for raw_other in tree.query(polygon):
            other_index = int(raw_other)
            if other_index <= index:
                continue
            other = polygons[other_index]
            if polygon.boundary.intersection(other.boundary).length <= 1e-7:
                continue
            result[index].add(other_index)
            result[other_index].add(index)
    return [sorted(items) for items in result]


def load_contract_and_province(contract_path: Path) -> tuple[dict[str, Any], dict[str, Any], Polygon]:
    contract = load_json(contract_path)
    if contract.get("format") != "province_subdivision_contract/v1":
        raise ValueError("unsupported subdivision-contract format")
    province_spec = contract.get("province", {})
    source_path = resolve_project_path(str(province_spec.get("geometry_path", "")))
    source = load_json(source_path)
    entry = next((item for item in source.get("provinces", []) if item.get("id") == province_spec.get("id")), None)
    if entry is None:
        raise ValueError("contract province is absent from its source geometry")
    return contract, entry, polygon_from_entry(entry)


def build(contract_path: Path, output_path: Path) -> dict[str, Any]:
    contract, province_entry, province = load_contract_and_province(contract_path)
    generation: dict[str, Any] = contract["generation"]
    settings: dict[str, Any] = generation.get("microcell_stage", {})
    requested_count = int(settings.get("requested_cell_count", 600))
    if requested_count < 8:
        raise ValueError("a microcell stage needs at least 8 cells")
    capital_raw = contract["province"].get("capital_anchor", {}).get("point", [])
    capital = Point(capital_raw) if len(capital_raw) == 2 and settings.get("include_capital_seed", True) else None
    seeds, actual_min_distance = poisson_disk_samples(
        province,
        requested_count,
        float(settings.get("minimum_seed_distance_world_px", 0.55)),
        int(generation.get("deterministic_seed", 0)),
        capital,
    )
    owned_cells = build_clipped_voronoi_cells(province, seeds)
    # Six percent of the average atom is safely below a playable microcell
    # (~0.8 km² for the La-Coruna pilot), but removes the coastal crumbs that
    # are caused only by clipping precision rather than by meaningful shape.
    owned_cells = merge_tiny_fragments(
        owned_cells,
        province.area / requested_count * 0.06,
        requested_count,
        capital,
    )
    polygons = [polygon for _, polygon in owned_cells]
    neighbor_indices = adjacency(polygons)
    world_px = float(province_entry.get("world_px", 8192.0))
    # Province geometry does not currently carry world_px; all runtime map
    # geometry is in the project's canonical 8192-wide Mercator space.
    if world_px <= 0:
        world_px = 8192.0

    capital_hits = [index for index, polygon in enumerate(polygons) if capital is not None and polygon.covers(capital)]
    if capital is not None and len(capital_hits) != 1:
        raise RuntimeError("capital anchor must belong to exactly one microcell")

    cell_ids = ["microcell:2848:%04d" % (index + 1) for index in range(len(polygons))]
    cells: list[dict[str, Any]] = []
    for index, (owner, polygon) in enumerate(owned_cells):
        min_x, min_y, max_x, max_y = polygon.bounds
        centroid = polygon.centroid
        cells.append(
            {
                "id": cell_ids[index],
                "name": "Микроклетка %03d" % (index + 1),
                "province_id": contract["province"]["id"],
                "seed_index": owner,
                "is_capital_microcell": index in capital_hits,
                "area_km2": round(area_km2(polygon, world_px), 4),
                "centroid": [round(centroid.x, 6), round(centroid.y, 6)],
                "bbox": [round(min_x, 6), round(min_y, 6), round(max_x, 6), round(max_y, 6)],
                "rings": rings_from_polygon(polygon),
                "neighbors": [cell_ids[other] for other in neighbor_indices[index]],
            }
        )

    combined = unary_union(polygons)
    source_area = max(province.area, 1e-12)
    missing_ratio = province.difference(combined).area / source_area
    extra_ratio = combined.difference(province).area / source_area
    overlap_ratio = max(0.0, (sum(polygon.area for polygon in polygons) - combined.area) / source_area)
    edge_count = sum(len(neighbors) for neighbors in neighbor_indices) // 2
    if missing_ratio > 1e-8 or extra_ratio > 1e-8 or overlap_ratio > 1e-8:
        raise RuntimeError(
            "microcell coverage invalid: missing=%.3g extra=%.3g overlap=%.3g"
            % (missing_ratio, extra_ratio, overlap_ratio)
        )
    if any(not neighbors for neighbors in neighbor_indices):
        raise RuntimeError("a microcell has no graph neighbour")

    payload = {
        "format": "province_microcell_mesh/v1",
        "stage": {"number": 2, "name": "Микроклеточная сетка"},
        "contract_id": contract["id"],
        "world_px": world_px,
        "province_id": contract["province"]["id"],
        "province_name": contract["province"]["name"],
        "province_rings": rings_from_polygon(province),
        "capital_anchor": contract["province"]["capital_anchor"],
        "generation": {
            "method": "poisson_disk_voronoi_clipped",
            "requested_cell_count": requested_count,
            "result_cell_count": len(cells),
            "minimum_seed_distance_world_px": round(actual_min_distance, 6),
            "deterministic_seed": generation.get("deterministic_seed"),
        },
        "cells": cells,
        "graph": {"edge_count": edge_count},
        "validation": {
            "coverage_complete": True,
            "missing_area_ratio": missing_ratio,
            "extra_area_ratio": extra_ratio,
            "overlap_area_ratio": overlap_ratio,
            "capital_microcell_count": len(capital_hits),
            "all_microcells_have_neighbours": True,
        },
    }
    write_json(output_path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    contract_path = args.contract if args.contract.is_absolute() else ROOT / args.contract
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    try:
        payload = build(contract_path, output_path)
    except (OSError, json.JSONDecodeError, TypeError, KeyError, ValueError, RuntimeError) as exc:
        print("MICROCELL BUILD FAILED: %s" % exc, file=sys.stderr)
        return 1
    print(
        "MICROCELL BUILD OK: %d cells, %d graph edges -> %s"
        % (payload["generation"]["result_cell_count"], payload["graph"]["edge_count"], output_path)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
