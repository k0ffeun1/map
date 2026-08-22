extends Node
## Ленивый вход в Stage 6.
## J показывает/скрывает всю Иберию.
## H циклически показывает 7 stress-test провинций с автоперелётом камеры.

const STAGE6_SCRIPT_PATH := "res://scripts/SubdivisionStage6Overview.gd"
const STRESS_SCRIPT_PATH := "res://scripts/SubdivisionStage6StressViewer.gd"

var _stage6 = null
var _stress6 = null
var _root_viewer: Node


func _ready() -> void:
	_root_viewer = get_parent()
	set_process_input(true)


func _input(event: InputEvent) -> void:
	var key_event := event as InputEventKey
	if key_event == null or not key_event.pressed or key_event.echo:
		return
	var key: Key = key_event.physical_keycode

	# Возврат к старым этапам автоматически убирает оба Stage 6 overlay.
	if key == KEY_Q or key == KEY_K or key == KEY_U or key == KEY_Y:
		hide_stage6()
		hide_stress6()
		return

	if key == KEY_J:
		hide_stress6()
		_toggle_iberia()
		get_viewport().set_input_as_handled()
		return

	if key == KEY_H:
		hide_stage6()
		_advance_stress()
		get_viewport().set_input_as_handled()
		return


func _toggle_iberia() -> void:
	if not _ensure_stage6():
		return
	var error_text := ""
	if _stage6.has_method("get_last_error"):
		error_text = str(_stage6.call("get_last_error"))
	if not error_text.is_empty():
		_show_top_info("Stage 6 не открыт: %s" % error_text)
		return

	var next_active := not bool(_stage6.get("visible"))
	_stage6.call("set_active", next_active)
	if next_active:
		_show_top_info("Stage 6: вся Иберия — J скрыть; H stress-тесты; ЛКМ выбрать территорию")
	else:
		_show_top_info("Stage 6 Иберия скрыта")


func _advance_stress() -> void:
	if not _ensure_stress6():
		return
	var error_text := ""
	if _stress6.has_method("get_last_error"):
		error_text = str(_stress6.call("get_last_error"))
	if not error_text.is_empty():
		_show_top_info("Stage 6 stress не открыт: %s" % error_text)
		return
	if not bool(_stress6.call("advance")):
		_show_top_info("Stage 6 stress: не удалось переключить контрольную провинцию")


func _ensure_stage6() -> bool:
	if is_instance_valid(_stage6):
		return true
	var stage_script = load(STAGE6_SCRIPT_PATH)
	if stage_script == null or not stage_script.can_instantiate():
		_show_top_info("Stage 6: Godot не смог загрузить %s — см. Output/Debugger" % STAGE6_SCRIPT_PATH)
		push_error("SubdivisionStage6InputBridge: failed to load %s" % STAGE6_SCRIPT_PATH)
		return false
	_stage6 = stage_script.new()
	if _stage6 == null:
		_show_top_info("Stage 6: не удалось создать overview-узел")
		return false
	_root_viewer.add_child(_stage6)
	var error_text := ""
	if _stage6.has_method("get_last_error"):
		error_text = str(_stage6.call("get_last_error"))
	if not error_text.is_empty():
		_show_top_info("Stage 6 загружен с ошибкой: %s" % error_text)
		return false
	return true


func _ensure_stress6() -> bool:
	if is_instance_valid(_stress6):
		return true
	var stress_script = load(STRESS_SCRIPT_PATH)
	if stress_script == null or not stress_script.can_instantiate():
		_show_top_info("Stage 6 stress: Godot не смог загрузить %s — см. Output/Debugger" % STRESS_SCRIPT_PATH)
		push_error("SubdivisionStage6InputBridge: failed to load %s" % STRESS_SCRIPT_PATH)
		return false
	_stress6 = stress_script.new()
	if _stress6 == null:
		_show_top_info("Stage 6 stress: не удалось создать viewer-узел")
		return false
	_root_viewer.add_child(_stress6)
	var error_text := ""
	if _stress6.has_method("get_last_error"):
		error_text = str(_stress6.call("get_last_error"))
	if not error_text.is_empty():
		_show_top_info("Stage 6 stress загружен с ошибкой: %s" % error_text)
		return false
	return true


func hide_stage6() -> void:
	if is_instance_valid(_stage6) and bool(_stage6.get("visible")):
		_stage6.call("set_active", false)


func hide_stress6() -> void:
	if is_instance_valid(_stress6) and bool(_stress6.get("visible")):
		_stress6.call("set_active", false)


func _show_top_info(message: String) -> void:
	if is_instance_valid(_root_viewer) and _root_viewer.has_method("_show_top_info"):
		_root_viewer.call("_show_top_info", message)
	else:
		print(message)
