"""ТЕСТОВЫЙ проход: разбить ОДНУ область (провинцию Ла-Корунья, реальные
провинции) на несколько клеток (самый нижний уровень лестницы, см.
УРОВНЕЙ_ТЕРРИТОРИЙ.md, раздел 4). Цель — проверить подход на одном примере,
прежде чем делать это для всех 4039 областей.

Источник контура — уже готовый assets/provinces.json (build_provinces.py),
а не сырые Natural Earth данные — незачем заново скачивать/проецировать то,
что уже спроецировано в мировые пиксели (WORLD_PX=8192, Web Mercator).

Метод: обычный Voronoi (shapely.ops.voronoi_diagram) по нескольким seed-точкам
внутри полигона провинции, каждая Voronoi-ячейка обрезается по контуру
провинции. Для одного некрупного простого полигона (не архипелаг, без дырок)
этого достаточно — дыры/щели, из-за которых в сессии отказались от Voronoi
для клеток СУШИ ЦЕЛИКОМ (см. TODO.md), там были на КРУПНЫХ многоклеточных
массивах (Британия, Евразия) с сотнями клеток; на одной маленькой провинции
с 3-5 клетками риск того же класса багов пренебрежимо мал.

Внутренние рёбра (между клетками) — "волнистые" (не прямые Voronoi-линии), по
просьбе пользователя после скриншота. Тот же приём, что уже применялся для
береговой линии/границ клеток суши в удалённом build_land_cells.py (см. done.md):
рекурсивное смещение середины отрезка, детерминированное по хэшу КЛЮЧА РЕБРА
(round(x,y) обеих концевых точек, БЕЗ учёта порядка обхода) — у двух соседних
клеток, которые делят одно и то же ребро, получается ИДЕНТИЧНАЯ волна, без
щели на стыке. Волнение применяется к СЫРЫМ (ещё не обрезанным по контуру
провинции) полигонам Voronoi — то, что потом отрезает `intersection(province_poly)`,
остаётся настоящей (прямой, как в исходных данных) границей провинции, а не
волнистой — волна нужна только на СВОИХ внутренних рёбрах клеток, не на
внешнем контуре области (см. вопрос пользователя: "внутренние границы").

Результат: assets/cells_test.json — тот же формат rings/bbox, что и у
остальных слоёв клеток, плюс игровые поля id/name/area_km2 (сверху формата,
IrregularCellProvider их просто не читает и не ломается на лишних ключах),
и с этой сессии — тестовые игровые атрибуты (rельеф/покров/освоение и т.п.,
см. TEST_CELL_ATTRS ниже и ПЛОЩАДЬ_КЛЕТОК_И_ПОЛЕЗНОСТЬ.md) для проверки
подсчёта показателей клетки (area_factor/settlement_factor/rural_capacity)
по клику на карте.
"""
import hashlib, json, math, random

from shapely.ops import transform as shapely_transform

from build_water_cells_architecture_v1 import (
	GAME_WATER_LAND_MARGIN_KM,
	WARP_SEGMENT_PX,
	densify_polygon,
	km_per_world_px,
	load_world_ocean,
	warp_xy,
)

SRC = "assets/provinces_iberia.json"
OUT = "assets/cells_test.json"
WORLD_PX = 8192.0

