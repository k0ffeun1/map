extends Node2D
## Тайловый движок карты со стримингом и уровнями детализации (LOD).
##
## Держит стек СЛОЁВ (физический + оверлеи). Каждый кадр:
##   1) по зуму камеры выбирает уровень z (LOD);
##   2) считает, какие тайлы видны;
##   3) догружает недостающие (с ограничением на кадр) и выгружает лишние.
##
## Так гигантская карта (весь мир -> зум до острова) занимает мало памяти:
## в кэше только то, что реально видно рядом.
##
## Слои переключаются клавишами 1..4. Физический — базовый, остальные —
## полупрозрачные оверлеи поверх него.

# --- Параметры мира -----------------------------------------------------------
const WORLD_PX := 8192          ## Размер мира в мировых координатах (px).
const TILE_PX := 256            ## Целевой экранный размер тайла.
const MIN_Z := 0
const MAX_Z := 7                ## Максимальная детализация зума (интерактивная, по требованию).
## Фоновый TilePreloader.gd качает ВЕСЬ мир на диск заранее — на полный MAX_Z=7
## это 16384 тайла на источник ТОЛЬКО для последнего уровня. Урезаем именно
## фоновую (заранее для всей планеты) прогрузку ДО z5 (1365 тайлов/источник)
## ради памяти/трафика, а сам зум по требованию всё равно доступен до
## MAX_Z=7 — недостающие z6/z7-тайлы конкретной видимой области подгружаются
## как обычно по мере приближения камеры, просто не докачиваются заранее для
## всей планеты целиком.
const PRELOAD_MAX_Z := 5
const TILE_PAD := 1             ## Запас тайлов за краями экрана.
const MAX_GEN_PER_FRAME := 16   ## Сколько спрайтов-тайлов создаём за кадр (против рывков).
const LOD_HYSTERESIS := 0.15    ## Запас за границей уровня, чтобы LOD не скакал туда-сюда.

## Полярные пороги — общие для всех геослоёв проекта (~76°N/~58°S, см. те же
## константы в build_land_sea.py/build_continents.py и др.). Здесь
## используются как ГРАНИЦЫ ВСЕЙ КАРТЫ (а не только одного слоя): камеру
## вообще нельзя провести/приблизить в Антарктиду и на Крайний Север ни на
## одном слое, поэтому тайлы этих широт даже не запрашиваются.
const NORTH_CUTOFF_Y := 1361.5
const SOUTH_CUTOFF_Y := 5724.7

## Стиль границ по уровню лестницы территорий (см. УРОВНЕЙ_ТЕРРИТОРИЙ.md).
## Только уровни, для которых сейчас реально есть геометрия на экране —
## "region"/"country" не заводим заранее без данных (см. CLAUDE.md: не тащить
## инфраструктуру про запас).
##
## "width"/"feather"/"min_half_w" — МИРОВЫЕ/растровые единицы для
## IrregularCellProvider (см. его комментарии), не экранные px напрямую. Но
## по формуле `screen_px = width × TILE_PX / (WORLD_PX / 2^LOD)` (raster_px
## сокращается — см. обсуждение с пользователем) числа ниже подобраны так,
## чтобы на LOD z7 (близкий зум) толщина на экране была ровно "width_target_px".
## cell: 0.375 -> 1.5px @ z7.  province: 0.625 -> 2.5px @ z7.
const BORDER_STYLE := {
	"cell": {
		# Граница МЕЖДУ клетками внутри провинции (не внешний контур — тот
		# отдельно, см. "cell_boundary" ниже). Подобрано пользователем через
		# живой ползунок 2026-07-11, зафиксировано как константа (панель
		# убрана). Общий стиль для слоя "C" и черновой сетки Ла-Коруньи ("G")
		# — трогает оба.
		"width": 0.100,
		"color": Color(0.0, 0.0, 0.0, 1.0),
		"feather": 3.0,
		"min_half_w": 0.2,   # растровые px; raster_px=1024 -> эквивалент ~0.05 экранного px, не мешает
		"raster_px": 1024,
		"dashed": true,
		"dash_len": 0.5,
		"dash_gap": 0.35,
	},
	"sea": {
		# Тонкая тёмно-синяя сетка навигации (см. §15 архитектуры морских
		# клеток) — не должна визуально спорить с сушей, alpha заметно ниже,
		# чем у province/cell.
		"width": 0.375,
		"color": Color(0.10, 0.20, 0.35, 0.35),
		"feather": 2.0,
		"min_half_w": 0.2,
		"raster_px": 1024,
		"dashed": false,
		"dash_len": 0.0,
		"dash_gap": 0.0,
	},
	"cell_boundary": {
		# Внешняя граница провинции ВНУТРИ слоя "C" (клетки Ла-Коруньи) — по
		# прямой просьбе пользователя 2026-07-11: "внешнюю границу оставить,
		# внутренние — без контуров". Независима от "cell" (рёбра между
		# клетками, см. выше) — рисуется отдельным проходом в
		# IrregularCellProvider._render (boundary_style, см. "brd_boundary").
		# Подобрано пользователем через временный живой ползунок, потом
		# зафиксировано как константа (сам ползунок/панель убраны).
		"width": 0.250,
		"color": Color(0.0, 0.0, 0.0, 1.0),
		"feather": 3.0,
		"min_half_w": 0.2,
	},
	"province": {
		# История правок в этой сессии (2026-07-10): 0.625 -> 0.2 (тоньше) ->
		# alpha=0 (убрана совсем, оказалось что видимая "граница" была на
		# самом деле щелями между провинциями, не отрисовкой) -> теперь
		# ВОЗВРАЩЕНА по прямой просьбе: тонкая (width=0.15), РЕЗКАЯ (feather
		# сведён к минимуму, не 0 — при feather=0 в _draw_segment было бы
		# деление на ноль), НЕпрозрачная (alpha=1.0).
		"width": 0.15,
		"color": Color(0.0, 0.0, 0.0, 1.0),
		"feather": 0.1,
		# min_half_w тоже уменьшен пропорционально — иначе пол снова
		# перебивает width на зумах ниже z7 (см. историю правки ниже).
		"min_half_w": 0.05,
		# 1024, как у клеток — по просьбе пользователя, ЗНАЯ цену: в отличие
		# от клеток (1-2 тайла всего), этот слой кроет весь мир, так что это
		# реально 16x пикселей на КАЖДЫЙ видимый тайл, а не разово. Приемлемо
		# для прототипа/сессии разработки; если станет заметно тормозить при
		# активном панорамировании по всему миру на близком зуме — снизить
		# обратно до 256/512 (см. обсуждение с пользователем в этой сессии).
		"raster_px": 1024,
		"dashed": false,
		"dash_len": 0.0,
		"dash_gap": 0.0,
	},
}

@onready var camera: Camera2D = $Camera2D
@onready var container: Node2D = $TileContainer
@onready var status_label: Label = $UI/StatusLabel

# --- Слои ---------------------------------------------------------------------
## Каждый слой: { "name": String, "provider": TileProvider, "visible": bool }
var _layers: Array = []
## Активные спрайты тайлов: ключ "layer|z/x/y" -> Sprite2D.
var _active: Dictionary = {}

var _sea_labels: SeaLabelsLayer ## Подписи морей/океанов (вместе со слоем "Моря", клавиша 6).
var _sea_layer_idx := -1        ## Индекс слоя "Моря" в _layers (для видимости подписей).
var _province_city_labels: SeaLabelsLayer ## Подписи городов провинций (вместе со слоем "Провинции", клавиша 4) — тот же генерический класс подписи-по-точке, что у морей.
var _lod := -1                 ## Текущий уровень детализации (с гистерезисом).
var _mark_tool: MarkTool       ## Разметка карты кликами -> scripts/tools/_work/user_marks.json (клавиша M).

# --- Клик по клетке (тест: Ла-Корунья) -----------------------------------------
var _cells_test_layer_idx := -1          ## Индекс слоя "Клетки (тест: Ла-Корунья)" в _layers.
var _cells_test_provider: IrregularCellProvider  ## Для point-in-polygon по клику (get_cell_id_at).
var _test_cells_by_id: Dictionary = {}   ## "id" -> Cell (см. CellCatalog.load_cells).
var _cell_info_label: Label              ## Панель с показателями кликнутой клетки.

var _ocean_layer_idx := -1  ## Индекс слоя "Мировой океан" — при включении заодно включает слой "Реки".

