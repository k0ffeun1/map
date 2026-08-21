extends Node2D
## India architecture test viewer.
## O = show/hide generated gameplay provinces; LMB = inspect.
##
## Visual rule: gameplay-province borders intentionally copy the DESIGN of
## map Layer 4 province borders from TileMapViewer.BORDER_STYLE["province"]:
## solid neutral gray, sharp edge, no white debug outline and no random fills.
## The direct Node2D preview converts the Layer-4 z7 look (~1.2 screen px)
## back to world width through the current Camera2D zoom, so it keeps the same
## apparent thickness while zooming.

const DATA_PATH := "res://assets/game_data/india_game_provinces_test.json"

# Layer 4: BORDER_STYLE["province"] = width 0.30, #9C9C9C, feather 0.3.
# In the raster provider this is ~1.2 screen px at z7 (0.30 * 4).
const LAYER4_BORDER_COLOR := Color(0.6117647, 0.6117647, 0.6117647, 1.0)
const LAYER4_BORDER_SCREEN_PX := 1.2
const SELECTED_FILL_COLOR := Color(1.0, 1.0, 1.0, 0.12)

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
	z_index = 260
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
	if key != null and key.pressed and not key.echo and (key.physical_keycode == KEY_O or key.keycode == KEY_O):
		if not _load_error.is_empty():
			_show(_load_error)
			get_viewport().set_input_as_handled()
			return
		visible = not visible
		if is_instance_valid(_panel):
			_panel.visible = visible
		_last_zoom = -1.0
		queue_redraw()
		_show("O: Индия • %d игровых провинций" % _items.size() if visible else "Индия: тестовый слой скрыт")
		get_viewport().set_input_as_handled()
		return
	if not visible:
		return
	var mouse := event as InputEventMouseButton
	if mouse == null or not mouse.pressed or mouse.button_index != MOUSE_BUTTON_LEFT:
		return
	var point := get_global_mouse_position()
	for item in _items:
		if _point_in_item(point, item):
			_selected = str(item.get("id", ""))
			_show("%s • %s • %d клеток" % [str(item.get("source_admin1_name", "?")), str(item.get("name", _selected)), int(item.get("cell_count", 0))])
			queue_redraw()
			get_viewport().set_input_as_handled()
			return

func _load_data() -> void:
	if not FileAccess.file_exists(DATA_PATH):
		_load_error = "Нет India test data. Запусти: python scripts/tools/run_india_game_province_test.py"
		return
	var file := FileAccess.open(DATA_PATH, FileAccess.READ)
	if file == null:
		_load_error = "Не удалось открыть India test data"
		return
	var parsed = JSON.parse_string(file.get_as_text())
	if typeof(parsed) != TYPE_DICTIONARY:
		_load_error = "India test data: неверный JSON"
		return
	_items = parsed.get("game_provinces", [])
	if _items.is_empty():
		_load_error = "India test data пуст"

func _draw() -> void:
	if not visible:
		return
	var zoom := maxf(0.0001, _camera.zoom.x if is_instance_valid(_camera) else 1.0)
	var border_width := LAYER4_BORDER_SCREEN_PX / zoom

	for item_raw in _items:
		var item: Dictionary = item_raw
		var selected := str(item.get("id", "")) == _selected
		for part_raw in item.get("parts", []):
			var part: Dictionary = part_raw
			var rings: Array = part.get("rings", [])
			if rings.is_empty():
				continue

			# Layer 4 itself does not use rainbow debug fills. Only the currently
			# selected gameplay province gets a subtle translucent fill, while its
			# border stays exactly the same Layer-4 gray as every other province.
			if selected:
				var outer := _ring_to_points(rings[0])
				if outer.size() >= 3:
				draw_colored_polygon(outer, SELECTED_FILL_COLOR)

			# Draw every ring (outer contour and holes) with the same solid gray
			# province-border design as Layer 4.
			for ring_raw in rings:
				var points := _ring_to_points(ring_raw)
				if points.size() < 2:
					continue
				if points[0].distance_squared_to(points[points.size() - 1]) > 0.00000001:
					points.append(points[0])
				draw_polyline(points, LAYER4_BORDER_COLOR, border_width, true)

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
	_panel.position = Vector2(1480, 16)
	_panel.size = Vector2(400, 86)
	_label = Label.new()
	_label.text = "INDIA TEST\nO — игровые провинции\nЛКМ — информация"
	_panel.add_child(_label)
	_ui.add_child(_panel)

func _show(text: String) -> void:
	if is_instance_valid(_label):
		_label.text = text
		_panel.visible = true
