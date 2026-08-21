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
## - концы внутренних границ, выходившие к естественному берегу, подрезаются
##   до 2-км gameplay coast и стыкуются с ним;
## - внутренние junction-точки и владение 600 микроклетками не меняются.

const GAMEPLAY_COAST_PATH := "res://assets/provinces_iberia_selection_2km.json"
const GAMEPLAY_PROVINCE_ID := "spain__la_coru_a"
const GAMEPLAY_COAST_RULE_KM := 2.0
const COAST_BOUNDARY_EPSILON := 0.0008

var _coast_inset_endpoint_count := 0
var _coast_fallback_chain_count := 0


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


func _load_layer4_gameplay_coast() -> bool:
	if not FileAccess.file_exists(GAMEPLAY_COAST_PATH):
		return _fail("не найден 2-км gameplay coast слоя 4: %s" % GAMEPLAY_COAST_PATH)
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(GAMEPLAY_COAST_PATH))
	if typeof(parsed) != TYPE_DICTIONARY:
		return _fail("2-км gameplay coast слоя 4 имеет неверный JSON-формат")
	var data: Dictionary = parsed
	var gameplay_rings: Array[PackedVector2Array] = []
	for raw_cell in data.get("cells", []):
		if not raw_cell is Dictionary:
			continue
		if str(raw_cell.get("id", "")) != GAMEPLAY_PROVINCE_ID:
			continue
		gameplay_rings = _to_rings(raw_cell.get("rings", []))
		break
	if gameplay_rings.is_empty():
		return _fail("в 2-км слое не найдена Ла-Корунья: %s" % GAMEPLAY_PROVINCE_ID)

	# Внешний контур Stage 4 становится тем же контуром, который уже принят
	# слоем 4 для клика/выделения. Никакой повторной буферизации в GDScript.
	_province_rings = gameplay_rings
	return true


func _apply_gameplay_coast_to_chains() -> bool:
	var rebuilt: Array[Dictionary] = []
	_coast_inset_endpoint_count = 0
	_coast_fallback_chain_count = 0
	_clean_point_count = 0
	_fallback_chain_count = 0

	for chain_data in _clean_chains:
		var pair := str(chain_data.get("pair", ""))
		var raw: PackedVector2Array = chain_data.get("raw", PackedVector2Array())
		if raw.size() < 2:
			continue

		# Сначала переносим только береговые окончания сырой K-цепи. Если конец
		# уже лежит внутри gameplay coast, он остаётся неизменным — так тройные
		# внутренние junction-точки не двигаются.
		var coast_raw := _trim_chain_ends_to_gameplay_coast(raw)
		if coast_raw.size() < 2:
			return _fail("2-км берег полностью удалил межзонную цепь %s" % pair)

		# Cleanup пересчитывается после переноса концов: inherited-алгоритм сам
		# закрепляет endpoints, поэтому новая политическая линия точно приходит
		# в точку 2-км gameplay coast, а не в старый естественный берег.
		var cleaned := _cleanup_chain(coast_raw, pair)
		var used_fallback := false
		if cleaned.size() < 2 or _has_self_intersection(cleaned) or not _chain_stays_in_gameplay_area(cleaned):
			cleaned = _rdp(coast_raw, RDP_TOLERANCE * 0.55)
			used_fallback = true
		if cleaned.size() < 2 or not _chain_stays_in_gameplay_area(cleaned):
			cleaned = coast_raw
			used_fallback = true
		if not _chain_stays_in_gameplay_area(cleaned):
			return _fail("межзонная цепь %s повторно выходит в удалённую 2-км береговую полосу" % pair)
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


func _trim_chain_ends_to_gameplay_coast(points: PackedVector2Array) -> PackedVector2Array:
	var result := _trim_chain_start_to_gameplay_coast(points)
	if result.size() < 2:
		return result
	result = _reversed(result)
	result = _trim_chain_start_to_gameplay_coast(result)
	if result.size() < 2:
		return result
	return _reversed(result)


