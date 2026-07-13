"""Офлайн-препроцессинг: РЕАЛЬНЫЕ административные единицы первого уровня
(штаты/области/республики/провинции) по всему миру — Natural Earth
ne_10m_admin_1_states_provinces (8535 полигонов, включая Мордовию, Марий Эл,
Галисию, любой штат США и т.п. — см. TODO.md, решение сессии: синтетические
Voronoi-клетки (build_land_cells_v2.py, удалён) заменены реальными границами).

Это ПЕРВЫЙ, минимальный проход — просто спроецировать реальный контур в
игровые координаты и показать на карте, БЕЗ волнения/сглаживания/дальнейшей
нарезки (это агрегированные РЕАЛЬНЫЕ административные границы, они уже
"настоящие", в отличие от синтетических Voronoi-клеток, которым нужно было
имитировать органичный вид).

Источник (скачан один раз):
  curl -L -o scripts/tools/_work/ne_10m_admin_1_states_provinces.zip \\
    https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_1_states_provinces.zip
  (unzip, затем shp -> geojson через pyshp: scripts/tools/_work/ne_10m_admin_1_states_provinces.geojson)

Не запускается в Godot — отдельный шаг подготовки данных. Результат:
assets/provinces.json — тот же формат, что у land_sea.json
({"world_px":...,"cells":[{"rings":...,"bbox":...,"name":...}]}).
"""
import json, math, time

SRC = "scripts/tools/_work/ne_10m_admin_1_states_provinces.geojson"
OUT = "assets/provinces.json"
WORLD_PX = 8192.0

# Те же полярные пороги, что у остальных слоёв (build_land_sea.py и т.п.).
LAT_NORTH = 76.0
LAT_SOUTH = -58.0

SIMPLIFY_TOLERANCE_DEG = 0.01  # как у build_land_sea.py — лёгкое упрощение
MIN_PIECE_AREA_KM2 = 5.0
R_KM = 6371.0

# Точечное слияние: Natural Earth для НЕКОТОРЫХ стран смешивает уровень
# детализации — часть страны как обычно (штат/область), а часть — вдруг
# районами/муниципалитетами (см. обсуждение в сессии: Лондон в UK — 29
# districts/boroughs вместо одного "Большой Лондон", как остальная Англия).
# Ключ — (admin, region) из полей датасета, значение — имя итоговой
# объединённой области. ТОЛЬКО эти группы сливаются в один полигон, всё
# остальное (включая другие "мелкие" регионы типа Словении/Латвии — те не
# подтверждены пользователем как проблема) остаётся как в источнике.
MERGE_GROUPS = {
	("United Kingdom", "Greater London"): "Большой Лондон",
}

# Страны, чьи острова НЕ сливаются в одну геометрию (атоллы Мальдив физически
# не касаются друг друга — обычное слияние по соседству их не объединит, а
# насильно unary_union через океан дал бы кляксу), но красятся ОДНИМ цветом
# (см. "color_key" в main()/IrregularCellProvider.gd — небольшое расширение
# формата: цвет клетки обычно берётся по её порядковому номеру в массиве,
# color_key переопределяет это на хэш по строке, чтобы несколько отдельных
# клеток красились одинаково).
COLOR_GROUP_COUNTRIES = {"Maldives"}

# Для этих стран после слияния оставляем только N САМЫХ КРУПНЫХ кусков
# (остальные удаляются как мелкие острова, см. _drop_small_islands) — по
# просьбе пользователя ("пусть будет это обычные 5 разделённых островов").
# Атоллы Мальдив ВСЕ мельче даже мягкого порога (100 км²), поэтому обычная
# защита по стране не подходит — оставляем явно топ-N по площади.
TOP_N_ISLANDS = {
	"Maldives": 5,
}

