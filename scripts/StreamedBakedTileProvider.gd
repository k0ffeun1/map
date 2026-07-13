class_name StreamedBakedTileProvider
extends Node
## То же самое, что BakedTileProvider.gd (см. его докстринг — офлайн PNG-
## тайлы "{z}_{x}_{y}.png", фоновая декодировка в потоке), но с ОГРАНИЧЕННЫМ
## по памяти кэшем текстур (LRU-вытеснение). Заведено для нового запечённого
## слоя 2 (см. bake_ocean_v_base_depth_tiles.py/bake_ocean_v_shallow_tiles.py,
## 2026-07-13) — тот комплект может со временем покрывать весь мир на всех
## LOD (десятки тысяч тайлов), а BakedTileProvider._cache растёт бесконечно
## (см. его аудит-комментарий) — при активном панорамировании по всему миру
## на близком зуме память росла бы без предела.
##
## Не трогает BakedTileProvider.gd — тот использует уже существующий "Спутник"/
## "Континенты"/"Суша-Море"/старый "Мировой океан" и т.п.; переводить их на
## LRU отдельная задача не по этой сессии.

const MAX_TEXTURE_CREATES_PER_FRAME := 16

## ~4МБ на тайл 1024x1024 RGBA8 (см. задачу) — бюджет по умолчанию 384МБ
## (в диапазоне 256-512МБ, запрошенном пользователем) -> ~96 тайлов в кэше.
## Этого с запасом хватает на видимый экран + запас TILE_PAD одного LOD.
const DEFAULT_BUDGET_TILES := 96

var _dir: String
var _max_baked_z: int
var _budget_tiles: int
var _cache: Dictionary = {}       ## "z/x/y" -> Texture2D
var _lru_order: Array = []        ## ключи от самого старого к самому свежему
var _decoding: Dictionary = {}    ## "z/x/y" -> true
var _done_mutex := Mutex.new()
var _done_images: Array = []
var _task_ids: Array = []
var _blank_tex: Texture2D

## Статистика для отладки (см. задачу "кэш должен показывать статистику").
var stat_hits := 0
var stat_misses := 0
var stat_evictions := 0


func _init(dir: String, max_baked_z: int, budget_tiles: int = DEFAULT_BUDGET_TILES) -> void:
	_dir = dir
	_max_baked_z = max_baked_z
	_budget_tiles = budget_tiles
	var blank := Image.create(256, 256, false, Image.FORMAT_RGBA8)
	_blank_tex = ImageTexture.create_from_image(blank)


func _exit_tree() -> void:
	for id in _task_ids:
		WorkerThreadPool.wait_for_task_completion(id)


func request_tile(z: int, x: int, y: int) -> Texture2D:
	var key := "%d/%d/%d" % [z, x, y]
	if _cache.has(key):
		stat_hits += 1
		_touch_lru(key)
		return _cache[key]
	if _decoding.has(key):
		return null

	stat_misses += 1
	if z > _max_baked_z:
		return null  # см. комментарий в шапке BakedTileProvider.gd — "ещё грузится", не пусто

	var path := "%s/%d_%d_%d.png" % [_dir, z, x, y]
	if not FileAccess.file_exists(path):
		_store_in_cache(key, _blank_tex)
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
		_store_in_cache(key, ImageTexture.create_from_image(img) if img != null else _blank_tex)
		i += 1
		budget -= 1
	if i < done.size():
		_done_mutex.lock()
		_done_images = done.slice(i) + _done_images
		_done_mutex.unlock()


func _touch_lru(key: String) -> void:
	var idx := _lru_order.find(key)
	if idx >= 0:
		_lru_order.remove_at(idx)
	_lru_order.append(key)


func _store_in_cache(key: String, tex: Texture2D) -> void:
	_cache[key] = tex
	_touch_lru(key)
	while _lru_order.size() > _budget_tiles:
		var oldest: String = _lru_order.pop_front()
		_cache.erase(oldest)
		stat_evictions += 1


func get_stats_text() -> String:
	return "тайлов в кэше: %d/%d, попаданий: %d, промахов: %d, вытеснено: %d" % [
		_cache.size(), _budget_tiles, stat_hits, stat_misses, stat_evictions]
