extends Node2D
## Отдельный просмотрщик нового безопасного слоя логических Admin-1.
##
## P — показать/скрыть слой.
## ЛКМ — выбрать логическую провинцию. Если провинция состоит из нескольких
## Polygon-pieces, подсвечиваются все её части одновременно.
##
## ВАЖНО: этот viewer НЕ заменяет старый Layer-8. Он специально существует
## параллельно, пока регионы/target-cell pipeline мигрируют на logical_admin1_id.

const PIECES_PATH := "res://assets/map_geometry/world_admin1_safe_pieces.json"
const PARENTS_PATH := "res://assets/game_data/world_admin1_logical_parents.json"
const PIECES_FORMAT := "world_admin1_safe_pieces/v1"
const PARENTS_FORMAT := "world_admin1_logical_parents/v1"
const PIECE_SCRIPT := preload("res://scripts/WorldAdmin1SafePieceNode.gd")
const BUILD_BATCH_PER_FRAME := 96
const EXPECTED_PARENT_COUNT := 4564
const EXPECTED_PIECE_COUNT := 8175

var _ui_layer: CanvasLayer
var _root_viewer: Node
var _panel: PanelContainer
var _summary: Label
var _selection_label: Label
var _render_root: Node2D

var _pieces: Array[Dictionary] = []
var _parent_by_id: Dictionary = {}
var _piece_nodes_by_parent: Dictionary = {}
var _parent_count := 0
var _piece_count := 0
var _selected_parent_id := ""
var _last_error := ""

var _build_cursor := 0
var _building := false
var _render_ready := false


func _ready() -> void:
	_ui_layer = get_node_or_null("../UI") as CanvasLayer
	_root_viewer = get_parent()
	z_index = 220

	_render_root = Node2D.new()
	_render_root.name = "CachedWorldAdmin1SafePieces"
	add_child(_render_root)

	visible = false
	_load_data()
	_build_panel()
	set_process(false)
	set_process_input(true)


func _input(event: InputEvent) -> void:
	var key := event as InputEventKey
	if key != null and key.pressed and not key.echo and (key.physical_keycode == KEY_P or key.keycode == KEY_P):
		if _last_error.is_empty():
			set_active(not visible)
		else:
			_show_top_info("Новые Admin-1: %s" % _last_error)
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
	var parent_id := str(hit.get("logical_admin1_id", ""))
	_set_selected_parent(parent_id)
	_show_selected_info(parent_id)
	get_viewport().set_input_as_handled()


func set_active(active: bool) -> void:
	if active and not _last_error.is_empty():
		return
	visible = active
	if is_instance_valid(_panel):
		_panel.visible = active

	if active:
		_hide_conflicting_debug_layers()
		_ensure_render_build_started()
		if _building:
			set_process(true)
			_show_top_info("P: новые Admin-1 • подготовка %d/%d polygon-pieces…" % [_build_cursor, _pieces.size()])
		else:
			_show_top_info("P: новые Admin-1 • %d логических провинций • %d polygon-pieces • ЛКМ выбрать" % [_parent_count, _piece_count])
	else:
		set_process(false)
		_show_top_info("Новый Admin-1 слой скрыт")


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

	var stop := mini(_build_cursor + BUILD_BATCH_PER_FRAME, _pieces.size())
	for index in range(_build_cursor, stop):
		_create_piece_node(_pieces[index], index)
	_build_cursor = stop

	if _build_cursor >= _pieces.size():
		_building = false
		_render_ready = true
		set_process(false)
		_show_top_info("P: новый Admin-1 слой готов • %d провинций • %d частей закэшировано" % [_parent_count, _piece_count])
	elif _build_cursor % (BUILD_BATCH_PER_FRAME * 8) == 0:
		_show_top_info("P: подготовка нового Admin-1 слоя %d/%d…" % [_build_cursor, _pieces.size()])


