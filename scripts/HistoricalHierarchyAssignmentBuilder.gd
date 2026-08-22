extends RefCounted
## Deterministic from-scratch assignment of canonical Layer-8 provinces to the
## historical hierarchy. Existing project region assignments are never read.

const WORLD_PX := 8192.0
const LLOYD_ITERATIONS := 7

var last_error := ""
var parent_center: Dictionary = {}


func build(parents: Array, super_defs: Array, expected_parents: int) -> Dictionary:
	last_error = ""
	parent_center.clear()

	for parent_value in parents:
		if not parent_value is Dictionary:
			continue
		var parent: Dictionary = parent_value
		var parent_id := str(parent.get("gameplay_parent_id", ""))
		var bbox_value: Variant = parent.get("viewer_bbox", [])
		if parent_id.is_empty() or not bbox_value is Array or bbox_value.size() < 4:
			continue
		var bbox: Array = bbox_value
		parent_center[parent_id] = Vector2(
			(float(bbox[0]) + float(bbox[2])) * 0.5,
			(float(bbox[1]) + float(bbox[3])) * 0.5
		)

	if parent_center.size() != expected_parents:
		last_error = "центры провинций Layer 8: %d/%d" % [parent_center.size(), expected_parents]
		return {}

	var assignments: Dictionary = {}
	var counts: Dictionary = {}
	var required: Dictionary = {}

	for super_value in super_defs:
		if not super_value is Dictionary:
			continue
		var super_def: Dictionary = super_value
		var super_id := str(super_def.get("id", ""))
		counts[super_id] = 0
		var regions_value: Variant = super_def.get("regions", [])
		required[super_id] = regions_value.size() if regions_value is Array else 0

	# First pass: nearest historical superregion seed in the exact WebMercator
	# world-pixel space used by Layer 8. No old region/country assignment is read.
	for parent_id_value in parent_center.keys():
		var parent_id := str(parent_id_value)
		var best := _nearest_superregion(parent_center[parent_id], super_defs)
		if best.is_empty():
			last_error = "не найден суперрегион для %s" % parent_id
			return {}
		_set_parent_super(assignments, parent_id, best)
		var super_id := str(best.get("id", ""))
		counts[super_id] = int(counts.get(super_id, 0)) + 1

	# Each named historical region must contain at least one Layer-8 province.
	# If a seed Voronoi cell is too small, borrow the nearest province from a
	# donor superregion that remains above its own minimum.
	for super_value in super_defs:
		if not super_value is Dictionary:
			continue
		var target: Dictionary = super_value
		var target_id := str(target.get("id", ""))
		var target_min := int(required.get(target_id, 0))

		while int(counts.get(target_id, 0)) < target_min:
			var best_parent := ""
			var best_distance := INF
			var target_seed: Vector2 = target.get("seed_world", Vector2.ZERO)

			for parent_id_value in parent_center.keys():
				var parent_id := str(parent_id_value)
				var current_value: Variant = assignments.get(parent_id, {})
				if not current_value is Dictionary:
					continue
				var current: Dictionary = current_value
				var donor_id := str(current.get("superregion_id", ""))
				if donor_id == target_id:
					continue
				if int(counts.get(donor_id, 0)) <= int(required.get(donor_id, 0)):
					continue
				var distance := world_distance_sq(parent_center[parent_id], target_seed)
				if distance < best_distance:
					best_distance = distance
					best_parent = parent_id

			if best_parent.is_empty():
				last_error = "не удалось дать минимум провинций суперрегиону %s" % str(target.get("name", target_id))
				return {}

			var donor_value: Variant = assignments.get(best_parent, {})
			var donor: Dictionary = donor_value if donor_value is Dictionary else {}
			var donor_id := str(donor.get("superregion_id", ""))
			counts[donor_id] = int(counts.get(donor_id, 0)) - 1
			_set_parent_super(assignments, best_parent, target)
			counts[target_id] = int(counts.get(target_id, 0)) + 1

	# Within each superregion, partition its Layer-8 province centroids into the
	# exact number of user-authored historical regions.
	for super_value in super_defs:
		if not super_value is Dictionary:
			continue
		var super_def: Dictionary = super_value
		var super_id := str(super_def.get("id", ""))
		var members: Array = []

		for parent_id_value in assignments.keys():
			var parent_id := str(parent_id_value)
			var assignment_value: Variant = assignments.get(parent_id, {})
			if assignment_value is Dictionary:
				var assignment: Dictionary = assignment_value
				if str(assignment.get("superregion_id", "")) == super_id:
					members.append(parent_id)

		var regions_value: Variant = super_def.get("regions", [])
		var region_defs: Array = regions_value if regions_value is Array else []
		if members.size() < region_defs.size():
			last_error = "%s: провинций %d < регионов %d" % [
				str(super_def.get("name", super_id)), members.size(), region_defs.size()
			]
			return {}
		_assign_regions(assignments, members, region_defs)

	return assignments


func _nearest_superregion(point: Vector2, super_defs: Array) -> Dictionary:
	var best: Dictionary = {}
	var best_distance := INF
	for super_value in super_defs:
		if not super_value is Dictionary:
			continue
		var super_def: Dictionary = super_value
		var seed_value: Variant = super_def.get("seed_world", Vector2.ZERO)
		var seed: Vector2 = seed_value if seed_value is Vector2 else Vector2.ZERO
		var distance := world_distance_sq(point, seed)
		if distance < best_distance:
			best_distance = distance
			best = super_def
	return best