## Был ВРЕМЕННО живой (2026-07-11, пока подбирали заход на сушу/ширину
## мелководья ползунком) — ВОЗВРАЩЕНО на запечённый (BakedTileProvider),
## тайлы перезапечены заново (bake_world_ocean_tiles.py, узкий регион СЗ
## Испания, SUPERSAMPLE=8, LAND_MARGIN_KM=0.5) с зафиксированными значениями.
## Живая панель (_setup_ocean_shallow_live/_build_ocean_shallow_panel) НЕ
## удалена по прямой просьбе пользователя — играться с ней и дальше, поверх
## уже запечённой заливки (см. z_index=50/51 у полос).
const OCEAN_FORCE_LIVE := false

## Скрыто по прямой просьбе пользователя 2026-07-12 (НЕ удалять PNG/данные,
## только не показывать) — теперь у слоя "Мировой океан" есть настоящая
## запечённая глубина на весь мир (bake_world_ocean_tiles.py, GEBCO), эта
## региональная растровая заплатка (Иберия+буфер, без LOD) стала избыточной
## и путала картинку швом на границе региона. Данные (coast_distance_field_
## iberia.png/sea_depth_raw_test_region.png) и сама функция-конструктор —
## не трогать, просто не вызывать.
const OCEAN_SHALLOW_LIVE_ENABLED := false

## Живая полоса "мелководье" поверх живого слоя "Мировой океан" (клавиша 2) —
## тот же приём, что у SeaZonesLayer (клавиша 5): шейдер читает уже готовое
## поле расстояний до берега (assets/generated/coast_distance_field_iberia.png,
## см. build_coast_distance_field.py), НЕ отдельная геометрия. Только регион
## Иберия+Балеары (там, где посчитано поле расстояний) — вне него полосы нет.
var _ocean_shallow_sprite: Sprite2D
var _ocean_shallow_material: ShaderMaterial
var _ocean_shallow_panel: VBoxContainer
const OCEAN_SHALLOW_DEFAULT_COLOR := Color("36b2dc")  # решение пользователя 2026-07-11
const OCEAN_SHALLOW_DEFAULT_LAND_MARGIN_KM := 2.0  # решение пользователя 2026-07-11
const OCEAN_SHALLOW_DEFAULT_SEA_MARGIN_KM := 15.0  # решение пользователя 2026-07-11
const OCEAN_SHALLOW_DEFAULT_EDGE_TRANSITION_KM := 12.1  # ширина плавного края полосы со стороны моря, решение пользователя 2026-07-11

## Ещё 2 уровня глубины (шельф/глубины моря) поверх слоя "Мировой океан" —
## по прямой просьбе пользователя 2026-07-11, тот же приём и те же исходные
## данные, что у SeaZonesLayer._setup_depth (клавиша 5): растр реальной
## глубины GMRT (assets/generated/sea_depth_raw_test_region.png, только
## тестовый бокс Галисии — см. scripts/tools/_preview_sea_depth.py), порог
## шельф/глубины — ползунком, цвета — своим цветовыбором каждый. НЕ связано
## с панелью слоя 5 (независимые материалы/значения, как и мелководье выше).
var _ocean_depth_sprite: Sprite2D
var _ocean_depth_material: ShaderMaterial
const OCEAN_DEPTH_DEFAULT_SHELF_COLOR := Color("009acd")             # решение пользователя 2026-07-11
const OCEAN_DEPTH_DEFAULT_MID_COLOR := Color("04588c")               # 3-й уровень градиента (склон), решение пользователя 2026-07-11
const OCEAN_DEPTH_DEFAULT_DEEP_COLOR := Color("062962")              # решение пользователя 2026-07-11
const OCEAN_DEPTH_DEFAULT_GRADIENT_GAMMA := 0.8  # решение пользователя 2026-07-11
const OCEAN_DEPTH_DEFAULT_MID_POINT := 0.7  # положение color_mid на кривой (0=шельф..1=глубины), решение пользователя 2026-07-11
const OCEAN_DEPTH_DEFAULT_SHOW_ISOBATHS := false  # решение пользователя 2026-07-11: изобаты выкл. по умолчанию, инструмент скрыт из панели
const OCEAN_DEPTH_DEFAULT_ISOBATH_INTERVAL_M := 50.0  # решение пользователя 2026-07-11
const OCEAN_DEPTH_DEFAULT_ISOBATH_COLOR := Color(1.0, 1.0, 1.0, 0.35)

## Debug-инструмент "3 уровня моря" (мелководье/шельф/глубины моря) —
## клавиша 5, см. scripts/SeaZonesLayer.gd (там подробности регионов и
## решений). Не тайловый слой — не участвует в общем механизме
## _layers/request_tile. ВАЖНО: рисуется под слоем 4 (z_index по умолчанию
## 0 у обоих спрайтов, у слоя 4 в container z_index = его индекс > 0) — по
## прямой просьбе пользователя, не менять.
var _sea_zones: SeaZonesLayer

## Индекс запечённого слоя "Провинции (Иберия, запечённый)" в _layers —
## запечённая проверка живого слоя "8" (тот же стиль — без границ, см.
## BORDER_STYLE["province"]), регион Пиренейского п-ова + Балеары, см.
## scripts/tools/bake_provinces_iberia_tiles.py. Слой "8" НЕ тронут. Клавиша 4.
var _provinces_iberia_layer_idx := -1

## Индекс слоя "Города провинций (Иберия)" — точка-маркер на главный (по
## населению) реальный город каждой провинции региона, координаты из Natural
## Earth ne_10m_populated_places, см. scripts/tools/build_province_cities_iberia.py
## -> assets/province_cities_iberia.json. Включается ВМЕСТЕ со слоем
## "Провинции (Иберия)" по клавише 4 (та же связка, что океан+реки на 2).
var _province_cities_iberia_layer_idx := -1

## Индекс слоя "Клетки (Ла-Корунья, сетка)" — черновой №2 нарезки клеток,
## прямыми линиями (равномерная сетка, обрезанная контуром провинции), БЕЗ
## волнения и БЕЗ анализа границы провинции (никакого brd_open) — по прямой
## просьбе пользователя. См. scripts/tools/build_cells_lacoruna_grid.py.
## Слой "Клетки (тест: Ла-Корунья)" (клавиша C, Voronoi) НЕ тронут. Клавиша G.
var _cells_lacoruna_grid_layer_idx := -1

