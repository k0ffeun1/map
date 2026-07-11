class_name OnlineTileProvider
extends Node
## Загружает РЕАЛЬНЫЕ тайлы карты Земли с онлайн-сервера (схема XYZ / slippy map).
##
## По умолчанию — спутник ESRI World Imagery (как в Google/Yandex-спутнике).
## Тайлы качаются асинхронно пулом HTTPRequest, кэшируются в памяти И на диске.
##
## Интерфейс тот же, что у процедурных слоёв: request_tile(z, x, y).
##   - вернёт Texture2D, если тайл готов (память или диск);
##   - вернёт null, если ещё качается (спрайт появится, когда загрузится).
##
## Диск-кэш (user://tilecache): при повторном запуске карта грузится мгновенно
## и работает офлайн для уже виденных мест.
##
## ВНИМАНИЕ: первая загрузка нужен интернет. У каждого тайл-сервера свои условия
## использования — для публичного релиза выбирайте разрешённый источник/ключ.

## Стиль карты. Меняешь STYLE_ID + URL_TEMPLATE — меняется вся стилистика.
## Порядок {z}/{y}/{x} — как у ESRI (сначала строка y, потом столбец x).
##
## Доступные бесплатные стили ESRI (тот же сервер, меняется имя сервиса):
##   World_Physical_Map   — стилизованный атлас (равнины/горы), до z8. ← сейчас
##   World_Shaded_Relief  — рельеф-отмывка (коричнево-серый), до z13.
##   World_Terrain_Base   — приглушённый рельеф, до z13.
##   World_Imagery        — спутник (фото), до z19.
const STYLE_ID := "esri_physical"
const URL_TEMPLATE := "https://server.arcgisonline.com/ArcGIS/rest/services/World_Physical_Map/MapServer/tile/{z}/{y}/{x}"
const POOL_SIZE := 16          ## Сколько тайлов качаем параллельно.
const REQUEST_TIMEOUT := 10.0  ## Сек. Зависший запрос освобождает слот.
## Сколько ImageTexture создавать за один _process(). Без лимита, если разом
## "дозрело" много фоновых декодирований (резкий разворот камеры/смена слоя),
## главный поток создал бы все текстуры одним кадром — микрофриз. Остаток
## просто доделывается в следующих кадрах, спрайт появится на кадр-два позже.
const MAX_TEXTURE_CREATES_PER_FRAME := 16
const CACHE_DIR := "user://tilecache"
## Тайлы, "запечённые" в саму игру (копируются сюда перед сборкой билда —
## см. README, раздел "Как раздать карту вместе с игрой"). Только чтение,
## доступны и в экспортированной сборке.
const BUNDLE_DIR := "res://assets/tiles_bundle/tilecache"

var _headers := PackedStringArray(["User-Agent: GlobalStrategyPrototype/0.2 (Godot)"])
var _cache: Dictionary = {}    ## "z/x/y" -> Texture2D (готовые, в памяти).
var _pending: Dictionary = {}  ## "z/x/y" -> true (в очереди / качается).
var _queue: Array = []         ## Очередь [z, x, y].
var _free_http: Array = []     ## Свободные HTTPRequest.

# Декодирование JPEG/PNG — это миллисекунды НА КАЖДЫЙ тайл; в главном потоке
# оно давало рывки при каждом зуме. Поэтому чтение файла и декодирование
# уходят в WorkerThreadPool, а главный поток только создаёт текстуру из
# готового Image (быстро) в _process.
var _decoding: Dictionary = {}   ## "z/x/y" -> true (декодируется в фоне).
var _done_mutex := Mutex.new()
var _done_images: Array = []     ## [[key, Image|null], ...] — результаты потоков.
var _task_ids: Array = []        ## Активные задачи WorkerThreadPool (ждём их при выходе).


## Если узел уничтожат, пока фоновый поток ещё бежит, callable (метод этого
## же объекта) станет невалидным и поток упадёт с ошибкой в "previously freed"
## объект. Поэтому перед уничтожением дожидаемся всех задач.
func _exit_tree() -> void:
	for id in _task_ids:
		WorkerThreadPool.wait_for_task_completion(id)


func _ready() -> void:
	DirAccess.make_dir_recursive_absolute(CACHE_DIR)
	for i in range(POOL_SIZE):
		var http := HTTPRequest.new()
		http.timeout = REQUEST_TIMEOUT
		add_child(http)
		http.request_completed.connect(_on_request_completed.bind(http))
		_free_http.append(http)


