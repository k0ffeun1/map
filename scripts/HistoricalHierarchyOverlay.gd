extends Node
## Глобальный переключатель НОВОЙ исторической территориальной иерархии.
##
## Клавиши (зарезервированы этим autoload через _input, поэтому старые
## _unhandled_input-слои TileMapViewer на C/V/B больше не срабатывают):
##   X — Region
##   C — Superregion
##   V — Macroregion
##   B — Major region (последняя ступень: Западная Европа и т.п.)
##
## ГЛАВНОЕ ПРАВИЛО ПРОЕКТА:
## принадлежность определяется ТОЛЬКО явными стабильными province_id слоя 8
## из assets/historical_hierarchy.json. Координатных эвристик и собственной
## геометрии верхних уровней здесь принципиально нет.

const HIERARCHY_PATH := "res://assets/historical_hierarchy.json"
const PROVINCES_PATH := "res://assets/provinces.json"
const PROVIDER_SCRIPT := preload("res://scripts/HistoricalHierarchyProvider.gd")

const TIER_BY_KEY := {
	KEY_X: "region",
	KEY_C: "superregion",
	KEY_V: "macroregion",
	KEY_B: "major_region",
}

const CHILD_TIER_BY_TIER := {
	"superregion": "region",
	"macroregion": "superregion",
	"major_region": "macroregion",
}

const ALPHA_BY_TIER := {
	"region": 0.58,
	"superregion": 0.52,
	"macroregion": 0.46,
	"major_region": 0.40,
}

const FORBIDDEN_GEOMETRY_FIELDS := [
	"rings", "polygon", "polygons", "geometry", "bbox", "coordinates", "points"
]

var _main: Node
var _provider
var _layer_idx := -1
var _data: Dictionary = {}
var _groups_by_tier: Dictionary = {}
var _active_tier := ""
var _ready_ok := false


func _ready() -> void:
	set_process_input(true)
	call_deferred("_setup_after_scene_ready")


