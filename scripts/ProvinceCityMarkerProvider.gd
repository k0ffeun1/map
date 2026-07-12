class_name ProvinceCityMarkerProvider
extends Node
## Тайловый оверлей с точкой-маркером на главный город каждой провинции —
## одна запись на провинцию, координаты уже реальные (см.
## scripts/tools/build_province_cities_iberia.py -> assets/province_cities_iberia.json,
## Natural Earth ne_10m_populated_places, а не геометрический центр
## провинции). Рисует пиксели прямо в тайл (как IrregularCellProvider/
## BakedTileProvider) — город НЕ отдельная Node2D на сцене, см. CLAUDE.md
## ("клетка = запись в данных, а не нода").

const WORLD_PX := 8192.0
const TILE_PX := 256
const MARKER_PX := 14.0

var _markers: Array = []  ## [{"pos": Vector2, "name": String}]
var _cache: Dictionary = {}
var _blank_tex: Texture2D
var _data_path: String
var _loaded := false


func _init(data_path: String) -> void:
	_data_path = data_path
	var blank := Image.create(TILE_PX, TILE_PX, false, Image.FORMAT_RGBA8)
	_blank_tex = ImageTexture.create_from_image(blank)
	# Загружаем сразу (не лениво при первом request_tile) — маркеров мало
	# (~100 на регион), а get_markers() нужен сразу после new() для подписей
	# городов (ProvinceCityLabelsLayer.setup), которые тайлы не запрашивают.
	_load_data(_data_path)


## [{"pos": Vector2, "name": String}] — для подписей (см. TileMapViewer.gd,
## SeaLabelsLayer используется так же для подписей морей).
func get_markers() -> Array:
	return _markers


func request_tile(z: int, x: int, y: int) -> Texture2D:
	if not _loaded:
		_load_data(_data_path)
	var key := "%d/%d/%d" % [z, x, y]
	if _cache.has(key):
		return _cache[key]
	var img := _render(z, x, y)
	if img == null:
		_cache[key] = _blank_tex
	else:
		_cache[key] = ImageTexture.create_from_image(img)
	return _cache[key]


func _load_data(path: String) -> void:
	_loaded = true
	if not FileAccess.file_exists(path):
		push_warning("ProvinceCityMarkerProvider: no file %s" % path)
		return

	var parsed = JSON.parse_string(FileAccess.get_file_as_string(path))
	if typeof(parsed) != TYPE_DICTIONARY:
		push_warning("ProvinceCityMarkerProvider: failed to parse %s" % path)
		return

	for city in parsed.get("cities", []):
		var pos_raw: Array = city.get("pos", [])
		if pos_raw.size() < 2:
			continue
		_markers.append({
			"pos": Vector2(float(pos_raw[0]), float(pos_raw[1])),
			"name": str(city.get("name", "")),
		})


func _render(z: int, x: int, y: int) -> Image:
	var n := 1 << z
	var tile_world := WORLD_PX / float(n)
	var t0 := Vector2(float(x) * tile_world, float(y) * tile_world)
	var tile_rect := Rect2(t0, Vector2.ONE * tile_world)
	var marker_world_pad := MARKER_PX * tile_world / TILE_PX
	var padded_rect := tile_rect.grow(marker_world_pad)

	var hits: Array = []
	for marker in _markers:
		var marker_pos: Vector2 = marker["pos"]
		if padded_rect.has_point(marker_pos):
			hits.append(marker)
	if hits.is_empty():
		return null

	var img := Image.create(TILE_PX, TILE_PX, false, Image.FORMAT_RGBA8)
	var scale := float(TILE_PX) / tile_world
	for marker in hits:
		var p: Vector2 = (marker["pos"] - t0) * scale
		_draw_marker(img, p)
	return img


## Аналитическая сглаженная заливка (smoothstep по расстоянию до центра,
## та же идея, что border_feather у IrregularCellProvider._render) — без
## неё круг рисовался жёстким порогом d>radius и на глазах были видны
## отдельные квадратные пиксели растра (по прямой просьбе пользователя).
const AA_PX := 0.75          ## ширина сглаживания внешнего края круга
const OUTLINE_WIDTH_PX := 2.0
const OUTLINE_AA_PX := 0.75  ## ширина сглаживания между заливкой и обводкой
const HIGHLIGHT_R_PX := 2.5
const HIGHLIGHT_AA_PX := 1.0


func _draw_marker(img: Image, center: Vector2) -> void:
	var radius := MARKER_PX * 0.5
	var outline := Color(0.04, 0.03, 0.02, 0.95)
	var fill := Color(1.0, 0.78, 0.20, 0.98)
	var highlight := Color(1.0, 0.95, 0.72, 0.95)
	var pad := 2.0
	var min_x := maxi(0, floori(center.x - radius - pad))
	var max_x := mini(img.get_width() - 1, ceili(center.x + radius + pad))
	var min_y := maxi(0, floori(center.y - radius - pad))
	var max_y := mini(img.get_height() - 1, ceili(center.y + radius + pad))
	for py in range(min_y, max_y + 1):
		for px in range(min_x, max_x + 1):
			var d := Vector2(px + 0.5, py + 0.5).distance_to(center)
			var outer_alpha := 1.0 - smoothstep(radius - AA_PX, radius + AA_PX, d)
			if outer_alpha <= 0.001:
				continue
			# fill -> outline (кольцо у внешнего края) -> highlight (в центре),
			# каждая граница смешивается smoothstep, а не жёстким if/else.
			var outline_t := smoothstep(radius - OUTLINE_WIDTH_PX - OUTLINE_AA_PX,
				radius - OUTLINE_WIDTH_PX + OUTLINE_AA_PX, d)
			var col := fill.lerp(outline, outline_t)
			var highlight_t := 1.0 - smoothstep(HIGHLIGHT_R_PX - HIGHLIGHT_AA_PX,
				HIGHLIGHT_R_PX + HIGHLIGHT_AA_PX, d)
			col = col.lerp(highlight, highlight_t)
			col.a *= outer_alpha
			var existing := img.get_pixel(px, py)
			img.set_pixel(px, py, existing.blend(col))
