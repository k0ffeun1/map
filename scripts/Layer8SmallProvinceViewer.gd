extends Node2D
## Debug viewer for very small Layer-8 provinces that currently get one gameplay cell.
##
## F9  — toggle the layer.
## F10 — jump to the next smallest province (Shift+F10 = previous).
## LMB — inspect a highlighted province.
##
## Colors:
##   red    < 100 km²
##   orange 100–500 km²

const GEOMETRY_PATH := "res://assets/provinces.json"
const TARGETS_PATH := "res://assets/game_data/world_province_cell_targets.json"
const PIECE_SCRIPT := preload("res://scripts/Layer8SmallProvincePieceNode.gd")

const EXPECTED_LAYER8_PROVINCES := 4027
const EXPECTED_SMALL_ONE_CELL := 878
const EXPECTED_UNDER_100 := 444
const SMALL_LIMIT_KM2 := 500.0
const VERY_SMALL_LIMIT_KM2 := 100.0

var _active := false
var _last_error := ""
var _parts: Array[Dictionary] = []
var _under_100_count := 0
var _focus_index := -1

var _geometry_root: Node2D
var _ui_layer: CanvasLayer
var _panel: PanelContainer
var _summary_label: Label
var _selection_label: Label


func _ready() -> void:
	z_index = 242
	_ui_layer = get_node_or_null("../UI") as CanvasLayer
	_geometry_root = Node2D.new()
	_geometry_root.name = "Layer8SmallOneCellGeometry"
	add_child(_geometry_root)
	_build_panel()
	_load_data()
	if _last_error.is_empty():
		_build_geometry()
	set_active(false)
	set_process_input(true)


func _input(event: InputEvent) -> void:
	var key := event as InputEventKey
	if key != null and key.pressed and not key.echo:
		if key.physical_keycode == KEY_F9 or key.keycode == KEY_F9:
			if not _last_error.is_empty():
				_show_status("Layer 8 small provinces: %s" % _last_error)
			else:
				set_active(not _active)
			get_viewport().set_input_as_handled()
			return
		if key.physical_keycode == KEY_F10 or key.keycode == KEY_F10:
			if not _last_error.is_empty():
				_show_status("Layer 8 small provinces: %s" % _last_error)
			else:
				if not _active:
					set_active(true)
				_focus_relative(-1 if key.shift_pressed else 1)
			get_viewport().set_input_as_handled()
			return

	if not _active:
		return
	var mouse := event as InputEventMouseButton
	if mouse == null or not mouse.pressed or mouse.button_index != MOUSE_BUTTON_LEFT:
		return
	var hit := _hit_at_point(get_global_mouse_position())
	if not hit.is_empty():
		_show_selection(hit, false)
		get_viewport().set_input_as_handled()


func set_active(value: bool) -> void:
	_active = value and _last_error.is_empty()
	if is_instance_valid(_geometry_root):
		_geometry_root.visible = _active
	if is_instance_valid(_panel):
		_panel.visible = _active
	if _active:
		_hide_conflicting_debug_layers()
		_show_status("F9: маленькие 1-cell Layer 8 • красный <100 км² • оранжевый 100–500 км² • F10 следующий")
	else:
		_show_status("F9: показать маленькие одноклеточные провинции Layer 8")
	_update_summary()


func is_active() -> bool:
	return _active


