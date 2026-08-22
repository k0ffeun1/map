extends "res://scripts/HistoricalHierarchyWorldViewerV3.gd"
## Compatibility entry point kept for Main.tscn.
## HistoricalHierarchyHotkeyBridge.gd now owns the interactive checkbox panel.
## X/C/V/B are no longer used here for switching hierarchy modes.


func _ready() -> void:
	super._ready()

	# Keep input enabled for LMB selection on the active hierarchy layer.
	set_process_input(true)

	# v3 catalog validation is intentionally strict.  Older intermediate data
	# may still contain a naming-only validation warning even though all actual
	# objects have already been loaded.  Recover only when the complete expected
	# object counts are present.  Real parse/count failures remain fatal.
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
	# Hierarchy level switching moved to the UI checkboxes.  Ignore X/C/V/B in
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
