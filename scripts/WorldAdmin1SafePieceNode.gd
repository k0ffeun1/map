extends Node2D
## Cached render node for one polygon piece of the clean logical Admin-1 layer.
##
## A polygon piece is NOT a gameplay province. Multiple piece nodes may share
## one logical_admin1_id; selection/highlight is therefore applied to all
## pieces belonging to the same logical parent by WorldAdmin1SafeViewer.

const OUTLINE_COLOR := Color(0.20, 0.92, 1.00, 0.92)
const SELECT_COLOR := Color(1.00, 0.78, 0.18, 1.00)

var logical_admin1_id := ""
var _rings: Array = []
var _fill_color := Color.TRANSPARENT
var _selected := false


func setup(p_logical_admin1_id: String, p_rings: Array, p_fill_color: Color) -> void:
	logical_admin1_id = p_logical_admin1_id
	_rings = p_rings
	_fill_color = p_fill_color
	queue_redraw()


func set_selected(value: bool) -> void:
	if _selected == value:
		return
	_selected = value
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

	var closed := _closed(outer)
	if closed.size() >= 2:
		draw_polyline(closed, OUTLINE_COLOR, 0.52, true)
	if _selected and closed.size() >= 2:
		draw_polyline(closed, SELECT_COLOR, 1.45, true)


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
