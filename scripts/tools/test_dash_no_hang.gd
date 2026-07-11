extends SceneTree
## Разовый тест: прогоняет IrregularCellProvider._dash_segments_world на
## реальных кольцах assets/cells_test.json с таймаутом — раньше здесь был
## бесконечный цикл (см. фикс в IrregularCellProvider.gd, EPS/MAX_DASH_SEGMENTS).
## Запуск: Godot_v4.7-stable_win64.exe --headless --script scripts/tools/test_dash_no_hang.gd


func _init() -> void:
	var text := FileAccess.get_file_as_string("res://assets/cells_test.json")
	var parsed = JSON.parse_string(text)
	var provider := IrregularCellProvider.new("res://assets/cells_test.json",
		Color(0, 0, 0, 0.85), 0.55, 0.55, 0.95, PackedColorArray(), 0.18, true, 0.5, 0.35)

	var t0 := Time.get_ticks_msec()
	var total_segments := 0
	for cell in parsed.get("cells", []):
		for ring_raw in cell.get("rings", []):
			var pts := PackedVector2Array()
			for p in ring_raw:
				pts.append(Vector2(p[0], p[1]))
			var segs: Array = provider._dash_segments_world(pts, 0.5, 0.35)
			total_segments += segs.size()
	var elapsed := Time.get_ticks_msec() - t0

	print("OK: %d штрихов посчитано за %d мс (без зависания)" % [total_segments, elapsed])
	quit()
