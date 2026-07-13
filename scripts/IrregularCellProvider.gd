class_name IrregularCellProvider
extends Node
## Неровные (Voronoi) клетки — суша ИЛИ море, в зависимости от data_path/
## border_color, переданных в _init(). Данные — офлайн-препроцессинг
## (scripts/tools/build_continents.py / build_land_sea.py / build_provinces.py /
## build_cells_test.py), формат:
## {"world_px":8192,"cells":[{"rings":[[[x,y],...],[[x,y],...]],"bbox":[...]}]}
## rings[0] — внешний контур, rings[1..] — дырки (озёра/внутренние моря и
## т.п.) — заливаются чётно-нечётным правилом (см. _fill_polygon), НЕ просто
## отбрасываются, иначе озеро закрашивается как суша.
##
## В отличие от SeaBorderTileProvider (только контуры), здесь ЗАЛИВКА —
## у каждой клетки свой пастельный цвет (по хэшу индекса), плюс тонкая
## тёмная граница поверх, как на референсной картинке провинций.
##
## Волнистые (изрезанные) границы дают клеткам МНОГО точек — рендер тайла
## (скан-линия заливки + отрисовка границ) заметно тяжелее, чем у остальных
## слоёв, поэтому он вынесен в WorkerThreadPool (см. OnlineTileProvider —
## та же схема: request_tile отдаёт null, пока фон считает Image).

const WORLD_PX := 8192.0
const EARTH_RADIUS_KM := 6371.0088

var _cells: Array = []            ## [{"bbox":Vector4, "rings":Array[PackedVector2Array], "color":Color}]
var _tex: Dictionary = {}         ## "z/x/y" -> Texture2D
var _border_color: Color
var _border_width: float          ## Толщина границы в мировых координатах (было const 1.4).
var _fill_alpha: float
var _sat: float
var _val: float
var _continent_colors: PackedColorArray  ## Непусто -> красим по "cont" из JSON, а не по хэшу индекса.

var _rendering: Dictionary = {}   ## "z/x/y" -> true (рендерится в фоне)
var _done_mutex := Mutex.new()
var _done_images: Array = []      ## [[key, Image], ...] — результаты потоков
var _task_ids: Array = []

## Сколько ImageTexture создавать за один _process() — см. то же самое в
## OnlineTileProvider.gd (защита от микрофриза при массовом "дозревании"
## фоновых рендеров одним кадром).
const MAX_TEXTURE_CREATES_PER_FRAME := 16

var _boundary_color: Color        ## Стиль ВНЕШНЕЙ границы (см. "brd_boundary"/BORDER_STYLE["cell_boundary"])
var _boundary_width: float        ## — независим от _border_color/_border_width (граница МЕЖДУ клетками,
var _boundary_feather: float      ## BORDER_STYLE["cell"]), по прямой просьбе пользователя 2026-07-11:
var _boundary_min_half_w: float   ## "внешнюю границу оставить, внутренние — без контуров".
var _has_boundary: bool           ## _has_boundary=false -> "brd_boundary" не рисуется вообще (старые слои
                                   ## "sea"/"G" её не передают в конструктор).

var _border_dashed: bool          ## true -> граница пунктиром (см. _dash_segments_world)
var _dash_len: float              ## длина штриха, МИРОВЫЕ px (не экранные) — фаза одинакова на всех тайлах
var _dash_gap: float              ## длина промежутка, мировые px
var _border_feather: float        ## ширина сглаживания края границы, растровые px (было жёстко 1.0)
var _border_min_half_w: float     ## минимальная полутолщина линии, растровые px (было жёстко 1.0 -> линия
                                   ## никогда не тоньше 2px на растре, ЧТО БЫ ни стояло в border_width)
var _raster_px: int               ## разрешение рендера ОДНОГО тайла, px (было жёстко 256 для всех слоёв).
                                   ## Sprite2D в TileMapViewer._make_tile масштабирует текстуру под фиксированный
                                   ## размер тайла В МИРЕ (`tile_world / texture.get_width()`) — увеличение этого
                                   ## числа даёт БОЛЬШЕ пикселей растра на тот же кусок мира, т.е. реально более
                                   ## чёткую картинку при сильном приближении, а не просто растянутую.
var _supersample: int             ## 1 = без суперсэмплинга (как раньше). N>1 -> тайл считается во ВНУТРЕННЕМ
                                   ## разрешении raster_px*N, потом усредняется блоками NxN до raster_px —
                                   ## финальная текстура остаётся того же размера (без доп. цены на текстуру/
                                   ## Sprite2D), но края заливки/скан-лайна получают честное усреднение по
                                   ## нескольким подпикселям вместо решения "по центру одного пикселя" — убирает
                                   ## растровые пятна не того цвета на резких изломах контура (см. обсуждение
                                   ## с пользователем про слой "Клетки", клавиши C/G).
var _selected_cell_name := ""
var _selection_color := Color(0.95, 0.78, 0.36, 0.42)
var _selected_cell_ids: Dictionary = {}
var _selection_id_color := Color(0.95, 0.78, 0.36, 0.42)
var _hidden_cell_ids: Dictionary = {}
var _manual_hidden_cell_ids: Dictionary = {}
var _area_hidden_cell_ids: Dictionary = {}
var _area_hidden_exempt_cell_ids: Dictionary = {}
var _border_smoothing_steps := 0
var _gap_fill_radius_px := 0
var _area_hidden_threshold := 0.0


