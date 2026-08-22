extends Node
## Interactive UI controller for the v3 historical geography hierarchy.
##
## The hierarchy is controlled by four checkboxes in the main UI:
##   Regions / Superregions / Macroregions / Megaregions.
## Only one hierarchy level is shown at a time because all four modes occupy
## the same world geometry. Unchecking the active box disables the hierarchy.

const MODES := [
	{"id": "region", "label": "Регионы", "count": 897},
	{"id": "superregion", "label": "Суперрегионы", "count": 193},
	{"id": "macroregion", "label": "Макрорегионы", "count": 64},
	{"id": "megaregion", "label": "Мегарегионы", "count": 20},
]

var _viewer: Node
var _root: Node
var _ui_layer: CanvasLayer
var _status: Label
var _panel: PanelContainer
var _panel_status: Label
var _selection_info: Label
var _checkboxes: Dictionary = {}
var _syncing_ui := false
var _last_seen_mode := "__unbound__"


func _ready() -> void:
	call_deferred("_bind_and_build")
	set_process(true)


func _bind_and_build() -> void:
	_root = get_parent()
	if not is_instance_valid(_root):
		return

	_viewer = _root.get_node_or_null("HistoricalHierarchyWorldViewer")
	_ui_layer = _root.get_node_or_null("UI") as CanvasLayer
	_status = _root.get_node_or_null("UI/StatusLabel") as Label

	if not is_instance_valid(_viewer) or not _viewer.has_method("set_active_mode"):
		_report_error("узел HistoricalHierarchyWorldViewer не запущен")
		return
	if not is_instance_valid(_ui_layer):
		_report_error("не найден CanvasLayer UI")
		return

	_build_panel()
	_sync_from_viewer()
	_refresh_health()
	show_selection_info({})
	_last_seen_mode = str(_viewer.call("get_active_mode")) if _viewer.has_method("get_active_mode") else ""


func _process(_delta: float) -> void:
	if not is_instance_valid(_viewer):
		return
	var current := ""
	if _viewer.has_method("get_active_mode"):
		current = str(_viewer.call("get_active_mode"))

	# Z/F6 or another map mode may close the hierarchy outside this controller.
	# Keep all four checkboxes and the panel status synchronized with the real
	# viewer state instead of leaving a stale checkmark on screen.
	if current != _last_seen_mode:
		_last_seen_mode = current
		_sync_from_viewer()
		_refresh_health()
		if current.is_empty():
			show_selection_info({})

	# Old TileMapViewer C/V/B bindings still exist for legacy debug layers. If
	# the hierarchy is visible, keep those obsolete layers off even if a legacy
	# hotkey is pressed accidentally.
	if not current.is_empty():
		_hide_legacy_layers()


func _build_panel() -> void:
	if is_instance_valid(_panel):
		return

	_panel = PanelContainer.new()
	_panel.name = "HistoricalHierarchyPanel"
	_panel.set_anchors_preset(Control.PRESET_TOP_RIGHT)
	_panel.offset_left = -390.0
	_panel.offset_top = 24.0
	_panel.offset_right = -24.0
	_panel.offset_bottom = 500.0
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
	title.text = "Историческая география"
	title.add_theme_font_size_override("font_size", 20)
	box.add_child(title)

	var hint := Label.new()
	hint.text = "Выберите уровень карты"
	hint.add_theme_color_override("font_color", Color(0.72, 0.72, 0.72, 1.0))
	box.add_child(hint)

	for mode_value in MODES:
		var mode: Dictionary = mode_value
		var mode_id := str(mode.get("id", ""))
		var checkbox := CheckBox.new()
		checkbox.text = "%s  (%d)" % [str(mode.get("label", mode_id)), int(mode.get("count", 0))]
		checkbox.tooltip_text = "Включить слой: %s" % str(mode.get("label", mode_id))
		checkbox.toggled.connect(_on_mode_toggled.bind(mode_id, checkbox))
		box.add_child(checkbox)
		_checkboxes[mode_id] = checkbox

	var separator := HSeparator.new()
	box.add_child(separator)

	_panel_status = Label.new()
	_panel_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_panel_status.text = "Проверка слоя..."
	_panel_status.add_theme_font_size_override("font_size", 12)
	_panel_status.add_theme_color_override("font_color", Color(0.82, 0.82, 0.82, 1.0))
	box.add_child(_panel_status)

	var info_separator := HSeparator.new()
	box.add_child(info_separator)

	_selection_info = Label.new()
	_selection_info.name = "SelectionInfo"
	_selection_info.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_selection_info.add_theme_font_size_override("font_size", 14)
	_selection_info.add_theme_color_override("font_color", Color(0.94, 0.94, 0.94, 1.0))
	_selection_info.text = "Включите слой и кликните по объекту."
	box.add_child(_selection_info)


