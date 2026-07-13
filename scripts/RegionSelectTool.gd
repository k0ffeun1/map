class_name RegionSelectTool
extends Node2D
## Отладочный инструмент выделения прямоугольного региона (lon/lat bbox) —
## по прямой просьбе пользователя 2026-07-13: вместо наведения курсора на
## оба угла и надиктовки координат, тянешь мышью прямоугольник прямо в игре,
## жмёшь "Сохранить", а bbox пишется в JSON, который потом читает Claude и
## подставляет в --region=... у scripts/tools/bake_ocean_v_*.py (или любого
## другого bake-скрипта с тем же аргументом). Тот же приём перевода
## world px <-> lon/lat, что и в MarkTool.gd/generate-скриптах (Web Mercator).
##
## Управление:
##   R          — вкл/выкл инструмент
##   ЛКМ+тяни    — нарисовать прямоугольник (новый drag заменяет старый)
##   Кнопка "Сохранить региона" в панели — пишет bbox в JSON
##   Delete     — очистить текущее выделение

const WORLD_PX := 8192.0
const OUT_REL := "res://scripts/tools/_work/user_region_selection.json"

var active := false
var _camera: Camera2D
var _dragging := false
var _drag_start_world := Vector2.ZERO
var _rect_world := Rect2()  ## пусто (size=0), пока ничего не выделено
var _has_rect := false

var _panel: VBoxContainer
var _status_label: Label
var _bbox_label: Label
var _save_button: Button


func setup(camera: Camera2D, ui_layer: CanvasLayer) -> void:
	_camera = camera
	z_index = 999  # поверх всех тайловых слоёв, как у MarkTool
	_build_panel(ui_layer)
	_load()
	queue_redraw()


func _build_panel(ui_layer: CanvasLayer) -> void:
	_panel = VBoxContainer.new()
	_panel.offset_left = 24.0
	_panel.offset_top = 900.0
	_panel.offset_right = 700.0
	_panel.offset_bottom = 965.0
	ui_layer.add_child(_panel)

	_status_label = Label.new()
	_status_label.add_theme_color_override("font_color", Color(1, 1, 1))
	_status_label.add_theme_font_size_override("font_size", 16)
	_panel.add_child(_status_label)

	_bbox_label = Label.new()
	_bbox_label.add_theme_color_override("font_color", Color(1.0, 0.85, 0.3))
	_bbox_label.add_theme_font_size_override("font_size", 16)
	_panel.add_child(_bbox_label)

	var row := HBoxContainer.new()
	_save_button = Button.new()
	_save_button.text = "Сохранить регион"
	_save_button.pressed.connect(_on_save_pressed)
	row.add_child(_save_button)
	_panel.add_child(row)

	_update_labels()


func _update_labels() -> void:
	if not _panel:
		return
	_panel.visible = active or _has_rect
	_status_label.text = "ВЫДЕЛЕНИЕ РЕГИОНА [%s]   (R вкл/выкл · ЛКМ тяни прямоугольник · Del очистить)" % \
		("ВКЛ" if active else "выкл")
	if _has_rect:
		var lon_lat := _rect_bbox_lonlat()
		_bbox_label.text = "--region=%.4f,%.4f,%.4f,%.4f" % [lon_lat[0], lon_lat[1], lon_lat[2], lon_lat[3]]
	else:
		_bbox_label.text = "Регион не выделен"


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		match event.physical_keycode:
			KEY_R:
				active = not active
				_update_labels()
				get_viewport().set_input_as_handled()
			KEY_DELETE, KEY_BACKSPACE:
				if active:
					_has_rect = false
					_dragging = false
					_update_labels()
					queue_redraw()
					get_viewport().set_input_as_handled()

	if not active or not is_instance_valid(_camera):
		return

	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		if event.pressed:
			_dragging = true
			_drag_start_world = _camera.get_global_mouse_position()
			_rect_world = Rect2(_drag_start_world, Vector2.ZERO)
			_has_rect = false
			get_viewport().set_input_as_handled()
		else:
			if _dragging:
				_dragging = false
				_has_rect = _rect_world.size.length() > 0.001
				_update_labels()
				get_viewport().set_input_as_handled()

	if event is InputEventMouseMotion and _dragging:
		var cur := _camera.get_global_mouse_position()
		_rect_world = Rect2(_drag_start_world, Vector2.ZERO).expand(cur)
		queue_redraw()