func _init(data_path: String, border_color: Color = Color(0.15, 0.12, 0.10, 0.55),
		fill_alpha: float = 0.55, saturation: float = 0.35, value: float = 0.88,
		continent_colors: PackedColorArray = PackedColorArray(), border_width: float = 1.4,
		border_dashed: bool = false, dash_len: float = 0.5, dash_gap: float = 0.35,
		border_feather: float = 1.0, border_min_half_w: float = 1.0, raster_px: int = 256,
		supersample: int = 1, boundary_style: Dictionary = {}) -> void:
	_border_color = border_color
	_fill_alpha = fill_alpha
	_sat = saturation
	_val = value
	_continent_colors = continent_colors
	_border_width = border_width
	_border_dashed = border_dashed
	_dash_len = dash_len
	_dash_gap = dash_gap
	_border_min_half_w = border_min_half_w
	_border_feather = border_feather
	_raster_px = raster_px
	_supersample = maxi(1, supersample)
	_has_boundary = not boundary_style.is_empty()
	_boundary_color = boundary_style.get("color", Color(0, 0, 0, 1))
	_boundary_width = boundary_style.get("width", 0.625)
	_boundary_feather = boundary_style.get("feather", 0.6)
	_boundary_min_half_w = boundary_style.get("min_half_w", 0.2)
	_load_data(data_path)


## См. OnlineTileProvider._exit_tree — не даём фоновому потоку дёрнуть метод
## уже уничтоженного объекта.
func _exit_tree() -> void:
	for id in _task_ids:
		WorkerThreadPool.wait_for_task_completion(id)


func _process(_delta: float) -> void:
	_task_ids = _task_ids.filter(func (id: int) -> bool:
		return not WorkerThreadPool.is_task_completed(id))

	_done_mutex.lock()
	var done := _done_images
	_done_images = []
	_done_mutex.unlock()
	var budget := MAX_TEXTURE_CREATES_PER_FRAME
	var i := 0
	while i < done.size() and budget > 0:
		var key: String = done[i][0]
		_rendering.erase(key)
		var img: Image = done[i][1]
		if img != null:
			_tex[key] = ImageTexture.create_from_image(img)
		i += 1
		budget -= 1
	if i < done.size():
		_done_mutex.lock()
		_done_images = done.slice(i) + _done_images
		_done_mutex.unlock()