# ТЕСТОВЫЕ игровые атрибуты по индексу клетки (порядок out_cells, см. main()) —
# НЕ проверенная реальная география, а иллюстративный набор "разной природы"
# специально для проверки формул ПЛОЩАДЬ_КЛЕТОК_И_ПОЛЕЗНОСТЬ.md по клику на
# карте (settlement_factor берётся из GameplayTables.default_settlement_factor
# по relief_type в Godot, если явно не переопределён здесь). Индекс -> клетка
# сопоставляется по площади (см. print в конце main()): чем разнообразнее
# набор освоений, тем нагляднее разница в rural_capacity при клике.
TEST_CELL_ATTRS = {
	0: {  # самая крупная (~2884 км²) — пашня на равнине
		"cell_type": "rural",
		"relief_type": "plain",
		"natural_cover_type": "cropland",
		"soil_type": "loam",
		"climate_type": "oceanic",
		"moisture_type": "humid",
		"features": [],
		"resource": "",
		"development_type": "farmland",
		"development_level": 2,
		"maturity": 0.8,
		"damage": 0.0,
		"road_level": 1,
		"irrigation_level": 0,
	},
	1: {  # самая мелкая (~590 км²) — городская периферия у порта
		"cell_type": "urban",
		"relief_type": "plain",
		"natural_cover_type": "urban",
		"soil_type": "loam",
		"climate_type": "oceanic",
		"moisture_type": "humid",
		"features": ["coast", "port_access"],
		"resource": "fish",
		"development_type": "urban_periphery",
		"development_level": 3,
		"maturity": 0.9,
		"damage": 0.0,
		"road_level": 2,
		"irrigation_level": 0,
	},
	2: {  # ~2022 км² — рыбацкое побережье
		"cell_type": "rural",
		"relief_type": "hills",
		"natural_cover_type": "meadow",
		"soil_type": "sandy",
		"climate_type": "oceanic",
		"moisture_type": "humid",
		"features": ["coast", "rocky_shore"],
		"resource": "fish",
		"development_type": "villages",
		"development_level": 1,
		"maturity": 0.6,
		"damage": 0.0,
		"road_level": 1,
		"irrigation_level": 0,
	},
	3: {  # ~2428 км² — пастбища на холмах; выбрана ПОТЕНЦИАЛЬНЫМ ЦЕНТРОМ
		# провинции для теста (по просьбе пользователя, розовая на карте —
		# см. IrregularCellProvider._load_data: цвет по золотому сечению от
		# индекса, idx=3 -> hue≈307° = розовый/пурпурный). Выбор не привязан
		# к тематике атрибутов ниже (это тестовая клетка, не реальная
		# география) — только чтобы проверить province_center_status и
		# "морская клетка обваливает столичную клетку" (см. TODO.md).
		"cell_type": "rural",
		"relief_type": "hills",
		"natural_cover_type": "scrub",
		"soil_type": "clay",
		"climate_type": "oceanic",
		"moisture_type": "humid",
		"features": [],
		"resource": "",
		"development_type": "pasture",
		"development_level": 1,
		"maturity": 0.5,
		"damage": 0.0,
		"road_level": 0,
		"irrigation_level": 0,
		"province_center_status": "potential",
	},
}
# ВНИМАНИЕ: provinces.json содержит баг двойной UTF-8-кодировки в именах
# с небазовыми латинскими буквами (существующий баг build_provinces.py /
# исходного geojson, не наш — вне рамок этого тестового скрипта). "ñ" ломает
# точное сравнение строк, поэтому ищем по надёжной ASCII-подстроке.
TARGET_NAME_SUBSTR = "Coru"
N_CELLS = 6
R_KM = 6371.0
SEED = 42
MIN_CELL_AREA_KM2 = 120.0
LAND_WARP_MULTIPLIER = 1.0

# Волнение внутренних рёбер клеток (мировые px, см. docstring выше).
WAVE_DEPTH = 3           # число рекурсивных делений ребра пополам
WAVE_AMPLITUDE = 0.12    # смещение середины, доля от длины ТЕКУЩЕГО подотрезка


def _round_key(p) -> tuple:
	return (round(p[0], 2), round(p[1], 2))


def _seeded_unit(*parts) -> float:
	"""Детерминированное псевдослучайное число в [0,1) из хэша аргументов —
	НЕ random.random() (см. done.md: важно, чтобы одно и то же ребро,
	пройденное с разных сторон/клеток, давало одно и то же число)."""
	h = hashlib.md5(repr(parts).encode()).hexdigest()
	return int(h[:8], 16) / 0xFFFFFFFF


def _displace_segment(a: tuple, b: tuple, depth: int, amplitude: float, edge_key: tuple, path: str) -> list:
	"""Рекурсивно делит отрезок a->b пополам со случайным (но детерминированным
	по edge_key+path) смещением середины по нормали. Возвращает список точек
	от a до b включительно (без дублей на стыках рекурсии)."""
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
	"""Волнистая линия от p0 до p1. edge_key строится по ОТСОРТИРОВАННЫМ
	концам (не зависит от направления обхода) — соседняя клетка, идущая по
	тому же ребру в обратную сторону, получает те же самые точки, только в
	обратном порядке (без щели на стыке двух клеток)."""
	k0, k1 = _round_key(p0), _round_key(p1)
	flip = k1 < k0
	a, b = (p1, p0) if flip else (p0, p1)
	edge_key = (min(k0, k1), max(k0, k1))
	pts = _displace_segment(a, b, WAVE_DEPTH, WAVE_AMPLITUDE, edge_key, "")
	if flip:
		pts = list(reversed(pts))
	return pts