func _process(_delta: float) -> void:
	if active or _has_rect or _dragging:
		queue_redraw()


func _draw() -> void:
	if not (_dragging or _has_rect):
		return
	var r := _rect_world
	var color := Color(0.92, 0.18, 0.18, 1.0)
	draw_rect(r, color, false, 3.0)


## Возвращает [lon0, lat0, lon1, lat1] (lon0<lon1, lat0<lat1) — тот же
## порядок, что ожидает --region= у bake_ocean_v_*.py.
func _rect_bbox_lonlat() -> Array:
	var p0 := _world_to_lonlat(_rect_world.position)
	var p1 := _world_to_lonlat(_rect_world.position + _rect_world.size)
	# min()/max() возвращают Variant в GDScript — явный тип float вместо ":="
	# (иначе "type inferred from Variant" считается ошибкой, см. project.godot).
	var lon0: float = min(p0.x, p1.x)
	var lon1: float = max(p0.x, p1.x)
	# Y мировых px растёт на юг -> меньший y = больший lat.
	var lat0: float = min(p0.y, p1.y)
	var lat1: float = max(p0.y, p1.y)
	return [lon0, lat0, lon1, lat1]


func _world_to_lonlat(pos: Vector2) -> Vector2:
	var lon: float = pos.x / WORLD_PX * 360.0 - 180.0
	var n: float = PI - 2.0 * PI * pos.y / WORLD_PX
	var lat: float = rad_to_deg(2.0 * atan(exp(n)) - PI / 2.0)
	return Vector2(lon, lat)


func _out_path() -> String:
	return ProjectSettings.globalize_path(OUT_REL)


func _on_save_pressed() -> void:
	if not _has_rect:
		return
	_save()


func _save() -> void:
	var lon_lat := _rect_bbox_lonlat()
	var data := {
		"region_lonlat": lon_lat,
		"region_arg": "%.4f,%.4f,%.4f,%.4f" % [lon_lat[0], lon_lat[1], lon_lat[2], lon_lat[3]],
		"saved_at": Time.get_datetime_string_from_system(),
	}
	var path := _out_path()
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify(data, "  "))
		f.close()
	_status_label.text = "Сохранено -> %s" % OUT_REL


func _load() -> void:
	var path := _out_path()
	if not FileAccess.file_exists(path):
		return
	var f := FileAccess.open(path, FileAccess.READ)
	if not f:
		return
	var txt := f.get_as_text()
	f.close()
	var parsed = JSON.parse_string(txt)
	if typeof(parsed) != TYPE_DICTIONARY or not parsed.has("region_lonlat"):
		return
	var lon_lat: Array = parsed["region_lonlat"]
	if lon_lat.size() != 4:
		return
	var p0 := _lonlat_to_world(float(lon_lat[0]), float(lon_lat[1]))
	var p1 := _lonlat_to_world(float(lon_lat[2]), float(lon_lat[3]))
	_rect_world = Rect2(p0, Vector2.ZERO).expand(p1)
	_has_rect = true


func _lonlat_to_world(lon: float, lat: float) -> Vector2:
	lat = clampf(lat, -85.05112878, 85.05112878)
	var x: float = (lon + 180.0) / 360.0 * WORLD_PX
	var lat_rad: float = deg_to_rad(lat)
	var y: float = (0.5 - log(tan(PI / 4.0 + lat_rad / 2.0)) / (2.0 * PI)) * WORLD_PX
	return Vector2(x, y)
