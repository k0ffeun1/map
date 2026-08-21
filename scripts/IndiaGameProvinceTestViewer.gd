extends Node2D
## India architecture test viewer.
## O = show/hide generated gameplay provinces; LMB = inspect.

const DATA_PATH := "res://assets/game_data/india_game_provinces_test.json"

var _items: Array = []
var _ui: CanvasLayer
var _panel: PanelContainer
var _label: Label
var _selected := ""
var _load_error := ""

func _ready() -> void:
	_ui = get_node_or_null("../UI") as CanvasLayer
	z_index = 260
	visible = false
	_load_data()
	_build_panel()
	set_process_input(true)

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
	for index in range(_items.size()):
		var item: Dictionary = _items[index]
		var selected := str(item.get("id", "")) == _selected
		var hue := fmod(float(index) * 0.173, 1.0)
		var fill := Color.from_hsv(hue, 0.52, 0.92, 0.22 if not selected else 0.42)
		for part_raw in item.get("parts", []):
			var part: Dictionary = part_raw
			var rings: Array = part.get("rings", [])
			if rings.is_empty():
				continue
			var points := PackedVector2Array()
			for raw in rings[0]:
				points.append(Vector2(float(raw[0]), float(raw[1])))
			if points.size() < 3:
				continue
			draw_colored_polygon(points, fill)
			draw_polyline(points, Color(0.96, 0.96, 0.96, 0.96), 1.7 if not selected else 3.2, true)

func _point_in_item(point: Vector2, item: Dictionary) -> bool:
	for part_raw in item.get("parts", []):
		var part: Dictionary = part_raw
		var rings: Array = part.get("rings", [])
		if rings.is_empty():
			continue
		var points := PackedVector2Array()
		for raw in rings[0]:
			points.append(Vector2(float(raw[0]), float(raw[1])))
		if points.size() >= 3 and Geometry2D.is_point_in_polygon(point, points):
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
