class_name SubdivisionFinalPolygonsStage
extends Node2D
## Этап 5: настоящие игровые полигоны Fantasy Admin-2.
##
## В отличие от U/Stage 4 здесь НЕ строится геометрия из микроклеток.
## Offline Python уже выполнил polygonize, назначил стабильные ID и проверил
## покрытие/пересечения/соседство. Godot только читает готовый JSON.

const FINAL_PATH := "res://assets/subdivision_stages/lacoruna_final_subdivision.json"
const EXPECTED_FORMAT := "province_final_subdivision/v1"
const GAMEPLAY_COAST_PATH := "res://assets/provinces_iberia_selection_2km.json"
const GAMEPLAY_PROVINCE_ID := "spain__la_coru_a"
const EXPECTED_ZONE_COUNT := 4
const EXPECTED_COAST_KM := 2.0

const OUTER_BORDER_COLOR := Color(1.0, 0.77, 0.24, 1.0)
const SHARED_BORDER_SHADOW := Color(0.015, 0.025, 0.035, 0.98)
const SHARED_BORDER_COLOR := Color(0.96, 0.96, 0.93, 0.98)
const SELECT_BORDER_COLOR := Color(1.0, 0.92, 0.52, 1.0)

var _camera: Camera2D
var _ui_layer: CanvasLayer
var _root_viewer: Node
var _panel: PanelContainer
var _summary_label: Label

var _zones: Array[Dictionary] = []
var _shared_lines: Array[PackedVector2Array] = []
var _outer_rings: Array[PackedVector2Array] = []
var _validation: Dictionary = {}
var _generation: Dictionary = {}
var _selected_zone_id := ""
var _last_error := ""
var _last_zoom := -1.0


func _ready() -> void:
	_camera = get_node_or_null("../Camera2D") as Camera2D
	_ui_layer = get_node_or_null("../UI") as CanvasLayer
	_root_viewer = get_parent()
	z_index = 220
	visible = false
	if not _load_final():
		push_warning("SubdivisionFinalPolygonsStage: %s" % _last_error)
	_build_panel()
	set_process(true)
	set_process_input(true)


func get_last_error() -> String:
	return _last_error


func set_active(active: bool) -> void:
	if active and not _last_error.is_empty():
		return
	visible = active
	if is_instance_valid(_panel):
		_panel.visible = active
	if active:
		_hide_previous_stages()
		_last_zoom = -1.0
		queue_redraw()
		_show_top_info("Этап 5: 4 финальные игровые территории — Y скрыть; клик по зоне показывает её ID")


func _process(_delta: float) -> void:
	if not visible:
		return
	var zoom := maxf(0.0001, _camera.zoom.x if is_instance_valid(_camera) else 1.0)
	if absf(zoom - _last_zoom) > 0.0001:
		_last_zoom = zoom
		queue_redraw()


func _input(event: InputEvent) -> void:
	if not visible:
		return
	var mouse_event := event as InputEventMouseButton
	if mouse_event == null or not mouse_event.pressed or mouse_event.button_index != MOUSE_BUTTON_LEFT:
		return
	var point := get_global_mouse_position()
	var zone := _zone_at_point(point)
	if zone.is_empty():
		return
	_selected_zone_id = str(zone.get("id", ""))
	queue_redraw()
	var area_share := float(zone.get("area_share", 0.0)) * 100.0
	var neighbors: Array = zone.get("neighbors", [])
	_show_top_info(
		"Этап 5 • %s • ID %s • площадь %.2f%% • соседей %d"
		% [str(zone.get("name", "Зона")), _selected_zone_id, area_share, neighbors.size()]
	)
	get_viewport().set_input_as_handled()


