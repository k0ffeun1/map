extends Node2D
## Batched renderer for one canonical normalized-land-cell shard.
##
## The world viewer keeps only 16 of these nodes instead of creating one
## CanvasItem per cell/polygon. Godot records the draw commands once and reuses
## them until queue_redraw() is called, so camera movement does not rebuild the
## 12 902-cell geometry every frame.

const BORDER_PALETTE := [
	Color(0.34, 0.86, 1.00, 0.92),
	Color(0.42, 1.00, 0.60, 0.90),
	Color(1.00, 0.78, 0.30, 0.92),
	Color(0.86, 0.54, 1.00, 0.90),
	Color(1.00, 0.48, 0.52, 0.90),
	Color(0.30, 0.96, 0.88, 0.90),
	Color(0.96, 0.94, 0.36, 0.90),
	Color(0.66, 0.74, 1.00, 0.90),
]

var _cells: Array[Dictionary] = []


func setup(cells: Array[Dictionary]) -> void:
	_cells = cells
	queue_redraw()


func cell_count() -> int:
	return _cells.size()


func _draw() -> void:
	for cell in _cells:
		var local_index := maxi(int(cell.get("local_index", 1)), 1)
		var border: Color = BORDER_PALETTE[(local_index - 1) % BORDER_PALETTE.size()]
		for raw_part in cell.get("viewer_parts", []):
			if not raw_part is Array:
				continue
			var rings: Array = raw_part
			for raw_ring in rings:
				if not raw_ring is PackedVector2Array:
					continue
				var ring: PackedVector2Array = raw_ring
				if ring.size() >= 2:
					# Negative width requests Godot's thin line primitive. It stays
					# readable while zooming without turning a degree-wide border into
					# a huge screen-space stroke.
					draw_polyline(ring, border, -1.0, true)

# CI trigger: full-world-viewer-2026-08-22
