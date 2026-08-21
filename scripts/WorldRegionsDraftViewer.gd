extends Node2D
## Мировой черновой слой историко-географических регионов.
##
## PERF v2: каждый polygon part — отдельный кэшируемый CanvasItem.
## I предпочитает island-corrected слой, но умеет откатиться на старый draft,
## если исправленные assets ещё не подтянуты локально.

const CORRECTED_DATA_PATH := "res://assets/regions_world_island_corrected.json"
const FALLBACK_DATA_PATH := "res://assets/regions_world_draft.json"
const CORRECTED_ASSIGNMENTS_PATH := "res://assets/game_data/world_region_assignments_island_corrected.json"
const FALLBACK_ASSIGNMENTS_PATH := "res://assets/game_data/world_region_assignments_draft.json"
const CORRECTED_FORMAT := "world_regions_island_corrected/v1"
const FALLBACK_FORMAT := "world_regions_draft/v1"
const PIECE_SCRIPT := preload("res://scripts/WorldRegionPieceNode.gd")
const BUILD_BATCH_PER_FRAME := 48

var _camera: Camera2D
var _ui_layer: CanvasLayer
var _root_viewer: Node
var _panel: PanelContainer
var _summary: Label
var _render_root: Node2D

var _parts: Array[Dictionary] = []
var _province_count_by_region: Dictionary = {}
var _region_name_by_id: Dictionary = {}
var _piece_nodes_by_region: Dictionary = {}
var _region_count := 0
var _province_count := 0
var _piece_count := 0
var _selected_region_id := ""
var _last_error := ""
var _source_label := "DRAFT"

var _build_cursor := 0
var _building := false
var _render_ready := false


func _ready() -> void:
	_camera = get_node_or_null("../Camera2D") as Camera2D
	_ui_layer = get_node_or_null("../UI") as CanvasLayer
	_root_viewer = get_parent()
	z_index = 210

	_render_root = Node2D.new()
	_render_root.name = "CachedWorldRegionPieces"
	add_child(_render_root)

	visible = false
	_load_data()
	_build_panel()
	set_process(false)
	set_process_input(true)


func _input(event: InputEvent) -> void:
	var key := event as InputEventKey
	if key != null and key.pressed and not key.echo and (key.physical_keycode == KEY_I or key.keycode == KEY_I):
		if _last_error.is_empty():
			set_active(not visible)
		else:
			_show_top_info("Мировые регионы: %s" % _last_error)
		get_viewport().set_input_as_handled()
		return

	if not visible:
		return
	var mouse := event as InputEventMouseButton
	if mouse == null or not mouse.pressed or mouse.button_index != MOUSE_BUTTON_LEFT:
		return
	var hit := _part_at_point(get_global_mouse_position())
	if hit.is_empty():
		return
	var new_region_id := str(hit.get("region_id", ""))
	_set_selected_region(new_region_id)
	var region_name := str(_region_name_by_id.get(new_region_id, hit.get("name", "?")))
	var provinces := int(_province_count_by_region.get(new_region_id, 0))
	_show_top_info("Регион • %s • %d провинций • %s" % [region_name, provinces, new_region_id])
	get_viewport().set_input_as_handled()


func set_active(active: bool) -> void:
	if active and not _last_error.is_empty():
		return
	visible = active
	if is_instance_valid(_panel):
		_panel.visible = active

	if active:
		_hide_other_subdivision_debug()
		_ensure_render_build_started()
		if _building:
			set_process(true)
			_show_top_info("I: мировые регионы %s • подготовка кэша %d/%d частей…" % [_source_label, _build_cursor, _parts.size()])
		else:
			_show_top_info("I: мировые регионы %s • %d регионов • %d провинций • ЛКМ выбрать" % [_source_label, _region_count, _province_count])
	else:
		set_process(false)
		_show_top_info("Мировые регионы скрыты")


func is_active() -> bool:
	return visible


func _ensure_render_build_started() -> void:
	if _render_ready:
		return
	if not _building:
		_building = true
		_build_cursor = 0


func _process(_delta: float) -> void:
	if not visible or not _building:
		return

	var stop := mini(_build_cursor + BUILD_BATCH_PER_FRAME, _parts.size())
	for index in range(_build_cursor, stop):
		_create_piece_node(_parts[index])
	_build_cursor = stop

	if _build_cursor >= _parts.size():
		_building = false
		_render_ready = true
		set_process(false)
		_show_top_info("I: мировой слой %s готов • %d регионов • %d провинций • %d частей закэшировано" % [_source_label, _region_count, _province_count, _parts.size()])
	elif _build_cursor % (BUILD_BATCH_PER_FRAME * 6) == 0:
		_show_top_info("I: подготовка мирового слоя %d/%d…" % [_build_cursor, _parts.size()])


func _create_piece_node(part: Dictionary) -> void:
	var region_id := str(part.get("region_id", ""))
	if region_id.is_empty():
		return
	var piece: Node2D = PIECE_SCRIPT.new()
	piece.name = "RegionPiece_%d" % _build_cursor
	_render_root.add_child(piece)
	piece.call("setup", region_id, part["rings"], _region_color(region_id))
	if not _piece_nodes_by_region.has(region_id):
		_piece_nodes_by_region[region_id] = []
	var nodes: Array = _piece_nodes_by_region[region_id]
	nodes.append(piece)
	_piece_nodes_by_region[region_id] = nodes
	if region_id == _selected_region_id:
		piece.call("set_selected", true)


