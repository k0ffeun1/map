class_name SubdivisionBoundaryCleanupStage
extends Node2D
## Этап 4 последовательного пайплайна деления провинции.
##
## Q (этап 2) создаёт 600 атомарных микроклеток.
## K (этап 3) назначает каждый атом одной из четырёх связных зон.
## Этот слой НЕ меняет эти назначения и не рисует новые полигоны зон.
## Он берёт только межзонную сеть рёбер K и превращает её в читаемые
## политические границы: собирает рёбра в длинные цепочки, убирает
## микроклеточную "лесенку", добавляет очень слабую крупномасштабную
## нерегулярность и обязательно сохраняет узлы стыков.
##
## Благодаря этому топология этапа 3 остаётся источником правды:
## - ни одна микроклетка не меняет владельца;
## - связность четырёх зон не меняется;
## - тройные стыки и концы границ остаются на исходных координатах;
## - визуальная кривая не используется как источник назначения территории.
##
## Это именно preview cleanup-этапа. После утверждения внешнего вида тот же
## принцип можно перенести в offline Python-генератор и выпустить финальные
## полигоны районов/ID-map без runtime-геометрии.

const GROWTH_PATH := "res://assets/subdivision_stages/lacoruna_competitive_growth.json"
const EXPECTED_FORMAT := "province_competitive_growth/v1"

const RAW_BORDER_COLOR := Color(0.12, 0.20, 0.28, 0.18)
const CLEAN_BORDER_SHADOW := Color(0.015, 0.025, 0.035, 0.98)
const CLEAN_BORDER_COLOR := Color(0.94, 0.94, 0.91, 0.96)
const PROVINCE_BORDER_COLOR := Color(1.0, 0.77, 0.24, 1.0)

# Мир у проекта шириной 8192. У Ла-Коруньи одна микроклетка обычно имеет
# характерный размер около 1 world-px. Эти значения намеренно меньше клетки:
# cleanup должен убрать ступеньки, а не увести границу в соседний район.
const RDP_TOLERANCE := 0.34
const RESAMPLE_SPACING := 0.95
const WAVINESS_AMPLITUDE := 0.22
const WAVINESS_MACRO_CYCLES := 1.35
const WAVINESS_MESO_CYCLES := 3.40
const ENDPOINT_EPSILON := 0.0001
const POINT_KEY_SCALE := 100000.0

var _camera: Camera2D
var _ui_layer: CanvasLayer
var _root_viewer: Node
var _panel: PanelContainer
var _title_label: Label
var _summary_label: Label

var _province_rings: Array[PackedVector2Array] = []
var _raw_pieces: Array[Dictionary] = []
var _clean_chains: Array[Dictionary] = []
var _claim_zone_by_microcell: Dictionary = {}
var _last_error := ""
var _last_zoom := -1.0
var _raw_point_count := 0
var _clean_point_count := 0
var _fallback_chain_count := 0


func _ready() -> void:
	_camera = get_node_or_null("../Camera2D") as Camera2D
	_ui_layer = get_node_or_null("../UI") as CanvasLayer
	_root_viewer = get_parent()
	z_index = 215
	visible = false
	if not _load_and_build():
		push_warning("SubdivisionBoundaryCleanupStage: %s" % _last_error)
	_build_panel()
	set_process(true)


func _input(event: InputEvent) -> void:
	if not event is InputEventKey or not event.pressed or event.echo:
		return
	var key := event.physical_keycode
	# Если пользователь возвращается к исходным этапам, cleanup-preview должен
	# сам уйти с экрана, чтобы сравнение не превращалось в наложение слоёв.
	if visible and (key == KEY_Q or key == KEY_K):
		set_active(false)
		return
	if key == KEY_U:
		if not _last_error.is_empty():
			_show_top_info("Этап 4 не открыт: %s" % _last_error)
			return
		set_active(not visible)
		get_viewport().set_input_as_handled()


func _process(_delta: float) -> void:
	if not visible:
		return
	var zoom := maxf(0.0001, _camera.zoom.x if is_instance_valid(_camera) else 1.0)
	if absf(zoom - _last_zoom) > 0.0001:
		_last_zoom = zoom
		queue_redraw()


