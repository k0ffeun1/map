extends Node2D

const WORLD_PX := 8192.0

var active := false:
	set(value):
		active = value
		if not active:
			end_freehand_stroke()
		queue_redraw()

var stroke_color := Color(1.0, 1.0, 1.0, 1.0)
var stroke_width_px := 2.0
var min_point_spacing_screen_px := 3.0

var _camera: Camera2D
var _data_path := ""
var _strokes: Array = []
var _current_stroke: PackedVector2Array = PackedVector2Array()
var _is_drawing := false


func setup(data_path: String, camera: Camera2D) -> void:
	_data_path = data_path
	_camera = camera
	_load_from_file()


func begin_freehand_stroke(world_pos: Vector2) -> void:
	_is_drawing = true
	_current_stroke = PackedVector2Array([world_pos])
	queue_redraw()


func add_freehand_point(world_pos: Vector2) -> void:
	if not _is_drawing:
		return
	if _current_stroke.is_empty():
		_current_stroke.append(world_pos)
		queue_redraw()
		return
	var min_dist := min_point_spacing_screen_px
	if is_instance_valid(_camera):
		min_dist = min_point_spacing_screen_px / maxf(0.0001, _camera.zoom.x)
	if _current_stroke[_current_stroke.size() - 1].distance_to(world_pos) < min_dist:
		return
	_current_stroke.append(world_pos)
	queue_redraw()


func end_freehand_stroke() -> void:
	if _current_stroke.size() >= 2:
		_strokes.append(_current_stroke.duplicate())
	_is_drawing = false
	_current_stroke = PackedVector2Array()
	queue_redraw()


func finish_stroke() -> void:
	end_freehand_stroke()


func undo_last_point() -> void:
	if _current_stroke.size() > 1:
		_current_stroke.remove_at(_current_stroke.size() - 1)
	elif _current_stroke.size() > 0:
		_current_stroke = PackedVector2Array()
		_is_drawing = false
	elif not _strokes.is_empty():
		_strokes.pop_back()
	queue_redraw()


func clear_current() -> void:
	_is_drawing = false
	_current_stroke = PackedVector2Array()
	queue_redraw()


func clear_all() -> void:
	_is_drawing = false
	_current_stroke = PackedVector2Array()
	_strokes.clear()
	queue_redraw()


func save_to_file() -> int:
	if _data_path.is_empty():
		return 0
	var out_strokes := []
	for stroke in _strokes:
		var pts := []
		for p in stroke:
			pts.append([snappedf(p.x, 0.01), snappedf(p.y, 0.01)])
		out_strokes.append(pts)
	var f := FileAccess.open(ProjectSettings.globalize_path(_data_path), FileAccess.WRITE)
	if not f:
		push_warning("CellBoundaryDraftLayer: failed to save %s" % _data_path)
		return 0
	f.store_string(JSON.stringify({"world_px": WORLD_PX, "strokes": out_strokes}))
	f.close()
	return _strokes.size()


func get_stroke_count() -> int:
	return _strokes.size()


func _load_from_file() -> void:
	_strokes.clear()
	if _data_path.is_empty() or not FileAccess.file_exists(_data_path):
		return
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(_data_path))
	if typeof(parsed) != TYPE_DICTIONARY:
		return
	for raw_stroke in parsed.get("strokes", []):
		if typeof(raw_stroke) != TYPE_ARRAY:
			continue
		var stroke := PackedVector2Array()
		for raw_pt in raw_stroke:
			if typeof(raw_pt) == TYPE_ARRAY and raw_pt.size() >= 2:
				stroke.append(Vector2(float(raw_pt[0]), float(raw_pt[1])))
		if stroke.size() >= 2:
			_strokes.append(stroke)


func _process(_delta: float) -> void:
	if visible:
		queue_redraw()


func _draw() -> void:
	var width := stroke_width_px
	if is_instance_valid(_camera):
		width = stroke_width_px / maxf(0.0001, _camera.zoom.x)
	for stroke in _strokes:
		if stroke.size() >= 2:
			draw_polyline(stroke, stroke_color, width, true)
	if _current_stroke.size() >= 2:
		var preview_color := stroke_color
		preview_color.a *= 0.75
		draw_polyline(_current_stroke, preview_color, width, true)
