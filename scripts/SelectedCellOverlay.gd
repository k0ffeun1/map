extends Node2D

var _rings: Array = []
var _fill_color := Color(0.95, 0.76, 0.34, 0.34)
var _outline_color := Color(1.0, 0.92, 0.55, 0.85)
var _outline_width := 1.2
var _outline_blur := 4.0
var _blur_steps := 5


func set_rings(rings: Array, fill_color: Color = Color(0.95, 0.76, 0.34, 0.34)) -> void:
	_rings = rings
	_fill_color = fill_color
	queue_redraw()


func set_style(fill_color: Color, outline_color: Color, outline_width: float, outline_blur: float, blur_steps: int = 5) -> void:
	_fill_color = fill_color
	_outline_color = outline_color
	_outline_width = maxf(outline_width, 0.0)
	_outline_blur = maxf(outline_blur, 0.0)
	_blur_steps = maxi(blur_steps, 1)
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
		if _outline_blur > 0.0 and _outline_color.a > 0.0:
			for step in range(_blur_steps, 0, -1):
				var t := float(step) / float(_blur_steps)
				var blur_color := _outline_color
				blur_color.a *= 0.16 * t
				draw_polyline(outline, blur_color, _outline_width + _outline_blur * t, true)
		draw_polyline(outline, _outline_color, _outline_width, true)
