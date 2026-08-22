extends Node2D
## Z — единая кликабельная суша мира, построенная СТРОГО из геометрии F6.
##
## Источник истины — уже существующий Layer8NormalizedCellsViewer:
##   assets/land_cells_normalized/world_manifest.json
##   assets/land_cells_normalized/shards/shard_000_of_016.json ... shard_015_of_016.json
##
## F6 загружает 12 902 нормализованные клетки мира. Этот контроллер не читает
## land_sea, provinces, Stage 6 и любые другие геослои. При первом Z он просит
## F6-viewer загрузить свой канонический набор и использует РОВНО те же
## `viewer_parts` для отрисовки и тот же `_hit_at_point()` для клика.
##
## Все клетки рисуются одной заливкой без внутренних линий. Логически любая
## клетка F6 возвращает один и тот же ID `world_land`.

const WORLD_LAND_ID := "world_land"
const WORLD_LAND_NAME := "Вся суша мира"
const EXPECTED_CELLS := 12902
const EXPECTED_PROVINCES := 2886

const LAND_FILL := Color(0.45, 0.52, 0.39, 0.96)
const LAND_SELECTED_FILL := Color(0.93, 0.72, 0.28, 0.98)

var _viewer: Node
var _f6_viewer: Node
var _cells: Array = []
var _world_ready := false
var _load_error := ""
var _selected := false


func _ready() -> void:
	visible = false
	z_index = 240
	set_process_input(true)
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
		_selected = true
		queue_redraw()
		_show_top_info("Выбрано: %s [%s] — все 12 902 клеток F6 = одна область" % [WORLD_LAND_NAME, WORLD_LAND_ID])
		get_viewport().set_input_as_handled()
	elif _selected:
		_selected = false
		queue_redraw()


func _set_world_visible(active: bool) -> void:
	if active:
		if not _ensure_f6_world_ready():
			_show_top_info("Слой Z не включён: %s" % _load_error)
			return
		# Не включаем сам F6: он остаётся отдельным слоем со своими границами.
		if is_instance_valid(_f6_viewer) and _f6_viewer.has_method("set_active"):
			_f6_viewer.call("set_active", false)
		_selected = false
		visible = true
		queue_redraw()
		_show_top_info("Z — вся суша мира: 12 902 клетки F6 / 2 886 провинций → 1 world_land; ЛКМ выбрать")
	else:
		_selected = false
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

	# Используем штатный загрузчик F6. Это гарантирует, что Z и F6 всегда
	# смотрят на один и тот же manifest/shards и одинаково интерпретируют rings.
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
	_cells = cells_variant
	if _cells.size() != EXPECTED_CELLS:
		_load_error = "ожидалось %d клеток F6, получено %d" % [EXPECTED_CELLS, _cells.size()]
		return false

	var parents_variant: Variant = _f6_viewer.get("_parents")
	if parents_variant is Array and parents_variant.size() != EXPECTED_PROVINCES:
		_load_error = "ожидалось %d провинций F6, получено %d" % [EXPECTED_PROVINCES, parents_variant.size()]
		return false

	_world_ready = true
	_load_error = ""
	return true


func _draw() -> void:
	if not visible or not _world_ready:
		return
	var fill_color := LAND_SELECTED_FILL if _selected else LAND_FILL

	# Рисуем ТОЛЬКО polygon parts, которые уже подготовил F6 viewer.
	# Никаких draw_polyline: внутренних границ клеток здесь нет.
	for cell_value in _cells:
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
			var fill_ring := _without_duplicate_closing_point(outer)
			if fill_ring.size() < 3:
				continue
			# Защита от некорректной геометрии: как и в других world viewers,
			# рисуем только то, что Godot способен триангулировать.
			if not Geometry2D.triangulate_polygon(fill_ring).is_empty():
				draw_colored_polygon(fill_ring, fill_color)


func get_world_area_id_at(world_pos: Vector2) -> String:
	if not _ensure_f6_world_ready():
		return ""
	return WORLD_LAND_ID if _contains_f6_land(world_pos) else ""


func _contains_f6_land(world_pos: Vector2) -> bool:
	if not is_instance_valid(_f6_viewer):
		return false
	# Тот же spatial grid + bbox + rings hit-test, который используется при
	# обычном ЛКМ на F6. Значит Z кликается ровно там же, где существует F6-клетка.
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
