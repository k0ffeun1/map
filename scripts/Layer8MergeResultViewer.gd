extends Node2D
## Visual inspection layer for the FINAL Layer-8 small-province normalization.
##
## F11 — toggle final merge result.
## F12 — next interesting final gameplay province (Shift+F12 = previous).
## LMB — select a highlighted gameplay province and show before -> after data.
##
## Colors:
##   red    — small source family that is absorbed;
##   green  — final/root territory that receives absorbed family;
##   cyan   — protected historical/strategic island province;
##   yellow — small province intentionally kept independent.

const GEOMETRY_PATH := "res://assets/provinces.json"
const IDENTITY_PATH := "res://assets/game_data/provinces.json"
const PLAN_PATH := "res://assets/game_data/layer8_small_province_merge_plan.json"
const GROUPS_PATH := "res://assets/game_data/layer8_normalized_province_groups.json"
const PIECE_SCRIPT := preload("res://scripts/Layer8MergeResultPieceNode.gd")

const EXPECTED_RENDER_RECORDS := 4027
const EXPECTED_SOURCE_FAMILIES := 2903
const EXPECTED_CANARY_GAMEPLAY_PROVINCES := 2

const COLOR_ABSORBED := Color(1.0, 0.08, 0.06, 0.53)
const COLOR_ABSORBED_OUTLINE := Color(1.0, 0.58, 0.48, 1.0)
const COLOR_ROOT := Color(0.10, 0.92, 0.30, 0.39)
const COLOR_ROOT_OUTLINE := Color(0.52, 1.0, 0.62, 1.0)
const COLOR_PROTECTED := Color(0.02, 0.80, 1.0, 0.40)
const COLOR_PROTECTED_OUTLINE := Color(0.55, 0.96, 1.0, 1.0)
const COLOR_ISOLATED := Color(1.0, 0.76, 0.04, 0.43)
const COLOR_ISOLATED_OUTLINE := Color(1.0, 0.94, 0.48, 1.0)

var _active := false
var _last_error := ""
var _focus_index := -1
var _selected_parent_id := ""

var _summary: Dictionary = {}
var _validation: Dictionary = {}
var _action_by_family: Dictionary = {}
var _group_by_parent: Dictionary = {}
var _render_family_by_pid: Dictionary = {}
var _interesting_groups: Array[Dictionary] = []
var _pieces: Array[Dictionary] = []
var _nodes_by_parent: Dictionary = {}

var _auto_merge_count := 0
var _isolated_keep_count := 0
var _protected_gameplay_count := 0
var _canary_count := 0

var _geometry_root: Node2D
var _ui_layer: CanvasLayer
var _panel: PanelContainer
var _summary_label: Label
var _selection_label: Label


func _ready() -> void:
	z_index = 244
	_ui_layer = get_node_or_null("../UI") as CanvasLayer
	_geometry_root = Node2D.new()
	_geometry_root.name = "Layer8MergeResultGeometry"
	add_child(_geometry_root)
	_build_panel()
	_load_data()
	if _last_error.is_empty():
		_build_geometry()
	set_active(false)
	set_process_input(true)


func _input(event: InputEvent) -> void:
	var key := event as InputEventKey
	if key != null and key.pressed and not key.echo:
		if key.physical_keycode == KEY_F11 or key.keycode == KEY_F11:
			if not _last_error.is_empty():
				_show_status("Layer 8 merge result: %s" % _last_error)
			else:
				set_active(not _active)
			get_viewport().set_input_as_handled()
			return
		if key.physical_keycode == KEY_F12 or key.keycode == KEY_F12:
			if not _last_error.is_empty():
				_show_status("Layer 8 merge result: %s" % _last_error)
			else:
				if not _active:
					set_active(true)
				_focus_relative(-1 if key.shift_pressed else 1)
			get_viewport().set_input_as_handled()
			return

	if not _active:
		return
	var mouse := event as InputEventMouseButton
	if mouse == null or not mouse.pressed or mouse.button_index != MOUSE_BUTTON_LEFT:
		return
	var hit := _hit_at_point(get_global_mouse_position())
	if not hit.is_empty():
		_select_parent(str(hit.get("gameplay_parent_id", "")), false)
		get_viewport().set_input_as_handled()


