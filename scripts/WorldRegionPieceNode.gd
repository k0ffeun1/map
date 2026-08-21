extends Node2D
## Один полигональный кусок мирового региона.
##
## Главное отличие от старого WorldRegionsDraftViewer: этот CanvasItem рисует
## свой кусок ОДИН раз и дальше Godot хранит draw-команды. Камера может
## двигаться/масштабироваться без queue_redraw() и без повторной
## триангуляции всех 1500+ частей мира. Отдельный CanvasItem также позволяет
## движку отсекать куски вне экрана.

const OUTLINE_COLOR := Color(0.93, 0.94, 0.90, 0.82)
const SELECT_COLOR := Color(1.0, 0.80, 0.24, 1.0)

var region_id := ""
var _rings: Array = []
var _fill_color := Color.TRANSPARENT
var _selected := false


func setup(p_region_id: String, p_rings: Array, p_fill_color: Color) -> void:
	region_id = p_region_id
	_rings = p_rings
	_fill_color = p_fill_color
	queue_redraw()


func set_selected(value: bool) -> void:
	if _selected == value:
		return
	_selected = value
	# Перерисовывается только выбранный/снятый регион, а не весь мир.
	queue_redraw()


func _draw() -> void:
	if _rings.is_empty():
		return

	var outer: PackedVector2Array = _rings[0]
	var fill_ring := _without_duplicate_closing_point(outer)
	if fill_ring.size() >= 3:
		# Проверка нужна для сложных островных контуров, которые Godot иногда
		# не может триангулировать. Это происходит только при первом draw этого
		# конкретного куска, а не при каждом изменении камеры.
		var triangles := Geometry2D.triangulate_polygon(fill_ring)
		if not triangles.is_empty():
			draw_colored_polygon(fill_ring, _fill_color)

	# width < 0 использует тонкий primitive line: линия остаётся тонкой при
	# масштабировании камеры и не требует менять ширину/queue_redraw на зуме.
	for ring in _rings:
		var closed := _closed(ring)
		if closed.size() >= 2:
			draw_polyline(closed, OUTLINE_COLOR, -1.0, false)

	if _selected:
		for ring in _rings:
			var closed := _closed(ring)
			if closed.size() >= 2:
				draw_polyline(closed, SELECT_COLOR, 0.9, true)


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
