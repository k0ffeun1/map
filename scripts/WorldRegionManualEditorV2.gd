extends Node2D
## Safe manual editor for the final world-region layer.
##
## IMPORTANT: province hit-testing uses the EXACT SAME canonical geometry as
## layer 8: res://assets/provinces.json.  The old editor used the numeric
## mirror assets/map_geometry/provinces.json, which can become stale when the
## layer-8 build changes ordering/filtered island pieces.  We now translate the
## stable layer-8 legacy id -> numeric province id through game_data/provinces.
##
## I          show/hide world regions (viewer)
## E          editor on/off
## LMB        source whole region
## Alt + LMB  source one exact layer-8 province
## RMB        target region
## Enter      save operation
## Z          remove last operation
## S          save file
## Esc        clear / exit

const ASSIGNMENTS_FINAL := "res://assets/game_data/world_region_assignments_final.json"
const ASSIGNMENTS_FALLBACK := "res://assets/game_data/world_region_assignments_island_corrected.json"
const LAYER8_PATH := "res://assets/provinces.json"
const IDENTITIES_PATH := "res://assets/game_data/provinces.json"
const OVERRIDES_PATH := "res://assets/game_data/world_region_manual_overrides.json"
const OVERRIDES_FALLBACK := "user://world_region_manual_overrides.json"

const SOURCE_COLOR := Color(1.0, 0.42, 0.18, 1.0)

var _viewer: Node
var _ui: CanvasLayer
var _panel: PanelContainer
var _label: Label
var _edit_mode := false

var _source_mode := ""
var _source_region_id := ""
var _source_region_name := ""
var _source_province_id := ""
var _source_province_name := ""
var _source_legacy_id := ""
var _source_country_prefix := ""
var _source_province_rings: Array = []
var _target_region_id := ""
var _target_region_name := ""

var _assignments_by_id: Dictionary = {}
var _identity_by_legacy: Dictionary = {}
var _province_records: Array[Dictionary] = []
var _province_geometry_loaded := false
var _missing_identity_count := 0
var _operations: Array = []
var _last_saved_path := ""


func _ready() -> void:
	_viewer = get_node_or_null("../WorldRegionsDraftViewer")
	_ui = get_node_or_null("../UI") as CanvasLayer
	z_index = 500
	_load_assignments()
	_load_identities()
	_load_overrides()
	_build_panel()
	set_process_input(true)
	visible = true


func _input(event: InputEvent) -> void:
	var key := event as InputEventKey
	if key != null and key.pressed and not key.echo:
		if key.physical_keycode == KEY_E or key.keycode == KEY_E:
			if _viewer_active():
				_edit_mode = not _edit_mode
				if not _edit_mode:
					_clear_selection()
				_update_panel()
				_show("Редактор регионов: %s" % ("ВКЛ" if _edit_mode else "ВЫКЛ"))
				get_viewport().set_input_as_handled()
			return
		if not _edit_mode:
			return
		if key.physical_keycode == KEY_ESCAPE or key.keycode == KEY_ESCAPE:
			if not _source_mode.is_empty() or not _target_region_id.is_empty():
				_clear_selection()
			else:
				_edit_mode = false
			_update_panel()
			get_viewport().set_input_as_handled()
			return
		if key.physical_keycode == KEY_ENTER or key.keycode == KEY_ENTER or key.physical_keycode == KEY_KP_ENTER:
			_apply_pending_override()
			get_viewport().set_input_as_handled()
			return
		if key.physical_keycode == KEY_Z or key.keycode == KEY_Z:
			_undo_last_override()
			get_viewport().set_input_as_handled()
			return
		if key.physical_keycode == KEY_S or key.keycode == KEY_S:
			_save_overrides()
			_show("Overrides сохранены: %s" % _last_saved_path)
			get_viewport().set_input_as_handled()
			return

	if not _edit_mode or not _viewer_active():
		return
	var mouse := event as InputEventMouseButton
	if mouse == null or not mouse.pressed:
		return
	if mouse.button_index == MOUSE_BUTTON_LEFT:
		if mouse.alt_pressed:
			_select_source_province(get_global_mouse_position())
		else:
			_select_source_region(get_global_mouse_position())
		get_viewport().set_input_as_handled()
	elif mouse.button_index == MOUSE_BUTTON_RIGHT:
		_select_target_region(get_global_mouse_position())
		get_viewport().set_input_as_handled()


