extends Node2D
## Batched colored polygon renderer for one hierarchy map chunk.
## Draw commands are recorded only when setup() changes the chunk. Camera pan/zoom
## reuses the cached CanvasItem, so X/C/V/B do not redraw 12 902 cells every frame.

var _polygons: Array = []
var _colors: Array = []


func setup(polygons: Array, colors: Array) -> void:
	_polygons = polygons
	_colors = colors
	queue_redraw()


func polygon_count() -> int:
	return _polygons.size()


func _draw() -> void:
	var count := mini(_polygons.size(), _colors.size())
	for i in range(count):
		var polygon_value: Variant = _polygons[i]
		if not polygon_value is PackedVector2Array:
			continue
		var polygon: PackedVector2Array = polygon_value
		if polygon.size() < 3:
			continue
		var color_value: Variant = _colors[i]
		var color: Color = color_value if color_value is Color else Color.WHITE
		draw_colored_polygon(polygon, color)
