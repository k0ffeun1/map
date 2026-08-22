extends Node2D
## X — ручной прототип суперрегиона «Нижние земли».
##
## ВАЖНО: этот слой НЕ читает provinces/admin/regions/F6/Stage6 и вообще
## никакие геоданные. Контур нарисован вручную как самостоятельная авторская
## форма в той же world-px системе координат, в которой отображается слой Z.
## Z нужен только как визуальная подложка/ориентир на карте.
##
## Это специально экспериментальный слой: проверяем, как должна выглядеть
## география уровня «суперрегион», если рисовать её вручную, а не наследовать
## административные границы нижних уровней.

const SUPERREGION_ID := "superregion:lower_countries"
const SUPERREGION_NAME := "Нижние земли"

const FILL_NORMAL := Color(0.86, 0.58, 0.20, 0.74)
const FILL_SELECTED := Color(1.00, 0.76, 0.25, 0.92)
const BORDER_NORMAL := Color(0.20, 0.12, 0.05, 0.95)
const BORDER_SELECTED := Color(1.00, 0.95, 0.72, 1.00)

# Контур полностью задан вручную. Это НЕ объединение Нидерландов/Бельгии/
# Люксембурга из какого-либо слоя. Форма лишь авторски размещена там, где
# на Z визуально находятся Нижние земли.
const REGION_POINTS := [
	Vector2(4202.95, 2666.67),
	Vector2(4205.68, 2661.74),
	Vector2(4212.05, 2656.41),
	Vector2(4222.29, 2652.60),
	Vector2(4234.81, 2650.69),
	Vector2(4246.19, 2652.22),
	Vector2(4257.56, 2655.27),
	Vector2(4258.70, 2664.77),
	Vector2(4256.43, 2675.35),
	Vector2(4255.29, 2685.49),
	Vector2(4257.11, 2696.68),
	Vector2(4253.47, 2705.94),
	Vector2(4250.28, 2712.58),
	Vector2(4245.05, 2720.66),
	Vector2(4240.50, 2729.79),
	Vector2(4237.08, 2737.06),
	Vector2(4235.95, 2745.39),
	Vector2(4234.81, 2752.59),
	Vector2(4237.54, 2762.27),
	Vector2(4242.09, 2772.96),
	Vector2(4244.37, 2782.52),
	Vector2(4243.91, 2794.13),
	Vector2(4238.90, 2796.58),
	Vector2(4232.53, 2798.33),
	Vector2(4226.16, 2797.28),
	Vector2(4220.02, 2793.08),
	Vector2(4214.33, 2788.16),
	Vector2(4206.36, 2784.63),
	Vector2(4198.40, 2780.75),
	Vector2(4190.44, 2777.57),
	Vector2(4183.61, 2774.02),
	Vector2(4177.46, 2767.62),
	Vector2(4172.23, 2759.76),
	Vector2(4166.54, 2753.31),
	Vector2(4159.26, 2748.99),
	Vector2(4154.03, 2741.77),
	Vector2(4156.98, 2735.98),
	Vector2(4163.13, 2732.34),
	Vector2(4168.36, 2727.97),
	Vector2(4172.91, 2723.59),
	Vector2(4176.10, 2718.09),
	Vector2(4180.20, 2713.32),
	Vector2(4185.20, 2708.90),
	Vector2(4188.84, 2702.24),
	Vector2(4192.03, 2695.56),
	Vector2(4194.99, 2688.10),
	Vector2(4198.86, 2680.99),
	Vector2(4202.04, 2673.84),
]

var _polygon := PackedVector2Array()
var _outline := PackedVector2Array()
var _selected := false
var _viewer: Node


func _ready() -> void:
	visible = false
	z_index = 252
	set_process_input(true)

	for point in REGION_POINTS:
		_polygon.append(point)
	_outline = _polygon.duplicate()
	if not _outline.is_empty():
		_outline.append(_outline[0])

	call_deferred("_bind_viewer")
	queue_redraw()


func _bind_viewer() -> void:
	_viewer = get_parent()


func _input(event: InputEvent) -> void:
	var key := event as InputEventKey
	if key != null and key.pressed and not key.echo:
		if key.physical_keycode == KEY_X or key.keycode == KEY_X:
			visible = not visible
			_selected = false
			queue_redraw()
			_show_info("X — суперрегион «%s» %s" % [SUPERREGION_NAME, "показан" if visible else "скрыт"])
			get_viewport().set_input_as_handled()
			return

	if not visible:
		return

	var mouse := event as InputEventMouseButton
	if mouse == null or not mouse.pressed or mouse.button_index != MOUSE_BUTTON_LEFT:
		return

	var point := get_global_mouse_position()
	var hit := Geometry2D.is_point_in_polygon(point, _polygon)
	if hit:
		_selected = true
		queue_redraw()
		_show_info("Выбрано: %s [%s] — ручной суперрегион слоя X" % [SUPERREGION_NAME, SUPERREGION_ID])
		get_viewport().set_input_as_handled()
	elif _selected:
		_selected = false
		queue_redraw()


func _draw() -> void:
	if _polygon.size() < 3:
		return
	var fill := FILL_SELECTED if _selected else FILL_NORMAL
	var border := BORDER_SELECTED if _selected else BORDER_NORMAL
	draw_colored_polygon(_polygon, fill)
	if _outline.size() >= 2:
		# Тонкая экранная линия: не раздувается при приближении камеры.
		draw_polyline(_outline, border, -1.0, true)


func get_superregion_id_at(world_pos: Vector2) -> String:
	return SUPERREGION_ID if Geometry2D.is_point_in_polygon(world_pos, _polygon) else ""


func _show_info(message: String) -> void:
	if is_instance_valid(_viewer) and _viewer.has_method("_show_top_info"):
		_viewer.call("_show_top_info", message)
	else:
		print(message)
