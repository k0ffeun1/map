extends Node2D

const WORLD_PX := 8192.0

var active := false:
	set(value):
		active = value
		if not active:
			end_freehand_stroke()
		queue_redraw()

## Режим точечного редактирования уже готовых (сохранённых) линий — по
## просьбе пользователя 2026-07-15 ("а редактировать линии которые я
## нарисовал я могу?"): отдельный от `active` (рисование новых линий) режим,
## включается своим чекбоксом в панели. Пока включён — ЛКМ на точке существующей
## линии захватывает её для перетаскивания, ПКМ на точке — удаляет её.
var edit_active := false:
	set(value):
		edit_active = value
		if not edit_active:
			end_point_drag()
		queue_redraw()

var stroke_color := Color(1.0, 1.0, 1.0, 1.0)
var stroke_width_px := 2.0
var min_point_spacing_screen_px := 3.0
## Радиус захвата точки под курсором в РЕДАКТИРОВАНИИ (экранные px, делится
## на zoom камеры так же, как min_point_spacing_screen_px) — насколько близко
## нужно кликнуть к существующей точке, чтобы её схватить/удалить.
var edit_point_hit_radius_screen_px := 9.0
## Радиус кружка-ручки поверх каждой точки готовой линии в режиме
## редактирования (мировые px после деления на zoom, как stroke_width_px).
var edit_point_handle_radius_px := 3.0

var _camera: Camera2D
var _data_path := ""
var _strokes: Array = []
var _current_stroke: PackedVector2Array = PackedVector2Array()
var _is_drawing := false

var _drag_stroke_idx := -1
var _drag_point_idx := -1


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
	end_point_drag()
	queue_redraw()


## Радиус захвата в МИРОВЫХ px (см. edit_point_hit_radius_screen_px) — та же
## поправка на зум камеры, что у min_point_spacing_screen_px в add_freehand_point.
func _edit_hit_radius_world() -> float:
	var r := edit_point_hit_radius_screen_px
	if is_instance_valid(_camera):
		r = edit_point_hit_radius_screen_px / maxf(0.0001, _camera.zoom.x)
	return r


## Ищет ближайшую точку среди ВСЕХ сохранённых (готовых) линий в пределах
## радиуса захвата. Возвращает {"stroke": int, "point": int} или {} если
## ничего не попало в радиус — намеренно НЕ трогает _current_stroke
## (незавершённую линию редактируют через undo_last_point/clear_current, как
## и раньше, а не через захват точки).
func _find_nearest_point(world_pos: Vector2) -> Dictionary:
	var max_dist := _edit_hit_radius_world()
	var best_stroke := -1
	var best_point := -1
	var best_dist := max_dist
	for si in range(_strokes.size()):
		var stroke: PackedVector2Array = _strokes[si]
		for pi in range(stroke.size()):
			var d: float = stroke[pi].distance_to(world_pos)
			if d <= best_dist:
				best_dist = d
				best_stroke = si
				best_point = pi
	if best_stroke < 0:
		return {}
	return {"stroke": best_stroke, "point": best_point}


## Захватывает ближайшую точку под курсором для перетаскивания. Возвращает
## true, если что-то захвачено (вызывающая сторона должна "съесть" событие
## мыши только в этом случае — промах мимо точки не должен блокировать клики
## по клеткам под курсором).
func try_begin_point_drag(world_pos: Vector2) -> bool:
	var hit := _find_nearest_point(world_pos)
	if hit.is_empty():
		return false
	_drag_stroke_idx = hit["stroke"]
	_drag_point_idx = hit["point"]
	queue_redraw()
	return true


func is_dragging_point() -> bool:
	return _drag_stroke_idx >= 0


func update_point_drag(world_pos: Vector2) -> void:
	if _drag_stroke_idx < 0 or _drag_stroke_idx >= _strokes.size():
		return
	var stroke: PackedVector2Array = _strokes[_drag_stroke_idx]
	if _drag_point_idx < 0 or _drag_point_idx >= stroke.size():
		return
	stroke[_drag_point_idx] = world_pos
	_strokes[_drag_stroke_idx] = stroke
	queue_redraw()


func end_point_drag() -> void:
	_drag_stroke_idx = -1
	_drag_point_idx = -1
	queue_redraw()


## Удаляет ближайшую точку под курсором (ПКМ в режиме редактирования).
## Если после удаления в линии осталось меньше 2 точек — линия удаляется
## целиком. Возвращает true, если что-то удалено (для "съедания" события,
## как и в try_begin_point_drag).
func try_delete_point_near(world_pos: Vector2) -> bool:
	var hit := _find_nearest_point(world_pos)
	if hit.is_empty():
		return false
	var si: int = hit["stroke"]
	var stroke: PackedVector2Array = _strokes[si]
	stroke.remove_at(hit["point"])
	if stroke.size() < 2:
		_strokes.remove_at(si)
	else:
		_strokes[si] = stroke
	end_point_drag()
	queue_redraw()
	return true


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

	if not edit_active:
		return
	# Ручки поверх точек готовых линий — видны только в режиме
	# редактирования, чтобы не засорять обычный просмотр черновика.
	var handle_r := edit_point_handle_radius_px
	if is_instance_valid(_camera):
		handle_r = edit_point_handle_radius_px / maxf(0.0001, _camera.zoom.x)
	for si in range(_strokes.size()):
		var stroke: PackedVector2Array = _strokes[si]
		for pi in range(stroke.size()):
			var is_dragged := si == _drag_stroke_idx and pi == _drag_point_idx
			var handle_color := Color(1.0, 0.85, 0.2, 1.0) if is_dragged else Color(0.2, 0.85, 1.0, 0.9)
			draw_circle(stroke[pi], handle_r if not is_dragged else handle_r * 1.4, handle_color)
