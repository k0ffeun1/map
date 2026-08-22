extends RefCounted
## Loads the from-scratch historical hierarchy catalog shards.

const CATALOG_FORMAT := "historical_geographic_hierarchy_shard/v1"
const PACK_FORMAT := "historical_geographic_hierarchy_pack/v1"
const WORLD_PX := 8192.0

var super_defs: Array = []
var region_meta: Dictionary = {}
var super_meta: Dictionary = {}
var macro_meta: Dictionary = {}
var mega_meta: Dictionary = {}
var last_error := ""


func load_from_dir(path: String, expected_regions: int, expected_supers: int, expected_macros: int, expected_megas: int) -> bool:
	super_defs.clear(); region_meta.clear(); super_meta.clear(); macro_meta.clear(); mega_meta.clear(); last_error = ""
	var dir := DirAccess.open(path)
	if dir == null:
		last_error = "не найден каталог %s" % path
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

		var single_mega: Variant = shard.get("megaregion", {})
		if single_mega is Dictionary and not (single_mega as Dictionary).is_empty():
			_add_mega(single_mega)
		for mega_value in shard.get("megaregions", []):
			if mega_value is Dictionary:
				_add_mega(mega_value)
		for macro_value in shard.get("macroregions", []):
			if macro_value is Dictionary:
				var macro: Dictionary = macro_value
				macro_meta[str(macro.get("id", ""))] = macro
		for super_value in shard.get("superregions", []):
			if super_value is Dictionary:
				_add_super(super_value)

	if region_meta.size() != expected_regions or super_defs.size() != expected_supers or macro_meta.size() != expected_macros or mega_meta.size() != expected_megas:
		last_error = "catalog counts: regions=%d/%d super=%d/%d macro=%d/%d mega=%d/%d" % [
			region_meta.size(), expected_regions, super_defs.size(), expected_supers,
			macro_meta.size(), expected_macros, mega_meta.size(), expected_megas,
		]
		return false
	return true


func _add_mega(value: Dictionary) -> void:
	mega_meta[str(value.get("id", ""))] = value


func _add_super(value: Dictionary) -> void:
	var super_def: Dictionary = value.duplicate(true)
	var super_id := str(super_def.get("id", ""))
	super_def["seed_world"] = lonlat_to_world(float(super_def.get("seed_lon", 0.0)), float(super_def.get("seed_lat", 0.0)))
	super_defs.append(super_def)
	super_meta[super_id] = {
		"id": super_id,
		"name": str(super_def.get("name", super_id)),
		"macroregion_id": str(super_def.get("macroregion_id", "")),
		"macroregion_name": str(super_def.get("macroregion_name", "")),
		"megaregion_id": str(super_def.get("megaregion_id", "")),
		"megaregion_name": str(super_def.get("megaregion_name", "")),
	}
	for region_value in super_def.get("regions", []):
		if not region_value is Dictionary:
			continue
		var region: Dictionary = region_value
		var region_id := str(region.get("id", ""))
		region_meta[region_id] = {
			"id": region_id,
			"name": str(region.get("name", region_id)),
			"superregion_id": super_id,
			"superregion_name": str(super_def.get("name", "")),
			"macroregion_id": str(super_def.get("macroregion_id", "")),
			"macroregion_name": str(super_def.get("macroregion_name", "")),
			"megaregion_id": str(super_def.get("megaregion_id", "")),
			"megaregion_name": str(super_def.get("megaregion_name", "")),
		}


func lonlat_to_world(lon: float, lat: float) -> Vector2:
	var x := (lon + 180.0) / 360.0 * WORLD_PX
	var safe_lat := clampf(lat, -85.05112878, 85.05112878)
	var lat_rad := deg_to_rad(safe_lat)
	var y := (1.0 - asinh(tan(lat_rad)) / PI) * 0.5 * WORLD_PX
	return Vector2(fposmod(x, WORLD_PX), y)
