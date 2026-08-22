extends Node2D
## Visual inspection of the additive Britain + North Atlantic regional build.
##
## N         cycles OFF -> gameplay provinces -> cells -> overlay -> OFF.
## Shift+N   focuses the whole Britain/North Atlantic test area.
## LMB       inspects a gameplay province/cell under the cursor.
##
## This viewer never modifies old layers. It only reads the dedicated regional
## outputs built from SAFE logical Admin-1 geometry and uses the same visual
## language as the India reference layers.

const PROVINCES_PATH := "res://assets/game_data/britain_north_atlantic_gameplay_provinces.json"
const CELLS_PATH := "res://assets/subdivision_stage6/britain_north_atlantic_subdivisions.json"
const EXPECTED_PROVINCES := 60
const EXPECTED_CELLS := 155

const MODE_OFF := 0
const MODE_PROVINCES := 1
const MODE_CELLS := 2
const MODE_OVERLAY := 3

const GOLDEN_HUE_STEP := 0.61803398875
const PROVINCE_FILL_SATURATION := 0.22
const PROVINCE_FILL_VALUE := 0.78
const PROVINCE_BORDER_COLOR := Color(0.6117647, 0.6117647, 0.6117647, 1.0)
const PROVINCE_BORDER_SCREEN_PX := 1.2
const CELL_BORDER_COLOR := Color(0.41960785, 0.41960785, 0.41960785, 1.0)
const CELL_BORDER_SCREEN_PX := 0.64
const SELECT_FILL := Color(1.0, 0.77, 0.30, 0.30)
const SELECT_OUTLINE := Color(1.0, 0.92, 0.46, 1.0)
const SELECT_OUTLINE_SCREEN_PX := 2.0

var _mode := MODE_OFF
var _load_error := ""
var _camera: Camera2D
var _ui: CanvasLayer
var _panel: PanelContainer
var _summary_label: Label
var _selection_label: Label
var _provinces: Array[Dictionary] = []
var _cells: Array[Dictionary] = []
var _province_by_id: Dictionary = {}
var _selected_id := ""
var _world_bbox: Array = []
var _last_zoom := -1.0


func _ready() -> void:
	_camera = get_node_or_null("../Camera2D") as Camera2D
	_ui = get_node_or_null("../UI") as CanvasLayer
	z_index = 270
	_load_data()
	_build_panel()
	visible = false
	set_process(true)
	set_process_input(true)


func _process(_delta: float) -> void:
	if _mode == MODE_OFF:
		return
	var zoom := maxf(0.0001, _camera.zoom.x if is_instance_valid(_camera) else 1.0)
	if absf(zoom - _last_zoom) > 0.0001:
		_last_zoom = zoom
		queue_redraw()


func _input(event: InputEvent) -> void:
	var key := event as InputEventKey
	if key != null and key.pressed and not key.echo and (key.physical_keycode == KEY_N or key.keycode == KEY_N):
		if not _load_error.is_empty():
			_show_status("Britain/North Atlantic: %s" % _load_error)
		elif key.shift_pressed:
			if _mode == MODE_OFF:
				_set_mode(MODE_PROVINCES)
			_focus_all()
		else:
			_set_mode((_mode + 1) % 4)
		get_viewport().set_input_as_handled()
		return

	if _mode == MODE_OFF:
		return
	var mouse := event as InputEventMouseButton
	if mouse == null or not mouse.pressed or mouse.button_index != MOUSE_BUTTON_LEFT:
		return
	var point := get_global_mouse_position()
	var hit := _hit(point)
	if not hit.is_empty():
		_selected_id = str(hit.get("id", ""))
		_show_selection(hit)
		queue_redraw()
		get_viewport().set_input_as_handled()


func _set_mode(value: int) -> void:
	_mode = clampi(value, MODE_OFF, MODE_OVERLAY)
	visible = _mode != MODE_OFF and _load_error.is_empty()
	if is_instance_valid(_panel):
		_panel.visible = visible
	_selected_id = ""
	_last_zoom = -1.0
	queue_redraw()
	if _mode == MODE_OFF:
		_show_status("N: Британия + Северная Атлантика")
	elif _mode == MODE_PROVINCES:
		_show_status("N: Британия/Сев. Атлантика — игровые провинции • ЛКМ детали • Shift+N обзор")
	elif _mode == MODE_CELLS:
		_show_status("N: Британия/Сев. Атлантика — клетки • ЛКМ детали • Shift+N обзор")
	else:
		_show_status("N: Британия/Сев. Атлантика — провинции + клетки • ЛКМ детали • Shift+N обзор")
	_update_summary()