func _load_data() -> void:
	var geometry := _load_json(GEOMETRY_PATH)
	var targets := _load_json(TARGETS_PATH)
	if geometry.is_empty() or targets.is_empty():
		return

	var target_records: Array = targets.get("provinces", [])
	if target_records.size() != EXPECTED_LAYER8_PROVINCES:
		_fail("ожидалось %d target-провинций, найдено %d" % [EXPECTED_LAYER8_PROVINCES, target_records.size()])
		return

	var same_name_counts: Dictionary = {}
	for raw in target_records:
		if not raw is Dictionary:
			continue
		var record: Dictionary = raw
		var key := _name_key(record)
		same_name_counts[key] = int(same_name_counts.get(key, 0)) + 1

	var small_by_legacy: Dictionary = {}
	for raw in target_records:
		if not raw is Dictionary:
			continue
		var record: Dictionary = raw
		if int(record.get("target_cell_count", 0)) != 1:
			continue
		var area := float(record.get("area_km2", 0.0))
		if area >= SMALL_LIMIT_KM2:
			continue
		var legacy_id := str(record.get("legacy_id", ""))
		if legacy_id.is_empty():
			continue
		var copy := record.duplicate(true)
		copy["repeated_country_name"] = int(same_name_counts.get(_name_key(record), 0)) > 1
		small_by_legacy[legacy_id] = copy

	_parts.clear()
	_under_100_count = 0
	for raw in geometry.get("cells", []):
		if not raw is Dictionary:
			continue
		var cell: Dictionary = raw
		var legacy_id := str(cell.get("id", ""))
		if not small_by_legacy.has(legacy_id):
			continue
		var rings := _to_rings(cell.get("rings", []))
		if rings.is_empty():
			continue
		var record: Dictionary = small_by_legacy[legacy_id]
		var area := float(record.get("area_km2", 0.0))
		if area < VERY_SMALL_LIMIT_KM2:
			_under_100_count += 1
		_parts.append({
			"province_id": str(record.get("province_id", "")),
			"legacy_id": legacy_id,
			"name": str(record.get("name", legacy_id)),
			"country_prefix": str(record.get("country_prefix", "")),
			"area_km2": area,
			"region_name": str(record.get("region_name", "")),
			"raw_area_count": float(record.get("raw_area_count", 0.0)),
			"target_cell_count": int(record.get("target_cell_count", 0)),
			"repeated_country_name": bool(record.get("repeated_country_name", false)),
			"rings": rings,
			"bbox": cell.get("bbox", []),
		})

	_parts.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return float(a.get("area_km2", 0.0)) < float(b.get("area_km2", 0.0)))
	if _parts.size() != EXPECTED_SMALL_ONE_CELL:
		_fail("ожидалось %d маленьких 1-cell полигонов, найдено %d" % [EXPECTED_SMALL_ONE_CELL, _parts.size()])
		return
	if _under_100_count != EXPECTED_UNDER_100:
		_fail("ожидалось %d полигонов <100 км², найдено %d" % [EXPECTED_UNDER_100, _under_100_count])
		return


func _build_geometry() -> void:
	for part in _parts:
		var area := float(part.get("area_km2", 0.0))
		var fill := Color(1.0, 0.07, 0.04, 0.50) if area < VERY_SMALL_LIMIT_KM2 else Color(1.0, 0.48, 0.04, 0.42)
		var outline := Color(1.0, 0.9, 0.78, 1.0) if area < VERY_SMALL_LIMIT_KM2 else Color(1.0, 0.72, 0.18, 1.0)
		var node: Node2D = PIECE_SCRIPT.new()
		_geometry_root.add_child(node)
		node.call("setup", part["rings"], fill, outline, 1.15)


func _focus_relative(delta: int) -> void:
	if _parts.is_empty():
		return
	if _focus_index < 0:
		_focus_index = 0 if delta >= 0 else _parts.size() - 1
	else:
		_focus_index = posmod(_focus_index + delta, _parts.size())
	var part: Dictionary = _parts[_focus_index]
	_focus_part(part)
	_show_selection(part, true)


func _focus_part(part: Dictionary) -> void:
	var bbox: Array = part.get("bbox", [])
	if bbox.size() < 4:
		return
	var min_x := float(bbox[0])
	var min_y := float(bbox[1])
	var max_x := float(bbox[2])
	var max_y := float(bbox[3])
	var width := maxf(max_x - min_x, 0.05)
	var height := maxf(max_y - min_y, 0.05)
	var camera := get_node_or_null("../Camera2D") as Camera2D
	if not is_instance_valid(camera):
		return
	camera.position = Vector2((min_x + max_x) * 0.5, (min_y + max_y) * 0.5)
	var viewport_size := get_viewport_rect().size
	var zx := viewport_size.x / (width * 5.0)
	var zy := viewport_size.y / (height * 5.0)
	var zoom_value := clampf(minf(zx, zy), 5.0, 120.0)
	camera.zoom = Vector2(zoom_value, zoom_value)


