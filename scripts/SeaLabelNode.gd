class_name SeaLabelNode
extends Node2D
## Одна подпись моря/океана/пролива. Рисуется вручную (draw_string), а не
## Control-Label, чтобы просто центрировать текст на точке и красиво
## сделать обводку. position — МИРОВАЯ точка (центроид объекта), не трогаем;
## масштаб (scale) выставляет SeaLabelsLayer каждый кадр = 1/zoom камеры,
## чтобы текст был константного размера на экране при любом зуме.

var text: String = ""
var font_size: int = 15
var fill_color: Color = Color(0.95, 0.98, 1.0, 0.95)
var outline_color: Color = Color(0.05, 0.08, 0.15, 0.75)
## Доп. сдвиг вниз в тех же "экранных" локальных единицах, что font_size (узел
## целиком масштабируется 1/zoom каждый кадр, см. SeaLabelsLayer._process —
## поэтому сдвиг остаётся константным на экране при любом зуме). По
## умолчанию 0 — центрирование на точке, как было (подписи морей это не
## трогает). Городам провинций нужна подпись ПОД маркером, а не поверх него.
var offset_y: float = 0.0

@onready var _font: Font = ThemeDB.fallback_font


func setup(p_text: String, p_font_size: int, p_offset_y: float = 0.0) -> void:
	text = p_text
	font_size = p_font_size
	offset_y = p_offset_y
	queue_redraw()


func _draw() -> void:
	if text.is_empty():
		return
	var size := _font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size)
	var origin := Vector2(-size.x * 0.5, size.y * 0.35 + offset_y)  # центрируем по горизонтали, по вертикали — центр точки + доп. сдвиг
	draw_string_outline(_font, origin, text, HORIZONTAL_ALIGNMENT_LEFT, -1,
		font_size, maxi(2, font_size / 6), outline_color)
	draw_string(_font, origin, text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, fill_color)
