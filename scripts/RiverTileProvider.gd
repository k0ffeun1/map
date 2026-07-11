class_name RiverTileProvider
extends Node
## Реки трёх уровней значимости (полилинии, НЕ полигоны) — офлайн-препроцессинг,
## см. scripts/tools/build_rivers.py / assets/rivers.json (Natural Earth
## ne_10m_rivers_lake_centerlines, поле "tier": 0 крупные/1 средние/2 мелкие,
## см. заголовок build_rivers.py). Важно для будущих механик (границы/торговые
## пути/движение вдоль рек, см. TODO.md).
##
## Рендер — та же схема, что у IrregularCellProvider (WorkerThreadPool,
## request_tile отдаёт null пока фон считает Image), но без заливки — только
## отрезки линий; толщина и цвет зависят от tier (крупные толще/темнее,
## мелкие тоньше/светлее).

const WORLD_PX := 8192.0

var _rivers: Array = []           ## [{"bbox":Vector4, "points":PackedVector2Array, "tier":int}]
var _tex: Dictionary = {}         ## "z/x/y" -> Texture2D
var _tier_widths: PackedFloat32Array   ## Толщина в мировых координатах по tier.
var _tier_colors: Array            ## Color по tier.


var _rendering: Dictionary = {}
var _done_mutex := Mutex.new()
var _done_images: Array = []
var _task_ids: Array = []

## Сколько ImageTexture создавать за один _process() — см. то же самое в
## OnlineTileProvider.gd (защита от микрофриза при массовом "дозревании"
## фоновых рендеров одним кадром).
const MAX_TEXTURE_CREATES_PER_FRAME := 16


func _init(data_path: String,
		tier_widths: PackedFloat32Array = PackedFloat32Array([1.1, 0.7, 0.4]),
		tier_colors: Array = [
			Color(0.20, 0.40, 0.72, 0.9),
			Color(0.28, 0.48, 0.78, 0.75),
			Color(0.35, 0.55, 0.80, 0.55),
		]) -> void:
	_tier_widths = tier_widths
	_tier_colors = tier_colors
	_load_data(data_path)


func _exit_tree() -> void:
	for id in _task_ids:
		WorkerThreadPool.wait_for_task_completion(id)


func _process(_delta: float) -> void:
	_task_ids = _task_ids.filter(func (id: int) -> bool:
		return not WorkerThreadPool.is_task_completed(id))

	_done_mutex.lock()
	var done := _done_images
	_done_images = []
	_done_mutex.unlock()
	var budget := MAX_TEXTURE_CREATES_PER_FRAME
	var i := 0
	while i < done.size() and budget > 0:
		var key: String = done[i][0]
		_rendering.erase(key)
		var img: Image = done[i][1]
		if img != null:
			_tex[key] = ImageTexture.create_from_image(img)
		i += 1
		budget -= 1
	if i < done.size():
		_done_mutex.lock()
		_done_images = done.slice(i) + _done_images
		_done_mutex.unlock()


func _load_data(path: String) -> void:
	if not FileAccess.file_exists(path):
		push_warning("RiverTileProvider: нет файла %s" % path)
		return
	var text := FileAccess.get_file_as_string(path)
	var parsed = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		push_warning("RiverTileProvider: не удалось разобрать %s" % path)
		return
	for river in parsed.get("rivers", []):
		var line: Array = river.get("points", [])
		if line.size() < 2:
			continue
		var pts := PackedVector2Array()
		for p in line:
			pts.append(Vector2(p[0], p[1]))
		var b: Array = river.get("bbox", [0, 0, 0, 0])
		_rivers.append({
			"bbox": Vector4(b[0], b[1], b[2], b[3]),
			"points": pts,
			"tier": int(river.get("tier", 0)),
		})


func request_tile(z: int, x: int, y: int) -> Texture2D:
	var key := "%d/%d/%d" % [z, x, y]
	if _tex.has(key):
		return _tex[key]
	if _rendering.has(key):
		return null
	_rendering[key] = true
	_task_ids.append(WorkerThreadPool.add_task(_render_in_thread.bind(key, z, x, y)))
	return null


