class_name SeaBorderTileProvider
extends RefCounted
## Слой контуров морей/заливов/проливов (весь мир), как в атласе — только линии,
## без заливки. Данные статические (не тайлы-картинки): бандл геоданных
## Natural Earth (общественное достояние), уже спроецированный в те же мировые
## координаты (Web Mercator, WORLD_PX), см. res://assets/sea_borders.json
## и scripts/tools/build_sea_borders.py (офлайн-препроцессинг, вне Godot).
##
## Рендер синхронный (без сети): при первом request_tile для тайла берём все
## кольца, чьи bbox пересекают тайл, клипуем отрезки по границе тайла и рисуем
## их в 256×256 RGBA-текстуру. Результат кэшируется по ключу "z/x/y".

const WORLD_PX := 8192.0          ## Должно совпадать с TileMapViewer.WORLD_PX.
const DATA_PATH := "res://assets/sea_borders.json"
const LINE_WIDTH := 1.6           ## Толщина линии в мировых координатах.
const LINE_COLOR := Color(0.95, 0.97, 1.0, 0.85)

var _rings: Array = []            ## [{"bbox": [x0,y0,x1,y1], "points": PackedVector2Array}]
var _tex: Dictionary = {}         ## "z/x/y" -> Texture2D
## Точки подписей: [{"name": String, "cla": String, "pos": Vector2, "area": float}]
var _labels: Array = []


func _init() -> void:
	_load_data()


func _load_data() -> void:
	if not FileAccess.file_exists(DATA_PATH):
		push_warning("SeaBorderTileProvider: нет файла %s" % DATA_PATH)
		return
	var text := FileAccess.get_file_as_string(DATA_PATH)
	var parsed = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		push_warning("SeaBorderTileProvider: не удалось разобрать %s" % DATA_PATH)
		return
	for feat in parsed.get("features", []):
		var name: String = feat.get("name", "")
		var cla: String = feat.get("cla", "")
		var best_area := 0.0
		var best_centroid := Vector2.ZERO
		for ring in feat.get("rings", []):
			if ring.size() < 2:
				continue
			var pts := PackedVector2Array()
			var minx := INF
			var miny := INF
			var maxx := -INF
			var maxy := -INF
			for p in ring:
				var v := Vector2(p[0], p[1])
				pts.append(v)
				minx = minf(minx, v.x); maxx = maxf(maxx, v.x)
				miny = minf(miny, v.y); maxy = maxf(maxy, v.y)
			_rings.append({"bbox": Vector4(minx, miny, maxx, maxy), "points": pts})

			if name.is_empty():
				continue
			# Подпись ставим в центр (area-weighted centroid) САМОГО БОЛЬШОГО
			# кольца объекта — для составных морей (несколько частей) это
			# даёт вменяемое место, а не среднее по всем частям сразу.
			var ac := _ring_area_and_centroid(pts)
			var ring_area: float = ac["area"]
			if ring_area > best_area:
				best_area = ring_area
				best_centroid = ac["centroid"]
		if not name.is_empty() and best_area > 0.0:
			_labels.append({"name": name, "cla": cla, "pos": best_centroid, "area": best_area})


## Площадь (модуль) и area-weighted центроид многоугольника (формула шнурков).
func _ring_area_and_centroid(pts: PackedVector2Array) -> Dictionary:
	var n := pts.size()
	var a := 0.0
	var cx := 0.0
	var cy := 0.0
	for i in range(n):
		var p0 := pts[i]
		var p1 := pts[(i + 1) % n]
		var cross := p0.x * p1.y - p1.x * p0.y
		a += cross
		cx += (p0.x + p1.x) * cross
		cy += (p0.y + p1.y) * cross
	a *= 0.5
	if absf(a) < 0.000001:
		# Вырожденное кольцо — просто среднее точек.
		var avg := Vector2.ZERO
		for p in pts:
			avg += p
		return {"area": 0.0, "centroid": avg / maxf(1.0, float(n))}
	cx /= (6.0 * a)
	cy /= (6.0 * a)
	return {"area": absf(a), "centroid": Vector2(cx, cy)}


