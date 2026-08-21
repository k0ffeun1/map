class_name SubdivisionContractOverlay
extends Node2D
## Видимый первый этап пайплайна деления провинции.
##
## Это не генератор и не слой готовых клеток: он показывает исходную форму
## провинции и привязку столицы, для которых закреплён контракт. Благодаря
## этому следующий этап (микроклеточная сетка) можно сравнивать с понятной
## отправной точкой прямо в игре.

const FILL_COLOR := Color(1.0, 0.69, 0.18, 0.16)
const OUTLINE_COLOR := Color(1.0, 0.78, 0.30, 0.98)
const CAPITAL_FILL_COLOR := Color(1.0, 0.93, 0.58, 1.0)
const CAPITAL_OUTLINE_COLOR := Color(0.18, 0.10, 0.02, 1.0)
const CityMarkerScript := preload("res://scripts/ProvinceCityMarkerNode.gd")

var _camera: Camera2D
var _contract: Dictionary = {}
var _rings: Array[PackedVector2Array] = []
var _capital_anchor := Vector2.ZERO
var _capital_marker = null
var _last_error := ""


func setup(contract_path: String, camera: Camera2D) -> bool:
	_camera = camera
	if not FileAccess.file_exists(contract_path):
		return _fail("Не найден контракт: %s" % contract_path)
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(contract_path))
	if typeof(parsed) != TYPE_DICTIONARY:
		return _fail("Контракт имеет неверный JSON-формат")
	_contract = parsed
	if str(_contract.get("format", "")) != "province_subdivision_contract/v1":
		return _fail("Неподдерживаемый формат контракта")

	var province: Dictionary = _contract.get("province", {})
	var capital: Dictionary = province.get("capital_anchor", {})
	var point: Array = capital.get("point", [])
	if point.size() != 2:
		return _fail("В контракте нет координат якоря столицы")
	_capital_anchor = Vector2(float(point[0]), float(point[1]))

	var geometry_path := str(province.get("geometry_path", ""))
	if geometry_path.is_empty() or not FileAccess.file_exists(geometry_path):
		return _fail("Не найден источник геометрии провинции: %s" % geometry_path)
	var geometry: Variant = JSON.parse_string(FileAccess.get_file_as_string(geometry_path))
	if typeof(geometry) != TYPE_DICTIONARY:
		return _fail("Источник геометрии имеет неверный JSON-формат")
	var province_id := str(province.get("id", ""))
	for raw_entry in geometry.get("provinces", []):
		if str(raw_entry.get("id", "")) != province_id:
			continue
		_rings = _to_rings(raw_entry.get("rings", []))
		if _rings.is_empty():
			return _fail("У провинции нет пригодного контура")
		_setup_capital_marker(capital)
		_last_error = ""
		queue_redraw()
		return true
	return _fail("Провинция %s не найдена в источнике геометрии" % province_id)


func set_active(active: bool) -> void:
	visible = active
	if active:
		queue_redraw()


func get_last_error() -> String:
	return _last_error


func get_stage_title() -> String:
	var stage: Dictionary = _contract.get("stage", {})
	return "Этап %d — %s" % [int(stage.get("number", 1)), str(stage.get("name", "Контракт деления"))]


func get_summary_lines() -> Array[String]:
	var province: Dictionary = _contract.get("province", {})
	var generation: Dictionary = _contract.get("generation", {})
	var constraints: Dictionary = _contract.get("constraints", {})
	var topology: Dictionary = constraints.get("topology", {})
	var coast: Dictionary = constraints.get("coast", {})
	var capital: Dictionary = province.get("capital_anchor", {})
	var limits: Array = constraints.get("area_ratio_limits", [])
	var area_line := "Площадь клетки: цель %.0f км²" % float(generation.get("target_cell_area_km2", 0.0))
	if limits.size() == 2:
		area_line += " (%.0f–%.0f%%)" % [float(limits[0]) * 100.0, float(limits[1]) * 100.0]
	return [
		"Провинция: %s" % str(province.get("name", "")),
		"Цель: %d игровых клетки" % int(generation.get("target_cell_count", 0)),
		area_line,
		"Якорь столицы: %s" % str(capital.get("name", "")),
		"Без анклавов и разрывов: %s" % ("да" if bool(topology.get("allow_enclaves", true)) == false and bool(topology.get("every_cell_connected", false)) else "нет"),
		"Отступ внутренних границ от моря: %.1f км" % float(coast.get("interior_generation_offset_km", 0.0)),
		"Этот слой: исходный контур и столица; он не меняет остальные включённые слои."
	]


func _process(_delta: float) -> void:
	if visible:
		if is_instance_valid(_capital_marker):
			var zoom := maxf(0.0001, _camera.zoom.x if is_instance_valid(_camera) else 1.0)
			_capital_marker.scale = Vector2.ONE / zoom
		queue_redraw()


func _draw() -> void:
	if _rings.is_empty():
		return
	var zoom := maxf(0.0001, _camera.zoom.x if is_instance_valid(_camera) else 1.0)
	var line_width := 2.6 / zoom

	# У Ла-Коруньи нет внутренних дыр; для будущих контрактов контуры всё
	# равно рисуются все, а заливка относится к внешнему контуру.
	draw_colored_polygon(_rings[0], FILL_COLOR)
	for ring in _rings:
		if ring.size() < 2:
			continue
		var line := ring.duplicate()
		line.append(ring[0])
		draw_polyline(line, OUTLINE_COLOR, line_width, true)



func _setup_capital_marker(capital: Dictionary) -> void:
	if is_instance_valid(_capital_marker):
		_capital_marker.queue_free()
	_capital_marker = CityMarkerScript.new()
	_capital_marker.position = _capital_anchor
	_capital_marker.fill_color = CAPITAL_FILL_COLOR
	_capital_marker.outline_color = CAPITAL_OUTLINE_COLOR
	_capital_marker.highlight_color = Color(1.0, 1.0, 1.0, 0.96)
	_capital_marker.label_fill_color = CAPITAL_FILL_COLOR
	_capital_marker.label_outline_color = CAPITAL_OUTLINE_COLOR
	_capital_marker.label_outline_width = 2
	_capital_marker.setup("Столица — %s" % str(capital.get("name", "")))
	add_child(_capital_marker)


func _to_rings(raw_rings: Array) -> Array[PackedVector2Array]:
	var result: Array[PackedVector2Array] = []
	for raw_ring in raw_rings:
		if not raw_ring is Array or raw_ring.size() < 3:
			continue
		var ring := PackedVector2Array()
		for raw_point in raw_ring:
			if raw_point is Array and raw_point.size() >= 2:
				ring.append(Vector2(float(raw_point[0]), float(raw_point[1])))
		if ring.size() >= 3:
			result.append(ring)
	return result


func _fail(message: String) -> bool:
	_last_error = message
	push_warning("SubdivisionContractOverlay: %s" % message)
	return false
