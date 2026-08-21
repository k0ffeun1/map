extends Node2D
## Cached render node for one dissolved world-region polygon part.

const OUTLINE_COLOR := Color(0.93, 0.94, 0.90, 0.82)
const SELECT_COLOR := Color(1.0, 0.80, 0.24, 1.0)
const EDIT_SOURCE_COLOR := Color(1.0, 0.42, 0.18, 1.0)
const EDIT_TARGET_COLOR := Color(0.25, 1.0, 0.48, 1.0)

var region_id := ""
var _rings: Array = []
var _fill_color := Color.TRANSPARENT
var _selected := false
var _edit_role := 0 # 0 none, 1 source, 2 target


func setup(p_region_id: String, p_rings: Array, p_fill_color: Color) -> void:
	region_id = p_region_id
	_rings = p_rings
	_fill_color = p_fill_color
	queue_redraw()


func set_selected(value: bool) -> void:
	if _selected == value:
		return
	_selected = value
	queue_redraw()


func set_edit_role(role: int) -> void:
	role = clampi(role, 0, 2)
	if _edit_role == role:
		return
	_edit_role = role
	queue_redraw()


func _draw() -> void:
	if _rings.is_empty():
		return
	var outer: PackedVector2Array = _rings[0]
	var fill_ring := _without_duplicate_closing_point(outer)
	if fill_ring.size() >= 3:
		var triangles := Geometry2D.triangulate_polygon(fill_ring)
		if not triangles.is_empty():
			draw_colored_polygon(fill_ring, _fill_color)
	for ring in _rings:
		var closed := _closed(ring)
		if closed.size() >= 2:
			draw_polyline(closed, OUTLINE_COLOR, -1.0, false)
	if _selected:
		_draw_outline(SELECT_COLOR, 0.9)
	if _edit_role == 1:
		_draw_outline(EDIT_SOURCE_COLOR, 1.5)
	elif _edit_role == 2:
		_draw_outline(EDIT_TARGET_COLOR, 1.5)


func _draw_outline(color: Color, width: float) -> void:
	for ring in _rings:
		var closed := _closed(ring)
		if closed.size() >= 2:
			draw_polyline(closed, color, width, true)


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
