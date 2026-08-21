"""ЧЕРНОВОЙ проход №2 по нарезке клеток Ла-Коруньи — по прямому запросу
пользователя ("нарежь клетку на равные прямые линии", "внешнюю границу
провинции вообще не трогай и чтобы связи вообще не было никакой с внешней
границей"), взамен предыдущего Voronoi-подхода (см. build_cells_test.py,
слой "Клетки (тест: Ла-Корунья)", клавиша C — НЕ трогаем, оставлен как есть).

2026-07-15: по просьбе пользователя ("сделай из квадратов более естественные
линии границ") внутренние рёбра сетки (стыки между соседними клетками)
сделаны волнистыми — тем же детерминированным приёмом рекурсивного смещения
середины отрезка, что уже используется в build_cells_test.py
(_seeded_unit/_displace_segment/_wavy_edge/_wavify_ring, скопированы сюда
как есть, а не импортированы, чтобы черновики №1 и №2 оставались независимы
друг от друга). Внешний контур провинции по-прежнему НЕ волнится и не
анализируется — волнение применяется к прямоугольнику сетки ДО пересечения с
province_poly (см. main()), поэтому после intersection() внешняя граница
остаётся точной прямой линией контура провинции, а волна остаётся только на
рёбрах, которые действительно лежат внутри клетки (см. тот же приём и
комментарий в build_cells_test.py/main()).

Механика — максимально простая, никакой органики на внешней границе:
1. Контур провинции (assets/provinces.json) используется ТОЛЬКО чтобы
   обрезать сетку — саму границу не меняем и не анализируем (нет ни
   выделения "какой кусок ребра лежит на границе провинции", в отличие
   от build_cells_test.py/_split_open_border_chains — brd_open по-прежнему
   не считаем, см. п.5 ниже).
2. bbox провинции делится ПРЯМЫМИ линиями — обычная равномерная сетка
   GRID_ROWS x GRID_COLS (2x2 по умолчанию = 4 клетки).
3. Каждый прямоугольник сетки волнится по всем 4 рёбрам (_wavify_polygon),
   затем обрезается пересечением с полигоном провинции (shapely
   intersection) — общее ребро двух соседних прямоугольников получает
   ИДЕНТИЧНУЮ волну (хэш по отсортированным координатам концов, без
   зависимости от направления обхода), без щели на стыке.
4. Внутренние рёбра клеток — волнистые; внешний контур (после обрезки
   полигоном провинции) — прямой, как исходный контур провинции.
5. Никакого brd_open: рендерим просто rings целиком (полный контур клетки),
   без разделения на "внешние"/"внутренние" сегменты — намеренно, по просьбе
   пользователя убрать саму логику связи с границей провинции. Значит слой
   визуально может задваивать линию с границей провинции — это ожидаемо.

Результат: assets/cells_lacoruna_grid.json, тот же формат rings/bbox, что и
у остальных слоёв (но БЕЗ brd_open — рендер использует rings, если brd_open
нет, см. IrregularCellProvider).

КОНТУР ПРОВИНЦИИ — не сырой из provinces.json, а предобработанный ТОЙ ЖЕ
формулой, что и у запечённого слоя "Провинции (Иберия, запечённый)" (клавиша
4, см. bake_provinces_iberia_tiles.py): `poly.buffer(GAP_FIX_PX).difference(
ocean)` — по прямой просьбе пользователя ("рисуй на основе слоя 4", не слоя
8/сырого provinces.json). Раздутие на GAP_FIX_PX лечит мелкие огрехи/
самопересечения самого полигона (щели между соседями в исходных Natural
Earth данных), а вычитание точного assets/world_ocean.json возвращает берег
к настоящей линии (не даёт раздутию вылезти в море/съесть узкие заливы) —
тот же контур, что уже проверен и даёт чистую границу на слое 4.
"""
import hashlib, json, math

SRC = "assets/provinces.json"
OCEAN_SRC = "assets/world_ocean.json"  # см. bake_provinces_iberia_tiles.py
OUT = "assets/cells_lacoruna_grid.json"
WORLD_PX = 8192.0
R_KM = 6371.0