func set_active(active: bool) -> void:
	if active and not _last_error.is_empty():
		return
	visible = active
	if is_instance_valid(_panel):
		_panel.visible = active
	if active:
		# Этапы Q/K остаются самостоятельными контрольными точками. Выключаем
		# их только при открытии U, не удаляя и не меняя их состояние/данные.
		if is_instance_valid(_root_viewer):
			if _root_viewer.has_method("_set_subdivision_contract_stage_visible"):
				_root_viewer.call("_set_subdivision_contract_stage_visible", false)
			if _root_viewer.has_method("_set_microcell_mesh_stage_visible"):
				_root_viewer.call("_set_microcell_mesh_stage_visible", false)
			if _root_viewer.has_method("_set_microcell_growth_stage_visible"):
				_root_viewer.call("_set_microcell_growth_stage_visible", false)
		_last_zoom = -1.0
		queue_redraw()
		_show_top_info("Этап 4: очищенные политические границы поверх топологии K")


func get_last_error() -> String:
	return _last_error


func _load_and_build() -> bool:
	if not FileAccess.file_exists(GROWTH_PATH):
		return _fail("не найден этап 3: %s" % GROWTH_PATH)
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(GROWTH_PATH))
	if typeof(parsed) != TYPE_DICTIONARY:
		return _fail("этап 3 имеет неверный JSON-формат")
	var growth: Dictionary = parsed
	if str(growth.get("format", "")) != EXPECTED_FORMAT:
		return _fail("ожидался формат %s" % EXPECTED_FORMAT)

	_claim_zone_by_microcell.clear()
	for raw_claim in growth.get("claims", []):
		if not raw_claim is Dictionary:
			continue
		var microcell_id := str(raw_claim.get("microcell_id", ""))
		var zone_id := str(raw_claim.get("zone_id", ""))
		if not microcell_id.is_empty() and not zone_id.is_empty():
			_claim_zone_by_microcell[microcell_id] = zone_id
	if _claim_zone_by_microcell.is_empty():
		return _fail("в этапе 3 нет назначений микроклеток")

	var source_mesh_path := str(growth.get("source_mesh_path", ""))
	if source_mesh_path.is_empty() or not FileAccess.file_exists(source_mesh_path):
		return _fail("не найдена исходная микросетка этапа 2")
	var mesh_parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(source_mesh_path))
	if typeof(mesh_parsed) != TYPE_DICTIONARY:
		return _fail("микросетка этапа 2 имеет неверный JSON-формат")
	var mesh: Dictionary = mesh_parsed
	_province_rings = _to_rings(mesh.get("province_rings", []))
	if _province_rings.is_empty():
		return _fail("в микросетке отсутствует контур провинции")

	_raw_pieces.clear()
	_raw_point_count = 0
	for raw_segment in growth.get("boundary_segments", []):
		if not raw_segment is Dictionary:
			continue
		var microcells: Array = raw_segment.get("microcells", [])
		if microcells.size() != 2:
			continue
		var first_id := str(microcells[0])
		var second_id := str(microcells[1])
		var first_zone := str(_claim_zone_by_microcell.get(first_id, ""))
		var second_zone := str(_claim_zone_by_microcell.get(second_id, ""))
		if first_zone.is_empty() or second_zone.is_empty() or first_zone == second_zone:
			continue
		var points := _to_polyline(raw_segment.get("points", []))
		if points.size() < 2:
			continue
		_raw_point_count += points.size()
		_raw_pieces.append({
			"pair": _pair_key(first_zone, second_zone),
			"points": points,
		})
	if _raw_pieces.is_empty():
		return _fail("этап 3 не содержит межзонных рёбер")

	_build_clean_chains()
	if _clean_chains.is_empty():
		return _fail("не удалось собрать очищенные цепочки границ")
	_last_error = ""
	queue_redraw()
	return true


func _build_clean_chains() -> void:
	_clean_chains.clear()
	_clean_point_count = 0
	_fallback_chain_count = 0
	var by_pair: Dictionary = {}
	for piece in _raw_pieces:
		var pair := str(piece["pair"])
		if not by_pair.has(pair):
			by_pair[pair] = []
		by_pair[pair].append(piece["points"])

	var pair_keys := by_pair.keys()
	pair_keys.sort()
	for pair_variant in pair_keys:
		var pair := str(pair_variant)
		var chains := _stitch_pair_pieces(by_pair[pair])
		for chain in chains:
			if chain.size() < 2:
				continue
			var cleaned := _cleanup_chain(chain, pair)
			var used_fallback := false
			if cleaned.size() < 2 or _has_self_intersection(cleaned):
				cleaned = _rdp(chain, RDP_TOLERANCE * 0.55)
				used_fallback = true
			if cleaned.size() < 2:
				cleaned = chain
				used_fallback = true
			if used_fallback:
				_fallback_chain_count += 1
			_clean_point_count += cleaned.size()
			_clean_chains.append({
				"pair": pair,
				"raw": chain,
				"clean": cleaned,
			})