# Удаление мелких островов (не слияние — просто не рисуем, см. обсуждение в
# сессии: сливать через море клякса-геометрию выглядело бы хуже, чем просто
# не показывать). Применяется ПОСЛЕ _merge_small_pieces, к итоговым кускам.
ISLAND_DROP_KM2 = 300.0
ISLAND_DROP_KM2_SOFT = 100.0  # мягче для Карибов/Мальдив — иначе снесли бы половину островных государств
SOFT_ISLAND_ZONES = [
	("Карибский бассейн", -90.0, -59.0, 8.0, 23.0),
	("Мальдивы", 72.0, 74.0, -1.0, 8.0),
]
# Жёсткое исключение — прибрежная полоса Германии/Дании (Schleswig-Holstein/
# Niedersachsen/Syddanmark), по прямой просьбе пользователя 2026-07-13:
# "убрать все острова западной Дании". Обычный ISLAND_DROP_KM2=300 в
# _drop_small_islands не ловит их все — часть мелких островков УСПЕВАЕТ
# слиться (_merge_small_pieces, по соседству) в один кластер с суммарной
# площадью выше 300 км², проходит защиту, а затем на выводе снова распадается
# на отдельные мелкие куски (see session). Проверяется ПОСЛЕ crop+simplify,
# на итоговом куске — независимо от того, к какому кластеру он относился при
# слиянии. lat начинается с 53.5, чтобы не задеть материковую часть
# Niedersachsen (~52.5) южнее. max_area_km2 берётся отдельно от общего
# ISLAND_DROP_KM2 — это не остров-протектор, а зачистка ИМЕННО этой полосы,
# так что настоящие крупные датские острова (Фюн и т.п., тысячи км²) не
# затрагиваются.
HARD_EXCLUDE_ZONES = [
	("Германия/Дания, Ваддензе", 7.3, 9.6, 53.5, 55.6, 300.0),
]


def _in_hard_exclude_zone(lon: float, lat: float, area_km2: float) -> bool:
	return any(lon0 <= lon <= lon1 and lat0 <= lat <= lat1 and area_km2 < max_area
			   for _name, lon0, lon1, lat0, lat1, max_area in HARD_EXCLUDE_ZONES)
# Зоны, где ЛЮБОЙ остров защищён от удаления НЕЗАВИСИМО ОТ ИМЕНИ — некоторые
# исторически значимые острова (Фризские/Ваддензе) в датасете НЕ имеют
# собственного имени (это просто мелкие куски внутри MultiPolygon провинции
# "Friesland"/"Groningen"/"Niedersachsen" — защита по имени PROTECTED_ISLAND_
# NAMES для них не срабатывает, см. сессию).
#
# Зона сужена до НИДЕРЛАНДСКОЙ части Ваддензе (была 4.5-9.0, покрывала ещё и
# германо-датский берег) — по прямой просьбе пользователя 2026-07-13: острова
# Ваддензе у Германии/Дании (Schleswig-Holstein/Niedersachsen/Syddanmark)
# больше НЕ защищены и удаляются как обычные мелкие острова (< ISLAND_DROP_KM2).
# Нидерландские острова (Texel/Vlieland/Terschelling/Ameland/Schiermonnikoog)
# остаются защищены — они ЕЩЁ И в PROTECTED_ISLAND_NAMES по имени, эта зона для
# них не единственная защита.
PROTECTED_ISLAND_ZONES = [
	("Ваддензе (Фризские о-ва, только Нидерланды)", 4.5, 7.3, 53.0, 55.6),
]
# Исторически/культурно значимые острова — НЕ удаляются независимо от
# площади (список согласован с пользователем в сессии). Сравнение по имени
# (name из датасета), без учёта регистра.
PROTECTED_ISLAND_NAMES = {
	"iona", "skellig michael", "lindisfarne", "holy island", "guernsey", "jersey", "sark",
	"heligoland", "helgoland", "elba", "capri", "delos", "hydra", "aegina", "patmos",
	"santorini", "thira", "gorée", "goree", "robben island",
	"saint helena", "st helena", "st. helena",
	"iwo jima", "corregidor", "midway", "tarawa", "bikini",
	"easter island", "rapa nui", "pitcairn",
	# Фризские о-ва (Ваддензе) — объект Всемирного наследия ЮНЕСКО, найдено
	# по скриншоту в сессии ("острова над Нидерландами").
	"texel", "vlieland", "terschelling", "ameland", "schiermonnikoog",
	"borkum", "juist", "norderney", "baltrum", "langeoog", "spiekeroog", "wangerooge",
	"föhr", "foehr", "amrum", "pellworm", "sylt",
}
# Целые ОСТРОВНЫЕ СТРАНЫ, где датасет делит территорию на локальные единицы
# (муниципалитеты Мальты) — даже слитые ПОЛНОСТЬЮ в одну клетку по соседству,
# всё равно мельче 300 км² (вся Мальта ~246 км²), поэтому защита по имени
# острова не срабатывает — нужна защита по СТРАНЕ (поле admin). Мальдивы
# сюда не входят — та страна слита в ОДНУ клетку целиком (см.
# MERGE_WHOLE_COUNTRY выше), которой этот фильтр в принципе не касается
# (обрабатывается до _drop_small_islands).
PROTECTED_ISLAND_COUNTRIES = {"malta"}

