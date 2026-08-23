class_name HistoricalHierarchyProvider
extends IrregularCellProvider
## Визуальный provider для исторической территориальной иерархии.
##
## ВАЖНО: геометрия НЕ создаётся заново и НЕ определяется по координатам.
## Этот provider загружает ТОТ ЖЕ assets/provinces.json, что и слой 8,
## а затем только:
##   1) скрывает провинции, которых нет в проверенной иерархии;
##   2) красит все куски одной проверенной группы одним цветом.
##
## Поэтому регион/суперрегион/макрорегион физически не может "уехать" в
## другую часть карты из-за bbox/центроида/эвристики. Источник геометрии —
## исключительно стабильные province_id слоя 8.


func validate_source_province_ids(province_ids: Array) -> Dictionary:
	## Проверяет, что КАЖДЫЙ province_id иерархии реально существует в том же
	## provinces.json, который уже загружен provider'ом для слоя 8.
	##
	## У одной исходной провинции могут быть дополнительные геометрические
	## куски с суффиксами _2/_3/_ov1. Поэтому существованием считаем либо
	## точный id, либо хотя бы один такой кусок с префиксом province_id + "_".
	var missing: Array = []
	var ids: Array = province_ids.duplicate()
	ids.sort()

	for raw_id in ids:
		var province_id := str(raw_id)
		var found := false
		for cell in _cells:
			var cell_id := str(cell.get("id", ""))
			if cell_id == province_id or cell_id.begins_with(province_id + "_"):
				found = true
				break
		if not found:
			missing.append(province_id)

	return {
		"ok": missing.is_empty(),
		"missing": missing,
		"checked": ids.size(),
	}


func apply_grouping(province_to_group: Dictionary, group_colors: Dictionary) -> Dictionary:
	var hidden_ids: Array = []
	var matched_cells := 0
	var unmatched_cells := 0
	var used_groups: Dictionary = {}

	# Базовые province_id могут иметь несколько геометрических кусков:
	# foo, foo_2, foo_3, foo_ov1. Сначала проверяем длинные id, чтобы более
	# короткий префикс случайно не перехватил более конкретный.
	var province_ids: Array = province_to_group.keys()
	province_ids.sort_custom(func(a, b) -> bool:
		return str(a).length() > str(b).length()
	)

	for cell in _cells:
		var cell_id := str(cell.get("id", ""))
		var province_id := _resolve_base_province_id(cell_id, province_ids)
		if province_id.is_empty():
			hidden_ids.append(cell_id)
			unmatched_cells += 1
			continue

		var group_id := str(province_to_group.get(province_id, ""))
		if group_id.is_empty() or not group_colors.has(group_id):
			hidden_ids.append(cell_id)
			unmatched_cells += 1
			continue

		cell["color"] = group_colors[group_id]
		used_groups[group_id] = true
		matched_cells += 1

	set_hidden_cell_ids(hidden_ids)
	_tex.clear()
	return {
		"matched_cells": matched_cells,
		"unmatched_cells": unmatched_cells,
		"groups": used_groups.size(),
	}


func _resolve_base_province_id(cell_id: String, province_ids: Array) -> String:
	for raw_id in province_ids:
		var province_id := str(raw_id)
		if cell_id == province_id:
			return province_id
		# build_provinces.py добавляет суффиксы только к дополнительным кускам
		# одной и той же исходной провинции. Для иерархии все они обязаны
		# наследовать одного родителя.
		if cell_id.begins_with(province_id + "_"):
			return province_id
	return ""
