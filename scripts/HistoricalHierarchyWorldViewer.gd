extends "res://scripts/HistoricalHierarchyWorldViewerV3.gd"
## Compatibility entry point kept for Main.tscn.
## HistoricalHierarchyHotkeyBridge.gd owns the interactive checkbox panel.
## This wrapper also provides a deliberately high-contrast stable palette and
## forwards selected-object information into that panel.

const GOLDEN_RATIO_CONJUGATE := 0.6180339887498949

var _palette_by_mode: Dictionary = {}


func _ready() -> void:
	super._ready()

	# Keep input enabled for LMB selection on the active hierarchy layer.
	set_process_input(true)

	# v3 catalog validation is intentionally strict. Older intermediate data
	# may still contain a naming-only validation warning even though all actual
	# objects have already been loaded. Recover only when the complete expected
	# object counts are present. Real parse/count failures remain fatal.
	if not _last_error.is_empty() and is_instance_valid(_catalog):
		var regions_value: Variant = _catalog.get("region_meta")
		var supers_value: Variant = _catalog.get("super_defs")
		var macros_value: Variant = _catalog.get("macro_meta")
		var megas_value: Variant = _catalog.get("mega_meta")
		var regions_ok := regions_value is Dictionary and (regions_value as Dictionary).size() == EXPECTED_REGIONS
		var supers_ok := supers_value is Array and (supers_value as Array).size() == EXPECTED_SUPERS
		var macros_ok := macros_value is Dictionary and (macros_value as Dictionary).size() == EXPECTED_MACROS
		var megas_ok := megas_value is Dictionary and (megas_value as Dictionary).size() == EXPECTED_MEGAS
		if regions_ok and supers_ok and macros_ok and megas_ok:
			push_warning("HistoricalHierarchyWorldViewer: recovered complete v3 catalog after validation warning: %s" % _last_error)
			_last_error = ""


func _input(event: InputEvent) -> void:
	# Hierarchy level switching lives in the UI checkboxes. Ignore X/C/V/B in
	# this viewer so the same key can never toggle the hierarchy behind the UI.
	var key := event as InputEventKey
	if key != null and key.pressed and not key.echo:
		var code := key.physical_keycode if key.physical_keycode != 0 else key.keycode
		if code == KEY_X or code == KEY_C or code == KEY_V or code == KEY_B:
			return
		if code == KEY_Z or code == KEY_F6:
			if not get_active_mode().is_empty():
				set_active_mode("")
			# Do not consume: Z/F6 controllers still own those events.
			return

	# Mouse selection and unrelated inherited input remain available.
	super._input(event)


# The old v3 color function hashes strings directly. Sequential IDs such as
# region:0001 / region:0002 then receive visually similar colors. Build a
# complete palette per hierarchy level instead. Consecutive stable IDs jump by
# the golden-ratio conjugate around the hue wheel, so neighbouring catalogue
# objects do not visually merge into one huge country-sized blob.
func _color_for_group(group_id: String, mode: String) -> Color:
	if not _palette_by_mode.has(mode):
		_palette_by_mode[mode] = _build_mode_palette(mode)
	var palette_value: Variant = _palette_by_mode.get(mode, {})
	if palette_value is Dictionary:
		var palette: Dictionary = palette_value
		var color_value: Variant = palette.get(group_id)
		if color_value is Color:
			return color_value
	return Color(0.85, 0.85, 0.85, 0.86)


