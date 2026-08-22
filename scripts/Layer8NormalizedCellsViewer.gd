extends Node2D
## World-wide visual inspection of all canonical normalized Layer-8 land cells.
##
## F6 — toggle all 12 902 generated cells.
## F5 — next gameplay province (Shift+F5 = previous).
## LMB — select a generated cell.
##
## Startup stays cheap: only the tiny world manifest is read in _ready(). The
## 16 canonical shard JSON files are parsed once, on the first F6/F5 request.
## Geometry is rendered by 16 batched CanvasItems instead of 12 902+ nodes.

const MANIFEST_PATH := "res://assets/land_cells_normalized/world_manifest.json"
const PIECE_SCRIPT := preload("res://scripts/Layer8MergeResultPieceNode.gd")
const SHARD_SCRIPT := preload("res://scripts/Layer8NormalizedWorldShardNode.gd")

const EXPECTED_SHARDS := 16
const EXPECTED_PARENTS := 2886
const EXPECTED_CELLS := 12902
const HIT_GRID_DEGREES := 2.0

var _active := false
var _last_error := ""
var _focus_index := -1
var _selected_cell_id := ""
var _world_loaded := false

var _manifest: Dictionary = {}
var _parents: Array[Dictionary] = []
var _parent_by_id: Dictionary = {}
var _cells: Array[Dictionary] = []
var _cell_by_id: Dictionary = {}
var _hit_grid: Dictionary = {}
var _shard_nodes: Array[Node2D] = []

var _geometry_root: Node2D
var _selection_root: Node2D
var _ui_layer: CanvasLayer
var _panel: PanelContainer
var _summary_label: Label
var _selection_label: Label


func _ready() -> void:
	z_index = 246
	_ui_layer = get_node_or_null("../UI") as CanvasLayer
	_geometry_root = Node2D.new()
	_geometry_root.name = "Layer8NormalizedWorldGeometry"
	add_child(_geometry_root)
	_selection_root = Node2D.new()
	_selection_root.name = "Layer8NormalizedCellSelection"
	_selection_root.z_index = 2
	add_child(_selection_root)
	_build_panel()
	_load_manifest()
	set_active(false)
	set_process_input(true)


func _input(event: InputEvent) -> void:
	var key := event as InputEventKey
	if key != null and key.pressed and not key.echo:
		if key.physical_keycode == KEY_F6 or key.keycode == KEY_F6:
			if _last_error.is_empty():
				set_active(not _active)
			else:
				_show_status("Normalized cells: %s" % _last_error)
			get_viewport().set_input_as_handled()
			return
		if key.physical_keycode == KEY_F5 or key.keycode == KEY_F5:
			if _last_error.is_empty():
				if not _active:
					set_active(true)
				if _active and _world_loaded:
					_focus_relative(-1 if key.shift_pressed else 1)
			else:
				_show_status("Normalized cells: %s" % _last_error)
			get_viewport().set_input_as_handled()
			return

	if not _active or not _world_loaded:
		return
	var mouse := event as InputEventMouseButton
	if mouse == null or not mouse.pressed or mouse.button_index != MOUSE_BUTTON_LEFT:
		return
	var hit := _hit_at_point(get_global_mouse_position())
	if not hit.is_empty():
		_select_cell(str(hit.get("id", "")))
		get_viewport().set_input_as_handled()


func set_active(value: bool) -> void:
	if value and _last_error.is_empty() and not _world_loaded:
		_show_status("F6: загрузка 16 shard / 12 902 клеток...")
		_ensure_world_loaded()

	_active = value and _last_error.is_empty() and _world_loaded
	if is_instance_valid(_geometry_root):
		_geometry_root.visible = _active
	if is_instance_valid(_selection_root):
		_selection_root.visible = _active
	if is_instance_valid(_panel):
		_panel.visible = _active
	if _active:
		_hide_conflicting_debug_layers()
		_show_status("F6: все 12 902 клетки • F5: следующая провинция • ЛКМ: клетка")
	else:
		_clear_selection()
		if _last_error.is_empty():
			_show_status("F6: показать все 12 902 нормализованные клетки")
	_update_summary()


