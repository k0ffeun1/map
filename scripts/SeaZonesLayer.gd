extends Node2D
class_name SeaZonesLayer
## Debug-инструмент "3 уровня моря" (клавиша 5), решение пользователя
## 2026-07-10 (второй заход, объединяет два прежних отдельных debug-слоя
## в один переключатель — регионы разные, но это концептуально одна
## система):
##
## 1. МЕЛКОВОДЬЕ — ФИКСИРОВАННАЯ полоса по расстоянию до берега (не по
##    глубине): -1 км (заходит на сушу) .. +10 км (в море), везде вдоль
##    берега региона Иберия+Балеары (тот же регион, что у слоя 4). Не
##    крутится слайдером — так решил пользователь.
## 2. ШЕЛЬФ — от края мелководья и до РЕДАКТИРУЕМОГО порога (реальная
##    глубина GMRT, тестовый бокс Галисии) — ТОТ ЖЕ цвет, что у мелководья
##    (общий цвет на двоих, один цветовыбор управляет обоими сразу).
## 3. ГЛУБИНЫ МОРЯ — всё глубже порога шельфа — свой цвет, свой слайдер.
##
## См. scripts/shaders/shallow_water_band.gdshader (мелководье, весь
## регион Иберия+Балеары) и scripts/shaders/sea_depth_zones.gdshader
## (шельф/глубины, маленький тестовый бокс Галисии — реальных данных по
## глубине пока нет для всей Иберии).
##
## ТОЛЬКО чтобы подобрать порог/цвета глазами перед тем, как зафиксировать
## их в коде. Подобранные тут значения нигде не сохраняются автоматически.

const SHALLOW_IMG_PATH := "res://assets/generated/coast_distance_field_iberia.png"
const SHALLOW_BBOX_PATH := "res://assets/generated/coast_distance_field_iberia_bbox.json"
const SHALLOW_SHADER_PATH := "res://scripts/shaders/shallow_water_band.gdshader"

const DEPTH_IMG_PATH := "res://assets/generated/sea_depth_raw_test_region.png"
const DEPTH_BBOX_PATH := "res://assets/generated/sea_depth_raw_test_region_bbox.json"
const DEPTH_SHADER_PATH := "res://scripts/shaders/sea_depth_zones.gdshader"

const LAND_MARGIN_KM := 1.0
const SEA_MARGIN_KM := 20.0
const DEFAULT_SHELF_COLOR := Color(0.541, 0.776, 0.855)  # #8ac6da — мелководье/шельф, общий
const DEFAULT_MID_COLOR := Color(0.220, 0.510, 0.690)  # 3-й уровень градиента (склон), между шельфом и глубинами
const DEFAULT_DEEP_COLOR := Color(0.117, 0.313, 0.627)
const DEFAULT_GRADIENT_GAMMA := 0.4
const DEFAULT_MID_POINT := 0.5
const DEFAULT_SHOW_ISOBATHS := false  # решение пользователя 2026-07-11: изобаты выкл. по умолчанию, инструмент скрыт из панели
const DEFAULT_ISOBATH_INTERVAL_M := 500.0
const DEFAULT_ISOBATH_COLOR := Color(1.0, 1.0, 1.0, 0.35)

var _shallow_sprite: Sprite2D
var _shallow_material: ShaderMaterial
var _depth_sprite: Sprite2D
var _depth_material: ShaderMaterial
var _panel: VBoxContainer


func setup(ui_layer: CanvasLayer) -> void:
	_setup_shallow()
	_setup_depth()
	_build_panel(ui_layer)


func _setup_shallow() -> void:
	if not (FileAccess.file_exists(SHALLOW_IMG_PATH) and FileAccess.file_exists(SHALLOW_BBOX_PATH)):
		return
	var bbox_text := FileAccess.get_file_as_string(SHALLOW_BBOX_PATH)
	var bbox: Dictionary = JSON.parse_string(bbox_text)
	if bbox == null:
		return
	var img := Image.new()
	if img.load(SHALLOW_IMG_PATH) != OK:
		return
	var tex := ImageTexture.create_from_image(img)

	_shallow_material = ShaderMaterial.new()
	_shallow_material.shader = load(SHALLOW_SHADER_PATH)
	_shallow_material.set_shader_parameter("encode_min_km", float(bbox["encode_min_km"]))
	_shallow_material.set_shader_parameter("encode_max_km", float(bbox["encode_max_km"]))
	_shallow_material.set_shader_parameter("land_margin_km", LAND_MARGIN_KM)
	_shallow_material.set_shader_parameter("sea_margin_km", SEA_MARGIN_KM)
	_shallow_material.set_shader_parameter("band_color", DEFAULT_SHELF_COLOR)

	_shallow_sprite = Sprite2D.new()
	_shallow_sprite.texture = tex
	_shallow_sprite.material = _shallow_material
	_shallow_sprite.centered = false
	# NEAREST, не LINEAR — расстояние закодировано как 16 бит, разбитые на
	# 2 отдельных 8-битных канала (R/G). LINEAR интерполирует каналы
	# НЕЗАВИСИМО, а не как единое число — там, где младший байт (G)
	# перескакивает 255->0 (каждые ~4 км расстояния), интерполяция даёт
	# мусорные значения (мелкие зубцы/вздутия вдоль всего берега, замечено
	# пользователем 2026-07-10).
	_shallow_sprite.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	_shallow_sprite.position = Vector2(bbox["x0"], bbox["y0"])
	var world_w: float = bbox["x1"] - bbox["x0"]
	var world_h: float = bbox["y1"] - bbox["y0"]
	_shallow_sprite.scale = Vector2(world_w / tex.get_width(), world_h / tex.get_height())
	add_child(_shallow_sprite)