func _render_in_thread(key: String, z: int, x: int, y: int) -> void:
	var img := _render(z, x, y)
	_done_mutex.lock()
	_done_images.append([key, img])
	_done_mutex.unlock()


func _render(z: int, x: int, y: int) -> Image:
	var tw := WORLD_PX / (1 << z)
	var t0x := x * tw
	var t0y := y * tw
	var t1x := t0x + tw
	var t1y := t0y + tw
	var max_width: float = _tier_widths[0] if not _tier_widths.is_empty() else 1.0
	var pad := max_width * 2.0

	var g := 256
	var scale := g / tw
	var out := PackedByteArray()
	out.resize(g * g * 4)  # прозрачно по умолчанию

	# Мелкие реки рисуем ПЕРВЫМИ, крупные — ПОСЛЕДНИМИ (поверх): на стыках
	# крупная река не должна теряться под мелкими притоками того же пикселя.
	for tier in range(_tier_widths.size() - 1, -1, -1):
		var half_w := maxf(1.0, _tier_widths[tier] * scale * 0.5)
		var color: Color = _tier_colors[tier] if tier < _tier_colors.size() else _tier_colors[0]
		for river in _rivers:
			if int(river["tier"]) != tier:
				continue
			var bbox: Vector4 = river["bbox"]
			if bbox.z < t0x - pad or bbox.x > t1x + pad or bbox.w < t0y - pad or bbox.y > t1y + pad:
				continue
			var world_pts: PackedVector2Array = river["points"]
			var local_pts := PackedVector2Array()
			for p in world_pts:
				local_pts.append(Vector2((p.x - t0x) * scale, (p.y - t0y) * scale))
			for i in range(local_pts.size() - 1):
				_draw_segment(out, g, local_pts[i], local_pts[i + 1], half_w, color)

	return Image.create_from_data(g, g, false, Image.FORMAT_RGBA8, out)


func _draw_segment(out: PackedByteArray, g: int, a: Vector2, b: Vector2, half_w: float, color: Color) -> void:
	var min_x := maxi(0, floori(minf(a.x, b.x) - half_w - 1))
	var max_x := mini(g - 1, ceili(maxf(a.x, b.x) + half_w + 1))
	var min_y := maxi(0, floori(minf(a.y, b.y) - half_w - 1))
	var max_y := mini(g - 1, ceili(maxf(a.y, b.y) + half_w + 1))
	if min_x > max_x or min_y > max_y:
		return

	var seg := b - a
	var len2 := seg.length_squared()
	var r := int(color.r * 255)
	var gc := int(color.g * 255)
	var bc := int(color.b * 255)
	var ac := int(color.a * 255)

	for py in range(min_y, max_y + 1):
		for px in range(min_x, max_x + 1):
			var p := Vector2(px + 0.5, py + 0.5)
			var d: float
			if len2 <= 0.000001:
				d = p.distance_to(a)
			else:
				var t := clampf((p - a).dot(seg) / len2, 0.0, 1.0)
				d = p.distance_to(a + seg * t)
			if d > half_w:
				continue
			var idx := (py * g + px) * 4
			var edge := clampf(half_w - d, 0.0, 1.0)
			var src_a := int(ac * edge)
			var dst_a := out[idx + 3]
			var out_a := src_a + dst_a * (255 - src_a) / 255
			if out_a <= 0:
				continue
			out[idx] = (r * src_a + out[idx] * dst_a * (255 - src_a) / 255) / maxi(1, out_a)
			out[idx + 1] = (gc * src_a + out[idx + 1] * dst_a * (255 - src_a) / 255) / maxi(1, out_a)
			out[idx + 2] = (bc * src_a + out[idx + 2] * dst_a * (255 - src_a) / 255) / maxi(1, out_a)
			out[idx + 3] = out_a


# --- Интерфейс для предзагрузчика — не нужен, данные локальные (без сети).
func prefetch_url(_z: int, _x: int, _y: int) -> String:
	return ""


func prefetch_path(_z: int, _x: int, _y: int) -> String:
	return ""