func _create_piece_node(part: Dictionary, index: int) -> void:
	var parent_id := str(part.get("logical_admin1_id", ""))
	if parent_id.is_empty():
		return
	var piece: Node2D = PIECE_SCRIPT.new()
	piece.name = "Admin1SafePiece_%d" % index
	_render_root.add_child(piece)
	piece.call("setup", parent_id, part["rings"], _parent_color(parent_id))
	if not _piece_nodes_by_parent.has(parent_id):
		_piece_nodes_by_parent[parent_id] = []
	var nodes: Array = _piece_nodes_by_parent[parent_id]
	nodes.append(piece)
	_piece_nodes_by_parent[parent_id] = nodes
	if parent_id == _selected_parent_id:
		piece.call("set_selected", true)


func _set_selected_parent(parent_id: String) -> void:
	if _selected_parent_id == parent_id:
		return
	if not _selected_parent_id.is_empty() and _piece_nodes_by_parent.has(_selected_parent_id):
		for node in (_piece_nodes_by_parent[_selected_parent_id] as Array):
			if is_instance_valid(node):
				node.call("set_selected", false)
	_selected_parent_id = parent_id
	if not _selected_parent_id.is_empty() and _piece_nodes_by_parent.has(_selected_parent_id):
		for node in (_piece_nodes_by_parent[_selected_parent_id] as Array):
			if is_instance_valid(node):
				node.call("set_selected", true)
	_update_selection_label()


func _load_data() -> bool:
	if not FileAccess.file_exists(PIECES_PATH):
		return _fail("не найден %s" % PIECES_PATH)
	if not FileAccess.file_exists(PARENTS_PATH):
		return _fail("не найден %s" % PARENTS_PATH)

	var pieces_parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(PIECES_PATH))
	var parents_parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(PARENTS_PATH))
	if typeof(pieces_parsed) != TYPE_DICTIONARY:
		return _fail("safe pieces JSON имеет неверный формат")
	if typeof(parents_parsed) != TYPE_DICTIONARY:
		return _fail("logical parents JSON имеет неверный формат")

	var pieces_doc: Dictionary = pieces_parsed
	var parents_doc: Dictionary = parents_parsed
	if str(pieces_doc.get("format", "")) != PIECES_FORMAT:
		return _fail("неподдерживаемый pieces format: %s" % str(pieces_doc.get("format", "")))
	if str(parents_doc.get("format", "")) != PARENTS_FORMAT:
		return _fail("неподдерживаемый parents format: %s" % str(parents_doc.get("format", "")))

	_parent_by_id.clear()
	for raw_parent in parents_doc.get("parents", []):
		if not raw_parent is Dictionary:
			continue
		var parent: Dictionary = raw_parent
		var parent_id := str(parent.get("logical_admin1_id", ""))
		if not parent_id.is_empty():
			_parent_by_id[parent_id] = parent

	_pieces.clear()
	var unknown_parent_count := 0
	for raw_piece in pieces_doc.get("pieces", []):
		if not raw_piece is Dictionary:
			continue
		var source_piece: Dictionary = raw_piece
		var parent_id := str(source_piece.get("logical_admin1_id", ""))
		var rings := _to_rings(source_piece.get("rings", []))
		if parent_id.is_empty() or rings.is_empty():
			continue
		if not _parent_by_id.has(parent_id):
			unknown_parent_count += 1
			continue
		_pieces.append({
			"piece_id": str(source_piece.get("piece_id", "")),
			"logical_admin1_id": parent_id,
			"bbox": source_piece.get("bbox", []),
			"rings": rings,
		})

	_parent_count = int(parents_doc.get("logical_parent_count", _parent_by_id.size()))
	_piece_count = int(pieces_doc.get("piece_count", _pieces.size()))
	if _parent_count != EXPECTED_PARENT_COUNT or _parent_by_id.size() != EXPECTED_PARENT_COUNT:
		return _fail("ожидалось %d logical Admin-1, получено header=%d loaded=%d" % [EXPECTED_PARENT_COUNT, _parent_count, _parent_by_id.size()])
	if _piece_count != EXPECTED_PIECE_COUNT or _pieces.size() != EXPECTED_PIECE_COUNT:
		return _fail("ожидалось %d polygon-pieces, получено header=%d loaded=%d" % [EXPECTED_PIECE_COUNT, _piece_count, _pieces.size()])
	if unknown_parent_count != 0:
		return _fail("%d polygon-pieces с неизвестным logical_admin1_id" % unknown_parent_count)

	_last_error = ""
	return true


