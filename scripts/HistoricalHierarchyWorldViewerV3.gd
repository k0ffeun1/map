extends Node2D
## v3 historical geography built strictly from canonical Layer-8 province atoms.
##
## X — 897 regions
## C — 193 superregions
## V — 64 macroregions
## B — 20 megaregions
##
## The hierarchy is structural: every C contains >= 2 X, every V contains >= 2 C,
## every B contains >= 2 V. Layer 8 supplies only province geometry/IDs.

const CATALOG_DIR := "res://assets/game_data/historical_hierarchy_v1"
const EXPECTED_PARENTS := 2886
const EXPECTED_CELLS := 12902
const EXPECTED_REGIONS := 897
const EXPECTED_SUPERS := 193
const EXPECTED_MACROS := 64
const EXPECTED_MEGAS := 20
const CHUNK_WORLD_PX := 512.0

const CHUNK_SCRIPT := preload("res://scripts/HistoricalHierarchyChunkNode.gd")
const CATALOG_SCRIPT := preload("res://scripts/HistoricalHierarchyCatalogV3.gd")
const BUILDER_SCRIPT := preload("res://scripts/HistoricalHierarchyAssignmentBuilder.gd")

var _viewer: Node
var _f6_viewer: Node
var _active_mode := ""
var _rendered_mode := ""
var _last_error := ""
var _ready_data := false

var _catalog: RefCounted
var _builder: RefCounted
var _parents: Array = []
var _cells: Array = []
var _assignments: Dictionary = {}

var _geometry_root: Node2D
var _selection_root: Node2D
var _chunk_nodes: Array[Node2D] = []
var _selection_nodes: Array[Node2D] = []


func _ready() -> void:
	z_index = 242
	set_process_input(true)

	_geometry_root = Node2D.new()
	_geometry_root.name = "HistoricalHierarchyV3Geometry"
	_geometry_root.visible = false
	add_child(_geometry_root)

	_selection_root = Node2D.new()
	_selection_root.name = "HistoricalHierarchyV3Selection"
	_selection_root.z_index = 2
	_selection_root.visible = false
	add_child(_selection_root)

	_catalog = CATALOG_SCRIPT.new()
	var loaded := bool(_catalog.call(
		"load_from_dir",
		CATALOG_DIR,
		EXPECTED_REGIONS,
		EXPECTED_SUPERS,
		EXPECTED_MACROS,
		EXPECTED_MEGAS
	))
	if not loaded:
		_fail(str(_catalog.get("last_error")))

	call_deferred("_bind_viewer")


func _bind_viewer() -> void:
	_viewer = get_parent()
	if not is_instance_valid(_viewer):
		_fail("нет TileMapViewer")
		return
	_f6_viewer = _viewer.get_node_or_null("Layer8NormalizedCellsViewer")
	if not is_instance_valid(_f6_viewer):
		_fail("не найден Layer8NormalizedCellsViewer")


func _input(event: InputEvent) -> void:
	var key := event as InputEventKey
	if key != null and key.pressed and not key.echo:
		var mode := ""
		if key.physical_keycode == KEY_X or key.keycode == KEY_X:
			mode = "region"
		elif key.physical_keycode == KEY_C or key.keycode == KEY_C:
			mode = "superregion"
		elif key.physical_keycode == KEY_V or key.keycode == KEY_V:
			mode = "macroregion"
		elif key.physical_keycode == KEY_B or key.keycode == KEY_B:
			mode = "megaregion"

		if not mode.is_empty():
			set_active_mode("" if _active_mode == mode else mode)
			get_viewport().set_input_as_handled()
			return

	if _active_mode.is_empty() or not _ready_data:
		return

	var mouse := event as InputEventMouseButton
	if mouse == null or not mouse.pressed or mouse.button_index != MOUSE_BUTTON_LEFT:
		return

	var hit: Variant = _f6_viewer.call("_hit_at_point", get_global_mouse_position())
	if hit is Dictionary:
		var hit_dict: Dictionary = hit
		if not hit_dict.is_empty():
			_select_parent_group(str(hit_dict.get("gameplay_parent_id", "")))
			get_viewport().set_input_as_handled()
			return
	_clear_selection()


