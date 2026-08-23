extends Node
## Строгий исторический слой территорий.
##
## Текущий этап проекта намеренно содержит ТОЛЬКО Region:
##   X — исторические регионы, построенные только из province_id слоя 8.
##
## C / V / B зарезервированы для следующих ступеней, но сейчас отключены.
## Старый I-регион Иберии также отключён, чтобы два разных набора регионов
## никогда не рисовались одновременно.
##
## ГЛАВНОЕ ПРАВИЛО:
## assets/provinces.json (слой 8) — единственный источник геометрии.
## Region не имеет собственной геометрии и существует только как явный список
## стабильных province_id. Никаких centroid/bbox/nearest-neighbour эвристик.

const HIERARCHY_PATH := "res://assets/historical_hierarchy.json"
const PROVINCES_PATH := "res://assets/provinces.json"
const PROVIDER_SCRIPT := preload("res://scripts/HistoricalHierarchyProvider.gd")

const REGION_KEY := KEY_X
const DISABLED_RESERVED_KEYS := [KEY_C, KEY_V, KEY_B, KEY_I]
const REGION_ALPHA := 0.58
const FORBIDDEN_GEOMETRY_FIELDS := [
	"rings", "ring", "polygon", "polygons", "geometry", "bbox", "bounds",
	"coordinates", "points", "centroid", "center", "seed"
]

var _main: Node
var _provider
var _layer_idx := -1
var _data: Dictionary = {}
var _regions_by_id: Dictionary = {}
var _ready_ok := false


func _ready() -> void:
	set_process_input(true)
	call_deferred("_setup_after_scene_ready")


func _setup_after_scene_ready() -> void:
	# Autoload создаётся раньше current_scene; ждём завершения Main._ready().
	await get_tree().process_frame
	await get_tree().process_frame
	_main = get_tree().current_scene
	if not is_instance_valid(_main):
		push_error("HistoricalRegions: current_scene не найден")
		return
	if not FileAccess.file_exists(HIERARCHY_PATH):
		push_error("HistoricalRegions: нет %s" % HIERARCHY_PATH)
		return
	if not FileAccess.file_exists(PROVINCES_PATH):
		push_error("HistoricalRegions: нет %s" % PROVINCES_PATH)
		return

	var parsed = JSON.parse_string(FileAccess.get_file_as_string(HIERARCHY_PATH))
	if typeof(parsed) != TYPE_DICTIONARY:
		push_error("HistoricalRegions: не удалось прочитать hierarchy JSON")
		return
	_data = parsed
	_build_region_index()
	if not _validate_region_structure():
		push_error("HistoricalRegions: строгая валидация Region не пройдена; X не подключён")
		return

	_provider = PROVIDER_SCRIPT.new(
		PROVINCES_PATH,
		Color(0.0, 0.0, 0.0, 0.0),
		0.58,
		0.55,
		0.94,
		PackedColorArray(),
		0.0,
		false,
		0.0,
		0.0,
		0.0,
		0.0,
		512,
		1
	)
	_main.add_child(_provider)

	# Каждый Region province_id обязан реально существовать в текущем слое 8.
	var source_check: Dictionary = _provider.validate_source_province_ids(_all_region_province_ids())
	if not bool(source_check.get("ok", false)):
		for raw_missing in source_check.get("missing", []):
			push_error("HistoricalRegions: province_id отсутствует в слое 8: %s" % str(raw_missing))
		push_error("HistoricalRegions: проверка источника слоя 8 не пройдена; X не подключён")
		_provider.queue_free()
		_provider = null
		return

	var layers_variant = _main.get("_layers")
	if typeof(layers_variant) != TYPE_ARRAY:
		push_error("HistoricalRegions: Main._layers недоступен")
		_provider.queue_free()
		_provider = null
		return
	var layers: Array = layers_variant
	_layer_idx = layers.size()
	layers.append({
		"name": "Исторические регионы (X)",
		"provider": _provider,
		"visible": false,
		"z_index": 94,
	})
	_main.set("_layers", layers)

	# Внутренние legacy-слои не удаляем из массива _layers физически: у старого
	# TileMapViewer много сохранённых индексов, и удаление элемента сдвинуло бы
	# их и сломало несвязанные режимы карты. Вместо этого они полностью удалены
	# из активного key-space: X/I/C/V/B перехватываются здесь ДО _unhandled_input,
	# а конфликтующие старые слои всегда остаются hidden.
	_force_legacy_conflicts_hidden()
	_ready_ok = true
	print("HistoricalRegions: готово. X=Region; I/C/V/B отключены до следующих проверенных этапов; province_id слоя 8 проверено: %d" % int(source_check.get("checked", 0)))


