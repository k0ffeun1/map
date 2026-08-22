extends RefCounted
## v3 historical hierarchy catalog.
##
## Core structural rules:
## - region -> superregion -> macroregion -> megaregion must be real scale steps;
## - every superregion contains at least 2 regions;
## - every macroregion contains at least 2 superregions;
## - every megaregion contains at least 2 macroregions;
## - neighbouring hierarchy levels cannot have identical names;
## - original Layer-8 province geometry/IDs are untouched.

const CATALOG_FORMAT := "historical_geographic_hierarchy_shard/v1"
const PACK_FORMAT := "historical_geographic_hierarchy_pack/v1"
const OVERRIDE_FORMAT := "historical_hierarchy_name_overrides/v1"
const STRUCTURE_FORMAT := "historical_hierarchy_structure_overrides/v1"
const OVERRIDE_FILE := "hierarchy_name_overrides.json"
const WORLD_PX := 8192.0

var super_defs: Array = []
var region_meta: Dictionary = {}
var super_meta: Dictionary = {}
var macro_meta: Dictionary = {}
var mega_meta: Dictionary = {}
var last_error := ""

var _macro_name_overrides: Dictionary = {}
var _mega_name_overrides: Dictionary = {}
var _structure_splits: Dictionary = {}
var _super_reassignments: Dictionary = {}


func load_from_dir(
	path: String,
	expected_regions: int,
	expected_supers: int,
	expected_macros: int,
	expected_megas: int
) -> bool:
	super_defs.clear()
	region_meta.clear()
	super_meta.clear()
	macro_meta.clear()
	mega_meta.clear()
	_macro_name_overrides.clear()
	_mega_name_overrides.clear()
	_structure_splits.clear()
	_super_reassignments.clear()
	last_error = ""

	if DirAccess.open(path) == null:
		last_error = "не найден каталог %s" % path
		return false

	if not _load_name_overrides(path.path_join(OVERRIDE_FILE)):
		return false
	if not _load_structure_overrides(path):
		return false

	var shard_files := _list_json_files(path, "shard_")
	if shard_files.is_empty():
		last_error = "в %s нет shard_*.json" % path
		return false

	for name in shard_files:
		var file_path := path.path_join(name)
		var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(file_path))
		if typeof(parsed) != TYPE_DICTIONARY:
			last_error = "неверный JSON %s" % file_path
			return false
		var shard: Dictionary = parsed
		var format := str(shard.get("format", ""))
		if format != CATALOG_FORMAT and format != PACK_FORMAT:
			last_error = "неверный format %s" % file_path
			return false

		var single_mega_value: Variant = shard.get("megaregion", {})
		if single_mega_value is Dictionary:
			var single_mega: Dictionary = single_mega_value
			if not single_mega.is_empty():
				_add_mega(single_mega)

		for mega_value in shard.get("megaregions", []):
			if mega_value is Dictionary:
				_add_mega(mega_value)

		for macro_value in shard.get("macroregions", []):
			if not macro_value is Dictionary:
				continue
			var source_macro: Dictionary = macro_value
			var macro: Dictionary = source_macro.duplicate(true)
			var macro_id := str(macro.get("id", ""))
			if macro_id.is_empty():
				last_error = "macroregion без id: %s" % file_path
				return false
			macro["name"] = _macro_name_for(macro_id, str(macro.get("name", macro_id)))
			macro_meta[macro_id] = macro

		for super_value in shard.get("superregions", []):
			if super_value is Dictionary:
				if not _add_super_with_structure(super_value):
					return false

	if region_meta.size() != expected_regions or super_defs.size() != expected_supers or macro_meta.size() != expected_macros or mega_meta.size() != expected_megas:
		last_error = "catalog counts: regions=%d/%d super=%d/%d macro=%d/%d mega=%d/%d" % [
			region_meta.size(), expected_regions,
			super_defs.size(), expected_supers,
			macro_meta.size(), expected_macros,
			mega_meta.size(), expected_megas,
		]
		return false

	if not _validate_distinct_adjacent_names():
		return false
	if not _validate_structural_depth():
		return false

	return true


