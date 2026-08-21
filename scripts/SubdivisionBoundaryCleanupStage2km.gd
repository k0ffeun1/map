extends "res://scripts/SubdivisionBoundaryCleanupStage.gd"
## Этап 4 с тем же игровым берегом, который уже использует слой 4.
##
## В build_provinces_iberia_selection_2km.py провинции для выделения слоя 4
## обрезаются на GAME_WATER_LAND_MARGIN_KM = 2.0 км от естественного берега.
## Здесь НЕ вычисляем второй независимый буфер: читаем уже готовую геометрию
## assets/provinces_iberia_selection_2km.json, чтобы Stage 4 и слой 4 имели
## буквально один и тот же внешний контур.
##
## K остаётся источником владения/топологии. Меняется только preview-геометрия:
## - внешний контур Ла-Коруньи берётся из gameplay coast слоя 4;
## - ВСЯ сеть внутренних границ клипуется по этому gameplay-полигону, а не
##   только её крайние точки: любые куски внутри удалённой 2-км полосы исчезают;
## - если одна политическая цепь несколько раз входит/выходит из береговой
##   полосы, она корректно разбивается на несколько внутренних компонентов;
## - внутренние junction-точки и владение 600 микроклетками не меняются.

const GAMEPLAY_COAST_PATH := "res://assets/provinces_iberia_selection_2km.json"
const GAMEPLAY_PROVINCE_ID := "spain__la_coru_a"
const GAMEPLAY_COAST_RULE_KM := 2.0
const COAST_BOUNDARY_EPSILON := 0.0008
const CLIP_T_EPSILON := 0.000001

# Каждый элемент — Array[PackedVector2Array]: [outer, hole1, hole2, ...].
# Отдельные MultiPolygon-части слоя 4 хранятся отдельными cells с суффиксом
# __selection_part_N; здесь они собираются обратно в одну gameplay-область.
var _gameplay_polygons: Array = []
var _coast_inset_endpoint_count := 0
var _coast_fallback_chain_count := 0
var _coast_removed_component_count := 0


func _ready() -> void:
	super._ready()
	if not _last_error.is_empty():
		return
	if not _load_layer4_gameplay_coast():
		_refresh_coast_summary()
		return
	if not _apply_gameplay_coast_to_chains():
		_refresh_coast_summary()
		return
	_refresh_coast_summary()
	queue_redraw()


func set_active(active: bool) -> void:
	super.set_active(active)
	if active and _last_error.is_empty():
		_show_top_info("Этап 4: политические границы K + игровой берег слоя 4 (2 км внутрь суши)")


func get_gameplay_coast_margin_km() -> float:
	return GAMEPLAY_COAST_RULE_KM


func get_gameplay_coast_source_path() -> String:
	return GAMEPLAY_COAST_PATH


func get_coast_inset_endpoint_count() -> int:
	return _coast_inset_endpoint_count


func get_coast_removed_component_count() -> int:
	return _coast_removed_component_count


func _load_layer4_gameplay_coast() -> bool:
	if not FileAccess.file_exists(GAMEPLAY_COAST_PATH):
		return _fail("не найден 2-км gameplay coast слоя 4: %s" % GAMEPLAY_COAST_PATH)
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(GAMEPLAY_COAST_PATH))
	if typeof(parsed) != TYPE_DICTIONARY:
		return _fail("2-км gameplay coast слоя 4 имеет неверный JSON-формат")
	var data: Dictionary = parsed

	_gameplay_polygons.clear()
	var draw_rings: Array[PackedVector2Array] = []
	var part_prefix := GAMEPLAY_PROVINCE_ID + "__selection_part_"
	for raw_cell in data.get("cells", []):
		if not raw_cell is Dictionary:
			continue
		var cell_id := str(raw_cell.get("id", ""))
		if cell_id != GAMEPLAY_PROVINCE_ID and not cell_id.begins_with(part_prefix):
			continue
		var rings := _to_rings(raw_cell.get("rings", []))
		if rings.is_empty():
			continue
		_gameplay_polygons.append(rings)
		for ring in rings:
			draw_rings.append(ring)

	if _gameplay_polygons.is_empty():
		return _fail("в 2-км слое не найдена Ла-Корунья: %s" % GAMEPLAY_PROVINCE_ID)

	# Внешний контур Stage 4 становится буквально тем же набором колец, который
	# уже сгенерирован для слоя 4. Повторной буферизации в GDScript нет.
	_province_rings = draw_rings
	return true


