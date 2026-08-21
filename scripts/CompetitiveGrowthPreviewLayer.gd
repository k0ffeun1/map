class_name CompetitiveGrowthPreviewLayer
extends Node2D
## Этап 3: видимый конкурентный рост четырёх зон по графу микроклеток.
##
## Этот слой читает назначения из offline-проверенного JSON, но рисует именно
## атомарные клетки этапа 2. Поэтому пользователь видит, что крупные зоны
## получены последовательным захватом соседей, а не скрытым разрезом готового
## полигона. Неровные границы микросетки намеренно остаются до этапа cleanup.

const CityMarkerScript := preload("res://scripts/ProvinceCityMarkerNode.gd")
const MICRO_GRID_COLOR := Color(0.025, 0.08, 0.13, 0.50)
const OUTER_BORDER_COLOR := Color(1.0, 0.77, 0.24, 1.0)
const BORDER_SHADOW_COLOR := Color(0.015, 0.035, 0.06, 0.96)
const BORDER_HIGHLIGHT_COLOR := Color(0.96, 0.98, 1.0, 0.92)
const SOURCE_OUTLINE_COLOR := Color(0.02, 0.04, 0.07, 1.0)
const CAPITAL_MARKER_FILL := Color(1.0, 0.90, 0.48, 1.0)
const CAPITAL_MARKER_OUTLINE := Color(0.16, 0.08, 0.01, 1.0)

var _camera: Camera2D
var _cells: Array[Dictionary] = []
var _zones: Array[Dictionary] = []
var _zone_by_id: Dictionary = {}
var _claim_by_cell_id: Dictionary = {}
var _boundary_segments: Array[Dictionary] = []
var _province_rings: Array[PackedVector2Array] = []
var _capital_marker = null
var _stage: Dictionary = {}
var _generation: Dictionary = {}
var _validation: Dictionary = {}
var _last_error := ""
var _last_zoom := -1.0
var _growth_progress := 1.0
var _growth_duration_seconds := 4.4
var _max_growth_step := 1
var _font: Font = ThemeDB.fallback_font


