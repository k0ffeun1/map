"""Build the first city-first land-cell geometry benchmark: La Coruna.

This follows the geometry plan's first practical stage:
- do not mass-generate Iberia;
- build the city cell first;
- then split the remaining province into west coastal, south interior, east interior;
- keep shared edges from real polygon operations, not per-cell smoothing.
"""
import json
import math
from pathlib import Path

from shapely.affinity import scale
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import split as shapely_split
from shapely.ops import unary_union

import build_cells_test as cell_tools


ROOT = Path(__file__).resolve().parents[2]
GEOMETRY_PATH = ROOT / "assets" / "map_geometry" / "provinces.json"
PROVINCES_PATH = ROOT / "assets" / "game_data" / "provinces.json"
CITIES_PATH = ROOT / "assets" / "province_cities_iberia.json"
OUT_PATH = ROOT / "assets" / "lacoruna_city_first_cells_preview.json"

PROVINCE_ID = "province:2848"
WORLD_PX = 8192.0
TARGET_AREA_KM2 = 2100.0
CITY_PROTECTION_RATIO = 0.32

_WORLD_OCEAN_CACHE = None
_ORIGINAL_LOAD_WORLD_OCEAN = cell_tools.load_world_ocean


def load_json(path: Path) -> dict:
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


def load_world_ocean_cached():
	global _WORLD_OCEAN_CACHE
	if _WORLD_OCEAN_CACHE is None:
		_WORLD_OCEAN_CACHE = _ORIGINAL_LOAD_WORLD_OCEAN()
	return _WORLD_OCEAN_CACHE


cell_tools.load_world_ocean = load_world_ocean_cached


def polygon_from_rings(rings: list) -> Polygon:
	poly = Polygon(rings[0], rings[1:])
	if not poly.is_valid:
		poly = poly.buffer(0)
	if poly.geom_type == "MultiPolygon":
		poly = max(poly.geoms, key=lambda p: p.area)
	return poly


def largest_polygon(geom):
	if geom.is_empty:
		return None
	if geom.geom_type == "Polygon":
		return geom
	if geom.geom_type == "MultiPolygon":
		return max(geom.geoms, key=lambda p: p.area)
	return None


def polygon_parts(geom) -> list:
	if geom.is_empty:
		return []
	if geom.geom_type == "Polygon":
		return [geom]
	if geom.geom_type == "MultiPolygon":
		return list(geom.geoms)
	if geom.geom_type == "GeometryCollection":
		return [g for part in geom.geoms for g in polygon_parts(part)]
	return []


def rings_from_polygon(poly: Polygon) -> list:
	rings = [[[round(x, 2), round(y, 2)] for x, y in poly.exterior.coords]]
	for hole in poly.interiors:
		rings.append([[round(x, 2), round(y, 2)] for x, y in hole.coords])
	return rings


def bbox_from_ring(ring: list) -> list:
	xs = [p[0] for p in ring]
	ys = [p[1] for p in ring]
	return [min(xs), min(ys), max(xs), max(ys)]


def polygon_area_km2(rings: list) -> float:
	area = cell_tools.ring_area_km2_world_px(rings[0])
	for hole in rings[1:]:
		area -= cell_tools.ring_area_km2_world_px(hole)
	return max(area, 0.0)


def get_province() -> tuple[dict, dict, Polygon]:
	province = next(p for p in load_json(PROVINCES_PATH)["provinces"] if p["id"] == PROVINCE_ID)
	geom = next(p for p in load_json(GEOMETRY_PATH)["provinces"] if p["id"] == PROVINCE_ID)
	raw_poly = polygon_from_rings(geom["rings"])
	return province, geom, raw_poly


def get_city() -> dict:
	for city in load_json(CITIES_PATH)["cities"]:
		if city.get("province") == "La Coruña":
			return city
	raise RuntimeError("La Coruna city marker not found")


def split_by_line(poly: Polygon, points: list[tuple[float, float]]) -> list:
	result = shapely_split(poly, LineString(points))
	return [p for p in polygon_parts(result) if p.area > 1e-6]


def make_city_cell(province_poly: Polygon, city_pos: tuple[float, float]) -> Polygon:
	minx, miny, maxx, maxy = province_poly.bounds
	# First benchmark geometry, per the La Coruna improvement plan:
	# not an ellipse/buffer, but an asymmetric urban district with a deeper
	# southern hinterland and a shorter northern coastal reach.
	city_shape = Polygon([
		(city_pos[0] - 10.8, miny - 2.0),
		(city_pos[0] + 10.8, miny - 2.0),
		(city_pos[0] + 10.5, city_pos[1] - 3.4),
		(city_pos[0] + 8.8, city_pos[1] + 4.4),
		(city_pos[0] + 5.4, city_pos[1] + 9.4),
		(city_pos[0] + 0.2, city_pos[1] + 11.9),
		(city_pos[0] - 5.8, city_pos[1] + 10.6),
		(city_pos[0] - 10.2, city_pos[1] + 6.4),
		(city_pos[0] - 12.4, city_pos[1] + 0.6),
		(city_pos[0] - 12.0, city_pos[1] - 3.0),
	])
	city_cell = province_poly.intersection(city_shape)
	city_cell = largest_polygon(city_cell)
	if city_cell is None:
		raise RuntimeError("failed to build city cell")
	return city_cell.buffer(0)


def choose_piece(pieces: list, scorer) -> Polygon:
	return max(pieces, key=scorer)


def choose_significant_piece(pieces: list, scorer, min_area_px2: float = 8.0) -> Polygon:
	significant = [p for p in pieces if p.area >= min_area_px2]
	return max(significant if significant else pieces, key=scorer)