func _apply_gameplay_coast_to_chains() -> bool:
	var rebuilt: Array[Dictionary] = []
	_coast_inset_endpoint_count = 0
	_coast_fallback_chain_count = 0
	_coast_removed_component_count = 0
	_clean_point_count = 0
	_fallback_chain_count = 0

	for chain_data in _clean_chains:
		var pair := str(chain_data.get("pair", ""))
		var raw: PackedVector2Array = chain_data.get("raw", PackedVector2Array())
		if raw.size() < 2:
			continue

		# Клипуем всю K-цепь. Это принципиально важнее простого переноса её двух
		# концов: в вогнутом береге цепь может зайти в удалённую 2-км полосу,
		# снова вернуться на сушу и затем ещё раз выйти к морю.
		var coast_components := _clip_polyline_to_gameplay_area(raw)
		if coast_components.is_empty():
			# Если контакт двух зон целиком лежал в удалённой береговой полосе,
			# после нового gameplay coast они действительно больше не граничат.
			_coast_removed_component_count += 1
			continue

		for coast_raw in coast_components:
			if coast_raw.size() < 2:
				continue

			# Cleanup пересчитывается ПОСЛЕ клипа. Если RDP/waviness пытается
			# срезать вогнутый берег и выйти наружу, откатываемся к более строгому
			# варианту, в крайнем случае — к исходной клипованной K-полилинии.
			var cleaned := _cleanup_chain(coast_raw, pair)
			var used_fallback := false
			if cleaned.size() < 2 or _has_self_intersection(cleaned) or not _chain_stays_in_gameplay_area(cleaned):
				cleaned = _rdp(coast_raw, RDP_TOLERANCE * 0.55)
				used_fallback = true
			if cleaned.size() < 2 or not _chain_stays_in_gameplay_area(cleaned):
				cleaned = coast_raw
				used_fallback = true
			if not _chain_stays_in_gameplay_area(cleaned):
				return _fail("клипованная межзонная цепь %s всё ещё выходит в удалённую 2-км береговую полосу" % pair)
			if used_fallback:
				_fallback_chain_count += 1
				_coast_fallback_chain_count += 1

			_clean_point_count += cleaned.size()
			rebuilt.append({
				"pair": pair,
				"raw": coast_raw,
				"clean": cleaned,
			})

	if rebuilt.is_empty():
		return _fail("после применения 2-км gameplay coast не осталось политических цепей")
	_clean_chains = rebuilt
	return true


func _clip_polyline_to_gameplay_area(points: PackedVector2Array) -> Array[PackedVector2Array]:
	var components: Array[PackedVector2Array] = []
	if points.size() < 2:
		return components

	var current := PackedVector2Array()
	for segment_index in range(points.size() - 1):
		var a := points[segment_index]
		var b := points[segment_index + 1]
		if _points_close(a, b):
			continue

		var splits := _segment_split_points(a, b)
		for split_index in range(splits.size() - 1):
			var p0: Vector2 = splits[split_index]["point"]
			var p1: Vector2 = splits[split_index + 1]["point"]
			if _points_close(p0, p1):
				continue
			var midpoint := p0.lerp(p1, 0.5)
			var interval_inside := _point_in_or_on_gameplay_area(midpoint)

			if interval_inside:
				if current.is_empty():
					current.append(p0)
				elif not _points_close(current[current.size() - 1], p0):
					# Между двумя внутренними интервалами был наружный промежуток:
					# это уже отдельная политическая компонента.
					if current.size() >= 2:
						components.append(current)
					current = PackedVector2Array([p0])
				if not _points_close(current[current.size() - 1], p1):
					current.append(p1)
			else:
				if current.size() >= 2:
					components.append(current)
				current = PackedVector2Array()

	if current.size() >= 2:
		components.append(current)
	return components


