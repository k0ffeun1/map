class_name MicrocellMeshPreviewLayer
extends Node2D
## Визуализация этапа 2: атомарная сетка внутри одной провинции.
##
## Это отдельный drawable-слой, а не IrregularCellProvider: он показывает
## ровно одну небольшую сетку (около 600 полигонов) без тайловой задержки и
## без смешивания с итоговыми игровыми клетками. Геометрия и граф соседства
## остаются в JSON и будут входом этапа 3 — конкурентного роста районов.

const CityMarkerScript := preload("res://scripts/ProvinceCityMarkerNode.gd")
const FILL_A := Color(0.16, 0.76, 0.92, 0.14)
const FILL_B := Color(0.12, 0.56, 0.82, 0.11)
const CAPITAL_FILL := Color(1.0, 0.68, 0.16, 0.32)
const INNER_BORDER := Color(0.02, 0.18, 0.29, 0.72)
const PROVINCE_BORDER := Color(1.0, 0.77, 0.24, 1.0)
const CAPITAL_MARKER_FILL := Color(1.0, 0.90, 0.48, 1.0)
const CAPITAL_MARKER_OUTLINE := Color(0.16, 0.08, 0.01, 1.0)

var _camera: Camera2D
var _cells: Array[Dictionary] = []
var _province_rings: Array[PackedVector2Array] = []
var _capital_marker = null
var _stage: Dictionary = {}
var _generation: Dictionary = {}
var _graph: Dictionary = {}
var _validation: Dictionary = {}
var _last_error := ""
var _last_zoom := -1.0


func setup(data_path: String, camera: Camera2D) -> bool:
	_camera = camera
	if not FileAccess.file_exists(data_path):
		return _fail("Не найден файл микросетки: %s" % data_path)
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(data_path))
	if typeof(parsed) != TYPE_DICTIONARY:
		return _fail("Файл микросетки имеет неверный JSON-формат")
	if str(parsed.get("format", "")) != "province_microcell_mesh/v1":
		return _fail("Неподдерживаемый формат микросетки")

	_cells.clear()
	for raw_cell in parsed.get("cells", []):
		var rings := _to_rings(raw_cell.get("rings", []))
		if rings.is_empty():
			continue
		_cells.append({
			"rings": rings,
			"is_capital": bool(raw_cell.get("is_capital_microcell", false)),
			"stripe": _cells.size() % 2,
		})
	if _cells.is_empty():
		return _fail("Микросетка не содержит пригодных ячеек")
	_province_rings = _to_rings(parsed.get("province_rings", []))
	if _province_rings.is_empty():
		return _fail("В микросетке отсутствует контур провинции")

	_stage = parsed.get("stage", {})
	_generation = parsed.get("generation", {})
	_graph = parsed.get("graph", {})
	_validation = parsed.get("validation", {})
	var capital: Dictionary = parsed.get("capital_anchor", {})
	var point: Array = capital.get("point", [])
	if point.size() != 2:
		return _fail("В микросетке отсутствует якорь столицы")
	_setup_capital_marker(Vector2(float(point[0]), float(point[1])), str(capital.get("name", "Ла-Корунья")))
	_last_error = ""
	queue_redraw()
	return true


func set_active(active: bool) -> void:
	visible = active
	if active:
		_last_zoom = -1.0
		queue_redraw()


func get_last_error() -> String:
	return _last_error


func get_stage_title() -> String:
	return "Этап %d — %s" % [int(_stage.get("number", 2)), str(_stage.get("name", "Микроклеточная сетка"))]


func get_summary_lines() -> Array[String]:
	var count := int(_generation.get("result_cell_count", _cells.size()))
	var edge_count := int(_graph.get("edge_count", 0))
	return [
		"Атомарных микроклеток: %d" % count,
		"Связей в графе соседства: %d" % edge_count,
		"Метод: Poisson Disk → Voronoi → обрезка контуром.",
		"Столица закреплена в выделенной золотой микроклетке.",
		"Покрытие без пропусков и перекрытий: %s." % ("да" if bool(_validation.get("coverage_complete", false)) else "нет"),
		"Это материал для роста 4 районов, а не итоговые границы."
	]


func _process(_delta: float) -> void:
	if not visible:
		return
	var zoom := maxf(0.0001, _camera.zoom.x if is_instance_valid(_camera) else 1.0)
	if is_instance_valid(_capital_marker):
		_capital_marker.scale = Vector2.ONE / zoom
	if absf(zoom - _last_zoom) > 0.0001:
		_last_zoom = zoom
		queue_redraw()


func _draw() -> void:
	if _cells.is_empty():
		return
	var zoom := maxf(0.0001, _camera.zoom.x if is_instance_valid(_camera) else 1.0)
	var cell_line_width := 0.72 / zoom
	for cell in _cells:
		var rings: Array = cell["rings"]
		var fill: Color = CAPITAL_FILL if cell["is_capital"] else (FILL_A if cell["stripe"] == 0 else FILL_B)
		# Микроячейки у этапа 2 не имеют дыр, но отрисовываем все кольца как
		# границы на случай переиспользования слоя для другой провинции.
		draw_colored_polygon(rings[0], fill)
		for ring in rings:
			if ring.size() < 2:
				continue
			var closed: PackedVector2Array = ring.duplicate()
			closed.append(ring[0])
			draw_polyline(closed, INNER_BORDER, cell_line_width, true)

	var province_line_width := 2.6 / zoom
	for ring in _province_rings:
		if ring.size() < 2:
			continue
		var closed: PackedVector2Array = ring.duplicate()
		closed.append(ring[0])
		draw_polyline(closed, PROVINCE_BORDER, province_line_width, true)


func _setup_capital_marker(position: Vector2, city_name: String) -> void:
	if is_instance_valid(_capital_marker):
		_capital_marker.queue_free()
	_capital_marker = CityMarkerScript.new()
	_capital_marker.position = position
	_capital_marker.fill_color = CAPITAL_MARKER_FILL
	_capital_marker.outline_color = CAPITAL_MARKER_OUTLINE
	_capital_marker.highlight_color = Color(1.0, 1.0, 1.0, 0.96)
	_capital_marker.label_fill_color = CAPITAL_MARKER_FILL
	_capital_marker.label_outline_color = CAPITAL_MARKER_OUTLINE
	_capital_marker.label_outline_width = 2
	_capital_marker.setup("Столица — %s" % city_name)
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
	push_warning("MicrocellMeshPreviewLayer: %s" % message)
	return false
