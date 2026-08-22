extends "res://scripts/WorldRegionsDraftViewer.gd"
## Final I viewer: same cached renderer, but fed by automatic sliver cleanup
## plus persistent manual overrides.

const FINAL_DATA_PATH := "res://assets/regions_world_final.json"
const FINAL_ASSIGNMENTS_PATH := "res://assets/game_data/world_region_assignments_final.json"
const FINAL_EXPECTED_FORMAT := "world_regions_final/v1"


func _load_data() -> bool:
	if not FileAccess.file_exists(FINAL_DATA_PATH):
		return _fail("не найден %s — дождись final cleanup / сделай git pull" % FINAL_DATA_PATH)
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(FINAL_DATA_PATH))
	if typeof(parsed) != TYPE_DICTIONARY:
		return _fail("regions_world_final.json имеет неверный JSON")
	var data: Dictionary = parsed
	if str(data.get("format", "")) != FINAL_EXPECTED_FORMAT:
		return _fail("ожидался формат %s" % FINAL_EXPECTED_FORMAT)

	_parts.clear()
	_region_name_by_id.clear()
	_province_count_by_region.clear()
	_region_count = int(data.get("region_count", 0))
	_province_count = int(data.get("province_count", 0))
	_piece_count = int(data.get("polygon_piece_count", 0))
	for raw in data.get("cells", []):
		if not raw is Dictionary:
			continue
		var cell: Dictionary = raw
		var region_id := str(cell.get("region_id", ""))
		var name := str(cell.get("name", region_id))
		var rings := _to_rings(cell.get("rings", []))
		if region_id.is_empty() or rings.is_empty():
			continue
		_parts.append({
			"id": str(cell.get("id", "")),
			"region_id": region_id,
			"name": name,
			"bbox": cell.get("bbox", []),
			"rings": rings,
		})
		_region_name_by_id[region_id] = name

	if FileAccess.file_exists(FINAL_ASSIGNMENTS_PATH):
		var ap: Variant = JSON.parse_string(FileAccess.get_file_as_string(FINAL_ASSIGNMENTS_PATH))
		if typeof(ap) == TYPE_DICTIONARY:
			for raw_assignment in (ap as Dictionary).get("assignments", []):
				if raw_assignment is Dictionary:
					var rid := str((raw_assignment as Dictionary).get("region_id", ""))
					if not rid.is_empty():
						_province_count_by_region[rid] = int(_province_count_by_region.get(rid, 0)) + 1

	if _parts.is_empty():
		return _fail("финальный мировой слой не содержит polygon parts")
	_last_error = ""
	return true
