extends Node
## Надёжный вход в этап 4 деления Ла-Коруньи.
##
## Этап 4 намеренно загружается лениво: ошибка экспериментального cleanup-
## скрипта не должна мешать запуску всей карты. Этот мост ловит U в том же
## дереве Main, создаёт preview только по запросу и всегда сообщает ошибку
## пользователю вместо молчаливого отказа.
##
## Конкретный Stage 4 использует тот же 2-км gameplay coastline, что слой 4:
## assets/provinces_iberia_selection_2km.json. Поэтому внешний контур и
## береговые окончания внутренних границ совпадают со слоем 4 буквально.

const STAGE4_SCRIPT_PATH := "res://scripts/SubdivisionBoundaryCleanupStage2km.gd"

var _stage4 = null
var _root_viewer: Node


func _ready() -> void:
	_root_viewer = get_parent()
	set_process_input(true)


func _input(event: InputEvent) -> void:
	var key_event := event as InputEventKey
	if key_event == null or not key_event.pressed or key_event.echo:
		return

	var key: Key = key_event.physical_keycode
	if key == KEY_Q or key == KEY_K:
		if is_instance_valid(_stage4) and bool(_stage4.get("visible")):
			_stage4.call("set_active", false)
		return

	if key != KEY_U:
		return

	if not _ensure_stage4():
		get_viewport().set_input_as_handled()
		return

	var error_text := ""
	if _stage4.has_method("get_last_error"):
		error_text = str(_stage4.call("get_last_error"))
	if not error_text.is_empty():
		_show_top_info("Этап 4 не открыт: %s" % error_text)
		get_viewport().set_input_as_handled()
		return

	var next_active := not bool(_stage4.get("visible"))
	_stage4.call("set_active", next_active)
	if next_active:
		_show_top_info("Этап 4: политические границы + берег слоя 4 с отступом 2 км — U скрыть")
	else:
		_show_top_info("Этап 4 скрыт")
	get_viewport().set_input_as_handled()


func _ensure_stage4() -> bool:
	if is_instance_valid(_stage4):
		return true

	var stage_script = load(STAGE4_SCRIPT_PATH)
	if stage_script == null or not stage_script.can_instantiate():
		_show_top_info("Этап 4: Godot не смог загрузить %s — см. Output/Debugger" % STAGE4_SCRIPT_PATH)
		push_error("SubdivisionStage4InputBridge: failed to load %s" % STAGE4_SCRIPT_PATH)
		return false

	_stage4 = stage_script.new()
	if _stage4 == null:
		_show_top_info("Этап 4: не удалось создать preview-узел")
		return false

	_root_viewer.add_child(_stage4)
	# Управление клавишами централизовано здесь. Сам cleanup-узел больше не
	# должен повторно обработать тот же U и мгновенно переключить видимость назад.
	_stage4.set_process_input(false)

	var error_text := ""
	if _stage4.has_method("get_last_error"):
		error_text = str(_stage4.call("get_last_error"))
	if not error_text.is_empty():
		_show_top_info("Этап 4 загружен с ошибкой: %s" % error_text)
		return false
	return true


func _show_top_info(message: String) -> void:
	if is_instance_valid(_root_viewer) and _root_viewer.has_method("_show_top_info"):
		_root_viewer.call("_show_top_info", message)
	else:
		print(message)
