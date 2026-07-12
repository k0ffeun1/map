"""Ручная историческая правка assets/provinces.json: у провинции "Sevilla" в
реальных административных границах НЕТ выхода к морю (~80 км вверх по
Гвадалквивиру от Атлантики), но исторически (с XV века, до заиливания реки
и постройки порта в Кадисе) Севилья была ГЛАВНЫМ атлантическим портом
Испании. По прямой просьбе пользователя (упрощённый вариант, без повторения
формы русла реки) — забираем прибрежный кусок земли у "CÃ¡diz"/"Huelva"
(двойная UTF-8-кодировка нелатинских имён — не опечатка, см. done.md/сессию)
в районе устья Гвадалквивира и присоединяем его к "Sevilla".

Не запускается в Godot — отдельный шаг подготовки данных, ПЕРЕД
build_provinces_iberia.py/bake_provinces_iberia_tiles.py (их надо перезапустить
после этого патча, чтобы слой "4" подхватил новую границу).
"""
import json, math

SRC = "assets/provinces.json"
WORLD_PX = 8192.0

# Прибрежный клин у устья Гвадалквивира (Санлукар-де-Баррамеда/Доньяна) —
# берём ТОЛЬКО пересечение с реальной сушей доноров, поэтому западная/южная
# граница клина сама упрётся в настоящую береговую линию Huelva/CÃ¡diz.
WEDGE_LONLAT = (-6.55, 36.75, -6.05, 37.15)  # (lon_min, lat_min, lon_max, lat_max)

SEVILLA_NAME = "Sevilla"
DONOR_NAMES = ["CÃ¡diz", "Huelva"]


def project(lon: float, lat: float) -> tuple:
	lat = max(-85.05112878, min(85.05112878, lat))
	x = (lon + 180.0) / 360.0 * WORLD_PX
	lat_rad = math.radians(lat)
	y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
	return x, y


def _cell_to_polygon(cell):
	from shapely.geometry import Polygon
	p = Polygon(cell["rings"][0], cell["rings"][1:])
	if not p.is_valid:
		p = p.buffer(0)
	return p


def _polygon_to_cells(geom, template: dict) -> list:
	from shapely.geometry import Polygon
	parts = [geom] if isinstance(geom, Polygon) else list(geom.geoms)
	out = []
	for piece in parts:
		if piece.is_empty or piece.area < 1e-6:
			continue
		ext = [[round(x, 2), round(y, 2)] for x, y in piece.exterior.coords]
		rings = [ext]
		for hole in piece.interiors:
			rings.append([[round(x, 2), round(y, 2)] for x, y in hole.coords])
		xs = [q[0] for q in ext]
		ys = [q[1] for q in ext]
		new_cell = dict(template)
		new_cell["rings"] = rings
		new_cell["bbox"] = [min(xs), min(ys), max(xs), max(ys)]
		out.append(new_cell)
	return out


def main() -> None:
	from shapely.geometry import box
	from shapely.ops import unary_union

	data = json.load(open(SRC, encoding="utf-8"))
	cells = data["cells"]

	lon0, lat0, lon1, lat1 = WEDGE_LONLAT
	x0, y0 = project(lon0, lat1)  # север -> меньший y
	x1, y1 = project(lon1, lat0)  # юг -> больший y
	wedge = box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

	sevilla_idx = [i for i, c in enumerate(cells) if c["name"] == SEVILLA_NAME]
	if not sevilla_idx:
		raise SystemExit(f"'{SEVILLA_NAME}' не найдена в {SRC}")

	donor_idx = [i for i, c in enumerate(cells) if c["name"] in DONOR_NAMES]
	print(f"Sevilla: {len(sevilla_idx)} кусок(ов), доноров-кандидатов: {len(donor_idx)}")

	chunks = []  # куски суши доноров внутри клина -> отдадим Sevilla
	out_cells = []
	trimmed_count = 0
	for i, c in enumerate(cells):
		if i in donor_idx:
			geom = _cell_to_polygon(c)
			if geom.intersects(wedge):
				piece = geom.intersection(wedge)
				if not piece.is_empty and piece.area > 1e-6:
					chunks.append(piece)
					remainder = geom.difference(wedge)
					trimmed_count += 1
					out_cells.extend(_polygon_to_cells(remainder, c))
					continue
			out_cells.append(c)
			continue
		if i == sevilla_idx[0]:
			continue  # добавим объединённой ниже
		out_cells.append(c)

	sevilla_geom = _cell_to_polygon(cells[sevilla_idx[0]])
	new_sevilla_geom = unary_union([sevilla_geom] + chunks)
	new_sevilla_cells = _polygon_to_cells(new_sevilla_geom, cells[sevilla_idx[0]])
	out_cells.extend(new_sevilla_cells)

	print(f"  доноров подрезано: {trimmed_count}, кусков земли отдано Sevilla: {len(chunks)}")
	print(f"  Sevilla: было 1 кусок -> стало {len(new_sevilla_cells)}")

	data["cells"] = out_cells
	json.dump(data, open(SRC, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
	print(f"wrote {SRC}, всего клеток: {len(out_cells)} (было {len(cells)})")


if __name__ == "__main__":
	main()