func _load_data(path: String) -> void:
	if not FileAccess.file_exists(path):
		push_warning("IrregularCellProvider: нет файла %s" % path)
		return
	var text := FileAccess.get_file_as_string(path)
	var parsed = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		push_warning("IrregularCellProvider: не удалось разобрать %s" % path)
		return
	var idx := 0
	var raw_cells: Array = parsed.get("cells", [])
	if raw_cells.is_empty() and parsed.has("water_cells"):
		raw_cells = parsed.get("water_cells", [])
	for cell in raw_cells:
		var rings_raw: Array = cell.get("rings", [])
		if rings_raw.is_empty() or rings_raw[0].size() < 3:
			idx += 1
			continue
		# ВСЕ кольца, не только внешнее — дальше идут дырки (озёра/Каспий/
		# Байкал и т.п., см. build_land_sea.py/build_continents.py), которые
		# нужно вырезать из заливки, а не просто игнорировать (иначе озеро
		# закрашивается как суша, см. TODO.md).
		var rings: Array = []
		for ring_raw in rings_raw:
			if ring_raw.size() < 3:
				continue
			var pts := PackedVector2Array()
			for p in ring_raw:
				pts.append(Vector2(p[0], p[1]))
			rings.append(pts)
		# "brd" — НЕраздутый (истинный) контур клетки, ТОЛЬКО для линии
		# границы (см. scripts/tools/build_land_cells_v2.py/_raster_voronoi_cells).
		# "rings" там специально раздут на пару px ради заливки без дыр на
		# стыках — если рисовать границу по НЕМУ же, у двух соседних клеток
		# получаются ДВЕ разные (сдвинутые) линии на одном стыке ("двойные
		# линии", найдено по скриншотам в сессии). Если "brd" нет (старые
		# слои — континенты/суша-море/старые клетки суши) — используем
		# rings как и раньше (border_rings пуст -> _render берёт rings).
		var border_rings: Array = []
		var brd_raw: Array = cell.get("brd", [])
		for ring_raw2 in brd_raw:
			if ring_raw2.size() < 3:
				continue
			var pts2 := PackedVector2Array()
			for p2 in ring_raw2:
				pts2.append(Vector2(p2[0], p2[1]))
			border_rings.append(pts2)
		# "brd_open" — НЕЗАМКНУТЫЕ цепочки рёбер (см. scripts/tools/build_cells_test.py):
		# рёбра клетки, СОВПАДАЮЩИЕ с внешним контуром области (реальные
		# провинции, слой "8"), в них не входят — эту линию уже рисует слой области, а рисуя
		# её ЕЩЁ РАЗ здесь (чуть другим сглаживанием/чуть другими округлёнными
		# координатами) получалось "мыло" из двух почти совпадающих линий
		# (баг найден пользователем по скриншоту). Когда это поле непустое,
		# оно ПОЛНОСТЬЮ заменяет border_rings/rings как источник линии границы
		# для клетки (заливка при этом всё равно идёт по полному "rings").
		var border_open_rings: Array = []
		var brd_open_raw: Array = cell.get("brd_open", [])
		for chain_raw in brd_open_raw:
			if chain_raw.size() < 2:
				continue
			var pts3 := PackedVector2Array()
			for p3 in chain_raw:
				pts3.append(Vector2(p3[0], p3[1]))
			border_open_rings.append(pts3)
		# "brd_boundary" — ОТКРЫТЫЕ цепочки рёбер, СОВПАДАЮЩИХ с внешним
		# контуром провинции (см. scripts/tools/build_cells_test.py/
		# _split_border_chains — дополнение к "brd_open" с точностью до
		# наоборот: там internal-рёбра, тут boundary-рёбра). Рисуются
		# отдельным стилем (_boundary_*), только если _has_boundary.
		var border_boundary_rings: Array = []
		var brd_boundary_raw: Array = cell.get("brd_boundary", [])
		for chain_raw2 in brd_boundary_raw:
			if chain_raw2.size() < 2:
				continue
			var pts4 := PackedVector2Array()
			for p4 in chain_raw2:
				pts4.append(Vector2(p4[0], p4[1]))
			border_boundary_rings.append(pts4)
		var b: Array = cell.get("bbox", [0, 0, 0, 0])
		var color: Color
		var color_key: String = str(cell.get("color_key", ""))
		var color_raw: Array = cell.get("color", [])
		if color_raw.size() >= 4:
			color = Color(float(color_raw[0]), float(color_raw[1]), float(color_raw[2]), float(color_raw[3]))
		elif not _continent_colors.is_empty():
			# Слой "Континенты" — фиксированный цвет по индексу континента
			# ("cont" из assets/continents.json), а не по хэшу клетки.
			var cont: int = int(cell.get("cont", 0))
			color = _continent_colors[cont % _continent_colors.size()]
		elif not color_key.is_empty():
			# "color_key" (см. build_provinces.py, COLOR_GROUP_COUNTRIES) —
			# НЕСКОЛЬКО отдельных (не слитых геометрически) клеток красятся
			# ОДНИМ цветом — хэш по строке ключа вместо порядкового индекса
			# клетки (напр. отдельные острова Мальдив — один цвет, но каждый
			# остров — своя, не склеенная через океан, геометрия).
			var hue := fmod(float(absi(color_key.hash())) * 0.61803398875, 1.0)
			color = Color.from_hsv(hue, _sat, _val, _fill_alpha)
		else:
			# Золотое сечение для равномерного разброса оттенков по хэшу индекса.
			var hue := fmod(float(idx) * 0.61803398875, 1.0)
			color = Color.from_hsv(hue, _sat, _val, _fill_alpha)
		var cell_id := str(cell.get("id", ""))
		if cell_id.is_empty():
			cell_id = "province_%04d" % idx
		_cells.append({
			"id": cell_id,
			"name": str(cell.get("name", "")),
			"bbox": Vector4(b[0], b[1], b[2], b[3]),
			"rings": rings,
			"area": _rings_area_km2(rings),
			"border_rings": border_rings,
			"border_open_rings": border_open_rings,
			"border_boundary_rings": border_boundary_rings,
			"color": color,
		})
		idx += 1


## Возвращает "id" клетки под мировой точкой pos, или "" если ни одна не
## подходит. Простой перебор всех клеток (без spatial-index) — нормально для
## маленьких bake/test-слоёв вроде "Клетки (тест: Ла-Корунья)" (единицы-
## десятки клеток); для крупных живых runtime-слоёв со многими тысячами
## клеток см. CLAUDE.md/optim_map_godot_strategy.md — тогда точку кликов
## нужно будет отдавать через ID-карту или spatial-index, не перебором.
func get_cell_id_at(pos: Vector2) -> String:
	for cell in _cells:
		if _hidden_cell_ids.has(str(cell["id"])):
			continue
		if _cell_contains_pos(cell, pos):
			return str(cell["id"])
	return ""


func get_cell_name_at(pos: Vector2) -> String:
	for cell in _cells:
		if _hidden_cell_ids.has(str(cell["id"])):
			continue
		if _cell_contains_pos(cell, pos):
			return str(cell["name"])
	return ""


func get_cell_rings_by_id(cell_id: String) -> Array:
	var out: Array = []
	for cell in _cells:
		if str(cell["id"]) != cell_id or _hidden_cell_ids.has(str(cell["id"])):
			continue
		for ring in cell["rings"]:
			out.append(PackedVector2Array(ring))
	return out


func get_cell_border_rings_by_id(cell_id: String) -> Array:
	var out: Array = []
	for cell in _cells:
		if str(cell["id"]) != cell_id or _hidden_cell_ids.has(str(cell["id"])):
			continue
		var border_src: Array = cell["border_open_rings"] if not cell["border_open_rings"].is_empty() else cell["rings"]
		for ring in border_src:
			out.append(PackedVector2Array(ring))
	return out


func get_cell_rings_by_name(cell_name: String) -> Array:
	var out: Array = []
	for cell in _cells:
		if str(cell["name"]) != cell_name or _hidden_cell_ids.has(str(cell["id"])):
			continue
		for ring in cell["rings"]:
			out.append(PackedVector2Array(ring))
	return out


func set_selected_cell_name(cell_name: String, color: Color = Color(0.95, 0.78, 0.36, 0.42)) -> void:
	_selected_cell_name = cell_name
	_selection_color = color
	_tex.clear()


