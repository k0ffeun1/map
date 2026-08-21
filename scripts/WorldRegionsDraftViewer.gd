extends Node2D
## Мировой черновой слой историко-географических регионов.
##
## Источник геометрии: assets/regions_world_draft.json.
## Каждый регион — dissolve уже утверждённых провинций старого слоя 8;
## границы провинций никогда не режутся и не двигаются этим viewer-ом.
##
## I переключает слой. Событие перехватывается в _input(), поэтому старый
## Iberia-only обработчик I в TileMapViewer не получает это нажатие.

const DATA_PATH := "res://assets/regions_world_draft.json"
const ASSIGNMENTS_PATH := "res://assets/game_data/world_region_assignments_draft.json"
const EXPECTED_FORMAT := "world_regions_draft/v1"

const OUTLINE_SHADOW := Color(0.015, 0.02, 0.028, 0.88)
const OUTLINE_COLOR := Color(0.93, 0.94, 0.90, 0.84)
const SELECT_COLOR := Color(1.0, 0.80, 0.24, 1.0)

var _camera: Camera2D
var _ui_layer: CanvasLayer
var _root_viewer: Node
var _panel: PanelContainer
var _summary: Label

var _parts: Array[Dictionary] = []
var _province_count_by_region: Dictionary = {}
var _region_name_by_id: Dictionary = {}
var _region_count := 0
var _province_count := 0
var _piece_count := 0
var _selected_region_id := ""
var _last_error := ""
var _last_zoom := -1.0


func _ready() -> void:
	_camera = get_node_or_null("../Camera2D") as Camera2D
	_ui_layer = get_node_or_null("../UI") as CanvasLayer
	_root_viewer = get_parent()
	z_index = 210
	visible = false
	_load_data()
	_build_panel()
	set_process(true)
	set_process_input(true)


func _input(event: InputEvent) -> void:
	var key := event as InputEventKey
	if key != null and key.pressed and not key.echo and key.physical_keycode == KEY_I:
		if _last_error.is_empty():
			set_active(not visible)
		else:
			_show_top_info("Мировые регионы: %s" % _last_error)
		get_viewport().set_input_as_handled()
		return

	if not visible:
		return
	var mouse := event as InputEventMouseButton
	if mouse == null or not mouse.pressed or mouse.button_index != MOUSE_BUTTON_LEFT:
		return
	var hit := _part_at_point(get_global_mouse_position())
	if hit.is_empty():
		return
	_selected_region_id = str(hit.get("region_id", ""))
	queue_redraw()
	var region_name := str(_region_name_by_id.get(_selected_region_id, hit.get("name", "?")))
	var provinces := int(_province_count_by_region.get(_selected_region_id, 0))
	_show_top_info("Регион • %s • %d провинций • %s" % [region_name, provinces, _selected_region_id])
	get_viewport().set_input_as_handled()


func set_active(active: bool) -> void:
	if active and not _last_error.is_empty():
		return
	visible = active
	if is_instance_valid(_panel):
		_panel.visible = active
	if active:
		_hide_other_subdivision_debug()
		_last_zoom = -1.0
		queue_redraw()
		_show_top_info("I: мировые регионы DRAFT • %d регионов • %d провинций • ЛКМ выбрать" % [_region_count, _province_count])
	else:
		_show_top_info("Мировые регионы скрыты")


func is_active() -> bool:
	return visible


func _process(_delta: float) -> void:
	if not visible:
		return
	var zoom := maxf(0.0001, _camera.zoom.x if is_instance_valid(_camera) else 1.0)
	if absf(zoom - _last_zoom) > 0.0001:
		_last_zoom = zoom
		queue_redraw()


func _load_data() -> bool:
	if not FileAccess.file_exists(DATA_PATH):
		return _fail("не найден %s — сделай git pull" % DATA_PATH)
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(DATA_PATH))
	if typeof(parsed) != TYPE_DICTIONARY:
		return _fail("regions_world_draft.json имеет неверный JSON")
	var data: Dictionary = parsed
	if str(data.get("format", "")) != EXPECTED_FORMAT:
		return _fail("ожидался формат %s" % EXPECTED_FORMAT)

	_parts.clear()
	_region_name_by_id.clear()
	_region_count = int(data.get("region_count", 0))
	_province_count = int(data.get("province_count", 0))
	_piece_count = int(data.get("polygon_piece_count", 0))
	for raw in data.get("cells", []):
		if not raw is Dictionary:
			continue
		var cell: Dictionary = raw
		var region_id := str(cell.get("region_id", ""))
		var name := str(cell.get("name", region_id))
		var rings := _to_rings(cell.get("rings", []))
		if region_id.is_empty() or rings.is_empty():
			continue
		var part: Dictionary = {
			"id": str(cell.get("id", "")),
			"region_id": region_id,
			"name": name,
			"bbox": cell.get("bbox", []),
			"rings": rings,
		}
		_parts.append(part)
		_region_name_by_id[region_id] = name

	if FileAccess.file_exists(ASSIGNMENTS_PATH):
		var ap: Variant = JSON.parse_string(FileAccess.get_file_as_string(ASSIGNMENTS_PATH))
		if typeof(ap) == TYPE_DICTIONARY:
			for raw_assignment in (ap as Dictionary).get("assignments", []):
				if not raw_assignment is Dictionary:
					continue
				var rid := str((raw_assignment as Dictionary).get("region_id", ""))
				if not rid.is_empty():
					_province_count_by_region[rid] = int(_province_count_by_region.get(rid, 0)) + 1

	if _parts.is_empty():
		return _fail("мировой слой не содержит polygon parts")
	_last_error = ""
	return true