func is_active() -> bool:
	return _active


func is_world_loaded() -> bool:
	return _world_loaded


func _load_manifest() -> void:
	if not FileAccess.file_exists(MANIFEST_PATH):
		_fail("не найден %s" % MANIFEST_PATH)
		return
	var raw: Variant = JSON.parse_string(FileAccess.get_file_as_string(MANIFEST_PATH))
	if typeof(raw) != TYPE_DICTIONARY:
		_fail("неверный JSON world_manifest")
		return
	_manifest = raw
	if str(_manifest.get("format", "")) != "layer8_normalized_land_cells_manifest/v1":
		_fail("неверный format world_manifest")
		return
	if not bool(_manifest.get("complete_and_valid", false)):
		_fail("world_manifest не помечен complete_and_valid")
		return
	if int(_manifest.get("province_count", 0)) != EXPECTED_PARENTS:
		_fail("ожидалось %d провинций, manifest=%d" % [EXPECTED_PARENTS, int(_manifest.get("province_count", 0))])
		return
	if int(_manifest.get("cell_count", 0)) != EXPECTED_CELLS:
		_fail("ожидалось %d клеток, manifest=%d" % [EXPECTED_CELLS, int(_manifest.get("cell_count", 0))])
		return
	var shards: Array = _manifest.get("shards", [])
	if shards.size() != EXPECTED_SHARDS:
		_fail("ожидалось %d shard, manifest=%d" % [EXPECTED_SHARDS, shards.size()])
		return
	_update_summary()