func set_selected_cell_ids(cell_ids: Array, color: Color = Color(0.95, 0.78, 0.36, 0.42)) -> void:
	_selected_cell_ids.clear()
	for cell_id in cell_ids:
		var key := str(cell_id)
		if not key.is_empty():
			_selected_cell_ids[key] = true
	_selection_id_color = color
	_tex.clear()


func set_hidden_cell_ids(cell_ids: Array) -> void:
	_manual_hidden_cell_ids.clear()
	for cell_id in cell_ids:
		var key := str(cell_id)
		if not key.is_empty():
			_manual_hidden_cell_ids[key] = true
	_rebuild_hidden_cell_ids()
	_tex.clear()


func set_cell_id_aliases(id_aliases: Dictionary) -> void:
	var target_info := {}
	for cell in _cells:
		var cell_id := str(cell["id"])
		if not target_info.has(cell_id):
			target_info[cell_id] = {
				"name": str(cell["name"]),
				"color": cell["color"],
			}
	for from_id in id_aliases.keys():
		var source_id := str(from_id)
		var target_id := str(id_aliases[from_id])
		if source_id.is_empty() or target_id.is_empty():
			continue
		if not target_info.has(target_id):
			continue
		var info: Dictionary = target_info[target_id]
		for cell in _cells:
			if str(cell["id"]) == source_id:
				cell["id"] = target_id
				cell["name"] = str(info["name"])
				cell["color"] = info["color"]
	set_area_hidden_threshold(_area_hidden_threshold)
	_tex.clear()


func set_area_hidden_threshold(area_threshold: float) -> int:
	_area_hidden_threshold = maxf(0.0, area_threshold)
	_area_hidden_cell_ids.clear()
	if _area_hidden_threshold > 0.0:
		var area_by_id := {}
		for cell in _cells:
			var cell_id := str(cell["id"])
			area_by_id[cell_id] = float(area_by_id.get(cell_id, 0.0)) + float(cell["area"])
		for cell_id in area_by_id.keys():
			if not _area_hidden_exempt_cell_ids.has(cell_id) and float(area_by_id[cell_id]) < _area_hidden_threshold:
				_area_hidden_cell_ids[cell_id] = true
	_rebuild_hidden_cell_ids()
	_tex.clear()
	return _area_hidden_cell_ids.size()


func set_area_hidden_exempt_cell_ids(cell_ids: Array) -> void:
	_area_hidden_exempt_cell_ids.clear()
	for cell_id in cell_ids:
		var key := str(cell_id)
		if not key.is_empty():
			_area_hidden_exempt_cell_ids[key] = true
	set_area_hidden_threshold(_area_hidden_threshold)


func get_area_hidden_threshold() -> float:
	return _area_hidden_threshold


func get_area_hidden_count() -> int:
	return _area_hidden_cell_ids.size()


func _rebuild_hidden_cell_ids() -> void:
	_hidden_cell_ids.clear()
	for key in _manual_hidden_cell_ids.keys():
		_hidden_cell_ids[key] = true
	for key in _area_hidden_cell_ids.keys():
		_hidden_cell_ids[key] = true


func _rings_area_km2(rings: Array) -> float:
	if rings.is_empty():
		return 0.0
	var total := absf(_ring_signed_area_km2(rings[0]))
	for i in range(1, rings.size()):
		total -= absf(_ring_signed_area_km2(rings[i]))
	return maxf(0.0, total)


func _ring_signed_area_km2(points: PackedVector2Array) -> float:
	if points.size() < 3:
		return 0.0
	var lonlat := PackedVector2Array()
	var lat_sum := 0.0
	for p in points:
		var ll := _world_px_to_lonlat(p)
		lonlat.append(ll)
		lat_sum += ll.y
	var lat0 := deg_to_rad(lat_sum / float(lonlat.size()))
	var sum := 0.0
	for i in range(lonlat.size()):
		var a_ll := lonlat[i]
		var b_ll := lonlat[(i + 1) % lonlat.size()]
		var a := Vector2(deg_to_rad(a_ll.x) * cos(lat0) * EARTH_RADIUS_KM, deg_to_rad(a_ll.y) * EARTH_RADIUS_KM)
		var b := Vector2(deg_to_rad(b_ll.x) * cos(lat0) * EARTH_RADIUS_KM, deg_to_rad(b_ll.y) * EARTH_RADIUS_KM)
		sum += a.x * b.y - b.x * a.y
	return sum * 0.5


func _world_px_to_lonlat(pos: Vector2) -> Vector2:
	var lon := pos.x / WORLD_PX * 360.0 - 180.0
	var n := PI - 2.0 * PI * pos.y / WORLD_PX
	var lat := rad_to_deg(atan(sinh(n)))
	return Vector2(lon, lat)


func _cell_contains_pos(cell: Dictionary, pos: Vector2) -> bool:
	var b: Vector4 = cell["bbox"]
	if pos.x < b.x or pos.x > b.z or pos.y < b.y or pos.y > b.w:
		return false
	var rings: Array = cell["rings"]
	if rings.is_empty():
		return false
	if not Geometry2D.is_point_in_polygon(pos, rings[0]):
		return false
	# Дырки (озёра и т.п.) исключают точку из клетки, даже если она внутри
	# внешнего контура — та же логика чётности, что и в заливке (см.
	# докстринг файла).
	for hi in range(1, rings.size()):
		if Geometry2D.is_point_in_polygon(pos, rings[hi]):
			return false
	return true


