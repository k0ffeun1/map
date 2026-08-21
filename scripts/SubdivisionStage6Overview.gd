extends Node2D
## Stage 6 overview: показывает готовые финальные зоны всей Иберии.
## Геометрия уже построена offline Python; здесь только чтение JSON, отрисовка и hit-test.

const DATA_PATH := "res://assets/subdivision_stage6/final_subdivisions.json"
const EXPECTED_FORMAT := "universal_final_subdivision/v1"
const IBERIA_PREFIXES := ["spain", "portugal", "andorra"]

const ZONE_BORDER_COLOR := Color(0.92, 0.94, 0.96, 0.92)
const ZONE_BORDER_SHADOW := Color(0.015, 0.025, 0.035, 0.92)
const SELECT_BORDER_COLOR := Color(1.0, 0.82, 0.28, 1.0)

var _camera: Camera2D
var _ui_layer: CanvasLayer
var _root_viewer: Node
var _panel: PanelContainer
var _summary_label: Label

var _zones: Array[Dictionary] = []
var _province_count := 0
var _total_zone_count := 0
var _selected_zone_id := ""
var _last_error := ""
var _last_zoom := -1.0


func _ready() -> void:
	_camera = get_node_or_null("../Camera2D") as Camera2D
	_ui_layer = get_node_or_null("../UI") as CanvasLayer
	_root_viewer = get_parent()
	z_index = 225
	visible = false
	if not _load_stage6():
		push_warning("SubdivisionStage6Overview: %s" % _last_error)
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
		_show_top_info("Stage 6: вся Иберия — %d провинций / %d финальных зон; J скрыть, ЛКМ выбрать" % [_province_count, _zones.size()])


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
	_show_top_info(
		"Stage 6 • %s • %s • %.1f км² • %s"
		% [
			str(zone.get("province_name", "?")),
			_selected_zone_id,
			float(zone.get("area_km2", 0.0)),
			str(zone.get("status", "?")),
		]
	)
	get_viewport().set_input_as_handled()


func _load_stage6() -> bool:
	if not FileAccess.file_exists(DATA_PATH):
		return _fail("не найден %s; сделай git pull" % DATA_PATH)
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(DATA_PATH))
	if typeof(parsed) != TYPE_DICTIONARY:
		return _fail("Stage 6 JSON имеет неверный формат")
	var data: Dictionary = parsed
	if str(data.get("format", "")) != EXPECTED_FORMAT:
		return _fail("ожидался формат %s" % EXPECTED_FORMAT)

	_total_zone_count = int(data.get("zone_count", 0))
	_zones.clear()
	var province_ids := {}
	for raw_province in data.get("provinces", []):
		if not raw_province is Dictionary:
			continue
		var province: Dictionary = raw_province
		var country_prefix := str(province.get("country_prefix", ""))
		if not IBERIA_PREFIXES.has(country_prefix):
			continue
		var province_id := str(province.get("province_id", ""))
		province_ids[province_id] = true
		var province_name := str(province.get("name", province_id))
		var status := str((province.get("validation", {}) as Dictionary).get("status", "?"))
		for raw_zone in province.get("zones", []):
			if not raw_zone is Dictionary:
				continue
			var zone: Dictionary = raw_zone.duplicate(true)
			var parsed_parts: Array = []
			for raw_part in zone.get("parts", []):
				if not raw_part is Dictionary:
					continue
				var rings := _to_rings((raw_part as Dictionary).get("rings", []))
				if not rings.is_empty():
					parsed_parts.append(rings)
			if parsed_parts.is_empty():
				return _fail("у зоны %s отсутствует polygon geometry" % str(zone.get("id", "?")))
			zone["_parsed_parts"] = parsed_parts
			zone["province_name"] = province_name
			zone["province_id"] = province_id
			zone["status"] = status
			_zones.append(zone)

	_province_count = province_ids.size()
	if _province_count <= 0 or _zones.is_empty():
		return _fail("в Stage 6 не найдена Иберия")
	_last_error = ""
	return true


