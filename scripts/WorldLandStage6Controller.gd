extends Node
## Верхний географический слой «Мир — вся суша».
##
## Источник логики — Stage 6 (`final_subdivisions.json`): все финальные
## сухопутные зоны мира трактуются как одна логическая территория `world_land`.
## Мы НЕ делаем тяжёлый polygon union в Godot. Для hit-test сохраняются
## исходные Stage-6 полигоны, но наружу любой из них возвращает один ID.
##
## Для визуала переиспользуется уже запечённый фундаментальный слой
## «Суша/Море», поэтому включение мирового уровня не запускает повторный
## живой рендер тысяч сложных полигонов.
##
## F7 — показать/скрыть агрегированный мировой слой.
## J остаётся штатной клавишей обычного Stage-6 overview и не меняется.

const STAGE6_PATH := "res://assets/subdivision_stage6/final_subdivisions.json"
const EXPECTED_FORMAT := "universal_final_subdivision/v1"
const WORLD_LAND_ID := "world_land"
const WORLD_LAND_NAME := "Вся суша мира"
const WORLD_LAYER_NAME := "Мир — вся суша (Stage 6)"
const WORLD_LAYER_Z_INDEX := 40
const WORLD_PX := 8192.0
const SPATIAL_GRID_SIZE := 64

var _viewer: Node
var _world_layer_idx := -1
var _stage6_loaded := false
var _stage6_load_error := ""
var _stage6_parts: Array[Dictionary] = []
var _spatial_buckets: Dictionary = {}
var _stage6_province_count := 0
var _stage6_zone_count := 0


func _ready() -> void:
	# Этот узел — ребёнок Main, а TileMapViewer.gd висит на самом Main.
	# child._ready вызывается раньше parent._ready, поэтому ждём один deferred
	# вызов: к этому моменту TileMapViewer уже зарегистрировал все `_layers`.
	call_deferred("_setup_after_viewer_ready")


func _setup_after_viewer_ready() -> void:
	_viewer = get_parent()
	if not is_instance_valid(_viewer):
		push_warning("WorldLandStage6Controller: нет TileMapViewer")
		return

	var layers_variant: Variant = _viewer.get("_layers")
	if not (layers_variant is Array):
		push_warning("WorldLandStage6Controller: TileMapViewer._layers недоступен")
		return
	var layers: Array = layers_variant

	# Старт игры: абсолютно все тайловые слои выключены, кроме составного
	# слоя 2 (base_depth + shallow). Это также гасит старые dev-слои,
	# которые в отдельных экспериментах могли иметь visible=true.
	for index in range(layers.size()):
		layers[index]["visible"] = false

	var base_idx := int(_viewer.get("_ocean_v_baked_base_depth_layer_idx"))
	var shallow_idx := int(_viewer.get("_ocean_v_baked_shallow_layer_idx"))
	if base_idx >= 0 and base_idx < layers.size():
		layers[base_idx]["visible"] = true
	else:
		push_warning("WorldLandStage6Controller: базовая часть слоя 2 не найдена")
	if shallow_idx >= 0 and shallow_idx < layers.size():
		layers[shallow_idx]["visible"] = true

	_register_world_layer(layers)
	_viewer.set("_layers", layers)
	_hide_standalone_debug_viewers()


func _register_world_layer(layers: Array) -> void:
	# Визуальную геометрию не дублируем: фундаментальный слой уже содержит
	# слитый контур суши без внутренних провинциальных/клеточных линий.
	var visual_provider: Variant = null
	for layer in layers:
		if str(layer.get("name", "")) == "Суша/Море":
			visual_provider = layer.get("provider", null)
			break
	if visual_provider == null:
		push_warning("WorldLandStage6Controller: слой «Суша/Море» не найден")
		return

	# Новые provider-слои в этом проекте добавляются только В КОНЕЦ массива,
	# чтобы не сдвигать старые hardcoded индексы TileMapViewer.
	_world_layer_idx = layers.size()
	layers.append({
		"name": WORLD_LAYER_NAME,
		"provider": visual_provider,
		"visible": false,
		"z_index": WORLD_LAYER_Z_INDEX,
	})