func _viewer_active() -> bool:
	return is_instance_valid(_viewer) and bool(_viewer.get("visible"))


func _select_source_region(point: Vector2) -> void:
	var hit: Dictionary = _viewer.call("_part_at_point", point)
	if hit.is_empty():
		_show("Редактор: под курсором нет региона")
		return
	_clear_source_highlight()
	_source_mode = "region"
	_source_region_id = str(hit.get("region_id", ""))
	_source_region_name = str(hit.get("name", _source_region_id))
	_source_province_id = ""
	_source_province_name = ""
	_source_legacy_id = ""
	_source_country_prefix = ""
	_source_province_rings.clear()
	_set_region_edit_role(_source_region_id, 1)
	queue_redraw()
	_update_panel()
	_show("ИСТОЧНИК-регион: %s • ПКМ по целевому региону" % _source_region_name)


func _select_source_province(point: Vector2) -> void:
	_ensure_province_geometry()
	var hit := _province_at_point(point)
	if hit.is_empty():
		_show("Редактор: под курсором нет провинции слоя 8")
		return
	_clear_source_highlight()
	_source_mode = "province"
	_source_province_id = str(hit.get("province_id", ""))
	_source_province_name = str(hit.get("name", _source_province_id))
	_source_legacy_id = str(hit.get("legacy_id", ""))
	_source_country_prefix = str(hit.get("country_prefix", ""))
	_source_province_rings = hit.get("rings", [])
	var assignment: Dictionary = _assignments_by_id.get(_source_province_id, {})
	_source_region_id = str(assignment.get("region_id", ""))
	_source_region_name = str(assignment.get("region_name", _source_region_id))
	queue_redraw()
	_update_panel()
	_show("ИСТОЧНИК: %s • %s • %s • регион %s" % [_source_province_name, _source_country_prefix, _source_legacy_id, _source_region_name])


func _select_target_region(point: Vector2) -> void:
	var hit: Dictionary = _viewer.call("_part_at_point", point)
	if hit.is_empty():
		_show("Редактор: под курсором нет целевого региона")
		return
	_clear_target_highlight()
	_target_region_id = str(hit.get("region_id", ""))
	_target_region_name = str(hit.get("name", _target_region_id))
	_set_region_edit_role(_target_region_id, 2)
	_update_panel()
	_show("ЦЕЛЬ: %s • Enter применить" % _target_region_name)


func _apply_pending_override() -> void:
	if _source_mode.is_empty() or _target_region_id.is_empty():
		_show("Редактор: сначала ЛКМ источник, затем ПКМ цель")
		return
	if _source_region_id == _target_region_id:
		_show("Редактор: источник уже находится в целевом регионе")
		return

	var op: Dictionary = {
		"mode": "move_province" if _source_mode == "province" else "merge_region",
		"target_region_id": _target_region_id,
		"target_region_name": _target_region_name,
	}
	if _source_mode == "province":
		op["source_province_id"] = _source_province_id
		op["source_province_name"] = _source_province_name
		op["source_legacy_id_at_edit"] = _source_legacy_id
		op["source_country_prefix_at_edit"] = _source_country_prefix
		op["source_region_id_at_edit"] = _source_region_id
		op["source_region_name_at_edit"] = _source_region_name
	else:
		op["source_region_id"] = _source_region_id
		op["source_region_name"] = _source_region_name

	_operations.append(op)
	if _save_overrides():
		_show("Override сохранён: %s → %s" % [_source_province_name if _source_mode == "province" else _source_region_name, _target_region_name])
	else:
		_show("Override добавлен в память, но файл сохранить не удалось")
	_clear_selection()


func _undo_last_override() -> void:
	if _operations.is_empty():
		_show("Редактор: нечего отменять")
		return
	var removed: Variant = _operations.pop_back()
	_save_overrides()
	_show("Отменён последний override: %s" % JSON.stringify(removed))
	_update_panel()


func _load_assignments() -> void:
	var path := ASSIGNMENTS_FINAL if FileAccess.file_exists(ASSIGNMENTS_FINAL) else ASSIGNMENTS_FALLBACK
	if not FileAccess.file_exists(path):
		return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if typeof(parsed) != TYPE_DICTIONARY:
		return
	for raw in (parsed as Dictionary).get("assignments", []):
		if raw is Dictionary:
			_assignments_by_id[str((raw as Dictionary).get("province_id", ""))] = raw


