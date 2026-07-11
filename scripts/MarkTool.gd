class_name MarkTool
extends Node2D
## Отладочный инструмент разметки карты для правки офлайн-генераторов геометрии
## (scripts/tools/build_*.py — изначально писался для build_land_cells.py,
## с тех пор удалённого, см. done.md/TODO.md, но приём общий для любого из них).
##
## Вместо "опиши словами / покажи скриншот с рамкой" — кликаешь прямо в
## игре, координаты кликов переводятся в lon/lat (та же формула Меркатора,
## что и в генераторах geo-слоёв) и пишутся в JSON, который потом читает Claude
## и превращает в конкретные правки кода (зоны-исключения, ручные
## include/exclude списки островов и т.п.).
##
## Режимы (Tab переключает по кругу):
##   EXCLUDE  (красный)  — "этот остров/кусок суши сделать морем (снести)"
##   PROTECT  (зелёный)  — "этот остров/кусок суши НИКОГДА не сносить"
##   BUG      (жёлтый)   — "здесь должна быть суша, а клетки нет (баг рендера)"
##
## Метка — это ТОЧКА (клик "выбирает" целый остров/кусок суши в исходных
## Natural Earth данных, как выделение фичи, а не пиксельная кисть) —
## этого достаточно, т.к. вся суша уже хранится как векторные полигоны:
## одна точка внутри контура однозначно указывает на нужный кусок.
##
## Управление:
##   M          — вкл/выкл режим разметки
##   Tab        — сменить режим текущей метки (EXCLUDE/PROTECT/BUG)
##   ЛКМ        — поставить метку текущего режима в точке курсора
##   Z          — отменить последнюю метку
##   Delete     — очистить все метки (с подтверждением в статусе)

const WORLD_PX := 8192.0
const OUT_REL := "res://scripts/tools/_work/user_marks.json"
const SCREEN_RADIUS_PX := 6.0  ## Радиус кружка-метки в ЭКРАННЫХ px (не мировых) — не должен "тонуть" при отдалении и не должен разрастаться при приближении.

enum Mode { EXCLUDE, PROTECT, BUG }
const MODE_NAMES := {
	Mode.EXCLUDE: "EXCLUDE (снести -> море)",
	Mode.PROTECT: "PROTECT (никогда не сносить)",
	Mode.BUG: "BUG (нет клетки, а должна быть)",
}
const MODE_COLORS := {
	Mode.EXCLUDE: Color(0.92, 0.18, 0.18),
	Mode.PROTECT: Color(0.20, 0.85, 0.25),
	Mode.BUG: Color(0.95, 0.85, 0.15),
}
const MODE_NAME_TO_ENUM := {
	"EXCLUDE": Mode.EXCLUDE,
	"PROTECT": Mode.PROTECT,
	"BUG": Mode.BUG,
}

var active := false
var mode: int = Mode.EXCLUDE
var marks: Array = []  ## [{lon, lat, mode(int)}]

var _camera: Camera2D
var _mode_label: Label


func setup(camera: Camera2D, ui_layer: CanvasLayer) -> void:
	_camera = camera
	z_index = 999  # поверх всех тайловых слоёв
	_build_label(ui_layer)
	_load()
	queue_redraw()


func _build_label(ui_layer: CanvasLayer) -> void:
	_mode_label = Label.new()
	_mode_label.add_theme_color_override("font_color", Color(1, 1, 1))
	_mode_label.add_theme_font_size_override("font_size", 18)
	_mode_label.offset_left = 24.0
	_mode_label.offset_top = 970.0
	_mode_label.offset_right = 1400.0
	_mode_label.offset_bottom = 1010.0
	ui_layer.add_child(_mode_label)
	_update_label()


func _update_label() -> void:
	if not _mode_label:
		return
	if active:
		_mode_label.text = "РАЗМЕТКА [%s]   меток: %d   (M выкл · Tab режим · ЛКМ метка · Z отмена · Del очистить)" % [
			MODE_NAMES[mode], marks.size()]
		_mode_label.visible = true
	else:
		_mode_label.visible = marks.size() > 0
		if _mode_label.visible:
			_mode_label.text = "Меток на карте: %d   (M — включить разметку)" % marks.size()


