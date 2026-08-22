extends Node2D
## Слой Z: «Вся суша мира» — строго производный ТОЛЬКО от Stage 6.
##
## Единственный источник геометрии:
##   res://assets/subdivision_stage6/final_subdivisions.json
##
## Никакие land_sea / «Суша/Море» / Natural Earth слои здесь не используются.
## Все polygon parts всех финальных зон Stage 6 образуют одну логическую
## область `world_land`: попадание в ЛЮБОЙ Stage-6 полигон = попадание в мир.
## Визуально все полигоны рисуются одной сплошной заливкой БЕЗ внутренних
## границ. При ЛКМ вся суша целиком меняет цвет, подчёркивая, что это одна
## выбираемая область, а не набор отдельных клеток.
##
## Z — показать/скрыть слой.

const STAGE6_PATH := "res://assets/subdivision_stage6/final_subdivisions.json"
const EXPECTED_FORMAT := "universal_final_subdivision/v1"
const WORLD_LAND_ID := "world_land"
const WORLD_LAND_NAME := "Вся суша мира"
const WORLD_PX := 8192.0
const SPATIAL_GRID_SIZE := 64

const LAND_FILL := Color(0.45, 0.52, 0.39, 0.96)
const LAND_SELECTED_FILL := Color(0.93, 0.72, 0.28, 0.98)

var _viewer: Node
var _stage6_loaded := false
var _stage6_load_error := ""
var _stage6_parts: Array[Dictionary] = []
var _spatial_buckets: Dictionary = {}
var _stage6_province_count := 0
var _stage6_zone_count := 0
var _selected := false


func _ready() -> void:
	visible = false
	z_index = 240
	set_process_input(true)
	# Этот узел — ребёнок Main, поэтому ждём parent._ready: только после него
	# TileMapViewer гарантированно закончит регистрацию своих тайловых слоёв.
	call_deferred("_setup_after_viewer_ready")


func _setup_after_viewer_ready() -> void:
	_viewer = get_parent()
	if not is_instance_valid(_viewer):
		push_warning("WorldLandStage6Controller: нет TileMapViewer")
		return

	# Сохраняем прежнее требование: при запуске виден только составной слой 2.
	var layers_variant: Variant = _viewer.get("_layers")
	if layers_variant is Array:
		var layers: Array = layers_variant
		for index in range(layers.size()):
			layers[index]["visible"] = false
		var base_idx := int(_viewer.get("_ocean_v_baked_base_depth_layer_idx"))
		var shallow_idx := int(_viewer.get("_ocean_v_baked_shallow_layer_idx"))
		if base_idx >= 0 and base_idx < layers.size():
			layers[base_idx]["visible"] = true
		if shallow_idx >= 0 and shallow_idx < layers.size():
			layers[shallow_idx]["visible"] = true
		_viewer.set("_layers", layers)

	_hide_standalone_debug_viewers()


func _hide_standalone_debug_viewers() -> void:
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


func _input(event: InputEvent) -> void:
	if not is_instance_valid(_viewer):
		return

	var key_event := event as InputEventKey
	if key_event != null and key_event.pressed and not key_event.echo:
		if key_event.physical_keycode == KEY_Z:
			_set_world_visible(not visible)
			get_viewport().set_input_as_handled()
			return

	if not visible:
		return

	var mouse_event := event as InputEventMouseButton
	if mouse_event == null or not mouse_event.pressed or mouse_event.button_index != MOUSE_BUTTON_LEFT:
		return
	if not _ensure_stage6_loaded():
		_show_top_info("Мир не загружен: %s" % _stage6_load_error)
		return

	# Node2D находится в той же мировой системе координат, что и Stage 6.
	var world_pos := get_global_mouse_position()
	if _stage6_contains_point(world_pos):
		_selected = true
		queue_redraw()
		_show_top_info(
			"Выбрано: %s [%s] — все %d зон Stage 6 считаются одной областью"
			% [WORLD_LAND_NAME, WORLD_LAND_ID, _stage6_zone_count]
		)
		get_viewport().set_input_as_handled()
	elif _selected:
		# Клик по воде снимает выбор, но сам клик не перехватываем.
		_selected = false
		queue_redraw()


func _set_world_visible(active: bool) -> void:
	if active:
		if not _ensure_stage6_loaded():
			_show_top_info("Слой Z не включён: %s" % _stage6_load_error)
			return
		_selected = false
		visible = true
		queue_redraw()
		_show_top_info(
			"Z — Вся суша мира: ТОЛЬКО Stage 6; %d провинций / %d зон → 1 world_land; ЛКМ выбрать"
			% [_stage6_province_count, _stage6_zone_count]
		)
	else:
		_selected = false
		visible = false
		_show_top_info("Слой Z «Вся суша мира» скрыт")


func _draw() -> void:
	if not visible or not _stage6_loaded or not _stage6_load_error.is_empty():
		return

	var fill_color := LAND_SELECTED_FILL if _selected else LAND_FILL
	# Никаких polyline/границ здесь намеренно нет. Все F6-полигоны получают
	# один цвет, поэтому внутреннее деление Stage 6 визуально исчезает.
	for part in _stage6_parts:
		var rings: Array = part.get("rings", [])
		if rings.is_empty():
			continue
		var outer: PackedVector2Array = rings[0]
		var fill_ring := _without_duplicate_closing_point(outer)
		if fill_ring.size() < 3:
			continue
		# Как и Stage6Overview: не отдаём renderer-у полигоны, которые Godot
		# не может триангулировать. Hit-test при этом всё равно остаётся точным.
		var triangles := Geometry2D.triangulate_polygon(fill_ring)
		if not triangles.is_empty():
			draw_colored_polygon(fill_ring, fill_color)


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

	# ВАЖНО: никаких country-prefix фильтров. Берём ВЕСЬ набор Stage 6.
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
		_stage6_load_error = "Stage 6 не содержит polygon geometry"
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


func _without_duplicate_closing_point(ring: PackedVector2Array) -> PackedVector2Array:
	var result := ring.duplicate()
	if result.size() >= 2 and result[0].is_equal_approx(result[result.size() - 1]):
		result.resize(result.size() - 1)
	return result


func _show_top_info(message: String) -> void:
	if is_instance_valid(_viewer) and _viewer.has_method("_show_top_info"):
		_viewer.call("_show_top_info", message)
	else:
		print(message)
