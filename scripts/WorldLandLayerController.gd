extends Node
## Верхний географический уровень «Мир — вся суша».
##
## Задачи этого контроллера:
## 1) после полной инициализации TileMapViewer оставить при старте видимым
##    только составной слой 2 (base_depth + shallow);
## 2) добавить отдельный слой «Мир — вся суша»;
## 3) трактовать любой кусок суши как ОДНУ логическую кликабельную область
##    с постоянным id `world_land`.
##
## Геометрия берётся из assets/land_sea.json. Этот файл уже является
## офлайн-dissolve всей суши (unary_union в build_land_sea.py), поэтому мы
## НЕ объединяем тысячи полигонов в runtime Godot. Для визуала переиспользуем
## уже существующий провайдер слоя «Суша/Море» (обычно baked PNG), а отдельный
## IrregularCellProvider нужен только для point-in-polygon по клику.

const WORLD_LAND_ID := "world_land"
const WORLD_LAND_NAME := "Вся суша мира"
const WORLD_LAND_SOURCE_PATH := "res://assets/land_sea.json"
const WORLD_LAYER_NAME := "Мир — вся суша"
const WORLD_LAYER_Z_INDEX := 40
const IRREGULAR_CELL_PROVIDER_SCRIPT := preload("res://scripts/IrregularCellProvider.gd")

var _viewer: Node
var _world_layer_idx := -1
var _pick_provider: Node
var _world_info_label: Label


func _ready() -> void:
	# У дочернего узла _ready() вызывается до _ready() родителя. Отложенный
	# вызов гарантирует, что TileMapViewer уже успел зарегистрировать ВСЕ
	# свои слои и индексы, включая составной слой 2.
	call_deferred("_setup_after_viewer_ready")


func _setup_after_viewer_ready() -> void:
	_viewer = get_parent()
	if not is_instance_valid(_viewer):
		push_warning("WorldLandLayerController: нет родительского TileMapViewer")
		return

	var layers = _viewer.get("_layers")
	if not (layers is Array):
		push_warning("WorldLandLayerController: TileMapViewer._layers недоступен")
		return

	# Требование стартового экрана: выключить вообще все тайловые слои,
	# затем вернуть только две части, которые вместе являются клавишей 2.
	_hide_all_layers_except_layer_2(layers)

	# Новый уровень добавляем СТРОГО в конец массива — TileMapViewer сам
	# содержит такое архитектурное правило, чтобы не сдвигать старые индексы.
	_setup_world_land_layer(layers)
	_viewer.set("_layers", layers)

	_hide_non_tile_debug_overlays()
	_build_world_info_label()


func _hide_all_layers_except_layer_2(layers: Array) -> void:
	for i in range(layers.size()):
		layers[i]["visible"] = false

	var base_idx := int(_viewer.get("_ocean_v_baked_base_depth_layer_idx"))
	var shallow_idx := int(_viewer.get("_ocean_v_baked_shallow_layer_idx"))

	if base_idx >= 0 and base_idx < layers.size():
		layers[base_idx]["visible"] = true
	else:
		push_warning("WorldLandLayerController: базовая часть слоя 2 не найдена")

	if shallow_idx >= 0 and shallow_idx < layers.size():
		layers[shallow_idx]["visible"] = true


func _setup_world_land_layer(layers: Array) -> void:
	if not FileAccess.file_exists(WORLD_LAND_SOURCE_PATH):
		push_warning("WorldLandLayerController: нет %s" % WORLD_LAND_SOURCE_PATH)
		return

	# Логический провайдер НЕ добавляем в _layers: он не рендерит тайлы и
	# служит только для определения «клик пришёлся на сушу или нет».
	_pick_provider = IRREGULAR_CELL_PROVIDER_SCRIPT.new(WORLD_LAND_SOURCE_PATH)
	add_child(_pick_provider)

	# Для картинки берём уже существующий провайдер фундаментального слоя
	# «Суша/Море». В нормальном билде это BakedTileProvider, то есть новый
	# уровень не создаёт второй тяжёлый живой рендер всей планеты.
	var visual_provider: Node = null
	for layer in layers:
		if str(layer.get("name", "")) == "Суша/Море":
			visual_provider = layer.get("provider", null) as Node
			break

	if visual_provider == null:
		# Fallback для dev-сборки без baked слоя: используем тот же источник
		# напрямую. В релизной/обычной конфигурации эта ветка не нужна.
		visual_provider = IRREGULAR_CELL_PROVIDER_SCRIPT.new(
			WORLD_LAND_SOURCE_PATH,
			Color(0.10, 0.08, 0.06, 0.8),
			0.60,
			0.35,
			0.88,
			PackedColorArray([Color(0.55, 0.50, 0.35, 0.60)]),
			1.4)
		add_child(visual_provider)

	_world_layer_idx = layers.size()
	layers.append({
		"name": WORLD_LAYER_NAME,
		"provider": visual_provider,
		"visible": false,
		"z_index": WORLD_LAYER_Z_INDEX,
	})


