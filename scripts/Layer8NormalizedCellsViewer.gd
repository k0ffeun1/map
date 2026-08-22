extends Node2D
## Visual inspection of the first REAL cells generated for normalized gameplay parents.
##
## F6 — toggle generated-cell control preview.
## F5 — next control province (Shift+F5 = previous).
## LMB — select a generated cell.

const DATA_PATH := "res://assets/land_cells_normalized/control_preview.json"
const PIECE_SCRIPT := preload("res://scripts/Layer8MergeResultPieceNode.gd")

const PALETTE := [
	Color(0.18, 0.78, 1.00, 0.46),
	Color(0.30, 1.00, 0.48, 0.44),
	Color(1.00, 0.70, 0.18, 0.46),
	Color(0.84, 0.38, 1.00, 0.44),
	Color(1.00, 0.34, 0.38, 0.43),
	Color(0.20, 0.94, 0.82, 0.45),
	Color(0.92, 0.90, 0.22, 0.43),
	Color(0.58, 0.66, 1.00, 0.45),
]
const OUTLINE := Color(0.96, 0.98, 1.0, 0.98)

var _active := false
var _last_error := ""
var _focus_index := -1
var _selected_cell_id := ""

var _parents: Array[Dictionary] = []
var _parent_by_id: Dictionary = {}
var _cells: Array[Dictionary] = []
var _cell_by_id: Dictionary = {}
var _nodes_by_cell: Dictionary = {}

var _geometry_root: Node2D
var _ui_layer: CanvasLayer
var _panel: PanelContainer
var _summary_label: Label
var _selection_label: Label


func _ready() -> void:
	z_index = 246
	_ui_layer = get_node_or_null("../UI") as CanvasLayer
	_geometry_root = Node2D.new()
	_geometry_root.name = "Layer8NormalizedCellsGeometry"
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
		if key.physical_keycode == KEY_F6 or key.keycode == KEY_F6:
			if _last_error.is_empty():
				set_active(not _active)
			else:
				_show_status("Normalized cells: %s" % _last_error)
			get_viewport().set_input_as_handled()
			return
		if key.physical_keycode == KEY_F5 or key.keycode == KEY_F5:
			if _last_error.is_empty():
				if not _active:
					set_active(true)
				_focus_relative(-1 if key.shift_pressed else 1)
			else:
				_show_status("Normalized cells: %s" % _last_error)
			get_viewport().set_input_as_handled()
			return

	if not _active:
		return
	var mouse := event as InputEventMouseButton
	if mouse == null or not mouse.pressed or mouse.button_index != MOUSE_BUTTON_LEFT:
		return
	var hit := _hit_at_point(get_global_mouse_position())
	if not hit.is_empty():
		_select_cell(str(hit.get("id", "")))
		get_viewport().set_input_as_handled()


func set_active(value: bool) -> void:
	_active = value and _last_error.is_empty()
	if is_instance_valid(_geometry_root):
		_geometry_root.visible = _active
	if is_instance_valid(_panel):
		_panel.visible = _active
	if _active:
		_hide_conflicting_debug_layers()
		_show_status("F6: реальные клетки • F5: следующая контрольная провинция • ЛКМ: клетка")
	else:
		_clear_selection()
		_show_status("F6: показать реальные нормализованные клетки")
	_update_summary()


func is_active() -> bool:
	return _active


func _load_data() -> void:
	if not FileAccess.file_exists(DATA_PATH):
		_fail("не найден %s" % DATA_PATH)
		return
	var raw: Variant = JSON.parse_string(FileAccess.get_file_as_string(DATA_PATH))
	if typeof(raw) != TYPE_DICTIONARY:
		_fail("неверный JSON control_preview")
		return
	var doc: Dictionary = raw
	if str(doc.get("format", "")) != "layer8_normalized_land_cells/v1":
		_fail("ожидался layer8_normalized_land_cells/v1")
		return

	_parents.clear()
	_parent_by_id.clear()
	_cells.clear()
	_cell_by_id.clear()

	for raw_parent in doc.get("provinces", []):
		if not raw_parent is Dictionary:
			continue
		var parent: Dictionary = raw_parent.duplicate(true)
		var parent_id := str(parent.get("gameplay_parent_id", ""))
		if parent_id.is_empty():
			continue
		var bbox: Array = []
		for raw_cell in parent.get("cells", []):
			if not raw_cell is Dictionary:
				continue
			var cell: Dictionary = raw_cell.duplicate(true)
			var cell_id := str(cell.get("id", ""))
			if cell_id.is_empty():
				continue
			cell["display_parent_name"] = str(parent.get("display_name", parent_id))
			cell["parent_validation_status"] = str(parent.get("validation", {}).get("status", ""))
			cell["capital_anchor_source"] = str(parent.get("capital_anchor", {}).get("source", ""))
			cell["target_cell_count"] = int(parent.get("target_cell_count", 0))
			cell["parent_area_km2"] = float(parent.get("normalized_area_km2", 0.0))
			_cells.append(cell)
			_cell_by_id[cell_id] = cell
			bbox = _merge_bbox(bbox, cell.get("bbox", []))
		parent["viewer_bbox"] = bbox
		_parents.append(parent)
		_parent_by_id[parent_id] = parent

	_parents.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		return str(a.get("display_name", "")).naturalnocasecmp_to(str(b.get("display_name", ""))) < 0
	)
	if _parents.is_empty() or _cells.is_empty():
		_fail("control preview пуст")