func set_active(value: bool) -> void:
	_active = value and _last_error.is_empty()
	if is_instance_valid(_geometry_root):
		_geometry_root.visible = _active
	if is_instance_valid(_panel):
		_panel.visible = _active
	if _active:
		_hide_conflicting_debug_layers()
		_show_status("F11: итог merge Layer 8 • F12: следующий результат • ЛКМ: детали")
	else:
		_clear_selection_visual()
		_show_status("F11: показать итог объединения маленьких провинций")
	_update_summary()


func is_active() -> bool:
	return _active


func _load_data() -> void:
	var geometry := _load_json(GEOMETRY_PATH)
	var identities_doc := _load_json(IDENTITY_PATH)
	var plan := _load_json(PLAN_PATH)
	var normalized := _load_json(GROUPS_PATH)
	if geometry.is_empty() or identities_doc.is_empty() or plan.is_empty() or normalized.is_empty():
		return

	if str(normalized.get("format", "")) != "layer8_normalized_province_groups/v2":
		_fail("ожидался layer8_normalized_province_groups/v2")
		return
	_summary = Dictionary(normalized.get("summary", {}))
	_validation = Dictionary(normalized.get("validation", {}))
	if int(_summary.get("render_record_count", 0)) != EXPECTED_RENDER_RECORDS:
		_fail("ожидалось %d render records" % EXPECTED_RENDER_RECORDS)
		return
	if int(_summary.get("source_family_count", 0)) != EXPECTED_SOURCE_FAMILIES:
		_fail("ожидалось %d source-family" % EXPECTED_SOURCE_FAMILIES)
		return
	if int(_validation.get("cross_country_gameplay_parent_count", -1)) != 0:
		_fail("найден cross-country gameplay parent")
		return
	if not bool(_validation.get("canary_grouping_ok", false)):
		_fail("две Канарские gameplay-провинции не подтверждены")
		return

	_auto_merge_count = int(_summary.get("automatic_merge_source_count", 0))
	_isolated_keep_count = int(_summary.get("isolated_small_keep_count", 0))
	_protected_gameplay_count = int(_summary.get("protected_gameplay_parent_count", 0))
	_canary_count = int(_validation.get("canary_gameplay_parent_count", 0))
	if _canary_count != EXPECTED_CANARY_GAMEPLAY_PROVINCES:
		_fail("ожидалось 2 Канарские gameplay-провинции, найдено %d" % _canary_count)
		return

	_action_by_family.clear()
	_render_family_by_pid.clear()
	var actions: Array = plan.get("family_actions", [])
	if actions.size() != EXPECTED_SOURCE_FAMILIES:
		_fail("merge plan содержит %d family вместо %d" % [actions.size(), EXPECTED_SOURCE_FAMILIES])
		return
	for raw in actions:
		if not raw is Dictionary:
			continue
		var action: Dictionary = raw
		var family_id := str(action.get("family_id", ""))
		if family_id.is_empty():
			continue
		_action_by_family[family_id] = action
		for raw_pid in action.get("member_ids", []):
			_render_family_by_pid[str(raw_pid)] = family_id

	var identity_by_pid: Dictionary = {}
	for raw in identities_doc.get("provinces", []):
		if raw is Dictionary:
			var identity: Dictionary = raw
			identity_by_pid[str(identity.get("id", ""))] = identity
	if identity_by_pid.size() != EXPECTED_RENDER_RECORDS:
		_fail("identity coverage %d != %d" % [identity_by_pid.size(), EXPECTED_RENDER_RECORDS])
		return

	var geometry_by_legacy: Dictionary = {}
	for raw in geometry.get("cells", []):
		if raw is Dictionary:
			var cell: Dictionary = raw
			var legacy_id := str(cell.get("id", ""))
			if not legacy_id.is_empty():
				geometry_by_legacy[legacy_id] = cell

	_group_by_parent.clear()
	_interesting_groups.clear()
	var groups: Array = normalized.get("groups", [])
	for raw in groups:
		if not raw is Dictionary:
			continue
		var group: Dictionary = raw.duplicate(true)
		var parent_id := str(group.get("gameplay_parent_id", ""))
		if parent_id.is_empty():
			continue
		var category := _classify_group(group)
		group["viewer_category"] = category
		_group_by_parent[parent_id] = group
		if not category.is_empty():
			_interesting_groups.append(group)

	_interesting_groups.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		var pa := _category_priority(str(a.get("viewer_category", "")))
		var pb := _category_priority(str(b.get("viewer_category", "")))
		if pa != pb:
			return pa < pb
		return str(a.get("display_name", "")).naturalnocasecmp_to(str(b.get("display_name", ""))) < 0
	)

	_pieces.clear()
	for group in _interesting_groups:
		var parent_id := str(group.get("gameplay_parent_id", ""))
		var group_bbox: Array = []
		for raw_pid in group.get("render_province_ids", []):
			var pid := str(raw_pid)
			var identity: Dictionary = identity_by_pid.get(pid, {})
			if identity.is_empty():
				_fail("нет identity для %s" % pid)
				return
			var legacy_id := str(identity.get("legacy_id", ""))
			var cell: Dictionary = geometry_by_legacy.get(legacy_id, {})
			if cell.is_empty():
				_fail("нет геометрии для %s / %s" % [pid, legacy_id])
				return
			var rings := _to_rings(cell.get("rings", []))
			if rings.is_empty():
				continue
			var family_id := str(_render_family_by_pid.get(pid, ""))
			var role := _piece_role(group, family_id)
			var bbox: Array = cell.get("bbox", [])
			group_bbox = _merge_bbox(group_bbox, bbox, rings)
			_pieces.append({
				"gameplay_parent_id": parent_id,
				"province_id": pid,
				"legacy_id": legacy_id,
				"family_id": family_id,
				"role": role,
				"rings": rings,
				"bbox": bbox,
			})
		group["viewer_bbox"] = group_bbox
		_group_by_parent[parent_id] = group

	if _interesting_groups.is_empty() or _pieces.is_empty():
		_fail("нет интересных итоговых merge/protected/isolated провинций")


