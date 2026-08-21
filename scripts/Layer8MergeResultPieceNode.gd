extends Node2D
## Lightweight polygon piece for Layer8MergeResultViewer.

var _rings: Array = []
var _base_fill := Color.TRANSPARENT
var _base_outline := Color.WHITE
var _outline_width := 1.0
var _selected := false


func setup(p_rings: Array, p_fill: Color, p_outline: Color, p_width: float = 1.0) -> void:
	_rings = p_rings
	_base_fill = p_fill
	_base_outline = p_outline
	_outline_width = p_width
	queue_redraw()


func set_selected(value: bool) -> void:
	if _selected == value:
		return
	_selected = value
	queue_redraw()


func _draw() -> void:
	if _rings.is_empty():
		return
	var fill := _base_fill
	var outline := _base_outline
	var width := _outline_width
	if _selected:
		fill = Color(
			minf(fill.r * 1.35 + 0.12, 1.0),
			minf(fill.g * 1.35 + 0.12, 1.0),
			minf(fill.b * 1.35 + 0.12, 1.0),
			minf(fill.a + 0.18, 0.82)
		)
		outline = Color.WHITE
		width = maxf(width * 2.1, 2.2)

	var outer: PackedVector2Array = _rings[0]
	var fill_ring := outer.duplicate()
	if fill_ring.size() >= 2 and fill_ring[0].is_equal_approx(fill_ring[fill_ring.size() - 1]):
		fill_ring.resize(fill_ring.size() - 1)
	if fill_ring.size() >= 3 and not Geometry2D.triangulate_polygon(fill_ring).is_empty():
		draw_colored_polygon(fill_ring, fill)

	for raw_ring in _rings:
		var ring: PackedVector2Array = raw_ring
		var closed := ring.duplicate()
		if closed.size() >= 2 and not closed[0].is_equal_approx(closed[closed.size() - 1]):
			closed.append(closed[0])
		if closed.size() >= 2:
			draw_polyline(closed, outline, width, true)