func _setup_depth() -> void:
	if not (FileAccess.file_exists(DEPTH_IMG_PATH) and FileAccess.file_exists(DEPTH_BBOX_PATH)):
		return
	var bbox_text := FileAccess.get_file_as_string(DEPTH_BBOX_PATH)
	var bbox: Dictionary = JSON.parse_string(bbox_text)
	if bbox == null:
		return
	var img := Image.new()
	if img.load(DEPTH_IMG_PATH) != OK:
		return
	var tex := ImageTexture.create_from_image(img)

	_depth_material = ShaderMaterial.new()
	_depth_material.shader = load(DEPTH_SHADER_PATH)
	_depth_material.set_shader_parameter("max_depth_m", float(bbox["max_depth_m"]))
	_depth_material.set_shader_parameter("color_shelf", DEFAULT_SHELF_COLOR)
	_depth_material.set_shader_parameter("color_mid", DEFAULT_MID_COLOR)
	_depth_material.set_shader_parameter("color_deep", DEFAULT_DEEP_COLOR)
	_depth_material.set_shader_parameter("gradient_gamma", DEFAULT_GRADIENT_GAMMA)
	_depth_material.set_shader_parameter("mid_point", DEFAULT_MID_POINT)
	_depth_material.set_shader_parameter("show_isobaths", DEFAULT_SHOW_ISOBATHS)
	_depth_material.set_shader_parameter("isobath_interval_m", DEFAULT_ISOBATH_INTERVAL_M)
	_depth_material.set_shader_parameter("isobath_color", DEFAULT_ISOBATH_COLOR)

	_depth_sprite = Sprite2D.new()
	_depth_sprite.texture = tex
	_depth_sprite.material = _depth_material
	_depth_sprite.centered = false
	_depth_sprite.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	_depth_sprite.position = Vector2(bbox["x0"], bbox["y0"])
	var world_w: float = bbox["x1"] - bbox["x0"]
	var world_h: float = bbox["y1"] - bbox["y0"]
	_depth_sprite.scale = Vector2(world_w / tex.get_width(), world_h / tex.get_height())
	add_child(_depth_sprite)


