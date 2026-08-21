class_name LocalTileWarmup
extends Node
## Прогревает локальные тяжёлые векторные слои до начала игры.
##
## В отличие от TilePreloader (он скачивает весь спутник на диск), здесь
## создаются только текстуры, реально нужные для детальной Иберии. Очередь
## маленькая и ограничена несколькими фоновыми задачами, чтобы не выбить
## память и не пытаться растеризовать весь мир.

const MAX_IN_FLIGHT := 3

var _tasks: Array = []
var _cursor := 0
var _in_flight: Dictionary = {}
var _done := 0
var _label: Label


## providers must expose get_content_bounds() and request_tile(z, x, y).
func setup(providers: Array, ui_layer: CanvasLayer, min_z: int, max_z: int) -> void:
	for provider in providers:
		if not is_instance_valid(provider) or not provider.has_method("get_content_bounds"):
			continue
		var bounds: Rect2 = provider.get_content_bounds()
		if bounds.size == Vector2.ZERO:
			continue
		for z in range(min_z, max_z + 1):
			_append_provider_tiles(provider, bounds, z)
	if _tasks.is_empty():
		queue_free()
		return
	_label = Label.new()
	_label.position = Vector2(24.0, 945.0)
	_label.add_theme_color_override("font_color", Color(0.82, 0.95, 1.0, 1.0))
	ui_layer.add_child(_label)
	_update_label()
	set_process(true)


func _append_provider_tiles(provider: Node, bounds: Rect2, z: int) -> void:
	var n := 1 << z
	var tile_world := 8192.0 / float(n)
	var x0 := clampi(floori(bounds.position.x / tile_world), 0, n - 1)
	var y0 := clampi(floori(bounds.position.y / tile_world), 0, n - 1)
	var x1 := clampi(floori((bounds.end.x - 0.0001) / tile_world), 0, n - 1)
	var y1 := clampi(floori((bounds.end.y - 0.0001) / tile_world), 0, n - 1)
	for y in range(y0, y1 + 1):
		for x in range(x0, x1 + 1):
			_tasks.append({"provider": provider, "z": z, "x": x, "y": y})


func _process(_delta: float) -> void:
	var pending: Dictionary = {}
	for key in _in_flight:
		var task: Dictionary = _in_flight[key]
		var provider: Node = task["provider"]
		if not is_instance_valid(provider):
			_done += 1
			continue
		if provider.request_tile(task["z"], task["x"], task["y"]) != null:
			_done += 1
		else:
			pending[key] = task
	_in_flight = pending
	while _in_flight.size() < MAX_IN_FLIGHT and _cursor < _tasks.size():
		var task: Dictionary = _tasks[_cursor]
		_cursor += 1
		var provider: Node = task["provider"]
		if not is_instance_valid(provider):
			_done += 1
			continue
		var key := "%d:%d/%d/%d" % [provider.get_instance_id(), task["z"], task["x"], task["y"]]
		if provider.request_tile(task["z"], task["x"], task["y"]) != null:
			_done += 1
		else:
			_in_flight[key] = task
	_update_label()
	if _done >= _tasks.size():
		if is_instance_valid(_label):
			_label.text = "Детальные тайлы готовы"
			get_tree().create_timer(1.5).timeout.connect(func() -> void:
				if is_instance_valid(_label):
					_label.queue_free()
				queue_free())
		set_process(false)


func _update_label() -> void:
	if is_instance_valid(_label):
		_label.text = "Подготовка детальных тайлов: %d / %d" % [_done, _tasks.size()]