func _ready() -> void:
	# Базовый слой — РЕАЛЬНЫЙ спутник Земли (онлайн-тайлы).
	var satellite := OnlineTileProvider.new()
	add_child(satellite)

	_layers = [
		{
			"name": "Спутник",
			"provider": satellite,
			"visible": true,
		},
	]

	# Границы морей/заливов/проливов (Natural Earth, статические данные,
	# без сети). Клавиша 6.
	var sea_borders := SeaBorderTileProvider.new()
	_sea_layer_idx = _layers.size()
	_layers.append({
		"name": "Моря",
		"provider": sea_borders,
		"visible": false,
	})

	# Подписи морей/океанов/проливов — не тайловый слой, см. SeaLabelsLayer.gd.
	_sea_labels = SeaLabelsLayer.new()
	_sea_labels.visible = false
	add_child(_sea_labels)
	_sea_labels.setup(sea_borders.get_labels(), camera)

	# Континенты — офлайн-препроцессинг из РЕАЛЬНЫХ данных Natural Earth
	# (страны + их атрибут CONTINENT), независимо от слоя клеток суши выше,
	# см. scripts/tools/build_continents.py и assets/continents.json.
	# Клавиша 0.
	#
	# Рендер картинки — ЗАПЕЧЁННЫЕ офлайн PNG-тайлы (см.
	# scripts/tools/bake_continents_tiles.py), а не живой scan-line рендер
	# IrregularCellProvider: несколько гигантских полигонов (Евразия и т.п.,
	# до ~5900 точек контура) делали живой рендер тайла заметно медленным.
	# continents.json остаётся источником правды для игровой ЛОГИКИ (клик,
	# принадлежность клетки к континенту и т.п.) — картинки этого не заменяют,
	# см. TODO.md.
	if DirAccess.dir_exists_absolute("res://assets/tiles_bundle/continents_baked"):
		var continents := BakedTileProvider.new("res://assets/tiles_bundle/continents_baked", MAX_Z)
		add_child(continents)
		_layers.append({
			"name": "Континенты",
			"provider": continents,
			"visible": false,
		})

	# ГЛАВНЫЙ слой суша/море — фундамент для остальных систем (клик "суша
	# или море", генерация провинций/клеток, движение юнитов и т.п., см.
	# TODO.md), не только визуализация. Независимая генерация, см.
	# scripts/tools/build_land_sea.py и assets/land_sea.json. Клавиша `-`.
	#
	# Рендер картинки — ЗАПЕЧЁННЫЕ офлайн PNG-тайлы (см.
	# scripts/tools/bake_land_sea_tiles.py), как и континенты: слитая
	# Евразия — 27830 точек контура, живой scan-line рендер заметно тормозил.
	# land_sea.json остаётся источником правды для игровой ЛОГИКИ.
	if DirAccess.dir_exists_absolute("res://assets/tiles_bundle/land_sea_baked"):
		var land_sea := BakedTileProvider.new("res://assets/tiles_bundle/land_sea_baked", MAX_Z)
		add_child(land_sea)
		_layers.append({
			"name": "Суша/Море",
			"provider": land_sea,
			"visible": false,
		})
	elif FileAccess.file_exists("res://assets/land_sea.json"):
		var land_color := PackedColorArray([Color(0.55, 0.50, 0.35, 0.6)])
		var land_sea_live := IrregularCellProvider.new("res://assets/land_sea.json",
			Color(0.10, 0.08, 0.06, 0.8), 0.6, 0.35, 0.88, land_color)
		add_child(land_sea_live)
		_layers.append({
			"name": "Суша/Море",
			"provider": land_sea_live,
			"visible": false,
		})

	# Крупные реки (Нил, Амазонка, Янцзы, Волга и т.п.) — важно для будущих
	# механик (границы/торговые пути/движение вдоль рек, см. TODO.md).
	# Независимая генерация, см. scripts/tools/build_rivers.py и
	# assets/rivers.json. Клавиша `=`.
	if FileAccess.file_exists("res://assets/rivers.json"):
		var rivers := RiverTileProvider.new("res://assets/rivers.json")
		add_child(rivers)
		_layers.append({
			"name": "Реки",
			"provider": rivers,
			"visible": false,
		})

	# РЕАЛЬНЫЕ административные единицы первого уровня (штаты/области/
	# республики — Мордовия, Галисия, любой штат США и т.п.), Natural Earth
	# ne_10m_admin_1_states_provinces — см. scripts/tools/build_provinces.py
	# и TODO.md (решение сессии: синтетические Voronoi-клетки, слой v2,
	# заменены реальными границами). Первый проход — БЕЗ нарезки/волнения,
	# просто спроецированный реальный контур. Клавиша `8`.
	if FileAccess.file_exists("res://assets/provinces.json"):
		var ps: Dictionary = BORDER_STYLE["province"]
		var provinces := IrregularCellProvider.new("res://assets/provinces.json",
			ps["color"], 0.55, 0.35, 0.88, PackedColorArray(), ps["width"],
			ps["dashed"], ps["dash_len"], ps["dash_gap"], ps["feather"],
			ps["min_half_w"], ps["raster_px"])
		add_child(provinces)
		_layers.append({
			"name": "Области (провинции)",
			"provider": provinces,
			"visible": false,
		})

	# ТЕСТ: одна провинция (Ла-Корунья) нарезана на клетки (самый нижний
	# уровень лестницы, см. УРОВНЕЙ_ТЕРРИТОРИЙ.md) — scripts/tools/build_cells_test.py
	# -> assets/cells_test.json. Проверка подхода на одном примере, ПЕРЕД тем
	# как резать так все 4039 областей. Клавиша `C`.
	if FileAccess.file_exists("res://assets/cells_test.json"):
		# ВСЕГДА живой рендер (не запечённый) — понадобился на время подбора
		# толщины/цвета границ через временный живой ползунок (2026-07-11,
		# потом убран, значения зафиксированы в BORDER_STYLE), а запечённые
		# PNG (bake_cells_test_tiles.py) статичны и к тому же вообще не рисуют
		# границ (только заливку, см. докстринг скрипта). Оставлено живым и
		# дальше — тот же провайдер отдаёт клик по клетке (get_cell_id_at).
		var cs: Dictionary = BORDER_STYLE["cell"]
		var csb: Dictionary = BORDER_STYLE["cell_boundary"]
		_cells_test_provider = IrregularCellProvider.new("res://assets/cells_test.json",
			cs["color"], 0.55, 0.55, 0.95, PackedColorArray(), cs["width"],
			cs["dashed"], cs["dash_len"], cs["dash_gap"], cs["feather"],
			cs["min_half_w"], cs["raster_px"], 8, csb)
		add_child(_cells_test_provider)
		var cells_test_visual_provider = _cells_test_provider

		_cells_test_layer_idx = _layers.size()
		_layers.append({
			"name": "Клетки (тест: Ла-Корунья)",
			"provider": cells_test_visual_provider,
			"visible": false,
			# ЯВНЫЙ z_index выше любого другого тайлового слоя (по умолчанию
			# z_index = порядковый индекс в _layers, см. _make_tile) — по
			# прямой просьбе пользователя 2026-07-11: слой "C" должен
			# рисоваться НАД слоем "4" (Провинции Иберия), а не под ним, как
			# получалось бы по обычному порядку добавления. Значение с
			# запасом (100 > любого реального числа слоёв).
			"z_index": 100,
		})
		# Игровые данные тех же клеток (id совпадает с id в cells_test.json) —
		# см. scripts/data/Cell.gd/CellCatalog.gd. Индексируем по id, чтобы по
		# клику мышью (get_cell_id_at в IrregularCellProvider.gd) сразу найти
		# нужный Cell и показать его карточку (см. _try_pick_cell/_show_cell_info).
		var test_cells := CellCatalog.load_cells("res://assets/cells_test.json")
		print("CellCatalog: загружено %d клеток (тест Ла-Корунья)" % test_cells.size())
		for c in test_cells:
			_test_cells_by_id[c.id] = c
			print("  %s (%s): %.1f км², area_factor=%.2f, settlement_factor=%.2f, rural_capacity=%.0f" %
				[c.id, c.display_name, c.area_km2, c.area_factor, c.settlement_factor, c.rural_capacity])
		_build_cell_info_label()

	# ЧЕРНОВОЙ №2: та же провинция (Ла-Корунья), но нарезка прямыми линиями
	# (равномерная сетка, обрезанная контуром провинции) — scripts/tools/
	# build_cells_lacoruna_grid.py -> assets/cells_lacoruna_grid.json. БЕЗ
	# волнения рёбер и БЕЗ brd_open (граница провинции не анализируется вообще
	# — см. докстринг скрипта). Клавиша `G`.
	if FileAccess.file_exists("res://assets/cells_lacoruna_grid.json"):
		var cg: Dictionary = BORDER_STYLE["cell"]
		# raster_px = 1024 как обычно, суперсэмплинг x8 (см. supersample в
		# IrregularCellProvider) — по прямой просьбе пользователя, чтобы убрать
		# растровый артефакт заливки на изломах реального контура провинции
		# (скан-лайн красит пиксель целиком по его центру, на резких вогнутых
		# углах контура это давало видимое при сильном приближении пятно не той
		# клетки — суперсэмплинг усредняет несколько подпикселей на пиксель).
		var cells_grid := IrregularCellProvider.new("res://assets/cells_lacoruna_grid.json",
			cg["color"], 0.55, 0.55, 0.95, PackedColorArray(), cg["width"],
			cg["dashed"], cg["dash_len"], cg["dash_gap"], cg["feather"],
			cg["min_half_w"], cg["raster_px"], 8)
		add_child(cells_grid)
		_cells_lacoruna_grid_layer_idx = _layers.size()
		_layers.append({
			"name": "Клетки (Ла-Корунья, сетка)",
			"provider": cells_grid,
			"visible": false,
		})

	# Единая маска мирового океана (БЕЗ клеток, просто "вода/не вода") —
	# scripts/tools/build_world_ocean.py -> assets/world_ocean.json. Считана
	# от provinces.json (основополагающий слой суши, см. память проекта), с
	# буфером на щели между провинциями (тот же приём, что в
	# generate_sea_cells.py/load_land_pieces). Клавиша `2` (не `O` — буква O
	# и цифра 0 у соседнего слоя "Континенты" визуально путаются); при включении
	# заодно включает слой "Реки" (см. _unhandled_input) — по просьбе
	# пользователя показывать всю воду (океан+реки) сразу, одной клавишей.
	# Живой рендер (IrregularCellProvider) на гигантском полигоне мирового
	# океана (34155 точек в одном куске) тормозит и даёт мыльный/пиксельный
	# берег, пока фоновый рендер тайла не досчитается (тот же класс проблемы,
	# что у "Континентов"/"Суша-Море" — см. их комментарии ниже). Печём
	# заранее, см. scripts/tools/bake_world_ocean_tiles.py. ТЕСТОВЫЙ прогон
	# по умолчанию печёт только регион (Северо-Запад Иберии) — вне него
	# BakedTileProvider покажет пусто, это ожидаемо, полный мир — отдельным
	# прогоном с --full, когда результат устроит.
	if not OCEAN_FORCE_LIVE and DirAccess.dir_exists_absolute("res://assets/tiles_bundle/world_ocean_baked"):
		var ocean_baked := BakedTileProvider.new("res://assets/tiles_bundle/world_ocean_baked", MAX_Z)
		add_child(ocean_baked)
		_ocean_layer_idx = _layers.size()
		_layers.append({
			"name": "Мировой океан",
			"provider": ocean_baked,
			"visible": false,
		})
		# Живая полоса мелководья/шельфа/глубин (ползунки) — НЕЗАВИСИМА от
		# того, чем рисуется сама заливка океана (запечённой или живой), см.
		# комментарий у OCEAN_FORCE_LIVE выше. Оставлена по прямой просьбе
		# пользователя 2026-07-11.
		if OCEAN_SHALLOW_LIVE_ENABLED:
			_setup_ocean_shallow_live()
	elif FileAccess.file_exists("res://assets/world_ocean.json"):
		var ocean_color := PackedColorArray([Color(0.20, 0.55, 0.85, 0.55)])
		# ВИДИМАЯ обводка контура (не alpha=0) — именно она даёт ГЛАДКИЙ берег.
		# Заливка (_fill_polygon) рисуется без сглаживания (скан-линия,
		# округление края до целого пикселя -> "лесенка"), а обводка
		# (_render, border_feather) — с настоящим феатером/градиентом. У
		# провинций гладкий берег именно из-за их тёмной обводки; у океана
		# раньше обводка была прозрачной (alpha=0) -> была видна голая
		# пиксельная заливка. Цвет обводки — чуть темнее заливки (не резко
		# чёрный как у провинций), border_feather=2.0 для мягкого края.
		var ocean := IrregularCellProvider.new("res://assets/world_ocean.json",
			Color(0.10, 0.35, 0.60, 0.85), 0.55, 0.35, 0.88, ocean_color,
			1.0, false, 0.5, 0.35, 2.0, 0.5, 1024)
		add_child(ocean)
		_ocean_layer_idx = _layers.size()
		_layers.append({
			"name": "Мировой океан",
			"provider": ocean,
			"visible": false,
		})
		if OCEAN_SHALLOW_LIVE_ENABLED:
			_setup_ocean_shallow_live()

	# Провинции региона Иберия — сравнение с живым слоем "8". СНОВА живой
	# (2026-07-12, по прямой просьбе пользователя) — bake_provinces_iberia_tiles.py
	# по умолчанию печёт только узкий тестовый регион СЗ Испании (тот же, что
	# у слоя "2"), а не всю Иберию, поэтому запечённые тайлы не покрывали бы
	# южные провинции (Севилья/Кадис/Уэльва после ручной правки границы, см.
	# scripts/tools/patch_sevilla_coastal_access.py) — перепекать под полный
	# регион дороже, чем просто рисовать живым рендером. Данные — ОБРЕЗАННАЯ
	# копия региона (assets/provinces_iberia.json, см.
	# scripts/tools/build_provinces_iberia.py) — иначе слой "4" рисовал бы
	# ВЕСЬ мир и дублировал живой слой "8" (найдено пользователем в сессии).
	const PROVINCES_IBERIA_FORCE_LIVE := true
	if not PROVINCES_IBERIA_FORCE_LIVE and DirAccess.dir_exists_absolute("res://assets/tiles_bundle/provinces_iberia_baked"):
		var provinces_iberia := BakedTileProvider.new("res://assets/tiles_bundle/provinces_iberia_baked", MAX_Z)
		add_child(provinces_iberia)
		_provinces_iberia_layer_idx = _layers.size()
		_layers.append({
			"name": "Провинции (Иберия, запечённый)",
			"provider": provinces_iberia,
			"visible": false,
		})
	elif PROVINCES_IBERIA_FORCE_LIVE and FileAccess.file_exists("res://assets/provinces_iberia.json"):
		var ps4: Dictionary = BORDER_STYLE["province"]
		var provinces_iberia_live := IrregularCellProvider.new("res://assets/provinces_iberia.json",
			ps4["color"], 0.55, 0.35, 0.88, PackedColorArray(), ps4["width"],
			ps4["dashed"], ps4["dash_len"], ps4["dash_gap"], ps4["feather"],
			ps4["min_half_w"], ps4["raster_px"])
		add_child(provinces_iberia_live)
		_provinces_iberia_layer_idx = _layers.size()
		_layers.append({
			"name": "Провинции (Иберия, живой ВРЕМЕННО)",
			"provider": provinces_iberia_live,
			"visible": false,
		})

	# Главный город каждой провинции (реальное историческое место, не центр
	# полигона) — см. build_province_cities_iberia.py. z_index с запасом
	# (выше провинций/клеток), чтобы точка города не пряталась под заливкой.
	if FileAccess.file_exists("res://assets/province_cities_iberia.json"):
		var province_city_markers := ProvinceCityMarkerProvider.new("res://assets/province_cities_iberia.json")
		add_child(province_city_markers)
		_province_cities_iberia_layer_idx = _layers.size()
		_layers.append({
			"name": "Города провинций (Иберия)",
			"provider": province_city_markers,
			"visible": false,
			"z_index": 90,
		})

		# Подписи имён городов рядом с маркерами — НЕ тайловый слой (та же
		# причина, что у SeaLabelsLayer: подписей мало, ~100 на регион),
		# показываются/прячутся вместе со слоем "Города провинций".
		# Подпись ПОД кругом маркера, не поверх него: радиус круга (в
		# "тайловых" px маркера) + небольшой зазор — тот же порядок величины,
		# что и font_size у SeaLabelNode, поэтому визуально уместно как
		# сдвиг в её локальных экранных единицах (см. SeaLabelNode.offset_y).
		var city_label_offset_y := ProvinceCityMarkerProvider.MARKER_PX * 0.5 + 6.0
		var city_labels: Array = []
		for marker in province_city_markers.get_markers():
			city_labels.append({
				"name": marker["name"],
				"pos": marker["pos"],
				"offset_y": city_label_offset_y,
			})
		_province_city_labels = SeaLabelsLayer.new()
		_province_city_labels.visible = false
		add_child(_province_city_labels)
		_province_city_labels.setup(city_labels, camera)

	if camera.has_method("set_map_bounds"):
		camera.set_map_bounds(Rect2(
			Vector2(0.0, NORTH_CUTOFF_Y),
			Vector2(WORLD_PX, SOUTH_CUTOFF_Y - NORTH_CUTOFF_Y)))

	# Полноценная маска полюсов (не полагаемся ТОЛЬКО на выбор тайлов): на
	# сильном отдалении ("вписать всю карту", R) один тайл может покрывать
	# сразу и видимую полосу, и Антарктиду/Арктику — тогда фильтрация по
	# тайлам не спасает. Эти прямоугольники рисуются ПОВЕРХ всех слоёв
	# (z_index заведомо больше любого слоя) и гарантированно скрывают то,
	# что южнее/севернее разрешённой полосы, чем бы оно ни было нарисовано.
	_add_polar_mask(-WORLD_PX, NORTH_CUTOFF_Y)
	_add_polar_mask(SOUTH_CUTOFF_Y, WORLD_PX * 2.0)

	# Фоновая предзагрузка всех тайлов спутникового слоя на диск.
	var preloader := TilePreloader.new()
	add_child(preloader)
	preloader.setup([satellite], PRELOAD_MAX_Z)

	# Разметка карты кликами (клавиша M) — см. scripts/MarkTool.gd.
	_mark_tool = MarkTool.new()
	add_child(_mark_tool)
	_mark_tool.setup(camera, $UI)

	# Debug-инструмент "3 уровня моря" (клавиша 5) — см. комментарий у
	# объявления поля выше.
	_sea_zones = SeaZonesLayer.new()
	# Явно ниже любого тайлового слоя (z_index=layer_idx у них, минимум 0) —
	# гарантия, что слой 5 рисуется ПОД слоями 2/4, а не полагается на
	# умолчание. По просьбе пользователя 2026-07-10.
	_sea_zones.z_index = -1
	add_child(_sea_zones)
	_sea_zones.setup($UI)
	_sea_zones.set_active(false)