func request_tile(z: int, x: int, y: int) -> Texture2D:
	var key := "%d/%d/%d" % [z, x, y]
	if _tex.has(key):
		return _tex[key]
	if _rendering.has(key):
		return null
	_rendering[key] = true
	_task_ids.append(WorkerThreadPool.add_task(_render_in_thread.bind(key, z, x, y)))
	return null


func set_border_width(width: float) -> void:
	_border_width = maxf(0.0, width)
	_tex.clear()


func set_border_feather(feather: float) -> void:
	_border_feather = maxf(0.01, feather)
	_tex.clear()


func set_border_smoothing_steps(steps: int) -> void:
	_border_smoothing_steps = clampi(steps, 0, 4)
	_tex.clear()


func set_gap_fill_radius_px(radius_px: int) -> void:
	_gap_fill_radius_px = clampi(radius_px, 0, 4)
	_tex.clear()


func set_border_color(color: Color) -> void:
	_border_color = color
	_tex.clear()


func set_uniform_fill_color(color: Color) -> void:
	for cell in _cells:
		cell["color"] = color
	_tex.clear()


func _render_in_thread(key: String, z: int, x: int, y: int) -> void:
	var img := _render(z, x, y)
	_done_mutex.lock()
	_done_images.append([key, img])
	_done_mutex.unlock()


func _render(z: int, x: int, y: int) -> Image:
	var tw := WORLD_PX / (1 << z)
	var t0x := x * tw
	var t0y := y * tw
	var t1x := t0x + tw
	var t1y := t0y + tw
	var pad := _border_width * 2.0

	var g := _raster_px
	var ss := _supersample
	var scale := g / tw
	var out := PackedByteArray()
	out.resize(g * g * 4)  # прозрачно по умолчанию

	for cell in _cells:
		if _hidden_cell_ids.has(str(cell["id"])):
			continue
		var bbox: Vector4 = cell["bbox"]
		if bbox.z < t0x - pad or bbox.x > t1x + pad or bbox.w < t0y - pad or bbox.y > t1y + pad:
			continue
		var local_rings: Array = []
		for world_pts in cell["rings"]:
			var local_pts := PackedVector2Array()
			for p in world_pts:
				local_pts.append(Vector2((p.x - t0x) * scale, (p.y - t0y) * scale))
			local_rings.append(local_pts)
		# supersample (см. _supersample) — НЕ раздувает весь тайл, а считает
		# несколько под-сканлайнов ПО Y на каждую строку финального разрешения
		# g (см. _fill_polygon) — на порядок дешевле, чем растеризация всего
		# тайла в g*ss и последующая свёртка вниз (первая версия этого фикса,
		# см. историю правки: 1024×8 давало 67 млн операций свёртки на тайл в
		# интерпретируемом GDScript — визуально "зависало"). Граница (ниже)
		# и так уже сглажена аналитически через feather, суперсэмплинг ей не нужен.
		_fill_polygon(out, g, local_rings, cell["color"], ss)

	if _gap_fill_radius_px > 0:
		_fill_transparent_gaps(out, g, _gap_fill_radius_px)

	if not _selected_cell_name.is_empty() or not _selected_cell_ids.is_empty():
		for cell_sel in _cells:
			if _hidden_cell_ids.has(str(cell_sel["id"])):
				continue
			var selected_by_name := not _selected_cell_name.is_empty() and str(cell_sel["name"]) == _selected_cell_name
			var selected_by_id := _selected_cell_ids.has(str(cell_sel["id"]))
			if not selected_by_name and not selected_by_id:
				continue
			var bbox_sel: Vector4 = cell_sel["bbox"]
			if bbox_sel.z < t0x - pad or bbox_sel.x > t1x + pad or bbox_sel.w < t0y - pad or bbox_sel.y > t1y + pad:
				continue
			var selected_local_rings: Array = []
			for world_pts_sel in cell_sel["rings"]:
				var selected_local_pts := PackedVector2Array()
				for p_sel in world_pts_sel:
					selected_local_pts.append(Vector2((p_sel.x - t0x) * scale, (p_sel.y - t0y) * scale))
				selected_local_rings.append(selected_local_pts)
			var highlight_color: Color = _selection_id_color if selected_by_id else _selection_color
			_fill_polygon(out, g, selected_local_rings, highlight_color, ss)

	for cell in _cells:
		if _hidden_cell_ids.has(str(cell["id"])):
			continue
		var bbox2: Vector4 = cell["bbox"]
		if bbox2.z < t0x - pad or bbox2.x > t1x + pad or bbox2.w < t0y - pad or bbox2.y > t1y + pad:
			continue
		var half_w := maxf(_border_min_half_w, _border_width * scale * 0.5)
		# "border_open_rings" (см. _load_data/build_cells_test.py) — рёбра,
		# СОВПАДАЮЩИЕ с границей контейнера (области), из которого клетку
		# вырезали, УЖЕ исключены на этапе генерации — эту линию рисует
		# слой контейнера, дублировать её здесь не нужно (иначе "мыло" из
		# двух почти совпадающих линий, см. обсуждение с пользователем).
		# Когда это поле есть — оно ПОЛНОСТЬЮ заменяет border_rings/rings как
		# источник линии, и рёбра НЕ замыкаются (открытые цепочки, а не кольца).
		var cell_border_open: Array = cell["border_open_rings"]
		var cell_border_rings: Array = cell["border_rings"]
		var is_open: bool = not cell_border_open.is_empty()
		# "border_rings" — НЕраздутый (истинный) контур клетки, только для
		# линии границы (см. build_land_cells_v2.py) — рисуем ЕГО, если он
		# есть, иначе (старые слои без этого поля — континенты/суша-море/
		# старые клетки суши) как и раньше берём "rings" (см. _load_data).
		var border_src: Array = cell_border_open if is_open \
			else (cell_border_rings if not cell_border_rings.is_empty() else cell["rings"])
		for world_pts2 in border_src:
			var pts2_arr := _smooth_points(world_pts2, is_open)
			var edge_count: int = (pts2_arr.size() - 1) if is_open else pts2_arr.size()
			if _border_dashed:
				# Фаза пунктира считается по МИРОВЫМ координатам (накопленная
				# длина от начала кольца), а не по локальным пикселям тайла —
				# иначе на стыке двух тайлов штрихи не совпали бы (каждый тайл
				# начинал бы счёт заново от своего края). Т.к. кольцо (world_pts2)
				# для клетки одно и то же независимо от тайла, при пересчёте на
				# каждом тайле получается идентичная схема штрихов — видимая
				# часть просто клипуется границами конкретного тайла.
				for seg in _dash_segments_world(pts2_arr, _dash_len, _dash_gap, is_open):
					var a: Vector2 = Vector2((seg[0].x - t0x) * scale, (seg[0].y - t0y) * scale)
					var b2: Vector2 = Vector2((seg[1].x - t0x) * scale, (seg[1].y - t0y) * scale)
					_draw_segment(out, g, a, b2, half_w)
			else:
				var local_pts2 := PackedVector2Array()
				for p in pts2_arr:
					local_pts2.append(Vector2((p.x - t0x) * scale, (p.y - t0y) * scale))
				for i in range(edge_count):
					var a2 := local_pts2[i]
					var b3 := local_pts2[(i + 1) % local_pts2.size()]
					_draw_segment(out, g, a2, b3, half_w)

	if _has_boundary:
		var half_w_b := maxf(_boundary_min_half_w, _boundary_width * scale * 0.5)
		for cell3 in _cells:
			if _hidden_cell_ids.has(str(cell3["id"])):
				continue
			var bbox3: Vector4 = cell3["bbox"]
			if bbox3.z < t0x - pad or bbox3.x > t1x + pad or bbox3.w < t0y - pad or bbox3.y > t1y + pad:
				continue
			# Открытые цепочки (см. _load_data) — БЕЗ замыкания последней точки
			# на первую, edge_count = size-1, как у border_open_rings выше.
			for world_pts3 in cell3["border_boundary_rings"]:
				var pts5_arr: PackedVector2Array = world_pts3
				var local_pts5 := PackedVector2Array()
				for p5 in pts5_arr:
					local_pts5.append(Vector2((p5.x - t0x) * scale, (p5.y - t0y) * scale))
				for i2 in range(local_pts5.size() - 1):
					_draw_segment(out, g, local_pts5[i2], local_pts5[i2 + 1], half_w_b,
						_boundary_feather, _boundary_color)

	return Image.create_from_data(g, g, false, Image.FORMAT_RGBA8, out)


