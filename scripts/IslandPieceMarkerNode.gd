class_name IslandPieceMarkerNode
extends Node2D
## Один маркер отдельного куска многочастной провинции (чекбокс "Островные
## куски" в панели слоя 8) — только кружок, без подписи (по прямой просьбе
## пользователя, в отличие от SmallProvinceMarkerNode). Рисуется вручную, тот
## же приём, что ProvinceCityMarkerNode.gd.

const RADIUS := 5.0
const OUTLINE_WIDTH := 1.5

var fill_color: Color = Color(0.25, 0.55, 1.0, 1.0)
var outline_color: Color = Color(0.04, 0.03, 0.02, 0.95)


func _draw() -> void:
	draw_circle(Vector2.ZERO, RADIUS, outline_color, true, -1.0, true)
	draw_circle(Vector2.ZERO, RADIUS - OUTLINE_WIDTH, fill_color, true, -1.0, true)