# Общий (без хардкода конкретных стран) алгоритм слияния "подозрительно
# мелких" единиц. ПЕРВАЯ версия сравнивала площадь куска с МЕДИАНОЙ площади
# по стране — оказалось ненадёжно: в Словении 181 из 193 кусков УЖЕ мелкие
# (муниципалитеты), поэтому сама медиана "тонет" в мелких значениях и порог
# почти не срабатывает (413 слияний вместо тысяч ожидаемых). Вместо
# статистики площади — поле type_en из датасета: явно "не тот" (более
# мелкий, чем государство/область/провинция) административный уровень —
# Municipality/Commune/Borough/Parish/Canton и т.п., см. FINE_TYPES. Кусок с
# таким типом итеративно сливается с соседом (В ТОЙ ЖЕ стране), с которым
# делит САМУЮ ДЛИННУЮ общую границу — сосед поглощает его и сохраняет своё
# имя/тип. Если сосед тоже "мелкого" типа — слияние продолжается на
# следующем проходе (кластер мелких кусков схлопывается постепенно); как
# только поглотивший кусок — уже НЕ мелкого типа (например Большой Лондон),
# цепочка останавливается. Настоящие маленькие страны (Руанда, Гватемала и
# т.п., see TODO.md) НЕ страдают — у них type_en = "Province"/"District" как
# у всей остальной страны, единообразно, это не смесь уровней.
FINE_TYPES = {
	"Commune|Municipality", "Municipality", "London Borough", "London Borough (city)",
	"Metropolitan Borough", "Quarter", "Unitary District", "Unitary District (city)",
	"Municipality|Governarate", "Parish", "Canton",
}
GAP_TOL_DEG = 0.01  # допуск "касания" границ (соседние полигоны иногда не совпадают идеально)
MAX_MERGE_PASSES = 25  # защита от зацикливания


def project(lon, lat):
	lat = max(-85.05112878, min(85.05112878, lat))
	x = (lon + 180.0) / 360.0 * WORLD_PX
	lat_rad = math.radians(lat)
	y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
	return (x, y)


def ring_area_km2_lonlat(ring):
	lats = [p[1] for p in ring]
	lat0 = math.radians(sum(lats) / len(lats))
	pts = []
	for lon, lat in ring:
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


def _explode(geom) -> list:
	from shapely.geometry import Polygon, MultiPolygon, GeometryCollection
	if geom.is_empty:
		return []
	if isinstance(geom, Polygon):
		return [geom]
	if isinstance(geom, MultiPolygon):
		return list(geom.geoms)
	if isinstance(geom, GeometryCollection):
		out = []
		for g in geom.geoms:
			out.extend(_explode(g))
		return out
	return []


LOCAL_RATIO = 5.0  # кусок в LOCAL_RATIO раз мельче среднего своих соседей -> тоже "мелкий"
# Абсолютный порог (км²) — самый агрессивный из трёх сигналов "мелкости",
# по явному запросу пользователя ("увеличить агрессивность слияния", принят
# риск задеть настоящие мелкие единицы вроде Македонии/Руанды/островов
# Персидского залива, не только явные аномалии смешанной детализации).
ABSOLUTE_SMALL_KM2 = 1500.0


def _local_outlier_flags(pieces: list) -> list:
	"""Второй, независимый от type_en сигнал "мелкости" (см. обсуждение в
	сессии — type_en не универсален, напр. в Македонии мелкие муниципалитеты
	почему-то помечены тем же ярлыком "Statistical Region", что в Словении —
	крупные области). ЛОКАЛЬНОЕ сравнение: кусок в LOCAL_RATIO раз мельче
	среднего размера своих СОСЕДЕЙ (в той же стране) — сигнал не зависит от
	текстовой метки и не тонет в общестрановой статистике (сравнение только с
	непосредственными соседями, не со всей страной сразу)."""
	from shapely.strtree import STRtree

	n = len(pieces)
	areas = [ring_area_km2_lonlat(list(p["geom"].exterior.coords)) for p in pieces]
	buffered = [p["geom"].buffer(GAP_TOL_DEG) for p in pieces]
	tree = STRtree(buffered)

	flags = [False] * n
	for i in range(n):
		cand_idx = tree.query(buffered[i])
		neighbor_areas = []
		for ci in cand_idx:
			j = int(ci)
			if j == i or pieces[j]["admin"] != pieces[i]["admin"]:
				continue
			if buffered[i].intersects(buffered[j]):
				neighbor_areas.append(areas[j])
		if neighbor_areas:
			avg_neighbor = sum(neighbor_areas) / len(neighbor_areas)
			if areas[i] < avg_neighbor / LOCAL_RATIO:
				flags[i] = True
	return flags