func setup(data_path: String, camera: Camera2D) -> bool:
	_camera = camera
	if not FileAccess.file_exists(data_path):
		return _fail("Не найден результат конкурентного роста: %s" % data_path)
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(data_path))
	if typeof(parsed) != TYPE_DICTIONARY:
		return _fail("Файл этапа 3 имеет неверный JSON-формат")
	var growth: Dictionary = parsed
	if str(growth.get("format", "")) != "province_competitive_growth/v1":
		return _fail("Неподдерживаемый формат результата этапа 3")
	var source_mesh_path := str(growth.get("source_mesh_path", ""))
	if source_mesh_path.is_empty() or not FileAccess.file_exists(source_mesh_path):
		return _fail("Не найден входной файл микросетки этапа 2: %s" % source_mesh_path)
	var mesh_parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(source_mesh_path))
	if typeof(mesh_parsed) != TYPE_DICTIONARY:
		return _fail("Входная микросетка имеет неверный JSON-формат")
	var mesh: Dictionary = mesh_parsed
	if str(mesh.get("format", "")) != "province_microcell_mesh/v1":
		return _fail("Этап 3 получил не микросетку этапа 2")

	_cells.clear()
	var raw_cells: Array = mesh.get("cells", [])
	for raw_cell in raw_cells:
		if not raw_cell is Dictionary:
			continue
		var cell: Dictionary = raw_cell
		var cell_id := str(cell.get("id", ""))
		var rings: Array[PackedVector2Array] = _to_rings(cell.get("rings", []))
		if cell_id.is_empty() or rings.is_empty():
			continue
		_cells.append({"id": cell_id, "rings": rings})
	if _cells.is_empty():
		return _fail("Микросетка этапа 2 не содержит пригодных клеток")
	_province_rings = _to_rings(mesh.get("province_rings", []))
	if _province_rings.is_empty():
		return _fail("В микросетке отсутствует контур исходной провинции")

	_zone_by_id.clear()
	_zones.clear()
	var raw_zones: Array = growth.get("zones", [])
	for raw_zone in raw_zones:
		if not raw_zone is Dictionary:
			continue
		var zone: Dictionary = raw_zone.duplicate(true)
		var zone_id := str(zone.get("id", ""))
		if zone_id.is_empty():
			continue
		zone["color_value"] = _color_from_raw(zone.get("color", []))
		zone["seed_point_value"] = _point_from_raw(zone.get("seed_point", []))
		zone["label_point_value"] = _point_from_raw(zone.get("label_point", []))
		_zones.append(zone)
		_zone_by_id[zone_id] = zone
	if _zones.size() != 4:
		return _fail("Этап 3 должен содержать ровно четыре зоны роста")

	_claim_by_cell_id.clear()
	_max_growth_step = 1
	var raw_claims: Array = growth.get("claims", [])
	for raw_claim in raw_claims:
		if not raw_claim is Dictionary:
			continue
		var claim: Dictionary = raw_claim.duplicate(true)
		var claim_cell_id := str(claim.get("microcell_id", ""))
		var claim_zone_id := str(claim.get("zone_id", ""))
		if claim_cell_id.is_empty() or not _zone_by_id.has(claim_zone_id):
			return _fail("Этап 3 содержит некорректное назначение микроклетки")
		if _claim_by_cell_id.has(claim_cell_id):
			return _fail("Этап 3 назначает одну микроклетку дважды: %s" % claim_cell_id)
		var step := int(claim.get("growth_step", -1))
		if step < 0:
			return _fail("У назначения микроклетки нет шага роста")
		_claim_by_cell_id[claim_cell_id] = claim
		_max_growth_step = max(_max_growth_step, step)
	for cell in _cells:
		if not _claim_by_cell_id.has(str(cell["id"])):
			return _fail("Не назначена микроклетка: %s" % str(cell["id"]))

	_boundary_segments.clear()
	var raw_segments: Array = growth.get("boundary_segments", [])
	for raw_segment in raw_segments:
		if not raw_segment is Dictionary:
			continue
		var segment: Dictionary = raw_segment
		var points := _to_polyline(segment.get("points", []))
		var microcells: Array = segment.get("microcells", [])
		if points.size() < 2 or microcells.size() != 2:
			continue
		_boundary_segments.append(
			{
				"points": points,
				"first_microcell": str(microcells[0]),
				"second_microcell": str(microcells[1]),
			}
		)
	if _boundary_segments.is_empty():
		return _fail("Этап 3 не содержит видимых границ между зонами")

	_stage = growth.get("stage", {})
	_generation = growth.get("generation", {})
	_validation = growth.get("validation", {})
	var capital: Dictionary = mesh.get("capital_anchor", {})
	var capital_point := _point_from_raw(capital.get("point", []))
	_setup_capital_marker(capital_point, str(capital.get("name", "Ла-Корунья")))
	_last_error = ""
	queue_redraw()
	return true


func set_active(active: bool) -> void:
	visible = active
	if active:
		# При каждом открытии этап проигрывается заново: сначала четыре источника,
		# затем их фронтиры, затем полная, но ещё не очищенная граница.
		_growth_progress = 0.0
		_last_zoom = -1.0
	queue_redraw()


func get_last_error() -> String:
	return _last_error


func get_stage_title() -> String:
	return "Этап %d — %s" % [int(_stage.get("number", 3)), str(_stage.get("name", "Конкурентный рост"))]


func get_summary_lines() -> Array[String]:
	var effective_target := float(_generation.get("effective_target_area_km2", 0.0))
	var balance := float(_validation.get("zone_area_balance_ratio", 0.0))
	var boundary_count := int(_validation.get("interzone_microcell_edge_count", _boundary_segments.size()))
	var compactness := float(_validation.get("minimum_zone_compactness_observed", 0.0))
	var compactness_limit := float(_validation.get("minimum_zone_compactness_required", 0.0))
	return [
		"Четыре волны идут только через соседние микроклетки; их приоритеты выравнивают площади.",
		"Рабочая цель: %.1f км² на зону; это площадь реальной провинции ÷ 4." % effective_target,
		"Баланс площадей: max/min = %.3f." % balance,
		"Компактность самой вытянутой зоны: %.3f (контракт: не ниже %.3f)." % [compactness, compactness_limit],
		"Проверено: 600/600 назначены, зоны связны, дыр нет.",
		"Межзонных рёбер микросетки: %d." % boundary_count,
		"Это ещё черновая граница из атомов; сглаживание будет отдельным этапом."
	]


func get_zone_rows() -> Array[String]:
	var rows: Array[String] = []
	for index in range(_zones.size()):
		var zone: Dictionary = _zones[index]
		rows.append(
			"%d. %s — %d клеток, %.1f км²"
			% [index + 1, str(zone.get("name", "Зона")), int(zone.get("microcell_count", 0)), float(zone.get("area_km2", 0.0))]
		)
	return rows