func _set_parent_super(assignments: Dictionary, parent_id: String, super_def: Dictionary) -> void:
	assignments[parent_id] = {
		"superregion_id": str(super_def.get("id", "")),
		"superregion_name": str(super_def.get("name", "")),
		"macroregion_id": str(super_def.get("macroregion_id", "")),
		"macroregion_name": str(super_def.get("macroregion_name", "")),
		"megaregion_id": str(super_def.get("megaregion_id", "")),
		"megaregion_name": str(super_def.get("megaregion_name", "")),
		"region_id": "",
		"region_name": "",
	}


func _assign_regions(assignments: Dictionary, members: Array, region_defs: Array) -> void:
	var member_count := members.size()
	var region_count := region_defs.size()
	if member_count <= 0 or region_count <= 0:
		return

	members.sort_custom(func(a: Variant, b: Variant) -> bool:
		var point_a: Vector2 = parent_center[str(a)]
		var point_b: Vector2 = parent_center[str(b)]
		if absf(point_a.y - point_b.y) > 0.001:
			return point_a.y < point_b.y
		return point_a.x < point_b.x
	)

	var seeds: Array[Vector2] = []
	for index in range(region_count):
		var position := clampi(
			int(floor((float(index) + 0.5) * float(member_count) / float(region_count))),
			0,
			member_count - 1
		)
		seeds.append(parent_center[str(members[position])])

	var labels: Array[int] = []
	labels.resize(member_count)

	for _iteration in range(LLOYD_ITERATIONS):
		var counts: Array[int] = []
		var sum_y: Array[float] = []
		var sum_cos: Array[float] = []
		var sum_sin: Array[float] = []
		counts.resize(region_count)
		sum_y.resize(region_count)
		sum_cos.resize(region_count)
		sum_sin.resize(region_count)

		for index in range(region_count):
			counts[index] = 0
			sum_y[index] = 0.0
			sum_cos[index] = 0.0
			sum_sin[index] = 0.0

		for member_index in range(member_count):
			var point: Vector2 = parent_center[str(members[member_index])]
			var cluster_index := _nearest_seed_index(point, seeds)
			labels[member_index] = cluster_index
			counts[cluster_index] += 1
			sum_y[cluster_index] += point.y
			var angle := TAU * point.x / WORLD_PX
			sum_cos[cluster_index] += cos(angle)
			sum_sin[cluster_index] += sin(angle)

		for index in range(region_count):
			if counts[index] <= 0:
				continue
			var angle := atan2(sum_sin[index], sum_cos[index])
			if angle < 0.0:
				angle += TAU
			seeds[index] = Vector2(
				angle / TAU * WORLD_PX,
				sum_y[index] / float(counts[index])
			)

	var groups: Array = []
	groups.resize(region_count)
	for index in range(region_count):
		groups[index] = []

	for member_index in range(member_count):
		var cluster_index := _nearest_seed_index(parent_center[str(members[member_index])], seeds)
		labels[member_index] = cluster_index
		var group: Array = groups[cluster_index]
		group.append(member_index)
		groups[cluster_index] = group

	# Repair empty clusters by moving the closest province from the largest
	# cluster that still has more than one province.
	for empty_index in range(region_count):
		var empty_group: Array = groups[empty_index]
		if not empty_group.is_empty():
			continue

		var donor_index := -1
		var donor_size := 0
		for index in range(region_count):
			var candidate_group: Array = groups[index]
			if candidate_group.size() > donor_size and candidate_group.size() > 1:
				donor_size = candidate_group.size()
				donor_index = index

		if donor_index < 0:
			break

		var donor_group: Array = groups[donor_index]
		var best_position := 0
		var best_distance := INF
		for position in range(donor_group.size()):
			var member_index := int(donor_group[position])
			var distance := world_distance_sq(
				parent_center[str(members[member_index])],
				seeds[empty_index]
			)
			if distance < best_distance:
				best_distance = distance
				best_position = position

		var moved_member_index := int(donor_group[best_position])
		donor_group.remove_at(best_position)
		groups[donor_index] = donor_group
		empty_group.append(moved_member_index)
		groups[empty_index] = empty_group
		labels[moved_member_index] = empty_index

	# Stable spatial cluster ordering makes the generated map deterministic.
	var cluster_order: Array[int] = []
	for index in range(region_count):
		cluster_order.append(index)
	cluster_order.sort_custom(func(a: int, b: int) -> bool:
		var seed_a: Vector2 = seeds[a]
		var seed_b: Vector2 = seeds[b]
		if absf(seed_a.y - seed_b.y) > 0.001:
			return seed_a.y < seed_b.y
		return seed_a.x < seed_b.x
	)

	var region_for_cluster: Dictionary = {}
	for order_index in range(cluster_order.size()):
		region_for_cluster[cluster_order[order_index]] = region_defs[order_index]

	for member_index in range(member_count):
		var region_value: Variant = region_for_cluster.get(labels[member_index], {})
		var region: Dictionary = region_value if region_value is Dictionary else {}
		var parent_id := str(members[member_index])
		var assignment_value: Variant = assignments.get(parent_id, {})
		var assignment: Dictionary = assignment_value if assignment_value is Dictionary else {}
		assignment["region_id"] = str(region.get("id", ""))
		assignment["region_name"] = str(region.get("name", ""))
		assignments[parent_id] = assignment


func _nearest_seed_index(point: Vector2, seeds: Array[Vector2]) -> int:
	var best_index := 0
	var best_distance := INF
	for index in range(seeds.size()):
		var distance := world_distance_sq(point, seeds[index])
		if distance < best_distance:
			best_distance = distance
			best_index = index
	return best_index


func world_distance_sq(a: Vector2, b: Vector2) -> float:
	var dx := absf(a.x - b.x)
	dx = minf(dx, WORLD_PX - dx)
	var dy := a.y - b.y
	return dx * dx + dy * dy
