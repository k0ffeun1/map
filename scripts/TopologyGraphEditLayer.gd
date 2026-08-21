class_name TopologyGraphEditLayer
extends Node2D

var edit_active := false:
	set(value):
		edit_active = value
		if not edit_active:
			end_point_drag()
		queue_redraw()

var line_color := Color(1.0, 0.9, 0.18, 0.95)
var node_color := Color(1.0, 0.38, 0.14, 1.0)
var point_color := Color(0.25, 0.9, 1.0, 0.95)
var drag_color := Color(1.0, 1.0, 1.0, 1.0)
var line_width_px := 2.0
var handle_radius_px := 4.0
var hit_radius_screen_px := 10.0

var _camera: Camera2D
var _data_path := ""
var _graph: Dictionary = {}
var _drag_kind := ""
var _drag_edge_idx := -1
var _drag_point_idx := -1
var _drag_node_id := ""


func setup(data_path: String, camera: Camera2D) -> void:
	_data_path = data_path
	_camera = camera
	load_from_file()


func load_from_file() -> bool:
	if _data_path.is_empty() or not FileAccess.file_exists(_data_path):
		_graph = {}
		queue_redraw()
		return false
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(_data_path))
	if typeof(parsed) != TYPE_DICTIONARY:
		_graph = {}
		queue_redraw()
		return false
	_graph = parsed
	queue_redraw()
	return true


func save_to_file() -> bool:
	if _data_path.is_empty() or _graph.is_empty():
		return false
	var file := FileAccess.open(ProjectSettings.globalize_path(_data_path), FileAccess.WRITE)
	if not file:
		push_warning("TopologyGraphEditLayer: failed to save %s" % _data_path)
		return false
	file.store_string(JSON.stringify(_graph, "\t", false, true) + "\n")
	file.close()
	return true


func get_node_count() -> int:
	return _graph.get("nodes", []).size()


func get_edge_count() -> int:
	return _graph.get("edges", []).size()


func get_control_point_count() -> int:
	var count := 0
	for edge in _graph.get("edges", []):
		count += edge.get("points", []).size()
	return count


## Настройки генератора хранятся в том же графе, что и узлы/рёбра. Так
## ползунки слоя T меняют будущую пересборку, а не временный стиль рендера.
func get_number_setting(key: String, fallback: float) -> float:
	return float(_graph.get(key, fallback))


func set_number_setting(key: String, value: float) -> void:
	if _graph.is_empty():
		return
	_graph[key] = value


func try_begin_point_drag(world_pos: Vector2) -> bool:
	var hit := _find_nearest_point(world_pos)
	if hit.is_empty():
		return false
	_drag_kind = hit.get("kind", "")
	_drag_edge_idx = int(hit.get("edge", -1))
	_drag_point_idx = int(hit.get("point", -1))
	_drag_node_id = str(hit.get("node", ""))
	queue_redraw()
	return true


func try_insert_point_near_segment(world_pos: Vector2) -> bool:
	var hit := _find_nearest_segment(world_pos)
	if hit.is_empty():
		return false
	var edges: Array = _graph.get("edges", [])
	var edge_idx := int(hit["edge"])
	if edge_idx < 0 or edge_idx >= edges.size():
		return false
	var edge: Dictionary = edges[edge_idx]
	var points: Array = edge.get("points", [])
	points.insert(int(hit["insert_at"]), [_round(world_pos.x), _round(world_pos.y)])
	edge["points"] = points
	edges[edge_idx] = edge
	_graph["edges"] = edges
	queue_redraw()
	return true


func try_delete_control_point_near(world_pos: Vector2) -> bool:
	var hit := _find_nearest_point(world_pos)
	if hit.is_empty() or hit.get("kind", "") != "edge_point":
		return false
	var edges: Array = _graph.get("edges", [])
	var edge_idx := int(hit["edge"])
	var point_idx := int(hit["point"])
	if edge_idx < 0 or edge_idx >= edges.size():
		return false
	var edge: Dictionary = edges[edge_idx]
	var points: Array = edge.get("points", [])
	if point_idx < 0 or point_idx >= points.size():
		return false
	points.remove_at(point_idx)
	edge["points"] = points
	edges[edge_idx] = edge
	_graph["edges"] = edges
	end_point_drag()
	queue_redraw()
	return true


func is_dragging_point() -> bool:
	return not _drag_kind.is_empty()


func update_point_drag(world_pos: Vector2) -> void:
	if _drag_kind == "node":
		_set_node_point(_drag_node_id, world_pos)
	elif _drag_kind == "edge_point":
		_set_edge_point(_drag_edge_idx, _drag_point_idx, world_pos)
	queue_redraw()


func end_point_drag() -> void:
	_drag_kind = ""
	_drag_edge_idx = -1
	_drag_point_idx = -1
	_drag_node_id = ""
	queue_redraw()


func _hit_radius_world() -> float:
	if is_instance_valid(_camera):
		return hit_radius_screen_px / maxf(0.0001, _camera.zoom.x)
	return hit_radius_screen_px


func _handle_radius_world() -> float:
	if is_instance_valid(_camera):
		return handle_radius_px / maxf(0.0001, _camera.zoom.x)
	return handle_radius_px


func _line_width_world() -> float:
	if is_instance_valid(_camera):
		return line_width_px / maxf(0.0001, _camera.zoom.x)
	return line_width_px


