#!/usr/bin/env python3
"""
Рассчитывает точную геодезическую площадь финальных провинций,
записывает area_km2 в assets/map_geometry/provinces.json
и создаёт отчёт reports/province_area_report.csv.

Запуск из корня репозитория:

    python scripts/tools/build_province_area_report.py
    python scripts/tools/build_province_area_report.py --write-geometry

Требуется:
    pip install pyproj
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

from pyproj import Geod

ROOT = Path(__file__).resolve().parents[2]
GEOMETRY_PATH = ROOT / "assets/map_geometry/provinces.json"
PASSPORT_PATH = ROOT / "assets/game_data/provinces.json"
REGIONS_PATH = ROOT / "assets/game_data/regions.json"
REPORT_DIR = ROOT / "reports"
CSV_PATH = REPORT_DIR / "province_area_report.csv"
SUMMARY_PATH = REPORT_DIR / "province_area_summary.json"

GEOD = Geod(ellps="WGS84")


def world_px_to_lonlat(x: float, y: float, world_px: float) -> tuple[float, float]:
    lon = x / world_px * 360.0 - 180.0
    n = math.pi - 2.0 * math.pi * y / world_px
    lat = math.degrees(math.atan(math.sinh(n)))
    return lon, lat


def ring_area_km2(ring: list[list[float]], world_px: float) -> float:
    if len(ring) < 4:
        return 0.0

    lon: list[float] = []
    lat: list[float] = []
    for x, y in ring:
        lo, la = world_px_to_lonlat(float(x), float(y), world_px)
        lon.append(lo)
        lat.append(la)

    # pyproj.Geod возвращает знаковую площадь в м².
    area_m2, _ = GEOD.polygon_area_perimeter(lon, lat)
    return abs(area_m2) / 1_000_000.0


def province_area_km2(rings: list[list[list[float]]], world_px: float) -> float:
    if not rings:
        return 0.0

    area = ring_area_km2(rings[0], world_px)
    for hole in rings[1:]:
        area -= ring_area_km2(hole, world_px)
    return max(0.0, area)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Не найден файл: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write-geometry",
        action="store_true",
        help="Перезаписать assets/map_geometry/provinces.json с полем area_km2",
    )
    args = parser.parse_args()

    geometry_doc = load_json(GEOMETRY_PATH)
    passport_doc = load_json(PASSPORT_PATH)
    regions_doc = load_json(REGIONS_PATH)

    world_px = float(geometry_doc.get("world_px", 8192.0))
    geometries = geometry_doc.get("provinces", [])
    passports = {
        item["id"]: item
        for item in passport_doc.get("provinces", [])
        if item.get("id")
    }
    regions = {
        item["id"]: item
        for item in regions_doc.get("regions", [])
        if item.get("id")
    }

    rows: list[dict[str, Any]] = []
    areas: list[float] = []
    missing_passports: list[str] = []
    unassigned_regions: list[str] = []

    for geom in geometries:
        province_id = geom.get("id", "")
        area = round(province_area_km2(geom.get("rings", []), world_px), 3)
        geom["area_km2"] = area
        areas.append(area)

        passport = passports.get(province_id)
        if passport is None:
            missing_passports.append(province_id)
            passport = {}

        region_id = passport.get("region_id", "")
        region = regions.get(region_id, {})
        if not region_id:
            unassigned_regions.append(province_id)

        generation = region.get("land_cell_generation", {})
        target = generation.get("target_cell_area_km2")
        min_cells = generation.get("min_cells_per_province", 1)
        max_cells = generation.get("max_cells_per_province")

        expected = ""
        if isinstance(target, (int, float)) and target > 0:
            expected_num = max(int(min_cells or 1), round(area / float(target)))
            if isinstance(max_cells, int):
                expected_num = min(expected_num, max_cells)
            expected = expected_num

        rows.append({
            "province_id": province_id,
            "legacy_id": passport.get("legacy_id", geom.get("legacy_id", "")),
            "numeric_id": passport.get("numeric_id", geom.get("numeric_id", "")),
            "name": passport.get("name", geom.get("name", "")),
            "region_id": region_id,
            "macroregion_id": passport.get("macroregion_id", ""),
            "area_km2": area,
            "profile_id": generation.get("profile_id", ""),
            "target_cell_area_km2": target or "",
            "expected_cell_count_base": expected,
            "status": (
                "MISSING_PASSPORT" if not passport
                else "UNASSIGNED_REGION" if not region_id
                else "REGION_WITHOUT_CELL_PROFILE" if not target
                else "OK"
            ),
        })

    rows.sort(key=lambda row: float(row["area_km2"]), reverse=True)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    fields = [
        "province_id",
        "legacy_id",
        "numeric_id",
        "name",
        "region_id",
        "macroregion_id",
        "area_km2",
        "profile_id",
        "target_cell_area_km2",
        "expected_cell_count_base",
        "status",
    ]
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    positive = sorted(area for area in areas if area > 0)
    summary = {
        "schema_version": 1,
        "province_count": len(geometries),
        "passport_count": len(passports),
        "region_count": len(regions),
        "world_px": world_px,
        "total_area_km2": round(sum(positive), 3),
        "min_area_km2": round(positive[0], 3) if positive else 0,
        "median_area_km2": round(median(positive), 3) if positive else 0,
        "max_area_km2": round(positive[-1], 3) if positive else 0,
        "missing_passport_count": len(missing_passports),
        "unassigned_region_count": len(unassigned_regions),
        "csv_path": str(CSV_PATH.relative_to(ROOT)),
    }
    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if args.write_geometry:
        # Атомарная запись, чтобы не повредить основной JSON при прерывании.
        temp_path = GEOMETRY_PATH.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(geometry_doc, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temp_path.replace(GEOMETRY_PATH)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"CSV: {CSV_PATH}")
    if args.write_geometry:
        print(f"Обновлён geometry-файл: {GEOMETRY_PATH}")
    else:
        print("Geometry-файл не изменён. Для записи используйте --write-geometry.")


if __name__ == "__main__":
    main()