func set_active_mode(mode: String) -> void:
	if mode != "" and mode != "region" and mode != "superregion" and mode != "macroregion" and mode != "megaregion":
		return

	if mode.is_empty():
		_active_mode = ""
		_geometry_root.visible = false
		_clear_selection()
		_show_status("X регионы • C суперрегионы • V макрорегионы • B мегарегионы")
		return

	if not _ensure_data():
		_show_status("Историческая иерархия v3: %s" % _last_error)
		return

	_hide_conflicting_layers()
	_active_mode = mode
	if _rendered_mode != mode:
		_render_mode(mode)
	_geometry_root.visible = true
	_clear_selection()
	_show_status(_mode_summary(mode))


func get_active_mode() -> String:
	return _active_mode


func _ensure_data() -> bool:
	if _ready_data:
		return true
	if not _last_error.is_empty():
		return false

	if not is_instance_valid(_f6_viewer):
		_f6_viewer = get_parent().get_node_or_null("Layer8NormalizedCellsViewer")
	if not is_instance_valid(_f6_viewer):
		_fail("Layer8NormalizedCellsViewer недоступен")
		return false

	_show_status("Иерархия v3: загрузка Layer 8...")
	_f6_viewer.call("_ensure_world_loaded")
	if _f6_viewer.has_method("is_world_loaded") and not bool(_f6_viewer.call("is_world_loaded")):
		_fail(str(_f6_viewer.get("_last_error")))
		return false

	var parents_value: Variant = _f6_viewer.get("_parents")
	var cells_value: Variant = _f6_viewer.get("_cells")
	if not parents_value is Array or not cells_value is Array:
		_fail("Layer 8 не отдал _parents/_cells")
		return false

	_parents = parents_value
	_cells = cells_value
	if _parents.size() != EXPECTED_PARENTS or _cells.size() != EXPECTED_CELLS:
		_fail("Layer8 counts: provinces=%d/%d cells=%d/%d" % [
			_parents.size(), EXPECTED_PARENTS, _cells.size(), EXPECTED_CELLS
		])
		return false

	_show_status("Иерархия v3: 2 886 провинций → 897/193/64/20...")
	_builder = BUILDER_SCRIPT.new()
	var super_defs_value: Variant = _catalog.get("super_defs")
	var super_defs: Array = super_defs_value if super_defs_value is Array else []
	var assignments_value: Variant = _builder.call("build", _parents, super_defs, EXPECTED_PARENTS)
	_assignments = assignments_value if assignments_value is Dictionary else {}

	if _assignments.size() != EXPECTED_PARENTS:
		var builder_error := str(_builder.get("last_error"))
		_fail(builder_error if not builder_error.is_empty() else "неполная иерархия v3")
		return false

	_ready_data = true
	_show_status("Готово: X 897 • C 193 • V 64 • B 20")
	return true


func _render_mode(mode: String) -> void:
	_geometry_root.visible = false
	for child in _geometry_root.get_children():
		child.queue_free()
	_chunk_nodes.clear()

	var buckets: Dictionary = {}
	var color_cache: Dictionary = {}
	var id_key := _mode_id_key(mode)

	for cell_value in _cells:
		if not cell_value is Dictionary:
			continue
		var cell: Dictionary = cell_value
		var assignment_value: Variant = _assignments.get(str(cell.get("gameplay_parent_id", "")), {})
		if not assignment_value is Dictionary:
			continue
		var assignment: Dictionary = assignment_value
		var group_id := str(assignment.get(id_key, ""))
		if group_id.is_empty():
			continue
		if not color_cache.has(group_id):
			color_cache[group_id] = _color_for_group(group_id, mode)
		var color_value: Variant = color_cache[group_id]
		var color: Color = color_value if color_value is Color else Color.WHITE

		for part_value in cell.get("viewer_parts", []):
			if not part_value is Array:
				continue
			var rings: Array = part_value
			if rings.is_empty() or not rings[0] is PackedVector2Array:
				continue
			var outer: PackedVector2Array = rings[0]
			var polygon := _without_duplicate_closing_point(outer)
			if polygon.size() >= 3:
				_add_polygon_to_bucket(buckets, polygon, color)

	_build_chunk_nodes(_geometry_root, buckets, _chunk_nodes)
	_rendered_mode = mode
	_geometry_root.visible = true