## Полоса мелководья поверх живого слоя "Мировой океан" (см. поля выше) —
## тот же шейдер/текстура, что у SeaZonesLayer, отдельный экземпляр материала
## (независимая правка цвета, не завязана на панель слоя 5). Если поля
## расстояний нет (build_coast_distance_field.py не прогонялся) — тихо ничего
## не делает, слой "Мировой океан" остаётся без полосы, как раньше.
func _setup_ocean_shallow_live() -> void:
	const SHALLOW_IMG_PATH := "res://assets/generated/coast_distance_field_iberia.png"
	const SHALLOW_BBOX_PATH := "res://assets/generated/coast_distance_field_iberia_bbox.json"
	const SHALLOW_SHADER_PATH := "res://scripts/shaders/shallow_water_band.gdshader"

	if not (FileAccess.file_exists(SHALLOW_IMG_PATH) and FileAccess.file_exists(SHALLOW_BBOX_PATH)):
		return
	var bbox_text := FileAccess.get_file_as_string(SHALLOW_BBOX_PATH)
	var bbox: Dictionary = JSON.parse_string(bbox_text)
	if bbox == null:
		return
	var img := Image.new()
	if img.load(SHALLOW_IMG_PATH) != OK:
		return
	var tex := ImageTexture.create_from_image(img)

	_ocean_shallow_material = ShaderMaterial.new()
	_ocean_shallow_material.shader = load(SHALLOW_SHADER_PATH)
	_ocean_shallow_material.set_shader_parameter("encode_min_km", float(bbox["encode_min_km"]))
	_ocean_shallow_material.set_shader_parameter("encode_max_km", float(bbox["encode_max_km"]))
	_ocean_shallow_material.set_shader_parameter("land_margin_km", OCEAN_SHALLOW_DEFAULT_LAND_MARGIN_KM)
	_ocean_shallow_material.set_shader_parameter("sea_margin_km", OCEAN_SHALLOW_DEFAULT_SEA_MARGIN_KM)
	_ocean_shallow_material.set_shader_parameter("edge_transition_km", OCEAN_SHALLOW_DEFAULT_EDGE_TRANSITION_KM)
	_ocean_shallow_material.set_shader_parameter("band_color", OCEAN_SHALLOW_DEFAULT_COLOR)

	_ocean_shallow_sprite = Sprite2D.new()
	_ocean_shallow_sprite.texture = tex
	_ocean_shallow_sprite.material = _ocean_shallow_material
	_ocean_shallow_sprite.centered = false
	# NEAREST — те же соображения, что в SeaZonesLayer._setup_shallow (16 бит
	# расстояния разбиты на 2 канала, LINEAR даёт мусор на границе байтов).
	_ocean_shallow_sprite.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	_ocean_shallow_sprite.position = Vector2(bbox["x0"], bbox["y0"])
	var world_w: float = bbox["x1"] - bbox["x0"]
	var world_h: float = bbox["y1"] - bbox["y0"]
	_ocean_shallow_sprite.scale = Vector2(world_w / tex.get_width(), world_h / tex.get_height())
	# ЯВНО выше тайлов океана (у них z_index = li ≈ индекс слоя "2" в _layers,
	# обычно 8-10) — иначе полупрозрачная заливка океана рисуется ПОВЕРХ этой
	# полосы, и правки цвета/ширины почти не видны сквозь неё (найдено
	# пользователем в сессии 2026-07-11: "кручу шельф — ничего не
	# происходит"). Числа с запасом, но МЕНЬШЕ z_index=100 у слоя "C" — тот
	# должен оставаться выше всего.
	_ocean_shallow_sprite.z_index = 51
	_ocean_shallow_sprite.visible = false
	add_child(_ocean_shallow_sprite)

	_setup_ocean_depth_live()
	_build_ocean_shallow_panel()