func _load_final() -> bool:
	if not FileAccess.file_exists(FINAL_PATH):
		return _fail("не найден результат Stage 5: %s; сначала запусти offline-генератор" % FINAL_PATH)
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(FINAL_PATH))
	if typeof(parsed) != TYPE_DICTIONARY:
		return _fail("Stage 5 JSON имеет неверный формат")
	var data: Dictionary = parsed
	if str(data.get("format", "")) != EXPECTED_FORMAT:
		return _fail("ожидался формат %s" % EXPECTED_FORMAT)

	var coast: Dictionary = data.get("gameplay_coast", {})
	if absf(float(coast.get("land_inset_km", -1.0)) - EXPECTED_COAST_KM) > 0.0001:
		return _fail("Stage 5 построен не по правилу 2 км от берега")
	if not bool(coast.get("authoritative_outer_boundary", false)):
		return _fail("2-км gameplay coastline не помечен как authoritative")

	_validation = data.get("validation", {})
	_generation = data.get("generation", {})
	if int(_validation.get("zone_count", 0)) != EXPECTED_ZONE_COUNT:
		return _fail("Stage 5 должен содержать ровно 4 зоны")
	if not bool(_validation.get("topology_locked", false)):
		return _fail("Stage 5 не прошёл topology lock")

	_zones.clear()
	for raw_zone in data.get("zones", []):
		if not raw_zone is Dictionary:
			continue
		var zone: Dictionary = raw_zone
		var parsed_polygons: Array = []
		for raw_polygon in zone.get("polygons", []):
			if not raw_polygon is Dictionary:
				continue
			var rings := _to_rings(raw_polygon.get("rings", []))
			if not rings.is_empty():
				parsed_polygons.append(rings)
		if parsed_polygons.is_empty():
			return _fail("у финальной зоны %s нет polygon geometry" % str(zone.get("id", "?")))
		zone["_parsed_polygons"] = parsed_polygons
		_zones.append(zone)
	if _zones.size() != EXPECTED_ZONE_COUNT:
		return _fail("в Stage 5 JSON прочитано не 4 зоны")

	_shared_lines.clear()
	for raw_shared in data.get("shared_boundaries", []):
		if not raw_shared is Dictionary:
			continue
		for raw_line in raw_shared.get("lines", []):
			var line := _to_polyline(raw_line)
			if line.size() >= 2:
				_shared_lines.append(line)

	if not _load_outer_rings():
		return false
	_last_error = ""
	return true


func _load_outer_rings() -> bool:
	if not FileAccess.file_exists(GAMEPLAY_COAST_PATH):
		return _fail("не найден gameplay coastline слоя 4")
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(GAMEPLAY_COAST_PATH))
	if typeof(parsed) != TYPE_DICTIONARY:
		return _fail("gameplay coastline слоя 4 имеет неверный JSON")
	var data: Dictionary = parsed
	_outer_rings.clear()
	var part_prefix := GAMEPLAY_PROVINCE_ID + "__selection_part_"
	for raw_cell in data.get("cells", []):
		if not raw_cell is Dictionary:
			continue
		var cell_id := str(raw_cell.get("id", ""))
		if cell_id != GAMEPLAY_PROVINCE_ID and not cell_id.begins_with(part_prefix):
			continue
		for ring in _to_rings(raw_cell.get("rings", [])):
			_outer_rings.append(ring)
	if _outer_rings.is_empty():
		return _fail("не найден 2-км контур Ла-Коруньи")
	return true


func _draw() -> void:
	if not visible or _zones.is_empty():
		return
	var zoom := maxf(0.0001, _camera.zoom.x if is_instance_valid(_camera) else 1.0)
	var shared_shadow_width := 3.5 / zoom
	var shared_width := 1.35 / zoom
	var outer_width := 2.8 / zoom
	var selected_width := 3.6 / zoom

	for zone in _zones:
		var fill := _zone_color(zone)
		var parsed_polygons: Array = zone.get("_parsed_polygons", [])
		for polygon_rings in parsed_polygons:
			if polygon_rings.is_empty():
				continue
			var outer: PackedVector2Array = polygon_rings[0]
			var fill_ring := _without_duplicate_closing_point(outer)
			if fill_ring.size() >= 3:
				draw_colored_polygon(fill_ring, fill)

	# Shared borders are stored once per zone pair in Stage 5 JSON.
	for line in _shared_lines:
		if line.size() >= 2:
			draw_polyline(line, SHARED_BORDER_SHADOW, shared_shadow_width, true)
	for line in _shared_lines:
		if line.size() >= 2:
			draw_polyline(line, SHARED_BORDER_COLOR, shared_width, true)

	# The outer line is read from exactly the same 2-km layer-4 coast source.
	for ring in _outer_rings:
		var closed := _closed(ring)
		if closed.size() >= 2:
			draw_polyline(closed, OUTER_BORDER_COLOR, outer_width, true)

	if not _selected_zone_id.is_empty():
		for zone in _zones:
			if str(zone.get("id", "")) != _selected_zone_id:
				continue
			for polygon_rings in zone.get("_parsed_polygons", []):
				for ring in polygon_rings:
					var closed := _closed(ring)
					if closed.size() >= 2:
						draw_polyline(closed, SELECT_BORDER_COLOR, selected_width, true)


func _zone_color(zone: Dictionary) -> Color:
	var values: Array = zone.get("color", [])
	if values.size() >= 3:
		return Color(float(values[0]), float(values[1]), float(values[2]), 0.42)
	return Color(0.72, 0.72, 0.72, 0.42)


func _zone_at_point(point: Vector2) -> Dictionary:
	for zone in _zones:
		for polygon_rings in zone.get("_parsed_polygons", []):
			if _point_in_polygon_rings(point, polygon_rings):
				return zone
	return {}


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


