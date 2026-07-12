extends Node2D

var _rings: Array = []
var _fill_color := Color(0.95, 0.76, 0.34, 0.34)
var _outline_color := Color(1.0, 0.92, 0.55, 0.85)
var _outline_width := 1.2


func set_rings(rings: Array, fill_color: Color = Color(0.95, 0.76, 0.34, 0.34)) -> void:
	_rings = rings
	_fill_color = fill_color
	_outline_color = Color(fill_color.r, fill_color.g, fill_color.b, minf(fill_color.a + 0.45, 0.9))
	queue_redraw()


func clear() -> void:
	_rings.clear()
	queue_redraw()


func _draw() -> void:
	for ring in _rings:
		if ring.size() < 3:
			continue
		draw_colored_polygon(ring, _fill_color)
		var outline := PackedVector2Array(ring)
		outline.append(ring[0])
		draw_polyline(outline, _outline_color, _outline_width, true)