func _smooth_points(points: PackedVector2Array, is_open: bool) -> PackedVector2Array:
	if _border_smoothing_steps <= 0 or points.size() < 3:
		return points
	var current := points
	for _step in range(_border_smoothing_steps):
		var next := PackedVector2Array()
		var n := current.size()
		if is_open:
			next.append(current[0])
			for i in range(n - 1):
				var a := current[i]
				var b := current[i + 1]
				next.append(a.lerp(b, 0.25))
				next.append(a.lerp(b, 0.75))
			next.append(current[n - 1])
		else:
			for i2 in range(n):
				var a2 := current[i2]
				var b2 := current[(i2 + 1) % n]
				next.append(a2.lerp(b2, 0.25))
				next.append(a2.lerp(b2, 0.75))
		current = next
	return current


func _fill_transparent_gaps(out: PackedByteArray, g: int, radius_px: int) -> void:
	var r := clampi(radius_px, 0, 4)
	if r <= 0:
		return
	var src := out.duplicate()
	var min_x := g
	var min_y := g
	var max_x := -1
	var max_y := -1
	for sy in range(g):
		for sx in range(g):
			if src[(sy * g + sx) * 4 + 3] == 0:
				continue
			min_x = mini(min_x, sx)
			min_y = mini(min_y, sy)
			max_x = maxi(max_x, sx)
			max_y = maxi(max_y, sy)
	if max_x < min_x or max_y < min_y:
		return
	min_x = maxi(0, min_x - r)
	min_y = maxi(0, min_y - r)
	max_x = mini(g - 1, max_x + r)
	max_y = mini(g - 1, max_y + r)
	for py in range(min_y, max_y + 1):
		var y0 := maxi(0, py - r)
		var y1 := mini(g - 1, py + r)
		for px in range(min_x, max_x + 1):
			var idx := (py * g + px) * 4
			if src[idx + 3] != 0:
				continue
			var best_idx := -1
			var best_d2 := 999999
			var x0 := maxi(0, px - r)
			var x1 := mini(g - 1, px + r)
			for ny in range(y0, y1 + 1):
				for nx in range(x0, x1 + 1):
					var dx := nx - px
					var dy := ny - py
					var d2 := dx * dx + dy * dy
					if d2 == 0 or d2 > r * r or d2 >= best_d2:
						continue
					var nidx := (ny * g + nx) * 4
					if src[nidx + 3] == 0:
						continue
					best_d2 = d2
					best_idx = nidx
			if best_idx >= 0:
				out[idx] = src[best_idx]
				out[idx + 1] = src[best_idx + 1]
				out[idx + 2] = src[best_idx + 2]
				out[idx + 3] = src[best_idx + 3]


