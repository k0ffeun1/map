"""Build a visible preview layer for Iberian land cells.

This is an offline debug/preview artifact, not the final world land-cell
pipeline. Counts come from reports/province_area_report.csv, which is generated
from the region land_cell_generation rules and province overrides.
"""
import csv
import json
import math
import random
from pathlib import Path

from shapely.geometry import LineString, MultiPoint, Polygon
from shapely.ops import split as shapely_split
from shapely.ops import unary_union, voronoi_diagram

import build_cells_test as cell_tools


ROOT = Path(__file__).resolve().parents[2]
GEOMETRY_PATH = ROOT / "assets" / "map_geometry" / "provinces.json"
PROVINCES_PATH = ROOT / "assets" / "game_data" / "provinces.json"
REPORT_PATH = ROOT / "reports" / "province_area_report.csv"
OUT_PATH = ROOT / "assets" / "iberia_land_cells_preview.json"

WORLD_PX = 8192.0
MIN_PREVIEW_CELL_AREA_KM2 = 0.1

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


def polygon_from_rings(rings: list) -> Polygon | None:
	if not rings or len(rings[0]) < 3:
		return None
	poly = Polygon(rings[0], rings[1:])
	if not poly.is_valid:
		poly = poly.buffer(0)
	if poly.is_empty:
		return None
	if poly.geom_type == "MultiPolygon":
		poly = max(poly.geoms, key=lambda p: p.area)
	if poly.geom_type != "Polygon":
		return None
	return poly


def largest_polygon(geom):
	if geom.is_empty:
		return None
	if geom.geom_type == "Polygon":
		return geom
	if geom.geom_type == "MultiPolygon":
		return max(geom.geoms, key=lambda p: p.area)
	return None


def rings_from_polygon(poly: Polygon) -> list:
	rings = [[[round(x, 2), round(y, 2)] for x, y in poly.exterior.coords]]
	for hole in poly.interiors:
		rings.append([[round(x, 2), round(y, 2)] for x, y in hole.coords])
	return rings


def polygon_area_km2(rings: list) -> float:
	if not rings:
		return 0.0
	area = cell_tools.ring_area_km2_world_px(rings[0])
	for hole in rings[1:]:
		area -= cell_tools.ring_area_km2_world_px(hole)
	return max(area, 0.0)


def bbox_from_ring(ring: list) -> list:
	xs = [p[0] for p in ring]
	ys = [p[1] for p in ring]
	return [min(xs), min(ys), max(xs), max(ys)]


def seed_points(poly: Polygon, count: int, rng: random.Random) -> list:
	from shapely.geometry import Point

	seeds = cell_tools.make_seeds(poly, count, rng)
	minx, miny, maxx, maxy = poly.bounds
	attempts = 0
	while len(seeds) < count and attempts < 5000:
		attempts += 1
		x = rng.uniform(minx, maxx)
		y = rng.uniform(miny, maxy)
		if poly.contains(Point(x, y)):
			seeds.append((x, y))
	if not seeds:
		p = poly.representative_point()
		seeds.append((p.x, p.y))
	return seeds[:count]


def load_counts() -> dict:
	counts = {}
	with REPORT_PATH.open("r", encoding="utf-8-sig", newline="") as f:
		for row in csv.DictReader(f):
			if row.get("status") != "OK":
				continue
			if row.get("macroregion_id") != "macroregion:iberia":
				continue
			counts[row["province_id"]] = int(row["final_cell_count_base"])
	return counts


def make_cell(province: dict, region_id: str, local_idx: int, poly: Polygon, source_poly: Polygon) -> dict | None:
	rings = rings_from_polygon(poly)
	area_km2 = polygon_area_km2(rings)
	if area_km2 < MIN_PREVIEW_CELL_AREA_KM2:
		return None
	brd_open, brd_boundary = cell_tools._split_border_chains(rings[0], source_poly.boundary)
	brd_open = cell_tools._trim_open_chains_to_land(brd_open, source_poly, source_poly)
	return {
		"id": "iberia_land_cell:%s:%02d" % (province["numeric_id"], local_idx),
		"name": "%s - cell %d" % (province.get("name", province["id"]), local_idx + 1),
		"province_id": province["id"],
		"legacy_province_id": province["legacy_id"],
		"region_id": region_id,
		"rings": rings,
		"brd_open": brd_open,
		"brd_boundary": brd_boundary,
		"bbox": bbox_from_ring(rings[0]),
		"area_km2": round(area_km2, 1),
		"color_key": region_id,
	}