func _set_selected_region(region_id: String) -> void:
	if _selected_region_id == region_id:
		return
	if not _selected_region_id.is_empty() and _piece_nodes_by_region.has(_selected_region_id):
		for node in (_piece_nodes_by_region[_selected_region_id] as Array):
			if is_instance_valid(node):
				node.call("set_selected", false)
	_selected_region_id = region_id
	if not _selected_region_id.is_empty() and _piece_nodes_by_region.has(_selected_region_id):
		for node in (_piece_nodes_by_region[_selected_region_id] as Array):
			if is_instance_valid(node):
				node.call("set_selected", true)


func _load_data() -> bool:
	var data_path := CORRECTED_DATA_PATH if FileAccess.file_exists(CORRECTED_DATA_PATH) else FALLBACK_DATA_PATH
	var assignments_path := CORRECTED_ASSIGNMENTS_PATH if FileAccess.file_exists(CORRECTED_ASSIGNMENTS_PATH) else FALLBACK_ASSIGNMENTS_PATH
	_source_label = "ISLAND-CORRECTED" if data_path == CORRECTED_DATA_PATH else "DRAFT"

	if not FileAccess.file_exists(data_path):
		return _fail("не найден мировой слой — сделай git pull")
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(data_path))
	if typeof(parsed) != TYPE_DICTIONARY:
		return _fail("мировой regions JSON имеет неверный формат")
	var data: Dictionary = parsed
	var data_format := str(data.get("format", ""))
	if data_format != CORRECTED_FORMAT and data_format != FALLBACK_FORMAT:
		return _fail("неподдерживаемый формат мировых регионов: %s" % data_format)

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

	if FileAccess.file_exists(assignments_path):
		var ap: Variant = JSON.parse_string(FileAccess.get_file_as_string(assignments_path))
		if typeof(ap) == TYPE_DICTIONARY:
			for raw_assignment in (ap as Dictionary).get("assignments", []):
				if not raw_assignment is Dictionary:
					continue
				var rid := str((raw_assignment as Dictionary).get("region_id", ""))
				if not rid.is_empty():
					_province_count_by_region[rid] = int(_province_count_by_region.get(rid, 0)) + 1

	if _parts.is_empty():
		return _fail("мировой слой не содержит polygon parts")
	_last_error = ""
	return true


func _region_color(region_id: String) -> Color:
	var h := absi(region_id.hash()) % 1000
	return Color.from_hsv(float(h) / 1000.0, 0.46, 0.90, 0.30)


func _part_at_point(point: Vector2) -> Dictionary:
	for index in range(_parts.size() - 1, -1, -1):
		var part: Dictionary = _parts[index]
		var bbox: Array = part.get("bbox", [])
		if bbox.size() >= 4:
			if point.x < float(bbox[0]) or point.y < float(bbox[1]) or point.x > float(bbox[2]) or point.y > float(bbox[3]):
				continue
		var rings: Array = part["rings"]
		if not rings.is_empty() and _point_in_rings(point, rings):
			return part
	return {}


func _point_in_rings(point: Vector2, rings: Array) -> bool:
	if rings.is_empty():
		return false
	if not Geometry2D.is_point_in_polygon(point, rings[0]):
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


func _hide_other_subdivision_debug() -> void:
	if not is_instance_valid(_root_viewer):
		return
	for node_name in ["SubdivisionStage4InputBridge", "SubdivisionStage5InputBridge", "SubdivisionStage6InputBridge"]:
		var node := _root_viewer.get_node_or_null(node_name)
		if not is_instance_valid(node):
			continue
		if node.has_method("hide_stage4"):
			node.call("hide_stage4")
		if node.has_method("hide_stage5"):
			node.call("hide_stage5")
		if node.has_method("hide_stage6"):
			node.call("hide_stage6")


func _build_panel() -> void:
	if not is_instance_valid(_ui_layer):
		return
	_panel = PanelContainer.new()
	_panel.offset_left = 1280.0
	_panel.offset_top = 90.0
	_panel.offset_right = 1896.0
	_panel.offset_bottom = 420.0
	_panel.visible = false
	_ui_layer.add_child(_panel)

	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 14)
	margin.add_theme_constant_override("margin_top", 12)
	margin.add_theme_constant_override("margin_right", 14)
	margin.add_theme_constant_override("margin_bottom", 12)
	_panel.add_child(margin)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 6)
	margin.add_child(box)

	var title := Label.new()
	title.text = "Мировые регионы — %s" % _source_label
	title.add_theme_color_override("font_color", Color(1.0, 0.84, 0.52, 1.0))
	title.add_theme_font_size_override("font_size", 20)
	box.add_child(title)

	var note := Label.new()
	note.text = "Регионы собраны только из целых провинций слоя 8. Island-corrected версия фиксирует куски одного Admin-1 в разных регионах, Готланд и европейские атлантические острова. Рендер кэшируется один раз."
	note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(note)

	_summary = Label.new()
	_summary.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	if _last_error.is_empty():
		_summary.text = "• Провинций: %d\n• Регионов: %d\n• Полигональных частей: %d\n• Первый I: пакетная подготовка кэша\n• Следующие I: мгновенно\n• ЛКМ — информация о регионе" % [_province_count, _region_count, _piece_count]
	else:
		_summary.text = "Ошибка: %s" % _last_error
	box.add_child(_summary)


func _show_top_info(message: String) -> void:
	if is_instance_valid(_root_viewer) and _root_viewer.has_method("_show_top_info"):
		_root_viewer.call("_show_top_info", message)
	else:
		print(message)


func _fail(message: String) -> bool:
	_last_error = message
	push_warning("WorldRegionsDraftViewer: %s" % message)
	return false