func _hide_standalone_debug_viewers() -> void:
	# Эти Node2D не входят в TileMapViewer._layers. Явно скрываем их на старте,
	# чтобы требование «виден только слой 2» выполнялось и для новых dev-viewer'ов.
	var names := [
		"WorldRegionsDraftViewer",
		"WorldRegionManualEditor",
		"WorldAdmin1SafeViewer",
		"SloveniaAdmin1ComparisonViewer",
		"Layer8SmallProvinceViewer",
		"Layer8MergeResultViewer",
		"Layer8NormalizedCellsViewer",
		"BritainNorthAtlanticViewer",
		"IndiaCellTestViewer",
		"IndiaGameProvinceTestViewer",
	]
	for node_name in names:
		var node := _viewer.get_node_or_null(NodePath(str(node_name)))
		if is_instance_valid(node) and node is CanvasItem:
			node.visible = false


func _unhandled_input(event: InputEvent) -> void:
	if not is_instance_valid(_viewer):
		return

	# Отдельная клавиша для НОВОГО агрегированного уровня. Штатный J/F6-stage
	# не трогаем: J по-прежнему показывает обычные финальные зоны Stage 6.
	if event is InputEventKey and event.pressed and not event.echo \
			and event.physical_keycode == KEY_F7:
		_set_world_layer_visible(not _is_world_layer_visible())
		get_viewport().set_input_as_handled()
		return

	if event is InputEventMouseButton and event.pressed \
			and event.button_index == MOUSE_BUTTON_LEFT \
			and _is_world_layer_visible():
		var camera := _viewer.get_node_or_null("Camera2D") as Camera2D
		if not is_instance_valid(camera):
			return
		if not _ensure_stage6_loaded():
			_show_top_info("Мир не загружен: %s" % _stage6_load_error)
			return
		var world_pos := camera.get_global_mouse_position()
		if not _stage6_contains_point(world_pos):
			return
		_show_top_info("Мир: %s [%s]" % [WORLD_LAND_NAME, WORLD_LAND_ID])
		get_viewport().set_input_as_handled()


func _set_world_layer_visible(active: bool) -> void:
	if not is_instance_valid(_viewer):
		return
	var layers_variant: Variant = _viewer.get("_layers")
	if not (layers_variant is Array):
		return
	var layers: Array = layers_variant
	if _world_layer_idx < 0 or _world_layer_idx >= layers.size():
		return

	if active and not _ensure_stage6_loaded():
		_show_top_info("Мир не включён: %s" % _stage6_load_error)
		return

	layers[_world_layer_idx]["visible"] = active
	_viewer.set("_layers", layers)
	if active:
		_show_top_info(
			"Мир — вся суша: Stage 6, %d провинций / %d зон → 1 территория; F7 скрыть"
			% [_stage6_province_count, _stage6_zone_count]
		)
	else:
		_show_top_info("Слой «Мир — вся суша» скрыт")


func _is_world_layer_visible() -> bool:
	if not is_instance_valid(_viewer):
		return false
	var layers_variant: Variant = _viewer.get("_layers")
	if not (layers_variant is Array):
		return false
	var layers: Array = layers_variant
	return _world_layer_idx >= 0 and _world_layer_idx < layers.size() \
		and bool(layers[_world_layer_idx].get("visible", false))


func get_world_area_id_at(world_pos: Vector2) -> String:
	if not _ensure_stage6_loaded():
		return ""
	return WORLD_LAND_ID if _stage6_contains_point(world_pos) else ""


func _ensure_stage6_loaded() -> bool:
	if _stage6_loaded:
		return _stage6_load_error.is_empty()
	_stage6_loaded = true
	_stage6_parts.clear()
	_spatial_buckets.clear()
	_stage6_province_count = 0
	_stage6_zone_count = 0

	if not FileAccess.file_exists(STAGE6_PATH):
		_stage6_load_error = "не найден %s" % STAGE6_PATH
		return false
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(STAGE6_PATH))
	if typeof(parsed) != TYPE_DICTIONARY:
		_stage6_load_error = "неверный JSON Stage 6"
		return false
	var data: Dictionary = parsed
	if str(data.get("format", "")) != EXPECTED_FORMAT:
		_stage6_load_error = "ожидался формат %s" % EXPECTED_FORMAT
		return false

	for raw_province in data.get("provinces", []):
		if not raw_province is Dictionary:
			continue
		_stage6_province_count += 1
		var province: Dictionary = raw_province
		for raw_zone in province.get("zones", []):
			if not raw_zone is Dictionary:
				continue
			_stage6_zone_count += 1
			var zone: Dictionary = raw_zone
			for raw_part in zone.get("parts", []):
				if not raw_part is Dictionary:
					continue
				var rings := _to_rings((raw_part as Dictionary).get("rings", []))
				if rings.is_empty():
					continue
				var bbox := _rings_bbox(rings)
				var part_index := _stage6_parts.size()
				_stage6_parts.append({"rings": rings, "bbox": bbox})
				_add_part_to_spatial_index(part_index, bbox)

	if _stage6_parts.is_empty():
		_stage6_load_error = "Stage 6 не содержит полигонов суши"
		return false
	_stage6_load_error = ""
	return true