func _list_json_files(path: String, prefix: String) -> Array[String]:
	var result: Array[String] = []
	var dir := DirAccess.open(path)
	if dir == null:
		return result
	dir.list_dir_begin()
	var file_name := dir.get_next()
	while not file_name.is_empty():
		if not dir.current_is_dir() and file_name.begins_with(prefix) and file_name.ends_with(".json"):
			result.append(file_name)
		file_name = dir.get_next()
	dir.list_dir_end()
	result.sort()
	return result


func _load_name_overrides(file_path: String) -> bool:
	if not FileAccess.file_exists(file_path):
		last_error = "не найден файл имён %s" % file_path
		return false
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(file_path))
	if typeof(parsed) != TYPE_DICTIONARY:
		last_error = "неверный JSON имён %s" % file_path
		return false
	var data: Dictionary = parsed
	if str(data.get("format", "")) != OVERRIDE_FORMAT:
		last_error = "неверный format имён %s" % file_path
		return false
	var macro_value: Variant = data.get("macroregion_names", {})
	if macro_value is Dictionary:
		_macro_name_overrides = (macro_value as Dictionary).duplicate(true)
	var mega_value: Variant = data.get("megaregion_names", {})
	if mega_value is Dictionary:
		_mega_name_overrides = (mega_value as Dictionary).duplicate(true)
	return true


func _load_structure_overrides(path: String) -> bool:
	var files := _list_json_files(path, "structure_")
	if files.is_empty():
		last_error = "не найдены structure_*.json для v3"
		return false

	for name in files:
		var file_path := path.path_join(name)
		var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(file_path))
		if typeof(parsed) != TYPE_DICTIONARY:
			last_error = "неверный structural JSON %s" % file_path
			return false
		var data: Dictionary = parsed
		if str(data.get("format", "")) != STRUCTURE_FORMAT:
			last_error = "неверный structural format %s" % file_path
			return false

		var splits_value: Variant = data.get("splits", {})
		if splits_value is Dictionary:
			var split_dict: Dictionary = splits_value
			for source_id_value in split_dict.keys():
				var source_id := str(source_id_value)
				if _structure_splits.has(source_id):
					last_error = "повторный structural split %s" % source_id
					return false
				_structure_splits[source_id] = split_dict[source_id_value]

		var reassign_value: Variant = data.get("reassign_superregions", {})
		if reassign_value is Dictionary:
			var reassign_dict: Dictionary = reassign_value
			for super_id_value in reassign_dict.keys():
				var super_id := str(super_id_value)
				if _super_reassignments.has(super_id):
					last_error = "повторный reassign %s" % super_id
					return false
				_super_reassignments[super_id] = reassign_dict[super_id_value]

	return true


func _add_super_with_structure(value: Dictionary) -> bool:
	var source: Dictionary = value.duplicate(true)
	var source_id := str(source.get("id", ""))
	if source_id.is_empty():
		last_error = "superregion без id"
		return false

	var split_value: Variant = _structure_splits.get(source_id, [])
	if split_value is Array and not (split_value as Array).is_empty():
		var replacements: Array = split_value
		var source_regions: Dictionary = {}
		for region_value in source.get("regions", []):
			if not region_value is Dictionary:
				continue
			var region: Dictionary = region_value
			var region_id := str(region.get("id", ""))
			if not region_id.is_empty():
				source_regions[region_id] = region

		var used: Dictionary = {}
		for replacement_value in replacements:
			if not replacement_value is Dictionary:
				last_error = "%s: replacement не Dictionary" % source_id
				return false
			var replacement: Dictionary = replacement_value
			var derived: Dictionary = source.duplicate(true)
			derived["id"] = str(replacement.get("id", ""))
			derived["name"] = str(replacement.get("name", ""))
			derived["seed_lon"] = float(replacement.get("seed_lon", source.get("seed_lon", 0.0)))
			derived["seed_lat"] = float(replacement.get("seed_lat", source.get("seed_lat", 0.0)))

			if str(derived.get("id", "")).is_empty() or str(derived.get("name", "")).is_empty():
				last_error = "%s: replacement без id/name" % source_id
				return false

			var derived_regions: Array = []
			var ids_value: Variant = replacement.get("region_ids", [])
			if not ids_value is Array:
				last_error = "%s: region_ids не Array" % str(derived.get("id", ""))
				return false
			for region_id_value in ids_value:
				var region_id := str(region_id_value)
				if not source_regions.has(region_id):
					last_error = "%s: неизвестный region %s" % [source_id, region_id]
					return false
				if used.has(region_id):
					last_error = "%s: region %s использован дважды" % [source_id, region_id]
					return false
				used[region_id] = true
				var source_region: Dictionary = source_regions[region_id]
				derived_regions.append(source_region.duplicate(true))

			if derived_regions.size() < 2:
				last_error = "%s: superregion должен иметь минимум 2 региона" % str(derived.get("name", ""))
				return false
			derived["regions"] = derived_regions
			if not _apply_super_reassignment(derived):
				return false
			_add_super(derived)

		if used.size() != source_regions.size():
			last_error = "%s: structural split покрыл %d/%d регионов" % [source_id, used.size(), source_regions.size()]
			return false
		return true

	if not _apply_super_reassignment(source):
		return false
	_add_super(source)
	return true


