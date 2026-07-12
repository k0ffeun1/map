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
берём ближайшую точку к провинции в пределах NEAREST_FALLBACK_PX.

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
# ИМЯ ПРОВИНЦИИ ровно как в provinces_iberia.json (там баг двойной кодировки
# у нелатинских имён из исходного geojson, "La CoruÃ±a" — не опечатка здесь).
# "La CoruÃ±a": маяк/полуостров Torre de Hércules — исторический порт и
# рыбацкий город стоял на самом полуострове, а не в современном центре южнее.
# "Sevilla": реальный город стоит в ~80 км от моря вверх по Гвадалквивиру;
# провинции вручную добавлен прибрежный кусок земли (см.
# patch_sevilla_coastal_access.py, прямая просьба пользователя) — маркер
# сдвинут к этому новому побережью, а не к реальному историческому центру
# города, чтобы наглядно показать его как порт.
CITY_POSITION_OVERRIDES = {
	"La CoruÃ±a": (-8.4067, 43.3853),
	"Sevilla": (-6.40, 36.83),
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

	out_cities = []
	no_match = 0
	for cell in provinces["cells"]:
		poly = Polygon(cell["rings"][0], cell["rings"][1:])
		if not poly.is_valid:
			poly = poly.buffer(0)

		cand_idx = tree.query(poly)
		inside = [city_points[int(i)] for i in cand_idx if poly.contains(pts_geom[int(i)])]

		best = None
		if inside:
			best = max(inside, key=lambda c: c["pop"])
		else:
			# ближайшая точка к полигону в пределах NEAREST_FALLBACK_PX
			nearest_d, nearest_c = None, None
			for c in city_points:
				d = poly.distance(Point(c["pos"]))
				if d <= NEAREST_FALLBACK_PX and (nearest_d is None or d < nearest_d):
					nearest_d, nearest_c = d, c
			best = nearest_c

		if best is None:
			no_match += 1
			continue

		pos = best["pos"]
		if cell["name"] in CITY_POSITION_OVERRIDES:
			pos = project(*CITY_POSITION_OVERRIDES[cell["name"]])

		out_cities.append({
			"name": best["name"],
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