func _load_identities() -> void:
	if not FileAccess.file_exists(IDENTITIES_PATH):
		return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(IDENTITIES_PATH))
	if typeof(parsed) != TYPE_DICTIONARY:
		return
	for raw in (parsed as Dictionary).get("provinces", []):
		if not raw is Dictionary:
			continue
		var entry: Dictionary = raw
		var legacy := str(entry.get("legacy_id", ""))
		if not legacy.is_empty():
			_identity_by_legacy[legacy] = entry


func _load_overrides() -> void:
	var path := OVERRIDES_PATH if FileAccess.file_exists(OVERRIDES_PATH) else OVERRIDES_FALLBACK
	if not FileAccess.file_exists(path):
		_operations = []
		return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if typeof(parsed) == TYPE_DICTIONARY:
		_operations = (parsed as Dictionary).get("operations", []).duplicate(true)


func _save_overrides() -> bool:
	var doc := {
		"schema_version": 1,
		"format": "world_region_manual_overrides/v1",
		"description": "Manual region editor overrides. Applied after automatic island/sliver cleanup so user decisions always win.",
		"operations": _operations,
	}
	var payload := JSON.stringify(doc, "  ") + "\n"
	for path in [OVERRIDES_PATH, OVERRIDES_FALLBACK]:
		var file := FileAccess.open(path, FileAccess.WRITE)
		if file != null:
			file.store_string(payload)
			file.close()
			_last_saved_path = ProjectSettings.globalize_path(path)
			_update_panel()
			return true
	return false


func _ensure_province_geometry() -> void:
	if _province_geometry_loaded:
		return
	_province_geometry_loaded = true
	if not FileAccess.file_exists(LAYER8_PATH):
		return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(LAYER8_PATH))
	if typeof(parsed) != TYPE_DICTIONARY:
		return

	# Canonical layer 8 uses `cells` and stable legacy ids such as
	# cuba__cienfuegos. Translate each to the current numeric passport id.
	for raw in (parsed as Dictionary).get("cells", []):
		if not raw is Dictionary:
			continue
		var entry: Dictionary = raw
		var legacy := str(entry.get("id", ""))
		var identity: Dictionary = _identity_by_legacy.get(legacy, {})
		if identity.is_empty():
			_missing_identity_count += 1
			continue
		var rings := _to_rings(entry.get("rings", []))
		if rings.is_empty():
			continue
		var bbox_raw: Variant = entry.get("bbox", [])
		var bbox: Array = bbox_raw if bbox_raw is Array and bbox_raw.size() >= 4 else _bbox_for_rings(rings)
		var pid := str(identity.get("id", ""))
		var legacy_parts := legacy.split("__", false, 1)
		var prefix := str(legacy_parts[0]) if legacy_parts.size() > 0 else legacy
		_province_records.append({
			"province_id": pid,
			"legacy_id": legacy,
			"country_prefix": prefix,
			"name": str(identity.get("name", entry.get("name", pid))),
			"bbox": bbox,
			"rings": rings,
		})
	_update_panel()


func _province_at_point(point: Vector2) -> Dictionary:
	var hits: Array[Dictionary] = []
	for item in _province_records:
		var bbox: Array = item["bbox"]
		if point.x < float(bbox[0]) or point.y < float(bbox[1]) or point.x > float(bbox[2]) or point.y > float(bbox[3]):
			continue
		if _point_in_rings(point, item["rings"]):
			hits.append(item)
	if hits.is_empty():
		return {}
	# Canonical provinces should not overlap. If source geometry has an overlap,
	# choose the most local/smallest bbox rather than an arbitrary dictionary id.
	hits.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		var ab: Array = a["bbox"]
		var bb: Array = b["bbox"]
		var aa := maxf(0.0, float(ab[2]) - float(ab[0])) * maxf(0.0, float(ab[3]) - float(ab[1]))
		var ba := maxf(0.0, float(bb[2]) - float(bb[0])) * maxf(0.0, float(bb[3]) - float(bb[1]))
		return aa < ba
	)
	if hits.size() > 1:
		_show("Внимание: под курсором %d перекрывающихся провинций; выбрана самая локальная" % hits.size())
	return hits[0]


func _set_region_edit_role(region_id: String, role: int) -> void:
	if region_id.is_empty() or not is_instance_valid(_viewer):
		return
	var mapping: Dictionary = _viewer.get("_piece_nodes_by_region")
	if not mapping.has(region_id):
		return
	for node in (mapping[region_id] as Array):
		if is_instance_valid(node) and node.has_method("set_edit_role"):
			node.call("set_edit_role", role)


