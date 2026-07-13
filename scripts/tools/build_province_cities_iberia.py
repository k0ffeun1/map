"""Главный (по населению) реальный город на каждую провинцию региона Иберия
(тот же регион, что у слоя "4", см. build_provinces_iberia.py) — координаты
из Natural Earth ne_10m_populated_places (реальное историческое место города,
а не геометрический центр провинции).

Источник (скачан один раз):
  curl -L -o scripts/tools/_work/ne_10m_populated_places.zip \\
    https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_populated_places.zip
  (unzip -> scripts/tools/_work/ne_10m_populated_places/*.shp, затем shp ->
  geojson через pyshp -> scripts/tools/_work/ne_10m_populated_places.geojson)

Алгоритм: для каждой провинции (assets/provinces_iberia.json) ищем ТОЧКИ
городов, которые физически попадают внутрь её полигона (point-in-polygon), и
берём из них ту, что с наибольшим POP_MAX (крупнейший реальный город
провинции). Если ни одна точка не попала внутрь (мелкая провинция, город на
самом краю после упрощения контура border simplify в build_provinces.py) —
берём ближайшую точку к провинции в пределах NEAREST_FALLBACK_PX, но ТОЛЬКО
если эта точка не принадлежит уже какой-то ДРУГОЙ провинции (см. _claimed_ids
ниже) — иначе провинция без своего города в датасете "крала" бы маркер
соседней провинции (найдено пользователем в сессии: Луго осталась без
видимого маркера, потому что её fallback увёл на Оренсе — тот уже законно
принадлежал провинции Ourense, а Луго вообще нет в ne_10m_populated_places
10m, слишком маленький город для этого разрешения датасета).

После подбора городов — отдельный проход "прижимания к берегу" (по прямой
просьбе пользователя): город, чей центр НЕ касается моря, но лежит ближе
SNAP_TO_COAST_KM км к береговой линии (assets/world_ocean.json) — переносится
на сам берег (ближайшая точка береговой линии + маленький отступ вглубь
суши, чтобы не оказаться ровно на границе вода/земля). Города УЖЕ на берегу
(< TOUCH_EPSILON_KM — этот зазор объясняется упрощением контуров, не
переносим повторно) и настоящие внутренние города (дальше SNAP_TO_COAST_KM)
не трогаются — иначе реально сухопутные центры вроде Тизи-Узу/Сантарена
(~17-20 км до берега в этих упрощённых контурах, но НЕ портовые города)
уехали бы на побережье безо всякого исторического основания.

Не запускается в Godot — отдельный шаг подготовки данных. Результат:
assets/province_cities_iberia.json ({"world_px":...,
"cities":[{"name":..., "province":..., "pos":[x,y]}]}).
"""
import json, math

PROVINCES_SRC = "assets/provinces_iberia.json"
CITIES_SRC = "scripts/tools/_work/ne_10m_populated_places.geojson"
OCEAN_SRC = "assets/world_ocean.json"
OUT = "assets/province_cities_iberia.json"
WORLD_PX = 8192.0

NEAREST_FALLBACK_PX = 15.0  # ~ несколько км на этом масштабе, см. WORLD_PX

SNAP_TO_COAST_KM = 12.0    # порог "рядом с берегом, но не на нём" (решение пользователя в сессии)
TOUCH_EPSILON_KM = 2.0     # уже фактически на берегу (шум от упрощения контура) — не трогаем повторно
INLAND_NUDGE_PX = 1.0      # маленький отступ от точки на линии берега обратно к городу, чтобы не встать ровно на границу вода/суша