func _ensure_world_loaded() -> void:
	if _world_loaded or not _last_error.is_empty():
		return

	_parents.clear()
	_parent_by_id.clear()
	_cells.clear()
	_cell_by_id.clear()
	_hit_grid.clear()
	_shard_nodes.clear()
	_focus_index = -1

	for child in _geometry_root.get_children():
		child.queue_free()

	var base_dir := MANIFEST_PATH.get_base_dir()
	var manifest_shards: Array = _manifest.get("shards", [])
	for manifest_shard_raw in manifest_shards:
		if not manifest_shard_raw is Dictionary:
			_fail("manifest содержит неверную запись shard")
			return
		var manifest_shard: Dictionary = manifest_shard_raw
		var relative_path := str(manifest_shard.get("file", ""))
		if relative_path.is_empty():
			_fail("у shard отсутствует file")
			return
		var shard_path := base_dir.path_join(relative_path)
		if not FileAccess.file_exists(shard_path):
			_fail("не найден shard %s" % shard_path)
			return
		var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(shard_path))
		if typeof(parsed) != TYPE_DICTIONARY:
			_fail("неверный JSON %s" % shard_path)
			return
		var doc: Dictionary = parsed
		if str(doc.get("format", "")) != "layer8_normalized_land_cells/v1":
			_fail("неверный format %s" % shard_path)
			return

		var shard_cells: Array[Dictionary] = []
		for raw_parent_value in doc.get("provinces", []):
			if not raw_parent_value is Dictionary:
				continue
			var raw_parent: Dictionary = raw_parent_value
			var parent_id := str(raw_parent.get("gameplay_parent_id", ""))
			if parent_id.is_empty():
				continue
			if _parent_by_id.has(parent_id):
				_fail("дублирующийся gameplay parent %s" % parent_id)
				return

			var validation_value: Variant = raw_parent.get("validation", {})
			var validation: Dictionary = validation_value if validation_value is Dictionary else {}
			var anchor_value: Variant = raw_parent.get("capital_anchor", {})
			var anchor: Dictionary = anchor_value if anchor_value is Dictionary else {}
			var parent_bbox: Array = []
			var parent_view: Dictionary = {
				"gameplay_parent_id": parent_id,
				"display_name": str(raw_parent.get("display_name", parent_id)),
				"country_prefix": str(raw_parent.get("country_prefix", "")),
				"region_name": str(raw_parent.get("region_name", "")),
				"target_cell_count": int(raw_parent.get("target_cell_count", 0)),
				"normalized_area_km2": float(raw_parent.get("normalized_area_km2", 0.0)),
				"geometry_component_count": int(raw_parent.get("geometry_component_count", 0)),
				"attached_satellite_component_count": int(raw_parent.get("attached_satellite_component_count", 0)),
				"capital_anchor_source": str(anchor.get("source", "")),
				"validation_status": str(validation.get("status", "")),
			}

			for raw_cell_value in raw_parent.get("cells", []):
				if not raw_cell_value is Dictionary:
					continue
				var raw_cell: Dictionary = raw_cell_value
				var cell_id := str(raw_cell.get("id", ""))
				if cell_id.is_empty():
					continue
				if _cell_by_id.has(cell_id):
					_fail("дублирующийся cell ID %s" % cell_id)
					return
				var viewer_parts := _to_viewer_parts(raw_cell.get("parts", []))
				if viewer_parts.is_empty():
					_fail("клетка без drawable geometry: %s" % cell_id)
					return
				var raw_neighbors: Variant = raw_cell.get("neighbor_land_cell_ids", [])
				var neighbor_count := 0
				if raw_neighbors is Array:
					neighbor_count = raw_neighbors.size()
				var bbox_value: Variant = raw_cell.get("bbox", [])
				var bbox: Array = []
				if bbox_value is Array and bbox_value.size() >= 4:
					bbox = [float(bbox_value[0]), float(bbox_value[1]), float(bbox_value[2]), float(bbox_value[3])]
				var cell: Dictionary = {
					"id": cell_id,
					"gameplay_parent_id": parent_id,
					"display_parent_name": str(parent_view.get("display_name", parent_id)),
					"local_index": int(raw_cell.get("local_index", 0)),
					"cell_role": str(raw_cell.get("cell_role", "territory")),
					"area_km2": float(raw_cell.get("area_km2", 0.0)),
					"multipart": bool(raw_cell.get("multipart", false)),
					"neighbor_count": neighbor_count,
					"bbox": bbox,
					"viewer_parts": viewer_parts,
					"target_cell_count": int(parent_view.get("target_cell_count", 0)),
					"parent_area_km2": float(parent_view.get("normalized_area_km2", 0.0)),
					"capital_anchor_source": str(parent_view.get("capital_anchor_source", "")),
					"parent_validation_status": str(parent_view.get("validation_status", "")),
				}
				var cell_index := _cells.size()
				_cells.append(cell)
				_cell_by_id[cell_id] = cell
				shard_cells.append(cell)
				parent_bbox = _merge_bbox(parent_bbox, bbox)
				_index_cell(cell_index, bbox)

			parent_view["viewer_bbox"] = parent_bbox
			_parents.append(parent_view)
			_parent_by_id[parent_id] = parent_view

		var shard_node: Node2D = SHARD_SCRIPT.new()
		shard_node.name = "WorldCellShard_%02d" % int(manifest_shard.get("shard_index", _shard_nodes.size()))
		_geometry_root.add_child(shard_node)
		shard_node.call("setup", shard_cells)
		_shard_nodes.append(shard_node)

	_parents.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		return str(a.get("display_name", "")).naturalnocasecmp_to(str(b.get("display_name", ""))) < 0
	)

	if _shard_nodes.size() != EXPECTED_SHARDS:
		_fail("загружено shard nodes %d/%d" % [_shard_nodes.size(), EXPECTED_SHARDS])
		return
	if _parents.size() != EXPECTED_PARENTS or _parent_by_id.size() != EXPECTED_PARENTS:
		_fail("загружено провинций %d/%d" % [_parents.size(), EXPECTED_PARENTS])
		return
	if _cells.size() != EXPECTED_CELLS or _cell_by_id.size() != EXPECTED_CELLS:
		_fail("загружено клеток %d/%d" % [_cells.size(), EXPECTED_CELLS])
		return

	_world_loaded = true
	_update_summary()


