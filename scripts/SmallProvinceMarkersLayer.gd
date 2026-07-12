class_name SmallProvinceMarkersLayer
extends Node2D
## Все маркеры провинций < 300 км² (см. build_small_provinces_markers.py ->
## assets/small_provinces_markers.json), созданные один раз при setup() — тот
## же приём, что ProvinceCityMarkersLayer.gd (сотни узлов, не тысячи —
## нормально создать все сразу, без LOD/чанков, см. CLAUDE.md).

var _camera: Camera2D


func setup(data_path: String, camera: Camera2D) -> void:
	_camera = camera
	if not FileAccess.file_exists(data_path):
		push_warning("SmallProvinceMarkersLayer: no file %s" % data_path)
		return

	var parsed = JSON.parse_string(FileAccess.get_file_as_string(data_path))
	if typeof(parsed) != TYPE_DICTIONARY:
		push_warning("SmallProvinceMarkersLayer: failed to parse %s" % data_path)
		return

	for m in parsed.get("markers", []):
		var pos_raw: Array = m.get("pos", [])
		if pos_raw.size() < 2:
			continue
		var node := SmallProvinceMarkerNode.new()
		node.position = Vector2(float(pos_raw[0]), float(pos_raw[1]))
		node.z_index = 100  # поверх всех тайловых слоёв, см. SeaLabelsLayer/ProvinceCityMarkersLayer
		add_child(node)
		node.setup(float(m.get("area_km2", 0.0)))


func _process(_delta: float) -> void:
	if not is_instance_valid(_camera):
		return
	var s := Vector2.ONE / maxf(0.0001, _camera.zoom.x)
	for child in get_children():
		child.scale = s