func _classify_group(group: Dictionary) -> String:
	if int(group.get("member_family_count", 1)) > 1:
		return "merged"
	var root_family_id := str(group.get("root_family_id", ""))
	var root_action: Dictionary = _action_by_family.get(root_family_id, {})
	if str(root_action.get("status", "")) == "KEEP_ISOLATED_SMALL":
		return "isolated"
	var protected_ids: Array = group.get("protected_group_ids", [])
	if not protected_ids.is_empty():
		return "protected"
	return ""


func _category_priority(category: String) -> int:
	match category:
		"merged": return 0
		"isolated": return 1
		"protected": return 2
		_: return 9


func _piece_role(group: Dictionary, family_id: String) -> String:
	var category := str(group.get("viewer_category", ""))
	if category == "merged":
		if family_id == str(group.get("root_family_id", "")):
			var protected_ids: Array = group.get("protected_group_ids", [])
			return "protected_root" if not protected_ids.is_empty() else "root"
		return "absorbed"
	if category == "protected":
		return "protected"
	if category == "isolated":
		return "isolated"
	return "root"


func _build_geometry() -> void:
	_nodes_by_parent.clear()
	for part in _pieces:
		var role := str(part.get("role", ""))
		var fill := COLOR_ROOT
		var outline := COLOR_ROOT_OUTLINE
		match role:
			"absorbed":
				fill = COLOR_ABSORBED
				outline = COLOR_ABSORBED_OUTLINE
			"protected", "protected_root":
				fill = COLOR_PROTECTED
				outline = COLOR_PROTECTED_OUTLINE
			"isolated":
				fill = COLOR_ISOLATED
				outline = COLOR_ISOLATED_OUTLINE
			_:
				fill = COLOR_ROOT
				outline = COLOR_ROOT_OUTLINE
		var node: Node2D = PIECE_SCRIPT.new()
		_geometry_root.add_child(node)
		node.call("setup", part["rings"], fill, outline, 1.25)
		part["node"] = node
		var parent_id := str(part.get("gameplay_parent_id", ""))
		if not _nodes_by_parent.has(parent_id):
			_nodes_by_parent[parent_id] = []
		var parent_nodes: Array = _nodes_by_parent[parent_id]
		parent_nodes.append(node)
		_nodes_by_parent[parent_id] = parent_nodes