func _focus_relative(delta: int) -> void:
	if _parents.is_empty():
		return
	if _focus_index < 0:
		_focus_index = 0 if delta >= 0 else _parents.size() - 1
	else:
		_focus_index = posmod(_focus_index + delta, _parents.size())
	var parent: Dictionary = _parents[_focus_index]
	_focus_bbox(parent.get("viewer_bbox", []))
	_clear_selection()
	_show_parent(parent)


func _focus_bbox(bbox: Array) -> void:
	if bbox.size() < 4:
		return
	var camera := get_node_or_null("../Camera2D") as Camera2D
	if not is_instance_valid(camera):
		return
	var min_x := float(bbox[0])
	var min_y := float(bbox[1])
	var max_x := float(bbox[2])
	var max_y := float(bbox[3])
	var width := maxf(max_x - min_x, 0.08)
	var height := maxf(max_y - min_y, 0.08)
	camera.position = Vector2((min_x + max_x) * 0.5, (min_y + max_y) * 0.5)
	var viewport_size := get_viewport_rect().size
	var zoom_value := clampf(minf(viewport_size.x / (width * 3.3), viewport_size.y / (height * 3.3)), 2.2, 120.0)
	camera.zoom = Vector2(zoom_value, zoom_value)


func _select_cell(cell_id: String) -> void:
	if cell_id.is_empty() or not _cell_by_id.has(cell_id):
		return
	_clear_selection()
	_selected_cell_id = cell_id
	var cell: Dictionary = _cell_by_id[cell_id]
	for raw_part in cell.get("viewer_parts", []):
		if not raw_part is Array:
			continue
		var rings: Array = raw_part
		if rings.is_empty():
			continue
		var node: Node2D = PIECE_SCRIPT.new()
		_selection_root.add_child(node)
		node.call("setup", rings, Color(0.24, 0.92, 1.0, 0.38), Color.WHITE, 0.08)
		node.call("set_selected", true)
	_show_cell(cell)


func _clear_selection() -> void:
	if is_instance_valid(_selection_root):
		for child in _selection_root.get_children():
			child.queue_free()
	_selected_cell_id = ""


func _show_parent(parent: Dictionary) -> void:
	if not is_instance_valid(_selection_label):
		return
	_selection_label.text = "F5 [%d/%d]\nПровинция: %s\nСтрана: %s\nРегион: %s\nКлеток: %d\nПлощадь: %.1f км²\nКомпонентов суши: %d\nСпутников прикреплено: %d\nAnchor: %s\nValidation: %s\nID: %s" % [
		_focus_index + 1,
		_parents.size(),
		str(parent.get("display_name", "?")),
		str(parent.get("country_prefix", "?")),
		str(parent.get("region_name", "?")),
		int(parent.get("target_cell_count", 0)),
		float(parent.get("normalized_area_km2", 0.0)),
		int(parent.get("geometry_component_count", 0)),
		int(parent.get("attached_satellite_component_count", 0)),
		str(parent.get("capital_anchor_source", "?")),
		str(parent.get("validation_status", "?")),
		str(parent.get("gameplay_parent_id", "?")),
	]
	_show_status("%s • %d клеток • %.1f км²" % [str(parent.get("display_name", "?")), int(parent.get("target_cell_count", 0)), float(parent.get("normalized_area_km2", 0.0))])


