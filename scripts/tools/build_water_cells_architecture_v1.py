"""Построить первую версию данных морских клеток в целевой архитектуре.

Это НЕ продолжение удалённого generate_sea_cells.py. Скрипт держит новый
контракт данных и использует первый заменяемый игровой алгоритм нарезки:
берёт готовую маску воды assets/world_ocean.json, строит jittered Voronoi
по водным seed-точкам, клипует клетки по воде и экспортирует файлы:

  assets/map_geometry/water_cells.json
  assets/game_data/water_cells.json
  assets/game_data/water_areas.json
  assets/map_graph/water_transitions.json
  assets/map_graph/water_land_links.json
  assets/scenarios/1444/water_cell_state.json

Алгоритм нарезки позже можно заменить на полноценный constrained Voronoi
с навигационными зонами без смены контракта файлов. Реестр
assets/migrations/water_cell_ids.json намеренно НЕ создаётся: геометрия
морских клеток пока нестабильна.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
from pathlib import Path
from typing import Any

from shapely.geometry import MultiPoint, MultiPolygon, Point, Polygon, box
from shapely.geometry import LineString
from shapely.ops import transform as shapely_transform
from shapely.ops import unary_union, voronoi_diagram
from shapely.strtree import STRtree


ROOT = Path(__file__).resolve().parents[2]

WORLD_OCEAN_PATH = ROOT / "assets/world_ocean.json"
PROVINCES_LEGACY_PATH = ROOT / "assets/provinces.json"
PROVINCES_PASSPORT_PATH = ROOT / "assets/game_data/provinces.json"

OUT_WATER_GEOMETRY = ROOT / "assets/map_geometry/water_cells.json"
OUT_WATER_PASSPORT = ROOT / "assets/game_data/water_cells.json"
OUT_WATER_AREAS = ROOT / "assets/game_data/water_areas.json"
OUT_WATER_TRANSITIONS = ROOT / "assets/map_graph/water_transitions.json"
OUT_WATER_LAND_LINKS = ROOT / "assets/map_graph/water_land_links.json"
OUT_WATER_SCENARIO = ROOT / "assets/scenarios/1444/water_cell_state.json"

WORLD_PX = 8192.0
EARTH_RADIUS_KM = 6371.0
VERSION = "2026.07.13"

# Тот же тестовый регион, который уже используется для водных слоёв:
# Иберия + Франция + Бискай + Ла-Манш.
TEST_REGION_LONLAT = (-17.5, 35.0, 8.5, 51.5)

DEFAULT_CELL_PX = 48.0
FULL_WORLD_CELL_PX = 192.0
COASTAL_CELL_PX = 30.0
SHELF_CELL_PX = 42.0
OPEN_SEA_CELL_PX = 64.0
COASTAL_BAND_KM = 90.0
SHELF_BAND_KM = 240.0
MIN_WATER_CELL_AREA_PX2 = 2.0
MIN_VORONOI_CELL_AREA_PX2 = 18.0
MIN_SHARED_BORDER_PX = 0.25
COAST_LINK_BUFFER_PX = 0.35
COAST_BORDER_TOL_PX = 0.45
GAME_WATER_LAND_MARGIN_KM = 2.0
SEED_RANDOM_SALT = 1444
WARP_SEGMENT_PX = 7.0
WARP_AMPLITUDE_PX = 4.8

DEFAULT_WATER_AREA_ID = "water_area:west_europe_test_water"
FULL_WATER_AREA_ID = "water_area:world_ocean_unclassified"


def load_json(path: Path) -> Any:
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


def dump_json(path: Path, data: Any) -> None:
	os.makedirs(path.parent, exist_ok=True)
	with path.open("w", encoding="utf-8") as f:
		json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def project(lon: float, lat: float) -> tuple[float, float]:
	lat = max(-85.05112878, min(85.05112878, lat))
	x = (lon + 180.0) / 360.0 * WORLD_PX
	lat_rad = math.radians(lat)
	y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
	return x, y


def unproject_lat(y: float) -> float:
	n = math.pi - 2.0 * math.pi * y / WORLD_PX
	return math.degrees(math.atan(math.sinh(n)))


def km_per_world_px(y: float) -> float:
	lat = unproject_lat(y)
	return (2.0 * math.pi * EARTH_RADIUS_KM / WORLD_PX) * math.cos(math.radians(lat))


def area_km2(geom: Polygon) -> float:
	c = geom.representative_point()
	scale = km_per_world_px(c.y)
	return geom.area * scale * scale


def length_km(line_geom, y: float) -> float:
	return getattr(line_geom, "length", 0.0) * km_per_world_px(y)


def explode_polygons(geom) -> list[Polygon]:
	if geom.is_empty:
		return []
	if isinstance(geom, Polygon):
		return [geom]
	if isinstance(geom, MultiPolygon):
		return list(geom.geoms)
	if geom.geom_type == "GeometryCollection":
		out: list[Polygon] = []
		for child in geom.geoms:
			out.extend(explode_polygons(child))
		return out
	return []


def polygon_from_rings(rings: list) -> Polygon | None:
	if not rings or len(rings[0]) < 3:
		return None
	try:
		poly = Polygon(rings[0], rings[1:])
		if not poly.is_valid:
			poly = poly.buffer(0)
		if poly.is_empty:
			return None
		return poly
	except Exception:
		return None


def load_world_ocean() -> list[Polygon]:
	data = load_json(WORLD_OCEAN_PATH)
	polys: list[Polygon] = []
	for item in data.get("cells", []):
		poly = polygon_from_rings(item.get("rings", []))
		if poly is None:
			continue
		polys.extend(explode_polygons(poly))
	return polys


def load_land_polygons() -> tuple[list[dict], list[Polygon]]:
	legacy = load_json(PROVINCES_LEGACY_PATH).get("cells", [])
	passports = load_json(PROVINCES_PASSPORT_PATH).get("provinces", [])
	legacy_to_new = {item.get("legacy_id"): item.get("id") for item in passports}

	items: list[dict] = []
	polys: list[Polygon] = []
	for item in legacy:
		poly = polygon_from_rings(item.get("rings", []))
		if poly is None:
			continue
		legacy_id = item.get("id", "")
		land_id = legacy_to_new.get(legacy_id) or legacy_id
		items.append({"id": land_id, "legacy_id": legacy_id, "name": item.get("name", "")})
		polys.append(poly)
	return items, polys


def region_bbox(lonlat_box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
	lon0, lat0, lon1, lat1 = lonlat_box
	x0, y0 = project(lon0, lat1)
	x1, y1 = project(lon1, lat0)
	return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def ring_points(poly: Polygon) -> list[list[list[float]]]:
	rings = [[[round(x, 2), round(y, 2)] for x, y in poly.exterior.coords]]
	for interior in poly.interiors:
		if len(interior.coords) >= 3:
			rings.append([[round(x, 2), round(y, 2)] for x, y in interior.coords])
	return rings


def chain_points(chain: list[tuple[float, float]]) -> list[list[float]]:
	return [[round(x, 2), round(y, 2)] for x, y in chain]


def split_internal_border_chains(poly: Polygon, ocean_boundary) -> list[list[list[float]]]:
	coords = list(poly.exterior.coords)
	n = len(coords) - 1
	if n < 2:
		return []
	is_internal: list[bool] = []
	for i in range(n):
		a = coords[i]
		b = coords[i + 1]
		seg = LineString([a, b])
		mid = seg.interpolate(0.5, normalized=True)
		is_internal.append(ocean_boundary.distance(mid) > COAST_BORDER_TOL_PX)

	if all(is_internal):
		return [chain_points(coords)]
	if not any(is_internal):
		return []

	start = next(i for i in range(n) if is_internal[i] and not is_internal[i - 1])
	chains: list[list[tuple[float, float]]] = []
	chain: list[tuple[float, float]] = []
	for k in range(n):
		i = (start + k) % n
		if is_internal[i]:
			if not chain:
				chain = [coords[i]]
			chain.append(coords[(i + 1) % n])
		else:
			if len(chain) >= 2:
				chains.append(chain)
			chain = []
	if len(chain) >= 2:
		chains.append(chain)
	return [chain_points(chain) for chain in chains if len(chain) >= 2]


def bbox_values(poly: Polygon) -> list[float]:
	x0, y0, x1, y1 = poly.bounds
	return [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)]


def point_values(point: Point) -> list[float]:
	return [round(point.x, 2), round(point.y, 2)]


def density_class(distance_to_land_km: float) -> str:
	if distance_to_land_km <= 90.0:
		return "coastal"
	if distance_to_land_km <= 220.0:
		return "dense_sea"
	if distance_to_land_km <= 500.0:
		return "regional_sea"
	return "ocean_transition"


def coast_margin_px_for_bbox(target_bbox: tuple[float, float, float, float]) -> float:
	y = (target_bbox[1] + target_bbox[3]) * 0.5
	return GAME_WATER_LAND_MARGIN_KM / max(km_per_world_px(y), 0.001)


def stable_noise(x: float, y: float, salt: int) -> float:
	v = math.sin(x * 12.9898 + y * 78.233 + salt * 37.719) * 43758.5453
	return (v - math.floor(v)) * 2.0 - 1.0


def warp_xy(x: float, y: float) -> tuple[float, float]:
	low_x = math.sin(x * 0.019 + y * 0.011 + 1.7) + 0.45 * math.sin(x * 0.041 - y * 0.017 + 4.1)
	low_y = math.cos(x * 0.013 - y * 0.023 + 2.9) + 0.45 * math.sin(x * 0.027 + y * 0.037 + 5.3)
	hi_x = stable_noise(x * 0.075, y * 0.075, 11) * 0.45
	hi_y = stable_noise(x * 0.075, y * 0.075, 23) * 0.45
	return x + (low_x + hi_x) * WARP_AMPLITUDE_PX, y + (low_y + hi_y) * WARP_AMPLITUDE_PX


def densify_ring(coords, segment_px: float) -> list[tuple[float, float]]:
	points = [(float(x), float(y)) for x, y in coords]
	if len(points) < 2:
		return points
	out: list[tuple[float, float]] = []
	for a, b in zip(points, points[1:]):
		ax, ay = a
		bx, by = b
		if not out:
			out.append(a)
		dist = math.hypot(bx - ax, by - ay)
		steps = max(1, int(math.ceil(dist / segment_px)))
		for i in range(1, steps + 1):
			t = i / steps
			out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
	return out


def densify_polygon(poly: Polygon, segment_px: float) -> Polygon:
	exterior = densify_ring(poly.exterior.coords, segment_px)
	interiors = [densify_ring(ring.coords, segment_px) for ring in poly.interiors]
	return Polygon(exterior, interiors)


def warp_polygon(poly: Polygon) -> Polygon:
	dense = densify_polygon(poly, WARP_SEGMENT_PX)
	warped = shapely_transform(lambda x, y, z=None: warp_xy(x, y), dense)
	if not warped.is_valid:
		warped = warped.buffer(0)
	return warped


def point_distance_to_land_px(point: Point, land_union) -> float:
	if land_union is None or land_union.is_empty:
		return 9999.0
	return point.distance(land_union)


def water_seed_target_cell_px(distance_to_land_px: float, y: float, base_cell_px: float) -> float:
	distance_to_land_km = distance_to_land_px * km_per_world_px(y)
	if distance_to_land_km <= COASTAL_BAND_KM:
		return min(base_cell_px, COASTAL_CELL_PX)
	if distance_to_land_km <= SHELF_BAND_KM:
		return min(base_cell_px, SHELF_CELL_PX)
	return max(base_cell_px, OPEN_SEA_CELL_PX)


def water_seed_keep_probability(distance_to_land_px: float, y: float, scan_step_px: float, base_cell_px: float) -> float:
	target_cell_px = water_seed_target_cell_px(distance_to_land_px, y, base_cell_px)
	probability = (scan_step_px / max(target_cell_px * 0.86, 1.0)) ** 2
	probability = max(0.10, min(1.0, probability))
	if distance_to_land_px <= target_cell_px * 1.25:
		return 1.0
	if distance_to_land_px <= target_cell_px * 2.75:
		return max(probability, 0.72)
	if distance_to_land_px <= target_cell_px * 5.5:
		return max(probability, 0.46)
	return probability


def build_water_seeds(ocean_union, target_bbox: tuple[float, float, float, float], cell_px: float) -> list[Point]:
	land_items, land_polys = load_land_polygons()
	crop = box(*target_bbox).buffer(cell_px * 2.0)
	near_land = [poly for poly in land_polys if poly.intersects(crop)]
	land_union = unary_union(near_land) if near_land else None

	x0, y0, x1, y1 = target_bbox
	rng = random.Random(SEED_RANDOM_SALT)
	step = min(cell_px, COASTAL_CELL_PX) * 0.86
	jitter = step * 0.34
	seeds: list[Point] = []
	y = y0 + step * 0.5
	row = 0
	while y < y1:
		x = x0 + step * (0.35 if row % 2 else 0.5)
		while x < x1:
			px = x + rng.uniform(-jitter, jitter)
			py = y + rng.uniform(-jitter, jitter)
			p = Point(px, py)
			if ocean_union.contains(p):
				d = point_distance_to_land_px(p, land_union)
				if rng.random() <= water_seed_keep_probability(d, py, step, cell_px):
					seeds.append(p)
			x += step
		y += step
		row += 1

	for poly in explode_polygons(ocean_union):
		if poly.area < COASTAL_CELL_PX * COASTAL_CELL_PX * 0.35:
			continue
		rp = poly.representative_point()
		if not any(rp.distance(seed) < COASTAL_CELL_PX * 0.45 for seed in seeds):
			seeds.append(rp)
	return seeds


def build_water_geometries(ocean_polys: list[Polygon], target_bbox: tuple[float, float, float, float], cell_px: float) -> list[Polygon]:
	crop = box(*target_bbox)
	ocean_parts = [poly.intersection(crop) for poly in ocean_polys if poly.intersects(crop)]
	ocean_parts = [part for part in ocean_parts if not part.is_empty]
	if not ocean_parts:
		return []
	raw_ocean_union = unary_union(ocean_parts)
	margin_px = coast_margin_px_for_bbox(target_bbox)
	ocean_union = raw_ocean_union.buffer(margin_px, quad_segs=8).intersection(crop)
	if not ocean_union.is_valid:
		ocean_union = ocean_union.buffer(0)

	seeds = build_water_seeds(ocean_union, target_bbox, cell_px)
	if len(seeds) < 2:
		return explode_polygons(ocean_union)

	envelope = box(*target_bbox).buffer(cell_px * 4.0)
	diagram = voronoi_diagram(MultiPoint(seeds), envelope=envelope, edges=False)
	water_cells: list[Polygon] = []
	for vor_cell in explode_polygons(diagram):
		warped_cell = warp_polygon(vor_cell)
		clipped = warped_cell.intersection(ocean_union)
		for part in explode_polygons(clipped):
			if part.area < MIN_VORONOI_CELL_AREA_PX2:
				continue
			if not part.is_valid:
				part = part.buffer(0)
			for clean in explode_polygons(part):
				if clean.area >= MIN_VORONOI_CELL_AREA_PX2:
					water_cells.append(clean)

	water_cells.sort(key=lambda geom: (geom.representative_point().y, geom.representative_point().x))
	return water_cells


def build_transitions(water_cells: list[Polygon]) -> list[dict]:
	buffered = [cell.buffer(0.05) for cell in water_cells]
	tree = STRtree(buffered)
	seen: set[tuple[int, int]] = set()
	transitions: list[dict] = []
	for i, geom in enumerate(water_cells):
		for candidate in tree.query(buffered[i]):
			j = int(candidate)
			if j <= i:
				continue
			pair = (i, j)
			if pair in seen:
				continue
			shared = geom.boundary.intersection(water_cells[j].boundary)
			if getattr(shared, "length", 0.0) <= MIN_SHARED_BORDER_PX:
				continue
			seen.add(pair)
			a = geom.representative_point()
			b = water_cells[j].representative_point()
			distance_px = math.hypot(a.x - b.x, a.y - b.y)
			mid_y = (a.y + b.y) * 0.5
			transitions.append({
				"id": f"water_transition:{len(transitions)}",
				"cell_a_id": f"water_cell:{i}",
				"cell_b_id": f"water_cell:{j}",
				"distance_km": round(distance_px * km_per_world_px(mid_y), 2),
				"shared_border_km": round(length_km(shared, mid_y), 2),
				"transition_type": "water",
				"flags": {
					"crosses_water_area_border": False,
					"is_narrow": False,
					"is_coastal": False,
				},
			})
	return transitions


def build_land_links(water_cells: list[Polygon], target_bbox: tuple[float, float, float, float]) -> tuple[list[dict], list[float], list[bool]]:
	land_items, land_polys = load_land_polygons()
	coast_link_buffer_px = COAST_LINK_BUFFER_PX + coast_margin_px_for_bbox(target_bbox)
	crop = box(*target_bbox).buffer(coast_link_buffer_px)
	near_land_indices = [i for i, poly in enumerate(land_polys) if poly.intersects(crop)]
	near_land = [land_polys[i] for i in near_land_indices]
	near_items = [land_items[i] for i in near_land_indices]

	if not near_land:
		return [], [9999.0 for _ in water_cells], [False for _ in water_cells]

	tree = STRtree([poly.buffer(coast_link_buffer_px) for poly in near_land])
	land_boundaries = [poly.boundary for poly in near_land]
	links: list[dict] = []
	min_distances = [9999.0 for _ in water_cells]
	has_link = [False for _ in water_cells]

	for i, water in enumerate(water_cells):
		probe = water.buffer(coast_link_buffer_px)
		candidates = tree.query(probe)
		center = water.representative_point()
		for candidate in candidates:
			land_idx = int(candidate)
			land_poly = near_land[land_idx]
			distance_px = water.distance(land_poly)
			distance_km = distance_px * km_per_world_px(center.y)
			if distance_km < min_distances[i]:
				min_distances[i] = distance_km
			coast = water.boundary.buffer(coast_link_buffer_px).intersection(land_boundaries[land_idx])
			shared_km = length_km(coast, center.y)
			if shared_km <= 0.01:
				continue
			has_link[i] = True
			links.append({
				"id": f"water_land_link:{len(links)}",
				"water_cell_id": f"water_cell:{i}",
				"land_area_id": near_items[land_idx]["id"],
				"shared_coast_km": round(shared_km, 2),
			})

	return links, min_distances, has_link


def build_outputs(water_cells: list[Polygon], water_area_id: str, water_area_name: str) -> None:
	transitions = build_transitions(water_cells)
	land_links, distances_to_land, coastal_flags = build_land_links(water_cells, union_bbox(water_cells))
	ocean_boundary = unary_union(water_cells).boundary

	geometry_items = []
	passport_items = []
	scenario_items = []
	for i, geom in enumerate(water_cells):
		center = geom.centroid
		label_point = geom.representative_point()
		navigation_point = label_point
		distance = distances_to_land[i]
		geometry_items.append({
			"id": f"water_cell:{i}",
			"numeric_id": i,
			"bbox": bbox_values(geom),
			"rings": ring_points(geom),
			"brd_open": split_internal_border_chains(geom, ocean_boundary),
			"center": point_values(center),
			"label_point": point_values(label_point),
			"navigation_point": point_values(navigation_point),
			"area_km2": round(area_km2(geom), 1),
		})
		passport_items.append({
			"id": f"water_cell:{i}",
			"numeric_id": i,
			"water_area_id": water_area_id,
			"density_class": density_class(distance),
			"generation_profile_id": "water_profile:jittered_voronoi_coast_margin_2km_mvp",
			"distance_to_land_km": round(distance, 1) if distance < 9999.0 else None,
			"flags": {
				"is_coastal": coastal_flags[i],
				"is_narrow_passage": False,
				"is_archipelago_cell": False,
				"touches_map_wrap": False,
			},
		})
		scenario_items.append({"water_cell_id": f"water_cell:{i}"})

	dump_json(OUT_WATER_GEOMETRY, {
		"schema_version": 1,
		"geometry_version": VERSION,
		"world_px": WORLD_PX,
		"water_cells": geometry_items,
	})
	dump_json(OUT_WATER_PASSPORT, {
		"schema_version": 1,
		"content_version": VERSION,
		"water_cells": passport_items,
	})
	dump_json(OUT_WATER_AREAS, {
		"schema_version": 1,
		"content_version": VERSION,
		"water_areas": [{
			"id": water_area_id,
			"name": water_area_name,
			"display_name_ru": "",
			"type": "sea",
		}],
	})
	dump_json(OUT_WATER_TRANSITIONS, {
		"schema_version": 1,
		"graph_version": VERSION,
		"water_transitions": transitions,
	})
	dump_json(OUT_WATER_LAND_LINKS, {
		"schema_version": 1,
		"graph_version": VERSION,
		"water_land_links": land_links,
	})
	dump_json(OUT_WATER_SCENARIO, {
		"schema_version": 1,
		"scenario_id": "scenario:1444",
		"map_content_version": VERSION,
		"water_cell_states": scenario_items,
	})

	print(f"water cells: {len(water_cells)}")
	print(f"water transitions: {len(transitions)}")
	print(f"water-land links: {len(land_links)}")


def union_bbox(polys: list[Polygon]) -> tuple[float, float, float, float]:
	if not polys:
		return 0.0, 0.0, 0.0, 0.0
	x0 = min(poly.bounds[0] for poly in polys)
	y0 = min(poly.bounds[1] for poly in polys)
	x1 = max(poly.bounds[2] for poly in polys)
	y1 = max(poly.bounds[3] for poly in polys)
	return x0, y0, x1, y1


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Build water cell architecture files.")
	parser.add_argument("--full", action="store_true", help="Build coarse cells for the whole current ocean mask.")
	parser.add_argument("--cell-px", type=float, default=None, help="Grid cell size in world pixels.")
	return parser.parse_args()


def main() -> int:
	args = parse_args()
	ocean_polys = load_world_ocean()
	if args.full:
		bbox = union_bbox(ocean_polys)
		cell_px = args.cell_px or FULL_WORLD_CELL_PX
		water_area_id = FULL_WATER_AREA_ID
		water_area_name = "World Ocean Unclassified"
	else:
		bbox = region_bbox(TEST_REGION_LONLAT)
		cell_px = args.cell_px or DEFAULT_CELL_PX
		water_area_id = DEFAULT_WATER_AREA_ID
		water_area_name = "West Europe Test Water"

	water_cells = build_water_geometries(ocean_polys, bbox, cell_px)
	if not water_cells:
		raise RuntimeError("water cell generation produced no cells")
	build_outputs(water_cells, water_area_id, water_area_name)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
