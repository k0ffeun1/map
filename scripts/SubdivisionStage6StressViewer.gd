extends Node2D
## Stage 6 stress viewer: циклический просмотр 7 контрольных провинций.
## H переключает тест; геометрия берётся из уже готового offline Stage 6 JSON.

const DATA_PATH := "res://assets/subdivision_stage6/final_subdivisions.json"
const MANIFEST_PATH := "res://assets/subdivision_stage6/test_manifest.json"
const EXPECTED_FORMAT := "universal_final_subdivision/v1"
const EXPECTED_MANIFEST_FORMAT := "stage6_test_manifest/v1"

const ROLE_ORDER := [
	"dense_complex_london",
	"island_sicily",
	"complex_coast_brittany",
	"long_narrow_stress",
	"large_inland_stress",
	"small_space_stress",
	"ordinary_coastal",
]
const ROLE_LABELS := {
	"dense_complex_london": "плотная / сложная",
	"island_sicily": "остров",
	"complex_coast_brittany": "сложное побережье",
	"long_narrow_stress": "длинная узкая форма",
	"large_inland_stress": "крупная внутренняя без моря",
	"small_space_stress": "маленькая / мало места",
	"ordinary_coastal": "обычная прибрежная",
}

const ZONE_BORDER_COLOR := Color(0.96, 0.97, 1.0, 0.96)
const ZONE_BORDER_SHADOW := Color(0.01, 0.02, 0.03, 0.96)
const SELECT_BORDER_COLOR := Color(1.0, 0.82, 0.28, 1.0)

var _camera: Camera2D
var _ui_layer: CanvasLayer
var _root_viewer: Node
var _panel: PanelContainer
var _summary_label: Label

var _controls: Array[Dictionary] = []
var _provinces_by_id: Dictionary = {}
var _zones: Array[Dictionary] = []
var _current_index: int = -1
var _selected_zone_id := ""
var _last_error := ""
var _last_zoom := -1.0


func _ready() -> void:
	_camera = get_node_or_null("../Camera2D") as Camera2D
	_ui_layer = get_node_or_null("../UI") as CanvasLayer
	_root_viewer = get_parent()
	z_index = 228
	visible = false
	if not _load_stress_data():
		push_warning("SubdivisionStage6StressViewer: %s" % _last_error)
	_build_panel()
	set_process(true)
	set_process_input(true)


func get_last_error() -> String:
	return _last_error


func get_control_count() -> int:
	return _controls.size()


func get_current_index() -> int:
	return _current_index


func get_current_province_id() -> String:
	if _current_index < 0 or _current_index >= _controls.size():
		return ""
	return str(_controls[_current_index].get("province_id", ""))


func get_current_role() -> String:
	if _current_index < 0 or _current_index >= _controls.size():
		return ""
	return str(_controls[_current_index].get("role", ""))


func advance() -> bool:
	if not _last_error.is_empty() or _controls.is_empty():
		return false
	visible = true
	if is_instance_valid(_panel):
		_panel.visible = true
	_hide_previous_stages()
	_current_index = (_current_index + 1) % _controls.size()
	_select_current()
	return true


func set_active(active: bool) -> void:
	if active and not _last_error.is_empty():
		return
	visible = active
	if is_instance_valid(_panel):
		_panel.visible = active
	if active:
		_hide_previous_stages()
		if _current_index < 0 and not _controls.is_empty():
			_current_index = 0
		_select_current()


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
	var zone := _zone_at_point(get_global_mouse_position())
	if zone.is_empty():
		return
	_selected_zone_id = str(zone.get("id", ""))
	queue_redraw()
	_show_top_info(
		"Stage 6 stress • %s • %s • %.1f км²"
		% [
			_current_name(),
			_selected_zone_id,
			float(zone.get("area_km2", 0.0)),
		]
	)
	get_viewport().set_input_as_handled()


