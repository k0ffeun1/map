extends RefCounted
## Loads the from-scratch historical hierarchy catalog shards.
##
## v2 naming rule:
## neighbouring hierarchy levels must never repeat the same geographic name.
## Canonical corrections live in hierarchy_name_overrides.json so IDs and
## Layer-8 geometry stay stable while names can be refined independently.

const CATALOG_FORMAT := "historical_geographic_hierarchy_shard/v1"
const PACK_FORMAT := "historical_geographic_hierarchy_pack/v1"
const OVERRIDE_FORMAT := "historical_hierarchy_name_overrides/v1"
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
	last_error = ""

	var dir := DirAccess.open(path)
	if dir == null:
		last_error = "не найден каталог %s" % path
		return false

	if not _load_name_overrides(path.path_join(OVERRIDE_FILE)):
		return false

	var files: Array[String] = []
	dir.list_dir_begin()
	var file_name := dir.get_next()
	while not file_name.is_empty():
		if not dir.current_is_dir() and file_name.begins_with("shard_") and file_name.ends_with(".json"):
			files.append(file_name)
		file_name = dir.get_next()
	dir.list_dir_end()
	files.sort()

	for name in files:
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
				var mega: Dictionary = mega_value
				_add_mega(mega)

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
				var super_def: Dictionary = super_value
				_add_super(super_def)

	if region_meta.size() != expected_regions or super_defs.size() != expected_supers or macro_meta.size() != expected_macros or mega_meta.size() != expected_megas:
		last_error = "catalog counts: regions=%d/%d super=%d/%d macro=%d/%d mega=%d/%d" % [
			region_meta.size(),
			expected_regions,
			super_defs.size(),
			expected_supers,
			macro_meta.size(),
			expected_macros,
			mega_meta.size(),
			expected_megas,
		]
		return false

	if not _validate_distinct_adjacent_names():
		return false

	return true


func _load_name_overrides(file_path: String) -> bool:
	if not FileAccess.file_exists(file_path):
		last_error = "не найден файл исправлений иерархии %s" % file_path
		return false

	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(file_path))
	if typeof(parsed) != TYPE_DICTIONARY:
		last_error = "неверный JSON исправлений иерархии %s" % file_path
		return false

	var data: Dictionary = parsed
	if str(data.get("format", "")) != OVERRIDE_FORMAT:
		last_error = "неверный format исправлений иерархии %s" % file_path
		return false

	var macro_value: Variant = data.get("macroregion_names", {})
	if macro_value is Dictionary:
		_macro_name_overrides = (macro_value as Dictionary).duplicate(true)

	var mega_value: Variant = data.get("megaregion_names", {})
	if mega_value is Dictionary:
		_mega_name_overrides = (mega_value as Dictionary).duplicate(true)

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
	if not macro_id.is_empty():
		super_def["macroregion_name"] = _macro_name_for(
			macro_id,
			str(super_def.get("macroregion_name", macro_id))
		)

	var mega_id := str(super_def.get("megaregion_id", ""))
	if not mega_id.is_empty():
		super_def["megaregion_name"] = _mega_name_for(
			mega_id,
			str(super_def.get("megaregion_name", mega_id))
		)

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