## Список подписей для SeaLabelsLayer: [{"name","cla","pos"}].
func get_labels() -> Array:
	return _labels


func request_tile(z: int, x: int, y: int) -> Texture2D:
	var key := "%d/%d/%d" % [z, x, y]
	if _tex.has(key):
		return _tex[key]
	var t := _render(z, x, y)
	_tex[key] = t
	return t


func _render(z: int, x: int, y: int) -> Texture2D:
	var tw := WORLD_PX / (1 << z)
	var t0x := x * tw
	var t0y := y * tw
	var t1x := t0x + tw
	var t1y := t0y + tw
	var pad := LINE_WIDTH * 2.0

	var g := 256
	var scale := g / tw
	var out := PackedByteArray()
	out.resize(g * g * 4)  # прозрачно по умолчанию

	var half_w_px := maxf(1.0, LINE_WIDTH * scale * 0.5)

	for ring in _rings:
		var bbox: Vector4 = ring["bbox"]
		if bbox.z < t0x - pad or bbox.x > t1x + pad or bbox.w < t0y - pad or bbox.y > t1y + pad:
			continue
		var pts: PackedVector2Array = ring["points"]
		for i in range(pts.size() - 1):
			var a := pts[i]
			var b := pts[i + 1]
			if absf(a.x - b.x) > WORLD_PX * 0.5:
				continue        # разрыв на антимеридиане (180°) — не соединяем края карты
			if not _segment_touches(a, b, t0x - pad, t0y - pad, t1x + pad, t1y + pad):
				continue
			var ap := Vector2((a.x - t0x) * scale, (a.y - t0y) * scale)
			var bp := Vector2((b.x - t0x) * scale, (b.y - t0y) * scale)
			_draw_segment(out, g, ap, bp, half_w_px)

	return ImageTexture.create_from_image(
		Image.create_from_data(g, g, false, Image.FORMAT_RGBA8, out))


func _segment_touches(a: Vector2, b: Vector2, minx: float, miny: float,
		maxx: float, maxy: float) -> bool:
	if maxf(a.x, b.x) < minx or minf(a.x, b.x) > maxx:
		return false
	if maxf(a.y, b.y) < miny or minf(a.y, b.y) > maxy:
		return false
	return true


## Рисует отрезок толщиной half_w (в пикселях текстуры) в буфер out (g×g RGBA).
func _draw_segment(out: PackedByteArray, g: int, a: Vector2, b: Vector2, half_w: float) -> void:
	var min_x := maxi(0, floori(minf(a.x, b.x) - half_w - 1))
	var max_x := mini(g - 1, ceili(maxf(a.x, b.x) + half_w + 1))
	var min_y := maxi(0, floori(minf(a.y, b.y) - half_w - 1))
	var max_y := mini(g - 1, ceili(maxf(a.y, b.y) + half_w + 1))
	if min_x > max_x or min_y > max_y:
		return

	var seg := b - a
	var len2 := seg.length_squared()
	var r := int(LINE_COLOR.r * 255)
	var gc := int(LINE_COLOR.g * 255)
	var bc := int(LINE_COLOR.b * 255)
	var ac := int(LINE_COLOR.a * 255)

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
			# Антиалиасинг по краю линии + смешивание с уже нарисованным (другие кольца).
			var edge := clampf(half_w - d, 0.0, 1.0)
			var a_out := int(ac * edge)
			if a_out > out[idx + 3]:
				out[idx] = r; out[idx + 1] = gc; out[idx + 2] = bc; out[idx + 3] = a_out


# --- Интерфейс для предзагрузчика (TilePreloader) — не нужен, данных нет в сети.
func prefetch_url(_z: int, _x: int, _y: int) -> String:
	return ""


func prefetch_path(_z: int, _x: int, _y: int) -> String:
	return ""
