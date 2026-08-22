extends Node2D
## Z — единая кликабельная суша мира, построенная СТРОГО из геометрии F6.
##
## Источник истины — Layer8NormalizedCellsViewer (тот же набор, что показывает F6):
##   assets/land_cells_normalized/world_manifest.json
##   assets/land_cells_normalized/shards/shard_000_of_016.json ... shard_015_of_016.json
##
## Оптимизация Z:
## - НЕ рисуем 12 902 клетки одним гигантским CanvasItem;
## - polygon parts раскладываются по географическим chunk-батчам;
## - Godot может целиком отсекать chunk вне камеры;
## - draw-команды каждого chunk записываются один раз и кэшируются;
## - выбор world_land меняет только modulate общего root, без queue_redraw;
## - hit-test остаётся штатным F6 `_hit_at_point()` со spatial grid.

const WORLD_LAND_ID := "world_land"
const WORLD_LAND_NAME := "Вся суша мира"
const EXPECTED_CELLS := 12902
const EXPECTED_PROVINCES := 2886
const CHUNK_DEGREES := 10.0

const LAND_FILL := Color(0.45, 0.52, 0.39, 0.96)
const LAND_SELECTED_FILL := Color(0.93, 0.72, 0.28, 0.98)

const CHUNK_SCRIPT := preload("res://scripts/WorldLandNormalizedChunkNode.gd")

var _viewer: Node
var _f6_viewer: Node
var _world_ready := false
var _load_error := ""
var _selected := false

var _fill_root: Node2D
var _chunk_nodes: Array[Node2D] = []
var _polygon_count := 0


func _ready() -> void:
	visible = false
	z_index = 240
	set_process_input(true)

	_fill_root = Node2D.new()
	_fill_root.name = "WorldLandNormalizedChunks"
	_fill_root.modulate = LAND_FILL
	add_child(_fill_root)

	call_deferred("_setup_after_viewer_ready")


func _setup_after_viewer_ready() -> void:
	_viewer = get_parent()
	if not is_instance_valid(_viewer):
		push_warning("WorldLandNormalizedController: нет TileMapViewer")
		return

	_f6_viewer = _viewer.get_node_or_null("Layer8NormalizedCellsViewer")
	if not is_instance_valid(_f6_viewer):
		_load_error = "не найден Layer8NormalizedCellsViewer (F6)"
		push_error("WorldLandNormalizedController: %s" % _load_error)

	# При запуске виден только составной слой 2 — сохраняем прежнее требование.
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
		if key_event.physical_keycode == KEY_Z or key_event.keycode == KEY_Z:
			_set_world_visible(not visible)
			get_viewport().set_input_as_handled()
			return

	if not visible or not _world_ready:
		return

	var mouse_event := event as InputEventMouseButton
	if mouse_event == null or not mouse_event.pressed or mouse_event.button_index != MOUSE_BUTTON_LEFT:
		return

	var world_pos := get_global_mouse_position()
	if _contains_f6_land(world_pos):
		_set_selected(true)
		_show_top_info("Выбрано: %s [%s] — все 12 902 клеток F6 = одна область" % [WORLD_LAND_NAME, WORLD_LAND_ID])
		get_viewport().set_input_as_handled()
	elif _selected:
		_set_selected(false)


func _set_selected(value: bool) -> void:
	_selected = value
	if is_instance_valid(_fill_root):
		# Ключевая оптимизация: НИКАКОГО queue_redraw всей мировой геометрии.
		# Меняется только цвет уже закэшированных chunk CanvasItems.
		_fill_root.modulate = LAND_SELECTED_FILL if _selected else LAND_FILL


func _set_world_visible(active: bool) -> void:
	if active:
		if not _ensure_f6_world_ready():
			_show_top_info("Слой Z не включён: %s" % _load_error)
			return
		# F6 остаётся отдельным режимом с границами; его картинку одновременно не держим.
		if is_instance_valid(_f6_viewer) and _f6_viewer.has_method("set_active"):
			_f6_viewer.call("set_active", false)
		_set_selected(false)
		visible = true
		_show_top_info(
			"Z — world_land: 12 902 клеток F6 → %d локальных батчей / %d polygon parts; ЛКМ выбрать"
			% [_chunk_nodes.size(), _polygon_count]
		)
	else:
		_set_selected(false)
		visible = false
		_show_top_info("Слой Z «Вся суша мира» скрыт")


