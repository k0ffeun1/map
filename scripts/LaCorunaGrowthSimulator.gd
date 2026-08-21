class_name LaCorunaGrowthSimulator
extends Node2D
## Живая растровая симуляция: четыре источника одновременно занимают
## доступные пиксели контура провинции. Геометрия берётся из готового
## Layer 4, поэтому эксперимент не меняет данные клеток и другие слои.

const OWNER_COLORS := [
	Color("ef476f"), Color("ffd166"), Color("06d6a0"), Color("118ab2"),
]
const EMPTY := -1

var pixel_size := 0.36
var ticks_per_second := 16.0
var running := false
var finished := false

var _bounds := Rect2()
var _width := 0
var _height := 0
var _mask: PackedByteArray = PackedByteArray()
var _owners: PackedInt32Array = PackedInt32Array()
var _source_polygons: Array = []
var _source_names: PackedStringArray = PackedStringArray()
var _seed_indices: PackedInt32Array = PackedInt32Array()
var _frontiers: Array = []
var _pixel_counts := PackedInt32Array([0, 0, 0, 0])
var _total_pixels := 0
var _accumulator := 0.0


func setup(data_path: String, province_id := "spain__la_coru_a") -> bool:
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(data_path))
	if typeof(parsed) != TYPE_DICTIONARY:
		push_warning("Growth simulator: invalid cell source " + data_path)
		return false
	var cells: Array = parsed.get("cells", [])
	for cell in cells:
		if cell.get("parent_province_id", "") != province_id:
			continue
		var rings: Array = cell.get("rings", [])
		if rings.is_empty() or rings[0].size() < 3:
			continue
		var polygon := PackedVector2Array()
		for point in rings[0]:
			polygon.append(Vector2(point[0], point[1]))
		_source_polygons.append(polygon)
		_source_names.append(str(cell.get("name", "Источник %d" % _source_polygons.size())))
	if _source_polygons.size() != 4:
		push_warning("Growth simulator needs four La Coruña source cells, got %d" % _source_polygons.size())
		return false
	_build_grid()
	reset()
	return true


func _build_grid() -> void:
	_bounds = Rect2(_source_polygons[0][0], Vector2.ZERO)
	for polygon in _source_polygons:
		for point in polygon:
			_bounds = _bounds.expand(point)
	_bounds = _bounds.grow(pixel_size)
	_width = ceili(_bounds.size.x / pixel_size)
	_height = ceili(_bounds.size.y / pixel_size)
	_mask.resize(_width * _height)
	_owners.resize(_width * _height)
	for y in range(_height):
		for x in range(_width):
			var index: int = _index(x, y)
			var point: Vector2 = _world_at(x, y)
			for polygon in _source_polygons:
				if Geometry2D.is_point_in_polygon(point, polygon):
					_mask[index] = 1
					_total_pixels += 1
					break


func reset() -> void:
	running = false
	finished = false
	_accumulator = 0.0
	_frontiers.clear()
	_pixel_counts = PackedInt32Array([0, 0, 0, 0])
	_seed_indices = PackedInt32Array()
	for index in range(_owners.size()):
		_owners[index] = EMPTY
	for owner in range(4):
		var seed: int = _find_seed_for_polygon(_source_polygons[owner])
		_seed_indices.append(seed)
		_frontiers.append([seed])
		_owners[seed] = owner
		_pixel_counts[owner] += 1
	queue_redraw()


func start() -> void:
	if finished:
		reset()
	running = true


func pause() -> void:
	running = false


func is_ready() -> bool:
	return _total_pixels > 0 and _seed_indices.size() == 4


func get_source_names() -> PackedStringArray:
	return _source_names


func get_pixel_counts() -> PackedInt32Array:
	return _pixel_counts


func get_total_pixels() -> int:
	return _total_pixels


func get_claimed_pixels() -> int:
	var claimed: int = 0
	for count in _pixel_counts:
		claimed += count
	return claimed


func get_progress() -> float:
	if _total_pixels == 0:
		return 0.0
	return float(get_claimed_pixels()) / float(_total_pixels)


func get_center() -> Vector2:
	return _bounds.get_center()


func _process(delta: float) -> void:
	if not running:
		return
	_accumulator += delta
	var tick_seconds: float = 1.0 / maxf(ticks_per_second, 1.0)
	var changed: bool = false
	while _accumulator >= tick_seconds and running:
		_accumulator -= tick_seconds
		changed = _advance_one_tick() or changed
	if changed:
		queue_redraw()


func _advance_one_tick() -> bool:
	var claims: Dictionary = {}
	for owner in range(4):
		var next_frontier: Array = []
		for cell_index in _frontiers[owner]:
			var x: int = int(cell_index) % _width
			var y: int = int(int(cell_index) / _width)
			for neighbor in _neighbors(x, y):
				if _mask[neighbor] == 0 or _owners[neighbor] != EMPTY:
					continue
				if not claims.has(neighbor) or owner < int(claims[neighbor]):
					claims[neighbor] = owner
		_frontiers[owner] = next_frontier
	if claims.is_empty():
		running = false
		finished = true
		return false
	for cell_index in claims:
		var owner: int = claims[cell_index]
		_owners[cell_index] = owner
		_frontiers[owner].append(cell_index)
		_pixel_counts[owner] += 1
	return true


func _neighbors(x: int, y: int) -> PackedInt32Array:
	var result := PackedInt32Array()
	if x > 0:
		result.append(_index(x - 1, y))
	if x + 1 < _width:
		result.append(_index(x + 1, y))
	if y > 0:
		result.append(_index(x, y - 1))
	if y + 1 < _height:
		result.append(_index(x, y + 1))
	return result


func _find_seed_for_polygon(polygon: PackedVector2Array) -> int:
	var target: Rect2 = Rect2(polygon[0], Vector2.ZERO)
	for point in polygon:
		target = target.expand(point)
	var best_index: int = -1
	var best_distance: float = INF
	for index in range(_mask.size()):
		if _mask[index] == 0:
			continue
		var x: int = index % _width
		var y: int = int(index / _width)
		var point: Vector2 = _world_at(x, y)
		if not Geometry2D.is_point_in_polygon(point, polygon):
			continue
		var distance: float = point.distance_squared_to(target.get_center())
		if distance < best_distance:
			best_distance = distance
			best_index = index
	return best_index


func _index(x: int, y: int) -> int:
	return y * _width + x


func _world_at(x: int, y: int) -> Vector2:
	return _bounds.position + Vector2((float(x) + 0.5) * pixel_size, (float(y) + 0.5) * pixel_size)


func _draw() -> void:
	for index in range(_owners.size()):
		var owner: int = _owners[index]
		if owner == EMPTY:
			continue
		var x: int = index % _width
		var y: int = int(index / _width)
		draw_rect(Rect2(_bounds.position + Vector2(x, y) * pixel_size,
			Vector2.ONE * (pixel_size + 0.025)), OWNER_COLORS[owner])
	for polygon in _source_polygons:
		draw_polyline(polygon, Color(0.04, 0.07, 0.12, 0.9), 0.22, true)
		draw_line(polygon[polygon.size() - 1], polygon[0], Color(0.04, 0.07, 0.12, 0.9), 0.22, true)
	for owner in range(_seed_indices.size()):
		var seed: int = _seed_indices[owner]
		if seed < 0:
			continue
		var x: int = seed % _width
		var y: int = int(seed / _width)
		var point: Vector2 = _world_at(x, y)
		draw_circle(point, 0.8, Color.WHITE)
		draw_circle(point, 0.46, OWNER_COLORS[owner])
