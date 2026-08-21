extends Node
## Ленивый вход в Stage 5. Y показывает/скрывает четыре финальных полигона.
## Ошибка финального JSON не должна мешать запуску основной карты.

const STAGE5_SCRIPT_PATH := "res://scripts/SubdivisionFinalPolygonsStage.gd"

var _stage5 = null
var _root_viewer: Node


func _ready() -> void:
	_root_viewer = get_parent()
	set_process_input(true)


func _input(event: InputEvent) -> void:
	var key_event := event as InputEventKey
	if key_event == null or not key_event.pressed or key_event.echo:
		return
	var key: Key = key_event.physical_keycode

	# Любой возврат к Q/K/U убирает финальный слой, чтобы этапы не накладывались.
	if key == KEY_Q or key == KEY_K or key == KEY_U:
		hide_stage5()
		return
	if key != KEY_Y:
		return

	if not _ensure_stage5():
		get_viewport().set_input_as_handled()
		return

	var error_text := ""
	if _stage5.has_method("get_last_error"):
		error_text = str(_stage5.call("get_last_error"))
	if not error_text.is_empty():
		_show_top_info("Этап 5 не открыт: %s" % error_text)
		get_viewport().set_input_as_handled()
		return

	var next_active := not bool(_stage5.get("visible"))
	_stage5.call("set_active", next_active)
	if next_active:
		_show_top_info("Этап 5: 4 настоящие игровые территории — Y скрыть; ЛКМ выбрать")
	else:
		_show_top_info("Этап 5 скрыт")
	get_viewport().set_input_as_handled()


func _ensure_stage5() -> bool:
	if is_instance_valid(_stage5):
		return true
	var stage_script = load(STAGE5_SCRIPT_PATH)
	if stage_script == null or not stage_script.can_instantiate():
		_show_top_info("Этап 5: Godot не смог загрузить %s — см. Output/Debugger" % STAGE5_SCRIPT_PATH)
		push_error("SubdivisionStage5InputBridge: failed to load %s" % STAGE5_SCRIPT_PATH)
		return false
	_stage5 = stage_script.new()
	if _stage5 == null:
		_show_top_info("Этап 5: не удалось создать preview-узел")
		return false
	_root_viewer.add_child(_stage5)
	var error_text := ""
	if _stage5.has_method("get_last_error"):
		error_text = str(_stage5.call("get_last_error"))
	if not error_text.is_empty():
		_show_top_info("Этап 5 загружен с ошибкой: %s" % error_text)
		return false
	return true


func hide_stage5() -> void:
	if is_instance_valid(_stage5) and bool(_stage5.get("visible")):
		_stage5.call("set_active", false)


func _show_top_info(message: String) -> void:
	if is_instance_valid(_root_viewer) and _root_viewer.has_method("_show_top_info"):
		_root_viewer.call("_show_top_info", message)
	else:
		print(message)