func _focus_relative(delta: int) -> void:
	if _interesting_groups.is_empty():
		return
	if _focus_index < 0:
		_focus_index = 0 if delta >= 0 else _interesting_groups.size() - 1
	else:
		_focus_index = posmod(_focus_index + delta, _interesting_groups.size())
	var group: Dictionary = _interesting_groups[_focus_index]
	_focus_group(group)
	_select_parent(str(group.get("gameplay_parent_id", "")), true)


func _focus_group(group: Dictionary) -> void:
	var bbox: Array = group.get("viewer_bbox", [])
	if bbox.size() < 4:
		return
	var min_x := float(bbox[0])
	var min_y := float(bbox[1])
	var max_x := float(bbox[2])
	var max_y := float(bbox[3])
	var width := maxf(max_x - min_x, 0.08)
	var height := maxf(max_y - min_y, 0.08)
	var camera := get_node_or_null("../Camera2D") as Camera2D
	if not is_instance_valid(camera):
		return
	camera.position = Vector2((min_x + max_x) * 0.5, (min_y + max_y) * 0.5)
	var viewport_size := get_viewport_rect().size
	var zx := viewport_size.x / (width * 3.8)
	var zy := viewport_size.y / (height * 3.8)
	var zoom_value := clampf(minf(zx, zy), 2.5, 100.0)
	camera.zoom = Vector2(zoom_value, zoom_value)


func _select_parent(parent_id: String, from_jump: bool) -> void:
	if parent_id.is_empty() or not _group_by_parent.has(parent_id):
		return
	_clear_selection_visual()
	_selected_parent_id = parent_id
	for raw_node in _nodes_by_parent.get(parent_id, []):
		var node := raw_node as Node2D
		if is_instance_valid(node) and node.has_method("set_selected"):
			node.call("set_selected", true)
	var group: Dictionary = _group_by_parent[parent_id]
	_show_selection(group, from_jump)


func _clear_selection_visual() -> void:
	if not _selected_parent_id.is_empty():
		for raw_node in _nodes_by_parent.get(_selected_parent_id, []):
			var node := raw_node as Node2D
			if is_instance_valid(node) and node.has_method("set_selected"):
				node.call("set_selected", false)
	_selected_parent_id = ""


func _hit_at_point(point: Vector2) -> Dictionary:
	for index in range(_pieces.size() - 1, -1, -1):
		var part: Dictionary = _pieces[index]
		var bbox: Array = part.get("bbox", [])
		if bbox.size() >= 4 and (point.x < float(bbox[0]) or point.y < float(bbox[1]) or point.x > float(bbox[2]) or point.y > float(bbox[3])):
			continue
		if _point_in_rings(point, part.get("rings", [])):
			return part
	return {}


func _show_selection(group: Dictionary, from_jump: bool) -> void:
	if not is_instance_valid(_selection_label):
		return
	var category := str(group.get("viewer_category", ""))
	var prefix := "F12 [%d/%d]" % [_focus_index + 1, _interesting_groups.size()] if from_jump else "ЛКМ"
	var label := "ОБЪЕДИНЕНО"
	match category:
		"isolated": label = "ОСТАВЛЕНО САМОСТОЯТЕЛЬНО"
		"protected": label = "ЗАЩИЩЁННЫЙ ОСТРОВ"
	var source_names: Array = group.get("source_names", [])
	var before_text := ", ".join(PackedStringArray(source_names))
	if before_text.length() > 190:
		before_text = before_text.left(187) + "..."
	var protected_ids: Array = group.get("protected_group_ids", [])
	var protected_text := ", ".join(PackedStringArray(protected_ids)) if not protected_ids.is_empty() else "—"
	_selection_label.text = "%s • %s\nСтало: %s\nБыло: %s\nПлощадь: %.1f км²\nFamily: %d   render-pieces: %d\nРегион: %s\nProtected: %s\nID: %s" % [
		prefix,
		label,
		str(group.get("display_name", "?")),
		before_text,
		float(group.get("area_km2", 0.0)),
		int(group.get("member_family_count", 0)),
		int(group.get("render_province_count", 0)),
		str(group.get("root_region_name", "?")),
		protected_text,
		str(group.get("gameplay_parent_id", "?")),
	]
	_show_status("%s → %s • %.1f км²" % [before_text, str(group.get("display_name", "?")), float(group.get("area_km2", 0.0))])