func _load_stress_data() -> bool:
	if not FileAccess.file_exists(DATA_PATH):
		return _fail("не найден %s" % DATA_PATH)
	if not FileAccess.file_exists(MANIFEST_PATH):
		return _fail("не найден %s" % MANIFEST_PATH)

	var manifest_parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(MANIFEST_PATH))
	if typeof(manifest_parsed) != TYPE_DICTIONARY:
		return _fail("неверный test_manifest JSON")
	var manifest: Dictionary = manifest_parsed
	if str(manifest.get("format", "")) != EXPECTED_MANIFEST_FORMAT:
		return _fail("ожидался manifest %s" % EXPECTED_MANIFEST_FORMAT)

	var by_role: Dictionary = {}
	var raw_controls: Array = manifest.get("controls", [])
	for raw_control in raw_controls:
		if raw_control is Dictionary:
			var control: Dictionary = raw_control
			by_role[str(control.get("role", ""))] = control

	_controls.clear()
	for role in ROLE_ORDER:
		if not by_role.has(role):
			return _fail("в manifest отсутствует stress role %s" % role)
		_controls.append((by_role[role] as Dictionary).duplicate(true))

	var data_parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(DATA_PATH))
	if typeof(data_parsed) != TYPE_DICTIONARY:
		return _fail("Stage 6 JSON имеет неверный формат")
	var data: Dictionary = data_parsed
	if str(data.get("format", "")) != EXPECTED_FORMAT:
		return _fail("ожидался формат %s" % EXPECTED_FORMAT)

	var wanted: Dictionary = {}
	for control in _controls:
		wanted[str(control.get("province_id", ""))] = true

	_provinces_by_id.clear()
	var raw_provinces: Array = data.get("provinces", [])
	for raw_province in raw_provinces:
		if not raw_province is Dictionary:
			continue
		var province: Dictionary = raw_province
		var province_id := str(province.get("province_id", ""))
		if not wanted.has(province_id):
			continue

		var parsed_zones: Array[Dictionary] = []
		var raw_zones: Array = province.get("zones", [])
		for raw_zone in raw_zones:
			if not raw_zone is Dictionary:
				continue
			var zone: Dictionary = (raw_zone as Dictionary).duplicate(true)
			var parsed_parts: Array = []
			var raw_parts: Array = zone.get("parts", [])
			for raw_part in raw_parts:
				if not raw_part is Dictionary:
					continue
				var rings := _to_rings((raw_part as Dictionary).get("rings", []))
				if not rings.is_empty():
					parsed_parts.append(rings)
			if parsed_parts.is_empty():
				return _fail("у stress-зоны %s отсутствует polygon geometry" % str(zone.get("id", "?")))
			zone["_parsed_parts"] = parsed_parts
			parsed_zones.append(zone)

		var stored := province.duplicate(true)
		stored["_parsed_zones"] = parsed_zones
		_provinces_by_id[province_id] = stored

	for control in _controls:
		var pid := str(control.get("province_id", ""))
		if not _provinces_by_id.has(pid):
			return _fail("stress province %s отсутствует в final_subdivisions.json" % pid)

	_last_error = ""
	return true


func _select_current() -> void:
	if _current_index < 0 or _current_index >= _controls.size():
		return
	var province_id := get_current_province_id()
	var province: Dictionary = _provinces_by_id.get(province_id, {})
	_zones.clear()
	for raw_zone in province.get("_parsed_zones", []):
		if raw_zone is Dictionary:
			_zones.append(raw_zone)
	_selected_zone_id = ""
	_last_zoom = -1.0
	_update_panel()
	_focus_current()
	queue_redraw()

	var role := get_current_role()
	var role_label := str(ROLE_LABELS.get(role, role))
	_show_top_info(
		"H [%d/%d] • %s • %s • %d зон • H следующий"
		% [_current_index + 1, _controls.size(), _current_name(), role_label, _zones.size()]
	)


func _current_name() -> String:
	if _current_index < 0 or _current_index >= _controls.size():
		return "?"
	return str(_controls[_current_index].get("name", get_current_province_id()))


