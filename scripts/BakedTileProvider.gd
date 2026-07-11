class_name BakedTileProvider
extends Node
## Читает заранее "запечённые" офлайн PNG-тайлы (см.
## scripts/tools/bake_continents_tiles.py) с диска — без сети, без
## пересчёта геометрии на лету. Формат имени файла: "{z}_{x}_{y}.png".
##
## Интерфейс тот же, что у остальных провайдеров: request_tile(z, x, y).
## Тайла нет на диске В ПРЕДЕЛАХ запечённых уровней (напр. открытый океан —
## там нечего рисовать) -> сразу отдаём прозрачную текстуру (дёшево, без
## похода в поток). А вот ЗА пределами запечённых уровней (z > max_baked_z,
## глубже, чем печь имело смысл — см. bake_continents_tiles.py) — ВАЖНО
## возвращать null ("ещё гружусь"), а НЕ готовую пустую текстуру: иначе
## TileMapViewer.gd решает, что слой полностью загружен, и сразу выбрасывает
## подложку предыдущего (более крупного) уровня зума вместо того, чтобы
## красиво растянуть её, пока настоящих тайлов на этом уровне нет и не
## будет — было видно как пропажа цвета и швы между уровнями зума при
## переходе через незапечённые уровни (см. сессию/TODO.md).

## Сколько ImageTexture создавать за один _process() — см. то же самое в
## OnlineTileProvider.gd (защита от микрофриза при массовом "дозревании"
## фоновых декодирований одним кадром).
const MAX_TEXTURE_CREATES_PER_FRAME := 16

var _dir: String
var _max_baked_z: int
var _cache: Dictionary = {}     ## "z/x/y" -> Texture2D
var _decoding: Dictionary = {}  ## "z/x/y" -> true (декодируется в фоне)
var _done_mutex := Mutex.new()
var _done_images: Array = []    ## [[key, Image], ...]
var _task_ids: Array = []
var _blank_tex: Texture2D


func _init(dir: String, max_baked_z: int) -> void:
	_dir = dir
	_max_baked_z = max_baked_z
	var blank := Image.create(256, 256, false, Image.FORMAT_RGBA8)
	_blank_tex = ImageTexture.create_from_image(blank)


func _exit_tree() -> void:
	for id in _task_ids:
		WorkerThreadPool.wait_for_task_completion(id)


func request_tile(z: int, x: int, y: int) -> Texture2D:
	var key := "%d/%d/%d" % [z, x, y]
	if _cache.has(key):
		return _cache[key]
	if _decoding.has(key):
		return null

	if z > _max_baked_z:
		return null  # см. комментарий в шапке файла

	var path := "%s/%d_%d_%d.png" % [_dir, z, x, y]
	if not FileAccess.file_exists(path):
		# Нет файла -> тут нечего рисовать (напр. открытый океан на этом
		# уровне зума) — не "ещё грузится", а окончательно пусто.
		_cache[key] = _blank_tex
		return _blank_tex

	_decoding[key] = true
	_task_ids.append(WorkerThreadPool.add_task(_decode_in_thread.bind(key, path)))
	return null


func _decode_in_thread(key: String, path: String) -> void:
	var img := Image.new()
	var err := img.load(path)
	_done_mutex.lock()
	_done_images.append([key, img if err == OK else null])
	_done_mutex.unlock()


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
		_decoding.erase(key)
		var img: Image = done[i][1]
		_cache[key] = ImageTexture.create_from_image(img) if img != null else _blank_tex
		i += 1
		budget -= 1
	if i < done.size():
		_done_mutex.lock()
		_done_images = done.slice(i) + _done_images
		_done_mutex.unlock()