func _show_cell(cell: Dictionary) -> void:
	if not is_instance_valid(_selection_label):
		return
	_selection_label.text = "КЛЕТКА\nПровинция: %s\nНомер: %d / %d\nРоль: %s\nПлощадь клетки: %.1f км²\nПлощадь провинции: %.1f км²\nMultipart: %s\nСоседей: %d\nAnchor source: %s\nValidation: %s\nID: %s" % [
		str(cell.get("display_parent_name", "?")),
		int(cell.get("local_index", 0)),
		int(cell.get("target_cell_count", 0)),
		str(cell.get("cell_role", "territory")),
		float(cell.get("area_km2", 0.0)),
		float(cell.get("parent_area_km2", 0.0)),
		str(bool(cell.get("multipart", false))),
		int(cell.get("neighbor_count", 0)),
		str(cell.get("capital_anchor_source", "?")),
		str(cell.get("parent_validation_status", "?")),
		str(cell.get("id", "?")),
	]
	_show_status("%s • клетка %d • %.1f км²" % [str(cell.get("display_parent_name", "?")), int(cell.get("local_index", 0)), float(cell.get("area_km2", 0.0))])


func _hit_at_point(point: Vector2) -> Dictionary:
	var key := Vector2i(int(floor(point.x / HIT_GRID_DEGREES)), int(floor(point.y / HIT_GRID_DEGREES)))
	var candidates_value: Variant = _hit_grid.get(key, [])
	if not candidates_value is Array:
		return {}
	var candidates: Array = candidates_value
	for candidate_pos in range(candidates.size() - 1, -1, -1):
		var cell_index := int(candidates[candidate_pos])
		if cell_index < 0 or cell_index >= _cells.size():
			continue
		var cell: Dictionary = _cells[cell_index]
		var bbox: Array = cell.get("bbox", [])
		if bbox.size() >= 4 and (point.x < float(bbox[0]) or point.y < float(bbox[1]) or point.x > float(bbox[2]) or point.y > float(bbox[3])):
			continue
		for raw_part in cell.get("viewer_parts", []):
			if raw_part is Array and _point_in_rings(point, raw_part):
				return cell
	return {}


func _index_cell(cell_index: int, bbox: Array) -> void:
	if bbox.size() < 4:
		return
	var ix0 := int(floor(float(bbox[0]) / HIT_GRID_DEGREES))
	var iy0 := int(floor(float(bbox[1]) / HIT_GRID_DEGREES))
	var ix1 := int(floor(float(bbox[2]) / HIT_GRID_DEGREES))
	var iy1 := int(floor(float(bbox[3]) / HIT_GRID_DEGREES))
	for ix in range(ix0, ix1 + 1):
		for iy in range(iy0, iy1 + 1):
			var key := Vector2i(ix, iy)
			var bucket_value: Variant = _hit_grid.get(key, [])
			var bucket: Array = bucket_value if bucket_value is Array else []
			bucket.append(cell_index)
			_hit_grid[key] = bucket


func _update_summary() -> void:
	if not is_instance_valid(_summary_label):
		return
	if not _last_error.is_empty():
		_summary_label.text = "Ошибка: %s" % _last_error
		return
	if _manifest.is_empty():
		_summary_label.text = "Чтение world manifest..."
		return
	var status_value: Variant = _manifest.get("status_counts", {})
	var status_counts: Dictionary = status_value if status_value is Dictionary else {}
	var pass_count := int(status_counts.get("PASS", 0))
	var warning_count := int(status_counts.get("ACCEPTED_WITH_WARNINGS", 0))
	var state := "ЗАГРУЖЕНО" if _world_loaded else "готово к загрузке по F6"
	_summary_label.text = "Мир: %d провинций\nКлеток: %d\nShard: %d/%d\nPASS: %d\nAccepted with warnings: %d\nMultipart клеток: %d\nСостояние: %s\n\nF5 — следующая провинция\nShift+F5 — предыдущая\nЛКМ — клетка" % [
		int(_manifest.get("province_count", 0)),
		int(_manifest.get("cell_count", 0)),
		_shard_nodes.size() if _world_loaded else 0,
		EXPECTED_SHARDS,
		pass_count,
		warning_count,
		int(_manifest.get("multipart_cell_count", 0)),
		state,
	]
	if is_instance_valid(_selection_label) and _selection_label.text.is_empty():
		_selection_label.text = "F6 подключает канонические 16 shard.\nЭто полный мировой слой: 2 886 gameplay-провинций и 12 902 реальные внутренние клетки."