func _build_mode_palette(mode: String) -> Dictionary:
	var id_key := _mode_id_key(mode)
	var seen: Dictionary = {}
	var ids: Array[String] = []

	for assignment_value in _assignments.values():
		if not assignment_value is Dictionary:
			continue
		var assignment: Dictionary = assignment_value
		var group_id := str(assignment.get(id_key, ""))
		if group_id.is_empty() or seen.has(group_id):
			continue
		seen[group_id] = true
		ids.append(group_id)

	ids.sort()
	var palette: Dictionary = {}
	var offset := _palette_mode_offset(mode)
	for i in range(ids.size()):
		var hue := fmod(offset + float(i) * GOLDEN_RATIO_CONJUGATE, 1.0)
		# Three saturation/value bands give additional separation when hundreds
		# of hues are present, while keeping the physical map visible below.
		var saturation := 0.58 + 0.09 * float(i % 3)
		var value_band := int(i / 3) % 3
		var value := 0.78 + 0.07 * float(value_band)
		palette[ids[i]] = Color.from_hsv(hue, saturation, value, 0.86)
	return palette


func _palette_mode_offset(mode: String) -> float:
	match mode:
		"region":
			return 0.03
		"superregion":
			return 0.17
		"macroregion":
			return 0.31
		"megaregion":
			return 0.47
	return 0.0


func _select_parent_group(parent_id: String) -> void:
	super._select_parent_group(parent_id)

	var assignment_value: Variant = _assignments.get(parent_id, {})
	if not assignment_value is Dictionary:
		return
	var assignment: Dictionary = assignment_value
	var id_key := _mode_id_key(_active_mode)
	var group_id := str(assignment.get(id_key, ""))
	if group_id.is_empty():
		return

	var info := {
		"mode": _active_mode,
		"id": group_id,
		"name": str(assignment.get(_mode_name_key(_active_mode), group_id)),
		"region_name": str(assignment.get("region_name", "—")),
		"superregion_name": str(assignment.get("superregion_name", "—")),
		"macroregion_name": str(assignment.get("macroregion_name", "—")),
		"megaregion_name": str(assignment.get("megaregion_name", "—")),
		"member_count": _selected_member_count(group_id, _active_mode),
	}
	_forward_selection_info(info)


func _clear_selection() -> void:
	super._clear_selection()
	_forward_selection_info({})


func _selected_member_count(group_id: String, mode: String) -> int:
	var id_key := _mode_id_key(mode)
	var child_key := "gameplay_parent_id"
	match mode:
		"superregion":
			child_key = "region_id"
		"macroregion":
			child_key = "superregion_id"
		"megaregion":
			child_key = "macroregion_id"

	var unique_members: Dictionary = {}
	for parent_id_value in _assignments.keys():
		var assignment_value: Variant = _assignments.get(parent_id_value, {})
		if not assignment_value is Dictionary:
			continue
		var assignment: Dictionary = assignment_value
		if str(assignment.get(id_key, "")) != group_id:
			continue
		if mode == "region":
			unique_members[str(parent_id_value)] = true
		else:
			var child_id := str(assignment.get(child_key, ""))
			if not child_id.is_empty():
				unique_members[child_id] = true
	return unique_members.size()


func _forward_selection_info(info: Dictionary) -> void:
	var bridge := get_parent().get_node_or_null("HistoricalHierarchyHotkeyBridge")
	if is_instance_valid(bridge) and bridge.has_method("show_selection_info"):
		bridge.call("show_selection_info", info)


func runtime_health() -> Dictionary:
	var result := {
		"ready_data": _ready_data,
		"active_mode": _active_mode,
		"last_error": _last_error,
		"catalog_regions": 0,
		"catalog_superregions": 0,
		"catalog_macroregions": 0,
		"catalog_megaregions": 0,
	}
	if is_instance_valid(_catalog):
		var regions_value: Variant = _catalog.get("region_meta")
		var supers_value: Variant = _catalog.get("super_defs")
		var macros_value: Variant = _catalog.get("macro_meta")
		var megas_value: Variant = _catalog.get("mega_meta")
		if regions_value is Dictionary:
			result["catalog_regions"] = (regions_value as Dictionary).size()
		if supers_value is Array:
			result["catalog_superregions"] = (supers_value as Array).size()
		if macros_value is Dictionary:
			result["catalog_macroregions"] = (macros_value as Dictionary).size()
		if megas_value is Dictionary:
			result["catalog_megaregions"] = (megas_value as Dictionary).size()
	return result
