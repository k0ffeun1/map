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
## Главное правило проекта: принадлежность определяется ТОЛЬКО явными
## стабильными province_id слоя 8 из assets/historical_hierarchy.json.
## Координатных эвристик здесь принципиально нет.

const HIERARCHY_PATH := "res://assets/historical_hierarchy.json"
const PROVINCES_PATH := "res://assets/provinces.json"
const PROVIDER_SCRIPT := preload("res://scripts/HistoricalHierarchyProvider.gd")

const TIER_BY_KEY := {
	KEY_X: "region",
	KEY_C: "superregion",
	KEY_V: "macroregion",
	KEY_B: "major_region",
}

const ALPHA_BY_TIER := {
	"region": 0.58,
	"superregion": 0.52,
	"macroregion": 0.46,
	"major_region": 0.40,
}

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
	if not _validate_hierarchy():
		push_error("HistoricalHierarchy: строгая валидация не пройдена; слой не подключён")
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

	var layers_variant = _main.get("_layers")
	if typeof(layers_variant) != TYPE_ARRAY:
		push_error("HistoricalHierarchy: Main._layers недоступен")
		_provider.queue_free()
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

	# Старые экспериментальные C/V/B остаются в коде для истории разработки,
	# но принудительно выключены. Их прежние клавиши ниже никогда до них не
	# доходят: этот autoload обрабатывает событие на стадии _input.
	_force_legacy_conflicts_hidden()
	_ready_ok = true
	print("HistoricalHierarchy: готово. X=регионы, C=суперрегионы, V=макрорегионы, B=большие регионы")


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


func _validate_hierarchy() -> bool:
	var ok := true
	var region_seen_provinces: Dictionary = {}
	var tiers: Dictionary = _data.get("tiers", {})

	# 1. На Region один province_id не может принадлежать двум регионам.
	var region_groups: Dictionary = _groups_by_tier.get("region", {})
	for region_id in region_groups.keys():
		var group: Dictionary = region_groups[region_id]
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

	# 2. Каждый child обязан реально существовать на указанной ступени.
	for tier in tiers.keys():
		var by_id: Dictionary = _groups_by_tier.get(str(tier), {})
		for group_id in by_id.keys():
			var group: Dictionary = by_id[group_id]
			if group.has("children"):
				var child_tier := str(group.get("child_tier", ""))
				var child_index: Dictionary = _groups_by_tier.get(child_tier, {})
				var children: Array = group.get("children", [])
				if str(tier) == "superregion" and children.size() < 2:
					push_error("HistoricalHierarchy: суперрегион %s нарушает правило минимум 2 региона" % group_id)
					ok = false
				for raw_child in children:
					var child := str(raw_child)
					if not child_index.has(child):
						push_error("HistoricalHierarchy: %s -> неизвестный child %s (%s)" % [group_id, child, child_tier])
						ok = false

	# 3. Проверяем, что рекурсивная развёртка вообще даёт province_id.
	for tier in _groups_by_tier.keys():
		var by_id: Dictionary = _groups_by_tier[tier]
		for group_id in by_id.keys():
			var provinces := _collect_provinces(str(tier), str(group_id), {})
			if provinces.is_empty():
				push_error("HistoricalHierarchy: %s/%s не содержит провинций" % [tier, group_id])
				ok = false
	return ok


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
	# сохранённых layer_idx внутри TileMapViewer. Вместо этого их горячие
	# клавиши полностью перехвачены выше, а видимость зафиксирована false.
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