func _load_data() -> void:
	var pdoc := _load_json(PROVINCES_PATH)
	var cdoc := _load_json(CELLS_PATH)
	if pdoc.is_empty() or cdoc.is_empty():
		return
	if str(pdoc.get("format", "")) != "britain_north_atlantic_gameplay_provinces/v1":
		_fail("неверный формат gameplay provinces")
		return
	if str(cdoc.get("format", "")) != "britain_north_atlantic_subdivisions/v1":
		_fail("неверный формат subdivisions")
		return
	if int(pdoc.get("gameplay_province_count", 0)) != EXPECTED_PROVINCES:
		_fail("ожидалось %d провинций" % EXPECTED_PROVINCES)
		return
	if int(cdoc.get("cell_count", 0)) != EXPECTED_CELLS:
		_fail("ожидалось %d клеток" % EXPECTED_CELLS)
		return

	_provinces.clear()
	_cells.clear()
	_province_by_id.clear()
	_world_bbox.clear()
	for raw in pdoc.get("provinces", []):
		if not raw is Dictionary:
			continue
		var item: Dictionary = raw.duplicate(true)
		item["viewer_parts"] = _to_parts(item.get("parts", []))
		if (item["viewer_parts"] as Array).is_empty():
			continue
		_provinces.append(item)
		_province_by_id[str(item.get("id", ""))] = item
		_world_bbox = _merge_bbox(_world_bbox, item.get("bbox", []))

	for raw_parent in cdoc.get("provinces", []):
		if not raw_parent is Dictionary:
			continue
		var parent: Dictionary = raw_parent
		var parent_id := str(parent.get("id", ""))
		for raw_cell in parent.get("cells", []):
			if not raw_cell is Dictionary:
				continue
			var cell: Dictionary = raw_cell.duplicate(true)
			cell["parent_id"] = parent_id
			cell["parent_name"] = str(parent.get("name", parent_id))
			cell["territory"] = str(parent.get("territory", ""))
			cell["viewer_parts"] = _to_parts(cell.get("parts", []))
			if not (cell["viewer_parts"] as Array).is_empty():
				_cells.append(cell)

	if _provinces.size() != EXPECTED_PROVINCES or _cells.size() != EXPECTED_CELLS:
		_fail("drawable count mismatch: %d провинций, %d клеток" % [_provinces.size(), _cells.size()])


func _draw() -> void:
	if _mode == MODE_OFF or not _load_error.is_empty():
		return
	var zoom := maxf(0.0001, _camera.zoom.x if is_instance_valid(_camera) else 1.0)
	var province_width := PROVINCE_BORDER_SCREEN_PX / zoom
	var cell_width := CELL_BORDER_SCREEN_PX / zoom
	var selected_width := SELECT_OUTLINE_SCREEN_PX / zoom

	if _mode == MODE_PROVINCES or _mode == MODE_OVERLAY:
		for i in range(_provinces.size()):
			var province := _provinces[i]
			var color := _province_color(i)
			_draw_item(province, color, PROVINCE_BORDER_COLOR, province_width, str(province.get("id", "")) == _selected_id, selected_width)

	if _mode == MODE_CELLS or _mode == MODE_OVERLAY:
		for cell in _cells:
			var selected := str(cell.get("id", "")) == _selected_id or str(cell.get("parent_id", "")) == _selected_id
			_draw_item(cell, Color(0, 0, 0, 0), CELL_BORDER_COLOR, cell_width, selected, selected_width)


func _draw_item(item: Dictionary, fill: Color, border: Color, width: float, selected: bool, selected_width: float) -> void:
	for part_raw in item.get("viewer_parts", []):
		if not part_raw is Array:
			continue
		var rings: Array = part_raw
		if rings.is_empty():
			continue
		var outer: PackedVector2Array = rings[0]
		if outer.size() < 3:
			continue
		if fill.a > 0.0:
			draw_colored_polygon(outer, fill)
		if selected:
			draw_colored_polygon(outer, SELECT_FILL)
		_draw_ring(outer, SELECT_OUTLINE if selected else border, selected_width if selected else width)
		for ring_index in range(1, rings.size()):
			var hole: PackedVector2Array = rings[ring_index]
			_draw_ring(hole, SELECT_OUTLINE if selected else border, selected_width if selected else width)


func _draw_ring(points: PackedVector2Array, color: Color, width: float) -> void:
	if points.size() < 2:
		return
	var closed := points.duplicate()
	if not closed[0].is_equal_approx(closed[closed.size() - 1]):
		closed.append(closed[0])
	draw_polyline(closed, color, width, true)


func _hit(point: Vector2) -> Dictionary:
	if _mode == MODE_CELLS:
		for i in range(_cells.size() - 1, -1, -1):
			if _point_in_item(point, _cells[i]):
				return _cells[i]
	else:
		for i in range(_provinces.size() - 1, -1, -1):
			if _point_in_item(point, _provinces[i]):
				return _provinces[i]
	return {}


func _point_in_item(point: Vector2, item: Dictionary) -> bool:
	for part_raw in item.get("viewer_parts", []):
		if not part_raw is Array:
			continue
		var rings: Array = part_raw
		if rings.is_empty() or not Geometry2D.is_point_in_polygon(point, rings[0]):
			continue
		var inside_hole := false
		for i in range(1, rings.size()):
			if Geometry2D.is_point_in_polygon(point, rings[i]):
				inside_hole = true
				break
		if not inside_hole:
			return true
	return false


