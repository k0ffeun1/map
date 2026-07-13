"""Build helper geometry for province selection on layer 4.

The visual ocean layer extends about 2 km inland. Province selection should use
the same gameplay coastline, otherwise the white selected outline sits on top of
the shallow-water strip. This file keeps the original provinces_iberia.json for
rendering/clicking and writes a clipped copy used only by TileMapViewer overlay.
"""
import json
import sys
from pathlib import Path

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_water_cells_architecture_v1 import (  # noqa: E402
	GAME_WATER_LAND_MARGIN_KM,
	km_per_world_px,
	load_world_ocean,
)

SRC = ROOT / "assets" / "provinces_iberia.json"
OUT = ROOT / "assets" / "provinces_iberia_selection_2km.json"
WORLD_PX = 8192.0
MIN_PART_AREA_PX2 = 0.02


def _explode_polygons(geom) -> list:
	if geom.is_empty:
		return []
	if geom.geom_type == "Polygon":
		return [geom]
	if geom.geom_type == "MultiPolygon":
		return list(geom.geoms)
	return []


def _rings_from_polygon(poly) -> list:
	rings = [[[round(x, 2), round(y, 2)] for x, y in poly.exterior.coords]]
	for hole in poly.interiors:
		rings.append([[round(x, 2), round(y, 2)] for x, y in hole.coords])
	return rings


def _bbox_from_rings(rings: list) -> list:
	points = [p for ring in rings for p in ring]
	xs = [p[0] for p in points]
	ys = [p[1] for p in points]
	return [min(xs), min(ys), max(xs), max(ys)]


def _clip_ocean_margin(poly, ocean_polys: list):
	margin_px = GAME_WATER_LAND_MARGIN_KM / max(km_per_world_px(poly.representative_point().y), 0.001)
	clip = box(*poly.bounds).buffer(margin_px + 3.0)
	ocean_parts = []
	for ocean_poly in ocean_polys:
		if ocean_poly.intersects(clip):
			part = ocean_poly.intersection(clip)
			if not part.is_empty:
				ocean_parts.append(part)
	if not ocean_parts:
		return poly
	ocean_margin = unary_union(ocean_parts).buffer(margin_px, quad_segs=8)
	clipped = poly.difference(ocean_margin)
	if clipped.is_empty:
		return poly
	if not clipped.is_valid:
		clipped = clipped.buffer(0)
	return clipped


def main() -> None:
	data = json.load(open(SRC, encoding="utf-8"))
	ocean_polys = load_world_ocean()
	out_cells = []
	clipped_count = 0
	for cell in data.get("cells", []):
		rings = cell.get("rings", [])
		if not rings:
			continue
		poly = Polygon(rings[0], rings[1:])
		if not poly.is_valid:
			poly = poly.buffer(0)
		clipped = _clip_ocean_margin(poly, ocean_polys)
		if clipped.area < poly.area - 1e-6:
			clipped_count += 1
		for idx, part in enumerate(_explode_polygons(clipped)):
			if part.area < MIN_PART_AREA_PX2:
				continue
			out_rings = _rings_from_polygon(part)
			out = {
				"id": cell.get("id", "") if idx == 0 else f"{cell.get('id', '')}__selection_part_{idx}",
				"name": cell.get("name", ""),
				"rings": out_rings,
				"bbox": _bbox_from_rings(out_rings),
			}
			if "color_key" in cell:
				out["color_key"] = cell["color_key"]
			out_cells.append(out)
	json.dump({"world_px": WORLD_PX, "cells": out_cells}, open(OUT, "w", encoding="utf-8"),
		ensure_ascii=False, separators=(",", ":"))
	print(f"wrote {OUT.relative_to(ROOT)}: {len(out_cells)} parts, clipped provinces={clipped_count}")


if __name__ == "__main__":
	main()