func _hide_non_tile_debug_overlays() -> void:
	# Большинство этих узлов и так создаются скрытыми. Явное выключение здесь
	# защищает стартовый экран от будущих изменений их default-visible.
	var simple_visible_props := [
		"_province_city_markers",
		"_small_provinces_markers",
		"_island_piece_markers",
		"_topology_graph_edit_layer",
		"_cell_boundary_draft_layer",
		"_cell_boundary_draft_layer_grid",
		"_iberia_land_cells_panel",
		"_world_provinces_panel",
		"_water_cells_panel",
		"_regions_iberia_panel",
		"_provinces_iberia_panel",
		"_cell_boundary_tool_panel",
		"_cell_boundary_tool_panel_grid",
		"_lacoruna_manual_drawing_panel",
		"_topology_graph_edit_panel",
		"_regional_claims_scroll",
		"_ocean_v_panel",
	]
	for prop_name in simple_visible_props:
		var node = _viewer.get(prop_name)
		if is_instance_valid(node) and node is CanvasItem:
			node.visible = false

	var active_props := [
		"_sea_zones",
		"_subdivision_contract_overlay",
		"_microcell_mesh_overlay",
		"_microcell_growth_overlay",
	]
	for prop_name in active_props:
		var node = _viewer.get(prop_name)
		if is_instance_valid(node):
			if node.has_method("set_active"):
				node.call("set_active", false)
			elif node is CanvasItem:
				node.visible = false


func _build_world_info_label() -> void:
	var ui := _viewer.get_node_or_null("UI")
	if not is_instance_valid(ui):
		return
	_world_info_label = Label.new()
	_world_info_label.offset_left = 720.0
	_world_info_label.offset_top = 24.0
	_world_info_label.offset_right = 1320.0
	_world_info_label.offset_bottom = 70.0
	_world_info_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_world_info_label.add_theme_color_override("font_color", Color(1.0, 0.94, 0.78, 1.0))
	_world_info_label.add_theme_color_override("font_shadow_color", Color(0.02, 0.02, 0.02, 0.85))
	_world_info_label.add_theme_constant_override("shadow_offset_x", 1)
	_world_info_label.add_theme_constant_override("shadow_offset_y", 1)
	_world_info_label.add_theme_font_size_override("font_size", 20)
	_world_info_label.visible = false
	ui.add_child(_world_info_label)


func _unhandled_input(event: InputEvent) -> void:
	if not is_instance_valid(_viewer):
		return

	# F6 — новый верхний уровень «Мир — вся суша». В текущем TileMapViewer
	# F6 ничем не занят, поэтому не конфликтует со старыми debug-слоями.
	if event is InputEventKey and event.pressed and not event.echo \
			and event.physical_keycode == KEY_F6:
		_set_world_layer_visible(not _is_world_layer_visible())
		get_viewport().set_input_as_handled()
		return

	if event is InputEventMouseButton and event.pressed \
			and event.button_index == MOUSE_BUTTON_LEFT \
			and _is_world_layer_visible() \
			and is_instance_valid(_pick_provider):
		var camera := _viewer.get_node_or_null("Camera2D") as Camera2D
		if not is_instance_valid(camera):
			return
		var world_pos := camera.get_global_mouse_position()
		if get_world_area_id_at(world_pos).is_empty():
			return
		_show_world_info()
		get_viewport().set_input_as_handled()


func get_world_area_id_at(world_pos: Vector2) -> String:
	if not is_instance_valid(_pick_provider):
		return ""
	# У land_sea.json несколько физических кусков (Евразия, Америки,
	# острова), но наружу они намеренно схлопываются в ОДИН логический id.
	return WORLD_LAND_ID if not str(_pick_provider.call("get_cell_id_at", world_pos)).is_empty() else ""


func _is_world_layer_visible() -> bool:
	if not is_instance_valid(_viewer):
		return false
	var layers = _viewer.get("_layers")
	if not (layers is Array):
		return false
	return _world_layer_idx >= 0 and _world_layer_idx < layers.size() \
		and bool(layers[_world_layer_idx].get("visible", false))


func _set_world_layer_visible(visible: bool) -> void:
	if not is_instance_valid(_viewer):
		return
	var layers = _viewer.get("_layers")
	if not (layers is Array):
		return
	if _world_layer_idx < 0 or _world_layer_idx >= layers.size():
		return
	layers[_world_layer_idx]["visible"] = visible
	_viewer.set("_layers", layers)
	if not visible and is_instance_valid(_world_info_label):
		_world_info_label.visible = false


func _show_world_info() -> void:
	if not is_instance_valid(_world_info_label):
		return
	_world_info_label.text = "Мир: %s [%s]" % [WORLD_LAND_NAME, WORLD_LAND_ID]
	_world_info_label.visible = true
