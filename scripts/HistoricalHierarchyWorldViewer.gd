extends "res://scripts/HistoricalHierarchyWorldViewerV3.gd"
## Compatibility entry point kept for Main.tscn.
## X/C/V/B keyboard routing is handled by HistoricalHierarchyHotkeyBridge.gd.


func _ready() -> void:
	super._ready()

	# The dedicated bridge is now the single owner of X/C/V/B hotkeys.  Disable
	# the inherited key path so one physical press can never toggle the mode
	# twice because of scene-tree input order.
	set_process_input(false)

	# v3 catalog validation is intentionally strict.  Older intermediate data
	# may still contain a naming-only validation warning even though all actual
	# objects have already been loaded.  Do not let such a warning make the
	# entire visual layer appear dead: recover only when the complete expected
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
