#!/usr/bin/env python3
"""Run, validate and publish the assisted Fantasy Admin-2 pipeline.

The actual topology generator lives in ``build_regional_political_claims_cells``.
This module is deliberately its orchestration and QA boundary: it converts the
generator output into a reproducible review queue, a machine-readable report
and an interchange GeoJSON.  It does not silently "repair" invalid geometry.

Typical use from the repository root::

    python scripts/tools/admin2_pipeline.py --all --build

The command is safe to repeat: every result is derived from versioned source
data, regional profiles and explicit generator parameters.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "scripts" / "tools" / "build_regional_political_claims_cells.py"
CELLS_PATH = ROOT / "assets" / "cells_iberia_regional_political_claims.json"
PROVINCE_GEOMETRY_PATH = ROOT / "assets" / "map_geometry" / "provinces.json"
PROVINCE_IDENTITY_PATH = ROOT / "assets" / "game_data" / "provinces.json"
REPORT_PATH = ROOT / "reports" / "admin2_pipeline_iberia.json"
QUEUE_PATH = ROOT / "assets" / "cell_topology" / "admin2_review_queue.json"
GEOJSON_PATH = ROOT / "build_artifacts" / "fantasy_admin2_iberia.geojson"
GPKG_PATH = ROOT / "build_artifacts" / "fantasy_admin2_iberia.gpkg"

AUTO_APPROVE_THRESHOLD = 90.0
REVIEW_THRESHOLD = 75.0
EPSILON = 1e-7


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def polygon_parts(geometry: Any) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [] if geometry.is_empty else [geometry]
    if isinstance(geometry, (MultiPolygon, GeometryCollection)) or hasattr(geometry, "geoms"):
        return [part for part in geometry.geoms if isinstance(part, Polygon) and not part.is_empty]
    return []


def polygon_from_rings(rings: list[list[list[float]]]) -> Polygon | None:
    if not rings or len(rings[0]) < 4:
        return None
    polygon = Polygon(rings[0], rings[1:])
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    parts = polygon_parts(polygon)
    return max(parts, key=lambda part: part.area) if parts else None


def compactness(polygon: Polygon) -> float:
    return 4.0 * math.pi * polygon.area / max(polygon.length**2, EPSILON)


def aspect_ratio(polygon: Polygon) -> float:
    rectangle = polygon.minimum_rotated_rectangle
    coords = list(rectangle.exterior.coords)
    lengths = [math.dist(coords[index], coords[index + 1]) for index in range(4)]
    short = min(length for length in lengths if length > EPSILON)
    return max(lengths) / short


def score_inverse(value: float, good: float, bad: float) -> float:
    """Score 100 at/below ``good``, zero at/above ``bad``."""
    if value <= good:
        return 100.0
    if value >= bad:
        return 0.0
    return 100.0 * (bad - value) / (bad - good)


def score_direct(value: float, bad: float, good: float) -> float:
    """Score zero at/below ``bad``, 100 at/above ``good``."""
    if value <= bad:
        return 0.0
    if value >= good:
        return 100.0
    return 100.0 * (value - bad) / (good - bad)


def shared_neighbours(cells: list[tuple[dict[str, Any], Polygon]]) -> tuple[dict[str, set[str]], list[float]]:
    neighbours = {str(cell["id"]): set() for cell, _geometry in cells}
    border_sinuosities: list[float] = []
    for index, (left, left_geometry) in enumerate(cells):
        for right, right_geometry in cells[index + 1:]:
            shared = left_geometry.boundary.intersection(right_geometry.boundary)
            if shared.length <= EPSILON:
                continue
            left_id, right_id = str(left["id"]), str(right["id"])
            neighbours[left_id].add(right_id)
            neighbours[right_id].add(left_id)
            # A perfect straight border is acceptable, but a map made only of
            # those has the grid/Voronoi look.  The score uses a gentle target.
            endpoints: list[tuple[float, float]] = []
            for line in getattr(shared, "geoms", [shared]):
                coords = list(getattr(line, "coords", []))
                if len(coords) >= 2:
                    endpoints.extend((coords[0], coords[-1]))
            if len(endpoints) >= 2:
                chord = math.dist(endpoints[0], endpoints[-1])
                if chord > EPSILON:
                    border_sinuosities.append(shared.length / chord)
    return neighbours, border_sinuosities


def validate_province(
    province_id: str,
    parent: Polygon,
    cells: list[tuple[dict[str, Any], Polygon]],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not cells:
        return {"province_id": province_id, "status": "NEEDS_REVIEW", "quality": 0.0,
                "errors": ["no generated Admin-2 cells"], "warnings": []}

    geometries = [geometry for _cell, geometry in cells]
    union = unary_union(geometries)
    coverage_error = parent.symmetric_difference(union).area / max(parent.area, EPSILON)
    overlap_area = sum(
        left.intersection(right).area
        for index, left in enumerate(geometries)
        for right in geometries[index + 1:]
    ) / max(parent.area, EPSILON)
    invalid = [str(cell["id"]) for cell, geometry in cells if not geometry.is_valid]
    disconnected = [str(cell["id"]) for cell, geometry in cells if len(polygon_parts(geometry)) != 1]
    enclaves = [
        str(cell["id"]) for cell, geometry in cells
        if geometry.boundary.intersection(parent.boundary).length <= EPSILON
    ]
    if coverage_error > 1e-5:
        errors.append(f"coverage error {coverage_error:.8f}")
    if overlap_area > 1e-6:
        errors.append(f"overlap {overlap_area:.8f}")
    if invalid:
        errors.append("invalid geometry: " + ", ".join(invalid))
    if disconnected:
        errors.append("disconnected cells: " + ", ".join(disconnected))
    if enclaves:
        warnings.append("enclave-like cells: " + ", ".join(enclaves))

    areas = [geometry.area for geometry in geometries]
    mean_area = sum(areas) / len(areas)
    area_cv = math.sqrt(sum((area - mean_area) ** 2 for area in areas) / len(areas)) / max(mean_area, EPSILON)
    smallest_ratio = min(areas) / max(mean_area, EPSILON)
    compacts = [compactness(geometry) for geometry in geometries]
    aspects = [aspect_ratio(geometry) for geometry in geometries]
    neighbours, sinuosity = shared_neighbours(cells)
    degrees = [len(value) for value in neighbours.values()]

    geometry_score = 100.0 if not errors else 0.0
    connectivity_score = 100.0 if not disconnected else 0.0
    area_score = min(score_inverse(area_cv, 0.20, 0.90), score_direct(smallest_ratio, 0.15, 0.55))
    shape_score = min(
        score_direct(min(compacts), 0.045, 0.20),
        score_inverse(max(aspects), 2.5, 12.0),
    )
    topology_score = min(score_inverse(max(degrees, default=0), 4.5, 8.0), score_inverse(sum(degrees) / max(len(degrees), 1), 3.8, 6.0))
    mean_sinuosity = sum(sinuosity) / len(sinuosity) if sinuosity else 1.0
    style_score = score_inverse(abs(mean_sinuosity - 1.07), 0.0, 0.12)
    if enclaves:
        style_score = min(style_score, 55.0)
    quality = (
        geometry_score * 0.25 + connectivity_score * 0.20 + area_score * 0.15
        + shape_score * 0.20 + topology_score * 0.10 + style_score * 0.10
    )
    if errors:
        quality = min(quality, 49.0)
    status = "AUTO_APPROVED" if quality >= AUTO_APPROVE_THRESHOLD else (
        "NEEDS_REVIEW" if quality < REVIEW_THRESHOLD or errors else "ACCEPTED"
    )
    return {
        "province_id": province_id,
        "cell_count": len(cells),
        "status": status,
        "quality": round(quality, 2),
        "scores": {
            "geometry": round(geometry_score, 2), "connectivity": round(connectivity_score, 2),
            "area_balance": round(area_score, 2), "shape": round(shape_score, 2),
            "topology": round(topology_score, 2), "style": round(style_score, 2),
        },
        "metrics": {
            "coverage_error": coverage_error, "overlap_ratio": overlap_area,
            "area_cv": round(area_cv, 4), "smallest_area_to_mean": round(smallest_ratio, 4),
            "min_compactness": round(min(compacts), 4), "max_aspect_ratio": round(max(aspects), 4),
            "max_neighbours": max(degrees, default=0), "mean_neighbours": round(sum(degrees) / max(len(degrees), 1), 3),
            "mean_border_sinuosity": round(mean_sinuosity, 4),
        },
        "errors": errors,
        "warnings": warnings,
    }


def export_geojson(cells: list[dict[str, Any]], output_path: Path = GEOJSON_PATH) -> list[dict[str, Any]]:
    features = []
    for cell in cells:
        geometry = polygon_from_rings(cell.get("rings", []))
        if geometry is None:
            continue
        properties = {key: value for key, value in cell.items() if key not in {"rings", "brd_open", "color"}}
        features.append({"type": "Feature", "geometry": mapping(geometry), "properties": properties})
    write_json(output_path, {"type": "FeatureCollection", "features": features})
    return features


def export_geopackage(features: list[dict[str, Any]]) -> None:
    """Write the GIS working copy when the optional GeoPandas stack exists."""
    try:
        import geopandas as gpd
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "GeoPackage export requires geopandas; install requirements_land_cells_v2.txt first"
        ) from error
    rows = []
    for feature in features:
        properties = {
            key: value if isinstance(value, (str, int, float, bool)) or value is None
            else json.dumps(value, ensure_ascii=False)
            for key, value in feature["properties"].items()
        }
        rows.append({**properties, "geometry": shape(feature["geometry"])})
    # GeoPandas accepts GeoJSON geometry mappings.  Keep the map's internal
    # pixel coordinate system deliberately unlabelled instead of claiming an
    # incorrect geographic CRS.
    frame = gpd.GeoDataFrame(rows, geometry="geometry")
    GPKG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if GPKG_PATH.exists():
        GPKG_PATH.unlink()
    frame.to_file(GPKG_PATH, layer="fantasy_admin2", driver="GPKG")


def build_generator(all_provinces: bool) -> None:
    command = [sys.executable, str(GENERATOR)]
    if all_provinces:
        command.append("--all")
    subprocess.run(command, cwd=ROOT, check=True)


def run(
    *,
    all_provinces: bool,
    rebuild: bool,
    geopackage: bool,
    cells_path: Path = CELLS_PATH,
    report_path: Path = REPORT_PATH,
    queue_path: Path = QUEUE_PATH,
    geojson_path: Path = GEOJSON_PATH,
) -> dict[str, Any]:
    if rebuild:
        build_generator(all_provinces)
    cell_document = read_json(cells_path)
    geometry_by_legacy = {
        str(item.get("legacy_id", "")): polygon_from_rings(item.get("rings", []))
        for item in read_json(PROVINCE_GEOMETRY_PATH).get("provinces", [])
    }
    parents = {
        str(item["id"]): geometry_by_legacy.get(str(item.get("legacy_id", "")))
        for item in read_json(PROVINCE_IDENTITY_PATH).get("provinces", [])
    }
    groups: dict[str, list[tuple[dict[str, Any], Polygon]]] = defaultdict(list)
    for cell in cell_document.get("cells", []):
        geometry = polygon_from_rings(cell.get("rings", []))
        if geometry is not None:
            groups[str(cell["province_id"])].append((cell, geometry))

    reports = []
    for province_id, cells in sorted(groups.items()):
        parent = parents.get(province_id)
        if parent is None:
            reports.append({"province_id": province_id, "status": "NEEDS_REVIEW", "quality": 0.0,
                            "errors": ["parent Admin-1 geometry not found"], "warnings": []})
            continue
        reports.append(validate_province(province_id, parent, cells))
    reports.sort(key=lambda item: (item["status"] != "NEEDS_REVIEW", item["quality"], item["province_id"]))
    counts = {status: sum(item["status"] == status for item in reports) for status in ("AUTO_APPROVED", "ACCEPTED", "NEEDS_REVIEW")}
    queue = [item for item in reports if item["status"] == "NEEDS_REVIEW"]
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "schema_version": 1,
        "created_at": timestamp,
        "source_cells": str(cells_path.relative_to(ROOT)).replace("\\", "/"),
        "thresholds": {"auto_approved": AUTO_APPROVE_THRESHOLD, "needs_review_below": REVIEW_THRESHOLD},
        "summary": {"province_count": len(reports), "cell_count": len(cell_document.get("cells", [])), **counts},
        "provinces": reports,
    }
    write_json(report_path, payload)
    write_json(queue_path, {"schema_version": 1, "created_at": timestamp, "count": len(queue), "queue": queue})
    features = export_geojson(cell_document.get("cells", []), geojson_path)
    if geopackage:
        export_geopackage(features)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and validate assisted Fantasy Admin-2 data.")
    parser.add_argument("--all", action="store_true", help="generate every currently available Iberian Admin-1")
    parser.add_argument("--build", action="store_true", help="run the generator before validation")
    parser.add_argument("--geopackage", action="store_true", help="also write the optional GeoPackage working copy")
    parser.add_argument("--cells", type=Path, help="validate this cells JSON instead of the default Political Claims layer")
    args = parser.parse_args()
    cells_path = (ROOT / args.cells).resolve() if args.cells and not args.cells.is_absolute() else args.cells
    if cells_path is None:
        cells_path = CELLS_PATH
    if args.build and cells_path != CELLS_PATH:
        parser.error("--build only writes the default Political Claims layer; validate candidates without --build")
    suffix = "" if cells_path == CELLS_PATH else "_" + cells_path.stem
    report_path = REPORT_PATH.with_name("admin2_pipeline_iberia%s.json" % suffix)
    queue_path = QUEUE_PATH.with_name("admin2_review_queue%s.json" % suffix)
    geojson_path = GEOJSON_PATH.with_name("fantasy_admin2%s.geojson" % suffix)
    report = run(
        all_provinces=args.all,
        rebuild=args.build,
        geopackage=args.geopackage,
        cells_path=cells_path,
        report_path=report_path,
        queue_path=queue_path,
        geojson_path=geojson_path,
    )
    summary = report["summary"]
    print(
        "Admin-2 pipeline: %(province_count)d Admin-1, %(cell_count)d Admin-2; "
        "%(AUTO_APPROVED)d auto-approved, %(ACCEPTED)d accepted, %(NEEDS_REVIEW)d need review" % summary
    )
    print(f"report: {report_path.relative_to(ROOT)}")
    print(f"review queue: {queue_path.relative_to(ROOT)}")
    print(f"GeoJSON: {geojson_path.relative_to(ROOT)}")
    if args.geopackage:
        print(f"GeoPackage: {GPKG_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