## Живая раскраска "шельф/глубины моря" поверх слоя "Мировой океан" — см.
## поля _ocean_depth_* выше. Тот же файл растра глубины, что у SeaZonesLayer
## (клавиша 5), НЕЗАВИСИМЫЙ материал/значения. Тихо ничего не делает, если
## растра глубины нет (_preview_sea_depth.py не прогонялся).
func _setup_ocean_depth_live() -> void:
	const DEPTH_IMG_PATH := "res://assets/generated/sea_depth_raw_test_region.png"
	const DEPTH_BBOX_PATH := "res://assets/generated/sea_depth_raw_test_region_bbox.json"
	const DEPTH_SHADER_PATH := "res://scripts/shaders/sea_depth_zones.gdshader"

	if not (FileAccess.file_exists(DEPTH_IMG_PATH) and FileAccess.file_exists(DEPTH_BBOX_PATH)):
		return
	var bbox_text := FileAccess.get_file_as_string(DEPTH_BBOX_PATH)
	var bbox: Dictionary = JSON.parse_string(bbox_text)
	if bbox == null:
		return
	var img := Image.new()
	if img.load(DEPTH_IMG_PATH) != OK:
		return
	var tex := ImageTexture.create_from_image(img)

	_ocean_depth_material = ShaderMaterial.new()
	_ocean_depth_material.shader = load(DEPTH_SHADER_PATH)
	_ocean_depth_material.set_shader_parameter("max_depth_m", float(bbox["max_depth_m"]))
	_ocean_depth_material.set_shader_parameter("color_shelf", OCEAN_DEPTH_DEFAULT_SHELF_COLOR)
	_ocean_depth_material.set_shader_parameter("color_mid", OCEAN_DEPTH_DEFAULT_MID_COLOR)
	_ocean_depth_material.set_shader_parameter("color_deep", OCEAN_DEPTH_DEFAULT_DEEP_COLOR)
	_ocean_depth_material.set_shader_parameter("gradient_gamma", OCEAN_DEPTH_DEFAULT_GRADIENT_GAMMA)
	_ocean_depth_material.set_shader_parameter("mid_point", OCEAN_DEPTH_DEFAULT_MID_POINT)
	_ocean_depth_material.set_shader_parameter("show_isobaths", OCEAN_DEPTH_DEFAULT_SHOW_ISOBATHS)
	_ocean_depth_material.set_shader_parameter("isobath_interval_m", OCEAN_DEPTH_DEFAULT_ISOBATH_INTERVAL_M)
	_ocean_depth_material.set_shader_parameter("isobath_color", OCEAN_DEPTH_DEFAULT_ISOBATH_COLOR)

	_ocean_depth_sprite = Sprite2D.new()
	_ocean_depth_sprite.texture = tex
	_ocean_depth_sprite.material = _ocean_depth_material
	_ocean_depth_sprite.centered = false
	_ocean_depth_sprite.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	_ocean_depth_sprite.position = Vector2(bbox["x0"], bbox["y0"])
	var world_w: float = bbox["x1"] - bbox["x0"]
	var world_h: float = bbox["y1"] - bbox["y0"]
	_ocean_depth_sprite.scale = Vector2(world_w / tex.get_width(), world_h / tex.get_height())
	# ЯВНО выше тайлов океана (та же причина, что у _ocean_shallow_sprite.z_index
	# выше — иначе заливка океана перекрывает и правки не видны), но НИЖЕ
	# мелководья (z_index=51) — мелководье фиксированной ширины у берега
	# должно перекрывать шельф/глубины там, где полосы пересекаются, как и у
	# слоя 5 (SeaZonesLayer: тот же порядок между двумя своими спрайтами).
	_ocean_depth_sprite.z_index = 50
	_ocean_depth_sprite.visible = false
	add_child(_ocean_depth_sprite)