func _update_summary() -> void:
	if not is_instance_valid(_summary_label):
		return
	_summary_label.text = "Gameplay-провинций: %d\nSafe merge: %d\nОставлено маленьких: %d\nProtected gameplay: %d\nКанары: %d gameplay-провинции\n\nКрасный = поглощается\nЗелёный = итоговый root\nГолубой = protected\nЖёлтый = оставлено" % [
		int(_summary.get("gameplay_parent_count", 0)),
		_auto_merge_count,
		_isolated_keep_count,
		_protected_gameplay_count,
		_canary_count,
	]
	if is_instance_valid(_selection_label) and _selection_label.text.is_empty():
		_selection_label.text = "F12 — следующий итоговый объект\nShift+F12 — предыдущий\nЛКМ — выделить всю итоговую gameplay-провинцию"


func _hide_conflicting_debug_layers() -> void:
	var root := get_parent()
	if not is_instance_valid(root):
		return
	for node_name in ["Layer8SmallProvinceViewer", "WorldAdmin1SafeViewer", "WorldRegionsDraftViewer", "SloveniaAdmin1ComparisonViewer"]:
		var viewer := root.get_node_or_null(node_name)
		if is_instance_valid(viewer) and viewer.has_method("set_active"):
			viewer.call("set_active", false)


func _merge_bbox(current: Array, raw_bbox: Variant, rings: Array) -> Array:
	var bbox: Array = []
	if raw_bbox is Array and raw_bbox.size() >= 4:
		bbox = [float(raw_bbox[0]), float(raw_bbox[1]), float(raw_bbox[2]), float(raw_bbox[3])]
	elif not rings.is_empty():
		var outer: PackedVector2Array = rings[0]
		if not outer.is_empty():
			var min_x := outer[0].x
			var min_y := outer[0].y
			var max_x := outer[0].x
			var max_y := outer[0].y
			for point in outer:
				min_x = minf(min_x, point.x)
				min_y = minf(min_y, point.y)
				max_x = maxf(max_x, point.x)
				max_y = maxf(max_y, point.y)
			bbox = [min_x, min_y, max_x, max_y]
	if bbox.size() < 4:
		return current
	if current.size() < 4:
		return bbox
	return [
		minf(float(current[0]), float(bbox[0])),
		minf(float(current[1]), float(bbox[1])),
		maxf(float(current[2]), float(bbox[2])),
		maxf(float(current[3]), float(bbox[3])),
	]


func _point_in_rings(point: Vector2, rings: Array) -> bool:
	if rings.is_empty() or not Geometry2D.is_point_in_polygon(point, rings[0]):
		return false
	for i in range(1, rings.size()):
		if Geometry2D.is_point_in_polygon(point, rings[i]):
			return false
	return true


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


func _load_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		_fail("не найден %s" % path)
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if typeof(parsed) != TYPE_DICTIONARY:
		_fail("неверный JSON %s" % path)
		return {}
	return parsed


func _fail(message: String) -> void:
	if _last_error.is_empty():
		_last_error = message
	push_error("Layer8MergeResultViewer: %s" % message)


func _show_status(text: String) -> void:
	var label := get_node_or_null("../UI/StatusLabel") as Label
	if is_instance_valid(label):
		label.text = text


func _build_panel() -> void:
	if not is_instance_valid(_ui_layer):
		return
	_panel = PanelContainer.new()
	_panel.offset_left = 1110.0
	_panel.offset_top = 55.0
	_panel.offset_right = 1890.0
	_panel.offset_bottom = 535.0
	_panel.visible = false
	_ui_layer.add_child(_panel)

	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 14)
	margin.add_theme_constant_override("margin_top", 12)
	margin.add_theme_constant_override("margin_right", 14)
	margin.add_theme_constant_override("margin_bottom", 12)
	_panel.add_child(margin)

	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 7)
	margin.add_child(box)

	var title := Label.new()
	title.text = "Layer 8 — итог объединения [F11]"
	title.add_theme_font_size_override("font_size", 20)
	title.add_theme_color_override("font_color", Color(0.72, 0.96, 1.0, 1.0))
	box.add_child(title)

	_summary_label = Label.new()
	_summary_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(_summary_label)

	var separator := HSeparator.new()
	box.add_child(separator)

	_selection_label = Label.new()
	_selection_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_selection_label.custom_minimum_size = Vector2(730.0, 185.0)
	box.add_child(_selection_label)