func _hit_at_point(point: Vector2) -> Dictionary:
	for index in range(_parts.size() - 1, -1, -1):
		var part: Dictionary = _parts[index]
		var bbox: Array = part.get("bbox", [])
		if bbox.size() >= 4 and (point.x < float(bbox[0]) or point.y < float(bbox[1]) or point.x > float(bbox[2]) or point.y > float(bbox[3])):
			continue
		if _point_in_rings(point, part["rings"]):
			return part
	return {}


func _show_selection(part: Dictionary, from_jump: bool) -> void:
	if not is_instance_valid(_selection_label):
		return
	var prefix := "F10 [%d/%d]" % [_focus_index + 1, _parts.size()] if from_jump else "ЛКМ"
	var repeated_text := "да — вероятный отдельный polygon-piece" if bool(part.get("repeated_country_name", false)) else "нет"
	_selection_label.text = "%s\n%s / %s\nПлощадь: %.1f км²\nКлеток: %d   raw: %.3f\nID: %s\nRegion: %s\nПовтор country+name: %s" % [
		prefix,
		str(part.get("country_prefix", "?")),
		str(part.get("name", "?")),
		float(part.get("area_km2", 0.0)),
		int(part.get("target_cell_count", 0)),
		float(part.get("raw_area_count", 0.0)),
		str(part.get("legacy_id", "?")),
		str(part.get("region_name", "?")),
		repeated_text,
	]
	_show_status("%s • %.1f км² • 1 клетка" % [str(part.get("name", "?")), float(part.get("area_km2", 0.0))])


func _update_summary() -> void:
	if not is_instance_valid(_summary_label):
		return
	_summary_label.text = "Подсвечено: %d\n<100 км²: %d (красные)\n100–500 км²: %d (оранжевые)" % [
		_parts.size(),
		_under_100_count,
		_parts.size() - _under_100_count,
	]
	if is_instance_valid(_selection_label) and _selection_label.text.is_empty():
		_selection_label.text = "ЛКМ — данные провинции\nF10 — перейти к самой маленькой / следующей\nShift+F10 — предыдущая"


func _hide_conflicting_debug_layers() -> void:
	var root := get_parent()
	if not is_instance_valid(root):
		return
	var safe_viewer := root.get_node_or_null("WorldAdmin1SafeViewer")
	if is_instance_valid(safe_viewer) and safe_viewer.has_method("set_active"):
		safe_viewer.call("set_active", false)
	var regions := root.get_node_or_null("WorldRegionsDraftViewer")
	if is_instance_valid(regions) and regions.has_method("set_active") and bool(regions.call("is_active")):
		regions.call("set_active", false)


func _point_in_rings(point: Vector2, rings: Array) -> bool:
	if rings.is_empty() or not Geometry2D.is_point_in_polygon(point, rings[0]):
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


func _name_key(record: Dictionary) -> String:
	return "%s|%s" % [str(record.get("country_prefix", "")), str(record.get("name", "")).to_lower()]


func _load_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		_fail("не найден %s" % path)
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if typeof(parsed) != TYPE_DICTIONARY:
		_fail("неверный JSON %s" % path)
		return {}
	return parsed


func _fail(message: String) -> void:
	if _last_error.is_empty():
		_last_error = message
	push_error("Layer8SmallProvinceViewer: %s" % message)


func _show_status(text: String) -> void:
	var label := get_node_or_null("../UI/StatusLabel") as Label
	if is_instance_valid(label):
		label.text = text


func _build_panel() -> void:
	if not is_instance_valid(_ui_layer):
		return
	_panel = PanelContainer.new()
	_panel.offset_left = 1190.0
	_panel.offset_top = 70.0
	_panel.offset_right = 1885.0
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
	box.add_theme_constant_override("separation", 7)
	margin.add_child(box)

	var title := Label.new()
	title.text = "Layer 8 — маленькие 1-cell [F9]"
	title.add_theme_font_size_override("font_size", 20)
	title.add_theme_color_override("font_color", Color(1.0, 0.64, 0.18, 1.0))
	box.add_child(title)

	var help := Label.new()
	help.text = "F9 — показать/скрыть   F10 — следующая маленькая\nShift+F10 — предыдущая   ЛКМ — подробности"
	box.add_child(help)

	_summary_label = Label.new()
	box.add_child(_summary_label)

	_selection_label = Label.new()
	_selection_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(_selection_label)