func _add_part_to_spatial_index(part_index: int, bbox: Rect2) -> void:
	var x0 := clampi(floori(bbox.position.x / WORLD_PX * SPATIAL_GRID_SIZE), 0, SPATIAL_GRID_SIZE - 1)
	var y0 := clampi(floori(bbox.position.y / WORLD_PX * SPATIAL_GRID_SIZE), 0, SPATIAL_GRID_SIZE - 1)
	var x1 := clampi(floori(bbox.end.x / WORLD_PX * SPATIAL_GRID_SIZE), 0, SPATIAL_GRID_SIZE - 1)
	var y1 := clampi(floori(bbox.end.y / WORLD_PX * SPATIAL_GRID_SIZE), 0, SPATIAL_GRID_SIZE - 1)
	for by in range(y0, y1 + 1):
		for bx in range(x0, x1 + 1):
			var bucket_id := by * SPATIAL_GRID_SIZE + bx
			var bucket: Array = _spatial_buckets.get(bucket_id, [])
			bucket.append(part_index)
			_spatial_buckets[bucket_id] = bucket


func _stage6_contains_point(point: Vector2) -> bool:
	if point.x < 0.0 or point.x > WORLD_PX or point.y < 0.0 or point.y > WORLD_PX:
		return false
	var bx := clampi(floori(point.x / WORLD_PX * SPATIAL_GRID_SIZE), 0, SPATIAL_GRID_SIZE - 1)
	var by := clampi(floori(point.y / WORLD_PX * SPATIAL_GRID_SIZE), 0, SPATIAL_GRID_SIZE - 1)
	for raw_index in _spatial_buckets.get(by * SPATIAL_GRID_SIZE + bx, []):
		var part: Dictionary = _stage6_parts[int(raw_index)]
		var bbox: Rect2 = part["bbox"]
		if not bbox.has_point(point):
			continue
		if _point_in_polygon_rings(point, part["rings"]):
			return true
	return false


func _point_in_polygon_rings(point: Vector2, rings: Array) -> bool:
	if rings.is_empty():
		return false
	var outer: PackedVector2Array = rings[0]
	if not Geometry2D.is_point_in_polygon(point, outer):
		return false
	for index in range(1, rings.size()):
		var hole: PackedVector2Array = rings[index]
		if Geometry2D.is_point_in_polygon(point, hole):
			return false
	return true


func _to_rings(raw_rings: Variant) -> Array:
	var result: Array = []
	if not raw_rings is Array:
		return result
	for raw_ring in raw_rings:
		if not raw_ring is Array:
			continue
		var ring := PackedVector2Array()
		for raw_point in raw_ring:
			if raw_point is Array and raw_point.size() >= 2:
				ring.append(Vector2(float(raw_point[0]), float(raw_point[1])))
		if ring.size() >= 3:
			result.append(ring)
	return result


func _rings_bbox(rings: Array) -> Rect2:
	var first := true
	var min_x := 0.0
	var min_y := 0.0
	var max_x := 0.0
	var max_y := 0.0
	for ring in rings:
		for point in ring:
			var p: Vector2 = point
			if first:
				min_x = p.x
				min_y = p.y
				max_x = p.x
				max_y = p.y
				first = false
			else:
				min_x = minf(min_x, p.x)
				min_y = minf(min_y, p.y)
				max_x = maxf(max_x, p.x)
				max_y = maxf(max_y, p.y)
	return Rect2(Vector2(min_x, min_y), Vector2(max_x - min_x, max_y - min_y))


func _show_top_info(message: String) -> void:
	if is_instance_valid(_viewer) and _viewer.has_method("_show_top_info"):
		_viewer.call("_show_top_info", message)
	else:
		print(message)