func _stitch_pair_pieces(raw_pieces: Array) -> Array[PackedVector2Array]:
	var pieces: Array[PackedVector2Array] = []
	for raw in raw_pieces:
		if raw is PackedVector2Array and raw.size() >= 2:
			pieces.append(raw)
	if pieces.is_empty():
		return []

	# Endpoint -> индексы кусков. Внутренняя точка цепи имеет степень 2,
	# тройной политический стык или конец у внешней границы — другую степень.
	var endpoint_map: Dictionary = {}
	for index in range(pieces.size()):
		for point in [pieces[index][0], pieces[index][pieces[index].size() - 1]]:
			var key := _point_key(point)
			if not endpoint_map.has(key):
				endpoint_map[key] = []
			endpoint_map[key].append(index)

	var used: Dictionary = {}
	var result: Array[PackedVector2Array] = []
	# Сначала стартуем с концов/стыков, чтобы не сшить цепь через политический
	# junction. Затем добираем замкнутые контуры, у которых все степени равны 2.
	var starts: Array[int] = []
	for index in range(pieces.size()):
		var a_degree := (endpoint_map.get(_point_key(pieces[index][0]), []) as Array).size()
		var b_degree := (endpoint_map.get(_point_key(pieces[index][pieces[index].size() - 1]), []) as Array).size()
		if a_degree != 2 or b_degree != 2:
			starts.append(index)
	for index in range(pieces.size()):
		if not starts.has(index):
			starts.append(index)

	for start in starts:
		if used.has(start):
			continue
		var chain := pieces[start].duplicate()
		used[start] = true
		chain = _extend_chain(chain, pieces, endpoint_map, used, true)
		chain = _extend_chain(chain, pieces, endpoint_map, used, false)
		result.append(chain)
	return result


func _extend_chain(
	chain: PackedVector2Array,
	pieces: Array[PackedVector2Array],
	endpoint_map: Dictionary,
	used: Dictionary,
	at_end: bool
) -> PackedVector2Array:
	while true:
		var anchor := chain[chain.size() - 1] if at_end else chain[0]
		var candidates: Array = endpoint_map.get(_point_key(anchor), [])
		# Не переходим через junction: там несколько политических цепей должны
		# встретиться в одной исходной точке, а не быть склеены в одну линию.
		if candidates.size() != 2:
			break
		var next_index := -1
		for candidate in candidates:
			var idx := int(candidate)
			if not used.has(idx):
				next_index = idx
				break
		if next_index < 0:
			break
		var next_piece := pieces[next_index]
		var forward := _points_close(next_piece[0], anchor)
		var ordered := next_piece if forward else _reversed(next_piece)
		if not _points_close(ordered[0], anchor):
			break
		used[next_index] = true
		if at_end:
			for i in range(1, ordered.size()):
				chain.append(ordered[i])
		else:
			for i in range(1, ordered.size()):
				chain.insert(0, ordered[i])
	return chain


func _cleanup_chain(raw: PackedVector2Array, pair: String) -> PackedVector2Array:
	if raw.size() <= 2:
		return raw.duplicate()
	var simplified := _rdp(raw, RDP_TOLERANCE)
	if simplified.size() <= 2:
		return simplified
	var sampled := _resample(simplified, RESAMPLE_SPACING)
	if sampled.size() <= 2:
		return sampled
	var phase := _stable_phase(pair)
	var result := sampled.duplicate()
	for i in range(1, result.size() - 1):
		var t := float(i) / float(result.size() - 1)
		var tangent := (result[i + 1] - result[i - 1]).normalized()
		if tangent.length_squared() < 1e-8:
			continue
		var normal := Vector2(-tangent.y, tangent.x)
		var endpoint_weight := sin(PI * t)
		var macro := sin(TAU * WAVINESS_MACRO_CYCLES * t + phase)
		var meso := sin(TAU * WAVINESS_MESO_CYCLES * t + phase * 1.73)
		var offset := (macro * 0.68 + meso * 0.32) * WAVINESS_AMPLITUDE * endpoint_weight
		result[i] += normal * offset
	# Эндпоинты политической цепи принципиально не двигаются: это сохраняет
	# тройные стыки и места выхода границы на внешний контур провинции.
	result[0] = raw[0]
	result[result.size() - 1] = raw[raw.size() - 1]
	return result