## Скан-линия заливки многоугольника С ДЫРКАМИ (чётно-нечётное правило) —
## rings[0] внешний контур, rings[1..] дырки (озёра и т.п.); пересечения со
## ВСЕХ колец собираются в один отсортированный список, заливка идёт через
## пару — это автоматически "выключает" заливку внутри дырок, без разбора,
## какое кольцо внешнее, а какое дырка.
## supersample=1 (по умолчанию, старые слои) -> ОДИН сэмпл на строку по
## центру пикселя (yc=py+0.5), в точности прежнее поведение. supersample=N>1
## -> N под-сканлайнов ПО Y внутри одной строки py (без раздутия тайла целиком
## и без отдельного прохода понижающей свёртки — см. историю правки в
## _render: та версия давала O(g²·ss²) операций и визуально "зависала").
## Пиксель получает alpha, пропорциональную ДОЛЕ под-сканлайнов, покрывших
## его, — сглаживает края заливки на резких/вогнутых углах контура, где
## "решение по центру одного пикселя" давало пятно не того цвета.
func _fill_polygon(out: PackedByteArray, g: int, rings: Array, color: Color, supersample: int = 1) -> void:
	if rings.is_empty():
		return
	var ss := maxi(1, supersample)
	var min_y := g
	var max_y := 0
	for pts in rings:
		var ring_pts0: PackedVector2Array = pts
		for p in ring_pts0:
			min_y = mini(min_y, int(floor(p.y)))
			max_y = maxi(max_y, int(ceil(p.y)))
	min_y = maxi(0, min_y)
	max_y = mini(g - 1, max_y)
	if min_y > max_y:
		return

	var r := int(color.r * 255)
	var gc := int(color.g * 255)
	var bc := int(color.b * 255)
	var base_a := int(color.a * 255)

	# Счётчик покрытия по X для ТЕКУЩЕЙ строки py (сколько из ss под-сканлайнов
	# накрыли каждый пиксель) — переиспользуется между строками, обнуляется
	# только в диапазоне [row_xa,row_xb], который реально трогали (не весь g).
	var cov := PackedInt32Array()
	cov.resize(g)

	for py in range(min_y, max_y + 1):
		var row_xa := g
		var row_xb := -1
		for sub in range(ss):
			var yc := py + (float(sub) + 0.5) / float(ss)
			var xs: Array = []
			for pts in rings:
				var ring_pts: PackedVector2Array = pts
				var n := ring_pts.size()
				for i in range(n):
					var a: Vector2 = ring_pts[i]
					var b2: Vector2 = ring_pts[(i + 1) % n]
					if (a.y <= yc and b2.y > yc) or (b2.y <= yc and a.y > yc):
						var t := (yc - a.y) / (b2.y - a.y)
						xs.append(a.x + t * (b2.x - a.x))
			xs.sort()
			var i2 := 0
			while i2 + 1 < xs.size():
				var xa := maxi(0, int(ceil(xs[i2] - 0.5)))
				var xb := mini(g - 1, int(floor(xs[i2 + 1] - 0.5)))
				if xa <= xb:
					row_xa = mini(row_xa, xa)
					row_xb = maxi(row_xb, xb)
					for px in range(xa, xb + 1):
						cov[px] += 1
				i2 += 2
		if row_xb < row_xa:
			continue
		for px in range(row_xa, row_xb + 1):
			var c := cov[px]
			cov[px] = 0
			if c == 0:
				continue
			var src_a := base_a * c / ss
			if src_a <= 0:
				continue
			var idx := (py * g + px) * 4
			# alpha-blend поверх того, что уже нарисовано (соседние клетки не перекрываются,
			# но на стыках краевые пиксели могут делиться — блендим по alpha).
			var dst_a := out[idx + 3]
			var out_a := src_a + dst_a * (255 - src_a) / 255
			if out_a <= 0:
				continue
			out[idx] = (r * src_a + out[idx] * dst_a * (255 - src_a) / 255) / maxi(1, out_a)
			out[idx + 1] = (gc * src_a + out[idx + 1] * dst_a * (255 - src_a) / 255) / maxi(1, out_a)
			out[idx + 2] = (bc * src_a + out[idx + 2] * dst_a * (255 - src_a) / 255) / maxi(1, out_a)
			out[idx + 3] = out_a