func _unhandled_input(event: InputEvent) -> void:
	# physical_keycode, а не keycode — тот же принцип, что для WASD в
	# CameraController.gd: keycode зависит от текущей раскладки (Tab не
	# зависит от букв, но M/Z — вполне обычные буквы, и на кириллице
	# логический код будет другим; physical_keycode всегда "физическая
	# позиция клавиши", независимо от раскладки).
	if event is InputEventKey and event.pressed and not event.echo:
		match event.physical_keycode:
			KEY_M:
				active = not active
				_update_label()
				get_viewport().set_input_as_handled()
			KEY_TAB:
				if active:
					mode = (mode + 1) % 3
					_update_label()
					get_viewport().set_input_as_handled()
			KEY_Z:
				if active and marks.size() > 0:
					marks.pop_back()
					_save()
					_update_label()
					queue_redraw()
			KEY_DELETE, KEY_BACKSPACE:
				if active:
					marks.clear()
					_save()
					_update_label()
					queue_redraw()

	if active and event is InputEventMouseButton and event.pressed \
			and event.button_index == MOUSE_BUTTON_LEFT and is_instance_valid(_camera):
		_add_mark(_camera.get_global_mouse_position())
		get_viewport().set_input_as_handled()


func _add_mark(world: Vector2) -> void:
	var lonlat := _world_to_lonlat(world)
	marks.append({"lon": lonlat.x, "lat": lonlat.y, "mode": mode})
	_save()
	_update_label()
	queue_redraw()


func _process(_delta: float) -> void:
	# Радиус меток завязан на текущий зум камеры (чтобы быть constant-size на
	# экране) -> перерисовываем каждый кадр, пока есть метки или ведётся разметка.
	if active or marks.size() > 0:
		queue_redraw()


func _draw() -> void:
	if not is_instance_valid(_camera) or _camera.zoom.x <= 0.0:
		return
	var r: float = SCREEN_RADIUS_PX / _camera.zoom.x
	for m in marks:
		var world := _lonlat_to_world(m["lon"], m["lat"])
		var color: Color = MODE_COLORS[int(m["mode"])]
		draw_circle(world, r, color)
		draw_arc(world, r, 0.0, TAU, 20, Color(0, 0, 0, 0.8), max(1.0, r * 0.15))


func _world_to_lonlat(pos: Vector2) -> Vector2:
	var lon: float = pos.x / WORLD_PX * 360.0 - 180.0
	var n: float = PI - 2.0 * PI * pos.y / WORLD_PX
	var lat: float = rad_to_deg(2.0 * atan(exp(n)) - PI / 2.0)
	return Vector2(lon, lat)


func _lonlat_to_world(lon: float, lat: float) -> Vector2:
	lat = clampf(lat, -85.05112878, 85.05112878)
	var x: float = (lon + 180.0) / 360.0 * WORLD_PX
	var lat_rad: float = deg_to_rad(lat)
	var y: float = (0.5 - log(tan(PI / 4.0 + lat_rad / 2.0)) / (2.0 * PI)) * WORLD_PX
	return Vector2(x, y)


func _out_path() -> String:
	return ProjectSettings.globalize_path(OUT_REL)


func _save() -> void:
	var arr := []
	for m in marks:
		arr.append({
			"lon": m["lon"],
			"lat": m["lat"],
			"mode": Mode.keys()[int(m["mode"])],
		})
	var path := _out_path()
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify(arr, "  "))
		f.close()


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
	if typeof(parsed) != TYPE_ARRAY:
		return
	for entry in parsed:
		if typeof(entry) != TYPE_DICTIONARY:
			continue
		var mode_name: String = entry.get("mode", "EXCLUDE")
		marks.append({
			"lon": float(entry.get("lon", 0.0)),
			"lat": float(entry.get("lat", 0.0)),
			"mode": MODE_NAME_TO_ENUM.get(mode_name, Mode.EXCLUDE),
		})