# Ручные поправки позиции конкретных городов (lon, lat) — когда точка из
# ne_10m_populated_places указывает на административный центр/вокзал, а не на
# исторически значимое место (по прямой правке пользователя на карте). Ключ —
# ИМЯ ПРОВИНЦИИ ровно как в provinces_iberia.json (2026-07-13: двойная
# UTF-8-кодировка имён починена в build_provinces.py, имена теперь нормальные).
#
# 2026-07-12: "La Coruña" — маяк Torre de Hércules на самом кончике
# полуострова (это не город, а сторожевая башня в стороне от него) заменён
# на настоящий исторический центр Старого города — площадь Мария-Пита
# (Plaza de María Pita, Cidade Vella).
#
# "Sevilla" — ПРЯМАЯ ПРОСЬБА ПОЛЬЗОВАТЕЛЯ 2026-07-13: маркер стоит НЕ на
# настоящем историческом месте города (это было бы ~80 км вверх по реке от
# моря, см. Кафедральный собор/Хиральда), а на побережье — на прибрежном
# клине земли, который patch_sevilla_coastal_access.py отобрал у "Cádiz"/
# "Huelva" и присоединил к "Sevilla" (см. этот скрипт), чтобы наглядно
# показать Севилью портом. Сознательное расхождение с реальной историей
# ради визуала карты — не путать с "La Coruña" выше, там наоборот важно
# было настоящее место.
#
# Остальные записи ниже (Cádiz/Portalegre/Castelo Branco/Guarda/Bragança/
# Vila Real/Braga/Santarém, добавлены 2026-07-13) — БЕЗ особой истории,
# просто подобраны пользователем ВРУЧНУЮ перетаскиванием маркера в игре (см.
# ProvinceCityMarkersLayer.gd/кнопка "Сохранить города" в TileMapViewer.gd) и
# перенесены сюда из assets/province_cities_iberia.json, чтобы не потеряться
# при следующей перегенерации этим скриптом.
CITY_POSITION_OVERRIDES = {
	"La Coruña": (-8.4083, 43.3712),
	"Sevilla": (-6.1545, 36.9042),
	"Cádiz": (-6.1770, 36.5135),
	"Portalegre": (-7.5823, 39.2904),
	"Castelo Branco": (-7.4914, 39.8683),
	"Guarda": (-7.2343, 40.5682),
	"Bragança": (-6.8432, 41.8169),
	"Vila Real": (-7.6364, 41.4322),
	"Braga": (-8.1501, 41.5892),
	"Santarém": (-8.5997, 39.0779),
}

# Реальные областные центры, которых физически НЕТ в ne_10m_populated_places
# (10m-разрешение содержит не каждый город — большинство этих провинциальных
# центров просто слишком малы для этого датасета) — ключ снова ИМЯ
# ПРОВИНЦИИ, значение (lon, lat, "имя"). Без этого провинция получала бы
# город соседа через fallback (см. докстринг выше) или вообще оставалась
# пустой (найдено пользователем в сессии — 21 провинция без маркера после
# того, как fallback перестал воровать чужие точки).
MISSING_CITY_OVERRIDES = {
	"Lugo": (-7.5567, 43.0097, "Луго"),
	"Ariège": (1.6053, 42.9646, "Фуа"),
	"Aude": (2.3491, 43.2130, "Каркассон"),
	"Aveyron": (2.5734, 44.3499, "Родез"),
	"Aïn Defla": (1.9679, 36.2642, "Айн-Дефла"),
	"Ciudad Real": (-3.9272, 38.9848, "Сьюдад-Реаль"),
	"Cuenca": (-2.1374, 40.0704, "Куэнка"),
	"Cáceres": (-6.3722, 39.4753, "Касерес"),
	"Gerona": (2.8214, 41.9794, "Жирона"),
	"Gers": (0.5866, 43.6470, "Ош"),
	"Huesca": (-0.4090, 42.1401, "Уэска"),
	"Lozère": (3.5013, 44.5177, "Манд"),
	"Lérida": (0.6200, 41.6176, "Льейда"),
	"Palencia": (-4.5114, 42.0640, "Паленсия"),  # 2026-07-13: сдвинута вручную (см. CITY_POSITION_OVERRIDES выше)
	"Segovia": (-4.1290, 40.9429, "Сеговия"),
	"Soria": (-2.4637, 41.7665, "Сория"),
	"Tarn": (2.1480, 43.9298, "Альби"),
	"Tarn-et-Garonne": (1.3540, 44.0181, "Монтобан"),
	"Teruel": (-1.1065, 40.3456, "Теруэль"),
	"Tipaza": (2.4474, 36.5892, "Типаза"),
	"Zamora": (-5.7446, 41.5033, "Самора"),
	# "Ávila" — двойная UTF-8-кодировка в исходнике даёт "Ã" + непечатный
	# control-байт \x81 + "vila" (НЕ просто "Ãvila" — тот же баг кодировки,
	# что и у остальных нелатинских имён, но здесь ещё и невидимый байт,
	# который нельзя надёжно набрать буквально — только unicode-escape).
	"Ávila": (-4.6982, 40.6566, "Авила"),
}


def project(lon: float, lat: float) -> tuple:
	lat = max(-85.05112878, min(85.05112878, lat))
	x = (lon + 180.0) / 360.0 * WORLD_PX
	lat_rad = math.radians(lat)
	y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
	return x, y


def unproject_lat(y: float) -> float:
	n = math.pi - 2.0 * math.pi * y / WORLD_PX
	return math.degrees(math.atan(math.sinh(n)))


def _km_per_px_at(y: float) -> float:
	"""Масштаб Web-Mercator сжимается к полюсам (cos(lat)) — без поправки на
	широту один и тот же мировой px означал бы разное число км в Испании и,
	например, у Алжира."""
	lat = unproject_lat(y)
	return (40075.0 / WORLD_PX) * math.cos(math.radians(lat))