func _round(value: float) -> float:
	return snappedf(value, 0.01)


func _point_from_array(raw: Variant) -> Vector2:
	if typeof(raw) == TYPE_ARRAY and raw.size() >= 2:
		return Vector2(float(raw[0]), float(raw[1]))
	return Vector2.ZERO


func _node_points_by_id() -> Dictionary:
	var out := {}
	for node in _graph.get("nodes", []):
		if typeof(node) != TYPE_DICTIONARY:
			continue
		out[str(node.get("id", ""))] = _point_from_array(node.get("point", []))
	return out


func _edge_polyline(edge: Dictionary, nodes: Dictionary) -> PackedVector2Array:
	var pts := PackedVector2Array()
	var from_id := str(edge.get("from", ""))
	var to_id := str(edge.get("to", ""))
	if nodes.has(from_id):
		pts.append(nodes[from_id])
	for raw in edge.get("points", []):
		pts.append(_point_from_array(raw))
	if nodes.has(to_id):
		pts.append(nodes[to_id])
	return pts


func _find_nearest_point(world_pos: Vector2) -> Dictionary:
	var max_dist := _hit_radius_world()
	var best := {}
	var best_dist := max_dist
	for node in _graph.get("nodes", []):
		if typeof(node) != TYPE_DICTIONARY:
			continue
		var p := _point_from_array(node.get("point", []))
		var d := p.distance_to(world_pos)
		if d <= best_dist:
			best_dist = d
			best = {"kind": "node", "node": str(node.get("id", ""))}
	var edges: Array = _graph.get("edges", [])
	for edge_idx in range(edges.size()):
		var edge: Dictionary = edges[edge_idx]
		var points: Array = edge.get("points", [])
		for point_idx in range(points.size()):
			var p := _point_from_array(points[point_idx])
			var d := p.distance_to(world_pos)
			if d <= best_dist:
				best_dist = d
				best = {"kind": "edge_point", "edge": edge_idx, "point": point_idx}
	return best


func _find_nearest_segment(world_pos: Vector2) -> Dictionary:
	var nodes := _node_points_by_id()
	var max_dist := _hit_radius_world()
	var best := {}
	var best_dist := max_dist
	var edges: Array = _graph.get("edges", [])
	for edge_idx in range(edges.size()):
		var edge: Dictionary = edges[edge_idx]
		var pts := _edge_polyline(edge, nodes)
		for seg_idx in range(pts.size() - 1):
			var d := _distance_to_segment(world_pos, pts[seg_idx], pts[seg_idx + 1])
			if d <= best_dist:
				best_dist = d
				best = {"edge": edge_idx, "insert_at": seg_idx}
	return best


func _distance_to_segment(p: Vector2, a: Vector2, b: Vector2) -> float:
	var ab := b - a
	var denom := ab.length_squared()
	if denom <= 0.000001:
		return p.distance_to(a)
	var t := clampf((p - a).dot(ab) / denom, 0.0, 1.0)
	return p.distance_to(a + ab * t)


func _set_node_point(node_id: String, world_pos: Vector2) -> void:
	var nodes: Array = _graph.get("nodes", [])
	for idx in range(nodes.size()):
		var node: Dictionary = nodes[idx]
		if str(node.get("id", "")) != node_id:
			continue
		node["point"] = [_round(world_pos.x), _round(world_pos.y)]
		nodes[idx] = node
		_graph["nodes"] = nodes
		return


func _set_edge_point(edge_idx: int, point_idx: int, world_pos: Vector2) -> void:
	var edges: Array = _graph.get("edges", [])
	if edge_idx < 0 or edge_idx >= edges.size():
		return
	var edge: Dictionary = edges[edge_idx]
	var points: Array = edge.get("points", [])
	if point_idx < 0 or point_idx >= points.size():
		return
	points[point_idx] = [_round(world_pos.x), _round(world_pos.y)]
	edge["points"] = points
	edges[edge_idx] = edge
	_graph["edges"] = edges


func _process(_delta: float) -> void:
	if visible:
		queue_redraw()


func _draw() -> void:
	if _graph.is_empty():
		return
	var nodes := _node_points_by_id()
	var width := _line_width_world()
	for edge in _graph.get("edges", []):
		if typeof(edge) != TYPE_DICTIONARY:
			continue
		var pts := _edge_polyline(edge, nodes)
		if pts.size() >= 2:
			draw_polyline(pts, line_color, width, true)
	if not edit_active:
		return
	var r := _handle_radius_world()
	for node in _graph.get("nodes", []):
		if typeof(node) != TYPE_DICTIONARY:
			continue
		var node_id := str(node.get("id", ""))
		var p := _point_from_array(node.get("point", []))
		var color := drag_color if _drag_kind == "node" and _drag_node_id == node_id else node_color
		draw_circle(p, r * 1.35, color)
	var edges: Array = _graph.get("edges", [])
	for edge_idx in range(edges.size()):
		var edge: Dictionary = edges[edge_idx]
		var points: Array = edge.get("points", [])
		for point_idx in range(points.size()):
			var p := _point_from_array(points[point_idx])
			var dragging := _drag_kind == "edge_point" and _drag_edge_idx == edge_idx and _drag_point_idx == point_idx
			draw_circle(p, r if not dragging else r * 1.45, drag_color if dragging else point_color)