func _focus_current() -> void:
	if not is_instance_valid(_camera) or _zones.is_empty():
		return
	var have_bounds := false
	var min_x := 0.0
	var min_y := 0.0
	var max_x := 0.0
	var max_y := 0.0
	for zone in _zones:
		var bbox: Array = zone.get("bbox", [])
		if bbox.size() < 4:
			continue
		var x0 := float(bbox[0])
		var y0 := float(bbox[1])
		var x1 := float(bbox[2])
		var y1 := float(bbox[3])
		if not have_bounds:
			min_x = x0
			min_y = y0
			max_x = x1
			max_y = y1
			have_bounds = true
		else:
			min_x = minf(min_x, x0)
			min_y = minf(min_y, y0)
			max_x = maxf(max_x, x1)
			max_y = maxf(max_y, y1)
	if not have_bounds:
		return

	var width := maxf(0.01, max_x - min_x)
	var height := maxf(0.01, max_y - min_y)
	var center := Vector2((min_x + max_x) * 0.5, (min_y + max_y) * 0.5)
	var viewport_size := get_viewport_rect().size
	var fit_zoom := minf(viewport_size.x / (width * 1.55), viewport_size.y / (height * 1.55))
	if _camera.has_method("focus_at"):
		_camera.call("focus_at", center, fit_zoom)
	else:
		_camera.position = center
		_camera.zoom = Vector2.ONE * clampf(fit_zoom, 0.1, 8.0)


func _draw() -> void:
	if not visible or _zones.is_empty():
		return
	var zoom := maxf(0.0001, _camera.zoom.x if is_instance_valid(_camera) else 1.0)
	var shadow_width := 3.0 / zoom
	var border_width := 1.15 / zoom
	var selected_width := 3.5 / zoom

	for zone in _zones:
		var fill := _zone_color(str(zone.get("id", "")))
		for polygon_rings in zone.get("_parsed_parts", []):
			if polygon_rings.is_empty():
				continue
			var outer: PackedVector2Array = polygon_rings[0]
			var fill_ring := _without_duplicate_closing_point(outer)
			if fill_ring.size() >= 3:
				var triangles := Geometry2D.triangulate_polygon(fill_ring)
				if not triangles.is_empty():
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
	var hash_value := absi(zone_id.hash()) % 1000
	return Color.from_hsv(float(hash_value) / 1000.0, 0.45, 0.94, 0.40)


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


func _build_panel() -> void:
	if not is_instance_valid(_ui_layer):
		return
	_panel = PanelContainer.new()
	_panel.offset_left = 1320.0
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
	title.text = "Stage 6 — Stress Test"
	title.add_theme_color_override("font_color", Color(1.0, 0.86, 0.58, 1.0))
	title.add_theme_font_size_override("font_size", 19)
	content.add_child(title)

	_summary_label = Label.new()
	_summary_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	content.add_child(_summary_label)
	_update_panel()


func _update_panel() -> void:
	if not is_instance_valid(_summary_label):
		return
	if not _last_error.is_empty():
		_summary_label.text = "Ошибка: %s" % _last_error
		return
	if _current_index < 0 or _current_index >= _controls.size():
		_summary_label.text = "H — начать цикл 7 контрольных провинций"
		return
	var province: Dictionary = _provinces_by_id.get(get_current_province_id(), {})
	var validation: Dictionary = province.get("validation", {})
	var role := get_current_role()
	var coast_km := float(province.get("gameplay_coast_rule_km", 0.0))
	var coast_text := "нет" if coast_km <= 0.0 else "%.1f км" % coast_km
	var count_source := str(province.get("target_count_source", "?"))
	_summary_label.text = (
		"[%d/%d] %s\n"
		+ "Тип: %s\n"
		+ "Финальных зон: %d\n"
		+ "Источник количества: %s\n"
		+ "Игровой берег: %s\n"
		+ "Площадь: %.1f км²\n"
		+ "Проверка: %s\n\n"
		+ "H — следующая провинция\n"
		+ "ЛКМ — выбрать зону"
	) % [
		_current_index + 1,
		_controls.size(),
		_current_name(),
		str(ROLE_LABELS.get(role, role)),
		_zones.size(),
		count_source,
		coast_text,
		float(province.get("gameplay_area_km2", 0.0)),
		str(validation.get("status", "?")),
	]


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
	var stage6_bridge := _root_viewer.get_node_or_null("SubdivisionStage6InputBridge")
	if is_instance_valid(stage6_bridge) and stage6_bridge.has_method("hide_stage6"):
		stage6_bridge.call("hide_stage6")


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