func _draw() -> void:
	if not visible or _parts.is_empty():
		return
	var zoom := maxf(0.0001, _camera.zoom.x if is_instance_valid(_camera) else 1.0)
	var shadow_width := 2.3 / zoom
	var border_width := 0.82 / zoom
	var selected_width := 3.0 / zoom

	# Заливка сначала, затем единым проходом границы. У сложных полигонов,
	# которые Godot не может триангулировать, оставляем точный контур вместо
	# renderer warning — это только debug-view, исходная геометрия не меняется.
	for part in _parts:
		var outer: PackedVector2Array = part["rings"][0]
		var fill_ring := _without_duplicate_closing_point(outer)
		if fill_ring.size() < 3:
			continue
		var triangles := Geometry2D.triangulate_polygon(fill_ring)
		if not triangles.is_empty():
			draw_colored_polygon(fill_ring, _region_color(str(part.get("region_id", ""))))

	for part in _parts:
		for ring in part["rings"]:
			var closed := _closed(ring)
			if closed.size() >= 2:
				draw_polyline(closed, OUTLINE_SHADOW, shadow_width, true)
	for part in _parts:
		for ring in part["rings"]:
			var closed := _closed(ring)
			if closed.size() >= 2:
				draw_polyline(closed, OUTLINE_COLOR, border_width, true)

	if not _selected_region_id.is_empty():
		for part in _parts:
			if str(part.get("region_id", "")) != _selected_region_id:
				continue
			for ring in part["rings"]:
				var closed := _closed(ring)
				if closed.size() >= 2:
					draw_polyline(closed, SELECT_COLOR, selected_width, true)


func _region_color(region_id: String) -> Color:
	var h := absi(region_id.hash()) % 1000
	return Color.from_hsv(float(h) / 1000.0, 0.46, 0.90, 0.30)


func _part_at_point(point: Vector2) -> Dictionary:
	# Reverse gives smaller/later multipart pieces a chance before a giant
	# polygon bbox. Exact point-in-polygon still decides the result.
	for index in range(_parts.size() - 1, -1, -1):
		var part: Dictionary = _parts[index]
		var bbox: Array = part.get("bbox", [])
		if bbox.size() >= 4:
			if point.x < float(bbox[0]) or point.y < float(bbox[1]) or point.x > float(bbox[2]) or point.y > float(bbox[3]):
				continue
		var rings: Array = part["rings"]
		if not rings.is_empty() and _point_in_rings(point, rings):
			return part
	return {}


func _point_in_rings(point: Vector2, rings: Array) -> bool:
	if rings.is_empty():
		return false
	if not Geometry2D.is_point_in_polygon(point, rings[0]):
		return false
	for i in range(1, rings.size()):
		if Geometry2D.is_point_in_polygon(point, rings[i]):
			return false
	return true


func _to_rings(raw_rings: Variant) -> Array:
	var out: Array = []
	if not raw_rings is Array:
		return out
	for raw_ring in raw_rings:
		if not raw_ring is Array:
			continue
		var ring := PackedVector2Array()
		for raw_point in raw_ring:
			if raw_point is Array and raw_point.size() >= 2:
				ring.append(Vector2(float(raw_point[0]), float(raw_point[1])))
		if ring.size() >= 3:
			out.append(ring)
	return out


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


func _hide_other_subdivision_debug() -> void:
	if not is_instance_valid(_root_viewer):
		return
	for node_name in ["SubdivisionStage4InputBridge", "SubdivisionStage5InputBridge", "SubdivisionStage6InputBridge"]:
		var node := _root_viewer.get_node_or_null(node_name)
		if not is_instance_valid(node):
			continue
		if node.has_method("hide_stage4"):
			node.call("hide_stage4")
		if node.has_method("hide_stage5"):
			node.call("hide_stage5")
		if node.has_method("hide_stage6"):
			node.call("hide_stage6")


func _build_panel() -> void:
	if not is_instance_valid(_ui_layer):
		return
	_panel = PanelContainer.new()
	_panel.offset_left = 1280.0
	_panel.offset_top = 90.0
	_panel.offset_right = 1896.0
	_panel.offset_bottom = 390.0
	_panel.visible = false
	_ui_layer.add_child(_panel)

	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 14)
	margin.add_theme_constant_override("margin_top", 12)
	margin.add_theme_constant_override("margin_right", 14)
	margin.add_theme_constant_override("margin_bottom", 12)
	_panel.add_child(margin)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 6)
	margin.add_child(box)

	var title := Label.new()
	title.text = "Мировые регионы — DRAFT"
	title.add_theme_color_override("font_color", Color(1.0, 0.84, 0.52, 1.0))
	title.add_theme_font_size_override("font_size", 20)
	box.add_child(title)

	var note := Label.new()
	note.text = "Каждый регион собран ТОЛЬКО из целых провинций слоя 8. Иберия использует ручную привязку. Остальной мир — первый массовый кандидат по 273 регионам таблицы; сомнительные места ещё будут проверяться."
	note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(note)

	_summary = Label.new()
	_summary.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	if _last_error.is_empty():
		_summary.text = "• Провинций: %d\n• Регионов в draft: %d\n• Полигональных частей: %d\n• I — скрыть/показать\n• ЛКМ — информация о регионе" % [_province_count, _region_count, _piece_count]
	else:
		_summary.text = "Ошибка: %s" % _last_error
	box.add_child(_summary)


func _show_top_info(message: String) -> void:
	if is_instance_valid(_root_viewer) and _root_viewer.has_method("_show_top_info"):
		_root_viewer.call("_show_top_info", message)
	else:
		print(message)


func _fail(message: String) -> bool:
	_last_error = message
	push_warning("WorldRegionsDraftViewer: %s" % message)
	return false