func _apply_super_reassignment(super_def: Dictionary) -> bool:
	var super_id := str(super_def.get("id", ""))
	var reassignment_value: Variant = _super_reassignments.get(super_id, {})
	if not reassignment_value is Dictionary or (reassignment_value as Dictionary).is_empty():
		return true

	var reassignment: Dictionary = reassignment_value
	var target_macro_id := str(reassignment.get("macroregion_id", ""))
	if target_macro_id.is_empty() or not macro_meta.has(target_macro_id):
		last_error = "%s: target macroregion %s не найден" % [super_id, target_macro_id]
		return false

	var target_macro: Dictionary = macro_meta[target_macro_id]
	super_def["macroregion_id"] = target_macro_id
	super_def["macroregion_name"] = str(target_macro.get("name", target_macro_id))

	var target_mega_id := str(target_macro.get("megaregion_id", ""))
	if target_mega_id.is_empty() or not mega_meta.has(target_mega_id):
		last_error = "%s: target megaregion %s не найден" % [super_id, target_mega_id]
		return false
	var target_mega: Dictionary = mega_meta[target_mega_id]
	super_def["megaregion_id"] = target_mega_id
	super_def["megaregion_name"] = str(target_mega.get("name", target_mega_id))
	return true


func _macro_name_for(macro_id: String, fallback: String) -> String:
	if _macro_name_overrides.has(macro_id):
		return str(_macro_name_overrides[macro_id])
	return fallback


func _mega_name_for(mega_id: String, fallback: String) -> String:
	if _mega_name_overrides.has(mega_id):
		return str(_mega_name_overrides[mega_id])
	return fallback


func _add_mega(value: Dictionary) -> void:
	var mega: Dictionary = value.duplicate(true)
	var mega_id := str(mega.get("id", ""))
	if mega_id.is_empty():
		return
	mega["name"] = _mega_name_for(mega_id, str(mega.get("name", mega_id)))
	mega_meta[mega_id] = mega


func _add_super(value: Dictionary) -> void:
	var super_def: Dictionary = value.duplicate(true)
	var super_id := str(super_def.get("id", ""))
	if super_id.is_empty():
		return

	var macro_id := str(super_def.get("macroregion_id", ""))
	if macro_meta.has(macro_id):
		var macro: Dictionary = macro_meta[macro_id]
		super_def["macroregion_name"] = str(macro.get("name", macro_id))
	else:
		super_def["macroregion_name"] = _macro_name_for(macro_id, str(super_def.get("macroregion_name", macro_id)))

	var mega_id := str(super_def.get("megaregion_id", ""))
	if mega_meta.has(mega_id):
		var mega: Dictionary = mega_meta[mega_id]
		super_def["megaregion_name"] = str(mega.get("name", mega_id))
	else:
		super_def["megaregion_name"] = _mega_name_for(mega_id, str(super_def.get("megaregion_name", mega_id)))

	super_def["seed_world"] = lonlat_to_world(
		float(super_def.get("seed_lon", 0.0)),
		float(super_def.get("seed_lat", 0.0))
	)
	super_defs.append(super_def)
	super_meta[super_id] = {
		"id": super_id,
		"name": str(super_def.get("name", super_id)),
		"macroregion_id": macro_id,
		"macroregion_name": str(super_def.get("macroregion_name", "")),
		"megaregion_id": mega_id,
		"megaregion_name": str(super_def.get("megaregion_name", "")),
	}

	for region_value in super_def.get("regions", []):
		if not region_value is Dictionary:
			continue
		var region: Dictionary = region_value
		var region_id := str(region.get("id", ""))
		if region_id.is_empty():
			continue
		region_meta[region_id] = {
			"id": region_id,
			"name": str(region.get("name", region_id)),
			"superregion_id": super_id,
			"superregion_name": str(super_def.get("name", "")),
			"macroregion_id": macro_id,
			"macroregion_name": str(super_def.get("macroregion_name", "")),
			"megaregion_id": mega_id,
			"megaregion_name": str(super_def.get("megaregion_name", "")),
		}


