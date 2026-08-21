extends Node2D

var _rings: Array = []
var _outline_chains: Array = []
var _fill_color := Color(0.95, 0.76, 0.34, 0.34)
var _outline_color := Color(1.0, 0.92, 0.55, 0.85)
var _outline_width := 1.2
var _outline_blur := 4.0
var _blur_steps := 5
var _draw_closed := true


func set_rings(rings: Array, fill_color: Color = Color(0.95, 0.76, 0.34, 0.34)) -> void:
	_rings = rings
	_outline_chains.clear()
	_fill_color = fill_color
	_draw_closed = true
	queue_redraw()


func set_open_chains(chains: Array, fill_color: Color = Color(0.0, 0.0, 0.0, 0.0)) -> void:
	_rings = chains
	_outline_chains.clear()
	_fill_color = fill_color
	_draw_closed = false
	queue_redraw()


func set_rings_with_outline_chains(rings: Array, outline_chains: Array,
		fill_color: Color = Color(0.95, 0.76, 0.34, 0.34)) -> void:
	_rings = rings
	_outline_chains = outline_chains
	_fill_color = fill_color
	_draw_closed = true
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
	_outline_chains.clear()
	_draw_closed = true
	queue_redraw()


func _draw() -> void:
	for ring in _rings:
		if ring.size() < 2:
			continue
		if _draw_closed and ring.size() >= 3 and _fill_color.a > 0.0:
			draw_colored_polygon(ring, _fill_color)
	var outline_sources: Array = _outline_chains if not _outline_chains.is_empty() else _rings
	for source in outline_sources:
		if source.size() < 2:
			continue
		var outline := PackedVector2Array(source)
		if _draw_closed and _outline_chains.is_empty():
			outline.append(source[0])
		if _outline_blur > 0.0 and _outline_color.a > 0.0:
			for step in range(_blur_steps, 0, -1):
				var t := float(step) / float(_blur_steps)
				var blur_color := _outline_color
				blur_color.a *= 0.16 * t
				draw_polyline(outline, blur_color, _outline_width + _outline_blur * t, true)
		draw_polyline(outline, _outline_color, _outline_width, true)