def _merge_small_pieces(pieces: list) -> list:
	"""pieces: [{"name":str, "admin":str, "type_en":str, "geom": shapely Polygon
	(lon/lat)}, ...]. Итеративно сливает куски, помеченные "мелкими" (по
	type_en ИЛИ по локальному сравнению с соседями, см. FINE_TYPES/
	_local_outlier_flags выше) с соседом по самой длинной общей границе,
	ТОЛЬКО в пределах одной страны (admin) — иначе мелкий кусок мог бы
	случайно "перетечь" через границу в соседнюю страну. Возвращает новый
	список того же формата (у слитых кусков type_en/флаг — от поглотившего
	соседа, т.е. цепочка слияний останавливается, как только дошли до
	"нормального" куска)."""
	from shapely.strtree import STRtree
	from shapely.ops import unary_union

	n = len(pieces)
	if n == 0:
		return pieces

	local_flags = _local_outlier_flags(pieces)
	areas = [ring_area_km2_lonlat(list(p["geom"].exterior.coords)) for p in pieces]

	cluster_geom = {i: pieces[i]["geom"] for i in range(n)}
	cluster_admin = {i: pieces[i]["admin"] for i in range(n)}
	cluster_name = {i: pieces[i]["name"] for i in range(n)}
	cluster_type = {i: pieces[i]["type_en"] for i in range(n)}
	cluster_fine_flag = {i: local_flags[i] for i in range(n)}
	cluster_area = {i: areas[i] for i in range(n)}

	def is_fine(root: int) -> bool:
		# Третий, самый агрессивный сигнал: абсолютный порог площади — по
		# решению пользователя в сессии ("увеличить агрессивность слияния"),
		# принят риск слить и настоящие маленькие единицы (Македония/Руанда/
		# острова Персидского залива и т.п.), а не только явные аномалии.
		return (cluster_type[root] in FINE_TYPES or cluster_fine_flag[root]
				or cluster_area[root] < ABSOLUTE_SMALL_KM2)

	for _pass in range(MAX_MERGE_PASSES):
		roots = list(cluster_geom.keys())
		buffered = [cluster_geom[r].buffer(GAP_TOL_DEG) for r in roots]
		tree = STRtree(buffered)
		any_merge = False

		for pos, r in enumerate(roots):
			# r или rj могли "протухнуть" (уже слиты) РАНЬШЕ в ЭТОМ ЖЕ проходе —
			# roots/tree — снимок на начало прохода, а cluster_geom/cluster_admin
			# мутируются по ходу. Пропускаем то, чего уже нет.
			if r not in cluster_geom:
				continue
			if not is_fine(r):
				continue
			cand_idx = tree.query(buffered[pos])
			best_j, best_len = None, 0.0
			for ci in cand_idx:
				j = int(ci)
				if j == pos:
					continue
				rj = roots[j]
				if rj not in cluster_admin:
					continue  # уже слит с кем-то другим в этом же проходе
				if cluster_admin[rj] != cluster_admin[r]:
					continue  # НЕ пересекаем границу страны
				shared = buffered[pos].intersection(buffered[j])
				length = getattr(shared, "length", 0.0)
				if length > best_len:
					best_len, best_j = length, rj
			if best_j is not None:
				# best_j (сосед) поглощает r (мелкий), сохраняет своё имя И тип
				# (если сосед тоже "мелкий" — цепочка продолжится на след. проходе).
				cluster_geom[best_j] = unary_union([cluster_geom[best_j], cluster_geom[r]])
				cluster_area[best_j] += cluster_area[r]
				del cluster_geom[r]
				del cluster_admin[r]
				del cluster_name[r]
				del cluster_type[r]
				del cluster_fine_flag[r]
				del cluster_area[r]
				any_merge = True

		print(f"  merge pass {_pass+1}: {len(roots)} -> {len(cluster_geom)} pieces")
		if not any_merge:
			break

	out = []
	for r, geom in cluster_geom.items():
		out.append({"name": cluster_name[r], "admin": cluster_admin[r],
					"type_en": cluster_type[r], "geom": geom})
	return out


def _geom_area_km2(geom) -> float:
	"""Площадь геометрии (Polygon ИЛИ MultiPolygon — после слияний бывает и
	то, и другое) в км², суммируя все куски."""
	parts = _explode(geom)
	return sum(ring_area_km2_lonlat(list(p.exterior.coords)) for p in parts)


def _in_soft_zone(lon: float, lat: float) -> bool:
	return any(lon0 <= lon <= lon1 and lat0 <= lat <= lat1
			   for _name, lon0, lon1, lat0, lat1 in SOFT_ISLAND_ZONES)


