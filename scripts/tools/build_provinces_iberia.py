"""Обрезка assets/provinces.json до региона Пиренейский п-ов + Балеары —
ЖИВОЙ (векторный) эквивалент того же региона, что уже фильтрует
bake_provinces_iberia_tiles.py (REGION_LONLAT, тот же bbox-фильтр по
запасу PAD_WORLD_PX). Результат — assets/provinces_iberia.json, тот же
формат rings/bbox/name, что и полный provinces.json.

Повод: слой "4" (клавиша 4) временно живой (IrregularCellProvider, см.
TileMapViewer.gd, PROVINCES_IBERIA_FORCE_LIVE, решение сессии 2026-07-11) —
пока не зафиксирована граница provinces.json и не перезапечено начисто.
Если грузить в слой "4" ПОЛНЫЙ provinces.json — слой рисует ВЕСЬ мир и
становится дубликатом слоя "8" (найдено пользователем в сессии). Этот
скрипт даёт слою "4" собственный, ограниченный регионом набор данных, как и
задумано изначально.

world_px клеток НЕ пересчитывается (уже спроецированы build_provinces.py) —
просто фильтр по bbox, дешёвая операция.
"""
import json, math

from shapely.geometry import MultiPolygon, Polygon

SRC = "assets/provinces.json"
OUT = "assets/provinces_iberia.json"
WORLD_PX = 8192.0

# ТОТ ЖЕ регион, что REGION_LONLAT в bake_provinces_iberia_tiles.py — не
# рассинхронизировать (баг-ловушка: другой регион на слое "4" live vs
# baked-версия, к которой вернёмся позже).
REGION_LONLAT = (-9.9, 35.95, 4.4, 44.0)
PAD_WORLD_PX = 5.0  # тот же запас, что "pad" в bake_provinces_iberia_tiles.py

# Тонкое расширение ТОЛЬКО заливки слоя 4, в мировых px. Исходная граница
# сохраняется в "brd" и используется IrregularCellProvider для отрисовки
# контура, поэтому визуально линия остаётся на настоящем месте, а прозрачные
# щели/чёрные крапинки между полигонами закрываются цветом провинции.
FILL_GAP_FIX_WORLD_PX = 0.0


def project(lon: float, lat: float) -> tuple:
	lat = max(-85.05112878, min(85.05112878, lat))
	x = (lon + 180.0) / 360.0 * WORLD_PX
	lat_rad = math.radians(lat)
	y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
	return x, y


def region_bbox_world_px() -> tuple:
	lon0, lat0, lon1, lat1 = REGION_LONLAT
	x0, y0 = project(lon0, lat1)
	x1, y1 = project(lon1, lat0)
	return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _polygon_from_rings(rings: list) -> Polygon | None:
	if not rings or len(rings[0]) < 3:
		return None
	poly = Polygon(rings[0], rings[1:])
	if not poly.is_valid:
		poly = poly.buffer(0)
	if poly.is_empty:
		return None
	return poly


def _rings_from_polygon(poly: Polygon) -> list:
	return [
		[[round(x, 2), round(y, 2)] for x, y in poly.exterior.coords[:-1]]
	]


def _expanded_fill_rings(rings: list) -> list:
	if FILL_GAP_FIX_WORLD_PX <= 0.0:
		return rings
	poly = _polygon_from_rings(rings)
	if poly is None:
		return rings
	expanded = poly.buffer(FILL_GAP_FIX_WORLD_PX, join_style=2)
	if expanded.is_empty:
		return rings
	if isinstance(expanded, MultiPolygon):
		# В исходных данных островные куски уже идут отдельными cells. Если
		# buffer всё же расколет геометрию, берём крупнейший кусок для этой
		# конкретной записи, чтобы формат одного cell оставался простым.
		expanded = max(expanded.geoms, key=lambda g: g.area)
	if not expanded.is_valid:
		expanded = expanded.buffer(0)
	if expanded.is_empty or not isinstance(expanded, Polygon):
		return rings
	return _rings_from_polygon(expanded)


def main() -> None:
	data = json.load(open(SRC, encoding="utf-8"))
	rx0, ry0, rx1, ry1 = region_bbox_world_px()
	print(f"регион {REGION_LONLAT} -> world px [{rx0:.0f},{ry0:.0f},{rx1:.0f},{ry1:.0f}]")

	out_cells = []
	for c in data["cells"]:
		bb = c.get("bbox")
		if not bb:
			continue
		if bb[2] < rx0 - PAD_WORLD_PX or bb[0] > rx1 + PAD_WORLD_PX \
				or bb[3] < ry0 - PAD_WORLD_PX or bb[1] > ry1 + PAD_WORLD_PX:
			continue
		original_rings = c.get("rings", [])
		out_cell = dict(c)
		if original_rings:
			out_cell["brd"] = original_rings
			out_cell["rings"] = _expanded_fill_rings(original_rings)
			out_cell["bbox"] = [
				min(p[0] for ring in out_cell["rings"] for p in ring),
				min(p[1] for ring in out_cell["rings"] for p in ring),
				max(p[0] for ring in out_cell["rings"] for p in ring),
				max(p[1] for ring in out_cell["rings"] for p in ring),
			]
		out_cells.append(out_cell)

	print(f"клеток в регионе: {len(out_cells)} из {len(data['cells'])}")
	json.dump({"world_px": data["world_px"], "cells": out_cells},
			   open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
	print(f"wrote {OUT}")


if __name__ == "__main__":
	main()
