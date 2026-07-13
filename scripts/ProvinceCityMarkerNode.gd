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
var province_name: String = ""  ## имя провинции (ключ в province_cities_iberia.json) — нужно для сохранения после перетаскивания, см. ProvinceCityMarkersLayer.save_to_file()
## Дефолт подписи — PT Sans Caption/15/#F3E8D2/#33434A/обводка 2px/жирность
## 60%/разрядка 5% (прямая просьба пользователя 2026-07-13) — панель "Шрифт
## городов" в TileMapViewer.gd проставляет те же значения поверх этих при
## старте, здесь дублируются просто чтобы дефолт узла не расходился с панелью.
var font_size: int = 15
var fill_color: Color = Color(1.0, 0.78, 0.20, 1.0)
var outline_color: Color = Color(0.04, 0.03, 0.02, 0.95)
var highlight_color: Color = Color(1.0, 0.95, 0.72, 0.95)
var label_fill_color: Color = Color("F3E8D2")
var label_outline_color: Color = Color("33434A")
var label_outline_width: int = 2  ## 0 = взять maxi(2, font_size / 6), см. _draw()

## Курсив/жирность/разрядка — синтетические эффекты через FontVariation,
## работают одинаково для ЛЮБОГО из шрифтов CITY_LABEL_FONTS (variable или
## static ttf), поэтому не нужны отдельные italic/bold файлы шрифтов.
var is_italic: bool = false
var bold_amount: float = 0.72  ## 0.0..1.2 — FontVariation.variation_embolden (60%)
var letter_spacing_percent: float = 5.0  ## доп. разрядка между буквами, % от font_size
const ITALIC_SHEAR := 0.22  ## тангенс наклона синтетического курсива (~12°)

var _base_font: Font = ThemeDB.fallback_font  ## сырой шрифт, меняется извне через set_font()
var _font: Font = ThemeDB.fallback_font  ## активный шрифт для отрисовки — FontVariation поверх _base_font, см. _rebuild_font()


func setup(p_name: String) -> void:
	city_name = p_name
	queue_redraw()


## Живая правка шрифта подписи (панель "Шрифт городов", слой 4) — только
## перерисовка, без пересоздания узла, чтобы позиция/перетаскивание не сбились.
func set_font(font: Font) -> void:
	_base_font = font
	_rebuild_font()


func set_label_style(p_font_size: int, p_fill: Color, p_outline: Color, p_outline_width: int) -> void:
	font_size = p_font_size
	label_fill_color = p_fill
	label_outline_color = p_outline
	label_outline_width = p_outline_width
	_rebuild_font()  # разрядка в px зависит от font_size — пересчитать


## Курсив/жирность/разрядка (панель "Шрифт городов", слой 4, прямая просьба
## пользователя 2026-07-13) — p_bold_amount 0..1, p_letter_spacing_percent в %.
func set_text_effects(p_italic: bool, p_bold_amount: float, p_letter_spacing_percent: float) -> void:
	is_italic = p_italic
	bold_amount = p_bold_amount
	letter_spacing_percent = p_letter_spacing_percent
	_rebuild_font()


func _rebuild_font() -> void:
	var variation := FontVariation.new()
	variation.base_font = _base_font
	variation.variation_transform = (
		Transform2D(Vector2(1, 0), Vector2(ITALIC_SHEAR, 1), Vector2.ZERO)
		if is_italic else Transform2D.IDENTITY)
	variation.variation_embolden = bold_amount
	variation.set_spacing(TextServer.SPACING_GLYPH, roundi(font_size * letter_spacing_percent / 100.0))
	_font = variation
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
	var outline_w := label_outline_width if label_outline_width > 0 else maxi(2, font_size / 6)
	draw_string_outline(_font, origin, city_name, HORIZONTAL_ALIGNMENT_LEFT, -1,
		font_size, outline_w, label_outline_color)
	draw_string(_font, origin, city_name, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, label_fill_color)
