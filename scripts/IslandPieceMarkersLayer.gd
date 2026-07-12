class_name IslandPieceMarkersLayer
extends Node2D
## Все маркеры отдельных кусков многочастных провинций (см.
## build_island_piece_markers.py -> assets/island_piece_markers.json),
## созданные один раз при setup() — тот же приём, что ProvinceCityMarkersLayer.gd.

var _camera: Camera2D


func setup(data_path: String, camera: Camera2D) -> void:
	_camera = camera
	if not FileAccess.file_exists(data_path):
		push_warning("IslandPieceMarkersLayer: no file %s" % data_path)
		return

	var parsed = JSON.parse_string(FileAccess.get_file_as_string(data_path))
	if typeof(parsed) != TYPE_DICTIONARY:
		push_warning("IslandPieceMarkersLayer: failed to parse %s" % data_path)
		return

	for m in parsed.get("markers", []):
		var pos_raw: Array = m.get("pos", [])
		if pos_raw.size() < 2:
			continue
		var node := IslandPieceMarkerNode.new()
		node.position = Vector2(float(pos_raw[0]), float(pos_raw[1]))
		node.z_index = 100  # поверх всех тайловых слоёв, см. SeaLabelsLayer/ProvinceCityMarkersLayer
		add_child(node)


func _process(_delta: float) -> void:
	if not is_instance_valid(_camera):
		return
	var s := Vector2.ONE / maxf(0.0001, _camera.zoom.x)
	for child in get_children():
		child.scale = s