func _input(event: InputEvent) -> void:
	if not _ready_ok:
		return
	if not (event is InputEventKey):
		return
	var key_event := event as InputEventKey
	if not key_event.pressed or key_event.echo:
		return
	var key := key_event.physical_keycode

	if key == REGION_KEY:
		_toggle_regions()
		get_viewport().set_input_as_handled()
		return

	if key in DISABLED_RESERVED_KEYS:
		_force_legacy_conflicts_hidden()
		_clear_visual_tiles()
		_set_status("Территориальная иерархия: сейчас готов только X (Region); I/C/V/B отключены до пересборки снизу вверх")
		get_viewport().set_input_as_handled()


func _toggle_regions() -> void:
	if _layer_idx < 0 or not is_instance_valid(_provider):
		return
	var layers: Array = _main.get("_layers")
	if _layer_idx >= layers.size():
		return

	if bool(layers[_layer_idx].get("visible", false)):
		layers[_layer_idx]["visible"] = false
		_main.set("_layers", layers)
		_clear_visual_tiles()
		_set_status("Исторические регионы (X): выключены")
		return

	var mapping: Dictionary = {}
	var conflicts: Dictionary = {}
	var group_ids: Array = []
	for region_id_raw in _regions_by_id.keys():
		var region_id := str(region_id_raw)
		var region: Dictionary = _regions_by_id[region_id_raw]
		group_ids.append(region_id)
		for raw_pid in region.get("province_ids", []):
			var pid := str(raw_pid)
			if mapping.has(pid) and mapping[pid] != region_id:
				conflicts[pid] = true
			else:
				mapping[pid] = region_id

	# Строгий fail-safe: конфликтующая провинция не рисуется вообще.
	for pid in conflicts.keys():
		mapping.erase(pid)
		push_error("HistoricalRegions: province_id %s имеет два Region — скрыто" % pid)

	group_ids.sort()
	var colors := _make_group_colors(group_ids, REGION_ALPHA)
	var stats: Dictionary = _provider.apply_grouping(mapping, colors)
	layers[_layer_idx]["visible"] = true
	_main.set("_layers", layers)
	_force_legacy_conflicts_hidden()
	_clear_visual_tiles()

	var text := "Исторические регионы (X): %d регионов, %d кусков слоя 8" % [
		int(stats.get("groups", 0)), int(stats.get("matched_cells", 0))
	]
	_set_status(text)
	print("HistoricalRegions: ", text)


func _build_region_index() -> void:
	_regions_by_id.clear()
	var tiers: Dictionary = _data.get("tiers", {})
	var region_tier: Dictionary = tiers.get("region", {})
	for raw_region in region_tier.get("groups", []):
		if typeof(raw_region) != TYPE_DICTIONARY:
			continue
		var region: Dictionary = raw_region
		var region_id := str(region.get("id", ""))
		if not region_id.is_empty():
			_regions_by_id[region_id] = region


