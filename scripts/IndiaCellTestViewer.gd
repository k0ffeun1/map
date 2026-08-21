extends Node2D
## Separate India Stage-6 cell viewer.
## P = show/hide generated cells; LMB = inspect a cell.
##
## This layer is intentionally independent from IndiaGameProvinceTestViewer:
## - P shows the raw Stage-6 gameplay cells;
## - O shows gameplay provinces assembled from those cells;
## - both can be enabled together, with province borders drawn above cells.

const DATA_PATH := "res://assets/subdivision_stage6/india_test_subdivisions.json"

const CELL_BORDER_COLOR := Color(0.0, 0.0, 0.0, 0.92)
const CELL_BORDER_SCREEN_PX := 0.65
const SELECTED_FILL_COLOR := Color(0.16, 0.74, 0.96, 0.22)

var _items: Array = []
var _camera: Camera2D
var _ui: CanvasLayer
var _panel: PanelContainer
var _label: Label
var _selected := ""
var _load_error := ""
var _last_zoom := -1.0

func _ready() -> void:
	_camera = get_node_or_null("../Camera2D") as Camera2D
	_ui = get_node_or_null("../UI") as CanvasLayer
	z_index = 250
	visible = false
	_load_data()
	_build_panel()
	set_process(true)
	set_process_input(true)

func _process(_delta: float) -> void:
	if not visible:
		return
	var zoom := maxf(0.0001, _camera.zoom.x if is_instance_valid(_camera) else 1.0)
	if absf(zoom - _last_zoom) > 0.0001:
		_last_zoom = zoom
		queue_redraw()

func _input(event: InputEvent) -> void:
	var key := event as InputEventKey
	if key != null and key.pressed and not key.echo and (key.physical_keycode == KEY_P or key.keycode == KEY_P):
		if not _load_error.is_empty():
			_show(_load_error)
			get_viewport().set_input_as_handled()
			return
		visible = not visible
		if is_instance_valid(_panel):
			_panel.visible = visible
		_last_zoom = -1.0
		queue_redraw()
		_show("P: Индия • %d клеток" % _items.size() if visible else "Индия: слой клеток скрыт")
		get_viewport().set_input_as_handled()
		return

	if not visible:
		return

	# When the gameplay-province layer is also visible, its click inspection
	# has priority. The cell layer still remains visible underneath it.
	var province_viewer := get_node_or_null("../IndiaGameProvinceTestViewer")
	if is_instance_valid(province_viewer) and bool(province_viewer.get("visible")):
		return

	var mouse := event as InputEventMouseButton
	if mouse == null or not mouse.pressed or mouse.button_index != MOUSE_BUTTON_LEFT:
		return
	var point := get_global_mouse_position()
	for item_raw in _items:
		var item: Dictionary = item_raw
		if _point_in_item(point, item):
			_selected = str(item.get("id", ""))
			_show("%s • %s • %.1f км²" % [
				str(item.get("source_admin1_name", "?")),
				_selected,
				float(item.get("area_km2", 0.0)),
			])
			queue_redraw()
			get_viewport().set_input_as_handled()
			return

func _load_data() -> void:
	if not FileAccess.file_exists(DATA_PATH):
		_load_error = "Нет клеток Индии. Запусти: python scripts/tools/run_india_game_province_test.py"
		return
	var file := FileAccess.open(DATA_PATH, FileAccess.READ)
	if file == null:
		_load_error = "Не удалось открыть клетки Индии"
		return
	var parsed = JSON.parse_string(file.get_as_text())
	if typeof(parsed) != TYPE_DICTIONARY:
		_load_error = "India cells: неверный JSON"
		return

	_items.clear()
	for province_raw in parsed.get("provinces", []):
		if not province_raw is Dictionary:
			continue
		var province: Dictionary = province_raw
		var source_name := str(province.get("name", province.get("province_id", "?")))
		for zone_raw in province.get("zones", []):
			if not zone_raw is Dictionary:
				continue
			var item: Dictionary = zone_raw.duplicate(true)
			item["source_admin1_name"] = source_name
			_items.append(item)

	if _items.is_empty():
		_load_error = "India cells: слой пуст"

func _draw() -> void:
	if not visible:
		return
	var zoom := maxf(0.0001, _camera.zoom.x if is_instance_valid(_camera) else 1.0)
	var border_width := CELL_BORDER_SCREEN_PX / zoom

	for item_raw in _items:
		var item: Dictionary = item_raw
		var selected := str(item.get("id", "")) == _selected
		for part_raw in item.get("parts", []):
			if not part_raw is Dictionary:
				continue
			var part: Dictionary = part_raw
			var rings: Array = part.get("rings", [])
			if rings.is_empty():
				continue

			if selected:
				var outer := _ring_to_points(rings[0])
				if outer.size() >= 3:
					draw_colored_polygon(outer, SELECTED_FILL_COLOR)

			for ring_raw in rings:
				var points := _ring_to_points(ring_raw)
				if points.size() < 2:
					continue
				if points[0].distance_squared_to(points[points.size() - 1]) > 0.00000001:
					points.append(points[0])
				draw_polyline(points, CELL_BORDER_COLOR, border_width, true)

func _ring_to_points(raw_ring: Variant) -> PackedVector2Array:
	var points := PackedVector2Array()
	if not raw_ring is Array:
		return points
	for raw in raw_ring:
		if raw is Array and raw.size() >= 2:
			points.append(Vector2(float(raw[0]), float(raw[1])))
	return points

func _point_in_item(point: Vector2, item: Dictionary) -> bool:
	for part_raw in item.get("parts", []):
		if not part_raw is Dictionary:
			continue
		var part: Dictionary = part_raw
		var rings: Array = part.get("rings", [])
		if rings.is_empty():
			continue
		var outer := _ring_to_points(rings[0])
		if outer.size() < 3 or not Geometry2D.is_point_in_polygon(point, outer):
			continue
		var in_hole := false
		for hole_index in range(1, rings.size()):
			var hole := _ring_to_points(rings[hole_index])
			if hole.size() >= 3 and Geometry2D.is_point_in_polygon(point, hole):
				in_hole = true
				break
		if not in_hole:
			return true
	return false

func _build_panel() -> void:
	if _ui == null:
		return
	_panel = PanelContainer.new()
	_panel.visible = false
	_panel.position = Vector2(1480, 112)
	_panel.size = Vector2(400, 86)
	_label = Label.new()
	_label.text = "INDIA CELLS\nP — клетки\nO — игровые провинции"
	_panel.add_child(_label)
	_ui.add_child(_panel)

func _show(text: String) -> void:
	if is_instance_valid(_label):
		_label.text = text
		_panel.visible = true