def split_province(province: dict, raw_poly: Polygon, target_count: int) -> list:
	province_poly = cell_tools._clip_ocean_margin(raw_poly)
	if province_poly.is_empty:
		province_poly = raw_poly
	province_poly = largest_polygon(province_poly) or raw_poly
	rng = random.Random(int(province["numeric_id"]) * 1009 + target_count * 37)
	if target_count <= 1:
		cell = make_cell(province, province["region_id"], 0, province_poly, raw_poly)
		return [cell] if cell else []

	parts = recursive_area_partition(province_poly, target_count, rng)
	if len(parts) == target_count:
		cells = []
		for part in parts:
			cell = make_cell(province, province["region_id"], len(cells), part, raw_poly)
			if cell:
				cells.append(cell)
		if len(cells) == target_count:
			return cells

	seeds = seed_points(province_poly, target_count, rng)
	if len(seeds) < 2:
		cell = make_cell(province, province["region_id"], 0, province_poly, raw_poly)
		return [cell] if cell else []

	vd = voronoi_diagram(MultiPoint(seeds), envelope=province_poly.envelope.buffer(50.0))
	cells = build_cells_from_voronoi(province, raw_poly, province_poly, vd, True)
	if len(cells) != target_count:
		cells = build_cells_from_voronoi(province, raw_poly, province_poly, vd, False)
	return cells


def recursive_area_partition(poly: Polygon, target_count: int, rng: random.Random, depth: int = 0) -> list:
	if target_count <= 1:
		return [poly]
	left_count = target_count // 2
	right_count = target_count - left_count
	split_pair = split_polygon_by_area(poly, left_count / target_count, rng, depth)
	if split_pair is None:
		return []
	left, right = split_pair
	left_parts = recursive_area_partition(left, left_count, rng, depth + 1)
	right_parts = recursive_area_partition(right, right_count, rng, depth + 1)
	if len(left_parts) != left_count or len(right_parts) != right_count:
		return []
	return left_parts + right_parts


def split_polygon_by_area(poly: Polygon, target_ratio: float, rng: random.Random, depth: int):
	minx, miny, maxx, maxy = poly.bounds
	width = maxx - minx
	height = maxy - miny
	if width <= 0.0 or height <= 0.0:
		return None
	center = poly.representative_point()
	base_angle = math.pi * 0.5 if width >= height else 0.0
	angle = base_angle + rng.uniform(-0.22, 0.22) * (0.65 ** depth)
	direction = (math.cos(angle), math.sin(angle))
	normal = (-direction[1], direction[0])
	corners = [(minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)]
	projections = [(x - center.x) * normal[0] + (y - center.y) * normal[1] for x, y in corners]
	lo = min(projections) - max(width, height)
	hi = max(projections) + max(width, height)
	best = None
	best_err = 10.0
	for _i in range(32):
		offset = (lo + hi) * 0.5
		pair = split_polygon_at_offset(poly, (center.x, center.y), direction, normal, offset, rng, depth)
		if pair is None:
			pair = split_polygon_at_offset(poly, (center.x, center.y), direction, normal, offset, rng, depth, False)
		if pair is None:
			if offset < 0.0:
				lo = offset
			else:
				hi = offset
			continue
		left, right = pair
		ratio = left.area / max(poly.area, 1e-9)
		err = abs(ratio - target_ratio)
		if err < best_err:
			best = pair
			best_err = err
		if ratio < target_ratio:
			lo = offset
		else:
			hi = offset
	return best