## Режет кольцо/цепочку (мировые координаты) на подотрезки "штрих" (пропуская
## "промежутки"), длины в тех же мировых px, что и сами координаты кольца.
## Фаза накапливается ПО ВСЕЙ цепочке от первой вершины — см. вызов в _render.
## is_open=true -> НЕ замыкаем последнюю точку на первую (открытая цепочка,
## см. border_open_rings) — n-1 рёбер вместо n.
func _dash_segments_world(world_pts: Array, dash_len: float, dash_gap: float, is_open: bool = false) -> Array:
	var period := dash_len + dash_gap
	var out: Array = []
	var n: int = world_pts.size()
	if n < 2 or period <= 0.0001:
		return out
	var edge_count := (n - 1) if is_open else n
	var dist_accum := 0.0
	# Второй, независимый предохранитель — общий потолок итераций по ВСЕМУ
	# кольцу. EPS-фикс ниже убирает конкретную причину зависания, но лимит
	# держим отдельно на случай, если когда-нибудь этот же код применят к
	# кольцу с гораздо большим числом точек/длиной (сейчас — всего 4 мелкие
	# клетки Ла-Коруньи, но правило именования/архитектуры в CLAUDE.md прямо
	# говорит переиспользовать код, а не плодить копии).
	const MAX_DASH_SEGMENTS := 200000
	for i in range(edge_count):
		var a: Vector2 = world_pts[i]
		var b: Vector2 = world_pts[(i + 1) % n]
		var seg_len := a.distance_to(b)
		if seg_len <= 0.0001:
			continue
		var pos := 0.0
		# ВАЖНО: без EPS вместо `pos < seg_len` возможен бесконечный цикл —
		# на границе штрих/промежуток remaining может из-за погрешности
		# плавающей точки округлиться до ~0, тогда seg_end == pos и цикл
		# никогда не продвигается (реально ловилось в игре: 100% одного ядра
		# навсегда в фоновом потоке WorkerThreadPool на каждый тайл слоя).
		const EPS := 0.0001
		while pos < seg_len - EPS:
			if out.size() > MAX_DASH_SEGMENTS:
				push_warning("IrregularCellProvider: превышен лимит штрихов, обрезаю кольцо")
				return out
			var phase := fmod(dist_accum + pos, period)
			var is_on := phase < dash_len
			var remaining: float = (dash_len - phase) if is_on else (period - phase)
			var seg_end := minf(pos + maxf(remaining, EPS), seg_len)
			if is_on:
				out.append([a.lerp(b, pos / seg_len), a.lerp(b, seg_end / seg_len)])
			pos = seg_end
		dist_accum += seg_len
	return out


func _draw_segment(out: PackedByteArray, g: int, a: Vector2, b: Vector2, half_w: float,
		feather: float = -1.0, draw_color: Color = Color(-1.0, -1.0, -1.0, -1.0)) -> void:
	# Полуширина зоны сглаживания (feather) добавляется К half_w — при
	# feather > 1.0 переход "цвет границы -> прозрачно" размазывается по
	# бОльшему числу пикселей (мягче/более гладкий контур на глаз), при
	# feather == 1.0 (по умолчанию, старые слои) — прежнее поведение.
	# feather<0 (не передан) -> берём _border_feather как раньше; _render
	# при supersample>1 передаёт feather явно (умноженный на ss), чтобы
	# сглаживание не "утоньшилось" после понижающей свёртки.
	var fw: float = feather if feather >= 0.0 else _border_feather
	var half_feather := fw * 0.5
	var reach := half_w + half_feather
	var min_x := maxi(0, floori(minf(a.x, b.x) - reach - 1))
	var max_x := mini(g - 1, ceili(maxf(a.x, b.x) + reach + 1))
	var min_y := maxi(0, floori(minf(a.y, b.y) - reach - 1))
	var max_y := mini(g - 1, ceili(maxf(a.y, b.y) + reach + 1))
	if min_x > max_x or min_y > max_y:
		return

	# draw_color<0 (не передан) -> обычная клеточная граница (_border_color);
	# используется boundary-проходом (_render) для отрисовки ВНЕШНЕЙ границы
	# провинции своим, независимым цветом (_boundary_color).
	var col: Color = draw_color if draw_color.a >= 0.0 else _border_color
	var seg := b - a
	var len2 := seg.length_squared()
	var r := int(col.r * 255)
	var gc := int(col.g * 255)
	var bc := int(col.b * 255)
	var ac := int(col.a * 255)

	for py in range(min_y, max_y + 1):
		for px in range(min_x, max_x + 1):
			var p := Vector2(px + 0.5, py + 0.5)
			var d: float
			if len2 <= 0.000001:
				d = p.distance_to(a)
			else:
				var t := clampf((p - a).dot(seg) / len2, 0.0, 1.0)
				d = p.distance_to(a + seg * t)
			if d > reach:
				continue
			var idx := (py * g + px) * 4
			var edge := clampf((half_w + half_feather - d) / fw, 0.0, 1.0)
			var src_a := int(ac * edge)
			var dst_a := out[idx + 3]
			var out_a := src_a + dst_a * (255 - src_a) / 255
			if out_a <= 0:
				continue
			out[idx] = (r * src_a + out[idx] * dst_a * (255 - src_a) / 255) / maxi(1, out_a)
			out[idx + 1] = (gc * src_a + out[idx + 1] * dst_a * (255 - src_a) / 255) / maxi(1, out_a)
			out[idx + 2] = (bc * src_a + out[idx + 2] * dst_a * (255 - src_a) / 255) / maxi(1, out_a)
			out[idx + 3] = out_a


# --- Интерфейс для предзагрузчика — не нужен, данные локальные (без сети).
func prefetch_url(_z: int, _x: int, _y: int) -> String:
	return ""


func prefetch_path(_z: int, _x: int, _y: int) -> String:
	return ""