func _validate_region_structure() -> bool:
	var ok := true
	if int(_data.get("source_of_truth_layer", -1)) != 8:
		push_error("HistoricalRegions: source_of_truth_layer обязан быть 8")
		ok = false
	if str(_data.get("province_source", "")) != PROVINCES_PATH:
		push_error("HistoricalRegions: province_source обязан быть %s" % PROVINCES_PATH)
		ok = false
	if not bool(_data.get("strict", false)):
		push_error("HistoricalRegions: hierarchy JSON обязан работать в strict=true")
		ok = false
	if str(_data.get("stage", "")) != "region_only":
		push_error("HistoricalRegions: текущий этап обязан быть stage=region_only")
		ok = false

	var tiers: Dictionary = _data.get("tiers", {})
	if not tiers.has("region"):
		push_error("HistoricalRegions: отсутствует tier region")
		return false
	# Пока пользователь не утвердил X, никаких верхних ступеней в данных быть не должно.
	for forbidden_tier in ["superregion", "macroregion", "major_region", "zone"]:
		if tiers.has(forbidden_tier):
			push_error("HistoricalRegions: преждевременный tier %s запрещён на этапе region_only" % forbidden_tier)
			ok = false

	var seen_region_ids: Dictionary = {}
	var seen_provinces: Dictionary = {}
	for raw_region in tiers["region"].get("groups", []):
		if typeof(raw_region) != TYPE_DICTIONARY:
			push_error("HistoricalRegions: элемент Region не Dictionary")
			ok = false
			continue
		var region: Dictionary = raw_region
		var region_id := str(region.get("id", "")).strip_edges()
		if region_id.is_empty():
			push_error("HistoricalRegions: пустой Region id")
			ok = false
			continue
		if seen_region_ids.has(region_id):
			push_error("HistoricalRegions: повторный Region id %s" % region_id)
			ok = false
		seen_region_ids[region_id] = true

		for field in FORBIDDEN_GEOMETRY_FIELDS:
			if region.has(field):
				push_error("HistoricalRegions: %s содержит запрещённую геометрию '%s'" % [region_id, field])
				ok = false
		if region.has("children"):
			push_error("HistoricalRegions: %s не должен иметь children; только province_ids" % region_id)
			ok = false
		var province_ids: Array = region.get("province_ids", [])
		if province_ids.is_empty():
			push_error("HistoricalRegions: %s имеет пустой province_ids" % region_id)
			ok = false
		if str(region.get("historical_basis", "")).strip_edges().is_empty():
			push_error("HistoricalRegions: %s не имеет historical_basis" % region_id)
			ok = false
		var sources: Array = region.get("sources", [])
		if sources.is_empty():
			push_error("HistoricalRegions: %s не имеет internet sources" % region_id)
			ok = false

		var country_prefixes: Dictionary = {}
		for raw_pid in province_ids:
			var pid := str(raw_pid).strip_edges()
			if pid.is_empty():
				push_error("HistoricalRegions: пустой province_id в %s" % region_id)
				ok = false
				continue
			if seen_provinces.has(pid):
				push_error("HistoricalRegions: %s одновременно в %s и %s" % [pid, seen_provinces[pid], region_id])
				ok = false
			else:
				seen_provinces[pid] = region_id
			var sep := pid.find("__")
			if sep > 0:
				country_prefixes[pid.substr(0, sep)] = true
		if country_prefixes.size() > 1:
			push_error("HistoricalRegions: %s смешивает страны: %s" % [region_id, str(country_prefixes.keys())])
			ok = false

	return ok


func _all_region_province_ids() -> Array:
	var result: Array = []
	for region_id in _regions_by_id.keys():
		var region: Dictionary = _regions_by_id[region_id]
		for raw_pid in region.get("province_ids", []):
			var pid := str(raw_pid)
			if not result.has(pid):
				result.append(pid)
	result.sort()
	return result


func _make_group_colors(group_ids: Array, alpha: float) -> Dictionary:
	var colors: Dictionary = {}
	for i in range(group_ids.size()):
		var group_id := str(group_ids[i])
		var hue := fmod(float(i) * 0.61803398875 + 0.08, 1.0)
		colors[group_id] = Color.from_hsv(hue, 0.48, 0.93, alpha)
	return colors


func _force_legacy_conflicts_hidden() -> void:
	if not is_instance_valid(_main):
		return
	var layers_variant = _main.get("_layers")
	if typeof(layers_variant) != TYPE_ARRAY:
		return
	var layers: Array = layers_variant
	# C = старый тест клеток; V/B = старые океанские debug-слои;
	# I = старый regions_iberia. Все они удалены из активного key-space.
	for property_name in ["_cells_test_layer_idx", "_ocean_v_layer_idx", "_ocean_flat_layer_idx", "_regions_iberia_layer_idx"]:
		var value = _main.get(property_name)
		if value == null:
			continue
		var idx := int(value)
		if idx >= 0 and idx < layers.size():
			layers[idx]["visible"] = false
	_main.set("_layers", layers)


func _clear_visual_tiles() -> void:
	if is_instance_valid(_main) and _main.has_method("_clear_layer_tiles") and _layer_idx >= 0:
		_main.call("_clear_layer_tiles", _layer_idx)


func _set_status(text: String) -> void:
	if not is_instance_valid(_main):
		return
	var label := _main.get_node_or_null("UI/StatusLabel")
	if label is Label:
		label.text = text