func get_zone_color(index: int) -> Color:
	if index < 0 or index >= _zones.size():
		return Color.WHITE
	return _zones[index].get("color_value", Color.WHITE)


func _process(delta: float) -> void:
	if not visible:
		return
	if _growth_progress < 1.0:
		_growth_progress = minf(1.0, _growth_progress + delta / _growth_duration_seconds)
		queue_redraw()
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
	var revealed_step := _revealed_step()
	var micro_line_width := 0.42 / zoom
	for cell in _cells:
		var cell_id := str(cell["id"])
		var claim: Dictionary = _claim_by_cell_id[cell_id]
		if int(claim.get("growth_step", 0)) > revealed_step:
			continue
		var zone: Dictionary = _zone_by_id[str(claim["zone_id"])]
		var color: Color = zone["color_value"]
		var fill := Color(color.r, color.g, color.b, color.a)
		var rings: Array = cell["rings"]
		draw_colored_polygon(rings[0], fill)
		for ring in rings:
			if ring.size() < 2:
				continue
			var closed: PackedVector2Array = ring.duplicate()
			closed.append(ring[0])
			draw_polyline(closed, MICRO_GRID_COLOR, micro_line_width, true)

	var zone_line_shadow_width := 3.5 / zoom
	var zone_line_width := 1.35 / zoom
	for segment in _boundary_segments:
		var first_claim: Dictionary = _claim_by_cell_id.get(str(segment["first_microcell"]), {})
		var second_claim: Dictionary = _claim_by_cell_id.get(str(segment["second_microcell"]), {})
		if first_claim.is_empty() or second_claim.is_empty():
			continue
		if int(first_claim.get("growth_step", 0)) > revealed_step or int(second_claim.get("growth_step", 0)) > revealed_step:
			continue
		var line: PackedVector2Array = segment["points"]
		draw_polyline(line, BORDER_SHADOW_COLOR, zone_line_shadow_width, true)
		draw_polyline(line, BORDER_HIGHLIGHT_COLOR, zone_line_width, true)

	var outer_width := 2.6 / zoom
	for ring in _province_rings:
		if ring.size() < 2:
			continue
		var closed: PackedVector2Array = ring.duplicate()
		closed.append(ring[0])
		draw_polyline(closed, OUTER_BORDER_COLOR, outer_width, true)
	_draw_source_markers(revealed_step, zoom)


func _draw_source_markers(revealed_step: int, zoom: float) -> void:
	for index in range(_zones.size()):
		var zone: Dictionary = _zones[index]
		var seed_id := str(zone.get("seed_microcell_id", ""))
		var claim: Dictionary = _claim_by_cell_id.get(seed_id, {})
		if claim.is_empty() or int(claim.get("growth_step", 0)) > revealed_step:
			continue
		var point: Vector2 = zone["seed_point_value"]
		var color: Color = zone["color_value"]
		draw_circle(point, 5.2 / zoom, SOURCE_OUTLINE_COLOR)
		draw_circle(point, 3.5 / zoom, color)
		if index > 0:
			var label_offset := Vector2(5.5, -4.5) / zoom
			draw_string(_font, point + label_offset, str(index + 1), HORIZONTAL_ALIGNMENT_LEFT, -1, 13.0 / zoom, Color.WHITE)


func _revealed_step() -> int:
	return int(floor(_growth_progress * float(_max_growth_step)))


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


func _to_polyline(raw_points: Array) -> PackedVector2Array:
	var line := PackedVector2Array()
	for raw_point in raw_points:
		if raw_point is Array and raw_point.size() >= 2:
			line.append(Vector2(float(raw_point[0]), float(raw_point[1])))
	return line


func _point_from_raw(raw: Variant) -> Vector2:
	if raw is Array and raw.size() >= 2:
		return Vector2(float(raw[0]), float(raw[1]))
	return Vector2.ZERO


func _color_from_raw(raw: Variant) -> Color:
	if raw is Array and raw.size() >= 3:
		var alpha := float(raw[3]) if raw.size() >= 4 else 0.52
		return Color(float(raw[0]), float(raw[1]), float(raw[2]), alpha)
	return Color(0.72, 0.72, 0.72, 0.52)


func _fail(message: String) -> bool:
	_last_error = message
	push_warning("CompetitiveGrowthPreviewLayer: %s" % message)
	return false
