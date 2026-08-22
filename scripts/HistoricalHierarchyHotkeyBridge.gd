extends Node
## Reliable runtime router for the historical hierarchy hotkeys.
##
## X — regions
## C — superregions
## V — macroregions
## B — megaregions
##
## TileMapViewer historically owns C/V/B too.  This bridge does not depend on
## _input() delivery order: it polls key state every frame, calls the hierarchy
## viewer directly and clears the obsolete legacy layers after the root script
## has had a chance to toggle them.

const MODE_KEYS := {
	KEY_X: "region",
	KEY_C: "superregion",
	KEY_V: "macroregion",
	KEY_B: "megaregion",
}

var _viewer: Node
var _root: Node
var _status: Label
var _was_down: Dictionary = {}


func _ready() -> void:
	for key_value in MODE_KEYS.keys():
		_was_down[int(key_value)] = false
	call_deferred("_bind")
	set_process(true)


func _bind() -> void:
	_root = get_parent()
	if not is_instance_valid(_root):
		return
	_viewer = _root.get_node_or_null("HistoricalHierarchyWorldViewer")
	_status = _root.get_node_or_null("UI/StatusLabel") as Label
	if not is_instance_valid(_viewer) or not _viewer.has_method("set_active_mode"):
		_report_error("узел HistoricalHierarchyWorldViewer не запущен")


func _process(_delta: float) -> void:
	if not is_instance_valid(_viewer):
		_bind()

	for key_value in MODE_KEYS.keys():
		var keycode := int(key_value)
		var down := Input.is_key_pressed(keycode)
		var was_down := bool(_was_down.get(keycode, false))
		if down and not was_down:
			_trigger(str(MODE_KEYS[key_value]))
		_was_down[keycode] = down

	# Old TileMapViewer bindings may have toggled their C/V/B layer during the
	# same frame.  While a hierarchy mode is active, keep those legacy layers
	# forcibly off every frame.
	if is_instance_valid(_viewer) and _viewer.has_method("get_active_mode"):
		if not str(_viewer.call("get_active_mode")).is_empty():
			_hide_legacy_layers()


func _trigger(mode: String) -> void:
	if not is_instance_valid(_viewer):
		_bind()
	if not is_instance_valid(_viewer) or not _viewer.has_method("set_active_mode"):
		_report_error("viewer X/C/V/B недоступен")
		return

	_hide_legacy_layers()
	var current := ""
	if _viewer.has_method("get_active_mode"):
		current = str(_viewer.call("get_active_mode"))
	_viewer.call("set_active_mode", "" if current == mode else mode)
	_hide_legacy_layers()

	var error_value: Variant = _viewer.get("_last_error")
	var error_text := str(error_value) if error_value != null else ""
	if not error_text.is_empty():
		_report_error(error_text)
		return

	# Viewer itself writes the normal mode summary.  This fallback confirms
	# that the bridge has actually delivered the key even if another UI script
	# overwrites the status line immediately afterwards.
	if is_instance_valid(_status) and _viewer.has_method("get_active_mode"):
		var active := str(_viewer.call("get_active_mode"))
		if active.is_empty():
			_status.text = "X/C/V/B: слой выключен"


func _hide_legacy_layers() -> void:
	if not is_instance_valid(_root):
		return
	var layers_value: Variant = _root.get("_layers")
	if not layers_value is Array:
		return
	var layers: Array = layers_value
	for property_name in ["_cells_test_layer_idx", "_ocean_v_layer_idx", "_ocean_flat_layer_idx"]:
		var idx_value: Variant = _root.get(property_name)
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
	_root.set("_layers", layers)


func _report_error(message: String) -> void:
	var text := "X/C/V/B ERROR: %s" % message
	push_error(text)
	if is_instance_valid(_status):
		_status.text = text
	elif is_instance_valid(_root) and _root.has_method("_show_top_info"):
		_root.call("_show_top_info", text)
