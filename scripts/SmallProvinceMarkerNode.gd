class_name SmallProvinceMarkerNode
extends Node2D
## Один маркер провинции площадью < 300 км² (чекбокс "< 300 км²" в панели
## слоя 8) — кружок + подпись площади НАД ним. Рисуется вручную, тот же
## приём, что ProvinceCityMarkerNode.gd (не тайловый слой — на стыке двух
## тайлов половина растрового маркера проваливалась бы, см. докстринг там же).

const RADIUS := 5.0
const OUTLINE_WIDTH := 1.5
const LABEL_GAP := 6.0

var area_km2: float = 0.0
var font_size: int = 12
var fill_color: Color = Color(1.0, 0.35, 0.20, 1.0)
var outline_color: Color = Color(0.04, 0.03, 0.02, 0.95)
var label_fill_color: Color = Color(1.0, 0.85, 0.78, 0.95)
var label_outline_color: Color = Color(0.05, 0.05, 0.05, 0.85)

@onready var _font: Font = ThemeDB.fallback_font


func setup(p_area_km2: float) -> void:
	area_km2 = p_area_km2
	queue_redraw()


func _draw() -> void:
	draw_circle(Vector2.ZERO, RADIUS, outline_color, true, -1.0, true)
	draw_circle(Vector2.ZERO, RADIUS - OUTLINE_WIDTH, fill_color, true, -1.0, true)

	var text := "%.0f км²" % area_km2
	var size := _font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size)
	# Подпись НАД маркером (в отличие от ProvinceCityMarkerNode, где имя города
	# под кружком) — по прямой просьбе пользователя.
	var origin := Vector2(-size.x * 0.5, -RADIUS - LABEL_GAP)
	draw_string_outline(_font, origin, text, HORIZONTAL_ALIGNMENT_LEFT, -1,
		font_size, maxi(2, font_size / 6), label_outline_color)
	draw_string(_font, origin, text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, label_fill_color)