func _hide_conflicting_debug_layers() -> void:
	var root := get_parent()
	if not is_instance_valid(root):
		return
	for node_name in ["Layer8SmallProvinceViewer", "Layer8MergeResultViewer", "WorldAdmin1SafeViewer", "WorldRegionsDraftViewer", "SloveniaAdmin1ComparisonViewer"]:
		var viewer := root.get_node_or_null(node_name)
		if is_instance_valid(viewer) and viewer.has_method("set_active"):
			viewer.call("set_active", false)


func _point_in_rings(point: Vector2, rings: Array) -> bool:
	if rings.is_empty():
		return false
	var outer_value: Variant = rings[0]
	if not outer_value is PackedVector2Array:
		return false
	var outer: PackedVector2Array = outer_value
	if not Geometry2D.is_point_in_polygon(point, outer):
		return false
	for i in range(1, rings.size()):
		var hole_value: Variant = rings[i]
		if hole_value is PackedVector2Array and Geometry2D.is_point_in_polygon(point, hole_value):
			return false
	return true


func _to_viewer_parts(raw_parts: Variant) -> Array:
	var result: Array = []
	if not raw_parts is Array:
		return result
	for raw_part_value in raw_parts:
		if not raw_part_value is Dictionary:
			continue
		var raw_part: Dictionary = raw_part_value
		var rings := _to_rings(raw_part.get("rings", []))
		if not rings.is_empty():
			result.append(rings)
	return result


func _to_rings(raw_rings: Variant) -> Array:
	var result: Array = []
	if not raw_rings is Array:
		return result
	for raw_ring in raw_rings:
		if not raw_ring is Array:
			continue
		var ring := PackedVector2Array()
		for raw_point in raw_ring:
			if raw_point is Array and raw_point.size() >= 2:
				ring.append(Vector2(float(raw_point[0]), float(raw_point[1])))
		if ring.size() >= 3:
			if not ring[0].is_equal_approx(ring[ring.size() - 1]):
				ring.append(ring[0])
			result.append(ring)
	return result


func _merge_bbox(current: Array, raw_bbox: Variant) -> Array:
	if not raw_bbox is Array or raw_bbox.size() < 4:
		return current
	var bbox := [float(raw_bbox[0]), float(raw_bbox[1]), float(raw_bbox[2]), float(raw_bbox[3])]
	if current.size() < 4:
		return bbox
	return [
		minf(float(current[0]), bbox[0]),
		minf(float(current[1]), bbox[1]),
		maxf(float(current[2]), bbox[2]),
		maxf(float(current[3]), bbox[3]),
	]


func _show_status(text: String) -> void:
	var label := get_node_or_null("../UI/StatusLabel") as Label
	if is_instance_valid(label):
		label.text = text


func _fail(message: String) -> void:
	if _last_error.is_empty():
		_last_error = message
	push_error("Layer8NormalizedCellsViewer: %s" % message)
	_update_summary()


func _build_panel() -> void:
	if not is_instance_valid(_ui_layer):
		return
	_panel = PanelContainer.new()
	_panel.offset_left = 1110.0
	_panel.offset_top = 55.0
	_panel.offset_right = 1890.0
	_panel.offset_bottom = 610.0
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
	title.text = "Все внутренние клетки мира [F6]"
	title.add_theme_font_size_override("font_size", 20)
	title.add_theme_color_override("font_color", Color(0.70, 0.96, 1.0, 1.0))
	box.add_child(title)

	_summary_label = Label.new()
	_summary_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(_summary_label)

	var separator := HSeparator.new()
	box.add_child(separator)

	_selection_label = Label.new()
	_selection_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_selection_label.custom_minimum_size = Vector2(730.0, 235.0)
	box.add_child(_selection_label)
