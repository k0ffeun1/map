extends Node2D
## In-game visual comparison for Slovenia Admin-1 normalization.
##
## F7 cycles:
##   OFF -> legacy Layer 8 -> raw SAFE (193) -> normalized preview (12)
##       -> legacy/new overlay -> OFF
## F8 focuses the camera on Slovenia.
## LMB shows the clicked territory name/id in the comparison panel.

const LEGACY_PATH := "res://assets/provinces.json"
const MANIFEST_PATH := "res://assets/game_data/world_admin1_source_manifest.json"
const SAFE_PIECES_PATH := "res://assets/map_geometry/world_admin1_safe_pieces.json"
const NORMALIZED_PARENTS_PATH := "res://assets/game_data/slovenia_admin1_normalized_preview.json"
const NORMALIZED_PIECES_PATH := "res://assets/map_geometry/slovenia_admin1_normalized_preview_pieces.json"
const PIECE_SCRIPT := preload("res://scripts/SloveniaAdmin1ComparisonPieceNode.gd")

const MODE_OFF := 0
const MODE_LEGACY := 1
const MODE_SAFE := 2
const MODE_NORMALIZED := 3
const MODE_OVERLAY := 4

const EXPECTED_LEGACY_RECORDS := 2
const EXPECTED_SAFE_PARENTS := 193
const EXPECTED_NORMALIZED_PARENTS := 12

var _mode := MODE_OFF
var _last_error := ""
var _ui_layer: CanvasLayer
var _panel: PanelContainer
var _mode_label: Label
var _selection_label: Label

var _legacy_root: Node2D
var _safe_root: Node2D
var _normalized_root: Node2D
var _overlay_root: Node2D

var _legacy_parts: Array[Dictionary] = []
var _safe_parts: Array[Dictionary] = []
var _normalized_parts: Array[Dictionary] = []
var _safe_parent_ids: Dictionary = {}
var _normalized_parent_ids: Dictionary = {}
var _slovenia_bbox := Rect2()


func _ready() -> void:
	_ui_layer = get_node_or_null("../UI") as CanvasLayer
	z_index = 235
	_create_roots()
	_build_panel()
	_load_data()
	if _last_error.is_empty():
		_build_geometry()
	_apply_mode()
	set_process_input(true)


func _input(event: InputEvent) -> void:
	var key := event as InputEventKey
	if key != null and key.pressed and not key.echo:
		if key.physical_keycode == KEY_F7 or key.keycode == KEY_F7:
			if not _last_error.is_empty():
				_show_status("Словения compare: %s" % _last_error)
			else:
				_mode = (_mode + 1) % 5
				_apply_mode()
			get_viewport().set_input_as_handled()
			return
		if (key.physical_keycode == KEY_F8 or key.keycode == KEY_F8) and _mode != MODE_OFF:
			_focus_slovenia()
			get_viewport().set_input_as_handled()
			return

	if _mode == MODE_OFF:
		return
	var mouse := event as InputEventMouseButton
	if mouse == null or not mouse.pressed or mouse.button_index != MOUSE_BUTTON_LEFT:
		return
	var hit := _hit_at_point(get_global_mouse_position())
	if not hit.is_empty():
		_selection_label.text = "Выбрано: %s\nID: %s" % [str(hit.get("name", "?")), str(hit.get("id", "?"))]
		get_viewport().set_input_as_handled()


func _create_roots() -> void:
	_legacy_root = Node2D.new()
	_legacy_root.name = "SloveniaLegacyLayer8"
	add_child(_legacy_root)
	_safe_root = Node2D.new()
	_safe_root.name = "SloveniaSafeRaw"
	add_child(_safe_root)
	_normalized_root = Node2D.new()
	_normalized_root.name = "SloveniaNormalized12"
	add_child(_normalized_root)
	_overlay_root = Node2D.new()
	_overlay_root.name = "SloveniaBeforeAfterOverlay"
	add_child(_overlay_root)