func _clear_source_highlight() -> void:
	if _source_mode == "region" and not _source_region_id.is_empty():
		_set_region_edit_role(_source_region_id, 0)


func _clear_target_highlight() -> void:
	if not _target_region_id.is_empty():
		_set_region_edit_role(_target_region_id, 0)


func _clear_selection() -> void:
	_clear_source_highlight()
	_clear_target_highlight()
	_source_mode = ""
	_source_region_id = ""
	_source_region_name = ""
	_source_province_id = ""
	_source_province_name = ""
	_source_legacy_id = ""
	_source_country_prefix = ""
	_source_province_rings.clear()
	_target_region_id = ""
	_target_region_name = ""
	queue_redraw()
	_update_panel()


func _draw() -> void:
	if not _edit_mode or _source_mode != "province" or _source_province_rings.is_empty():
		return
	# Political selection outline only needs the exterior ring.
	var ring: PackedVector2Array = _source_province_rings[0]
	var closed: PackedVector2Array = ring.duplicate()
	if closed.size() >= 2 and not closed[0].is_equal_approx(closed[closed.size() - 1]):
		closed.append(closed[0])
	if closed.size() >= 2:
		draw_polyline(closed, SOURCE_COLOR, 1.7, true)


func _to_rings(raw_rings: Variant) -> Array:
	var out: Array = []
	if not raw_rings is Array:
		return out
	for raw_ring in raw_rings:
		if not raw_ring is Array:
			continue
		var ring := PackedVector2Array()
		for raw_point in raw_ring:
			if raw_point is Array and raw_point.size() >= 2:
				ring.append(Vector2(float(raw_point[0]), float(raw_point[1])))
		if ring.size() >= 3:
			out.append(ring)
	return out


func _bbox_for_rings(rings: Array) -> Array:
	var minx := INF
	var miny := INF
	var maxx := -INF
	var maxy := -INF
	for ring in rings:
		for p in ring:
			minx = minf(minx, p.x)
			miny = minf(miny, p.y)
			maxx = maxf(maxx, p.x)
			maxy = maxf(maxy, p.y)
	return [minx, miny, maxx, maxy]


func _point_in_rings(point: Vector2, rings: Array) -> bool:
	if rings.is_empty() or not Geometry2D.is_point_in_polygon(point, rings[0]):
		return false
	for i in range(1, rings.size()):
		if Geometry2D.is_point_in_polygon(point, rings[i]):
			return false
	return true


func _build_panel() -> void:
	if not is_instance_valid(_ui):
		return
	_panel = PanelContainer.new()
	_panel.offset_left = 24.0
	_panel.offset_top = 320.0
	_panel.offset_right = 720.0
	_panel.offset_bottom = 585.0
	_panel.visible = false
	_ui.add_child(_panel)
	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 12)
	margin.add_theme_constant_override("margin_top", 10)
	margin.add_theme_constant_override("margin_right", 12)
	margin.add_theme_constant_override("margin_bottom", 10)
	_panel.add_child(margin)
	_label = Label.new()
	_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	margin.add_child(_label)
	_update_panel()


func _update_panel() -> void:
	if not is_instance_valid(_panel) or not is_instance_valid(_label):
		return
	_panel.visible = _edit_mode and _viewer_active()
	var source := "—"
	if _source_mode == "region":
		source = "%s [весь регион]" % _source_region_name
	elif _source_mode == "province":
		source = "%s\n%s\n%s" % [_source_province_name, _source_province_id, _source_legacy_id]
	_label.text = "РЕДАКТОР РЕГИОНОВ V2 — canonical layer 8\nИсточник: %s\nЦель: %s\nОпераций: %d\nLayer8 records: %d • identity misses: %d\n\nLMB регион • Alt+LMB одна провинция • RMB цель • Enter применить\nZ отменить последнюю • S сохранить • Esc очистить/выйти\n%s" % [source, _target_region_name if not _target_region_name.is_empty() else "—", _operations.size(), _province_records.size(), _missing_identity_count, _last_saved_path]


func _show(message: String) -> void:
	if is_instance_valid(get_parent()) and get_parent().has_method("_show_top_info"):
		get_parent().call("_show_top_info", message)
	else:
		print(message)