func _build_geometry() -> void:
	_nodes_by_cell.clear()
	for cell in _cells:
		var cell_id := str(cell.get("id", ""))
		var local_index := int(cell.get("local_index", 1))
		var fill: Color = PALETTE[(local_index - 1) % PALETTE.size()]
		var nodes: Array = []
		for raw_part in cell.get("parts", []):
			if not raw_part is Dictionary:
				continue
			var rings := _to_rings(raw_part.get("rings", []))
			if rings.is_empty():
				continue
			var node: Node2D = PIECE_SCRIPT.new()
			_geometry_root.add_child(node)
			node.call("setup", rings, fill, OUTLINE, 1.2)
			nodes.append(node)
		_nodes_by_cell[cell_id] = nodes


func _focus_relative(delta: int) -> void:
	if _parents.is_empty():
		return
	if _focus_index < 0:
		_focus_index = 0 if delta >= 0 else _parents.size() - 1
	else:
		_focus_index = posmod(_focus_index + delta, _parents.size())
	var parent: Dictionary = _parents[_focus_index]
	_focus_bbox(parent.get("viewer_bbox", []))
	_clear_selection()
	_show_parent(parent)


func _focus_bbox(bbox: Array) -> void:
	if bbox.size() < 4:
		return
	var camera := get_node_or_null("../Camera2D") as Camera2D
	if not is_instance_valid(camera):
		return
	var min_x := float(bbox[0])
	var min_y := float(bbox[1])
	var max_x := float(bbox[2])
	var max_y := float(bbox[3])
	var width := maxf(max_x - min_x, 0.08)
	var height := maxf(max_y - min_y, 0.08)
	camera.position = Vector2((min_x + max_x) * 0.5, (min_y + max_y) * 0.5)
	var viewport_size := get_viewport_rect().size
	var zoom_value := clampf(minf(viewport_size.x / (width * 3.3), viewport_size.y / (height * 3.3)), 2.2, 120.0)
	camera.zoom = Vector2(zoom_value, zoom_value)


func _select_cell(cell_id: String) -> void:
	if cell_id.is_empty() or not _cell_by_id.has(cell_id):
		return
	_clear_selection()
	_selected_cell_id = cell_id
	for raw_node in _nodes_by_cell.get(cell_id, []):
		var node := raw_node as Node2D
		if is_instance_valid(node) and node.has_method("set_selected"):
			node.call("set_selected", true)
	var cell: Dictionary = _cell_by_id[cell_id]
	_show_cell(cell)


func _clear_selection() -> void:
	if not _selected_cell_id.is_empty():
		for raw_node in _nodes_by_cell.get(_selected_cell_id, []):
			var node := raw_node as Node2D
			if is_instance_valid(node) and node.has_method("set_selected"):
				node.call("set_selected", false)
	_selected_cell_id = ""


func _show_parent(parent: Dictionary) -> void:
	if not is_instance_valid(_selection_label):
		return
	_selection_label.text = "F5 [%d/%d]\nПровинция: %s\nКлеток: %d\nПлощадь: %.1f км²\nКомпонентов суши: %d\nСпутников прикреплено: %d\nAnchor: %s\nValidation: %s\nID: %s" % [
		_focus_index + 1,
		_parents.size(),
		str(parent.get("display_name", "?")),
		int(parent.get("target_cell_count", 0)),
		float(parent.get("normalized_area_km2", 0.0)),
		int(parent.get("geometry_component_count", 0)),
		int(parent.get("attached_satellite_component_count", 0)),
		str(parent.get("capital_anchor", {}).get("source", "?")),
		str(parent.get("validation", {}).get("status", "?")),
		str(parent.get("gameplay_parent_id", "?")),
	]
	_show_status("%s • %d клеток • %.1f км²" % [str(parent.get("display_name", "?")), int(parent.get("target_cell_count", 0)), float(parent.get("normalized_area_km2", 0.0))])