func _load_data() -> void:
	var legacy := _load_json(LEGACY_PATH)
	var manifest := _load_json(MANIFEST_PATH)
	var safe := _load_json(SAFE_PIECES_PATH)
	var normalized_parents := _load_json(NORMALIZED_PARENTS_PATH)
	var normalized_pieces := _load_json(NORMALIZED_PIECES_PATH)
	if legacy.is_empty() or manifest.is_empty() or safe.is_empty() or normalized_parents.is_empty() or normalized_pieces.is_empty():
		return

	_legacy_parts.clear()
	for raw in legacy.get("cells", []):
		if not raw is Dictionary:
			continue
		var cell: Dictionary = raw
		var legacy_id := str(cell.get("id", ""))
		if not legacy_id.begins_with("slovenia__"):
			continue
		var rings := _to_rings(cell.get("rings", []))
		if rings.is_empty():
			continue
		_legacy_parts.append({"id": legacy_id, "name": str(cell.get("name", legacy_id)), "rings": rings, "bbox": cell.get("bbox", [])})

	_safe_parent_ids.clear()
	var safe_names: Dictionary = {}
	for raw in manifest.get("source_features", []):
		if not raw is Dictionary:
			continue
		var feature: Dictionary = raw
		if str(feature.get("admin", "")) != "Slovenia":
			continue
		var parent_id := str(feature.get("logical_admin1_id", ""))
		if parent_id.is_empty():
			continue
		_safe_parent_ids[parent_id] = true
		safe_names[parent_id] = str(feature.get("name", parent_id))

	_safe_parts.clear()
	for raw in safe.get("pieces", []):
		if not raw is Dictionary:
			continue
		var piece: Dictionary = raw
		var parent_id := str(piece.get("logical_admin1_id", ""))
		if not _safe_parent_ids.has(parent_id):
			continue
		var rings := _to_rings(piece.get("rings", []))
		if rings.is_empty():
			continue
		_safe_parts.append({"id": parent_id, "name": str(safe_names.get(parent_id, parent_id)), "rings": rings, "bbox": piece.get("bbox", [])})

	_normalized_parent_ids.clear()
	var normalized_names: Dictionary = {}
	for raw in normalized_parents.get("parents", []):
		if not raw is Dictionary:
			continue
		var parent: Dictionary = raw
		var parent_id := str(parent.get("normalized_admin1_id", ""))
		if parent_id.is_empty():
			continue
		_normalized_parent_ids[parent_id] = true
		normalized_names[parent_id] = str(parent.get("name", parent_id))

	_normalized_parts.clear()
	for raw in normalized_pieces.get("pieces", []):
		if not raw is Dictionary:
			continue
		var piece: Dictionary = raw
		var parent_id := str(piece.get("normalized_admin1_id", ""))
		if not _normalized_parent_ids.has(parent_id):
			continue
		var rings := _to_rings(piece.get("rings", []))
		if rings.is_empty():
			continue
		_normalized_parts.append({"id": parent_id, "name": str(normalized_names.get(parent_id, parent_id)), "rings": rings, "bbox": piece.get("bbox", [])})

	if _legacy_parts.size() != EXPECTED_LEGACY_RECORDS:
		_fail("ожидалось %d legacy records, найдено %d" % [EXPECTED_LEGACY_RECORDS, _legacy_parts.size()])
		return
	if _safe_parent_ids.size() != EXPECTED_SAFE_PARENTS:
		_fail("ожидалось %d SAFE parents, найдено %d" % [EXPECTED_SAFE_PARENTS, _safe_parent_ids.size()])
		return
	if _normalized_parent_ids.size() != EXPECTED_NORMALIZED_PARENTS:
		_fail("ожидалось %d normalized parents, найдено %d" % [EXPECTED_NORMALIZED_PARENTS, _normalized_parent_ids.size()])
		return
	_compute_bbox()


func _build_geometry() -> void:
	for part in _legacy_parts:
		_add_piece(_legacy_root, part, _hash_color(str(part["id"]), 0.24), Color(1.0, 0.48, 0.18, 0.98), 0.9)
	for part in _safe_parts:
		_add_piece(_safe_root, part, _hash_color(str(part["id"]), 0.18), Color(0.78, 0.82, 0.88, 0.88), 0.42)
	for part in _normalized_parts:
		_add_piece(_normalized_root, part, _hash_color(str(part["id"]), 0.28), Color(0.18, 0.95, 1.0, 0.98), 0.9)
	for part in _legacy_parts:
		_add_piece(_overlay_root, part, Color(1.0, 0.25, 0.10, 0.06), Color(1.0, 0.28, 0.12, 1.0), 1.5)
	for part in _normalized_parts:
		_add_piece(_overlay_root, part, Color(0.10, 0.85, 1.0, 0.08), Color(0.10, 0.92, 1.0, 1.0), 1.05)


func _add_piece(root: Node2D, part: Dictionary, fill: Color, outline: Color, width: float) -> void:
	var node: Node2D = PIECE_SCRIPT.new()
	root.add_child(node)
	node.call("setup", part["rings"], fill, outline, width)


func _apply_mode() -> void:
	_legacy_root.visible = _mode == MODE_LEGACY
	_safe_root.visible = _mode == MODE_SAFE
	_normalized_root.visible = _mode == MODE_NORMALIZED
	_overlay_root.visible = _mode == MODE_OVERLAY
	if is_instance_valid(_panel):
		_panel.visible = _mode != MODE_OFF
	if _mode != MODE_OFF:
		_hide_conflicting_debug_layers()
	_update_panel()
	_show_status(_status_text())


func _hide_conflicting_debug_layers() -> void:
	var root := get_parent()
	if not is_instance_valid(root):
		return
	var safe_viewer := root.get_node_or_null("WorldAdmin1SafeViewer")
	if is_instance_valid(safe_viewer) and safe_viewer.has_method("set_active"):
		safe_viewer.call("set_active", false)
	var regions := root.get_node_or_null("WorldRegionsDraftViewer")
	if is_instance_valid(regions) and regions.has_method("set_active") and bool(regions.call("is_active")):
		regions.call("set_active", false)