func _parent_color(parent_id: String) -> Color:
	var h := absi(parent_id.hash()) % 1000
	return Color.from_hsv(float(h) / 1000.0, 0.40, 0.90, 0.22)


func _part_at_point(point: Vector2) -> Dictionary:
	for index in range(_pieces.size() - 1, -1, -1):
		var part: Dictionary = _pieces[index]
		var bbox: Array = part.get("bbox", [])
		if bbox.size() >= 4:
			if point.x < float(bbox[0]) or point.y < float(bbox[1]) or point.x > float(bbox[2]) or point.y > float(bbox[3]):
				continue
		var rings: Array = part["rings"]
		if _point_in_rings(point, rings):
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


func _show_selected_info(parent_id: String) -> void:
	var parent: Dictionary = _parent_by_id.get(parent_id, {})
	if parent.is_empty():
		return
	var name := str(parent.get("name", parent_id))
	var admin := str(parent.get("admin", "?"))
	var area := float(parent.get("source_geodesic_area_km2", 0.0))
	var piece_count := int(parent.get("piece_count", 0))
	var source_count := int(parent.get("source_feature_count", 0))
	var explicit := bool(parent.get("explicit_aggregation", false))
	_show_top_info("Новая провинция • %s • %s • %.1f км² • pieces %d • source %d%s" % [name, admin, area, piece_count, source_count, " • explicit aggregate" if explicit else ""])


func _update_selection_label() -> void:
	if not is_instance_valid(_selection_label):
		return
	if _selected_parent_id.is_empty() or not _parent_by_id.has(_selected_parent_id):
		_selection_label.text = "Выбрано: —"
		return
	var parent: Dictionary = _parent_by_id[_selected_parent_id]
	_selection_label.text = "Выбрано: %s\nСтрана: %s\nПлощадь: %.1f км²\nPolygon-pieces: %d\nSource features: %d\nID: %s" % [
		str(parent.get("name", "?")),
		str(parent.get("admin", "?")),
		float(parent.get("source_geodesic_area_km2", 0.0)),
		int(parent.get("piece_count", 0)),
		int(parent.get("source_feature_count", 0)),
		_selected_parent_id,
	]


func _hide_conflicting_debug_layers() -> void:
	if not is_instance_valid(_root_viewer):
		return
	var regions := _root_viewer.get_node_or_null("WorldRegionsDraftViewer")
	if is_instance_valid(regions) and regions.has_method("set_active") and bool(regions.call("is_active")):
		regions.call("set_active", false)
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
	_panel.offset_left = 1210.0
	_panel.offset_top = 460.0
	_panel.offset_right = 1896.0
	_panel.offset_bottom = 800.0
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
	title.text = "Новые провинции — SAFE Admin-1 [P]"
	title.add_theme_color_override("font_color", Color(0.35, 0.94, 1.0, 1.0))
	title.add_theme_font_size_override("font_size", 20)
	box.add_child(title)

	var note := Label.new()
	note.text = "Отдельный слой поверх старых провинций. 4564 logical Admin-1; Polygon-pieces используются только для геометрии. Старый Layer-8 пока не заменяется."
	note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(note)

	_summary = Label.new()
	_summary.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	if _last_error.is_empty():
		_summary.text = "• Логических провинций: %d\n• Polygon-pieces: %d\n• P — показать/скрыть\n• ЛКМ — выбрать провинцию\n• Первый запуск: пакетное кэширование" % [_parent_count, _piece_count]
	else:
		_summary.text = "Ошибка: %s" % _last_error
	box.add_child(_summary)

	_selection_label = Label.new()
	_selection_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_selection_label.text = "Выбрано: —"
	box.add_child(_selection_label)


func _show_top_info(message: String) -> void:
	if is_instance_valid(_root_viewer) and _root_viewer.has_method("_show_top_info"):
		_root_viewer.call("_show_top_info", message)
	else:
		print(message)


func _fail(message: String) -> bool:
	_last_error = message
	push_warning("WorldAdmin1SafeViewer: %s" % message)
	return false
