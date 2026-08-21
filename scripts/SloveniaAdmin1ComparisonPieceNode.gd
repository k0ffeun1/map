extends Node2D
## Lightweight debug polygon used by SloveniaAdmin1ComparisonViewer.

var _rings: Array = []
var _fill_color := Color.TRANSPARENT
var _outline_color := Color.WHITE
var _outline_width := 0.8


func setup(p_rings: Array, p_fill: Color, p_outline: Color, p_width: float = 0.8) -> void:
	_rings = p_rings
	_fill_color = p_fill
	_outline_color = p_outline
	_outline_width = p_width
	queue_redraw()


func _draw() -> void:
	if _rings.is_empty():
		return
	var outer: PackedVector2Array = _rings[0]
	var fill_ring := outer.duplicate()
	if fill_ring.size() >= 2 and fill_ring[0].is_equal_approx(fill_ring[fill_ring.size() - 1]):
		fill_ring.resize(fill_ring.size() - 1)
	if fill_ring.size() >= 3 and not Geometry2D.triangulate_polygon(fill_ring).is_empty():
		draw_colored_polygon(fill_ring, _fill_color)
	var closed := outer.duplicate()
	if closed.size() >= 2 and not closed[0].is_equal_approx(closed[closed.size() - 1]):
		closed.append(closed[0])
	if closed.size() >= 2:
		draw_polyline(closed, _outline_color, _outline_width, true)