def _in_protected_zone(lon: float, lat: float) -> bool:
	return any(lon0 <= lon <= lon1 and lat0 <= lat <= lat1
			   for _name, lon0, lon1, lat0, lat1 in PROTECTED_ISLAND_ZONES)


def _top_n_protected_names(pieces: list) -> set:
	"""Для стран из TOP_N_ISLANDS выше — имена N самых крупных (по площади)
	кусков ЭТОЙ страны, которые нужно защитить от удаления как мелкие
	острова (остальные куски этой же страны — не защищены, удалятся как
	обычно)."""
	extra = set()
	for country, n in TOP_N_ISLANDS.items():
		candidates = [p for p in pieces if p["admin"] == country]
		candidates.sort(key=lambda p: _geom_area_km2(p["geom"]), reverse=True)
		for p in candidates[:n]:
			extra.add((p["name"] or "").strip().lower())
	return extra


def _drop_small_islands(pieces: list) -> list:
	"""Убирает мелкие острова (см. ISLAND_DROP_KM2/_SOFT/PROTECTED_ISLAND_NAMES
	выше) — НЕ сливает, а полностью выкидывает из вывода (слияние через море
	дало бы кляксу-геометрию через воду, что выглядело бы хуже, чем просто не
	показать маленький остров). Куски из TOP_N_ISLANDS/COLOR_GROUP_COUNTRIES
	дополнительно получают "color_key" — несколько ОТДЕЛЬНЫХ (не слитых)
	клеток красятся одним цветом (см. IrregularCellProvider.gd)."""
	top_n_names = _top_n_protected_names(pieces)
	out = []
	dropped = 0
	for p in pieces:
		name_l = (p["name"] or "").strip().lower()
		admin_l = (p["admin"] or "").strip().lower()
		c = p["geom"].centroid
		protected = (name_l in PROTECTED_ISLAND_NAMES
					 or admin_l in PROTECTED_ISLAND_COUNTRIES
					 or (p["admin"] in TOP_N_ISLANDS and name_l in top_n_names)
					 or _in_protected_zone(c.x, c.y))
		if not protected:
			area = _geom_area_km2(p["geom"])
			threshold = ISLAND_DROP_KM2_SOFT if _in_soft_zone(c.x, c.y) else ISLAND_DROP_KM2
			if area < threshold:
				dropped += 1
				continue
		if p["admin"] in COLOR_GROUP_COUNTRIES:
			p = dict(p)
			p["color_key"] = p["admin"]
		out.append(p)
	print(f"  dropped {dropped} small islands (< {ISLAND_DROP_KM2:.0f} km2, "
		  f"< {ISLAND_DROP_KM2_SOFT:.0f} km2 in Caribbean/Maldives)")
	return out


# Осколки мельче этого порога (кв. мировых px; 1e-3 px² ≈ 0.02 км² на экваторе)
# после вычитания перекрытий выкидываются — это микро-обрезки на стыках, не
# настоящая территория.
MIN_SLIVER_PX2 = 1e-3
# Порог в км² (а не в мировых px²) для осколков РАЗНИЦЫ (см. докстринг
# _remove_overlaps) — px² не переводится линейно в км² (зависит от широты
# Меркатора), из-за чего MIN_SLIVER_PX2 пропускал куски порядка 0.03-1.9 км²
# (найдено 2026-07-12: Westmeath/Appenzell Innerrhoden/Kalmar/Northwest
# Territories/Qaasuitsup Kommunia — микро-хвостики от simplify()-нестыковки
# границ соседей, реальная территория этих провинций уже есть в другой,
# крупной записи с тем же именем). 2.0 км² — заведомо больше найденных
# осколков, но заведомо меньше любого настоящего маленького острова/анклава.
MIN_SLIVER_KM2 = 2.0


def _fix_mojibake(s: str) -> str:
	"""Разворачивает порчу "UTF-8 прочитан как latin-1" в именах.

	Промежуточный geojson (_work/ne_10m_admin_1_states_provinces.geojson)
	был когда-то сконвертирован из shapefile с неверной кодировкой DBF:
	"Entre Ríos" превратился в "Entre RÃ­os" (байты C3 AD прочитаны как два
	latin-1 символа). Исходный .dbf корректен (рядом .cpg = UTF-8), но
	конвертера в репозитории нет, поэтому чиним при чтении.

	Преобразование безопасно: чистый ASCII проходит без изменений, а строки,
	не являющиеся таким мойбейком, не декодируются и возвращаются как есть.
	"""
	try:
		return s.encode("latin-1").decode("utf-8")
	except (UnicodeEncodeError, UnicodeDecodeError):
		return s