## Панель "Мелководье (слой 2)" — цвет + два ползунка ширины полосы, тот же
## приём (ColorPickerButton/HSlider поверх ShaderMaterial), что у панели
## SeaZonesLayer (клавиша 5), но НЕЗАВИСИМАЯ панель под КЛАВИШУ 2 — по прямой
## просьбе пользователя ("возьми этот инструмент... для слоя 2").
func _build_ocean_shallow_panel() -> void:
	_ocean_shallow_panel = VBoxContainer.new()
	_ocean_shallow_panel.offset_left = 1440.0
	_ocean_shallow_panel.offset_top = 220.0
	_ocean_shallow_panel.offset_right = 1896.0
	_ocean_shallow_panel.offset_bottom = 760.0
	_ocean_shallow_panel.visible = false
	$UI.add_child(_ocean_shallow_panel)

	var title := Label.new()
	title.add_theme_color_override("font_color", Color(1, 1, 1))
	title.text = "Мелководье (слой 2)"
	_ocean_shallow_panel.add_child(title)

	var color_row := HBoxContainer.new()
	var color_label := Label.new()
	color_label.custom_minimum_size = Vector2(280, 0)
	color_label.add_theme_color_override("font_color", Color(1, 1, 1))
	color_label.text = "Цвет"
	var color_picker := ColorPickerButton.new()
	color_picker.color = OCEAN_SHALLOW_DEFAULT_COLOR
	color_picker.custom_minimum_size = Vector2(80, 24)
	color_picker.color_changed.connect(func(color: Color) -> void:
		if _ocean_shallow_material:
			_ocean_shallow_material.set_shader_parameter("band_color", color)
	)
	color_row.add_child(color_label)
	color_row.add_child(color_picker)
	_ocean_shallow_panel.add_child(color_row)

	var land_row := HBoxContainer.new()
	var land_label := Label.new()
	land_label.custom_minimum_size = Vector2(280, 0)
	land_label.add_theme_color_override("font_color", Color(1, 1, 1))
	land_label.text = "Заход на сушу: %.1f км" % OCEAN_SHALLOW_DEFAULT_LAND_MARGIN_KM
	var land_slider := HSlider.new()
	land_slider.min_value = 0.0
	land_slider.max_value = 5.0
	land_slider.step = 0.1
	land_slider.value = OCEAN_SHALLOW_DEFAULT_LAND_MARGIN_KM
	land_slider.custom_minimum_size = Vector2(220, 0)
	land_slider.value_changed.connect(func(value: float) -> void:
		if _ocean_shallow_material:
			_ocean_shallow_material.set_shader_parameter("land_margin_km", value)
		land_label.text = "Заход на сушу: %.1f км" % value
	)
	land_row.add_child(land_label)
	land_row.add_child(land_slider)
	_ocean_shallow_panel.add_child(land_row)

	var sea_row := HBoxContainer.new()
	var sea_label := Label.new()
	sea_label.custom_minimum_size = Vector2(280, 0)
	sea_label.add_theme_color_override("font_color", Color(1, 1, 1))
	sea_label.text = "Ширина в море: %.1f км" % OCEAN_SHALLOW_DEFAULT_SEA_MARGIN_KM
	var sea_slider := HSlider.new()
	sea_slider.min_value = 0.0
	sea_slider.max_value = 40.0
	sea_slider.step = 0.5
	sea_slider.value = OCEAN_SHALLOW_DEFAULT_SEA_MARGIN_KM
	sea_slider.custom_minimum_size = Vector2(220, 0)
	sea_slider.value_changed.connect(func(value: float) -> void:
		if _ocean_shallow_material:
			_ocean_shallow_material.set_shader_parameter("sea_margin_km", value)
		sea_label.text = "Ширина в море: %.1f км" % value
	)
	sea_row.add_child(sea_label)
	sea_row.add_child(sea_slider)
	_ocean_shallow_panel.add_child(sea_row)

	var edge_row := HBoxContainer.new()
	var edge_label := Label.new()
	edge_label.custom_minimum_size = Vector2(280, 0)
	edge_label.add_theme_color_override("font_color", Color(1, 1, 1))
	edge_label.text = "Плавность края (море): %.1f км" % OCEAN_SHALLOW_DEFAULT_EDGE_TRANSITION_KM
	var edge_slider := HSlider.new()
	edge_slider.min_value = 0.0
	edge_slider.max_value = 100.0
	edge_slider.step = 0.1
	edge_slider.value = OCEAN_SHALLOW_DEFAULT_EDGE_TRANSITION_KM
	edge_slider.custom_minimum_size = Vector2(220, 0)
	edge_slider.value_changed.connect(func(value: float) -> void:
		if _ocean_shallow_material:
			_ocean_shallow_material.set_shader_parameter("edge_transition_km", value)
		edge_label.text = "Плавность края (море): %.1f км" % value
	)
	edge_row.add_child(edge_label)
	edge_row.add_child(edge_slider)
	_ocean_shallow_panel.add_child(edge_row)

	# Шельф/глубины моря — 2 доп. уровня глубины, тот же приём, что у панели
	# слоя 5 (SeaZonesLayer._build_panel), но НЕЗАВИСИМЫЕ значения/материал
	# (_ocean_depth_material), по прямой просьбе пользователя 2026-07-11.
	var depth_title := Label.new()
	depth_title.add_theme_color_override("font_color", Color(1, 1, 1))
	depth_title.text = "Шельф / Глубины моря"
	_ocean_shallow_panel.add_child(depth_title)

	var shelf_color_row := HBoxContainer.new()
	var shelf_color_label := Label.new()
	shelf_color_label.custom_minimum_size = Vector2(280, 0)
	shelf_color_label.add_theme_color_override("font_color", Color(1, 1, 1))
	shelf_color_label.text = "Цвет: Шельф"
	var shelf_color_picker := ColorPickerButton.new()
	shelf_color_picker.color = OCEAN_DEPTH_DEFAULT_SHELF_COLOR
	shelf_color_picker.custom_minimum_size = Vector2(80, 24)
	shelf_color_picker.color_changed.connect(func(color: Color) -> void:
		if _ocean_depth_material:
			_ocean_depth_material.set_shader_parameter("color_shelf", color)
	)
	shelf_color_row.add_child(shelf_color_label)
	shelf_color_row.add_child(shelf_color_picker)
	_ocean_shallow_panel.add_child(shelf_color_row)

	var gamma_row := HBoxContainer.new()
	var gamma_label := Label.new()
	gamma_label.custom_minimum_size = Vector2(280, 0)
	gamma_label.add_theme_color_override("font_color", Color(1, 1, 1))
	gamma_label.text = "Кривизна градиента: %.2f" % OCEAN_DEPTH_DEFAULT_GRADIENT_GAMMA
	var gamma_slider := HSlider.new()
	gamma_slider.min_value = 0.05
	gamma_slider.max_value = 3.0
	gamma_slider.step = 0.05
	gamma_slider.value = OCEAN_DEPTH_DEFAULT_GRADIENT_GAMMA
	gamma_slider.custom_minimum_size = Vector2(220, 0)
	gamma_slider.value_changed.connect(func(value: float) -> void:
		if _ocean_depth_material:
			_ocean_depth_material.set_shader_parameter("gradient_gamma", value)
		gamma_label.text = "Кривизна градиента: %.2f" % value
	)
	gamma_row.add_child(gamma_label)
	gamma_row.add_child(gamma_slider)
	_ocean_shallow_panel.add_child(gamma_row)

	var mid_color_row := HBoxContainer.new()
	var mid_color_label := Label.new()
	mid_color_label.custom_minimum_size = Vector2(280, 0)
	mid_color_label.add_theme_color_override("font_color", Color(1, 1, 1))
	mid_color_label.text = "Цвет: Склон (3-й уровень)"
	var mid_color_picker := ColorPickerButton.new()
	mid_color_picker.color = OCEAN_DEPTH_DEFAULT_MID_COLOR
	mid_color_picker.custom_minimum_size = Vector2(80, 24)
	mid_color_picker.color_changed.connect(func(color: Color) -> void:
		if _ocean_depth_material:
			_ocean_depth_material.set_shader_parameter("color_mid", color)
	)
	mid_color_row.add_child(mid_color_label)
	mid_color_row.add_child(mid_color_picker)
	_ocean_shallow_panel.add_child(mid_color_row)

	var mid_point_row := HBoxContainer.new()
	var mid_point_label := Label.new()
	mid_point_label.custom_minimum_size = Vector2(280, 0)
	mid_point_label.add_theme_color_override("font_color", Color(1, 1, 1))
	mid_point_label.text = "Положение склона: %.2f" % OCEAN_DEPTH_DEFAULT_MID_POINT
	var mid_point_slider := HSlider.new()
	mid_point_slider.min_value = 0.01
	mid_point_slider.max_value = 0.99
	mid_point_slider.step = 0.01
	mid_point_slider.value = OCEAN_DEPTH_DEFAULT_MID_POINT
	mid_point_slider.custom_minimum_size = Vector2(220, 0)
	mid_point_slider.value_changed.connect(func(value: float) -> void:
		if _ocean_depth_material:
			_ocean_depth_material.set_shader_parameter("mid_point", value)
		mid_point_label.text = "Положение склона: %.2f" % value
	)
	mid_point_row.add_child(mid_point_label)
	mid_point_row.add_child(mid_point_slider)
	_ocean_shallow_panel.add_child(mid_point_row)

	var deep_color_row := HBoxContainer.new()
	var deep_color_label := Label.new()
	deep_color_label.custom_minimum_size = Vector2(280, 0)
	deep_color_label.add_theme_color_override("font_color", Color(1, 1, 1))
	deep_color_label.text = "Цвет: Глубины моря"
	var deep_color_picker := ColorPickerButton.new()
	deep_color_picker.color = OCEAN_DEPTH_DEFAULT_DEEP_COLOR
	deep_color_picker.custom_minimum_size = Vector2(80, 24)
	deep_color_picker.color_changed.connect(func(color: Color) -> void:
		if _ocean_depth_material:
			_ocean_depth_material.set_shader_parameter("color_deep", color)
	)
	deep_color_row.add_child(deep_color_label)
	deep_color_row.add_child(deep_color_picker)
	_ocean_shallow_panel.add_child(deep_color_row)

	var isobaths_row := HBoxContainer.new()
	var isobaths_check := CheckBox.new()
	isobaths_check.text = "Изобаты"
	isobaths_check.add_theme_color_override("font_color", Color(1, 1, 1))
	isobaths_check.button_pressed = OCEAN_DEPTH_DEFAULT_SHOW_ISOBATHS
	isobaths_check.toggled.connect(func(pressed: bool) -> void:
		if _ocean_depth_material:
			_ocean_depth_material.set_shader_parameter("show_isobaths", pressed)
	)
	isobaths_row.add_child(isobaths_check)
	isobaths_row.visible = false  # инструмент изобат скрыт из панели по прямой просьбе пользователя 2026-07-11
	_ocean_shallow_panel.add_child(isobaths_row)

	var isobath_interval_row := HBoxContainer.new()
	var isobath_interval_label := Label.new()
	isobath_interval_label.custom_minimum_size = Vector2(280, 0)
	isobath_interval_label.add_theme_color_override("font_color", Color(1, 1, 1))
	isobath_interval_label.text = "Шаг изобат: %d м" % int(OCEAN_DEPTH_DEFAULT_ISOBATH_INTERVAL_M)
	var isobath_interval_slider := HSlider.new()
	isobath_interval_slider.min_value = 50.0
	isobath_interval_slider.max_value = 2000.0
	isobath_interval_slider.step = 10.0
	isobath_interval_slider.value = OCEAN_DEPTH_DEFAULT_ISOBATH_INTERVAL_M
	isobath_interval_slider.custom_minimum_size = Vector2(220, 0)
	isobath_interval_slider.value_changed.connect(func(value: float) -> void:
		if _ocean_depth_material:
			_ocean_depth_material.set_shader_parameter("isobath_interval_m", value)
		isobath_interval_label.text = "Шаг изобат: %d м" % int(value)
	)
	isobath_interval_row.add_child(isobath_interval_label)
	isobath_interval_row.add_child(isobath_interval_slider)
	isobath_interval_row.visible = false  # инструмент изобат скрыт из панели по прямой просьбе пользователя 2026-07-11
	_ocean_shallow_panel.add_child(isobath_interval_row)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		var idx := -1
		# physical_keycode (не keycode!) — тот же баг раскладки, что и с WASD
		# (см. TODO.md): keycode зависит от активной раскладки клавиатуры,
		# на русской "=" может давать другой логический код.
		# КЛЮЧ 3, O СВОБОДНЫ — были у удалённых слоёв: "Клетки"/
		# CellTileProvider, "Клетки суши (неровные)"/land_cells.json
		# (заменены реальной геогеометрией provinces.json/land_sea.json), и
		# "Политический"/"Экономический"/"Религиозный" (процедурные
		# заглушки на PhysicalTileProvider/OverlayTileProvider — удалены
		# по решению пользователя, TODO.md годами просил заменить их
		# реальными данными провинций, до реализации не дошло, см. done.md).
		# 4/5 больше НЕ свободны — заняты слоями "Провинции (Иберия)" и
		# "3 уровня моря" (мелководье/шельф/глубины). 7 снова СВОБОДЕН —
		# мелководье объединено с батиметрией под одну клавишу 5.
		# "Мировой океан" НЕ на клавише O — буква O и цифра 0 (соседняя
		# клавиша "Континенты") визуально неотличимы, легко перепутать.
		match event.physical_keycode:
			KEY_1: idx = 0
			KEY_6: idx = 1
			KEY_0: idx = 2
			KEY_MINUS: idx = 3
			KEY_EQUAL: idx = 4
			KEY_8: idx = 5
			KEY_C: idx = 6
			KEY_2: idx = _ocean_layer_idx
			KEY_4: idx = _provinces_iberia_layer_idx
			KEY_G: idx = _cells_lacoruna_grid_layer_idx
		if event.physical_keycode == KEY_5 and is_instance_valid(_sea_zones):
			_sea_zones.set_active(not _sea_zones.visible)
		if idx >= 0 and idx < _layers.size():
			_layers[idx]["visible"] = not _layers[idx]["visible"]
			# "Мировой океан" при включении заодно включает "Реки" (индекс 4,
			# см. KEY_EQUAL выше) — по просьбе пользователя показывать всю
			# воду (океан+реки) сразу одной клавишей, а не двумя отдельными.
			if idx == _ocean_layer_idx and 4 < _layers.size():
				_layers[4]["visible"] = _layers[idx]["visible"]
			# "Провинции (Иберия)" при включении заодно включает "Города
			# провинций (Иберия)" — та же связка, что океан+реки выше.
			if idx == _provinces_iberia_layer_idx and _province_cities_iberia_layer_idx >= 0 \
					and _province_cities_iberia_layer_idx < _layers.size():
				_layers[_province_cities_iberia_layer_idx]["visible"] = _layers[idx]["visible"]

	# Клик по клетке (тест: Ла-Корунья) — только пока слой включён и только
	# пока MarkTool не активен (иначе ЛКМ уже занята им, см. MarkTool.gd).
	if event is InputEventMouseButton and event.pressed \
			and event.button_index == MOUSE_BUTTON_LEFT \
			and not (is_instance_valid(_mark_tool) and _mark_tool.active) \
			and _cells_test_layer_idx >= 0 and _cells_test_layer_idx < _layers.size() \
			and _layers[_cells_test_layer_idx]["visible"] \
			and is_instance_valid(camera):
		_try_pick_cell(camera.get_global_mouse_position())