func _draw() -> void:
	if not visible or _zones.is_empty():
		return
	var zoom := maxf(0.0001, _camera.zoom.x if is_instance_valid(_camera) else 1.0)
	var shadow_width := 2.7 / zoom
	var border_width := 0.95 / zoom
	var selected_width := 3.2 / zoom

	for zone in _zones:
		var fill := _zone_color(str(zone.get("id", "")))
		for polygon_rings in zone.get("_parsed_parts", []):
			if polygon_rings.is_empty():
				continue
			var outer: PackedVector2Array = polygon_rings[0]
			var fill_ring := _without_duplicate_closing_point(outer)
			if fill_ring.size() >= 3:
				draw_colored_polygon(fill_ring, fill)

	for zone in _zones:
		for polygon_rings in zone.get("_parsed_parts", []):
			for ring in polygon_rings:
				var closed := _closed(ring)
				if closed.size() >= 2:
					draw_polyline(closed, ZONE_BORDER_SHADOW, shadow_width, true)
	for zone in _zones:
		for polygon_rings in zone.get("_parsed_parts", []):
			for ring in polygon_rings:
				var closed := _closed(ring)
				if closed.size() >= 2:
					draw_polyline(closed, ZONE_BORDER_COLOR, border_width, true)

	if not _selected_zone_id.is_empty():
		for zone in _zones:
			if str(zone.get("id", "")) != _selected_zone_id:
				continue
			for polygon_rings in zone.get("_parsed_parts", []):
				for ring in polygon_rings:
					var closed := _closed(ring)
					if closed.size() >= 2:
						draw_polyline(closed, SELECT_BORDER_COLOR, selected_width, true)


func _zone_color(zone_id: String) -> Color:
	var h := absi(zone_id.hash()) % 1000
	var hue := float(h) / 1000.0
	return Color.from_hsv(hue, 0.42, 0.92, 0.34)


func _zone_at_point(point: Vector2) -> Dictionary:
	for zone in _zones:
		var bbox: Array = zone.get("bbox", [])
		if bbox.size() >= 4:
			if point.x < float(bbox[0]) or point.y < float(bbox[1]) or point.x > float(bbox[2]) or point.y > float(bbox[3]):
				continue
		for polygon_rings in zone.get("_parsed_parts", []):
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
	var stage5_bridge := _root_viewer.get_node_or_null("SubdivisionStage5InputBridge")
	if is_instance_valid(stage5_bridge) and stage5_bridge.has_method("hide_stage5"):
		stage5_bridge.call("hide_stage5")


func _build_panel() -> void:
	if not is_instance_valid(_ui_layer):
		return
	_panel = PanelContainer.new()
	_panel.offset_left = 1320.0
	_panel.offset_top = 92.0
	_panel.offset_right = 1896.0
	_panel.offset_bottom = 402.0
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
	title.text = "Stage 6 — Вся Иберия"
	title.add_theme_color_override("font_color", Color(1.0, 0.86, 0.58, 1.0))
	title.add_theme_font_size_override("font_size", 19)
	content.add_child(title)

	var explanation := Label.new()
	explanation.text = "Готовые финальные Admin-2 полигоны Испании, Португалии и Андорры. Это offline-результат универсального Q → K → U → Y конвейера."
	explanation.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	content.add_child(explanation)

	_summary_label = Label.new()
	_summary_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	if _last_error.is_empty():
		_summary_label.text = (
			"• Провинций Иберии: %d\n"
			+ "• Финальных зон Иберии: %d\n"
			+ "• Зон во всём Stage 6 наборе: %d\n"
			+ "• Береговые провинции используют правило 2 км\n"
			+ "• J — показать/скрыть\n"
			+ "• ЛКМ — выбрать территорию"
		) % [_province_count, _zones.size(), _total_zone_count]
	else:
		_summary_label.text = "Ошибка: %s" % _last_error
	content.add_child(_summary_label)


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


func _closed(ring: PackedVector2Array) -> PackedVector2Array:
	var result := ring.duplicate()
	if result.size() >= 2 and not result[0].is_equal_approx(result[result.size() - 1]):
		result.append(result[0])
	return result


func _without_duplicate_closing_point(ring: PackedVector2Array) -> PackedVector2Array:
	var result := ring.duplicate()
	if result.size() >= 2 and result[0].is_equal_approx(result[result.size() - 1]):
		result.resize(result.size() - 1)
	return result


func _show_top_info(message: String) -> void:
	if is_instance_valid(_root_viewer) and _root_viewer.has_method("_show_top_info"):
		_root_viewer.call("_show_top_info", message)
	else:
		print(message)


func _fail(message: String) -> bool:
	_last_error = message
	return false