def _slug(s: str) -> str:
	out = []
	prev_underscore = False
	for ch in s.lower():
		if ch.isascii() and (ch.isalnum()):
			out.append(ch)
			prev_underscore = False
		elif not prev_underscore:
			out.append("_")
			prev_underscore = True
	return "".join(out).strip("_") or "unnamed"


def _world_px_to_lonlat(x: float, y: float) -> tuple:
	lon = x / WORLD_PX * 360.0 - 180.0
	n = math.pi - 2.0 * math.pi * y / WORLD_PX
	lat = math.degrees(math.atan(math.sinh(n)))
	return lon, lat


def _piece_area_km2(piece) -> float:
	ext_ll = [_world_px_to_lonlat(x, y) for x, y in piece.exterior.coords]
	area = ring_area_km2_lonlat(ext_ll)
	for hole in piece.interiors:
		hole_ll = [_world_px_to_lonlat(x, y) for x, y in hole.coords]
		area -= ring_area_km2_lonlat(hole_ll)
	return max(0.0, area)


def _remove_overlaps(cells: list) -> list:
	"""Финальный проход по УЖЕ спроецированным клеткам (мировые px): из каждой
	клетки вычитается объединение ПЕРЕКРЫВАЮЩИХСЯ клеток, записанных раньше неё
	("кто раньше в файле — тот и владеет спорной полосой"). Перекрытия рождает
	simplify(): каждый полигон упрощается НЕЗАВИСИМО от соседей, и общая
	граница расходится в обе стороны — где-то щель (её закрывает GAP_FIX_PX
	при запекании), а где-то наложение до ~1 мирового px (Ла-Корунья/Луго,
	см. сессию 2026-07-11: клетка слоя "C" вылезала за границу запечённого
	слоя "4", потому что слои решали судьбу спорной полосы по-разному).
	Если после вычитания клетка распалась на несколько кусков — каждый кусок
	пишется отдельной записью (формат "одна запись = один полигон" сохраняется).
	"""
	from shapely.geometry import Polygon
	from shapely.strtree import STRtree
	from shapely.ops import unary_union

	polys = []
	for c in cells:
		p = Polygon(c["rings"][0], c["rings"][1:])
		if not p.is_valid:
			p = p.buffer(0)
		polys.append(p)
	tree = STRtree(polys)

	out = []
	trimmed = 0
	dropped_slivers = 0
	for i, c in enumerate(cells):
		p = polys[i]
		# соседи, записанные РАНЬШЕ и реально пересекающиеся площадью (не
		# просто касающиеся границей — difference на них ничего не меняет)
		blockers = []
		for j in tree.query(p):
			j = int(j)
			if j >= i:
				continue
			inter = polys[j].intersection(p)
			if getattr(inter, "area", 0.0) > 0.0:
				blockers.append(polys[j])
		if not blockers:
			out.append(c)
			continue
		geom = p.difference(unary_union(blockers))
		trimmed += 1
		survivors = []
		for piece in _explode(geom):
			if piece.is_empty or piece.area < MIN_SLIVER_PX2:
				dropped_slivers += 1
				continue
			if _piece_area_km2(piece) < MIN_SLIVER_KM2:
				dropped_slivers += 1
				continue
			ext = [[round(x, 2), round(y, 2)] for x, y in piece.exterior.coords]
			if len(ext) < 4:
				continue
			rings = [ext]
			for hole in piece.interiors:
				h = [[round(x, 2), round(y, 2)] for x, y in hole.coords]
				if len(h) >= 4:
					rings.append(h)
			xs = [q[0] for q in ext]
			ys = [q[1] for q in ext]
			survivors.append((rings, [min(xs), min(ys), max(xs), max(ys)]))
		# Разница может распасться на НЕСКОЛЬКО кусков — если c["id"] оставить
		# как есть у всех, получится дублирующийся id. Суффикс "_ovN" только
		# когда кусков реально больше одного (обычный случай — один кусок —
		# id остаётся исходным, не "плывёт" от появления/исчезновения соседей
		# по всему остальному файлу).
		base_id = c.get("id")
		for k, (rings, bbox) in enumerate(survivors):
			new_c = dict(c)
			new_c["rings"] = rings
			new_c["bbox"] = bbox
			if base_id and len(survivors) > 1:
				new_c["id"] = f"{base_id}_ov{k + 1}"
			out.append(new_c)
	print(f"  overlaps: подрезано клеток {trimmed}, выкинуто осколков {dropped_slivers}")
	return out


