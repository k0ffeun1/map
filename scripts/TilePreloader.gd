class_name TilePreloader
extends Node
## Фоновая предзагрузка ВСЕХ тайлов мира на диск (уровни 0..max_z).
##
## Качает тайлы у переданных провайдеров и складывает их в тот же дисковый кэш,
## откуда провайдеры потом читают мгновенно. Работает в фоне, не держит тайлы
## в памяти (только пишет файлы), поэтому память не растёт.
##
## ВНИМАНИЕ: весь мир до z7 — это ~21845 тайлов НА КАЖДЫЙ источник
## (карта + высоты => ~44000 запросов, сотни МБ, несколько минут в первый раз).
## Дальше всё берётся с диска и грузится моментально. Уже скачанное пропускается.

const POOL_SIZE := 3    ## Параллельные закачки (мало, чтобы не душить видимые тайлы).
const START_DELAY := 10.0        ## Сек до старта — сначала пусть загрузится видимое.
const SCAN_BUDGET_PER_FRAME := 400  ## Проверок file_exists за кадр (против фризов).

var _headers := PackedStringArray(["User-Agent: GlobalStrategyPrototype/0.2 (Godot)"])
var _providers: Array = []
var _max_z := 0

# Итератор по задачам (без хранения огромного списка).
var _pi := 0            ## индекс провайдера
var _z := 0
var _x := 0
var _y := 0
var _exhausted := false

var _total := 0
var _done := 0
var _downloaded := 0
var _free_http: Array = []

var _label: Label
var _finished := false


## Запуск. providers — объекты с prefetch_url(z,x,y) и prefetch_path(z,x,y).
func setup(providers: Array, max_z: int) -> void:
	_providers = providers
	_max_z = max_z

	# Всего тайлов = провайдеры * сумма(4^z, z=0..max_z).
	var per_provider := 0
	for z in range(max_z + 1):
		per_provider += 1 << (2 * z)   # 4^z
	_total = per_provider * providers.size()

	for i in range(POOL_SIZE):
		var http := HTTPRequest.new()
		http.timeout = 15.0
		add_child(http)
		http.request_completed.connect(_on_done.bind(http))
		_free_http.append(http)

	# Стартуем с задержкой: первые секунды сеть нужна видимой области карты.
	set_process(false)
	get_tree().create_timer(START_DELAY).timeout.connect(func () -> void:
		_make_label()
		set_process(true))


func _make_label() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	_label = Label.new()
	_label.add_theme_color_override("font_color", Color(0.8, 1.0, 0.8))
	_label.position = Vector2(24, 985)   # над строкой статуса, ниже панели подсказок
	layer.add_child(_label)


## Следующая задача [provider, z, x, y] или null, если всё пройдено.
func _next_task() -> Variant:
	while not _exhausted:
		if _pi >= _providers.size():
			_exhausted = true
			return null
		var n := 1 << _z
		if _y >= n:
			_y = 0
			_z += 1
			if _z > _max_z:
				_z = 0
				_pi += 1
			continue
		if _x >= n:
			_x = 0
			_y += 1
			continue
		var task: Array = [_providers[_pi], _z, _x, _y]
		_x += 1
		return task
	return null


## Продвижение с бюджетом: не больше budget задач за вызов, чтобы проход по
## десяткам тысяч уже скачанных файлов (file_exists) не замораживал кадр.
func _process(_delta: float) -> void:
	_pump(SCAN_BUDGET_PER_FRAME)


func _pump(budget: int) -> void:
	if _finished:
		return
	while budget > 0 and _free_http.size() > 0:
		var task: Variant = _next_task()
		if task == null:
			if _free_http.size() == POOL_SIZE:
				_finish()
			return
		budget -= 1
		var provider = task[0]
		var path: String = provider.prefetch_path(task[1], task[2], task[3])
		if FileAccess.file_exists(path):
			_done += 1          # уже в кэше
			continue
		var http: HTTPRequest = _free_http.pop_back()
		http.set_meta("path", path)
		var url: String = provider.prefetch_url(task[1], task[2], task[3])
		if http.request(url, _headers) != OK:
			_free_http.append(http)
			_done += 1
	_update_label()


func _on_done(result: int, code: int, _h: PackedStringArray, body: PackedByteArray,
		http: HTTPRequest) -> void:
	if result == HTTPRequest.RESULT_SUCCESS and code == 200 and not body.is_empty():
		var f := FileAccess.open(http.get_meta("path"), FileAccess.WRITE)
		if f:
			f.store_buffer(body)
			f.close()
			_downloaded += 1
	_done += 1
	_free_http.append(http)
	if _done % 25 == 0:
		_update_label()
	_pump(SCAN_BUDGET_PER_FRAME)


func _update_label() -> void:
	if _label == null:
		return
	var pct := 100.0 * _done / maxf(1.0, _total)
	_label.text = "Предзагрузка тайлов: %.1f%%  (%d / %d, скачано %d)" % [
		pct, _done, _total, _downloaded]


func _finish() -> void:
	if _finished:
		return
	_finished = true
	set_process(false)
	if _label:
		_label.text = "Предзагрузка завершена (%d тайлов)." % _downloaded
		await get_tree().create_timer(4.0).timeout
		_label.queue_free()
	queue_free()