func _select_parent_group(parent_id: String) -> void:
	var assignment_value: Variant = _assignments.get(parent_id, {})
	if not assignment_value is Dictionary:
		return
	var assignment: Dictionary = assignment_value
	if assignment.is_empty():
		return

	var id_key := _mode_id_key(_active_mode)
	var group_id := str(assignment.get(id_key, ""))
	if group_id.is_empty():
		return

	_clear_selection()
	var buckets: Dictionary = {}
	var selection_color := Color(1.0, 0.88, 0.25, 0.72)

	for cell_value in _cells:
		if not cell_value is Dictionary:
			continue
		var cell: Dictionary = cell_value
		var candidate_value: Variant = _assignments.get(str(cell.get("gameplay_parent_id", "")), {})
		if not candidate_value is Dictionary:
			continue
		var candidate: Dictionary = candidate_value
		if str(candidate.get(id_key, "")) != group_id:
			continue
		for part_value in cell.get("viewer_parts", []):
			if not part_value is Array:
				continue
			var rings: Array = part_value
			if rings.is_empty() or not rings[0] is PackedVector2Array:
				continue
			var outer: PackedVector2Array = rings[0]
			var polygon := _without_duplicate_closing_point(outer)
			if polygon.size() >= 3:
				_add_polygon_to_bucket(buckets, polygon, selection_color)

	_build_chunk_nodes(_selection_root, buckets, _selection_nodes)
	_selection_root.visible = true
	_show_status("%s [%s] • регион: %s • суперрегион: %s • макрорегион: %s • мегарегион: %s" % [
		str(assignment.get(_mode_name_key(_active_mode), group_id)), group_id,
		str(assignment.get("region_name", "—")),
		str(assignment.get("superregion_name", "—")),
		str(assignment.get("macroregion_name", "—")),
		str(assignment.get("megaregion_name", "—")),
	])


func _add_polygon_to_bucket(buckets: Dictionary, polygon: PackedVector2Array, color: Color) -> void:
	var center := _polygon_bbox_center(polygon)
	var key := Vector2i(
		int(floor(center.x / CHUNK_WORLD_PX)),
		int(floor(center.y / CHUNK_WORLD_PX))
	)
	var bucket_value: Variant = buckets.get(key, {})
	var bucket: Dictionary = bucket_value if bucket_value is Dictionary else {}
	var polygons_value: Variant = bucket.get("polygons", [])
	var colors_value: Variant = bucket.get("colors", [])
	var polygons: Array = polygons_value if polygons_value is Array else []
	var colors: Array = colors_value if colors_value is Array else []
	polygons.append(polygon)
	colors.append(color)
	bucket["polygons"] = polygons
	bucket["colors"] = colors
	buckets[key] = bucket


func _build_chunk_nodes(root: Node2D, buckets: Dictionary, output: Array[Node2D]) -> void:
	var keys := buckets.keys()
	keys.sort_custom(func(a: Variant, b: Variant) -> bool:
		var av: Vector2i = a
		var bv: Vector2i = b
		return av.y < bv.y or (av.y == bv.y and av.x < bv.x)
	)
	for key_value in keys:
		var key: Vector2i = key_value
		var bucket_value: Variant = buckets.get(key, {})
		if not bucket_value is Dictionary:
			continue
		var bucket: Dictionary = bucket_value
		var node: Node2D = CHUNK_SCRIPT.new()
		node.name = "HierarchyV3Chunk_%d_%d" % [key.x, key.y]
		root.add_child(node)
		node.call("setup", bucket.get("polygons", []), bucket.get("colors", []))
		output.append(node)


