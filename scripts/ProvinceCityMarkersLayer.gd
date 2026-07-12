class_name ProvinceCityMarkersLayer
extends Node2D
## Главные города провинций (клавиша 4, вместе со слоем "Провинции (Иберия)")
## — кружок-маркер + подпись под ним на реальном месте города (см.
## scripts/tools/build_province_cities_iberia.py -> assets/province_cities_iberia.json).
## НЕ тайловый слой — та же причина и тот же приём, что у SeaLabelsLayer
## (городов мало, ~100 на регион, все узлы создаются один раз при setup()).

var _camera: Camera2D


func setup(data_path: String, camera: Camera2D) -> void:
	_camera = camera
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
		node.setup(str(city.get("name", "")))


func _process(_delta: float) -> void:
	if not is_instance_valid(_camera):
		return
	var s := Vector2.ONE / maxf(0.0001, _camera.zoom.x)
	for child in get_children():
		child.scale = s