func _trim_chain_start_to_gameplay_coast(points: PackedVector2Array) -> PackedVector2Array:
	if points.size() < 2 or _point_in_or_on_gameplay_area(points[0]):
		return points.duplicate()

	var first_inside := -1
	for i in range(1, points.size()):
		if _point_in_or_on_gameplay_area(points[i]):
			first_inside = i
			break
	if first_inside < 0:
		return PackedVector2Array()

	var outside := points[first_inside - 1]
	var inside := points[first_inside]
	var hit: Variant = _segment_gameplay_boundary_intersection(outside, inside)
	var coast_point: Vector2
	if hit is Vector2:
		coast_point = hit
	else:
		# Численный fallback на случай почти касательного пересечения.
		coast_point = _bisect_gameplay_boundary(outside, inside)

	var result := PackedVector2Array()
	result.append(coast_point)
	for i in range(first_inside, points.size()):
		if not _points_close(result[result.size() - 1], points[i]):
			result.append(points[i])
	_coast_inset_endpoint_count += 1
	return result


func _segment_gameplay_boundary_intersection(outside: Vector2, inside: Vector2) -> Variant:
	var best_hit: Variant = null
	var best_distance := 1.0e30
	for ring in _province_rings:
		if ring.size() < 2:
			continue
		for i in range(ring.size()):
			var a := ring[i]
			var b := ring[(i + 1) % ring.size()]
			if _points_close(a, b):
				continue
			var hit: Variant = Geometry2D.segment_intersects_segment(outside, inside, a, b)
			if hit is Vector2:
				# Берём пересечение, ближайшее к уже внутренней точке. На коротком
				# K-сегменте обычно оно одно, но это устойчиво и для вогнутого берега.
				var distance := inside.distance_squared_to(hit)
				if distance < best_distance:
					best_distance = distance
					best_hit = hit
	return best_hit


func _bisect_gameplay_boundary(outside: Vector2, inside: Vector2) -> Vector2:
	var low := outside
	var high := inside
	for _iteration in range(32):
		var mid := low.lerp(high, 0.5)
		if _point_in_or_on_gameplay_area(mid):
			high = mid
		else:
			low = mid
	return high


func _chain_stays_in_gameplay_area(points: PackedVector2Array) -> bool:
	if points.size() < 2:
		return false
	for i in range(points.size()):
		if not _point_in_or_on_gameplay_area(points[i]):
			return false
		if i + 1 >= points.size():
			continue
		# Проверяем не только вершины: у вогнутого берега отрезок с двумя
		# внутренними концами теоретически может на мгновение выйти наружу.
		var a := points[i]
		var b := points[i + 1]
		for sample_t in [0.25, 0.5, 0.75]:
			if not _point_in_or_on_gameplay_area(a.lerp(b, float(sample_t))):
				return false
	return true


func _point_in_or_on_gameplay_area(point: Vector2) -> bool:
	if _province_rings.is_empty():
		return false
	var outer := _province_rings[0]
	var inside_outer := Geometry2D.is_point_in_polygon(point, outer)
	if not inside_outer and not _point_on_gameplay_boundary(point):
		return false
	# Дополнительные rings у Polygon трактуем как отверстия. Точка на самой
	# границе отверстия допустима как политический endpoint.
	for i in range(1, _province_rings.size()):
		if Geometry2D.is_point_in_polygon(point, _province_rings[i]) and not _point_on_ring_boundary(point, _province_rings[i]):
			return false
	return true


func _point_on_gameplay_boundary(point: Vector2) -> bool:
	for ring in _province_rings:
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
		+ "• Собранных политических цепей: %d\n"
		+ "• Точек до/после cleanup: %d → %d\n"
		+ "• Берег: gameplay coastline слоя 4, отступ 2 км\n"
		+ "• Береговых окончаний перенесено на 2-км контур: %d\n"
		+ "• Защитных fallback-цепей: %d (после coast-check: %d)\n"
		+ "• Владение 600 микроклетками K не изменяется."
	) % [
		_raw_pieces.size(),
		_clean_chains.size(),
		_raw_point_count,
		_clean_point_count,
		_coast_inset_endpoint_count,
		_fallback_chain_count,
		_coast_fallback_chain_count,
	]