func _draw() -> void:
	if not visible or _clean_chains.is_empty():
		return
	var zoom := maxf(0.0001, _camera.zoom.x if is_instance_valid(_camera) else 1.0)
	var raw_width := 0.35 / zoom
	var shadow_width := 3.2 / zoom
	var clean_width := 1.25 / zoom
	var outer_width := 2.6 / zoom

	# Сырая K-сетка остаётся едва видимой как контроль: пользователь может
	# увидеть, насколько cleanup реально ушёл от атомарной лесенки.
	for chain in _clean_chains:
		var raw: PackedVector2Array = chain["raw"]
		if raw.size() >= 2:
			draw_polyline(raw, RAW_BORDER_COLOR, raw_width, true)
	for chain in _clean_chains:
		var clean: PackedVector2Array = chain["clean"]
		if clean.size() < 2:
			continue
		draw_polyline(clean, CLEAN_BORDER_SHADOW, shadow_width, true)
		draw_polyline(clean, CLEAN_BORDER_COLOR, clean_width, true)

	for ring in _province_rings:
		if ring.size() < 2:
			continue
		var closed := ring.duplicate()
		if not _points_close(closed[0], closed[closed.size() - 1]):
			closed.append(closed[0])
		draw_polyline(closed, PROVINCE_BORDER_COLOR, outer_width, true)


func _build_panel() -> void:
	if not is_instance_valid(_ui_layer):
		return
	_panel = PanelContainer.new()
	_panel.offset_left = 1370.0
	_panel.offset_top = 92.0
	_panel.offset_right = 1896.0
	_panel.offset_bottom = 410.0
	_panel.visible = false
	_ui_layer.add_child(_panel)

	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 14)
	margin.add_theme_constant_override("margin_top", 12)
	margin.add_theme_constant_override("margin_right", 14)
	margin.add_theme_constant_override("margin_bottom", 12)
	_panel.add_child(margin)
	var content := VBoxContainer.new()
	content.add_theme_constant_override("separation", 6)
	margin.add_child(content)

	_title_label = Label.new()
	_title_label.text = "Этап 4 — Очистка политических границ"
	_title_label.add_theme_color_override("font_color", Color(1.0, 0.86, 0.58, 1.0))
	_title_label.add_theme_font_size_override("font_size", 19)
	content.add_child(_title_label)

	var explanation := Label.new()
	explanation.text = "K остаётся источником правды. Межзонные рёбра собираются в цепи, микроклеточная лесенка упрощается, а затем добавляется слабая крупная нерегулярность с закреплёнными стыками."
	explanation.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	explanation.add_theme_color_override("font_color", Color(0.94, 0.94, 0.94, 1.0))
	content.add_child(explanation)

	_summary_label = Label.new()
	_summary_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_summary_label.add_theme_color_override("font_color", Color(0.88, 0.91, 0.95, 1.0))
	if _last_error.is_empty():
		_summary_label.text = (
			"• Сырых межзонных кусков K: %d\n"
			+ "• Собранных политических цепей: %d\n"
			+ "• Точек до/после cleanup: %d → %d\n"
			+ "• Защитных fallback-цепей: %d\n"
			+ "• Владение 600 микроклетками не изменяется."
		) % [_raw_pieces.size(), _clean_chains.size(), _raw_point_count, _clean_point_count, _fallback_chain_count]
	else:
		_summary_label.text = "Ошибка: %s" % _last_error
	content.add_child(_summary_label)

	var hint := Label.new()
	hint.text = "U — показать/скрыть этап 4; Q/K возвращают исходные этапы"
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	hint.add_theme_color_override("font_color", Color(1.0, 0.86, 0.58, 1.0))
	content.add_child(hint)


func _show_top_info(message: String) -> void:
	if is_instance_valid(_root_viewer) and _root_viewer.has_method("_show_top_info"):
		_root_viewer.call("_show_top_info", message)


func _pair_key(a: String, b: String) -> String:
	return "%s|%s" % [a, b] if a < b else "%s|%s" % [b, a]


func _point_key(point: Vector2) -> String:
	return "%d:%d" % [roundi(point.x * POINT_KEY_SCALE), roundi(point.y * POINT_KEY_SCALE)]