func _build_panel(ui_layer: CanvasLayer) -> void:
	_panel = VBoxContainer.new()
	_panel.offset_left = 1440.0
	_panel.offset_top = 40.0
	_panel.offset_right = 1896.0
	_panel.offset_bottom = 440.0
	_panel.visible = false
	ui_layer.add_child(_panel)

	# Общий цвет: мелководье + шельф — один пикер обновляет ОБА материала.
	var shelf_row := HBoxContainer.new()
	var shelf_label := Label.new()
	shelf_label.custom_minimum_size = Vector2(280, 0)
	shelf_label.add_theme_color_override("font_color", Color(1, 1, 1))
	shelf_label.text = "Цвет: Мелководье/Шельф"

	var shelf_picker := ColorPickerButton.new()
	shelf_picker.color = DEFAULT_SHELF_COLOR
	shelf_picker.custom_minimum_size = Vector2(80, 24)
	shelf_picker.color_changed.connect(func(color: Color) -> void:
		if _shallow_material:
			_shallow_material.set_shader_parameter("band_color", color)
		if _depth_material:
			_depth_material.set_shader_parameter("color_shelf", color)
	)
	shelf_row.add_child(shelf_label)
	shelf_row.add_child(shelf_picker)
	_panel.add_child(shelf_row)

	# Кривизна непрерывного градиента глубины (0 м -> max_depth_m).
	var gamma_row := HBoxContainer.new()
	var gamma_label := Label.new()
	gamma_label.custom_minimum_size = Vector2(280, 0)
	gamma_label.add_theme_color_override("font_color", Color(1, 1, 1))
	gamma_label.text = "Кривизна градиента: %.2f" % DEFAULT_GRADIENT_GAMMA

	var gamma_slider := HSlider.new()
	gamma_slider.min_value = 0.05
	gamma_slider.max_value = 3.0
	gamma_slider.step = 0.05
	gamma_slider.value = DEFAULT_GRADIENT_GAMMA
	gamma_slider.custom_minimum_size = Vector2(220, 0)
	gamma_slider.value_changed.connect(func(value: float) -> void:
		if _depth_material:
			_depth_material.set_shader_parameter("gradient_gamma", value)
		gamma_label.text = "Кривизна градиента: %.2f" % value
	)
	gamma_row.add_child(gamma_label)
	gamma_row.add_child(gamma_slider)
	_panel.add_child(gamma_row)

	# 3-й уровень градиента ("склон") между шельфом и глубинами.
	var mid_row := HBoxContainer.new()
	var mid_label := Label.new()
	mid_label.custom_minimum_size = Vector2(280, 0)
	mid_label.add_theme_color_override("font_color", Color(1, 1, 1))
	mid_label.text = "Цвет: Склон (3-й уровень)"

	var mid_picker := ColorPickerButton.new()
	mid_picker.color = DEFAULT_MID_COLOR
	mid_picker.custom_minimum_size = Vector2(80, 24)
	mid_picker.color_changed.connect(func(color: Color) -> void:
		if _depth_material:
			_depth_material.set_shader_parameter("color_mid", color)
	)
	mid_row.add_child(mid_label)
	mid_row.add_child(mid_picker)
	_panel.add_child(mid_row)

	var mid_point_row := HBoxContainer.new()
	var mid_point_label := Label.new()
	mid_point_label.custom_minimum_size = Vector2(280, 0)
	mid_point_label.add_theme_color_override("font_color", Color(1, 1, 1))
	mid_point_label.text = "Положение склона: %.2f" % DEFAULT_MID_POINT
	var mid_point_slider := HSlider.new()
	mid_point_slider.min_value = 0.01
	mid_point_slider.max_value = 0.99
	mid_point_slider.step = 0.01
	mid_point_slider.value = DEFAULT_MID_POINT
	mid_point_slider.custom_minimum_size = Vector2(220, 0)
	mid_point_slider.value_changed.connect(func(value: float) -> void:
		if _depth_material:
			_depth_material.set_shader_parameter("mid_point", value)
		mid_point_label.text = "Положение склона: %.2f" % value
	)
	mid_point_row.add_child(mid_point_label)
	mid_point_row.add_child(mid_point_slider)
	_panel.add_child(mid_point_row)

	# Цвет глубин моря — независимый.
	var deep_row := HBoxContainer.new()
	var deep_label := Label.new()
	deep_label.custom_minimum_size = Vector2(280, 0)
	deep_label.add_theme_color_override("font_color", Color(1, 1, 1))
	deep_label.text = "Цвет: Глубины моря"

	var deep_picker := ColorPickerButton.new()
	deep_picker.color = DEFAULT_DEEP_COLOR
	deep_picker.custom_minimum_size = Vector2(80, 24)
	deep_picker.color_changed.connect(func(color: Color) -> void:
		if _depth_material:
			_depth_material.set_shader_parameter("color_deep", color)
	)
	deep_row.add_child(deep_label)
	deep_row.add_child(deep_picker)
	_panel.add_child(deep_row)

	var isobaths_row := HBoxContainer.new()
	var isobaths_check := CheckBox.new()
	isobaths_check.text = "Изобаты"
	isobaths_check.add_theme_color_override("font_color", Color(1, 1, 1))
	isobaths_check.button_pressed = DEFAULT_SHOW_ISOBATHS
	isobaths_check.toggled.connect(func(pressed: bool) -> void:
		if _depth_material:
			_depth_material.set_shader_parameter("show_isobaths", pressed)
	)
	isobaths_row.add_child(isobaths_check)
	isobaths_row.visible = false  # инструмент изобат скрыт из панели по прямой просьбе пользователя 2026-07-11
	_panel.add_child(isobaths_row)

	var isobath_interval_row := HBoxContainer.new()
	var isobath_interval_label := Label.new()
	isobath_interval_label.custom_minimum_size = Vector2(280, 0)
	isobath_interval_label.add_theme_color_override("font_color", Color(1, 1, 1))
	isobath_interval_label.text = "Шаг изобат: %d м" % int(DEFAULT_ISOBATH_INTERVAL_M)
	var isobath_interval_slider := HSlider.new()
	isobath_interval_slider.min_value = 50.0
	isobath_interval_slider.max_value = 2000.0
	isobath_interval_slider.step = 10.0
	isobath_interval_slider.value = DEFAULT_ISOBATH_INTERVAL_M
	isobath_interval_slider.custom_minimum_size = Vector2(220, 0)
	isobath_interval_slider.value_changed.connect(func(value: float) -> void:
		if _depth_material:
			_depth_material.set_shader_parameter("isobath_interval_m", value)
		isobath_interval_label.text = "Шаг изобат: %d м" % int(value)
	)
	isobath_interval_row.add_child(isobath_interval_label)
	isobath_interval_row.add_child(isobath_interval_slider)
	isobath_interval_row.visible = false  # инструмент изобат скрыт из панели по прямой просьбе пользователя 2026-07-11
	_panel.add_child(isobath_interval_row)


func set_active(active: bool) -> void:
	visible = active
	if _panel:
		_panel.visible = active
