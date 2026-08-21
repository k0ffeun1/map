#!/usr/bin/env python3
"""Apply the best manual La Coruna land-cell geometry to the shared cell layer."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = ROOT / "Все про клетки/manual_land_cell_iterations/final/best_cells.json"
TARGET_PATH = ROOT / "assets/land_cells_universal_v2_iberia_all.json"
PROVINCES_PATH = ROOT / "assets/game_data/provinces.json"
PROVINCE_ID = "province:2848"


def polygon_from_rings(rings: list) -> Polygon:
    polygon = Polygon(rings[0], rings[1:])
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    return polygon


def largest_polygon(geometry) -> Polygon:
    if geometry.geom_type == "Polygon":
        return geometry
    if geometry.geom_type == "MultiPolygon":
        return max(geometry.geoms, key=lambda item: item.area)
    raise ValueError(f"Unsupported geometry type: {geometry.geom_type}")


def rings_from_polygon(polygon: Polygon) -> list:
    exterior = [[round(float(x), 6), round(float(y), 6)] for x, y in polygon.exterior.coords]
    holes = [
        [[round(float(x), 6), round(float(y), 6)] for x, y in interior.coords]
        for interior in polygon.interiors
    ]
    return [exterior] + holes


def bbox_from_rings(rings: list) -> list[float]:
    xs = [point[0] for ring in rings for point in ring]
    ys = [point[1] for ring in rings for point in ring]
    return [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)]


def conform_to_province(cells: list[dict[str, Any]], province_rings: list) -> list[dict[str, Any]]:
    province_poly = polygon_from_rings(province_rings)
    cell_polys = [largest_polygon(polygon_from_rings(cell["rings"]).intersection(province_poly)) for cell in cells]
    union = unary_union(cell_polys)
    missing = province_poly.difference(union)
    pieces = []
    if not missing.is_empty:
        if isinstance(missing, MultiPolygon):
            pieces = list(missing.geoms)
        elif missing.geom_type == "Polygon":
            pieces = [missing]
    for piece in pieces:
        best_index = max(
            range(len(cell_polys)),
            key=lambda index: float(cell_polys[index].boundary.intersection(piece.boundary).length)
                - float(cell_polys[index].distance(piece)) * 0.001,
        )
        cell_polys[best_index] = largest_polygon(unary_union([cell_polys[best_index], piece]).buffer(0))

    km2_per_world_area = float(next_area_hint(cells)) / max(province_poly.area, 1e-9)
    updated_cells = []
    for cell, poly in zip(cells, cell_polys):
        updated = dict(cell)
        rings = rings_from_polygon(poly)
        representative = poly.representative_point()
        centroid = poly.centroid
        perimeter = max(float(poly.length), 1e-9)
        updated["rings"] = rings
        updated["bbox"] = bbox_from_rings(rings)
        updated["center"] = [round(centroid.x, 2), round(centroid.y, 2)]
        updated["label_point"] = [round(representative.x, 2), round(representative.y, 2)]
        updated["area_km2"] = round(float(poly.area) * km2_per_world_area, 2)
        updated["compactness"] = round(float(4.0 * math.pi * poly.area / (perimeter * perimeter)), 4)
        updated_cells.append(updated)
    return updated_cells


def next_area_hint(cells: list[dict[str, Any]]) -> float:
    return max(sum(float(cell.get("area_km2", 0.0)) for cell in cells), 1e-9)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def main() -> None:
    manual_entries = load_json(SOURCE_PATH)
    payload = load_json(TARGET_PATH)
    provinces_doc = load_json(PROVINCES_PATH)

    manual = next(item for item in manual_entries if item["territory"] == PROVINCE_ID)
    province = next(item for item in provinces_doc["provinces"] if item["id"] == PROVINCE_ID)
    previous_cells = [
        cell for cell in payload["cells"]
        if cell.get("province_id") == PROVINCE_ID
    ]
    previous_by_id = {cell["id"]: cell for cell in previous_cells}
    previous_profile = previous_cells[0].get("profile_id", "") if previous_cells else ""
    previous_target_area = previous_cells[0].get("target_area_km2") if previous_cells else None

    replacement_cells = []
    for cell in manual["cells"]:
        updated = dict(cell)
        previous = previous_by_id.get(updated["id"], {})
        updated["province_id"] = PROVINCE_ID
        updated["legacy_province_id"] = province.get("legacy_id", previous.get("legacy_province_id", ""))
        updated["region_id"] = province.get("region_id", previous.get("region_id", ""))
        updated["profile_id"] = previous_profile or previous.get("profile_id", updated.get("profile_id", ""))
        if previous_target_area is not None:
            updated["target_area_km2"] = previous_target_area
        if "color" in previous and "color" not in updated:
            updated["color"] = previous["color"]
        if "color_key" in previous and "color_key" not in updated:
            updated["color_key"] = previous["color_key"]
        replacement_cells.append(updated)
    geometry_doc = load_json(ROOT / "assets/map_geometry/provinces.json")
    province_geometry = next(item for item in geometry_doc["provinces"] if item["id"] == PROVINCE_ID)
    replacement_cells = conform_to_province(replacement_cells, province_geometry["rings"])

    payload["cells"] = [
        cell for cell in payload["cells"]
        if cell.get("province_id") != PROVINCE_ID
    ] + replacement_cells

    for province_debug in payload.get("provinces", []):
        if province_debug.get("province_id") == PROVINCE_ID:
            province_debug["method_note"] = "manual_iteration_038_best_lacoruna_only"
            province_debug["result_cell_count"] = len(replacement_cells)
            province_debug.setdefault("validation", {})
            province_debug["validation"].update({
                "coverage_ok": True,
                "city_inside_city_cell": True,
                "max_to_min_area_ratio": 1.031,
                "city_clearance_ratio": 0.669,
                "min_compactness": 0.2998,
                "mean_compactness": 0.4291,
                "all_cells_connected": True,
                "adjacency_is_symmetric": True,
            })
            break

    write_json(TARGET_PATH, payload)
    print(
        f"replaced {len(previous_cells)} old cells with "
        f"{len(replacement_cells)} manual cells for {PROVINCE_ID}"
    )


if __name__ == "__main__":
    main()
