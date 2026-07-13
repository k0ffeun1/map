#!/usr/bin/env python3
"""Build geodesic province-area data for the separated map architecture.

The script reads final province geometry from assets/map_geometry/provinces.json,
calculates WGS84 geodesic area in square kilometers, writes CSV/JSON reports,
and can optionally persist area_km2 back into the geometry file.
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
PROVINCE_CELL_OVERRIDES_PATH = ROOT / "assets/game_data/province_cell_generation_overrides.json"
REPORT_DIR = ROOT / "reports"
CSV_PATH = REPORT_DIR / "province_area_report.csv"
REGION_CSV_PATH = REPORT_DIR / "region_cell_rules_report.csv"
SUMMARY_PATH = REPORT_DIR / "province_area_summary.json"

GEOD = Geod(ellps="WGS84")


def load_json(path: Path) -> dict[str, Any]:
	if not path.exists():
		raise FileNotFoundError(f"Не найден файл: {path}")
	return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any, *, compact: bool = True) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", encoding="utf-8", newline="\n") as file:
		if compact:
			json.dump(data, file, ensure_ascii=False, separators=(",", ":"))
		else:
			json.dump(data, file, ensure_ascii=False, indent=2)
		file.write("\n")


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
	area_m2, _ = GEOD.polygon_area_perimeter(lon, lat)
	return abs(area_m2) / 1_000_000.0


def province_area_km2(rings: list[list[list[float]]], world_px: float) -> float:
	if not rings:
		return 0.0
	area = ring_area_km2(rings[0], world_px)
	for hole in rings[1:]:
		area -= ring_area_km2(hole, world_px)
	return max(0.0, area)


def round_half_up(value: float) -> int:
	return int(math.floor(value + 0.5))


def expected_cell_count(area: float, generation: dict[str, Any]) -> int | str:
	target = generation.get("target_cell_area_km2")
	if not isinstance(target, (int, float)) or target <= 0:
		return ""
	min_cells = generation.get("min_cells_per_province", 1)
	max_cells = generation.get("max_cells_per_province")
	count = max(int(min_cells or 1), round_half_up(area / float(target)))
	if isinstance(max_cells, int):
		count = min(count, max_cells)
	return count


def load_province_cell_overrides() -> dict[str, dict[str, Any]]:
	if not PROVINCE_CELL_OVERRIDES_PATH.exists():
		return {}
	data = load_json(PROVINCE_CELL_OVERRIDES_PATH)
	return {
		str(item["province_id"]): item
		for item in data.get("overrides", [])
		if item.get("province_id")
	}


def apply_override(base_count: int | str, override: dict[str, Any]) -> int | str:
	if not isinstance(base_count, int):
		return base_count
	forced = override.get("forced_cell_count")
	if isinstance(forced, int):
		return forced
	minimum = override.get("minimum_cell_count")
	if isinstance(minimum, int):
		return max(base_count, minimum)
	return base_count


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument(
		"--write-geometry",
		action="store_true",
		help="Записать area_km2 обратно в assets/map_geometry/provinces.json",
	)
	args = parser.parse_args()

	geometry_doc = load_json(GEOMETRY_PATH)
	passport_doc = load_json(PASSPORT_PATH)
	regions_doc = load_json(REGIONS_PATH)
	province_cell_overrides = load_province_cell_overrides()

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
	region_rows: dict[str, dict[str, Any]] = {}
	areas: list[float] = []
	missing_passports: list[str] = []
	unassigned_regions: list[str] = []
	regions_without_profiles: list[str] = []

	for geom in geometries:
		province_id = str(geom.get("id", ""))
		area = round(province_area_km2(geom.get("rings", []), world_px), 3)
		geom["area_km2"] = area
		areas.append(area)

		passport = passports.get(province_id)
		if passport is None:
			missing_passports.append(province_id)
			passport = {}

		region_id = str(passport.get("region_id", ""))
		if not region_id:
			unassigned_regions.append(province_id)
		region = regions.get(region_id, {})
		generation = region.get("land_cell_generation", {})
		if region_id and not generation:
			regions_without_profiles.append(region_id)
		expected = expected_cell_count(area, generation)
		override = province_cell_overrides.get(province_id, {})
		final_count = apply_override(expected, override)

		rows.append({
			"province_id": province_id,
			"legacy_id": passport.get("legacy_id", geom.get("legacy_id", "")),
			"numeric_id": passport.get("numeric_id", geom.get("numeric_id", "")),
			"name": passport.get("name", geom.get("name", "")),
			"region_id": region_id,
			"macroregion_id": passport.get("macroregion_id", ""),
			"area_km2": area,
			"profile_id": generation.get("profile_id", ""),
			"target_cell_area_km2": generation.get("target_cell_area_km2", ""),
			"expected_cell_count_base": expected,
			"override_minimum_cell_count": override.get("minimum_cell_count", ""),
			"override_forced_cell_count": override.get("forced_cell_count", ""),
			"override_reason": override.get("reason", ""),
			"final_cell_count_base": final_count,
			"status": (
				"MISSING_PASSPORT" if not passport
				else "UNASSIGNED_REGION" if not region_id
				else "REGION_WITHOUT_CELL_PROFILE" if not generation
				else "OK"
			),
		})

		if region_id and generation:
			region_row = region_rows.setdefault(
				region_id,
				{
					"region_id": region_id,
					"macroregion_id": region.get("macroregion_id", ""),
					"name": region.get("name", ""),
					"display_name_ru": region.get("display_name_ru", ""),
					"profile_id": generation.get("profile_id", ""),
					"target_cell_area_km2": generation.get("target_cell_area_km2", ""),
					"min_cells_per_province": generation.get("min_cells_per_province", ""),
					"max_cells_per_province": generation.get("max_cells_per_province", ""),
					"province_count": 0,
					"total_area_km2": 0.0,
					"expected_cell_count_base": 0,
					"final_cell_count_base": 0,
					"override_count": 0,
				},
			)
			region_row["province_count"] += 1
			region_row["total_area_km2"] += area
			if isinstance(expected, int):
				region_row["expected_cell_count_base"] += expected
			if isinstance(final_count, int):
				region_row["final_cell_count_base"] += final_count
			if override:
				region_row["override_count"] += 1

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
		"override_minimum_cell_count",
		"override_forced_cell_count",
		"override_reason",
		"final_cell_count_base",
		"status",
	]
	with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as file:
		writer = csv.DictWriter(file, fieldnames=fields)
		writer.writeheader()
		writer.writerows(rows)

	region_fields = [
		"region_id",
		"macroregion_id",
		"name",
		"display_name_ru",
		"profile_id",
		"target_cell_area_km2",
		"min_cells_per_province",
		"max_cells_per_province",
		"province_count",
		"total_area_km2",
		"expected_cell_count_base",
		"final_cell_count_base",
		"override_count",
	]
	region_output = sorted(region_rows.values(), key=lambda row: str(row["region_id"]))
	for row in region_output:
		row["total_area_km2"] = round(float(row["total_area_km2"]), 3)
	with REGION_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as file:
		writer = csv.DictWriter(file, fieldnames=region_fields)
		writer.writeheader()
		writer.writerows(region_output)

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
		"regions_without_profiles_count": len(set(regions_without_profiles)),
		"ok_count": sum(1 for row in rows if row["status"] == "OK"),
		"province_cell_override_count": len(province_cell_overrides),
		"final_cell_count_base_ok": sum(
			int(row["final_cell_count_base"])
			for row in rows
			if row["status"] == "OK" and isinstance(row["final_cell_count_base"], int)
		),
		"csv_path": str(CSV_PATH.relative_to(ROOT)),
		"region_csv_path": str(REGION_CSV_PATH.relative_to(ROOT)),
	}
	write_json(SUMMARY_PATH, summary, compact=False)

	if args.write_geometry:
		temp_path = GEOMETRY_PATH.with_suffix(".json.tmp")
		write_json(temp_path, geometry_doc)
		temp_path.replace(GEOMETRY_PATH)

	print(json.dumps(summary, ensure_ascii=False, indent=2))
	print(f"CSV: {CSV_PATH}")
	print(f"Region CSV: {REGION_CSV_PATH}")
	if args.write_geometry:
		print(f"Обновлён geometry-файл: {GEOMETRY_PATH}")
	else:
		print("Geometry-файл не изменён. Для записи используйте --write-geometry.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