func _hide_previous_stages() -> void:
	if not is_instance_valid(_root_viewer):
		return
	if _root_viewer.has_method("_set_subdivision_contract_stage_visible"):
		_root_viewer.call("_set_subdivision_contract_stage_visible", false)
	if _root_viewer.has_method("_set_microcell_mesh_stage_visible"):
		_root_viewer.call("_set_microcell_mesh_stage_visible", false)
	if _root_viewer.has_method("_set_microcell_growth_stage_visible"):
		_root_viewer.call("_set_microcell_growth_stage_visible", false)
	var stage4_bridge := _root_viewer.get_node_or_null("SubdivisionStage4InputBridge")
	if is_instance_valid(stage4_bridge) and stage4_bridge.has_method("hide_stage4"):
		stage4_bridge.call("hide_stage4")


func _build_panel() -> void:
	if not is_instance_valid(_ui_layer):
		return
	_panel = PanelContainer.new()
	_panel.offset_left = 1370.0
	_panel.offset_top = 92.0
	_panel.offset_right = 1896.0
	_panel.offset_bottom = 430.0
	_panel.visible = false
	_ui_layer.add_child(_panel)

	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 14)
	margin.add_theme_constant_override("margin_top", 12)
	margin.add_theme_constant_override("margin_right", 14)
	margin.add_theme_constant_override("margin_bottom", 12)
	_panel.add_child(margin)
	var content := VBoxContainer.new()
	content.add_theme_constant_override("separation", 6)
	margin.add_child(content)

	var title := Label.new()
	title.text = "Этап 5 — Финальные игровые территории"
	title.add_theme_color_override("font_color", Color(1.0, 0.86, 0.58, 1.0))
	title.add_theme_font_size_override("font_size", 19)
	content.add_child(title)

	var explanation := Label.new()
	explanation.text = "Это уже не микроклетки и не preview-линии: четыре готовых полигона с постоянными ID. Общая граница хранится один раз, берег — тот же gameplay coast слоя 4 с отступом 2 км."
	explanation.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	explanation.add_theme_color_override("font_color", Color(0.94, 0.94, 0.94, 1.0))
	content.add_child(explanation)

	_summary_label = Label.new()
	_summary_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_summary_label.add_theme_color_override("font_color", Color(0.88, 0.91, 0.95, 1.0))
	if _last_error.is_empty():
		var adjacency: Array = _validation.get("adjacency_pairs", [])
		_summary_label.text = (
			"• Финальных зон: %d\n"
			+ "• Полигонализированных faces: %d\n"
			+ "• Пропущенная площадь: %.9f\n"
			+ "• Лишняя площадь: %.9f\n"
			+ "• Перекрытия: %.9f\n"
			+ "• Соседств: %d\n"
			+ "• Берег: authoritative gameplay coastline, 2 км"
		) % [
			_zones.size(),
			int(_generation.get("polygonized_face_count", 0)),
			float(_validation.get("coverage_missing_world_px2", 0.0)),
			float(_validation.get("coverage_extra_world_px2", 0.0)),
			float(_validation.get("max_pair_overlap_world_px2", 0.0)),
			adjacency.size(),
		]
	else:
		_summary_label.text = "Ошибка: %s" % _last_error
	content.add_child(_summary_label)

	var hint := Label.new()
	hint.text = "Y — показать/скрыть; ЛКМ — выбрать финальную территорию"
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	hint.add_theme_color_override("font_color", Color(1.0, 0.86, 0.58, 1.0))
	content.add_child(hint)


func _to_polyline(raw_points: Array) -> PackedVector2Array:
	var result := PackedVector2Array()
	for raw_point in raw_points:
		if raw_point is Array and raw_point.size() >= 2:
			result.append(Vector2(float(raw_point[0]), float(raw_point[1])))
	return result


func _to_rings(raw_rings: Array) -> Array[PackedVector2Array]:
	var result: Array[PackedVector2Array] = []
	for raw_ring in raw_rings:
		if not raw_ring is Array or raw_ring.size() < 3:
			continue
		var ring := _to_polyline(raw_ring)
		if ring.size() >= 3:
			result.append(ring)
	return result


func _without_duplicate_closing_point(ring: PackedVector2Array) -> PackedVector2Array:
	var result := ring.duplicate()
	if result.size() >= 2 and result[0].distance_squared_to(result[result.size() - 1]) <= 1.0e-10:
		result.remove_at(result.size() - 1)
	return result


func _closed(ring: PackedVector2Array) -> PackedVector2Array:
	var result := ring.duplicate()
	if result.size() >= 2 and result[0].distance_squared_to(result[result.size() - 1]) > 1.0e-10:
		result.append(result[0])
	return result


func _show_top_info(message: String) -> void:
	if is_instance_valid(_root_viewer) and _root_viewer.has_method("_show_top_info"):
		_root_viewer.call("_show_top_info", message)
	else:
		print(message)


func _fail(message: String) -> bool:
	_last_error = message
	return false