func _validate_distinct_adjacent_names() -> bool:
	for region_value in region_meta.values():
		if not region_value is Dictionary:
			continue
		var region: Dictionary = region_value
		if _same_name(str(region.get("name", "")), str(region.get("superregion_name", ""))):
			last_error = "дублирование region/superregion: %s" % str(region.get("name", ""))
			return false

	for super_value in super_defs:
		if not super_value is Dictionary:
			continue
		var super_def: Dictionary = super_value
		var super_name := str(super_def.get("name", ""))
		var macro_name := str(super_def.get("macroregion_name", ""))
		var mega_name := str(super_def.get("megaregion_name", ""))
		if _same_name(super_name, macro_name):
			last_error = "дублирование superregion/macroregion: %s" % super_name
			return false
		if _same_name(macro_name, mega_name):
			last_error = "дублирование macroregion/megaregion: %s" % macro_name
			return false
	return true


func _validate_structural_depth() -> bool:
	var macro_super_count: Dictionary = {}
	for super_value in super_defs:
		if not super_value is Dictionary:
			continue
		var super_def: Dictionary = super_value
		var regions_value: Variant = super_def.get("regions", [])
		var region_count := regions_value.size() if regions_value is Array else 0
		if region_count < 2:
			last_error = "superregion %s содержит только %d регион(ов)" % [str(super_def.get("name", "")), region_count]
			return false
		var macro_id := str(super_def.get("macroregion_id", ""))
		macro_super_count[macro_id] = int(macro_super_count.get(macro_id, 0)) + 1

	for macro_id_value in macro_meta.keys():
		var macro_id := str(macro_id_value)
		var count := int(macro_super_count.get(macro_id, 0))
		if count < 2:
			var macro: Dictionary = macro_meta[macro_id]
			last_error = "macroregion %s содержит только %d superregion(ов)" % [str(macro.get("name", macro_id)), count]
			return false

	var mega_macro_count: Dictionary = {}
	for macro_value in macro_meta.values():
		if not macro_value is Dictionary:
			continue
		var macro: Dictionary = macro_value
		var mega_id := str(macro.get("megaregion_id", ""))
		mega_macro_count[mega_id] = int(mega_macro_count.get(mega_id, 0)) + 1

	for mega_id_value in mega_meta.keys():
		var mega_id := str(mega_id_value)
		var count := int(mega_macro_count.get(mega_id, 0))
		if count < 2:
			var mega: Dictionary = mega_meta[mega_id]
			last_error = "megaregion %s содержит только %d macroregion(ов)" % [str(mega.get("name", mega_id)), count]
			return false

	return true


func _same_name(a: String, b: String) -> bool:
	if a.is_empty() or b.is_empty():
		return false
	return a.strip_edges().to_lower() == b.strip_edges().to_lower()


func lonlat_to_world(lon: float, lat: float) -> Vector2:
	var x := (lon + 180.0) / 360.0 * WORLD_PX
	var safe_lat := clampf(lat, -85.05112878, 85.05112878)
	var lat_rad := deg_to_rad(safe_lat)
	var y := (1.0 - asinh(tan(lat_rad)) / PI) * 0.5 * WORLD_PX
	return Vector2(fposmod(x, WORLD_PX), y)