func _status_text() -> String:
	match _mode:
		MODE_LEGACY:
			return "F7 Slovenia compare • БЫЛО: legacy Layer 8 • 2 территории • F8 фокус"
		MODE_SAFE:
			return "F7 Slovenia compare • SAFE RAW: 193 исходные Admin-1 • F8 фокус"
		MODE_NORMALIZED:
			return "F7 Slovenia compare • СТАЛО: 12 Statistical Regions • F8 фокус"
		MODE_OVERLAY:
			return "F7 Slovenia compare • НАЛОЖЕНИЕ: красный=старое, голубой=новое • F8 фокус"
		_:
			return "F7: сравнение Admin-1 Словении"


func _update_panel() -> void:
	if not is_instance_valid(_mode_label):
		return
	var mode_name := "OFF"
	match _mode:
		MODE_LEGACY: mode_name = "БЫЛО — Layer 8"
		MODE_SAFE: mode_name = "SAFE RAW — 193"
		MODE_NORMALIZED: mode_name = "СТАЛО — 12 регионов"
		MODE_OVERLAY: mode_name = "НАЛОЖЕНИЕ"
	_mode_label.text = "Режим: %s\nLegacy: %d записей\nSAFE: %d parents / %d pieces\nНовый preview: %d parents / %d pieces" % [
		mode_name,
		_legacy_parts.size(),
		_safe_parent_ids.size(), _safe_parts.size(),
		_normalized_parent_ids.size(), _normalized_parts.size(),
	]
	_selection_label.text = "ЛКМ по территории — показать название"


func _focus_slovenia() -> void:
	if _slovenia_bbox.size.x <= 0.0 or _slovenia_bbox.size.y <= 0.0:
		return
	var camera := get_node_or_null("../Camera2D") as Camera2D
	if not is_instance_valid(camera):
		return
	camera.position = _slovenia_bbox.get_center()
	camera.zoom = Vector2(8.0, 8.0)
	_show_status(_status_text())


func _compute_bbox() -> void:
	var first := true
	var min_x := 0.0
	var min_y := 0.0
	var max_x := 0.0
	var max_y := 0.0
	for part in _normalized_parts:
		var bbox: Array = part.get("bbox", [])
		if bbox.size() < 4:
			continue
		if first:
			min_x = float(bbox[0]); min_y = float(bbox[1]); max_x = float(bbox[2]); max_y = float(bbox[3]); first = false
		else:
			min_x = minf(min_x, float(bbox[0])); min_y = minf(min_y, float(bbox[1])); max_x = maxf(max_x, float(bbox[2])); max_y = maxf(max_y, float(bbox[3]))
	if not first:
		_slovenia_bbox = Rect2(Vector2(min_x, min_y), Vector2(max_x - min_x, max_y - min_y))


func _hit_at_point(point: Vector2) -> Dictionary:
	var parts: Array[Dictionary] = _normalized_parts
	if _mode == MODE_LEGACY:
		parts = _legacy_parts
	elif _mode == MODE_SAFE:
		parts = _safe_parts
	for index in range(parts.size() - 1, -1, -1):
		var part: Dictionary = parts[index]
		var bbox: Array = part.get("bbox", [])
		if bbox.size() >= 4 and (point.x < float(bbox[0]) or point.y < float(bbox[1]) or point.x > float(bbox[2]) or point.y > float(bbox[3])):
			continue
		if _point_in_rings(point, part["rings"]):
			return part
	return {}


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


func _hash_color(value: String, alpha: float) -> Color:
	var h := absi(value.hash()) % 1000
	var color := Color.from_hsv(float(h) / 1000.0, 0.48, 0.92, alpha)
	color.a = alpha
	return color


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


func _show_status(text: String) -> void:
	var label := get_node_or_null("../UI/StatusLabel") as Label
	if is_instance_valid(label):
		label.text = text


func _build_panel() -> void:
	if not is_instance_valid(_ui_layer):
		return
	_panel = PanelContainer.new()
	_panel.offset_left = 1180.0
	_panel.offset_top = 80.0
	_panel.offset_right = 1885.0
	_panel.offset_bottom = 360.0
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
	title.text = "Словения — Admin-1 до/после [F7]"
	title.add_theme_font_size_override("font_size", 20)
	title.add_theme_color_override("font_color", Color(0.35, 0.94, 1.0, 1.0))
	box.add_child(title)
	var help := Label.new()
	help.text = "F7 — следующий режим   F8 — приблизить Словению\nНаложение: красный = старый Layer 8, голубой = новый preview"
	box.add_child(help)
	_mode_label = Label.new()
	box.add_child(_mode_label)
	_selection_label = Label.new()
	_selection_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(_selection_label)
