extends "res://scripts/HistoricalHierarchyWorldViewerV3.gd"
## Compatibility/input router for the v3 historical hierarchy.
##
## X — regions
## C — superregions
## V — macroregions
## B — megaregions
##
## TileMapViewer historically used C/V/B for old debug/ocean layers.  Those
## bindings still exist in the root script, so relying only on _input() makes
## the result depend on input-delivery order.  Poll the physical keys once per
## frame and forcibly disable those legacy layers: X/C/V/B now belong to the
## historical hierarchy regardless of which sibling receives the key event
## first.

var _x_was_down := false
var _c_was_down := false
var _v_was_down := false
var _b_was_down := false


func _ready() -> void:
	super._ready()
	set_process(true)


func _input(event: InputEvent) -> void:
	var key := event as InputEventKey
	if key != null and key.pressed and not key.echo:
		var code := key.physical_keycode if key.physical_keycode != 0 else key.keycode

		# Hierarchy hotkeys are handled by _process() below.  Consume the event
		# here so old sibling/debug handlers do not normally toggle themselves.
		if code == KEY_X or code == KEY_C or code == KEY_V or code == KEY_B:
			get_viewport().set_input_as_handled()
			return

		# Z and F6 own their own map modes.  Closing the hierarchy here keeps
		# modes mutually exclusive, but the original Z/F6 handler must still
		# receive the same event.
		if code == KEY_Z or code == KEY_F6:
			if not get_active_mode().is_empty():
				set_active_mode("")
			return

	# Mouse selection and every unrelated input path remain implemented by v3.
	super._input(event)


func _process(_delta: float) -> void:
	_x_was_down = _poll_mode_key(KEY_X, "region", _x_was_down)
	_c_was_down = _poll_mode_key(KEY_C, "superregion", _c_was_down)
	_v_was_down = _poll_mode_key(KEY_V, "macroregion", _v_was_down)
	_b_was_down = _poll_mode_key(KEY_B, "megaregion", _b_was_down)


func _poll_mode_key(keycode: Key, mode: String, was_down: bool) -> bool:
	var down := Input.is_physical_key_pressed(keycode)
	if down and not was_down:
		# Do this both before and after toggling.  If TileMapViewer already saw
		# the key this frame its legacy layer is cleared; if it sees it later,
		# the next process frame clears it again while the key is still held.
		_hide_legacy_xcvb_layers()
		set_active_mode("" if get_active_mode() == mode else mode)
		_hide_legacy_xcvb_layers()
	return down


func _hide_legacy_xcvb_layers() -> void:
	var root := get_parent()
	if not is_instance_valid(root):
		return

	var layers_value: Variant = root.get("_layers")
	if not layers_value is Array:
		return
	var layers: Array = layers_value

	# These are the old meanings of C, V and B in TileMapViewer.gd.
	var index_properties := [
		"_cells_test_layer_idx",
		"_ocean_v_layer_idx",
		"_ocean_flat_layer_idx",
	]
	for property_name_value in index_properties:
		var property_name := str(property_name_value)
		var idx_value: Variant = root.get(property_name)
		if idx_value == null:
			continue
		var idx := int(idx_value)
		if idx < 0 or idx >= layers.size():
			continue
		var entry_value: Variant = layers[idx]
		if not entry_value is Dictionary:
			continue
		var entry: Dictionary = entry_value
		entry["visible"] = false
		layers[idx] = entry

	root.set("_layers", layers)