func _try_pick_cell(world_pos: Vector2) -> void:
	if not is_instance_valid(_cells_test_provider):
		return
	var cell_id := _cells_test_provider.get_cell_id_at(world_pos)
	if cell_id.is_empty() or not _test_cells_by_id.has(cell_id):
		return
	var cell: Cell = _test_cells_by_id[cell_id]
	_show_cell_info(cell)


func _build_cell_info_label() -> void:
	_cell_info_label = Label.new()
	_cell_info_label.offset_left = 1400.0
	_cell_info_label.offset_top = 24.0
	_cell_info_label.offset_right = 1900.0
	_cell_info_label.offset_bottom = 520.0
	_cell_info_label.add_theme_color_override("font_color", Color(0.95, 0.95, 0.85, 1))
	_cell_info_label.add_theme_font_size_override("font_size", 16)
	_cell_info_label.autowrap_mode = TextServer.AUTOWRAP_WORD
	_cell_info_label.visible = false
	$UI.add_child(_cell_info_label)


## Карточка клетки — рендерит to_display_dict() (Cell.gd) текстом. UI здесь
## только форматирует уже готовый ViewModel, ничего сам не считает (см.
## CLAUDE.md: "UI получает готовые ViewModel", а не сырые данные).
func _show_cell_info(cell: Cell) -> void:
	var d := cell.to_display_dict()
	var nature: Dictionary = d["nature"]
	var dev: Dictionary = d["development"]
	var pop: Dictionary = d["population"]
	var infra: Dictionary = d["infrastructure"]
	var area: Dictionary = d["area"]
	var factors: Dictionary = d["factors"]
	var features_str := ", ".join(nature["features"]) if not nature["features"].is_empty() else "—"
	var resource_str: String = d["resource"] if not String(d["resource"]).is_empty() else "—"
	_cell_info_label.text = (
		"[%s] %s\n" +
		"Площадь: %.1f км²  (area_factor=%.2f)\n" +
		"Природа: %s / %s / почва %s / %s, %s\n" +
		"Особенности: %s   Ресурс: %s\n" +
		"Освоение: %s (ур. %d)  зрелость=%.0f%%  повреждение=%.0f%%\n" +
		"Население: %d / ёмкость %.0f\n" +
		"Дороги: %d   Ирригация: %d\n" +
		"settlement_factor=%.2f  usable_land_factor=%.2f") % [
		d["id"], d["name"],
		area["area_km2"], area["area_factor"],
		nature["relief"], nature["cover"], nature["soil"], nature["climate"], nature["moisture"],
		features_str, resource_str,
		dev["type"], dev["level"], dev["maturity"] * 100.0, dev["damage"] * 100.0,
		pop["rural_population"], pop["rural_capacity"],
		infra["road_level"], infra["irrigation_level"],
		factors["settlement_factor"], factors["usable_land_factor"],
	]
	_cell_info_label.visible = true