def split_polygon_at_offset(poly: Polygon, center: tuple, direction: tuple, normal: tuple,
		offset: float, rng: random.Random, depth: int, wavy: bool = True):
	minx, miny, maxx, maxy = poly.bounds
	span = max(maxx - minx, maxy - miny) * 3.0 + 20.0
	amp = min(max(maxx - minx, maxy - miny) * 0.045, 4.5) * (0.75 ** depth)
	phase = rng.random() * math.tau
	points = []
	steps = 24 if wavy else 1
	for i in range(steps + 1):
		u = i / steps
		t = -span + span * 2.0 * u
		wave = 0.0
		if wavy:
			wave = math.sin(u * math.tau + phase) * amp
			wave += math.sin(u * math.tau * 2.0 + phase * 0.7) * amp * 0.35
		x = center[0] + direction[0] * t + normal[0] * (offset + wave)
		y = center[1] + direction[1] * t + normal[1] * (offset + wave)
		points.append((x, y))
	line = LineString(points)
	try:
		result = shapely_split(poly, line)
	except Exception:
		return None
	pieces = [g for g in getattr(result, "geoms", []) if g.geom_type == "Polygon" and g.area > 1e-6]
	if len(pieces) < 2:
		return None
	left_parts = []
	right_parts = []
	for piece in pieces:
		p = piece.representative_point()
		proj = (p.x - center[0]) * normal[0] + (p.y - center[1]) * normal[1]
		if proj <= offset:
			left_parts.append(piece)
		else:
			right_parts.append(piece)
	if not left_parts or not right_parts:
		return None
	left = largest_polygon(unary_union(left_parts))
	right = largest_polygon(unary_union(right_parts))
	if left is None or right is None:
		return None
	return left, right


def build_cells_from_voronoi(province: dict, raw_poly: Polygon, province_poly: Polygon, vd, wavify: bool) -> list:
	cells = []
	for region in vd.geoms:
		region_geom = cell_tools._wavify_polygon(region) if wavify and region.geom_type == "Polygon" else region
		clipped = largest_polygon(region_geom.intersection(province_poly))
		if clipped is None:
			continue
		if not clipped.is_valid:
			clipped = largest_polygon(clipped.buffer(0))
		if clipped is None:
			continue
		cell = make_cell(province, province["region_id"], len(cells), clipped, raw_poly)
		if cell:
			cells.append(cell)
	return cells


def main() -> None:
	geometry_by_id = {p["id"]: p for p in load_json(GEOMETRY_PATH)["provinces"]}
	provinces = load_json(PROVINCES_PATH)["provinces"]
	counts = load_counts()

	out_cells = []
	expected = 0
	missing_geometry = []
	for province in provinces:
		if province.get("macroregion_id") != "macroregion:iberia":
			continue
		count = counts.get(province["id"])
		if count is None:
			continue
		expected += count
		geom = geometry_by_id.get(province["id"])
		if geom is None:
			missing_geometry.append(province["id"])
			continue
		raw_poly = polygon_from_rings(geom.get("rings", []))
		if raw_poly is None:
			missing_geometry.append(province["id"])
			continue
		out_cells.extend(split_province(province, raw_poly, count))

	if missing_geometry:
		raise SystemExit("missing geometry for: %s" % ", ".join(missing_geometry))

	payload = {
		"schema_version": 1,
		"kind": "iberia_land_cells_preview",
		"world_px": WORLD_PX,
		"source": {
			"counts": str(REPORT_PATH.relative_to(ROOT)).replace("\\", "/"),
			"geometry": str(GEOMETRY_PATH.relative_to(ROOT)).replace("\\", "/"),
		},
		"expected_cell_count": expected,
		"cells": out_cells,
	}
	with OUT_PATH.open("w", encoding="utf-8") as f:
		json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
	print("wrote %s" % OUT_PATH.relative_to(ROOT))
	print("iberia provinces: %d" % len(counts))
	print("expected cells: %d" % expected)
	print("preview cells: %d" % len(out_cells))


if __name__ == "__main__":
	main()