func _on_mode_toggled(pressed: bool, mode: String, source: CheckBox) -> void:
	if _syncing_ui:
		return
	if not is_instance_valid(_viewer):
		_report_error("viewer иерархии недоступен")
		return

	_syncing_ui = true

	if pressed:
		# The four hierarchy levels are alternative views. Keep the requested
		# checkbox checked and clear the other three without recursively firing.
		for mode_value in _checkboxes.keys():
			var other_mode := str(mode_value)
			if other_mode == mode:
				continue
			var other_value: Variant = _checkboxes.get(other_mode)
			if other_value is CheckBox:
				(other_value as CheckBox).button_pressed = false

		_hide_legacy_layers()
		_viewer.call("set_active_mode", mode)
		_hide_legacy_layers()
	else:
		var current := ""
		if _viewer.has_method("get_active_mode"):
			current = str(_viewer.call("get_active_mode"))
		if current == mode:
			_viewer.call("set_active_mode", "")

	_syncing_ui = false

	var error_text := _viewer_error()
	if not error_text.is_empty():
		_syncing_ui = true
		source.button_pressed = false
		_syncing_ui = false
		_report_error(error_text)
		return

	show_selection_info({})
	_sync_from_viewer()
	_refresh_health()
	_last_seen_mode = str(_viewer.call("get_active_mode")) if _viewer.has_method("get_active_mode") else ""


func _sync_from_viewer() -> void:
	if not is_instance_valid(_viewer):
		return
	var current := ""
	if _viewer.has_method("get_active_mode"):
		current = str(_viewer.call("get_active_mode"))

	_syncing_ui = true
	for mode_value in _checkboxes.keys():
		var mode := str(mode_value)
		var checkbox_value: Variant = _checkboxes.get(mode)
		if checkbox_value is CheckBox:
			(checkbox_value as CheckBox).button_pressed = mode == current
	_syncing_ui = false


func _refresh_health() -> void:
	if not is_instance_valid(_panel_status) or not is_instance_valid(_viewer):
		return

	var error_text := _viewer_error()
	if not error_text.is_empty():
		_panel_status.text = "Ошибка: %s" % error_text
		_panel_status.add_theme_color_override("font_color", Color(1.0, 0.45, 0.35, 1.0))
		return

	var active := ""
	if _viewer.has_method("get_active_mode"):
		active = str(_viewer.call("get_active_mode"))
	if active.is_empty():
		_panel_status.text = "Слой выключен"
	else:
		_panel_status.text = "Активен: %s" % _mode_label(active)
	_panel_status.add_theme_color_override("font_color", Color(0.82, 0.82, 0.82, 1.0))


func show_selection_info(info: Dictionary) -> void:
	if not is_instance_valid(_selection_info):
		return
	if info.is_empty():
		var active := ""
		if is_instance_valid(_viewer) and _viewer.has_method("get_active_mode"):
			active = str(_viewer.call("get_active_mode"))
		_selection_info.text = "Кликните по объекту на карте." if not active.is_empty() else "Включите слой и кликните по объекту."
		return

	var mode := str(info.get("mode", ""))
	var name := str(info.get("name", "—"))
	var member_count := int(info.get("member_count", 0))
	var lines: Array[String] = []
	lines.append("Выбрано: %s" % name)
	lines.append("Тип: %s" % _mode_type_label(mode))

	match mode:
		"region":
			lines.append("Провинций: %d" % member_count)
			lines.append("Суперрегион: %s" % str(info.get("superregion_name", "—")))
			lines.append("Макрорегион: %s" % str(info.get("macroregion_name", "—")))
			lines.append("Мегарегион: %s" % str(info.get("megaregion_name", "—")))
		"superregion":
			lines.append("Регионов: %d" % member_count)
			lines.append("Макрорегион: %s" % str(info.get("macroregion_name", "—")))
			lines.append("Мегарегион: %s" % str(info.get("megaregion_name", "—")))
		"macroregion":
			lines.append("Суперрегионов: %d" % member_count)
			lines.append("Мегарегион: %s" % str(info.get("megaregion_name", "—")))
		"megaregion":
			lines.append("Макрорегионов: %d" % member_count)

	_selection_info.text = "\n".join(lines)


func _mode_label(mode: String) -> String:
	for mode_value in MODES:
		var definition: Dictionary = mode_value
		if str(definition.get("id", "")) == mode:
			return str(definition.get("label", mode))
	return mode


func _mode_type_label(mode: String) -> String:
	match mode:
		"region":
			return "регион"
		"superregion":
			return "суперрегион"
		"macroregion":
			return "макрорегион"
		"megaregion":
			return "мегарегион"
	return mode


func _viewer_error() -> String:
	if not is_instance_valid(_viewer):
		return "viewer недоступен"
	var error_value: Variant = _viewer.get("_last_error")
	return str(error_value) if error_value != null else ""


func _hide_legacy_layers() -> void:
	if not is_instance_valid(_root):
		return
	var layers_value: Variant = _root.get("_layers")
	if not layers_value is Array:
		return
	var layers: Array = layers_value
	var changed := false
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
		if bool(entry.get("visible", false)):
			entry["visible"] = false
			layers[idx] = entry
			changed = true
	if changed:
		_root.set("_layers", layers)


func _report_error(message: String) -> void:
	var text := "Иерархия: %s" % message
	push_error(text)
	if is_instance_valid(_panel_status):
		_panel_status.text = text
		_panel_status.add_theme_color_override("font_color", Color(1.0, 0.45, 0.35, 1.0))
	if is_instance_valid(_status):
		_status.text = text
	elif is_instance_valid(_root) and _root.has_method("_show_top_info"):
		_root.call("_show_top_info", text)