def build_cells(province_poly: Polygon, city_cell: Polygon) -> list[tuple[str, str, Polygon]]:
	remaining = province_poly.difference(city_cell)
	if not remaining.is_valid:
		remaining = remaining.buffer(0)
	remaining = remaining.buffer(0)
	if remaining is None:
		raise RuntimeError("city cell consumed the province")

	minx, miny, maxx, maxy = province_poly.bounds
	# First natural-looking cut: detach the western coastal/peninsular side by
	# a short neck-ish polyline, not by a central fan.
	west_line = [
		(minx + 9.0, miny - 5.0),
		(minx + 12.0, miny + 10.0),
		(minx + 9.5, maxy + 5.0),
	]
	west_split = split_by_line(remaining, west_line)
	if len(west_split) < 2:
		west_split = split_by_line(remaining, [(minx + 11.0, miny - 5.0), (minx + 11.0, maxy + 5.0)])
	west = choose_significant_piece(west_split, lambda p: -p.representative_point().x, 20.0)
	interior = remaining.difference(west).buffer(0)
	if interior is None:
		raise RuntimeError("failed to isolate western coastal cell")

	# Then split the interior once: south vs east. This avoids one central node
	# shared by all cells.
	south_east_line = [
		(minx + 20.0, maxy + 5.0),
		(minx + 28.0, miny - 5.0),
	]
	interior_split = split_by_line(interior, south_east_line)
	if len(interior_split) < 2:
		interior_split = split_by_line(interior, [(minx + 19.0, maxy + 5.0), (maxx + 3.0, miny + 10.0)])
	south = choose_significant_piece(interior_split, lambda p: p.representative_point().y, 20.0)
	east = interior.difference(south).buffer(0)
	if east is None:
		raise RuntimeError("failed to split south/east cells")

	return [
		("city", "Ла-Корунья - городская клетка", city_cell),
		("west_coast", "Ла-Корунья - западная прибрежная", west),
		("south_interior", "Ла-Корунья - южная внутренняя", south),
		("east_interior", "Ла-Корунья - восточная внутренняя", east),
	]


def make_cell(province: dict, kind: str, name: str, idx: int, poly: Polygon, source_poly: Polygon) -> dict:
	poly = poly.buffer(0)
	if poly.geom_type != "Polygon":
		poly = largest_polygon(poly)
	if poly is None:
		raise RuntimeError("empty cell geometry for %s" % kind)
	rings = rings_from_polygon(poly)
	brd_open, brd_boundary = cell_tools._split_border_chains(rings[0], source_poly.boundary)
	brd_open = cell_tools._trim_open_chains_to_land(brd_open, source_poly, source_poly)
	return {
		"id": "lacoruna_city_first:%s" % kind,
		"name": name,
		"province_id": province["id"],
		"legacy_province_id": province["legacy_id"],
		"region_id": province["region_id"],
		"cell_role": kind,
		"rings": rings,
		"brd_open": brd_open,
		"brd_boundary": brd_boundary,
		"bbox": bbox_from_ring(rings[0]),
		"area_km2": round(polygon_area_km2(rings), 1),
		"color_key": kind,
	}


def validate_coverage(province_poly: Polygon, cells: list[tuple[str, str, Polygon]]) -> dict:
	main_polys = [largest_polygon(p) or p for _kind, _name, p in cells]
	union = unary_union(main_polys)
	missing = province_poly.difference(union).area
	extra = union.difference(province_poly).area
	overlap_area = sum(p.area for p in main_polys) - union.area
	return {
		"missing_world_px2": round(missing, 6),
		"extra_world_px2": round(extra, 6),
		"overlap_world_px2": round(overlap_area, 6),
		"ok": missing < 0.5 and extra < 1e-4 and overlap_area < 1e-4,
	}


def main() -> None:
	province, geom, province_poly = get_province()
	city = get_city()
	city_pos = tuple(city["pos"])
	city_cell = make_city_cell(province_poly, city_pos)
	cells_geom = build_cells(province_poly, city_cell)
	coverage = validate_coverage(province_poly, cells_geom)

	target_radius_km = math.sqrt(TARGET_AREA_KM2 / math.pi)
	payload = {
		"schema_version": 1,
		"kind": "lacoruna_city_first_preview",
		"world_px": WORLD_PX,
		"source": {
			"geometry": str(GEOMETRY_PATH.relative_to(ROOT)).replace("\\", "/"),
			"city": str(CITIES_PATH.relative_to(ROOT)).replace("\\", "/"),
			"plan": "Все про клетки/ГЕОМЕТРИЯ_СУХОПУТНЫХ_КЛЕТОК_ПОЛНЫЙ_АНАЛИЗ_И_ПЛАН.md",
		},
		"debug": {
			"province_id": province["id"],
			"city": city,
			"target_area_km2": TARGET_AREA_KM2,
			"city_protection_radius_km": round(target_radius_km * CITY_PROTECTION_RATIO, 2),
			"coverage": coverage,
		},
		"cells": [
			make_cell(province, kind, name, idx, poly, province_poly)
			for idx, (kind, name, poly) in enumerate(cells_geom)
		],
	}
	with OUT_PATH.open("w", encoding="utf-8") as f:
		json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
	print("wrote %s" % OUT_PATH.relative_to(ROOT))
	print("cells: %d" % len(payload["cells"]))
	for cell in payload["cells"]:
		print("%s: %.1f km2" % (cell["id"], cell["area_km2"]))
	print("coverage ok: %s" % coverage["ok"])


if __name__ == "__main__":
	main()