func _clear_selection() -> void:
	_selection_root.visible = false
	for child in _selection_root.get_children():
		child.queue_free()
	_selection_nodes.clear()


func _hide_conflicting_layers() -> void:
	if is_instance_valid(_f6_viewer) and _f6_viewer.has_method("set_active"):
		_f6_viewer.call("set_active", false)
	var z := get_parent().get_node_or_null("WorldLandNormalizedController")
	if is_instance_valid(z) and z is CanvasItem:
		z.visible = false
	var names := [
		"WorldRegionsDraftViewer",
		"WorldRegionManualEditor",
		"WorldAdmin1SafeViewer",
		"SloveniaAdmin1ComparisonViewer",
		"Layer8SmallProvinceViewer",
		"Layer8MergeResultViewer",
		"BritainNorthAtlanticViewer",
		"IndiaCellTestViewer",
		"IndiaGameProvinceTestViewer",
	]
	for node_name in names:
		var node := get_parent().get_node_or_null(NodePath(str(node_name)))
		if is_instance_valid(node) and node is CanvasItem:
			node.visible = false


func _mode_id_key(mode: String) -> String:
	match mode:
		"region":
			return "region_id"
		"superregion":
			return "superregion_id"
		"macroregion":
			return "macroregion_id"
		"megaregion":
			return "megaregion_id"
	return ""


func _mode_name_key(mode: String) -> String:
	match mode:
		"region":
			return "region_name"
		"superregion":
			return "superregion_name"
		"macroregion":
			return "macroregion_name"
		"megaregion":
			return "megaregion_name"
	return ""


func _mode_summary(mode: String) -> String:
	match mode:
		"region":
			return "X — 897 исторических регионов • ЛКМ выбрать"
		"superregion":
			return "C — 193 суперрегиона • ЛКМ выбрать"
		"macroregion":
			return "V — 64 макрорегиона • ЛКМ выбрать"
		"megaregion":
			return "B — 20 мегарегионов • ЛКМ выбрать"
	return ""


func _color_for_group(group_id: String, mode: String) -> Color:
	var h := absi(group_id.hash())
	var hue := fmod(float(h % 10007) / 10007.0 + _mode_hue_offset(mode), 1.0)
	var saturation := 0.50
	var value := 0.82
	var alpha := 0.82
	if mode == "superregion":
		saturation = 0.56
	elif mode == "macroregion":
		saturation = 0.60
	elif mode == "megaregion":
		saturation = 0.64
	return Color.from_hsv(hue, saturation, value, alpha)


func _mode_hue_offset(mode: String) -> float:
	match mode:
		"region":
			return 0.00
		"superregion":
			return 0.11
		"macroregion":
			return 0.23
		"megaregion":
			return 0.37
	return 0.0


func _without_duplicate_closing_point(ring: PackedVector2Array) -> PackedVector2Array:
	var result := ring.duplicate()
	if result.size() >= 2 and result[0].is_equal_approx(result[result.size() - 1]):
		result.resize(result.size() - 1)
	return result


func _polygon_bbox_center(polygon: PackedVector2Array) -> Vector2:
	var min_x := polygon[0].x
	var min_y := polygon[0].y
	var max_x := polygon[0].x
	var max_y := polygon[0].y
	for i in range(1, polygon.size()):
		var p := polygon[i]
		min_x = minf(min_x, p.x)
		min_y = minf(min_y, p.y)
		max_x = maxf(max_x, p.x)
		max_y = maxf(max_y, p.y)
	return Vector2((min_x + max_x) * 0.5, (min_y + max_y) * 0.5)


func _show_status(message: String) -> void:
	if is_instance_valid(_viewer) and _viewer.has_method("_show_top_info"):
		_viewer.call("_show_top_info", message)
	else:
		print(message)


func _fail(message: String) -> void:
	_last_error = message if not message.is_empty() else "неизвестная ошибка"
	push_error("HistoricalHierarchyWorldViewerV3: %s" % _last_error)