func _show_selection(item: Dictionary) -> void:
	if not is_instance_valid(_selection_label):
		return
	if item.has("parent_id"):
		_selection_label.text = "КЛЕТКА\n%s\n%s\nПровинция: %s\nТерритория: %s\nПлощадь: %.1f км²" % [
			str(item.get("id", "")),
			str(item.get("local_id", "")),
			str(item.get("parent_name", item.get("parent_id", ""))),
			str(item.get("territory", "")),
			float(item.get("area_km2", 0.0)),
		]
	else:
		var sources: Array = item.get("source_names", [])
		var source_text := ", ".join(PackedStringArray(sources.map(func(x): return str(x))))
		_selection_label.text = "ИГРОВАЯ ПРОВИНЦИЯ\n%s\nID: %s\nТерритория: %s\nКлеток: %d\nПлощадь: %.1f км²\nИсточники: %s" % [
			str(item.get("name", "")), str(item.get("id", "")), str(item.get("territory", "")),
			int(item.get("target_cell_count", 0)), float(item.get("area_km2", 0.0)), source_text,
		]


func _focus_all() -> void:
	if not is_instance_valid(_camera) or _world_bbox.size() < 4:
		return
	var minx := float(_world_bbox[0]); var miny := float(_world_bbox[1])
	var maxx := float(_world_bbox[2]); var maxy := float(_world_bbox[3])
	var size := Vector2(maxf(maxx - minx, 1.0), maxf(maxy - miny, 1.0))
	var viewport_size := get_viewport_rect().size
	var zoom := minf(viewport_size.x / (size.x * 1.12), viewport_size.y / (size.y * 1.12))
	_camera.position = Vector2((minx + maxx) * 0.5, (miny + maxy) * 0.5)
	_camera.zoom = Vector2(zoom, zoom)
	if _camera.has_method("set_target_zoom_at_center"):
		_camera.call("set_target_zoom_at_center", zoom)


func _province_color(index: int) -> Color:
	var hue := fmod(float(index) * GOLDEN_HUE_STEP, 1.0)
	return Color.from_hsv(hue, PROVINCE_FILL_SATURATION, PROVINCE_FILL_VALUE, 1.0)


func _to_parts(raw_parts: Variant) -> Array:
	var result: Array = []
	if not raw_parts is Array:
		return result
	for raw_part in raw_parts:
		if not raw_part is Dictionary:
			continue
		var converted: Array = []
		for raw_ring in raw_part.get("rings", []):
			if not raw_ring is Array:
				continue
			var ring := PackedVector2Array()
			for raw_point in raw_ring:
				if raw_point is Array and raw_point.size() >= 2:
					ring.append(Vector2(float(raw_point[0]), float(raw_point[1])))
			if ring.size() >= 3:
				converted.append(ring)
		if not converted.is_empty():
			result.append(converted)
	return result


func _merge_bbox(current: Array, raw: Variant) -> Array:
	if not raw is Array or raw.size() < 4:
		return current
	if current.size() < 4:
		return [float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])]
	return [minf(float(current[0]), float(raw[0])), minf(float(current[1]), float(raw[1])), maxf(float(current[2]), float(raw[2])), maxf(float(current[3]), float(raw[3]))]


func _load_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		_fail("не найден %s" % path)
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if typeof(parsed) != TYPE_DICTIONARY:
		_fail("неверный JSON %s" % path)
		return {}
	return parsed


func _build_panel() -> void:
	if not is_instance_valid(_ui):
		return
	_panel = PanelContainer.new()
	_panel.offset_left = 760.0
	_panel.offset_top = 28.0
	_panel.offset_right = 1235.0
	_panel.offset_bottom = 300.0
	_ui.add_child(_panel)
	var margin := MarginContainer.new()
	for side in ["margin_left", "margin_top", "margin_right", "margin_bottom"]:
		margin.add_theme_constant_override(side, 12)
	_panel.add_child(margin)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 7)
	margin.add_child(box)
	var title := Label.new()
	title.add_theme_font_size_override("font_size", 19)
	title.text = "Британия + Северная Атлантика"
	box.add_child(title)
	_summary_label = Label.new()
	box.add_child(_summary_label)
	_selection_label = Label.new()
	_selection_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_selection_label.custom_minimum_size = Vector2(440, 120)
	box.add_child(_selection_label)
	_panel.visible = false
	_update_summary()


func _update_summary() -> void:
	if not is_instance_valid(_summary_label):
		return
	var mode_name := ["OFF", "ПРОВИНЦИИ", "КЛЕТКИ", "OVERLAY"][_mode]
	_summary_label.text = "N — режим: %s\nПровинций: %d • клеток: %d\nШотландия: 10 провинций / 26 клеток\nShift+N — показать весь регион" % [mode_name, _provinces.size(), _cells.size()]


func _show_status(text: String) -> void:
	var root_viewer := get_parent()
	if is_instance_valid(root_viewer) and root_viewer.has_method("_show_top_info"):
		root_viewer.call("_show_top_info", text)
	else:
		print(text)


func _fail(text: String) -> void:
	_load_error = text
	push_error("BritainNorthAtlanticViewer: %s" % text)