func _process(_delta: float) -> void:
	if not is_instance_valid(camera):
		return

	if _sea_layer_idx >= 0 and is_instance_valid(_sea_labels):
		_sea_labels.visible = _layers[_sea_layer_idx]["visible"]

	if _province_cities_iberia_layer_idx >= 0 and is_instance_valid(_province_city_labels):
		_province_city_labels.visible = _layers[_province_cities_iberia_layer_idx]["visible"]


	# Полоса мелководья + панель настройки — не тайловый слой (не в _layers/
	# request_tile), синхронизируем видимость с флагом слоя "Мировой океан"
	# вручную, тем же приёмом, что и у подписей морей выше.
	if _ocean_layer_idx >= 0 and is_instance_valid(_ocean_shallow_sprite):
		var ocean_visible: bool = _layers[_ocean_layer_idx]["visible"]
		_ocean_shallow_sprite.visible = ocean_visible
		# ЗАБЫЛ синхронизировать это раньше (2026-07-11) — полоса шельфа/
		# глубин создавалась с visible=false и так и оставалась скрытой
		# навсегда, даже при включённом слое "2" — отсюда "кручу шельф,
		# ничего не происходит" (материал/сигналы работали правильно, но
		# сам спрайт нечего было показывать).
		if is_instance_valid(_ocean_depth_sprite):
			_ocean_depth_sprite.visible = ocean_visible
		if is_instance_valid(_ocean_shallow_panel):
			_ocean_shallow_panel.visible = ocean_visible

	var cam_zoom: float = camera.zoom.x
	# Выбор уровня детализации: чтобы тайл на экране был ~TILE_PX.
	# Считаем от ЦЕЛЕВОГО зума (куда едет камера), а не от промежуточного
	# сглаженного значения — иначе за одну прокрутку колеса LOD успевает
	# переключиться несколько раз. Плюс гистерезис на границе уровней.
	var lod_zoom: float = camera.get_target_zoom() if camera.has_method("get_target_zoom") else cam_zoom
	var lod_f := log(WORLD_PX * lod_zoom / TILE_PX) / log(2.0)
	if _lod < 0 or absf(lod_f - float(_lod)) > 0.5 + LOD_HYSTERESIS:
		_lod = clampi(int(round(lod_f)), MIN_Z, MAX_Z)
	var lod := _lod
	var n := 1 << lod
	var tile_world := float(WORLD_PX) / n

	# Видимый прямоугольник мира.
	var view: Vector2 = get_viewport_rect().size / cam_zoom
	var top_left: Vector2 = camera.position - view * 0.5
	# Жёсткий клип строк тайлов по широте (Антарктида/Арктика) — НЕ полагаемся
	# только на ограничение позиции камеры: если соотношение сторон окна не
	# совпадает с обрезанной картой, "вписать всю карту" (R) может показать на
	# несколько пикселей больше по вертикали, чем разрешено, и тонкая полоска
	# полюса просачивается. Тут отсекаем гарантированно, на уровне тайлов.
	var row_north := clampi(int(floor(NORTH_CUTOFF_Y / tile_world)), 0, n - 1)
	var row_south := clampi(int(ceil(SOUTH_CUTOFF_Y / tile_world)), 0, n - 1)
	var x0 := clampi(int(floor(top_left.x / tile_world)) - TILE_PAD, 0, n - 1)
	var y0 := clampi(int(floor(top_left.y / tile_world)) - TILE_PAD, row_north, row_south)
	var x1 := clampi(int(floor((top_left.x + view.x) / tile_world)) + TILE_PAD, 0, n - 1)
	var y1 := clampi(int(floor((top_left.y + view.y) / tile_world)) + TILE_PAD, row_north, row_south)

	var needed: Dictionary = {}
	var gens := 0

	for li in range(_layers.size()):
		if not _layers[li]["visible"]:
			continue
		var provider = _layers[li]["provider"]  # TileProvider или OnlineTileProvider (по request_tile)
		for ty in range(y0, y1 + 1):
			for tx in range(x0, x1 + 1):
				var key := "%d|%d/%d/%d" % [li, lod, tx, ty]
				needed[key] = true
				if _active.has(key):
					continue
				if gens < MAX_GEN_PER_FRAME:
					var tex: Texture2D = provider.request_tile(lod, tx, ty)
					if tex != null:
						var z: int = _layers[li].get("z_index", li)
						_active[key] = _make_tile(tex, li, tx, ty, tile_world, z)
						gens += 1

	# Выгружаем то, что больше не нужно (другой LOD / скрытый слой / ушло за экран).
	# ВАЖНО: тайл СТАРОГО LOD держим как подложку, пока именно ЕГО ЗАМЕНА (новый
	# тайл(и), покрывающие ту же область) не готова полностью, — иначе в этом
	# месте на кадр-другой мелькнёт дыра. Раньше ждали, пока догрузится ВЕСЬ
	# слой на экране целиком — из-за этого старый и новый тайл полупрозрачного
	# слоя (континенты) висели друг на друге лишние кадры, и их альфа
	# складывалась (0.55 поверх 0.55 ≈ 0.8), что было видно как мерцание при
	# зуме. Теперь проверяем только конкретную перекрываемую область.
	for key in _active.keys():
		if needed.has(key):
			continue
		var sep := (key as String).find("|")
		var li := int((key as String).substr(0, sep))
		var rest := (key as String).substr(sep + 1).split("/")
		var kz := int(rest[0])
		var kx := int(rest[1])
		var ky := int(rest[2])
		if kz != lod and li < _layers.size() and _layers[li]["visible"] \
				and not _replacement_ready(li, kz, kx, ky, lod, x0, y0, x1, y1):
			continue
		_active[key].queue_free()
		_active.erase(key)

	_update_status(lod, cam_zoom)


## Проверяет, готова ли ЗАМЕНА старого тайла (li, kz, kx, ky) на текущем LOD.
## Используется только для решения "можно ли уже убрать старый тайл", см.
## комментарий в _process — без этого полупрозрачные слои (континенты)
## мерцали при зуме из-за наложения старого и нового тайла друг на друга.
func _replacement_ready(li: int, kz: int, kx: int, ky: int, lod: int,
		x0: int, y0: int, x1: int, y1: int) -> bool:
	var dz := lod - kz
	if dz > 0:
		# Старый тайл грубее нового — над его областью должны лечь ВСЕ дочерние
		# тайлы нового LOD (те из них, что вообще видны на экране).
		var n := 1 << dz
		for cy in range(ky * n, ky * n + n):
			if cy < y0 or cy > y1:
				continue  # эта часть вне экрана — не ждём её
			for cx in range(kx * n, kx * n + n):
				if cx < x0 or cx > x1:
					continue
				if not _active.has("%d|%d/%d/%d" % [li, lod, cx, cy]):
					return false
		return true
	else:
		# Старый тайл детальнее нового — один новый (грубый) тайл целиком его
		# перекрывает, как только он готов.
		var pdz := -dz
		return _active.has("%d|%d/%d/%d" % [li, lod, kx >> pdz, ky >> pdz])


func _add_polar_mask(y0: float, y1: float) -> void:
	var poly := Polygon2D.new()
	poly.polygon = PackedVector2Array([
		Vector2(-WORLD_PX, y0), Vector2(WORLD_PX * 2.0, y0),
		Vector2(WORLD_PX * 2.0, y1), Vector2(-WORLD_PX, y1),
	])
	poly.color = Color(0.02, 0.05, 0.09)  # тёмный "край мира", не спутано с океаном
	poly.z_index = 1000
	container.add_child(poly)


func _make_tile(tex: Texture2D, layer_idx: int, x: int, y: int,
		tile_world: float, z_index_override: int = -1) -> Sprite2D:
	var spr := Sprite2D.new()
	spr.centered = false
	spr.texture = tex
	var s := tile_world / spr.texture.get_width()
	spr.scale = Vector2(s, s)
	spr.position = Vector2(x * tile_world, y * tile_world)
	# оверлеи поверх базового слоя (по умолчанию) — или явный override
	# (_layers[li]["z_index"], см. вызов в _process), если слою нужен
	# порядок отрисовки, не совпадающий с порядком добавления в _layers.
	spr.z_index = z_index_override if z_index_override >= 0 else layer_idx
	# Билинейная фильтрация (по умолчанию) смешивает цвет с краем СОСЕДНЕГО
	# тайла на стыке (доля пикселя несовпадения от масштабирования) — тонкая
	# линия другого оттенка на границе тайлов, мерцающая при зуме (несовпадение
	# "плавает"). NEAREST убирает смешивание на стыке ценой чуть менее гладкой
	# картинки при сильном приближении внутри одного тайла.
	spr.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	container.add_child(spr)
	return spr


func _update_status(lod: int, cam_zoom: float) -> void:
	if not status_label:
		return
	var names: Array = []
	for l in _layers:
		if l["visible"]:
			names.append(l["name"])
	status_label.text = "Слои: %s   |   LOD z%d   |   zoom %.2f   |   тайлов: %d" % [
		", ".join(names), lod, cam_zoom, _active.size()]