def _merge_grouped_features(features: list) -> list:
	"""Заменяет фичи, попавшие в MERGE_GROUPS (по ключу admin+region), на ОДНУ
	слитую фичу (unary_union их полигонов) с новым именем; остальные фичи
	возвращает без изменений. См. MERGE_GROUPS выше — сейчас только Лондон."""
	from shapely.geometry import shape, mapping
	from shapely.ops import unary_union

	if not MERGE_GROUPS:
		return features

	groups: dict = {}  # ключ MERGE_GROUPS -> список shapely-геометрий
	passthrough = []
	for f in features:
		props = f["properties"]
		key = (props.get("admin"), props.get("region"))
		if key in MERGE_GROUPS:
			groups.setdefault(key, []).append(shape(f["geometry"]))
		else:
			passthrough.append(f)

	for key, geoms in groups.items():
		merged = unary_union(geoms)
		passthrough.append({
			"properties": {"name": MERGE_GROUPS[key], "admin": key[0]},
			"geometry": mapping(merged),
		})
	return passthrough


def main() -> None:
	from shapely.geometry import Polygon, box, shape

	t0 = time.time()
	data = json.load(open(SRC, encoding="utf-8"))
	print(f"[{time.time()-t0:.1f}s] features: {len(data['features'])}")

	features = _merge_grouped_features(data["features"])
	print(f"[{time.time()-t0:.1f}s] features after merge groups: {len(features)}")

	# Explode в отдельные куски (lon/lat, ДО обрезки/упрощения/проекции) —
	# алгоритм слияния мелких кусков (_merge_small_pieces) работает именно
	# на этом уровне, см. формулы в сессии.
	raw_pieces = []
	for f in features:
		name = _fix_mojibake(f["properties"].get("name") or f["properties"].get("name_en")
				or f["properties"].get("admin") or "")
		admin = _fix_mojibake(f["properties"].get("admin") or "") or name
		# У фич из MERGE_GROUPS (см. _merge_grouped_features) type_en нет —
		# ставим заведомо "не мелкий" тип, чтобы их не подхватило повторно
		# (Большой Лондон уже объединён, дальше сливать нечего).
		type_en = f["properties"].get("type_en") or "Region"
		geom = shape(f["geometry"])
		if not geom.is_valid:
			geom = geom.buffer(0)
		for piece in _explode(geom):
			if not piece.is_empty and len(list(piece.exterior.coords)) >= 3:
				raw_pieces.append({"name": name, "admin": admin, "type_en": type_en, "geom": piece})
	print(f"[{time.time()-t0:.1f}s] raw pieces (до слияния): {len(raw_pieces)}")

	merged_pieces = _merge_small_pieces(raw_pieces)
	print(f"[{time.time()-t0:.1f}s] pieces после слияния мелких: {len(merged_pieces)}")

	merged_pieces = _drop_small_islands(merged_pieces)
	print(f"[{time.time()-t0:.1f}s] pieces после удаления мелких островов: {len(merged_pieces)}")

	crop_box = box(-180.0, LAT_SOUTH, 180.0, LAT_NORTH)

	out_cells = []
	skipped_small = 0
	skipped_empty = 0
	# Стабильный id клетки — по (admin, name) из ИСХОДНЫХ данных, а не по
	# порядковому номеру в итоговом файле (см. сессию 2026-07-13: правка
	# _remove_overlaps сдвинула positional id ("province_%04d") ВСЕХ клеток
	# после удалённых осколков, из-за чего сломались жёсткие списки в
	# TileMapViewer.gd — Нидерланды/Мальта/исключения по площади указывали уже
	# не на те провинции). Один и тот же (admin, name) может дать НЕСКОЛЬКО
	# итоговых клеток (остров-архипелаг, MultiPolygon) — первая клетка получает
	# голый base_id, следующие — "_2", "_3" и т.п. Правки в ДРУГИХ провинциях
	# (добавление/удаление где-то ещё в файле) больше не сдвигают этот id —
	# он зависит только от собственных (admin, name) провинции.
	id_counts: dict = {}
	for mp in merged_pieces:
		name = mp["name"]
		color_key = mp.get("color_key")
		base_id = _slug(mp["admin"]) + "__" + _slug(name)
		for piece0 in _explode(mp["geom"]):
			if piece0.is_empty:
				continue
			ext_ll0 = list(piece0.exterior.coords)
			if ring_area_km2_lonlat(ext_ll0) < MIN_PIECE_AREA_KM2:
				skipped_small += 1
				continue
			try:
				p = piece0
				if not p.is_valid:
					p = p.buffer(0)
				if p.is_empty:
					skipped_empty += 1
					continue
				p = p.intersection(crop_box)
				if p.is_empty:
					skipped_empty += 1
					continue
				p = p.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
				if p.is_empty:
					skipped_empty += 1
					continue
			except Exception:
				skipped_empty += 1
				continue

			for piece in _explode(p):
				if piece.is_empty:
					continue
				ext_ll = list(piece.exterior.coords)
				if len(ext_ll) < 3:
					continue
				# Повторная проверка ПОСЛЕ crop+simplify (а не только на исходной,
				# нетронутой геометрии выше) — simplify() иногда схлопывает кусок
				# до микроскопического размера (найдено 2026-07-12: Northwest
				# Territories/Qaasuitsup Kommunia — целые крупные провинции, но
				# один из exploded кусков после simplify ужимался до 0.03-1.9 км²,
				# то есть меньше MIN_SLIVER_KM2 у _remove_overlaps, но никогда не
				# попадал в тот фильтр, т.к. не имел overlap-блокеров).
				# ВАЖНО: порог здесь — MIN_SLIVER_KM2 (2 км², как у
				# _remove_overlaps), а НЕ полный MIN_PIECE_AREA_KM2 (5 км²).
				# Настоящие маленькие острова (атоллы Мальдив, Сарк, острова
				# Ваддензе) уже прошли проверку MIN_PIECE_AREA_KM2 ДО simplify()
				# (см. ring_area_km2_lonlat(ext_ll0) выше, на нетронутой
				# геометрии) — они защищены отдельно (PROTECTED_ISLAND_NAMES/
				# _COUNTRIES/_ZONES, ISLAND_DROP_KM2_SOFT), а не через этот порог.
				# Если здесь снова использовать 5 км², simplify() может увести их
				# post-simplify площадь чуть ниже 5 км² и отбросить остров,
				# который _drop_small_islands сознательно защитил (найдено
				# 2026-07-13: пропали второй Сарк, один атолл Мальдив, один
				# остров Нижней Саксонии). 2 км² — заведомо больше настоящих
				# osколков-артефактов simplify, но заведомо меньше любого
				# защищённого маленького острова.
				piece_area_km2 = ring_area_km2_lonlat(ext_ll)
				if piece_area_km2 < MIN_SLIVER_KM2:
					skipped_small += 1
					continue
				piece_lon = sum(p[0] for p in ext_ll) / len(ext_ll)
				piece_lat = sum(p[1] for p in ext_ll) / len(ext_ll)
				if _in_hard_exclude_zone(piece_lon, piece_lat, piece_area_km2):
					skipped_small += 1
					continue
				ext = [(round(x, 2), round(y, 2)) for x, y in
					   (project(lon, lat) for lon, lat in ext_ll)]
				holes = []
				for hole in piece.interiors:
					hole_ll = list(hole.coords)
					if len(hole_ll) < 3:
						continue
					holes.append([(round(x, 2), round(y, 2)) for x, y in
								   (project(lon, lat) for lon, lat in hole_ll)])
				xs = [q[0] for q in ext]
				ys = [q[1] for q in ext]
				rings = [[[x, y] for x, y in ext]]
				for hole in holes:
					rings.append([[x, y] for x, y in hole])
				n_seen = id_counts.get(base_id, 0)
				id_counts[base_id] = n_seen + 1
				cell_id = base_id if n_seen == 0 else f"{base_id}_{n_seen + 1}"
				cell = {
					"rings": rings,
					"bbox": [min(xs), min(ys), max(xs), max(ys)],
					"name": name,
					"id": cell_id,
				}
				if color_key:
					cell["color_key"] = color_key
				out_cells.append(cell)

	print(f"[{time.time()-t0:.1f}s] skipped small: {skipped_small}, skipped empty/polar: {skipped_empty}")

	out_cells = _remove_overlaps(out_cells)
	print(f"[{time.time()-t0:.1f}s] total cells: {len(out_cells)}")

	ids = [c.get("id") for c in out_cells]
	dup_ids = {i for i in ids if ids.count(i) > 1}
	if dup_ids:
		print(f"  ВНИМАНИЕ: {len(dup_ids)} дублирующихся id (первые 10): {list(dup_ids)[:10]}")

	json.dump({"world_px": WORLD_PX, "cells": out_cells},
			   open(OUT, "w", encoding="utf-8"), separators=(",", ":"))
	print(f"[{time.time()-t0:.1f}s] wrote {OUT}")


if __name__ == "__main__":
	main()