def _wavify_ring(coords: list) -> list:
	"""Кольцо (замкнутое, coords[0]==coords[-1]) -> волнистое кольцо. Каждое
	РЕБРО волнится независимо (не всё кольцо целиком), см. docstring файла."""
	out: list = []
	n = len(coords) - 1  # последняя точка = первая (замкнутое кольцо shapely)
	for i in range(n):
		seg_pts = _wavy_edge(coords[i], coords[i + 1])
		if out:
			seg_pts = seg_pts[1:]  # не дублировать стык с предыдущим ребром
		out.extend(seg_pts)
	return out


# Порог "лежит на границе провинции" (мировые px) — см. обсуждение с
# пользователем: рёбра клетки, полученные из intersection() с province_poly,
# лежат на исходном контуре с точностью до погрешности плавающей точки
# (много меньше 0.05); волнистые ВНУТРЕННИЕ рёбра смещены на амплитуду волны
# (много больше 0.05 для любого не микроскопического сегмента).
BOUNDARY_TOL = 0.05


def _split_border_chains(ext_coords: list, province_boundary) -> tuple:
	"""ext_coords — замкнутое кольцо клетки (первая точка == последней, как
	отдаёт shapely exterior.coords). Возвращает пару списков ОТКРЫТЫХ цепочек
	точек, разделённых по тому же признаку (лежит ребро на границе провинции
	или нет):

	- interior_chains — рёбра клетки, НЕ лежащие на границе провинции (стык с
	  соседней клеткой внутри провинции). Слой "C" рисует их alpha=0
	  (BORDER_STYLE["cell"] в TileMapViewer.gd) — они не должны быть видны.
	- boundary_chains — рёбра, СОВПАДАЮЩИЕ с внешним контуром провинции. По
	  прямой просьбе пользователя 2026-07-11 ("внешнюю границу оставить,
	  внутренние — без контуров") слой "C" рисует ИХ отдельным, более заметным
	  стилем (BORDER_STYLE["cell_boundary"]), а не полагается только на
	  отдельный слой области "4"/"8" — тот факт, что эти два контура (клетки
	  здесь и области там) геометрически совпадают, роли не играет: раньше
	  дублирование именно ВНУТРЕННИХ (волнистых) рёбер давало "мыло" на стыке,
	  внешний контур провинции у обоих слоёв идентичен (не волнистый).
	"""
	from shapely.geometry import Point

	n = len(ext_coords) - 1
	if n < 2:
		return [], []
	is_interior = []
	for i in range(n):
		a, b = ext_coords[i], ext_coords[i + 1]
		mx, my = (a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5
		is_interior.append(province_boundary.distance(Point(mx, my)) > BOUNDARY_TOL)

	def _chains_for(flags: list) -> list:
		if all(flags):
			# Клетка целиком на этой стороне (все рёбра — внутренние ИЛИ все —
			# граница провинции) — вернуть как ОДНУ замкнутую цепочку.
			return [ext_coords[:]]
		if not any(flags):
			return []
		# Начинаем с ребра, где предыдущее НЕ подходит, а текущее подходит —
		# чтобы не разрывать цепочку, "перетекающую" через индекс 0 кольца.
		start = next(i for i in range(n) if flags[i] and not flags[i - 1])
		chains: list = []
		chain: list = []
		for k in range(n):
			i = (start + k) % n
			if flags[i]:
				if not chain:
					chain = [ext_coords[i]]
				chain.append(ext_coords[(i + 1) % n])
			else:
				if len(chain) >= 2:
					chains.append(chain)
				chain = []
		if len(chain) >= 2:
			chains.append(chain)
		return chains

	is_boundary = [not v for v in is_interior]
	return _chains_for(is_interior), _chains_for(is_boundary)


def _wavify_polygon(poly):
	"""Применяет _wavify_ring к внешнему контуру полигона (у сырых
	Voronoi-регионов дырок не бывает). При самопересечении после волнения —
	buffer(0) фикс, та же схема, что была в удалённом build_land_cells.py/
	_add_wavy_cell (см. done.md)."""
	from shapely.geometry import Polygon

	wavy_ext = _wavify_ring(list(poly.exterior.coords))
	wavy = Polygon(wavy_ext)
	if not wavy.is_valid:
		wavy = wavy.buffer(0)
	return wavy


def _strong_warp_polygon(poly):
	dense = densify_polygon(poly, max(3.2, WARP_SEGMENT_PX * 0.55))
	def _warp(x, y, z=None):
		wx, wy = warp_xy(x, y)
		return x + (wx - x) * LAND_WARP_MULTIPLIER, y + (wy - y) * LAND_WARP_MULTIPLIER
	warped = shapely_transform(_warp, dense)
	if not warped.is_valid:
		warped = warped.buffer(0)
	return warped


def _clip_ocean_margin(province_poly):
	from shapely.geometry import box
	from shapely.ops import unary_union

	margin_px = _ocean_margin_px(province_poly)
	clip_box = box(*province_poly.bounds).buffer(margin_px + 3.0)
	ocean_parts = []
	for ocean_poly in load_world_ocean():
		if ocean_poly.intersects(clip_box):
			part = ocean_poly.intersection(clip_box)
			if not part.is_empty:
				ocean_parts.append(part)
	if not ocean_parts:
		return province_poly
	ocean_margin = unary_union(ocean_parts).buffer(margin_px, quad_segs=8)
	clipped = province_poly.difference(ocean_margin)
	if clipped.is_empty:
		return province_poly
	if clipped.geom_type == "MultiPolygon":
		clipped = max(clipped.geoms, key=lambda g: g.area)
	if not clipped.is_valid:
		clipped = clipped.buffer(0)
	return clipped


def _ocean_margin_px(poly) -> float:
	return GAME_WATER_LAND_MARGIN_KM / max(km_per_world_px(poly.representative_point().y), 0.001)


def _trim_open_chains_to_land(chains: list, province_poly, source_poly) -> list:
	"""Keep drawn cell dividers out of the coastal ocean-overlap strip.

	The cell polygons are already clipped by the 2 km ocean margin, but at high
	zoom a divider ending exactly on that clipped boundary still reads as a tail
	inside the cyan sea overlay. For the visual `brd_open` lines only, trim one
	more game margin inward. The actual cell `rings` stay untouched for picking.
	"""
	from shapely.geometry import LineString, MultiLineString

	margin_px = _ocean_margin_px(source_poly)
	line_mask = province_poly.buffer(-margin_px, join_style=2)
	if line_mask.is_empty:
		line_mask = province_poly.buffer(-margin_px * 0.35, join_style=2)
	if line_mask.is_empty:
		return chains

	out = []
	for chain in chains:
		if len(chain) < 2:
			continue
		trimmed = LineString(chain).intersection(line_mask)
		parts = []
		if trimmed.is_empty:
			continue
		if isinstance(trimmed, LineString):
			parts = [trimmed]
		elif isinstance(trimmed, MultiLineString):
			parts = list(trimmed.geoms)
		else:
			parts = [g for g in getattr(trimmed, "geoms", []) if isinstance(g, LineString)]
		for part in parts:
			coords = [[round(x, 2), round(y, 2)] for x, y in part.coords]
			if len(coords) >= 2:
				out.append(coords)
	return out


def unproject(x, y):
	"""Обратная функция к project() из build_provinces.py (Web Mercator)."""
	lon = x / WORLD_PX * 360.0 - 180.0
	n = math.pi - 2.0 * math.pi * y / WORLD_PX
	lat = math.degrees(math.atan(math.sinh(n)))
	return lon, lat


def ring_area_km2_world_px(ring_px: list) -> float:
	"""Площадь кольца (мировые px) в км² — переводим в lon/lat и считаем
	локальной равнопромежуточной проекцией вокруг среднего lat (тот же метод,
	что ring_area_km2_lonlat в build_provinces.py)."""
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


def make_seeds(poly, n: int, rng: random.Random) -> list:
	"""n точек внутри polygon — джиттер по регулярной сетке над bbox,
	отбрасываем точки вне полигона, пока не наберём n (тот же приём, что и в
	build_land_cells_v2.py, но без региональной плотности — тут она не нужна)."""
	minx, miny, maxx, maxy = poly.bounds
	seeds = []
	attempts = 0
	while len(seeds) < n and attempts < 2000:
		attempts += 1
		x = rng.uniform(minx, maxx)
		y = rng.uniform(miny, maxy)
		from shapely.geometry import Point
		p = Point(x, y)
		if poly.contains(p):
			# минимальная дистанция между семенами, чтобы не слипались в углу
			too_close = False
			min_dist = (maxx - minx + maxy - miny) * 0.5 / (n * 1.5)
			for sx, sy in seeds:
				if (sx - x) ** 2 + (sy - y) ** 2 < min_dist ** 2:
					too_close = True
					break
			if not too_close:
				seeds.append((x, y))
	return seeds


def main() -> None:
	from shapely.geometry import shape, mapping, MultiPoint, Polygon
	from shapely.ops import voronoi_diagram

	data = json.load(open(SRC, encoding="utf-8"))
	target = None
	for c in data["cells"]:
		if TARGET_NAME_SUBSTR in c.get("name", ""):
			target = c
			break
	if target is None:
		raise SystemExit(f"'{TARGET_NAME_SUBSTR}' не найдена в {SRC}")
	print(f"matched province: {target['name'].encode('utf-8', errors='replace')}")

	raw_province_poly = Polygon(target["rings"][0], target["rings"][1:])
	province_poly = _clip_ocean_margin(raw_province_poly)
	print(f"provincia bbox: {target['bbox']}")

	rng = random.Random(SEED)
	seeds = make_seeds(province_poly, N_CELLS, rng)
	print(f"seeds: {len(seeds)}")

	vd = voronoi_diagram(MultiPoint(seeds), envelope=province_poly.envelope.buffer(50.0))
	province_boundary = province_poly.boundary

	out_cells = []
	cell_idx = 0
	for region in vd.geoms:
		# Волним ДО обрезки провинцией — общие рёбра между соседними
		# Voronoi-регионами получают одинаковую волну (см. docstring), а
		# после intersection() внешний контур области остаётся прямым, как
		# в исходных данных (волна режется вместе с остальным).
		region_wavy = _wavify_polygon(region) if region.geom_type == "Polygon" else region
		clipped = region_wavy.intersection(province_poly)
		if clipped.is_empty:
			continue
		parts = []
		if clipped.geom_type == "Polygon":
			parts = [clipped]
		elif clipped.geom_type == "MultiPolygon":
			parts = list(clipped.geoms)
		for part in parts:
			if part.area < 1e-6:
				continue
			ext = [[round(x, 2), round(y, 2)] for x, y in part.exterior.coords]
			rings = [ext]
			for hole in part.interiors:
				rings.append([[round(x, 2), round(y, 2)] for x, y in hole.coords])
			xs = [p[0] for p in ext]
			ys = [p[1] for p in ext]
			area_km2 = ring_area_km2_world_px(ext)
			if area_km2 < MIN_CELL_AREA_KM2:
				continue
			brd_open, _ = _split_border_chains(ext, province_boundary)
			brd_open = _trim_open_chains_to_land(brd_open, province_poly, raw_province_poly)
			cell_out = {
				"id": f"lacoruna_{cell_idx}",
				"name": f"Ла-Корунья — клетка {cell_idx + 1}",
				"rings": rings,
				"brd_open": brd_open,
				"bbox": [min(xs), min(ys), max(xs), max(ys)],
				"area_km2": round(area_km2, 1),
			}
			cell_out.update(TEST_CELL_ATTRS.get(cell_idx, {}))
			out_cells.append(cell_out)
			cell_idx += 1

	print(f"cells: {len(out_cells)}")
	for c in out_cells:
		print(f"  {c['id']}: {c['area_km2']} km2")

	json.dump({"world_px": WORLD_PX, "cells": out_cells},
			   open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
	print(f"wrote {OUT}")


if __name__ == "__main__":
	main()