## Запрос тайла. Готов -> Texture2D; ещё нет -> null (и ставим в очередь:
## сеть или фоновое декодирование — спрайт появится, когда тайл будет готов).
func request_tile(z: int, x: int, y: int) -> Texture2D:
	var key := "%d/%d/%d" % [z, x, y]
	if _cache.has(key):
		return _cache[key]
	if _decoding.has(key) or _pending.has(key):
		return null

	# 1) Тайл зашит в саму игру (res://) — доступен и офлайн, и в билде.
	# 2) Или локальный кэш игрока (то, что он сам догрузил во время игры).
	var path := _bundle_path(key)
	if not FileAccess.file_exists(path):
		path = _disk_path(key)
		if not FileAccess.file_exists(path):
			_pending[key] = true
			_queue.append([z, x, y])
			_pump()
			return null

	# Файл есть — декодируем в фоновом потоке, текстура появится через кадр-два.
	_decoding[key] = true
	_task_ids.append(WorkerThreadPool.add_task(_decode_file_in_thread.bind(key, path)))
	return null


func _decode_file_in_thread(key: String, path: String) -> void:
	var img := _load_image(FileAccess.get_file_as_bytes(path))
	_done_mutex.lock()
	_done_images.append([key, img])
	_done_mutex.unlock()


func _process(_delta: float) -> void:
	# Чистим список задач от завершённых (иначе _exit_tree ждал бы их вечно
	# ссылками на давно готовые задачи — WorkerThreadPool держит их до опроса).
	_task_ids = _task_ids.filter(func (id: int) -> bool:
		return not WorkerThreadPool.is_task_completed(id))

	# Забираем готовые Image из потоков и создаём текстуры (это быстро, но не
	# бесплатно — ограничиваем штук за кадр, см. MAX_TEXTURE_CREATES_PER_FRAME).
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
		if img != null:
			_cache[key] = ImageTexture.create_from_image(img)
		i += 1
		budget -= 1
	if i < done.size():
		_done_mutex.lock()
		_done_images = done.slice(i) + _done_images
		_done_mutex.unlock()


func _pump() -> void:
	while _queue.size() > 0 and _free_http.size() > 0:
		var t: Array = _queue.pop_front()
		var http: HTTPRequest = _free_http.pop_back()
		var key := "%d/%d/%d" % [t[0], t[1], t[2]]
		var url := URL_TEMPLATE.format({"z": t[0], "x": t[1], "y": t[2]})
		http.set_meta("key", key)
		var err := http.request(url, _headers)
		if err != OK:
			_pending.erase(key)
			_free_http.append(http)


func _on_request_completed(result: int, code: int, _headers2: PackedStringArray,
		body: PackedByteArray, http: HTTPRequest) -> void:
	var key: String = http.get_meta("key", "")
	_pending.erase(key)
	_free_http.append(http)

	if result == HTTPRequest.RESULT_SUCCESS and code == 200 and not body.is_empty():
		# Запись на диск и декодирование — в фоне, чтобы не дёргать кадр.
		_decoding[key] = true
		_task_ids.append(WorkerThreadPool.add_task(_save_and_decode_in_thread.bind(key, body)))

	_pump()  # берём следующий тайл из очереди


func _save_and_decode_in_thread(key: String, body: PackedByteArray) -> void:
	# Сохраняем на диск для мгновенной загрузки в будущем.
	var f := FileAccess.open(_disk_path(key), FileAccess.WRITE)
	if f:
		f.store_buffer(body)
		f.close()
	var img := _load_image(body)
	_done_mutex.lock()
	_done_images.append([key, img])
	_done_mutex.unlock()


## Декодирование байтов тайла в Image (ESRI — JPEG, запасной вариант PNG).
## Вызывается из фоновых потоков — только Image, без создания текстур.
func _load_image(body: PackedByteArray) -> Image:
	if body.is_empty():
		return null
	var img := Image.new()
	var e := img.load_jpg_from_buffer(body)
	if e != OK:
		e = img.load_png_from_buffer(body)
	return img if e == OK else null


func _disk_path(key: String) -> String:
	# STYLE_ID в имени -> при смене стиля старые тайлы не подмешиваются.
	return "%s/%s_%s.img" % [CACHE_DIR, STYLE_ID, key.replace("/", "_")]


func _bundle_path(key: String) -> String:
	return "%s/%s_%s.img" % [BUNDLE_DIR, STYLE_ID, key.replace("/", "_")]


# --- Интерфейс для предзагрузчика (TilePreloader) -----------------------------
func prefetch_url(z: int, x: int, y: int) -> String:
	return URL_TEMPLATE.format({"z": z, "x": x, "y": y})


func prefetch_path(z: int, x: int, y: int) -> String:
	return _disk_path("%d/%d/%d" % [z, x, y])