func _setup_after_scene_ready() -> void:
	# Autoload создаётся раньше current_scene; даём Main закончить _ready(),
	# чтобы его _layers уже содержал слой 8 и остальные штатные слои.
	await get_tree().process_frame
	await get_tree().process_frame
	_main = get_tree().current_scene
	if not is_instance_valid(_main):
		push_error("HistoricalHierarchy: current_scene не найден")
		return
	if not FileAccess.file_exists(HIERARCHY_PATH):
		push_error("HistoricalHierarchy: нет %s" % HIERARCHY_PATH)
		return
	if not FileAccess.file_exists(PROVINCES_PATH):
		push_error("HistoricalHierarchy: нет %s" % PROVINCES_PATH)
		return

	var parsed = JSON.parse_string(FileAccess.get_file_as_string(HIERARCHY_PATH))
	if typeof(parsed) != TYPE_DICTIONARY:
		push_error("HistoricalHierarchy: не удалось прочитать hierarchy JSON")
		return
	_data = parsed
	_build_group_indexes()
	if not _validate_hierarchy_structure():
		push_error("HistoricalHierarchy: строгая структурная валидация не пройдена; слой не подключён")
		return

	# Один provider на все четыре ступени: provinces.json (~весь мир) грузится
	# в память ОДИН раз. При X/C/V/B меняются только цвета/visibility.
	_provider = PROVIDER_SCRIPT.new(
		PROVINCES_PATH,
		Color(0.0, 0.0, 0.0, 0.0), # границы провинций верхнему уровню не нужны
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

	# Критическая проверка, которой раньше не было: каждый province_id из
	# Region обязан реально существовать в ТОМ ЖЕ provinces.json слоя 8.
	# Ошибка/опечатка в id больше не может молча дать пустой или съехавший слой.
	var source_check: Dictionary = _provider.validate_source_province_ids(_all_region_province_ids())
	if not bool(source_check.get("ok", false)):
		for raw_missing in source_check.get("missing", []):
			push_error("HistoricalHierarchy: province_id отсутствует в слое 8: %s" % str(raw_missing))
		push_error("HistoricalHierarchy: проверка источника слоя 8 не пройдена; слой не подключён")
		_provider.queue_free()
		_provider = null
		return

	var layers_variant = _main.get("_layers")
	if typeof(layers_variant) != TYPE_ARRAY:
		push_error("HistoricalHierarchy: Main._layers недоступен")
		_provider.queue_free()
		_provider = null
		return
	var layers: Array = layers_variant
	_layer_idx = layers.size()
	layers.append({
		"name": "Историческая иерархия (X/C/V/B)",
		"provider": _provider,
		"visible": false,
		"z_index": 94,
	})
	_main.set("_layers", layers)

	# Старые экспериментальные C/V/B физически не вырезаем из _layers:
	# удаление элемента сдвигает layer_idx десятков уже существующих слоёв.
	# Вместо этого X/C/V/B принадлежат только новой иерархии: autoload ловит
	# их в _input до старого _unhandled_input, а старые слои всегда скрыты.
	_force_legacy_conflicts_hidden()
	_ready_ok = true
	print("HistoricalHierarchy: готово. X=регионы, C=суперрегионы, V=макрорегионы, B=большие регионы; проверено province_id слоя 8: %d" % int(source_check.get("checked", 0)))


func _input(event: InputEvent) -> void:
	if not _ready_ok:
		return
	if not (event is InputEventKey):
		return
	var key_event := event as InputEventKey
	if not key_event.pressed or key_event.echo:
		return
	var key := key_event.physical_keycode
	if not TIER_BY_KEY.has(key):
		return

	_activate_tier(str(TIER_BY_KEY[key]))
	# КРИТИЧНО: TileMapViewer использует _unhandled_input для старых C/V/B.
	# Помечаем событие обработанным, поэтому конфликтующий старый слой не
	# включится поверх новой иерархии.
	get_viewport().set_input_as_handled()


func _activate_tier(tier: String) -> void:
	if _layer_idx < 0 or not is_instance_valid(_provider):
		return
	var layers: Array = _main.get("_layers")
	if _layer_idx >= layers.size():
		return

	# Повторное нажатие той же клавиши = выключить слой.
	if _active_tier == tier and bool(layers[_layer_idx].get("visible", false)):
		layers[_layer_idx]["visible"] = false
		_main.set("_layers", layers)
		_clear_visual_tiles()
		_set_status("Историческая иерархия: выключена")
		return

	var built := _build_province_mapping(tier)
	var province_to_group: Dictionary = built["mapping"]
	var group_ids: Array = built["group_ids"]
	var colors := _make_group_colors(group_ids, float(ALPHA_BY_TIER.get(tier, 0.50)))
	var stats: Dictionary = _provider.apply_grouping(province_to_group, colors)

	layers[_layer_idx]["visible"] = true
	layers[_layer_idx]["name"] = "Историческая иерархия — %s" % _tier_name(tier)
	_main.set("_layers", layers)
	_active_tier = tier
	_clear_visual_tiles()
	_force_legacy_conflicts_hidden()

	var text := "%s: %d групп, %d кусков слоя 8" % [
		_tier_name(tier), int(stats.get("groups", 0)), int(stats.get("matched_cells", 0))
	]
	_set_status(text)
	print("HistoricalHierarchy: ", text)


func _build_group_indexes() -> void:
	_groups_by_tier.clear()
	var tiers: Dictionary = _data.get("tiers", {})
	for tier in tiers.keys():
		var by_id: Dictionary = {}
		var tier_data: Dictionary = tiers[tier]
		for raw_group in tier_data.get("groups", []):
			var group: Dictionary = raw_group
			var group_id := str(group.get("id", ""))
			if not group_id.is_empty():
				by_id[group_id] = group
		_groups_by_tier[str(tier)] = by_id


func _validate_hierarchy_structure() -> bool:
	var ok := true
	var tiers: Dictionary = _data.get("tiers", {})

	if int(_data.get("source_of_truth_layer", -1)) != 8:
		push_error("HistoricalHierarchy: source_of_truth_layer обязан быть 8")
		ok = false
	if str(_data.get("province_source", "")) != PROVINCES_PATH:
		push_error("HistoricalHierarchy: province_source обязан быть %s" % PROVINCES_PATH)
		ok = false
	if not bool(_data.get("strict", false)):
		push_error("HistoricalHierarchy: hierarchy JSON обязан работать в strict=true")
		ok = false

	for required_tier in ["region", "superregion", "macroregion", "major_region"]:
		if not tiers.has(required_tier):
			push_error("HistoricalHierarchy: отсутствует обязательная ступень %s" % required_tier)
			ok = false

	# 1. IDs групп уникальны внутри каждой ступени; собственная геометрия
	# запрещена вообще. Верхний слой должен быть только объединением детей.
	for tier_raw in tiers.keys():
		var tier := str(tier_raw)
		var tier_data: Dictionary = tiers[tier_raw]
		var seen_group_ids: Dictionary = {}
		for raw_group in tier_data.get("groups", []):
			var group: Dictionary = raw_group
			var group_id := str(group.get("id", ""))
			if group_id.is_empty():
				push_error("HistoricalHierarchy: пустой id группы на ступени %s" % tier)
				ok = false
				continue
			if seen_group_ids.has(group_id):
				push_error("HistoricalHierarchy: повторный id группы %s на ступени %s" % [group_id, tier])
				ok = false
			seen_group_ids[group_id] = true

			for forbidden_field in FORBIDDEN_GEOMETRY_FIELDS:
				if group.has(forbidden_field):
					push_error("HistoricalHierarchy: %s содержит запрещённую собственную геометрию '%s'" % [group_id, forbidden_field])
					ok = false

	# 2. Region может ссылаться ТОЛЬКО на province_id слоя 8. Один province_id
	# не может быть сразу в двух регионах. Регион не смешивает страны.
	var region_seen_provinces: Dictionary = {}
	var region_groups: Dictionary = _groups_by_tier.get("region", {})
	for region_id_raw in region_groups.keys():
		var region_id := str(region_id_raw)
		var group: Dictionary = region_groups[region_id_raw]
		if group.has("children") or not group.has("province_ids"):
			push_error("HistoricalHierarchy: Region %s обязан содержать только province_ids" % region_id)
			ok = false
			continue
		if str(group.get("historical_basis", "")).strip_edges().is_empty():
			push_error("HistoricalHierarchy: Region %s не имеет historical_basis" % region_id)
			ok = false
		var sources: Array = group.get("sources", [])
		if sources.is_empty():
			push_error("HistoricalHierarchy: Region %s не имеет интернет-источника" % region_id)
			ok = false

		var country_prefixes: Dictionary = {}
		for raw_pid in group.get("province_ids", []):
			var pid := str(raw_pid)
			if pid.is_empty():
				push_error("HistoricalHierarchy: пустой province_id в %s" % region_id)
				ok = false
				continue
			if region_seen_provinces.has(pid):
				push_error("HistoricalHierarchy: %s одновременно в %s и %s" % [pid, region_seen_provinces[pid], region_id])
				ok = false
			else:
				region_seen_provinces[pid] = region_id
			var sep := pid.find("__")
			if sep > 0:
				country_prefixes[pid.substr(0, sep)] = true
		if country_prefixes.size() > 1:
			push_error("HistoricalHierarchy: Region %s смешивает провинции разных стран: %s" % [region_id, str(country_prefixes.keys())])
			ok = false

	# 3. Каждый верхний уровень обязан ссылаться РОВНО на предыдущую ступень.
	# Один ребёнок не может иметь двух родителей на одной ступени.
	for tier in CHILD_TIER_BY_TIER.keys():
		var expected_child_tier := str(CHILD_TIER_BY_TIER[tier])
		var child_index: Dictionary = _groups_by_tier.get(expected_child_tier, {})
		var by_id: Dictionary = _groups_by_tier.get(tier, {})
		var seen_children: Dictionary = {}
		for group_id_raw in by_id.keys():
			var group_id := str(group_id_raw)
			var group: Dictionary = by_id[group_id_raw]
			if group.has("province_ids"):
				push_error("HistoricalHierarchy: %s/%s не имеет права ссылаться напрямую на province_ids" % [tier, group_id])
				ok = false
			if not group.has("children"):
				push_error("HistoricalHierarchy: %s/%s не содержит children" % [tier, group_id])
				ok = false
				continue
			var child_tier := str(group.get("child_tier", ""))
			if child_tier != expected_child_tier:
				push_error("HistoricalHierarchy: %s/%s обязан иметь child_tier=%s, получено %s" % [tier, group_id, expected_child_tier, child_tier])
				ok = false
			var children: Array = group.get("children", [])
			if children.is_empty():
				push_error("HistoricalHierarchy: %s/%s имеет пустой children" % [tier, group_id])
				ok = false
			if tier == "superregion" and children.size() < 2:
				push_error("HistoricalHierarchy: суперрегион %s нарушает правило минимум 2 региона" % group_id)
				ok = false

			var local_seen: Dictionary = {}
			for raw_child in children:
				var child := str(raw_child)
				if local_seen.has(child):
					push_error("HistoricalHierarchy: %s дважды перечисляет child %s" % [group_id, child])
					ok = false
				local_seen[child] = true
				if not child_index.has(child):
					push_error("HistoricalHierarchy: %s -> неизвестный child %s (%s)" % [group_id, child, child_tier])
					ok = false
				if seen_children.has(child):
					push_error("HistoricalHierarchy: %s одновременно имеет двух родителей на %s: %s и %s" % [child, tier, seen_children[child], group_id])
					ok = false
				else:
					seen_children[child] = group_id

	# 4. Проверяем, что рекурсивная развёртка каждого объекта вообще даёт
	# province_id. Так невозможно создать красивое имя без реальной земли.
	for tier_raw in _groups_by_tier.keys():
		var tier := str(tier_raw)
		var by_id: Dictionary = _groups_by_tier[tier_raw]
		for group_id_raw in by_id.keys():
			var group_id := str(group_id_raw)
			var provinces := _collect_provinces(tier, group_id, {})
			if provinces.is_empty():
				push_error("HistoricalHierarchy: %s/%s не содержит провинций" % [tier, group_id])
				ok = false

	return ok


func _all_region_province_ids() -> Array:
	var result: Array = []
	var region_groups: Dictionary = _groups_by_tier.get("region", {})
	for region_id in region_groups.keys():
		var group: Dictionary = region_groups[region_id]
		for raw_pid in group.get("province_ids", []):
			var pid := str(raw_pid)
			if not result.has(pid):
				result.append(pid)
	result.sort()
	return result


func _collect_provinces(tier: String, group_id: String, visiting: Dictionary) -> Array:
	var visit_key := tier + ":" + group_id
	if visiting.has(visit_key):
		push_error("HistoricalHierarchy: цикл иерархии в %s" % visit_key)
		return []
	visiting[visit_key] = true

	var by_id: Dictionary = _groups_by_tier.get(tier, {})
	if not by_id.has(group_id):
		visiting.erase(visit_key)
		return []
	var group: Dictionary = by_id[group_id]
	var result: Array = []

	if group.has("province_ids"):
		for raw_pid in group.get("province_ids", []):
			var pid := str(raw_pid)
			if not result.has(pid):
				result.append(pid)
	else:
		var child_tier := str(group.get("child_tier", ""))
		for raw_child in group.get("children", []):
			for pid in _collect_provinces(child_tier, str(raw_child), visiting.duplicate()):
				if not result.has(pid):
					result.append(pid)

	visiting.erase(visit_key)
	return result


func _build_province_mapping(tier: String) -> Dictionary:
	var mapping: Dictionary = {}
	var conflicts: Dictionary = {}
	var group_ids: Array = []
	var by_id: Dictionary = _groups_by_tier.get(tier, {})

	for group_id_raw in by_id.keys():
		var group_id := str(group_id_raw)
		group_ids.append(group_id)
		for pid in _collect_provinces(tier, group_id, {}):
			if mapping.has(pid) and mapping[pid] != group_id:
				conflicts[pid] = true
			else:
				mapping[pid] = group_id

	# Строгий режим: конфликтующая провинция НЕ рисуется вообще. Это лучше,
	# чем молча выбрать одного из двух родителей и получить историческую ложь.
	for pid in conflicts.keys():
		mapping.erase(pid)
		push_error("HistoricalHierarchy: конфликт родителей для %s — скрыто" % pid)

	group_ids.sort()
	return {"mapping": mapping, "group_ids": group_ids}


func _make_group_colors(group_ids: Array, alpha: float) -> Dictionary:
	var colors: Dictionary = {}
	for i in range(group_ids.size()):
		var group_id := str(group_ids[i])
		# Золотое сечение даёт далеко разнесённые соседние оттенки; порядок
		# групп стабильный после sort(), поэтому цвета не прыгают между запусками.
		var hue := fmod(float(i) * 0.61803398875 + 0.08, 1.0)
		colors[group_id] = Color.from_hsv(hue, 0.48, 0.93, alpha)
	return colors


func _tier_name(tier: String) -> String:
	var tiers: Dictionary = _data.get("tiers", {})
	if tiers.has(tier):
		return str(tiers[tier].get("name_ru", tier))
	return tier


func _force_legacy_conflicts_hidden() -> void:
	if not is_instance_valid(_main):
		return
	var layers_variant = _main.get("_layers")
	if typeof(layers_variant) != TYPE_ARRAY:
		return
	var layers: Array = layers_variant
	# C = старый тест клеток; V/B = старые океанские debug-слои.
	# Не удаляем элементы из массива физически: это сдвинуло бы десятки
	# сохранённых layer_idx внутри TileMapViewer. Их клавиши перехвачены
	# новой иерархией выше, а видимость здесь всегда фиксируется false.
	for property_name in ["_cells_test_layer_idx", "_ocean_v_layer_idx", "_ocean_flat_layer_idx"]:
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
