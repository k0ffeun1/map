class_name ProvinceCityMarkersLayer
extends Node2D
## Главные города провинций (клавиша 4, вместе со слоем "Провинции (Иберия)")
## — кружок-маркер + подпись под ним на реальном месте города (см.
## scripts/tools/build_province_cities_iberia.py -> assets/province_cities_iberia.json).
## НЕ тайловый слой — та же причина и тот же приём, что у SeaLabelsLayer
## (городов мало, ~100 на регион, все узлы создаются один раз при setup()).
##
## Перетаскивание мышкой (прямая просьба пользователя 2026-07-13, см.
## сессию про ручную правку положения Севильи) — ЛКМ по маркеру двигает его,
## отпустить — остаётся на новом месте; кнопка "Сохранить города" в
## TileMapViewer.gd пишет ТЕКУЩИЕ позиции всех узлов обратно в
## data_path (тот же JSON, что грузили при setup) — правки переживают
## следующий запуск игры, но НЕ переживают повторный запуск
## build_province_cities_iberia.py (это офлайн-генератор, он перезапишет
## файл заново) — если позиция должна быть постоянной, её нужно отдельно
## перенести в CITY_POSITION_OVERRIDES того скрипта.

const WORLD_PX := 8192.0
const HIT_RADIUS_SCREEN_PX := 16.0  ## Радиус попадания мышкой в ЭКРАННЫХ px — чуть больше видимого круга (RADIUS=7 в ProvinceCityMarkerNode), чтобы проще попасть курсором.

var _camera: Camera2D
var _data_path: String = ""
var _dragging: ProvinceCityMarkerNode = null


func setup(data_path: String, camera: Camera2D) -> void:
	_camera = camera
	_data_path = data_path
	if not FileAccess.file_exists(data_path):
		push_warning("ProvinceCityMarkersLayer: no file %s" % data_path)
		return

	var parsed = JSON.parse_string(FileAccess.get_file_as_string(data_path))
	if typeof(parsed) != TYPE_DICTIONARY:
		push_warning("ProvinceCityMarkersLayer: failed to parse %s" % data_path)
		return

	for city in parsed.get("cities", []):
		var pos_raw: Array = city.get("pos", [])
		if pos_raw.size() < 2:
			continue
		var node := ProvinceCityMarkerNode.new()
		node.position = Vector2(float(pos_raw[0]), float(pos_raw[1]))
		node.z_index = 100  # поверх всех тайловых слоёв, см. SeaLabelsLayer
		add_child(node)
		node.province_name = str(city.get("province", ""))
		node.setup(str(city.get("name", "")))


## Хит-тест по всем маркерам в ЭКРАННЫХ px (не мировых — иначе на сильном
## отдалении промахнуться было бы легко, а вблизи наоборот пришлось бы
## целиться в одну точку) — тот же приём радиуса/зума, что в
## ProvinceCityMarkerNode._process (scale = 1/zoom). Возвращает true и
## начинает перетаскивание, если под курсором нашёлся маркер.
func try_begin_drag(world_pos: Vector2) -> bool:
	if not visible or not is_instance_valid(_camera) or _camera.zoom.x <= 0.0:
		return false
	var hit_r_world: float = HIT_RADIUS_SCREEN_PX / _camera.zoom.x
	var best: ProvinceCityMarkerNode = null
	var best_d := INF
	for child in get_children():
		if not (child is ProvinceCityMarkerNode):
			continue
		var d: float = child.position.distance_to(world_pos)
		if d <= hit_r_world and d < best_d:
			best = child
			best_d = d
	if best == null:
		return false
	_dragging = best
	return true


func update_drag(world_pos: Vector2) -> void:
	if is_instance_valid(_dragging):
		_dragging.position = world_pos


func end_drag() -> void:
	_dragging = null


func is_dragging() -> bool:
	return is_instance_valid(_dragging)


## Пишет ТЕКУЩИЕ позиции всех маркеров обратно в data_path (тот же формат,
## что у build_province_cities_iberia.py) — см. докстринг класса.
func save_to_file() -> int:
	if _data_path.is_empty():
		return 0
	var cities := []
	for child in get_children():
		if not (child is ProvinceCityMarkerNode):
			continue
		cities.append({
			"name": child.city_name,
			"province": child.province_name,
			"pos": [snappedf(child.position.x, 0.01), snappedf(child.position.y, 0.01)],
		})
	var f := FileAccess.open(ProjectSettings.globalize_path(_data_path), FileAccess.WRITE)
	if not f:
		push_warning("ProvinceCityMarkersLayer: не удалось сохранить %s" % _data_path)
		return 0
	f.store_string(JSON.stringify({"world_px": WORLD_PX, "cities": cities}))
	f.close()
	return cities.size()


func _process(_delta: float) -> void:
	if not is_instance_valid(_camera):
		return
	var s := Vector2.ONE / maxf(0.0001, _camera.zoom.x)
	for child in get_children():
		child.scale = s