func _show_cell(cell: Dictionary) -> void:
	if not is_instance_valid(_selection_label):
		return
	_selection_label.text = "КЛЕТКА\nПровинция: %s\nНомер: %d / %d\nРоль: %s\nПлощадь клетки: %.1f км²\nПлощадь провинции: %.1f км²\nMultipart: %s\nСоседей: %d\nAnchor source: %s\nValidation: %s\nID: %s" % [
		str(cell.get("display_parent_name", "?")),
		int(cell.get("local_index", 0)),
		int(cell.get("target_cell_count", 0)),
		str(cell.get("cell_role", "territory")),
		float(cell.get("area_km2", 0.0)),
		float(cell.get("parent_area_km2", 0.0)),
		str(bool(cell.get("multipart", false))),
		Array(cell.get("neighbor_land_cell_ids", [])).size(),
		str(cell.get("capital_anchor_source", "?")),
		str(cell.get("parent_validation_status", "?")),
		str(cell.get("id", "?")),
	]
	_show_status("%s • клетка %d • %.1f км²" % [str(cell.get("display_parent_name", "?")), int(cell.get("local_index", 0)), float(cell.get("area_km2", 0.0))])


func _hit_at_point(point: Vector2) -> Dictionary:
	for index in range(_cells.size() - 1, -1, -1):
		var cell: Dictionary = _cells[index]
		var bbox: Array = cell.get("bbox", [])
		if bbox.size() >= 4 and (point.x < float(bbox[0]) or point.y < float(bbox[1]) or point.x > float(bbox[2]) or point.y > float(bbox[3])):
			continue
		for raw_part in cell.get("parts", []):
			if not raw_part is Dictionary:
				continue
			var rings := _to_rings(raw_part.get("rings", []))
			if _point_in_rings(point, rings):
				return cell
	return {}


func _update_summary() -> void:
	if not is_instance_valid(_summary_label):
		return
	var pass_count := 0
	var warning_count := 0
	for parent in _parents:
		var status := str(parent.get("validation", {}).get("status", ""))
		if status == "PASS":
			pass_count += 1
		elif status == "ACCEPTED_WITH_WARNINGS":
			warning_count += 1
	_summary_label.text = "Контрольных провинций: %d\nСгенерировано клеток: %d\nPASS: %d\nAccepted with warnings: %d\n\nF5 — следующая провинция\nShift+F5 — предыдущая\nЛКМ — клетка" % [
		_parents.size(), _cells.size(), pass_count, warning_count
	]
	if is_instance_valid(_selection_label) and _selection_label.text.is_empty():
		_selection_label.text = "Это уже реальные полигоны нового world-wide генератора.\nСначала проверяем их визуально, затем тем же алгоритмом строятся все 12 902 клетки."


func _hide_conflicting_debug_layers() -> void:
	var root := get_parent()
	if not is_instance_valid(root):
		return
	for node_name in ["Layer8SmallProvinceViewer", "Layer8MergeResultViewer", "WorldAdmin1SafeViewer", "WorldRegionsDraftViewer", "SloveniaAdmin1ComparisonViewer"]:
		var viewer := root.get_node_or_null(node_name)
		if is_instance_valid(viewer) and viewer.has_method("set_active"):
			viewer.call("set_active", false)


func _point_in_rings(point: Vector2, rings: Array) -> bool:
	if rings.is_empty() or not Geometry2D.is_point_in_polygon(point, rings[0]):
		return false
	for i in range(1, rings.size()):
		if Geometry2D.is_point_in_polygon(point, rings[i]):
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


func _merge_bbox(current: Array, raw_bbox: Variant) -> Array:
	if not raw_bbox is Array or raw_bbox.size() < 4:
		return current
	var bbox := [float(raw_bbox[0]), float(raw_bbox[1]), float(raw_bbox[2]), float(raw_bbox[3])]
	if current.size() < 4:
		return bbox
	return [
		minf(float(current[0]), bbox[0]),
		minf(float(current[1]), bbox[1]),
		maxf(float(current[2]), bbox[2]),
		maxf(float(current[3]), bbox[3]),
	]


func _show_status(text: String) -> void:
	var label := get_node_or_null("../UI/StatusLabel") as Label
	if is_instance_valid(label):
		label.text = text


func _fail(message: String) -> void:
	if _last_error.is_empty():
		_last_error = message
	push_error("Layer8NormalizedCellsViewer: %s" % message)


func _build_panel() -> void:
	if not is_instance_valid(_ui_layer):
		return
	_panel = PanelContainer.new()
	_panel.offset_left = 1110.0
	_panel.offset_top = 55.0
	_panel.offset_right = 1890.0
	_panel.offset_bottom = 560.0
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
	title.text = "Новые внутренние клетки [F6]"
	title.add_theme_font_size_override("font_size", 20)
	title.add_theme_color_override("font_color", Color(0.70, 0.96, 1.0, 1.0))
	box.add_child(title)

	_summary_label = Label.new()
	_summary_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(_summary_label)

	var separator := HSeparator.new()
	box.add_child(separator)

	_selection_label = Label.new()
	_selection_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_selection_label.custom_minimum_size = Vector2(730.0, 210.0)
	box.add_child(_selection_label)