TARGET_NAME_SUBSTR = "Coru"  # provinces.json: баг двойной UTF-8-кодировки в "ñ", см. build_cells_test.py
GRID_ROWS = 2
GRID_COLS = 2
GAP_FIX_PX = 0.15  # мировые px, ровно как в bake_provinces_iberia_tiles.py

# Волнение внутренних рёбер сетки (мировые px) — те же значения и тот же
# приём, что в build_cells_test.py (см. докстринг файла выше).
WAVE_DEPTH = 3
WAVE_AMPLITUDE = 0.12


def _round_key(p) -> tuple:
	return (round(p[0], 2), round(p[1], 2))


def _seeded_unit(*parts) -> float:
	"""Детерминированное псевдослучайное число в [0,1) из хэша аргументов —
	одно и то же ребро, пройденное с разных сторон/клеток, даёт одно и то же
	число (см. build_cells_test.py)."""
	h = hashlib.md5(repr(parts).encode()).hexdigest()
	return int(h[:8], 16) / 0xFFFFFFFF


def _displace_segment(a: tuple, b: tuple, depth: int, amplitude: float, edge_key: tuple, path: str) -> list:
	"""Рекурсивно делит отрезок a->b пополам со случайным (но детерминированным
	по edge_key+path) смещением середины по нормали."""
	if depth <= 0:
		return [a, b]
	dx, dy = b[0] - a[0], b[1] - a[1]
	length = math.hypot(dx, dy)
	if length < 1e-6:
		return [a, b]
	mx, my = (a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5
	nx, ny = -dy / length, dx / length
	r = _seeded_unit(edge_key, path) * 2.0 - 1.0
	offset = r * amplitude * length
	mx += nx * offset
	my += ny * offset
	mid = (mx, my)
	left = _displace_segment(a, mid, depth - 1, amplitude, edge_key, path + "0")
	right = _displace_segment(mid, b, depth - 1, amplitude, edge_key, path + "1")
	return left[:-1] + right


def _wavy_edge(p0: tuple, p1: tuple) -> list:
	"""Волнистая линия от p0 до p1, симметричная относительно направления
	обхода (edge_key строится по отсортированным концам)."""
	k0, k1 = _round_key(p0), _round_key(p1)
	flip = k1 < k0
	a, b = (p1, p0) if flip else (p0, p1)
	edge_key = (min(k0, k1), max(k0, k1))
	pts = _displace_segment(a, b, WAVE_DEPTH, WAVE_AMPLITUDE, edge_key, "")
	if flip:
		pts = list(reversed(pts))
	return pts


def _wavify_ring(coords: list) -> list:
	"""Кольцо (замкнутое, coords[0]==coords[-1]) -> волнистое кольцо, каждое
	ребро волнится независимо."""
	out: list = []
	n = len(coords) - 1
	for i in range(n):
		seg_pts = _wavy_edge(coords[i], coords[i + 1])
		if out:
			seg_pts = seg_pts[1:]
		out.extend(seg_pts)
	return out


def _wavify_polygon(poly):
	"""Волнит внешний контур прямоугольника сетки ДО пересечения с
	province_poly — общие рёбра соседних прямоугольников получают
	идентичную волну, внешняя граница провинции волну не наследует, так как
	отрезается пересечением уже после (см. докстринг файла)."""
	from shapely.geometry import Polygon

	wavy_ext = _wavify_ring(list(poly.exterior.coords))
	wavy = Polygon(wavy_ext)
	if not wavy.is_valid:
		wavy = wavy.buffer(0)
	return wavy


def unproject(x, y):
	lon = x / WORLD_PX * 360.0 - 180.0
	n = math.pi - 2.0 * math.pi * y / WORLD_PX
	lat = math.degrees(math.atan(math.sinh(n)))
	return lon, lat


def ring_area_km2_world_px(ring_px: list) -> float:
	ll = [unproject(x, y) for x, y in ring_px]
	lat0 = math.radians(sum(p[1] for p in ll) / len(ll))
	pts = []
	for lon, lat in ll:
		x = math.radians(lon) * math.cos(lat0) * R_KM
		y = math.radians(lat) * R_KM
		pts.append((x, y))
	a = 0.0
	n = len(pts)
	for i in range(n):
		x0, y0 = pts[i]
		x1, y1 = pts[(i + 1) % n]
		a += x0 * y1 - x1 * y0
	return abs(a) * 0.5


def main() -> None:
	from shapely.geometry import Polygon, box
	from shapely.ops import unary_union

	data = json.load(open(SRC, encoding="utf-8"))
	target = None
	for c in data["cells"]:
		if TARGET_NAME_SUBSTR in c.get("name", ""):
			target = c
			break
	if target is None:
		raise SystemExit(f"'{TARGET_NAME_SUBSTR}' не найдена в {SRC}")
	print(f"matched province: {target['name'].encode('utf-8', errors='replace')}")

	raw_poly = Polygon(target["rings"][0], target["rings"][1:])
	if not raw_poly.is_valid:
		raw_poly = raw_poly.buffer(0)

	# Та же предобработка контура, что у запечённого слоя 4 (см. докстринг
	# файла) — обрезаем океан ТОЛЬКО рядом с провинцией (не весь мир), ради
	# скорости unary_union/difference.
	pad = 5.0 + GAP_FIX_PX * 2.0
	clip_box = box(*[v + d for v, d in zip(target["bbox"], (-pad, -pad, pad, pad))])
	ocean_polys = []
	for oc in json.load(open(OCEAN_SRC, encoding="utf-8"))["cells"]:
		orings = oc.get("rings", [])
		if orings and len(orings[0]) >= 3:
			op = Polygon(orings[0], orings[1:])
			if not op.is_valid:
				op = op.buffer(0)
			if op.intersects(clip_box):
				ocean_polys.append(op.intersection(clip_box))
	ocean = unary_union(ocean_polys) if ocean_polys else None

	province_poly = raw_poly.buffer(GAP_FIX_PX)
	if ocean is not None:
		province_poly = province_poly.difference(ocean)
	if province_poly.geom_type == "MultiPolygon":
		province_poly = max(province_poly.geoms, key=lambda g: g.area)
	print(f"raw area px2={raw_poly.area:.2f}, preprocessed area px2={province_poly.area:.2f}")

	minx, miny, maxx, maxy = target["bbox"]
	print(f"provincia bbox: {target['bbox']}")

	xs = [minx + (maxx - minx) * i / GRID_COLS for i in range(GRID_COLS + 1)]
	ys = [miny + (maxy - miny) * j / GRID_ROWS for j in range(GRID_ROWS + 1)]

	out_cells = []
	cell_idx = 0
	for row in range(GRID_ROWS):
		for col in range(GRID_COLS):
			rect = box(xs[col], ys[row], xs[col + 1], ys[row + 1])
			rect_wavy = _wavify_polygon(rect)
			clipped = rect_wavy.intersection(province_poly)
			if clipped.is_empty:
				continue
			parts = [clipped] if clipped.geom_type == "Polygon" else list(clipped.geoms)
			for part in parts:
				if part.area < 1e-6:
					continue
				ext = [[round(x, 2), round(y, 2)] for x, y in part.exterior.coords]
				rings = [ext]
				for hole in part.interiors:
					rings.append([[round(x, 2), round(y, 2)] for x, y in hole.coords])
				pxs = [p[0] for p in ext]
				pys = [p[1] for p in ext]
				area_km2 = ring_area_km2_world_px(ext)
				out_cells.append({
					"id": f"lacoruna_grid_{cell_idx}",
					"name": f"Ла-Корунья (сетка) — клетка {cell_idx + 1}",
					"rings": rings,
					"bbox": [min(pxs), min(pys), max(pxs), max(pys)],
					"area_km2": round(area_km2, 1),
				})
				cell_idx += 1

	print(f"cells: {len(out_cells)}")
	for c in out_cells:
		print(f"  {c['id']}: {c['area_km2']} km2")

	json.dump({"world_px": WORLD_PX, "cells": out_cells},
			   open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
	print(f"wrote {OUT}")


if __name__ == "__main__":
	main()