func _points_close(a: Vector2, b: Vector2) -> bool:
	return a.distance_squared_to(b) <= ENDPOINT_EPSILON * ENDPOINT_EPSILON


func _reversed(points: PackedVector2Array) -> PackedVector2Array:
	var result := PackedVector2Array()
	for i in range(points.size() - 1, -1, -1):
		result.append(points[i])
	return result


func _to_polyline(raw_points: Array) -> PackedVector2Array:
	var result := PackedVector2Array()
	for raw_point in raw_points:
		if raw_point is Array and raw_point.size() >= 2:
			result.append(Vector2(float(raw_point[0]), float(raw_point[1])))
	return result


func _to_rings(raw_rings: Array) -> Array[PackedVector2Array]:
	var result: Array[PackedVector2Array] = []
	for raw_ring in raw_rings:
		if not raw_ring is Array or raw_ring.size() < 3:
			continue
		var ring := _to_polyline(raw_ring)
		if ring.size() >= 3:
			result.append(ring)
	return result


func _rdp(points: PackedVector2Array, epsilon: float) -> PackedVector2Array:
	if points.size() <= 2:
		return points.duplicate()
	var start := points[0]
	var finish := points[points.size() - 1]
	var max_distance := -1.0
	var split_index := -1
	for i in range(1, points.size() - 1):
		var distance := _point_segment_distance(points[i], start, finish)
		if distance > max_distance:
			max_distance = distance
			split_index = i
	if max_distance <= epsilon or split_index < 0:
		return PackedVector2Array([start, finish])
	var left_input := PackedVector2Array()
	for i in range(0, split_index + 1):
		left_input.append(points[i])
	var right_input := PackedVector2Array()
	for i in range(split_index, points.size()):
		right_input.append(points[i])
	var left := _rdp(left_input, epsilon)
	var right := _rdp(right_input, epsilon)
	var result := left.duplicate()
	for i in range(1, right.size()):
		result.append(right[i])
	return result


func _point_segment_distance(point: Vector2, a: Vector2, b: Vector2) -> float:
	var ab := b - a
	var length_sq := ab.length_squared()
	if length_sq <= 1e-12:
		return point.distance_to(a)
	var t := clampf((point - a).dot(ab) / length_sq, 0.0, 1.0)
	return point.distance_to(a + ab * t)


func _resample(points: PackedVector2Array, spacing: float) -> PackedVector2Array:
	if points.size() <= 2 or spacing <= 0.0:
		return points.duplicate()
	var cumulative := PackedFloat32Array()
	cumulative.append(0.0)
	var total := 0.0
	for i in range(1, points.size()):
		total += points[i - 1].distance_to(points[i])
		cumulative.append(total)
	if total <= spacing:
		return PackedVector2Array([points[0], points[points.size() - 1]])
	var result := PackedVector2Array()
	result.append(points[0])
	var target := spacing
	var segment := 1
	while target < total and segment < points.size():
		while segment < cumulative.size() and cumulative[segment] < target:
			segment += 1
		if segment >= points.size():
			break
		var prev_distance := cumulative[segment - 1]
		var segment_length := maxf(cumulative[segment] - prev_distance, 1e-8)
		var t := (target - prev_distance) / segment_length
		result.append(points[segment - 1].lerp(points[segment], t))
		target += spacing
	result.append(points[points.size() - 1])
	return result


func _stable_phase(value: String) -> float:
	var hash_value := 2166136261
	for byte in value.to_utf8_buffer():
		hash_value = int((hash_value ^ int(byte)) * 16777619) & 0x7fffffff
	return fmod(float(hash_value) * 0.000001, TAU)


func _has_self_intersection(points: PackedVector2Array) -> bool:
	if points.size() < 4:
		return false
	for i in range(points.size() - 1):
		for j in range(i + 2, points.size() - 1):
			# Соседние сегменты естественно встречаются в общей вершине.
			if j == i + 1:
				continue
			# Для замкнутой цепи первый/последний сегменты тоже соседи.
			if i == 0 and j == points.size() - 2 and _points_close(points[0], points[points.size() - 1]):
				continue
			var hit: Variant = Geometry2D.segment_intersects_segment(points[i], points[i + 1], points[j], points[j + 1])
			if hit != null:
				return true
	return false


func _fail(message: String) -> bool:
	_last_error = message
	return false