func _segment_split_points(a: Vector2, b: Vector2) -> Array[Dictionary]:
	var result: Array[Dictionary] = [
		{"t": 0.0, "point": a},
		{"t": 1.0, "point": b},
	]
	var ab := b - a
	var length_sq := ab.length_squared()
	if length_sq <= 1e-12:
		return result

	for polygon_rings in _gameplay_polygons:
		for ring in polygon_rings:
			if ring.size() < 2:
				continue
			for ring_index in range(ring.size()):
				var c: Vector2 = ring[ring_index]
				var d: Vector2 = ring[(ring_index + 1) % ring.size()]
				if _points_close(c, d):
					continue
				var hit: Variant = Geometry2D.segment_intersects_segment(a, b, c, d)
				if not hit is Vector2:
					continue
				var t := clampf((hit - a).dot(ab) / length_sq, 0.0, 1.0)
				if _split_t_exists(result, t):
					continue
				result.append({"t": t, "point": hit})
				if t > CLIP_T_EPSILON and t < 1.0 - CLIP_T_EPSILON:
					_coast_inset_endpoint_count += 1

	result.sort_custom(_split_point_less)
	return result


func _split_t_exists(points: Array[Dictionary], t: float) -> bool:
	for item in points:
		if absf(float(item["t"]) - t) <= CLIP_T_EPSILON:
			return true
	return false


func _split_point_less(a: Dictionary, b: Dictionary) -> bool:
	return float(a["t"]) < float(b["t"])


func _chain_stays_in_gameplay_area(points: PackedVector2Array) -> bool:
	if points.size() < 2:
		return false
	for i in range(points.size()):
		if not _point_in_or_on_gameplay_area(points[i]):
			return false
		if i + 1 >= points.size():
			continue
		# Проверяем не только вершины: RDP/waviness могут срезать вогнутый берег.
		var a := points[i]
		var b := points[i + 1]
		for sample_t in [0.125, 0.25, 0.5, 0.75, 0.875]:
			if not _point_in_or_on_gameplay_area(a.lerp(b, float(sample_t))):
				return false
	return true


func _point_in_or_on_gameplay_area(point: Vector2) -> bool:
	for polygon_rings in _gameplay_polygons:
		if polygon_rings.is_empty():
			continue
		var outer: PackedVector2Array = polygon_rings[0]
		var on_outer := _point_on_ring_boundary(point, outer)
		if not on_outer and not Geometry2D.is_point_in_polygon(point, outer):
			continue

		var blocked_by_hole := false
		for hole_index in range(1, polygon_rings.size()):
			var hole: PackedVector2Array = polygon_rings[hole_index]
			if _point_on_ring_boundary(point, hole):
				# Граница отверстия сама является допустимой границей gameplay area.
				continue
			if Geometry2D.is_point_in_polygon(point, hole):
				blocked_by_hole = true
				break
		if not blocked_by_hole:
			return true
	return false


func _point_on_gameplay_boundary(point: Vector2) -> bool:
	for polygon_rings in _gameplay_polygons:
		for ring in polygon_rings:
			if _point_on_ring_boundary(point, ring):
				return true
	return false


func _point_on_ring_boundary(point: Vector2, ring: PackedVector2Array) -> bool:
	if ring.size() < 2:
		return false
	for i in range(ring.size()):
		var a := ring[i]
		var b := ring[(i + 1) % ring.size()]
		if _point_segment_distance(point, a, b) <= COAST_BOUNDARY_EPSILON:
			return true
	return false


func _refresh_coast_summary() -> void:
	if not is_instance_valid(_summary_label):
		return
	if not _last_error.is_empty():
		_summary_label.text = "Ошибка: %s" % _last_error
		return
	_summary_label.text = (
		"• Сырых межзонных кусков K: %d\n"
		+ "• Компонент политических границ после 2-км clip: %d\n"
		+ "• Точек до/после cleanup: %d → %d\n"
		+ "• Берег: gameplay coastline слоя 4, отступ 2 км\n"
		+ "• Пересечений с 2-км контуром: %d\n"
		+ "• Полностью удалённых береговых контактов: %d\n"
		+ "• Защитных fallback-цепей: %d (после coast-check: %d)\n"
		+ "• Владение 600 микроклетками K не изменяется."
	) % [
		_raw_pieces.size(),
		_clean_chains.size(),
		_raw_point_count,
		_clean_point_count,
		_coast_inset_endpoint_count,
		_coast_removed_component_count,
		_fallback_chain_count,
		_coast_fallback_chain_count,
	]
