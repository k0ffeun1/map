class_name ProvinceCityMarkerNode
extends Node2D
## Один маркер главного города провинции: кружок + подпись ПОД ним. Рисуется
## вручную (draw_circle/draw_string, antialiased=true — Godot 4 сам сглаживает
## контур), НЕ через тайловую систему (см. done.md/сессию 2026-07-12: растровый
## маркер на стыке двух тайлов проваливался — половина круга рисовалась в
## одном тайле, половина в другом, и на стыке просвечивала заливка провинции
## под ним). position — МИРОВАЯ точка; масштаб (scale) выставляет
## ProvinceCityMarkersLayer каждый кадр = 1/zoom камеры, тот же приём, что у
## SeaLabelNode — маркер и текст остаются константного размера на экране.

const RADIUS := 7.0
const OUTLINE_WIDTH := 2.0
const HIGHLIGHT_RADIUS := 2.5
const LABEL_GAP := 8.0  ## зазор между низом круга и подписью, чтобы не сливались

var city_name: String = ""
var font_size: int = 13
var fill_color: Color = Color(1.0, 0.78, 0.20, 1.0)
var outline_color: Color = Color(0.04, 0.03, 0.02, 0.95)
var highlight_color: Color = Color(1.0, 0.95, 0.72, 0.95)
var label_fill_color: Color = Color(0.98, 0.96, 0.90, 0.95)
var label_outline_color: Color = Color(0.05, 0.05, 0.05, 0.8)

@onready var _font: Font = ThemeDB.fallback_font


func setup(p_name: String) -> void:
	city_name = p_name
	queue_redraw()


func _draw() -> void:
	# ЯВНО выше клеток/провинций (см. z_index=100, выставляется в
	# ProvinceCityMarkersLayer.setup, тот же приём, что SeaLabelsLayer) —
	# круг рисуется полностью НЕПРОЗРАЧНЫМ, поэтому заливка провинции под ним
	# больше не может просвечивать ни при каких обстоятельствах.
	draw_circle(Vector2.ZERO, RADIUS, outline_color, true, -1.0, true)
	draw_circle(Vector2.ZERO, RADIUS - OUTLINE_WIDTH, fill_color, true, -1.0, true)
	draw_circle(Vector2.ZERO, HIGHLIGHT_RADIUS, highlight_color, true, -1.0, true)

	if city_name.is_empty():
		return
	var size := _font.get_string_size(city_name, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size)
	var origin := Vector2(-size.x * 0.5, RADIUS + LABEL_GAP + size.y * 0.75)
	draw_string_outline(_font, origin, city_name, HORIZONTAL_ALIGNMENT_LEFT, -1,
		font_size, maxi(2, font_size / 6), label_outline_color)
	draw_string(_font, origin, city_name, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, label_fill_color)