def _snap_cities_to_coast(out_cities: list) -> None:
	from shapely.geometry import Polygon, Point
	from shapely.ops import unary_union

	ocean = json.load(open(OCEAN_SRC, encoding="utf-8"))
	polys = []
	for c in ocean["cells"]:
		p = Polygon(c["rings"][0], c["rings"][1:])
		if not p.is_valid:
			p = p.buffer(0)
		polys.append(p)
	coastline = unary_union(polys).boundary

	snapped = 0
	for city in out_cities:
		pt = Point(city["pos"])
		km_per_px = _km_per_px_at(city["pos"][1])
		d_km = pt.distance(coastline) * km_per_px
		if d_km <= TOUCH_EPSILON_KM or d_km > SNAP_TO_COAST_KM:
			continue

		nearest_on_coast = coastline.interpolate(coastline.project(pt))
		nx, ny = nearest_on_coast.x, nearest_on_coast.y
		dir_x, dir_y = pt.x - nx, pt.y - ny
		dir_len = math.hypot(dir_x, dir_y)
		if dir_len > 1e-6:
			nx += dir_x / dir_len * INLAND_NUDGE_PX
			ny += dir_y / dir_len * INLAND_NUDGE_PX

		print(f"  прижат к берегу: {city['province']} -> {city['name']} "
			  f"({d_km:.1f} км -> ~0 км)")
		city["pos"] = [round(nx, 2), round(ny, 2)]
		snapped += 1

	print(f"прижато к берегу городов: {snapped}")


def main() -> None:
	from shapely.geometry import Polygon, Point
	from shapely.strtree import STRtree

	provinces = json.load(open(PROVINCES_SRC, encoding="utf-8"))
	cities_raw = json.load(open(CITIES_SRC, encoding="utf-8"))

	city_points = []
	for f in cities_raw["features"]:
		props = f["properties"]
		lon, lat = f["geometry"]["coordinates"]
		x, y = project(lon, lat)
		name = props.get("NAME_RU") or props.get("NAME") or props.get("NAMEASCII") or "?"
		pop = props.get("POP_MAX") or props.get("POP_MIN") or 0
		city_points.append({"pos": (x, y), "name": name, "pop": pop})

	pts_geom = [Point(c["pos"]) for c in city_points]
	tree = STRtree(pts_geom)

	polys = []
	for cell in provinces["cells"]:
		p = Polygon(cell["rings"][0], cell["rings"][1:])
		if not p.is_valid:
			p = p.buffer(0)
		polys.append(p)

	# Точки, которые уже ЗАКОННО принадлежат какой-то провинции (попадают
	# внутрь её полигона) — при fallback-поиске соседям их брать нельзя,
	# иначе провинция без своего города в датасете крала бы маркер соседней
	# провинции (см. докстринг выше).
	claimed_ids = set()
	for p in polys:
		for i in tree.query(p):
			i = int(i)
			if p.contains(pts_geom[i]):
				claimed_ids.add(i)

	out_cities = []
	no_match = 0
	for cell, poly in zip(provinces["cells"], polys):
		cand_idx = tree.query(poly)
		inside = [city_points[int(i)] for i in cand_idx if poly.contains(pts_geom[int(i)])]

		best = None
		if inside:
			best = max(inside, key=lambda c: c["pop"])
		else:
			# ближайшая СВОБОДНАЯ точка (не принадлежит другой провинции) в
			# пределах NEAREST_FALLBACK_PX.
			nearest_d, nearest_c = None, None
			for i, c in enumerate(city_points):
				if i in claimed_ids:
					continue
				d = poly.distance(Point(c["pos"]))
				if d <= NEAREST_FALLBACK_PX and (nearest_d is None or d < nearest_d):
					nearest_d, nearest_c = d, c
			best = nearest_c

		name = best["name"] if best else None
		pos = best["pos"] if best else None

		if cell["name"] in MISSING_CITY_OVERRIDES:
			lon, lat, override_name = MISSING_CITY_OVERRIDES[cell["name"]]
			pos = project(lon, lat)
			name = override_name
		elif cell["name"] in CITY_POSITION_OVERRIDES:
			pos = project(*CITY_POSITION_OVERRIDES[cell["name"]])

		if pos is None:
			no_match += 1
			continue

		out_cities.append({
			"name": name,
			"province": cell["name"],
			"pos": [round(pos[0], 2), round(pos[1], 2)],
		})

	print(f"провинций: {len(provinces['cells'])}, городов найдено: {len(out_cities)}, "
		  f"без города: {no_match}")

	_snap_cities_to_coast(out_cities)

	json.dump({"world_px": WORLD_PX, "cities": out_cities},
			   open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
	print(f"wrote {OUT}")


if __name__ == "__main__":
	main()
