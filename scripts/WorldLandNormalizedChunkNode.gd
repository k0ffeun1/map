extends Node2D
## Локальный батч заливки для слоя Z.
##
## Один узел содержит только полигоны небольшого географического участка.
## Godot кэширует его draw-команды и может отсечь весь CanvasItem, когда этот
## участок вне камеры. Цвет всей суши меняется через modulate родительского
## узла, поэтому выбор world_land НЕ вызывает повторную триангуляцию/перерисовку.

var _polygons: Array = []


func setup(polygons: Array) -> void:
	_polygons = polygons
	queue_redraw()


func polygon_count() -> int:
	return _polygons.size()


func _draw() -> void:
	for polygon_value in _polygons:
		if polygon_value is PackedVector2Array:
			var polygon: PackedVector2Array = polygon_value
			if polygon.size() >= 3:
				# Геометрия уже прошла canonical normalized pipeline F6.
				# Не вызываем Geometry2D.triangulate_polygon отдельно: это удваивало
				# CPU-работу, потому что draw_colored_polygon всё равно триангулирует.
				draw_colored_polygon(polygon, Color.WHITE)
