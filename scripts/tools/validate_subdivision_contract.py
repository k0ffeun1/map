#!/usr/bin/env python3
"""Validate the fixed rules for a province-subdivision pilot.

Stage 1 deliberately validates only the contract and its real geographic
inputs.  Passing ``--cells`` additionally checks a generated candidate before
it is shown as the next visual stage.  The script is independent from a
specific generator, so future microcell/graph implementations share one
acceptance gate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from shapely.geometry import Point, Polygon
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "assets" / "game_data" / "subdivision_contracts" / "lacoruna.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_project_path(raw: str) -> Path:
    if raw.startswith("res://"):
        return ROOT / raw.removeprefix("res://")
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def polygon_from_entry(entry: dict[str, Any]) -> Polygon:
    rings = entry.get("rings", [])
    if not rings or len(rings[0]) < 3:
        raise ValueError("entry has no usable rings")
    polygon = Polygon(rings[0], rings[1:])
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.is_empty:
        raise ValueError("entry has empty geometry")
    if polygon.geom_type != "Polygon":
        # A generated candidate cannot be a disconnected multipolygon under
        # the stage-1 connectivity contract.
        raise ValueError("entry is disconnected or not a polygon")
    return polygon


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def validate_contract(contract: dict[str, Any]) -> tuple[list[str], dict[str, Any], Polygon]:
    errors: list[str] = []
    if contract.get("format") != "province_subdivision_contract/v1":
        fail(errors, "unsupported contract format")

    province = contract.get("province")
    generation = contract.get("generation")
    constraints = contract.get("constraints")
    if not isinstance(province, dict) or not isinstance(generation, dict) or not isinstance(constraints, dict):
        fail(errors, "province, generation, and constraints must be objects")
        return errors, {}, Polygon()

    target_count = generation.get("target_cell_count")
    target_area = generation.get("target_cell_area_km2")
    if not isinstance(target_count, int) or target_count < 1:
        fail(errors, "generation.target_cell_count must be a positive integer")
    if not isinstance(target_area, (int, float)) or target_area <= 0:
        fail(errors, "generation.target_cell_area_km2 must be positive")

    limits = constraints.get("area_ratio_limits")
    if not isinstance(limits, list) or len(limits) != 2 or not all(isinstance(value, (int, float)) for value in limits):
        fail(errors, "constraints.area_ratio_limits must contain two numbers")
    elif not (0 < limits[0] <= limits[1]):
        fail(errors, "constraints.area_ratio_limits must be ordered positive values")

    capital = province.get("capital_anchor")
    point = capital.get("point") if isinstance(capital, dict) else None
    if not isinstance(point, list) or len(point) != 2 or not all(isinstance(value, (int, float)) for value in point):
        fail(errors, "province.capital_anchor.point must be [x, y]")

    source = resolve_project_path(str(province.get("geometry_path", "")))
    if not source.is_file():
        fail(errors, f"province geometry source does not exist: {source}")
        return errors, province, Polygon()
    data = load_json(source)
    entry = next((item for item in data.get("provinces", []) if item.get("id") == province.get("id")), None)
    if entry is None:
        fail(errors, f"province {province.get('id')} not found in {source}")
        return errors, province, Polygon()
    try:
        polygon = polygon_from_entry(entry)
    except ValueError as exc:
        fail(errors, f"province geometry invalid: {exc}")
        return errors, province, Polygon()
    if isinstance(point, list) and len(point) == 2 and not polygon.covers(Point(point)):
        fail(errors, "capital anchor lies outside the source province")
    return errors, province, polygon


def validate_candidate(contract: dict[str, Any], province: dict[str, Any], source_polygon: Polygon, cells_path: Path) -> list[str]:
    errors: list[str] = []
    cells_data = load_json(cells_path)
    cells = [cell for cell in cells_data.get("cells", []) if cell.get("province_id") == province["id"]]
    generation: dict[str, Any] = contract["generation"]
    constraints: dict[str, Any] = contract["constraints"]
    target_count = generation["target_cell_count"]
    if len(cells) != target_count:
        fail(errors, f"expected {target_count} cells, got {len(cells)}")

    limits = constraints["area_ratio_limits"]
    target_area = float(generation["target_cell_area_km2"])
    polygons: list[tuple[str, Polygon]] = []
    capital = Point(province["capital_anchor"]["point"])
    capital_hits = 0
    for cell in cells:
        cell_id = str(cell.get("id", "<unnamed>"))
        if cell.get("province_id") != province["id"]:
            fail(errors, f"{cell_id}: belongs to another province")
        try:
            polygon = polygon_from_entry(cell)
        except ValueError as exc:
            fail(errors, f"{cell_id}: {exc}")
            continue
        # Sources and exports are rounded independently.  A strict geometric
        # ``covers`` here would reject the selected V2 baseline for
        # sub-pixel slivers (about 1e-10 of the province), despite zero
        # meaningful spill.  The contract's explicit area tolerance below is
        # the authoritative, scale-independent test.
        outside_ratio = polygon.difference(source_polygon).area / max(source_polygon.area, 1e-12)
        maximum_spill = float(constraints.get("topology", {}).get("maximum_overlap_area_ratio", 0.0))
        if outside_ratio > maximum_spill:
            fail(errors, f"{cell_id}: extends {outside_ratio:.8%} outside the source province")
        declared_area = cell.get("area_km2")
        if not isinstance(declared_area, (int, float)):
            fail(errors, f"{cell_id}: has no numeric area_km2")
        elif not limits[0] * target_area <= float(declared_area) <= limits[1] * target_area:
            fail(errors, f"{cell_id}: area {declared_area:.2f} km² is outside contract limits")
        if polygon.covers(capital):
            capital_hits += 1
        polygons.append((cell_id, polygon))

    if province["capital_anchor"].get("must_be_inside_exactly_one_cell", False) and capital_hits != 1:
        fail(errors, f"capital anchor must occur in exactly one cell, got {capital_hits}")

    for index, (cell_id, polygon) in enumerate(polygons):
        neighbors = 0
        for other_id, other in polygons[index + 1:]:
            intersection = polygon.intersection(other)
            if intersection.area > 1e-7:
                fail(errors, f"{cell_id} overlaps {other_id}")
            if polygon.boundary.intersection(other.boundary).length > 1e-6:
                neighbors += 1
        if constraints.get("topology", {}).get("minimum_neighbors_per_cell", 0) > 0:
            # Count adjacency from both directions in a separate loop so the
            # first candidate cannot accidentally escape checking.
            neighbors = sum(
                1 for other_id, other in polygons
                if other_id != cell_id and polygon.boundary.intersection(other.boundary).length > 1e-6
            )
            if neighbors < constraints["topology"]["minimum_neighbors_per_cell"]:
                fail(errors, f"{cell_id}: has only {neighbors} neighbours")

    topology = constraints.get("topology", {})
    if polygons and topology.get("full_province_coverage_required", False):
        combined = unary_union([polygon for _, polygon in polygons])
        source_area = max(source_polygon.area, 1e-12)
        missing_ratio = source_polygon.difference(combined).area / source_area
        extra_ratio = combined.difference(source_polygon).area / source_area
        maximum_missing = float(topology.get("maximum_uncovered_area_ratio", 0.0))
        maximum_overlap = float(topology.get("maximum_overlap_area_ratio", 0.0))
        if missing_ratio > maximum_missing:
            fail(errors, f"candidate leaves {missing_ratio:.8%} of province uncovered")
        if extra_ratio > maximum_overlap:
            fail(errors, f"candidate extends {extra_ratio:.8%} outside province")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--cells", type=Path, help="Optional generated cell JSON to validate against the contract")
    args = parser.parse_args()

    contract_path = args.contract if args.contract.is_absolute() else ROOT / args.contract
    try:
        contract = load_json(contract_path)
        errors, province, source_polygon = validate_contract(contract)
        if not errors and args.cells:
            cells_path = args.cells if args.cells.is_absolute() else ROOT / args.cells
            if not cells_path.is_file():
                errors.append(f"candidate cells do not exist: {cells_path}")
            else:
                errors.extend(validate_candidate(contract, province, source_polygon, cells_path))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        errors = [str(exc)]

    if errors:
        print("CONTRACT INVALID")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"CONTRACT OK: {contract['id']}")
    if args.cells:
        print(f"CANDIDATE OK: {args.cells}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