func _ensure_f6_world_ready() -> bool:
	if _world_ready:
		return true
	if not _load_error.is_empty():
		return false
	if not is_instance_valid(_f6_viewer):
		_load_error = "F6 viewer недоступен"
		return false

	_show_top_info("Z: загрузка канонических 16 shard F6...")
	_f6_viewer.call("_ensure_world_loaded")
	if _f6_viewer.has_method("is_world_loaded") and not bool(_f6_viewer.call("is_world_loaded")):
		_load_error = str(_f6_viewer.get("_last_error"))
		if _load_error.is_empty():
			_load_error = "F6 не смог загрузить мировой набор"
		return false

	var cells_variant: Variant = _f6_viewer.get("_cells")
	if not cells_variant is Array:
		_load_error = "F6 не отдал массив _cells"
		return false
	var cells: Array = cells_variant
	if cells.size() != EXPECTED_CELLS:
		_load_error = "ожидалось %d клеток F6, получено %d" % [EXPECTED_CELLS, cells.size()]
		return false

	var parents_variant: Variant = _f6_viewer.get("_parents")
	if parents_variant is Array and parents_variant.size() != EXPECTED_PROVINCES:
		_load_error = "ожидалось %d провинций F6, получено %d" % [EXPECTED_PROVINCES, parents_variant.size()]
		return false

	_show_top_info("Z: сборка локальных батчей суши...")
	_build_spatial_chunks(cells)
	if _chunk_nodes.is_empty() or _polygon_count <= 0:
		_load_error = "не удалось собрать polygon parts из F6"
		return false

	_world_ready = true
	_load_error = ""
	return true


func _build_spatial_chunks(cells: Array) -> void:
	for child in _fill_root.get_children():
		child.queue_free()
	_chunk_nodes.clear()
	_polygon_count = 0

	# Ключ = географический chunk 10x10 градусов. Кладём туда ОТДЕЛЬНЫЕ
	# polygon parts, а не целую multipart-клетку: удалённый остров не раздувает
	# bounding box CanvasItem через полмира и не ломает culling.
	var buckets: Dictionary = {}

	for cell_value in cells:
		if not cell_value is Dictionary:
			continue
		var cell: Dictionary = cell_value
		for part_value in cell.get("viewer_parts", []):
			if not part_value is Array:
				continue
			var rings: Array = part_value
			if rings.is_empty() or not rings[0] is PackedVector2Array:
				continue
			var outer: PackedVector2Array = rings[0]
			var polygon := _without_duplicate_closing_point(outer)
			if polygon.size() < 3:
				continue

			var center := _polygon_bbox_center(polygon)
			var chunk_key := Vector2i(
				int(floor(center.x / CHUNK_DEGREES)),
				int(floor(center.y / CHUNK_DEGREES))
			)
			var bucket_value: Variant = buckets.get(chunk_key, [])
			var bucket: Array = bucket_value if bucket_value is Array else []
			bucket.append(polygon)
			buckets[chunk_key] = bucket
			_polygon_count += 1

	var keys := buckets.keys()
	keys.sort_custom(func(a: Variant, b: Variant) -> bool:
		var av: Vector2i = a
		var bv: Vector2i = b
		return av.y < bv.y or (av.y == bv.y and av.x < bv.x)
	)

	for key_value in keys:
		var key: Vector2i = key_value
		var polygons_value: Variant = buckets[key]
		if not polygons_value is Array:
			continue
		var polygons: Array = polygons_value
		if polygons.is_empty():
			continue
		var chunk: Node2D = CHUNK_SCRIPT.new()
		chunk.name = "WorldLandChunk_%d_%d" % [key.x, key.y]
		_fill_root.add_child(chunk)
		chunk.call("setup", polygons)
		_chunk_nodes.append(chunk)


func _polygon_bbox_center(polygon: PackedVector2Array) -> Vector2:
	var min_x := polygon[0].x
	var min_y := polygon[0].y
	var max_x := polygon[0].x
	var max_y := polygon[0].y
	for i in range(1, polygon.size()):
		var p := polygon[i]
		min_x = minf(min_x, p.x)
		min_y = minf(min_y, p.y)
		max_x = maxf(max_x, p.x)
		max_y = maxf(max_y, p.y)
	return Vector2((min_x + max_x) * 0.5, (min_y + max_y) * 0.5)


func get_world_area_id_at(world_pos: Vector2) -> String:
	if not _ensure_f6_world_ready():
		return ""
	return WORLD_LAND_ID if _contains_f6_land(world_pos) else ""


func _contains_f6_land(world_pos: Vector2) -> bool:
	if not is_instance_valid(_f6_viewer):
		return false
	# Тот же spatial grid + bbox + rings hit-test, который использует F6.
	var hit: Variant = _f6_viewer.call("_hit_at_point", world_pos)
	return hit is Dictionary and not (hit as Dictionary).is_empty()


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
