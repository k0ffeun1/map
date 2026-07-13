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
		"width": 0.10,
		"color": Color(0x10 / 255.0, 0x22 / 255.0, 0x3d / 255.0, 0.49),
		"feather": 1.0,
		"min_half_w": 0.05,
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
		"width": 0.30,
		"color": Color(0.6117647, 0.6117647, 0.6117647, 1.0),
		"feather": 0.3,
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
	"region": {
		# Слой "Исторические регионы Иберии" (клавиша I): цветовая заливка
		# объединённых провинций + толстая внешняя граница региона поверх
		# слоя 4. Толщина редактируется живым слайдером, этот default только
		# стартовая точка.
		"width": 0.55,
		"color": Color(0.03, 0.02, 0.01, 0.95),
		"feather": 0.7,
		"min_half_w": 0.35,
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
var _lod := -1                 ## Текущий уровень детализации (с гистерезисом).
var _mark_tool: MarkTool       ## Разметка карты кликами -> scripts/tools/_work/user_marks.json (клавиша M).
var _dragging_city_marker := false  ## ЛКМ зажата на маркере города — см. _build_city_markers_panel/ProvinceCityMarkersLayer.try_begin_drag.
var _city_markers_status_label: Label
var _world_provinces_layer_idx := -1
var _world_provinces_provider: IrregularCellProvider
var _selected_world_province_id := ""
var _world_provinces_panel: VBoxContainer
var _netherlands_provinces_layer_idx := -1
var _netherlands_provinces_provider: IrregularCellProvider
var _selected_netherlands_province_id := ""
const DEFAULT_WORLD_PROVINCE_AREA_HIDE_THRESHOLD_KM2 := 500.0

## Стабильные id по (admin, name) провинции, см. build_provinces.py — НЕ
## зависят от позиции клетки в provinces.json (2026-07-13: до этого были
## "province_%04d" по порядковому номеру, и правка build_provinces.py,
## убравшая осколки-артефакты из середины файла, сдвинула ВСЕ номера после
## них и сломала эти списки — Нидерланды/Мальта и т.п. стали указывать не на
## те провинции). Пересчитано сопоставлением bbox старой/новой версии файла.
const NETHERLANDS_PROVINCE_IDS := [
	"netherlands__groningen", # Groningen
	"netherlands__drenthe", # Drenthe
	"netherlands__overijssel", # Overijssel
	"netherlands__gelderland", # Gelderland
	"netherlands__limburg", # Limburg (NL)
	"netherlands__zeeland", # Zeeland
	"netherlands__noord_brabant", # Noord-Brabant
	"netherlands__zuid_holland", # Zuid-Holland island piece
	"netherlands__zuid_holland_2", # Zuid-Holland
	"netherlands__noord_holland", # Noord-Holland
	"netherlands__noord_holland_2", # Noord-Holland island piece
	"netherlands__friesland_2", # Friesland island piece
	"netherlands__friesland_3", # Friesland island piece
	"netherlands__friesland_4", # Friesland island piece
	"netherlands__friesland_5", # Friesland island piece
	"netherlands__flevoland", # Flevoland
]
const HIDDEN_WORLD_PROVINCE_IDS := [
	"netherlands__friesland", # основной массив суши Фрисландии (не остров)
]
const WORLD_PROVINCE_ID_ALIASES := {
	"tunisia__m_denine_2": "tunisia__m_denine",
	"spain__santa_cruz_de_tenerife": "spain__santa_cruz_de_tenerife_3",
	"spain__santa_cruz_de_tenerife_2": "spain__santa_cruz_de_tenerife_3",
	"spain__santa_cruz_de_tenerife_4": "spain__santa_cruz_de_tenerife_3",
	"spain__las_palmas_2": "spain__las_palmas",
	"spain__las_palmas_3": "spain__las_palmas",
	"portugal__azores_2": "portugal__azores",
	"portugal__azores_3": "portugal__azores",
	"spain__baleares": "spain__baleares_2",
	"spain__baleares_3": "spain__baleares_2",
}
const WORLD_PROVINCE_AREA_FILTER_EXEMPT_IDS := [
	"denmark__syddanmark_2", # Syddanmark, Wadden island
	"denmark__syddanmark_3", # Syddanmark, Wadden island
	"netherlands__groningen", # Groningen, Wadden zone
	"germany__niedersachsen_2", # Niedersachsen island
	"germany__niedersachsen_3", # Niedersachsen island
	"germany__niedersachsen_4", # Niedersachsen island
	"netherlands__noord_holland_2", # Noord-Holland island
	"netherlands__friesland", # Friesland
	"netherlands__friesland_2", # Friesland island
	"netherlands__friesland_3", # Friesland island
	"netherlands__friesland_4", # Friesland island
	"netherlands__friesland_5", # Friesland island
	"saint_helena__saint_helena", # Saint Helena
	"jersey__jersey", # Jersey
	"guernsey__sark", # Sark
	"guernsey__sark_2", # Sark
	"maldives__addu", # Maldives
	"maldives__mal", # Maldives
	"maldives__haa_dhaalu", # Maldives
	"malta__xewkija", # Malta
	"malta__birgu", # Malta
	# Карибский кластер восточнее Пуэрто-Рико, найдено по скрину 2026-07-13.
	"united_states_virgin_islands__saint_croix", # Saint Croix (US Virgin Islands)
	"saint_kitts_and_nevis__saint_john_capesterre", # Saint John Capesterre
	"antigua_and_barbuda__barbuda", # Barbuda
	"antigua_and_barbuda__saint_mary", # Saint Mary (Antigua)
]

# --- Клик по клетке (тест: Ла-Корунья) -----------------------------------------
var _cells_test_layer_idx := -1          ## Индекс слоя "Клетки (тест: Ла-Корунья)" в _layers.
var _cells_test_provider: IrregularCellProvider  ## Для point-in-polygon по клику (get_cell_id_at).
var _test_cells_by_id: Dictionary = {}   ## "id" -> Cell (см. CellCatalog.load_cells).
var _cells_test_fill_color := Color(0.22, 0.62, 1.0, 0.18)
var _cells_test_border_color := Color(0.02, 0.08, 0.14, 0.70)
var _cells_test_border_width := 0.14
var _cells_test_border_blur := 1.2
var _cells_test_selected_fill_color := Color(1.0, 1.0, 1.0, 0.12)
var _cells_test_selected_outline_color := Color(1.0, 1.0, 1.0, 1.0)
var _cells_test_selected_outline_width := 0.45
var _cells_test_selected_outline_blur := 0.0
var _iberia_land_cells_layer_idx := -1
var _iberia_land_cells_provider: IrregularCellProvider
var _iberia_land_cells_fill_color := Color(0.16, 0.74, 0.96, 0.16)
var _iberia_land_cells_border_color := Color(0.01, 0.05, 0.08, 0.82)
var _selected_iberia_land_cell_id := ""
var _cell_info_label: Label              ## Панель с показателями кликнутой клетки.
var _cell_boundary_draft_layer: Node2D
var _cell_boundary_tool_panel: VBoxContainer
var _cell_boundary_tool_content: VBoxContainer
var _cell_boundary_tool_status: Label
var _cell_boundary_tool_collapsed := false

## Индекс слоя "Мировой океан (без глубин/мелководья)" — та же геометрия
## world_ocean.json, но плоский однотонный живой рендер, без запечённого
## GEBCO-градиента и без живых полос поверх. Клавиша B.
var _ocean_flat_layer_idx := -1

## Значения по умолчанию для мелководья/глубины — используются ТОЛЬКО живым
## слоем V (_setup_ocean_v_depth_shallow/_build_ocean_v_panel) с 2026-07-13,
## когда старый живой слой "Мировой океан" (свои _ocean_shallow_*/
## _ocean_depth_*-переменные, _setup_ocean_shallow_live/_setup_ocean_depth_live/
## _build_ocean_shallow_panel) был удалён — заменён запечённым комплектом
## (см. клавишу 2 в _unhandled_input).
const OCEAN_SHALLOW_DEFAULT_COLOR := Color("36b2dc")  # решение пользователя 2026-07-11
const OCEAN_SHALLOW_DEFAULT_LAND_MARGIN_KM := 2.0  # решение пользователя 2026-07-11
const OCEAN_SHALLOW_DEFAULT_SEA_MARGIN_KM := 15.0  # решение пользователя 2026-07-11
const OCEAN_SHALLOW_DEFAULT_EDGE_TRANSITION_KM := 12.1  # ширина плавного края полосы со стороны моря, решение пользователя 2026-07-11

const OCEAN_DEPTH_DEFAULT_SHELF_COLOR := Color("009acd")             # решение пользователя 2026-07-11
const OCEAN_DEPTH_DEFAULT_MID_COLOR := Color("04588c")               # 3-й уровень градиента (склон), решение пользователя 2026-07-11
const OCEAN_DEPTH_DEFAULT_DEEP_COLOR := Color("062962")              # решение пользователя 2026-07-11
const OCEAN_DEPTH_DEFAULT_GRADIENT_GAMMA := 0.8  # решение пользователя 2026-07-11
const OCEAN_DEPTH_DEFAULT_MID_POINT := 0.7  # положение color_mid на кривой (0=шельф..1=глубины), решение пользователя 2026-07-11
const OCEAN_DEPTH_DEFAULT_SHOW_ISOBATHS := false  # решение пользователя 2026-07-11: изобаты выкл. по умолчанию, инструмент скрыт из панели
const OCEAN_DEPTH_DEFAULT_ISOBATH_INTERVAL_M := 50.0  # решение пользователя 2026-07-11
const OCEAN_DEPTH_DEFAULT_ISOBATH_COLOR := Color(1.0, 1.0, 1.0, 0.35)
## 4-й уровень градиента "бездна" (хадальная зона, >9000м) — по прямой
## просьбе пользователя 2026-07-13, добавлен вместе с регионом Марианской
## впадины (см. build_sea_depth_mariana_trench.py). Порог — АБСОЛЮТНЫЕ метры
## (не доля кривой, как mid_point), поэтому одно и то же значение можно
## применять ко всем материалам глубины сразу: у регионов с max_depth_m<=9000
## (Западная Европа/Атлантика, слой 2) порог физически недостижим, цвет
## бездны там никогда не проявится — только у Марианской впадины (max_depth_m=11000).
const OCEAN_DEPTH_DEFAULT_ABYSS_COLOR := Color("040e1c")  # почти чёрный тёмно-синий — хадальная зона (>9000м), реальный цвет темнее любого света
const OCEAN_DEPTH_DEFAULT_ABYSS_DEPTH_M := 9000.0

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
var _provinces_iberia_provider: IrregularCellProvider
var _provinces_iberia_selection_provider: IrregularCellProvider
var _provinces_iberia_panel: VBoxContainer
var _province_info_label: Label
var _selected_province_name := ""
const SELECTED_CELL_OVERLAY_SCRIPT := preload("res://scripts/SelectedCellOverlay.gd")
const CELL_BOUNDARY_DRAFT_LAYER_SCRIPT := preload("res://scripts/CellBoundaryDraftLayer.gd")
## class_name StreamedBakedTileProvider не подхватывается глобальным реестром
## скриптов при запуске БЕЗ редактора (кэш .godot/global_script_class_cache.cfg
## обновляется только редактором) — грузим явным preload, как и два скрипта
## выше.
const STREAMED_BAKED_TILE_PROVIDER_SCRIPT := preload("res://scripts/StreamedBakedTileProvider.gd")
var _selected_cell_overlay = null
var _selected_cell_overlay_layer_idx := -1
var _selection_style_panel: VBoxContainer
var _selection_style_content: VBoxContainer
var _selection_style_collapsed := false
var _selection_fill_color := Color(1.0, 1.0, 1.0, 0.28)
var _selection_outline_color := Color(1.0, 1.0, 1.0, 1.0)
var _selection_outline_width := 0.5
var _selection_outline_blur := 0.0
var _selected_cell_overlay_fill_override = null

## Главные города провинций (кружок + подпись, НЕ тайловый слой, см.
## ProvinceCityMarkersLayer.gd) — координаты из Natural Earth
## ne_10m_populated_places, см. scripts/tools/build_province_cities_iberia.py
## -> assets/province_cities_iberia.json. Видимость синхронизирована со слоем
## "Провинции (Иберия)" (клавиша 4) в _process, та же связка, что океан+реки на 2.
var _province_city_markers: ProvinceCityMarkersLayer

## Панель "Шрифт городов" (прямая просьба пользователя 2026-07-13) — живая
## правка шрифта/размера/цвета подписей маркеров ProvinceCityMarkerNode на
## слое 4. Шрифты — .ttf-файлы Google Fonts в assets/fonts/, ключ "По
## умолчанию" -> "" означает ThemeDB.fallback_font (как было раньше).
const CITY_LABEL_FONTS := {
	"По умолчанию": "",
	"Montserrat": "res://assets/fonts/Montserrat.ttf",
	"Roboto": "res://assets/fonts/Roboto.ttf",
	"Open Sans": "res://assets/fonts/OpenSans.ttf",
	"Oswald": "res://assets/fonts/Oswald.ttf",
	"Lato": "res://assets/fonts/Lato.ttf",
	"Playfair Display": "res://assets/fonts/PlayfairDisplay.ttf",
	"Literata": "res://assets/fonts/Literata.ttf",
	"PT Sans Caption": "res://assets/fonts/PTSansCaption.ttf",
}
var _city_font_panel: VBoxContainer
var _city_font_content: VBoxContainer
var _city_font_collapsed := false
var _city_label_fill_color := Color(0.98, 0.96, 0.90, 0.95)
var _city_label_outline_color := Color(0.05, 0.05, 0.05, 0.8)
var _city_label_italic := false
var _city_label_bold_amount := 0.0  ## 0..1, передаётся в FontVariation.variation_embolden как 0..1.2
var _city_label_spacing_percent := 0.0

## Диагностика слоя "8" (2026-07-12) — чекбоксы в панели
## _build_world_provinces_panel, НЕ связаны с видимостью самого слоя 8 (только
## со своими чекбоксами). Данные предпосчитаны офлайн, см.
## scripts/tools/build_small_provinces_markers.py -> assets/small_provinces_markers.json
## и scripts/tools/build_island_piece_markers.py -> assets/island_piece_markers.json.
var _small_provinces_markers: SmallProvinceMarkersLayer
var _island_piece_markers: IslandPieceMarkersLayer

## Исторические регионы Иберии — цветовая группировка провинций из слоя 4
## по assets/regions_iberia.json. Клавиша I. При включении слой 4 включается
## автоматически как основа, а региональные границы рисуются поверх него.
var _regions_iberia_layer_idx := -1
var _regions_iberia_provider: IrregularCellProvider
var _regions_iberia_panel: VBoxContainer

## Индекс слоя "Клетки (Ла-Корунья, сетка)" — черновой №2 нарезки клеток,
## прямыми линиями (равномерная сетка, обрезанная контуром провинции), БЕЗ
## волнения и БЕЗ анализа границы провинции (никакого brd_open) — по прямой
## просьбе пользователя. См. scripts/tools/build_cells_lacoruna_grid.py.
## Слой "Клетки (тест: Ла-Корунья)" (клавиша C, Voronoi) НЕ тронут. Клавиша G.
var _cells_lacoruna_grid_layer_idx := -1

## Слой "V" — подложка океан+глубины, всегда снизу (план см. done.md/
## обсуждение с пользователем 2026-07-12): плоский цвет на весь мир, БЕЗ
## вычитания геометрии provinces.json/world_ocean.json — острова не
## дырявятся, потому что слою V вообще нечего вычитать (см. SolidColorTileProvider.gd).
## z_index заведомо ниже любого другого слоя (явное число, не позиция в
## _layers) — гарантированно рисуется САМЫМ нижним, под провинциями/спутником.
## Включён по умолчанию при запуске игры (visible=true) — постоянный рабочий
## слой, не черновик за клавишей; клавиша V по-прежнему переключает его
## видимость, панель настроек-ползунков убрана по прямой просьбе пользователя
## 2026-07-13 (тюнинг цвета/градиента больше не нужен как live-инструмент).
var _ocean_v_layer_idx := -1
var _ocean_v_provider: SolidColorTileProvider
const OCEAN_V_Z_INDEX := -10

## ЗАПЕЧЁННЫЙ слой "2" (базовая заливка+глубина GEBCO снизу + мелководье
## сверху, точная офлайн-копия внешнего вида живого V — см. задачу "заменить
## старый слой 2 запечённой версией слоя V", 2026-07-13,
## assets/config/ocean_v_bake_profile.json, scripts/tools/bake_ocean_v_*.py).
## Визуально сверен и подтверждён пользователем — теперь ЭТО и есть клавиша
## 2 (см. match ниже); старый слой "Мировой океан" (_ocean_layer_idx и весь
## его живой оверлей/панель) удалён отдельным коммитом 2026-07-13.
## Переключается ОДНОЙ клавишей на ОБА под-слоя разом (та же связка, что
## раньше была "Мировой океан"+"Реки").
var _ocean_v_baked_base_depth_layer_idx := -1
var _ocean_v_baked_shallow_layer_idx := -1
const OCEAN_V_COLOR := Color("36b2dc")  # тот же цвет, что OCEAN_SHALLOW_DEFAULT_COLOR — по прямой просьбе пользователя 2026-07-12, чтобы дыры в данных (см. ниже) не выглядели чёрным провалом, а сливались с мелководьем
var _water_cells_layer_idx := -1
var _water_cells_provider: IrregularCellProvider
var _selected_water_cell_id := ""
var _water_cells_panel: VBoxContainer
var _water_cells_panel_content: VBoxContainer
var _water_cells_panel_collapsed := false
var _water_cells_fill_color := Color(1.0, 1.0, 1.0, 0.0)
var _water_cells_border_color := Color(0x10 / 255.0, 0x22 / 255.0, 0x3d / 255.0, 0.49)
var _water_cells_border_width := 0.10
var _water_cells_border_blur := 1.0
var _water_selected_fill_color := Color(0.0, 0.0, 0.0, 0.0)
var _water_selected_outline_color := Color(1.0, 1.0, 1.0, 1.0)
var _water_selected_outline_width := 0.3
var _water_selected_outline_blur := 0.0

## Этап 2 черновика "V" — глубина/мелководье из sea_depth_west_europe.png
## (те же PNG, что уже использует слой "2"). Маска суша/море (альфа PNG)
## ИСПРАВЛЕНА 2026-07-12: берётся из world_ocean.json (векторно), не из
## знака высоты GEBCO — см. докстринг build_sea_depth_west_europe.py (баг с
## польдерами Нидерландов, помеченными морем по чистой высоте). Покрывает
## только регион REGION_LONLAT (Атлантика/Карибы/обе Америки) — вне него
## виден только плоский OCEAN_V_COLOR слоя ниже. z_index чуть выше
## OCEAN_V_Z_INDEX, но всё ещё далеко ниже любого другого слоя (0/2/3/4/20/...).
##
## ТОЧНАЯ КОПИЯ слоя 2 (по прямой просьбе пользователя 2026-07-12) — тот же
## непрерывный градиент (sea_depth_zones.gdshader, НЕ дискретные уровни —
## пробовали 8 уровней отдельным шейдером, откатили обратно), те же
## OCEAN_DEPTH_DEFAULT_*/OCEAN_SHALLOW_DEFAULT_* значения по умолчанию, та же
## панель (сравни с _build_ocean_shallow_panel) — только СВОИ независимые
## материалы/спрайты/панель, чтобы крутить слой V отдельно от слоя 2, не
## трогая его настройки.
var _ocean_v_depth_sprites: Array = []  # см. комментарий у _ocean_depth_sprites (та же тайловая логика)
var _ocean_v_depth_material: ShaderMaterial
var _ocean_v_shallow_sprites: Array = []  # см. комментарий у _ocean_shallow_sprites (та же тайловая логика)
var _ocean_v_shallow_material: ShaderMaterial
## Марианская впадина (Бездна Челленджера +500км, см. build_sea_depth_mariana_trench.py)
## — ВТОРОЙ независимый растр/материал глубины поверх слоя V, тот же приём,
## что у _ocean_v_depth_*, но свой регион (Тихий океан) и max_depth_m=11000
## (единственный материал, где реально достижим 4-й уровень градиента
## "бездна", см. OCEAN_DEPTH_DEFAULT_ABYSS_* выше).
var _ocean_v_mariana_depth_sprites: Array = []
var _ocean_v_mariana_depth_material: ShaderMaterial
## Панель ползунков слоя V (клавиша V) — по прямой просьбе пользователя
## 2026-07-13 ("сделай инструментарий... где я могу ползунком двигать
## градиент глубин по всем уровням"), возвращена после того, как её ранее
## убрали в этой же сессии — теперь крутит ОБА материала глубины слоя V
## разом (_ocean_v_depth_material — Атлантика/Америки, _ocean_v_mariana_depth_material
## — Марианская впадина), чтобы 4-й уровень "бездна" (реально виден только
## на Марианской впадине) настраивался тем же инструментом, что и остальные
## уровни.
var _ocean_v_panel: VBoxContainer
## Пипетка (используется панелями настроек, где остались ползунки/цвета) —
## жмём кнопку рядом с ColorPickerButton, потом кликаем по карте: цвет ПОД
## КУРСОРОМ (реально отрисованный кадр, любой слой сверху) подставляется в
## этот picker. Не null, пока ждём клика — следующий ЛКМ его использует и
## сбрасывает (см. _unhandled_input).
var _eyedropper_target: ColorPickerButton = null
var _eyedropper_button: Button = null  # сама кнопка-пипетка — нужно снять toggle после использования/отмены

func _ready() -> void:
	# Базовый слой — РЕАЛЬНЫЙ спутник Земли (онлайн-тайлы).
	var satellite := OnlineTileProvider.new()
	add_child(satellite)

	_layers = [
		{
			"name": "Спутник",
			"provider": satellite,
			# Скрыт по умолчанию (2026-07-13, прямая просьба пользователя) —
			# теперь стартовый вид даёт запечённый слой "2", не спутник.
			"visible": false,
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
		_world_provinces_provider = IrregularCellProvider.new("res://assets/provinces.json",
			ps["color"], 1.0, 0.22, 0.78, PackedColorArray(), ps["width"],
			ps["dashed"], ps["dash_len"], ps["dash_gap"], ps["feather"],
			ps["min_half_w"], ps["raster_px"])
		_world_provinces_provider.set_cell_id_aliases(WORLD_PROVINCE_ID_ALIASES)
		_world_provinces_provider.set_hidden_cell_ids(HIDDEN_WORLD_PROVINCE_IDS)
		_world_provinces_provider.set_area_hidden_exempt_cell_ids(WORLD_PROVINCE_AREA_FILTER_EXEMPT_IDS)
		_world_provinces_provider.set_area_hidden_threshold(DEFAULT_WORLD_PROVINCE_AREA_HIDE_THRESHOLD_KM2)
		_world_provinces_provider.set_selected_cell_ids(NETHERLANDS_PROVINCE_IDS, Color(0.96, 0.78, 0.30, 0.48))
		add_child(_world_provinces_provider)
		_world_provinces_layer_idx = _layers.size()
		_layers.append({
			"name": "Области (провинции)",
			"provider": _world_provinces_provider,
			"visible": false,
			"z_index": 20,
		})
		_build_world_provinces_panel($UI)

	if FileAccess.file_exists("res://assets/provinces_netherlands.json"):
		var ns: Dictionary = BORDER_STYLE["province"]
		_netherlands_provinces_provider = IrregularCellProvider.new("res://assets/provinces_netherlands.json",
			ns["color"], 1.0, 0.22, 0.78, PackedColorArray(), ns["width"],
			ns["dashed"], ns["dash_len"], ns["dash_gap"], ns["feather"],
			ns["min_half_w"], ns["raster_px"])
		add_child(_netherlands_provinces_provider)
		var netherlands_visual_provider = _netherlands_provinces_provider
		if DirAccess.dir_exists_absolute("res://assets/tiles_bundle/provinces_netherlands_baked"):
			netherlands_visual_provider = BakedTileProvider.new("res://assets/tiles_bundle/provinces_netherlands_baked", 7)
			add_child(netherlands_visual_provider)
		_netherlands_provinces_layer_idx = _layers.size()
		_layers.append({
			"name": "Нидерланды + Кёльн-Гамбург",
			"provider": netherlands_visual_provider,
			"visible": false,
			"z_index": 30,
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
		_cells_test_provider = IrregularCellProvider.new("res://assets/cells_test.json",
			_cells_test_border_color, _cells_test_fill_color.a, 0.55, 0.95, PackedColorArray(), _cells_test_border_width,
			cs["dashed"], cs["dash_len"], cs["dash_gap"], cs["feather"],
			cs["min_half_w"], cs["raster_px"], 8)
		_cells_test_provider.set_uniform_fill_color(_cells_test_fill_color)
		_cells_test_provider.set_border_feather(_cells_test_border_blur)
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
		_cell_boundary_draft_layer = CELL_BOUNDARY_DRAFT_LAYER_SCRIPT.new()
		_cell_boundary_draft_layer.z_index = 220
		container.add_child(_cell_boundary_draft_layer)
		_cell_boundary_draft_layer.setup("res://assets/cell_boundary_drafts.json", camera)
		_build_cell_boundary_tool_panel($UI)

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

	# Старый слой "Мировой океан" (BakedTileProvider на world_ocean_baked
	# ИЛИ живой IrregularCellProvider-фолбэк на world_ocean.json + живая
	# полоса мелководья/шельфа/глубин через _setup_ocean_shallow_live) УДАЛЁН
	# 2026-07-13 (задача "заменить старый слой 2 запечённой версией слоя V")
	# — заменён запечённым комплектом base_depth+shallow, см. регистрацию
	# ov_base/ov_shallow в конце _ready() и клавишу 2 в _unhandled_input.
	# _ocean_layer_idx/_setup_ocean_shallow_live/_setup_ocean_depth_live/
	# _build_ocean_shallow_panel и связанные live-материалы удалены вместе с
	# ним — не трогать живой V (_setup_ocean_v_depth_shallow, отдельные
	# _ocean_v_*-материалы) и слой "B" ниже, они независимы.

	# Слой "B" — та же геометрия "Мирового океана" (assets/world_ocean.json),
	# но БЕЗ запечённого глубинного градиента GEBCO (см. bake_world_ocean_tiles.py)
	# и БЕЗ живых полос мелководья/шельфа/глубин поверх — по прямой просьбе
	# пользователя, чтобы видеть "чистую" заливку отдельно от слоя 2. ВСЕГДА
	# живой рендер (не запечённый), один плоский цвет на всю заливку (не
	# HSV-хэш по клетке — здесь всего один "кусок" воды на весь мир, но для
	# наглядности задан явно). Дырки-острова (см. done.md) ведут себя так же,
	# как у слоя 2 — это не отдельная фича этого слоя. Клавиша `B`.
	if FileAccess.file_exists("res://assets/world_ocean.json"):
		var ocean_flat_color := PackedColorArray([Color("36b2dc")])
		var ocean_flat := IrregularCellProvider.new("res://assets/world_ocean.json",
			Color("36b2dc"), 1.0, 0.35, 0.88, ocean_flat_color,
			1.0, false, 0.5, 0.35, 2.0, 0.5, 1024)
		add_child(ocean_flat)
		_ocean_flat_layer_idx = _layers.size()
		_layers.append({
			"name": "Мировой океан (без глубин/мелководья)",
			"provider": ocean_flat,
			"visible": false,
			"z_index": 2,
		})

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
		_provinces_iberia_provider = IrregularCellProvider.new("res://assets/provinces_iberia.json",
			ps4["color"], 1.0, 0.22, 0.78, PackedColorArray(), ps4["width"],
			ps4["dashed"], ps4["dash_len"], ps4["dash_gap"], ps4["feather"],
			ps4["min_half_w"], ps4["raster_px"])
		if FileAccess.file_exists("res://assets/provinces_iberia_selection_2km.json"):
			_provinces_iberia_selection_provider = IrregularCellProvider.new("res://assets/provinces_iberia_selection_2km.json",
				ps4["color"], 1.0, 0.22, 0.78, PackedColorArray(), ps4["width"],
				ps4["dashed"], ps4["dash_len"], ps4["dash_gap"], ps4["feather"],
				ps4["min_half_w"], ps4["raster_px"])
		# По умолчанию выключено: на 1024px live-тайлах даже радиус 1px
		# заметно утяжеляет первичный рендер слоя 4. Включается вручную
		# слайдером после того, как провинции уже прогрузились.
		_provinces_iberia_provider.set_gap_fill_radius_px(0)
		_provinces_iberia_provider.set_render_smaller_cells_on_top(true)
		add_child(_provinces_iberia_provider)
		_provinces_iberia_layer_idx = _layers.size()
		_layers.append({
			"name": "Провинции (Иберия, живой ВРЕМЕННО)",
			"provider": _provinces_iberia_provider,
			"visible": false,
		})
		_build_provinces_iberia_panel($UI)

	# Исторические регионы Иберии — объединённые полигоны провинций из слоя
	# 4, см. scripts/tools/build_regions_iberia.py. Отдельный регион =
	# отдельный цвет; граница регулируется слайдером в панели.
	if FileAccess.file_exists("res://assets/regions_iberia.json"):
		var rs: Dictionary = BORDER_STYLE["region"]
		_regions_iberia_provider = IrregularCellProvider.new("res://assets/regions_iberia.json",
			rs["color"], 0.42, 0.40, 0.92, PackedColorArray(), rs["width"],
			rs["dashed"], rs["dash_len"], rs["dash_gap"], rs["feather"],
			rs["min_half_w"], rs["raster_px"])
		add_child(_regions_iberia_provider)
		_regions_iberia_layer_idx = _layers.size()
		_layers.append({
			"name": "Исторические регионы Иберии",
			"provider": _regions_iberia_provider,
			"visible": false,
			"z_index": 90,
		})
		_build_regions_iberia_panel($UI)

	# Главные города провинций (реальное историческое место, не центр
	# полигона) — см. build_province_cities_iberia.py. НЕ тайловый слой (см.
	# ProvinceCityMarkersLayer.gd/ProvinceCityMarkerNode.gd: растровые
	# маркеры на стыке тайлов проваливались, часть круга не рисовалась и
	# сквозь неё была видна заливка провинции, см. сессию 2026-07-12) —
	# векторные узлы с z_index=100, гарантированно выше всех тайловых слоёв
	# и без пропусков на стыках.
	if FileAccess.file_exists("res://assets/province_cities_iberia.json"):
		_province_city_markers = ProvinceCityMarkersLayer.new()
		_province_city_markers.visible = false
		add_child(_province_city_markers)
		_province_city_markers.setup("res://assets/province_cities_iberia.json", camera)
		_build_city_markers_panel($UI)
		_build_city_font_panel($UI)

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
	_selected_cell_overlay = SELECTED_CELL_OVERLAY_SCRIPT.new()
	_selected_cell_overlay.z_index = 190
	container.add_child(_selected_cell_overlay)
	_apply_selection_overlay_style()

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
	_build_province_info_label()
	_build_selection_style_panel($UI)

	# Клавиша V — см. комментарий у _ocean_v_layer_idx выше. Добавлен ПОСЛЕДНИМ
	# в _ready() НАРОЧНО: клавиши 1/6/0/-/=/8/C завязаны на ЖЁСТКИЕ числовые
	# индексы в _layers (см. _unhandled_input) — вставка нового слоя в
	# СЕРЕДИНУ массива на 2026-07-12 сдвинула эти индексы и временно сломала
	# клавишу 8 (стала открывать "Реки" вместо "Провинции"). z_index у V и так
	# явный (OCEAN_V_Z_INDEX), поэтому позиция в массиве ни на что визуально
	# не влияет — новые слои-провайдеры добавлять СТРОГО в конец _ready().
	# Выключен по умолчанию (2026-07-13, прямая просьба пользователя) —
	# стартовый вид теперь у запечённого слоя "2" (см. ниже), V остаётся
	# рабочим визуальным эталоном/инструментом настройки, но не показывается
	# сразу при запуске.
	var ocean_v := SolidColorTileProvider.new(OCEAN_V_COLOR)
	_ocean_v_provider = ocean_v
	_ocean_v_layer_idx = _layers.size()
	_layers.append({
		"name": "V (подложка океан + глубина/мелководье из GEBCO)",
		"provider": ocean_v,
		"visible": false,
		"z_index": OCEAN_V_Z_INDEX,
	})
	_setup_ocean_v_depth_shallow()

	# Диагностика слоя "8" (2026-07-12, чекбоксы в _build_world_provinces_panel)
	# — добавлено ПОСЛЕДНИМ по той же причине, что и слой V выше: векторные
	# ноды, не тайловые провайдеры, в _layers не участвуют, но порядок в
	# _ready() всё равно держим строго в конце по общему правилу файла.
	if FileAccess.file_exists("res://assets/small_provinces_markers.json"):
		_small_provinces_markers = SmallProvinceMarkersLayer.new()
		_small_provinces_markers.visible = false
		add_child(_small_provinces_markers)
		_small_provinces_markers.setup("res://assets/small_provinces_markers.json", camera)

	if FileAccess.file_exists("res://assets/island_piece_markers.json"):
		_island_piece_markers = IslandPieceMarkersLayer.new()
		_island_piece_markers.visible = false
		add_child(_island_piece_markers)
		_island_piece_markers.setup("res://assets/island_piece_markers.json", camera)

	# Запечённый слой "2" (клавиша 2, см. комментарий у
	# _ocean_v_baked_base_depth_layer_idx выше) — офлайн-копия внешнего вида
	# живого V, визуально сверена и подтверждена пользователем 2026-07-13.
	# Добавлен ПОСЛЕДНИМ по общему правилу файла (новые слои-провайдеры
	# строго в конец _ready()). StreamedBakedTileProvider (LRU-кэш), а не
	# обычный BakedTileProvider — этот комплект рассчитан на покрытие всего
	# мира на всех LOD, в отличие от старых bake-слоёв с растущим без
	# ограничений кэшем.
	# Включён по умолчанию (visible=true, 2026-07-13, прямая просьба
	# пользователя) — теперь это стартовый вид игры вместо спутника/V.
	if DirAccess.dir_exists_absolute("res://assets/tiles_bundle/ocean_v_final/base_depth"):
		# fallback_color=OCEAN_V_COLOR — bake-скрипт НЕ сохраняет однотонные
		# тайлы (вне регионов GEBCO, см. его комментарий), поэтому отсутствие
		# файла здесь означает "сплошная заливка", а не "пусто".
		var ov_base = STREAMED_BAKED_TILE_PROVIDER_SCRIPT.new("res://assets/tiles_bundle/ocean_v_final/base_depth", MAX_Z, STREAMED_BAKED_TILE_PROVIDER_SCRIPT.DEFAULT_BUDGET_TILES, OCEAN_V_COLOR)
		add_child(ov_base)
		_ocean_v_baked_base_depth_layer_idx = _layers.size()
		_layers.append({
			"name": "Мировой океан (запечённый)",
			"provider": ov_base,
			"visible": true,
			"z_index": OCEAN_V_Z_INDEX - 1,
		})
	if DirAccess.dir_exists_absolute("res://assets/tiles_bundle/ocean_v_final/shallow"):
		var ov_shallow = STREAMED_BAKED_TILE_PROVIDER_SCRIPT.new("res://assets/tiles_bundle/ocean_v_final/shallow", MAX_Z)
		add_child(ov_shallow)
		_ocean_v_baked_shallow_layer_idx = _layers.size()
		_layers.append({
			"name": "Мировой океан: мелководье (запечённый)",
			"provider": ov_shallow,
			"visible": true,
			"z_index": 21,
		})

	if FileAccess.file_exists("res://assets/map_geometry/water_cells.json"):
		var ws: Dictionary = BORDER_STYLE["sea"]
		_water_cells_border_color = ws["color"]
		_water_cells_border_width = ws["width"]
		_water_cells_border_blur = ws["feather"]
		_water_cells_provider = IrregularCellProvider.new("res://assets/map_geometry/water_cells.json",
			_water_cells_border_color, _water_cells_fill_color.a, 0.48, 0.94, PackedColorArray(), _water_cells_border_width,
			ws["dashed"], ws["dash_len"], ws["dash_gap"], ws["feather"],
			ws["min_half_w"], ws["raster_px"], 4)
		_water_cells_provider.set_uniform_fill_color(_water_cells_fill_color)
		add_child(_water_cells_provider)
		_water_cells_layer_idx = _layers.size()
		_layers.append({
			"name": "Морские клетки",
			"provider": _water_cells_provider,
			"visible": false,
			"z_index": 120,
		})
		_build_water_cells_panel($UI)

	if FileAccess.file_exists("res://assets/lacoruna_city_first_cells_preview.json"):
		_iberia_land_cells_provider = IrregularCellProvider.new("res://assets/lacoruna_city_first_cells_preview.json",
			_iberia_land_cells_border_color, _iberia_land_cells_fill_color.a, 0.36, 0.96,
			PackedColorArray(), 0.11, false, 0.0, 0.0, 1.0, 0.08, 1024, 2)
		_iberia_land_cells_provider.set_uniform_fill_color(_iberia_land_cells_fill_color)
		add_child(_iberia_land_cells_provider)
		_iberia_land_cells_layer_idx = _layers.size()
		_layers.append({
			"name": "Ла-Корунья: клетки city-first (эталон)",
			"provider": _iberia_land_cells_provider,
			"visible": true,
			"z_index": 130,
		})

## Грузит полосу мелководья (расстояние до берега, 16 бит + альфа) как ОДИН
## или НЕСКОЛЬКО Sprite2D с общим ShaderMaterial `material` (шейдер уже
## должен быть назначен вызывающим кодом, сюда только грузим текстуру(ы) и
## выставляем encode_min_km/encode_max_km). Тайловый вариант используется,
## если найден manifest.json (см. build_coast_distance_field.py, x8 на весь
## регион Атлантики — один файл такого разрешения не влезает в лимит Godot
## Image, см. done.md), иначе — старый одиночный файл (x4, для регионов
## поменьше, где один Sprite2D укладывается в лимит). Возвращает Array
## созданных Sprite2D (пустой, если данных нет вообще).
func _load_shallow_water_sprites(material: ShaderMaterial, z_index: int) -> Array:
	const TILES_DIR := "res://assets/generated/coast_distance_field_west_europe_tiles"
	const MANIFEST_PATH := TILES_DIR + "/manifest.json"
	const SINGLE_IMG_PATH := "res://assets/generated/coast_distance_field_west_europe.png"
	const SINGLE_BBOX_PATH := "res://assets/generated/coast_distance_field_west_europe_bbox.json"

	var sprites: Array = []

	if FileAccess.file_exists(MANIFEST_PATH):
		var manifest: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(MANIFEST_PATH))
		if manifest != null:
			material.set_shader_parameter("encode_min_km", float(manifest["encode_min_km"]))
			material.set_shader_parameter("encode_max_km", float(manifest["encode_max_km"]))
			for t in manifest["tiles"]:
				var img := Image.new()
				if img.load("%s/%s" % [TILES_DIR, t["file"]]) != OK:
					continue
				var tex := ImageTexture.create_from_image(img)
				var spr := Sprite2D.new()
				spr.texture = tex
				spr.material = material
				spr.centered = false
				spr.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
				spr.position = Vector2(t["x0"], t["y0"])
				spr.scale = Vector2(
					(float(t["x1"]) - float(t["x0"])) / tex.get_width(),
					(float(t["y1"]) - float(t["y0"])) / tex.get_height())
				spr.z_index = z_index
				spr.visible = false
				add_child(spr)
				sprites.append(spr)
			if not sprites.is_empty():
				return sprites

	if FileAccess.file_exists(SINGLE_IMG_PATH) and FileAccess.file_exists(SINGLE_BBOX_PATH):
		var bbox: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(SINGLE_BBOX_PATH))
		var img := Image.new()
		if bbox != null and img.load(SINGLE_IMG_PATH) == OK:
			var tex := ImageTexture.create_from_image(img)
			material.set_shader_parameter("encode_min_km", float(bbox["encode_min_km"]))
			material.set_shader_parameter("encode_max_km", float(bbox["encode_max_km"]))
			var spr := Sprite2D.new()
			spr.texture = tex
			spr.material = material
			spr.centered = false
			spr.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
			spr.position = Vector2(bbox["x0"], bbox["y0"])
			spr.scale = Vector2(
				(float(bbox["x1"]) - float(bbox["x0"])) / tex.get_width(),
				(float(bbox["y1"]) - float(bbox["y0"])) / tex.get_height())
			spr.z_index = z_index
			spr.visible = false
			add_child(spr)
			sprites.append(spr)

	return sprites


## Грузит растр глубины (метры в R/G, альфа = маска моря) как ОДИН или
## НЕСКОЛЬКО Sprite2D с общим ShaderMaterial `material` (шейдер уже назначен
## вызывающим кодом заранее, сюда только текстура(ы) + max_depth_m). Тот же
## тайловый приём, что и у _load_shallow_water_sprites — с x8 на большой
## регион (см. build_sea_depth_west_europe.py) один файл больше не влезает в
## лимит Godot Image, есть manifest.json с тайлами.
## `base_name` — общая часть имени файлов генератора без суффиксов
## (_tiles/_bbox.json/.png), напр. "sea_depth_west_europe" или
## "sea_depth_mariana_trench" — по прямой просьбе пользователя 2026-07-13
## обобщено под несколько регионов вместо одного жёстко зашитого пути.
func _load_depth_sprites(material: ShaderMaterial, z_index: int, base_name: String) -> Array:
	var tiles_dir := "res://assets/generated/%s_tiles" % base_name
	var manifest_path := tiles_dir + "/manifest.json"
	var single_img_path := "res://assets/generated/%s.png" % base_name
	var single_bbox_path := "res://assets/generated/%s_bbox.json" % base_name

	var sprites: Array = []

	if FileAccess.file_exists(manifest_path):
		var manifest: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(manifest_path))
		if manifest != null:
			material.set_shader_parameter("max_depth_m", float(manifest["max_depth_m"]))
			for t in manifest["tiles"]:
				var img := Image.new()
				if img.load("%s/%s" % [tiles_dir, t["file"]]) != OK:
					continue
				var tex := ImageTexture.create_from_image(img)
				var spr := Sprite2D.new()
				spr.texture = tex
				spr.material = material
				spr.centered = false
				spr.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
				spr.position = Vector2(t["x0"], t["y0"])
				spr.scale = Vector2(
					(float(t["x1"]) - float(t["x0"])) / tex.get_width(),
					(float(t["y1"]) - float(t["y0"])) / tex.get_height())
				spr.z_index = z_index
				spr.visible = false
				add_child(spr)
				sprites.append(spr)
			if not sprites.is_empty():
				return sprites

	if FileAccess.file_exists(single_img_path) and FileAccess.file_exists(single_bbox_path):
		var bbox: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(single_bbox_path))
		var img := Image.new()
		if bbox != null and img.load(single_img_path) == OK:
			var tex := ImageTexture.create_from_image(img)
			material.set_shader_parameter("max_depth_m", float(bbox["max_depth_m"]))
			var spr := Sprite2D.new()
			spr.texture = tex
			spr.material = material
			spr.centered = false
			spr.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
			spr.position = Vector2(bbox["x0"], bbox["y0"])
			spr.scale = Vector2(
				(float(bbox["x1"]) - float(bbox["x0"])) / tex.get_width(),
				(float(bbox["y1"]) - float(bbox["y0"])) / tex.get_height())
			spr.z_index = z_index
			spr.visible = false
			add_child(spr)
			sprites.append(spr)

	return sprites


## Этап 2 черновика "V" (см. комментарий у _ocean_v_depth_sprite выше) —
## ДВА независимых спрайта поверх плоской заливки V, ТОЧНАЯ копия того, что
## уже даёт слою "2" глубину/мелководье (тот же шейдер/дефолты/панель), но
## ПОЗИЦИОНИРОВАНЫ под НИЗКИМ z_index слоя V, а не под слоем "2". Оба PNG
## (sea_depth_west_europe.png И coast_distance_field_west_europe.png) теперь
## берут маску суша/море из ОДНОГО источника — world_ocean.json (см. фикс
## 2026-07-12 в build_sea_depth_west_europe.py) — береговая линия глубины и
## мелководья совпадают между собой.
func _setup_ocean_v_depth_shallow() -> void:
	const DEPTH_SHADER_PATH := "res://scripts/shaders/sea_depth_zones.gdshader"
	const SHALLOW_SHADER_PATH := "res://scripts/shaders/shallow_water_band.gdshader"

	_ocean_v_depth_material = ShaderMaterial.new()
	_ocean_v_depth_material.shader = load(DEPTH_SHADER_PATH)
	_ocean_v_depth_material.set_shader_parameter("color_shelf", OCEAN_DEPTH_DEFAULT_SHELF_COLOR)
	_ocean_v_depth_material.set_shader_parameter("color_mid", OCEAN_DEPTH_DEFAULT_MID_COLOR)
	_ocean_v_depth_material.set_shader_parameter("color_deep", OCEAN_DEPTH_DEFAULT_DEEP_COLOR)
	_ocean_v_depth_material.set_shader_parameter("gradient_gamma", OCEAN_DEPTH_DEFAULT_GRADIENT_GAMMA)
	_ocean_v_depth_material.set_shader_parameter("mid_point", OCEAN_DEPTH_DEFAULT_MID_POINT)
	_ocean_v_depth_material.set_shader_parameter("show_isobaths", OCEAN_DEPTH_DEFAULT_SHOW_ISOBATHS)
	_ocean_v_depth_material.set_shader_parameter("isobath_interval_m", OCEAN_DEPTH_DEFAULT_ISOBATH_INTERVAL_M)
	_ocean_v_depth_material.set_shader_parameter("isobath_color", OCEAN_DEPTH_DEFAULT_ISOBATH_COLOR)
	_ocean_v_depth_material.set_shader_parameter("color_abyss", OCEAN_DEPTH_DEFAULT_ABYSS_COLOR)
	_ocean_v_depth_material.set_shader_parameter("abyss_depth_m", OCEAN_DEPTH_DEFAULT_ABYSS_DEPTH_M)
	_ocean_v_depth_sprites = _load_depth_sprites(_ocean_v_depth_material, OCEAN_V_Z_INDEX + 1, "sea_depth_west_europe")

	# Марианская впадина (Бездна Челленджера +500км) — по прямой просьбе
	# пользователя 2026-07-13: слой V раньше давал реальную батиметрию только
	# в регионе Атлантики/Америк (REGION_LONLAT в build_sea_depth_west_europe.py),
	# здесь — отдельный НЕЗАВИСИМЫЙ растр/материал для Тихого океана (см.
	# build_sea_depth_mariana_trench.py), max_depth_m=11000 у него в манифесте
	# — единственный материал, где порог "бездны" (abyss_depth_m=9000)
	# реально достижим (глубина там до ~10912м).
	_ocean_v_mariana_depth_material = ShaderMaterial.new()
	_ocean_v_mariana_depth_material.shader = load(DEPTH_SHADER_PATH)
	_ocean_v_mariana_depth_material.set_shader_parameter("color_shelf", OCEAN_DEPTH_DEFAULT_SHELF_COLOR)
	_ocean_v_mariana_depth_material.set_shader_parameter("color_mid", OCEAN_DEPTH_DEFAULT_MID_COLOR)
	_ocean_v_mariana_depth_material.set_shader_parameter("color_deep", OCEAN_DEPTH_DEFAULT_DEEP_COLOR)
	_ocean_v_mariana_depth_material.set_shader_parameter("gradient_gamma", OCEAN_DEPTH_DEFAULT_GRADIENT_GAMMA)
	_ocean_v_mariana_depth_material.set_shader_parameter("mid_point", OCEAN_DEPTH_DEFAULT_MID_POINT)
	_ocean_v_mariana_depth_material.set_shader_parameter("show_isobaths", OCEAN_DEPTH_DEFAULT_SHOW_ISOBATHS)
	_ocean_v_mariana_depth_material.set_shader_parameter("isobath_interval_m", OCEAN_DEPTH_DEFAULT_ISOBATH_INTERVAL_M)
	_ocean_v_mariana_depth_material.set_shader_parameter("isobath_color", OCEAN_DEPTH_DEFAULT_ISOBATH_COLOR)
	_ocean_v_mariana_depth_material.set_shader_parameter("color_abyss", OCEAN_DEPTH_DEFAULT_ABYSS_COLOR)
	_ocean_v_mariana_depth_material.set_shader_parameter("abyss_depth_m", OCEAN_DEPTH_DEFAULT_ABYSS_DEPTH_M)
	_ocean_v_mariana_depth_sprites = _load_depth_sprites(_ocean_v_mariana_depth_material, OCEAN_V_Z_INDEX + 1, "sea_depth_mariana_trench")

	_ocean_v_shallow_material = ShaderMaterial.new()
	_ocean_v_shallow_material.shader = load(SHALLOW_SHADER_PATH)
	_ocean_v_shallow_material.set_shader_parameter("land_margin_km", OCEAN_SHALLOW_DEFAULT_LAND_MARGIN_KM)
	_ocean_v_shallow_material.set_shader_parameter("sea_margin_km", OCEAN_SHALLOW_DEFAULT_SEA_MARGIN_KM)
	_ocean_v_shallow_material.set_shader_parameter("edge_transition_km", OCEAN_SHALLOW_DEFAULT_EDGE_TRANSITION_KM)
	_ocean_v_shallow_material.set_shader_parameter("band_color", OCEAN_SHALLOW_DEFAULT_COLOR)
	# По прямой просьбе пользователя 2026-07-12 — ТОЛЬКО полоса мелководья (не
	# глубина) должна рисоваться ПОВЕРХ провинций (z_index=20, слой "Области
	# (провинции)", клавиша 8), а не под ними, как остальная часть слоя V.
	# 21 — сразу над провинциями, но ниже интерактивных слоёв верхнего
	# уровня (90/95/100).
	_ocean_v_shallow_sprites = _load_shallow_water_sprites(_ocean_v_shallow_material, 21)

	_build_ocean_v_panel()


## Кнопка-пипетка рядом с ColorPickerButton `target` — жмём, потом кликаем
## по карте (см. _eyedropper_target/_unhandled_input) — цвет под курсором
## подставляется в `target` и запускает его color_changed, как обычный выбор
## цвета руками. Используется панелями настроек других слоёв (см. вызовы ниже).
func _make_eyedropper_button(target: ColorPickerButton) -> Button:
	var btn := Button.new()
	btn.text = "🖉"
	btn.tooltip_text = "Пипетка: кликнуть по карте, чтобы взять цвет под курсором"
	btn.custom_minimum_size = Vector2(28, 24)
	btn.toggle_mode = true
	btn.pressed.connect(func() -> void:
		if btn.button_pressed:
			# Только ОДНА пипетка активна разом — если была нажата другая
			# кнопка, снимаем её toggle, иначе визуально останутся "нажаты"
			# сразу две.
			if is_instance_valid(_eyedropper_button) and _eyedropper_button != btn:
				_eyedropper_button.button_pressed = false
			_eyedropper_target = target
			_eyedropper_button = btn
		else:
			_eyedropper_target = null
			_eyedropper_button = null
	)
	return btn


## Панель "Мелководье/Глубина (слой V)" — по прямой просьбе пользователя
## 2026-07-13 ("ползунком двигать градиент глубин по всем уровням"). Та же
## вёрстка/ползунки, что у _build_ocean_shallow_panel (слой 2), НО каждый
## слайдер/цвет пишет сразу в ДВА материала (_ocean_v_depth_material —
## Атлантика/Америки, _ocean_v_mariana_depth_material — Марианская
## впадина) — единый инструмент двигает градиент по всем уровням
## (шельф/склон/глубины/бездна) на ОБОИХ регионах слоя V разом, а не по
## отдельности. Кнопка-пипетка — см. _make_eyedropper_button выше.
func _build_ocean_v_panel() -> void:
	_ocean_v_panel = VBoxContainer.new()
	_ocean_v_panel.offset_left = 960.0
	_ocean_v_panel.offset_top = 220.0
	_ocean_v_panel.offset_right = 1416.0
	_ocean_v_panel.offset_bottom = 940.0
	_ocean_v_panel.visible = false
	$UI.add_child(_ocean_v_panel)

	var title := Label.new()
	title.add_theme_color_override("font_color", Color(1, 1, 1))
	title.text = "Мелководье / Глубина (слой V)"
	_ocean_v_panel.add_child(title)

	var color_row := HBoxContainer.new()
	var color_label := Label.new()
	color_label.custom_minimum_size = Vector2(280, 0)
	color_label.add_theme_color_override("font_color", Color(1, 1, 1))
	color_label.text = "Цвет мелководья"
	var color_picker := ColorPickerButton.new()
	color_picker.color = OCEAN_SHALLOW_DEFAULT_COLOR
	color_picker.custom_minimum_size = Vector2(80, 24)
	color_picker.color_changed.connect(func(color: Color) -> void:
		if _ocean_v_shallow_material:
			_ocean_v_shallow_material.set_shader_parameter("band_color", color)
	)
	color_row.add_child(color_label)
	color_row.add_child(color_picker)
	color_row.add_child(_make_eyedropper_button(color_picker))
	_ocean_v_panel.add_child(color_row)

	var base_color_row := HBoxContainer.new()
	var base_color_label := Label.new()
	base_color_label.custom_minimum_size = Vector2(280, 0)
	base_color_label.add_theme_color_override("font_color", Color(1, 1, 1))
	base_color_label.text = "Базовая заливка V = цвет мелководья"
	var base_color_check := CheckBox.new()
	base_color_check.button_pressed = true
	base_color_check.add_theme_color_override("font_color", Color(1, 1, 1))
	base_color_row.add_child(base_color_label)
	base_color_row.add_child(base_color_check)
	_ocean_v_panel.add_child(base_color_row)

	color_picker.color_changed.connect(func(color: Color) -> void:
		if base_color_check.button_pressed and is_instance_valid(_ocean_v_provider):
			_ocean_v_provider.set_color(color)
	)

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
		if _ocean_v_shallow_material:
			_ocean_v_shallow_material.set_shader_parameter("land_margin_km", value)
		land_label.text = "Заход на сушу: %.1f км" % value
	)
	land_row.add_child(land_label)
	land_row.add_child(land_slider)
	_ocean_v_panel.add_child(land_row)

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
		if _ocean_v_shallow_material:
			_ocean_v_shallow_material.set_shader_parameter("sea_margin_km", value)
		sea_label.text = "Ширина в море: %.1f км" % value
	)
	sea_row.add_child(sea_label)
	sea_row.add_child(sea_slider)
	_ocean_v_panel.add_child(sea_row)

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
		if _ocean_v_shallow_material:
			_ocean_v_shallow_material.set_shader_parameter("edge_transition_km", value)
		edge_label.text = "Плавность края (море): %.1f км" % value
	)
	edge_row.add_child(edge_label)
	edge_row.add_child(edge_slider)
	_ocean_v_panel.add_child(edge_row)

	var depth_title := Label.new()
	depth_title.add_theme_color_override("font_color", Color(1, 1, 1))
	depth_title.text = "Шельф / Склон / Глубины / Бездна"
	_ocean_v_panel.add_child(depth_title)

	var shelf_color_row := HBoxContainer.new()
	var shelf_color_label := Label.new()
	shelf_color_label.custom_minimum_size = Vector2(280, 0)
	shelf_color_label.add_theme_color_override("font_color", Color(1, 1, 1))
	shelf_color_label.text = "Цвет: Шельф"
	var shelf_color_picker := ColorPickerButton.new()
	shelf_color_picker.color = OCEAN_DEPTH_DEFAULT_SHELF_COLOR
	shelf_color_picker.custom_minimum_size = Vector2(80, 24)
	shelf_color_picker.color_changed.connect(func(color: Color) -> void:
		if _ocean_v_depth_material:
			_ocean_v_depth_material.set_shader_parameter("color_shelf", color)
		if _ocean_v_mariana_depth_material:
			_ocean_v_mariana_depth_material.set_shader_parameter("color_shelf", color)
	)
	shelf_color_row.add_child(shelf_color_label)
	shelf_color_row.add_child(shelf_color_picker)
	shelf_color_row.add_child(_make_eyedropper_button(shelf_color_picker))
	_ocean_v_panel.add_child(shelf_color_row)

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
		if _ocean_v_depth_material:
			_ocean_v_depth_material.set_shader_parameter("gradient_gamma", value)
		if _ocean_v_mariana_depth_material:
			_ocean_v_mariana_depth_material.set_shader_parameter("gradient_gamma", value)
		gamma_label.text = "Кривизна градиента: %.2f" % value
	)
	gamma_row.add_child(gamma_label)
	gamma_row.add_child(gamma_slider)
	_ocean_v_panel.add_child(gamma_row)

	var mid_color_row := HBoxContainer.new()
	var mid_color_label := Label.new()
	mid_color_label.custom_minimum_size = Vector2(280, 0)
	mid_color_label.add_theme_color_override("font_color", Color(1, 1, 1))
	mid_color_label.text = "Цвет: Склон (3-й уровень)"
	var mid_color_picker := ColorPickerButton.new()
	mid_color_picker.color = OCEAN_DEPTH_DEFAULT_MID_COLOR
	mid_color_picker.custom_minimum_size = Vector2(80, 24)
	mid_color_picker.color_changed.connect(func(color: Color) -> void:
		if _ocean_v_depth_material:
			_ocean_v_depth_material.set_shader_parameter("color_mid", color)
		if _ocean_v_mariana_depth_material:
			_ocean_v_mariana_depth_material.set_shader_parameter("color_mid", color)
	)
	mid_color_row.add_child(mid_color_label)
	mid_color_row.add_child(mid_color_picker)
	mid_color_row.add_child(_make_eyedropper_button(mid_color_picker))
	_ocean_v_panel.add_child(mid_color_row)

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
		if _ocean_v_depth_material:
			_ocean_v_depth_material.set_shader_parameter("mid_point", value)
		if _ocean_v_mariana_depth_material:
			_ocean_v_mariana_depth_material.set_shader_parameter("mid_point", value)
		mid_point_label.text = "Положение склона: %.2f" % value
	)
	mid_point_row.add_child(mid_point_label)
	mid_point_row.add_child(mid_point_slider)
	_ocean_v_panel.add_child(mid_point_row)

	var deep_color_row := HBoxContainer.new()
	var deep_color_label := Label.new()
	deep_color_label.custom_minimum_size = Vector2(280, 0)
	deep_color_label.add_theme_color_override("font_color", Color(1, 1, 1))
	deep_color_label.text = "Цвет: Глубины моря"
	var deep_color_picker := ColorPickerButton.new()
	deep_color_picker.color = OCEAN_DEPTH_DEFAULT_DEEP_COLOR
	deep_color_picker.custom_minimum_size = Vector2(80, 24)
	deep_color_picker.color_changed.connect(func(color: Color) -> void:
		if _ocean_v_depth_material:
			_ocean_v_depth_material.set_shader_parameter("color_deep", color)
		if _ocean_v_mariana_depth_material:
			_ocean_v_mariana_depth_material.set_shader_parameter("color_deep", color)
	)
	deep_color_row.add_child(deep_color_label)
	deep_color_row.add_child(deep_color_picker)
	deep_color_row.add_child(_make_eyedropper_button(deep_color_picker))
	_ocean_v_panel.add_child(deep_color_row)

	# 4-й уровень "бездна" (>9000м, см. sea_depth_zones.gdshader) — НОВЫЙ по
	# прямой просьбе пользователя 2026-07-13, добавлен в тот же инструмент,
	# что и остальные уровни. Порог abyss_depth_m — АБСОЛЮТНЫЕ метры (не доля
	# кривой), реально сдвигает границу бездны только у
	# _ocean_v_mariana_depth_material (max_depth_m=11000 там) — у
	# _ocean_v_depth_material (max_depth_m=6000, Атлантика) порог всё равно
	# недостижим, но параметр пишется в оба материала для единообразия.
	var abyss_color_row := HBoxContainer.new()
	var abyss_color_label := Label.new()
	abyss_color_label.custom_minimum_size = Vector2(280, 0)
	abyss_color_label.add_theme_color_override("font_color", Color(1, 1, 1))
	abyss_color_label.text = "Цвет: Бездна (>9000м)"
	var abyss_color_picker := ColorPickerButton.new()
	abyss_color_picker.color = OCEAN_DEPTH_DEFAULT_ABYSS_COLOR
	abyss_color_picker.custom_minimum_size = Vector2(80, 24)
	abyss_color_picker.color_changed.connect(func(color: Color) -> void:
		if _ocean_v_depth_material:
			_ocean_v_depth_material.set_shader_parameter("color_abyss", color)
		if _ocean_v_mariana_depth_material:
			_ocean_v_mariana_depth_material.set_shader_parameter("color_abyss", color)
	)
	abyss_color_row.add_child(abyss_color_label)
	abyss_color_row.add_child(abyss_color_picker)
	abyss_color_row.add_child(_make_eyedropper_button(abyss_color_picker))
	_ocean_v_panel.add_child(abyss_color_row)

	var abyss_depth_row := HBoxContainer.new()
	var abyss_depth_label := Label.new()
	abyss_depth_label.custom_minimum_size = Vector2(280, 0)
	abyss_depth_label.add_theme_color_override("font_color", Color(1, 1, 1))
	abyss_depth_label.text = "Порог бездны: %d м" % int(OCEAN_DEPTH_DEFAULT_ABYSS_DEPTH_M)
	var abyss_depth_slider := HSlider.new()
	abyss_depth_slider.min_value = 1000.0
	abyss_depth_slider.max_value = 11000.0
	abyss_depth_slider.step = 100.0
	abyss_depth_slider.value = OCEAN_DEPTH_DEFAULT_ABYSS_DEPTH_M
	abyss_depth_slider.custom_minimum_size = Vector2(220, 0)
	abyss_depth_slider.value_changed.connect(func(value: float) -> void:
		if _ocean_v_depth_material:
			_ocean_v_depth_material.set_shader_parameter("abyss_depth_m", value)
		if _ocean_v_mariana_depth_material:
			_ocean_v_mariana_depth_material.set_shader_parameter("abyss_depth_m", value)
		abyss_depth_label.text = "Порог бездны: %d м" % int(value)
	)
	abyss_depth_row.add_child(abyss_depth_label)
	abyss_depth_row.add_child(abyss_depth_slider)
	_ocean_v_panel.add_child(abyss_depth_row)


func _apply_cells_test_provider_style() -> void:
	if not is_instance_valid(_cells_test_provider):
		return
	_cells_test_provider.set_uniform_fill_color(_cells_test_fill_color)
	_cells_test_provider.set_border_color(_cells_test_border_color)
	_cells_test_provider.set_border_width(_cells_test_border_width)
	_cells_test_provider.set_border_feather(_cells_test_border_blur)
	_clear_layer_tiles(_cells_test_layer_idx)


func _apply_cells_test_selected_style() -> void:
	if not is_instance_valid(_selected_cell_overlay):
		return
	if _selected_cell_overlay_layer_idx != _cells_test_layer_idx:
		return
	_selected_cell_overlay_fill_override = _cells_test_selected_fill_color
	_selected_cell_overlay.set_style(
		_cells_test_selected_fill_color,
		_cells_test_selected_outline_color,
		_cells_test_selected_outline_width,
		_cells_test_selected_outline_blur)


func _build_cell_boundary_tool_panel(ui_layer: CanvasLayer) -> void:
	_cell_boundary_tool_panel = VBoxContainer.new()
	_cell_boundary_tool_panel.offset_left = 1440.0
	_cell_boundary_tool_panel.offset_top = 720.0
	_cell_boundary_tool_panel.offset_right = 1896.0
	_cell_boundary_tool_panel.offset_bottom = 980.0
	_cell_boundary_tool_panel.visible = false
	ui_layer.add_child(_cell_boundary_tool_panel)

	var toggle_button := Button.new()
	toggle_button.text = "Карандаш клеток ▼"
	toggle_button.toggle_mode = true
	toggle_button.button_pressed = true
	toggle_button.pressed.connect(func() -> void:
		_cell_boundary_tool_collapsed = not toggle_button.button_pressed
		if is_instance_valid(_cell_boundary_tool_content):
			_cell_boundary_tool_content.visible = not _cell_boundary_tool_collapsed
		toggle_button.text = "Карандаш клеток %s" % ("▶" if _cell_boundary_tool_collapsed else "▼")
	)
	_cell_boundary_tool_panel.add_child(toggle_button)

	_cell_boundary_tool_content = VBoxContainer.new()
	_cell_boundary_tool_panel.add_child(_cell_boundary_tool_content)

	var pencil_check := CheckBox.new()
	pencil_check.text = "Карандаш"
	pencil_check.add_theme_color_override("font_color", Color(1, 1, 1))
	pencil_check.toggled.connect(func(pressed: bool) -> void:
		if is_instance_valid(_cell_boundary_draft_layer):
			_cell_boundary_draft_layer.active = pressed
		_update_cell_boundary_tool_status()
	)
	_cell_boundary_tool_content.add_child(pencil_check)

	var finish_button := Button.new()
	finish_button.text = "Завершить линию"
	finish_button.pressed.connect(func() -> void:
		if is_instance_valid(_cell_boundary_draft_layer):
			_cell_boundary_draft_layer.finish_stroke()
		_update_cell_boundary_tool_status()
	)
	_cell_boundary_tool_content.add_child(finish_button)

	var undo_button := Button.new()
	undo_button.text = "Назад"
	undo_button.pressed.connect(func() -> void:
		if is_instance_valid(_cell_boundary_draft_layer):
			_cell_boundary_draft_layer.undo_last_point()
		_update_cell_boundary_tool_status()
	)
	_cell_boundary_tool_content.add_child(undo_button)

	var clear_button := Button.new()
	clear_button.text = "Очистить черновик"
	clear_button.pressed.connect(func() -> void:
		if is_instance_valid(_cell_boundary_draft_layer):
			_cell_boundary_draft_layer.clear_all()
		_update_cell_boundary_tool_status()
	)
	_cell_boundary_tool_content.add_child(clear_button)

	var save_button := Button.new()
	save_button.text = "Сохранить линии"
	save_button.pressed.connect(func() -> void:
		var n := 0
		if is_instance_valid(_cell_boundary_draft_layer):
			_cell_boundary_draft_layer.finish_stroke()
			n = _cell_boundary_draft_layer.save_to_file()
		if is_instance_valid(_cell_boundary_tool_status):
			_cell_boundary_tool_status.text = "Сохранено линий: %d" % n
	)
	_cell_boundary_tool_content.add_child(save_button)

	_cell_boundary_tool_status = Label.new()
	_cell_boundary_tool_status.add_theme_color_override("font_color", Color(1, 1, 1))
	_cell_boundary_tool_status.add_theme_font_size_override("font_size", 13)
	_cell_boundary_tool_content.add_child(_cell_boundary_tool_status)
	_update_cell_boundary_tool_status()

	var style_sep := HSeparator.new()
	_cell_boundary_tool_content.add_child(style_sep)

	var border_color_row := HBoxContainer.new()
	var border_color_label := Label.new()
	border_color_label.custom_minimum_size = Vector2(260, 0)
	border_color_label.add_theme_color_override("font_color", Color(1, 1, 1))
	border_color_label.text = "Цвет контура"
	var border_color_picker := ColorPickerButton.new()
	border_color_picker.color = _cells_test_border_color
	border_color_picker.custom_minimum_size = Vector2(80, 24)
	border_color_picker.color_changed.connect(func(color: Color) -> void:
		_cells_test_border_color.r = color.r
		_cells_test_border_color.g = color.g
		_cells_test_border_color.b = color.b
		_apply_cells_test_provider_style()
	)
	border_color_row.add_child(border_color_label)
	border_color_row.add_child(border_color_picker)
	_cell_boundary_tool_content.add_child(border_color_row)

	var border_alpha_row := HBoxContainer.new()
	var border_alpha_label := Label.new()
	border_alpha_label.custom_minimum_size = Vector2(260, 0)
	border_alpha_label.add_theme_color_override("font_color", Color(1, 1, 1))
	border_alpha_label.text = "Прозрачность контура: %.2f" % _cells_test_border_color.a
	var border_alpha_slider := HSlider.new()
	border_alpha_slider.min_value = 0.0
	border_alpha_slider.max_value = 1.0
	border_alpha_slider.step = 0.01
	border_alpha_slider.value = _cells_test_border_color.a
	border_alpha_slider.custom_minimum_size = Vector2(170, 0)
	border_alpha_slider.value_changed.connect(func(value: float) -> void:
		_cells_test_border_color.a = value
		border_alpha_label.text = "Прозрачность контура: %.2f" % value
		_apply_cells_test_provider_style()
	)
	border_alpha_row.add_child(border_alpha_label)
	border_alpha_row.add_child(border_alpha_slider)
	_cell_boundary_tool_content.add_child(border_alpha_row)

	var fill_alpha_row := HBoxContainer.new()
	var fill_alpha_label := Label.new()
	fill_alpha_label.custom_minimum_size = Vector2(260, 0)
	fill_alpha_label.add_theme_color_override("font_color", Color(1, 1, 1))
	fill_alpha_label.text = "Прозрачность заливки: %.2f" % _cells_test_fill_color.a
	var fill_alpha_slider := HSlider.new()
	fill_alpha_slider.min_value = 0.0
	fill_alpha_slider.max_value = 0.8
	fill_alpha_slider.step = 0.01
	fill_alpha_slider.value = _cells_test_fill_color.a
	fill_alpha_slider.custom_minimum_size = Vector2(170, 0)
	fill_alpha_slider.value_changed.connect(func(value: float) -> void:
		_cells_test_fill_color.a = value
		fill_alpha_label.text = "Прозрачность заливки: %.2f" % value
		_apply_cells_test_provider_style()
	)
	fill_alpha_row.add_child(fill_alpha_label)
	fill_alpha_row.add_child(fill_alpha_slider)
	_cell_boundary_tool_content.add_child(fill_alpha_row)

	var width_row := HBoxContainer.new()
	var width_label := Label.new()
	width_label.custom_minimum_size = Vector2(260, 0)
	width_label.add_theme_color_override("font_color", Color(1, 1, 1))
	width_label.text = "Толщина контура: %.2f" % _cells_test_border_width
	var width_slider := HSlider.new()
	width_slider.min_value = 0.0
	width_slider.max_value = 1.2
	width_slider.step = 0.01
	width_slider.value = _cells_test_border_width
	width_slider.custom_minimum_size = Vector2(170, 0)
	width_slider.value_changed.connect(func(value: float) -> void:
		_cells_test_border_width = value
		width_label.text = "Толщина контура: %.2f" % value
		_apply_cells_test_provider_style()
	)
	width_row.add_child(width_label)
	width_row.add_child(width_slider)
	_cell_boundary_tool_content.add_child(width_row)

	var blur_row := HBoxContainer.new()
	var blur_label := Label.new()
	blur_label.custom_minimum_size = Vector2(260, 0)
	blur_label.add_theme_color_override("font_color", Color(1, 1, 1))
	blur_label.text = "Размытость контура: %.1f" % _cells_test_border_blur
	var blur_slider := HSlider.new()
	blur_slider.min_value = 0.01
	blur_slider.max_value = 8.0
	blur_slider.step = 0.1
	blur_slider.value = _cells_test_border_blur
	blur_slider.custom_minimum_size = Vector2(170, 0)
	blur_slider.value_changed.connect(func(value: float) -> void:
		_cells_test_border_blur = value
		blur_label.text = "Размытость контура: %.1f" % value
		_apply_cells_test_provider_style()
	)
	blur_row.add_child(blur_label)
	blur_row.add_child(blur_slider)
	_cell_boundary_tool_content.add_child(blur_row)

	var selected_color_row := HBoxContainer.new()
	var selected_color_label := Label.new()
	selected_color_label.custom_minimum_size = Vector2(260, 0)
	selected_color_label.add_theme_color_override("font_color", Color(1, 1, 1))
	selected_color_label.text = "Цвет выделения"
	var selected_color_picker := ColorPickerButton.new()
	selected_color_picker.color = _cells_test_selected_outline_color
	selected_color_picker.custom_minimum_size = Vector2(80, 24)
	selected_color_picker.color_changed.connect(func(color: Color) -> void:
		_cells_test_selected_outline_color.r = color.r
		_cells_test_selected_outline_color.g = color.g
		_cells_test_selected_outline_color.b = color.b
		_apply_cells_test_selected_style()
	)
	selected_color_row.add_child(selected_color_label)
	selected_color_row.add_child(selected_color_picker)
	_cell_boundary_tool_content.add_child(selected_color_row)

	var selected_fill_alpha_row := HBoxContainer.new()
	var selected_fill_alpha_label := Label.new()
	selected_fill_alpha_label.custom_minimum_size = Vector2(260, 0)
	selected_fill_alpha_label.add_theme_color_override("font_color", Color(1, 1, 1))
	selected_fill_alpha_label.text = "Заливка выделения: %.2f" % _cells_test_selected_fill_color.a
	var selected_fill_alpha_slider := HSlider.new()
	selected_fill_alpha_slider.min_value = 0.0
	selected_fill_alpha_slider.max_value = 0.8
	selected_fill_alpha_slider.step = 0.01
	selected_fill_alpha_slider.value = _cells_test_selected_fill_color.a
	selected_fill_alpha_slider.custom_minimum_size = Vector2(170, 0)
	selected_fill_alpha_slider.value_changed.connect(func(value: float) -> void:
		_cells_test_selected_fill_color.a = value
		selected_fill_alpha_label.text = "Заливка выделения: %.2f" % value
		_apply_cells_test_selected_style()
	)
	selected_fill_alpha_row.add_child(selected_fill_alpha_label)
	selected_fill_alpha_row.add_child(selected_fill_alpha_slider)
	_cell_boundary_tool_content.add_child(selected_fill_alpha_row)

	var selected_width_row := HBoxContainer.new()
	var selected_width_label := Label.new()
	selected_width_label.custom_minimum_size = Vector2(260, 0)
	selected_width_label.add_theme_color_override("font_color", Color(1, 1, 1))
	selected_width_label.text = "Толщина выделения: %.1f px" % _cells_test_selected_outline_width
	var selected_width_slider := HSlider.new()
	selected_width_slider.min_value = 0.0
	selected_width_slider.max_value = 8.0
	selected_width_slider.step = 0.1
	selected_width_slider.value = _cells_test_selected_outline_width
	selected_width_slider.custom_minimum_size = Vector2(170, 0)
	selected_width_slider.value_changed.connect(func(value: float) -> void:
		_cells_test_selected_outline_width = value
		selected_width_label.text = "Толщина выделения: %.1f px" % value
		_apply_cells_test_selected_style()
	)
	selected_width_row.add_child(selected_width_label)
	selected_width_row.add_child(selected_width_slider)
	_cell_boundary_tool_content.add_child(selected_width_row)

	var selected_blur_row := HBoxContainer.new()
	var selected_blur_label := Label.new()
	selected_blur_label.custom_minimum_size = Vector2(260, 0)
	selected_blur_label.add_theme_color_override("font_color", Color(1, 1, 1))
	selected_blur_label.text = "Размытость выделения: %.1f px" % _cells_test_selected_outline_blur
	var selected_blur_slider := HSlider.new()
	selected_blur_slider.min_value = 0.0
	selected_blur_slider.max_value = 8.0
	selected_blur_slider.step = 0.1
	selected_blur_slider.value = _cells_test_selected_outline_blur
	selected_blur_slider.custom_minimum_size = Vector2(170, 0)
	selected_blur_slider.value_changed.connect(func(value: float) -> void:
		_cells_test_selected_outline_blur = value
		selected_blur_label.text = "Размытость выделения: %.1f px" % value
		_apply_cells_test_selected_style()
	)
	selected_blur_row.add_child(selected_blur_label)
	selected_blur_row.add_child(selected_blur_slider)
	_cell_boundary_tool_content.add_child(selected_blur_row)


func _update_cell_boundary_tool_status() -> void:
	if not is_instance_valid(_cell_boundary_tool_status):
		return
	if not is_instance_valid(_cell_boundary_draft_layer):
		_cell_boundary_tool_status.text = ""
		return
	var mode := "вкл" if _cell_boundary_draft_layer.active else "выкл"
	_cell_boundary_tool_status.text = "Карандаш: %s, линий: %d" % [mode, _cell_boundary_draft_layer.get_stroke_count()]


func _unhandled_input(event: InputEvent) -> void:
	# Пипетка панели слоя V — ПЕРВЫМ делом, до кликов по клеткам/провинциям
	# (см. _eyedropper_target выше): пока активна, следующий ЛКМ забирает
	# цвет экрана под курсором и НЕ идёт дальше в обычные обработчики клика.
	if _eyedropper_target != null and event is InputEventMouseButton \
			and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		var screen_img := get_viewport().get_texture().get_image()
		var mp := get_viewport().get_mouse_position()
		var px := clampi(int(mp.x), 0, screen_img.get_width() - 1)
		var py := clampi(int(mp.y), 0, screen_img.get_height() - 1)
		var picked := screen_img.get_pixel(px, py)
		var target := _eyedropper_target
		_eyedropper_target = null
		if is_instance_valid(_eyedropper_button):
			_eyedropper_button.button_pressed = false
		_eyedropper_button = null
		target.color = picked
		target.color_changed.emit(picked)
		get_viewport().set_input_as_handled()
		return

	# Перетаскивание маркера города (см. ProvinceCityMarkersLayer.gd) —
	# ТОЖЕ первым делом, до кликов по клеткам/провинциям (тот же приём, что
	# у пипетки выше): начало/продолжение/конец перетаскивания полностью
	# "съедают" событие, чтобы клик по маркеру не проваливался в клик по
	# провинции под ним.
	if is_instance_valid(_province_city_markers) and is_instance_valid(camera):
		if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
			if event.pressed:
				if _province_city_markers.try_begin_drag(camera.get_global_mouse_position()):
					_dragging_city_marker = true
					get_viewport().set_input_as_handled()
					return
			elif _dragging_city_marker:
				_dragging_city_marker = false
				_province_city_markers.end_drag()
				get_viewport().set_input_as_handled()
				return
		elif event is InputEventMouseMotion and _dragging_city_marker:
			_province_city_markers.update_drag(camera.get_global_mouse_position())
			get_viewport().set_input_as_handled()
			return

	if is_instance_valid(_cell_boundary_draft_layer) \
			and _cell_boundary_draft_layer.active \
			and _cells_test_layer_idx >= 0 and _cells_test_layer_idx < _layers.size() \
			and _layers[_cells_test_layer_idx]["visible"] \
			and is_instance_valid(camera):
		if event is InputEventMouseButton:
			if event.button_index == MOUSE_BUTTON_LEFT:
				if event.pressed:
					_cell_boundary_draft_layer.begin_freehand_stroke(camera.get_global_mouse_position())
				else:
					_cell_boundary_draft_layer.end_freehand_stroke()
				_update_cell_boundary_tool_status()
				get_viewport().set_input_as_handled()
				return
			if event.pressed and event.button_index == MOUSE_BUTTON_RIGHT:
				_cell_boundary_draft_layer.finish_stroke()
				_update_cell_boundary_tool_status()
				get_viewport().set_input_as_handled()
				return
		if event is InputEventMouseMotion:
			_cell_boundary_draft_layer.add_freehand_point(camera.get_global_mouse_position())
			get_viewport().set_input_as_handled()
			return
		if event is InputEventKey and event.pressed and not event.echo:
			if event.physical_keycode == KEY_ESCAPE:
				_cell_boundary_draft_layer.clear_current()
				_update_cell_boundary_tool_status()
				get_viewport().set_input_as_handled()
				return
			if event.physical_keycode == KEY_ENTER:
				_cell_boundary_draft_layer.finish_stroke()
				_update_cell_boundary_tool_status()
				get_viewport().set_input_as_handled()
				return

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
		# Клавиша O СВОБОДНА — была у удалённого слоя "Зоны Иберии" (уровень
		# "Зона" убран из игровой лестницы территорий по решению пользователя,
		# см. CLAUDE.md/УРОВНЕЙ_ТЕРРИТОРИЙ.md).
		match event.physical_keycode:
			KEY_1: idx = 0
			KEY_6: idx = 1
			KEY_0: idx = 2
			KEY_MINUS: idx = 3
			KEY_EQUAL: idx = 4
			KEY_8: idx = _world_provinces_layer_idx
			KEY_C: idx = _cells_test_layer_idx
			# Клавиша 2 ПЕРЕКЛЮЧЕНА (2026-07-13, задача "заменить старый слой 2
			# запечённой версией слоя V") со старого живого/полу-запечённого
			# "Мировой океан" (_ocean_layer_idx, удалён вместе с регистрацией/
			# живым оверлеем/панелью) на НОВЫЙ запечённый комплект
			# base_depth+shallow (см. assets/config/ocean_v_bake_profile.json,
			# scripts/tools/bake_ocean_v_*.py). Визуальное сравнение с живым V
			# подтверждено пользователем.
			KEY_2: idx = _ocean_v_baked_base_depth_layer_idx
			KEY_B: idx = _ocean_flat_layer_idx
			KEY_V: idx = _ocean_v_layer_idx
			KEY_4: idx = _provinces_iberia_layer_idx
			KEY_7: idx = _iberia_land_cells_layer_idx
			KEY_I: idx = _regions_iberia_layer_idx
			KEY_G: idx = _cells_lacoruna_grid_layer_idx
			KEY_N: idx = _netherlands_provinces_layer_idx
			KEY_9: idx = _water_cells_layer_idx
		if event.physical_keycode == KEY_5 and is_instance_valid(_sea_zones):
			_sea_zones.set_active(not _sea_zones.visible)
		if idx >= 0 and idx < _layers.size():
			_layers[idx]["visible"] = not _layers[idx]["visible"]
			# Регионы Иберии используют слой 4 как основу: при включении
			# автоматически поднимаем провинциальную карту под цветной overlay.
			if idx == _regions_iberia_layer_idx and _layers[idx]["visible"] \
					and _provinces_iberia_layer_idx >= 0 and _provinces_iberia_layer_idx < _layers.size():
				_layers[_provinces_iberia_layer_idx]["visible"] = true
			# Клавиша 2 (запечённый комплект base_depth+shallow) при включении
			# заодно включает мелководье И "Реки" (индекс 4, см. KEY_EQUAL
			# выше) — по просьбе пользователя показывать всю воду (океан+
			# мелководье+реки) сразу одной клавишей, та же логика, что была у
			# старого _ocean_layer_idx.
			if idx == _ocean_v_baked_base_depth_layer_idx:
				if _ocean_v_baked_shallow_layer_idx >= 0 and _ocean_v_baked_shallow_layer_idx < _layers.size():
					_layers[_ocean_v_baked_shallow_layer_idx]["visible"] = _layers[idx]["visible"]
				if 4 < _layers.size():
					_layers[4]["visible"] = _layers[idx]["visible"]

	if event is InputEventMouseButton and event.pressed \
			and event.button_index == MOUSE_BUTTON_LEFT \
			and not (is_instance_valid(_mark_tool) and _mark_tool.active) \
			and is_instance_valid(camera):
		var click_pos := camera.get_global_mouse_position()
		if _cells_test_layer_idx >= 0 and _cells_test_layer_idx < _layers.size() \
				and _layers[_cells_test_layer_idx]["visible"] \
				and _try_pick_cell(click_pos):
			return
		if _iberia_land_cells_layer_idx >= 0 and _iberia_land_cells_layer_idx < _layers.size() \
				and _layers[_iberia_land_cells_layer_idx]["visible"] \
				and is_instance_valid(_iberia_land_cells_provider) \
				and _try_pick_iberia_land_cell(click_pos):
			return
		if _water_cells_layer_idx >= 0 and _water_cells_layer_idx < _layers.size() \
				and _layers[_water_cells_layer_idx]["visible"] \
				and is_instance_valid(_water_cells_provider) \
				and _try_pick_water_cell(click_pos):
			return
		if _netherlands_provinces_layer_idx >= 0 and _netherlands_provinces_layer_idx < _layers.size() \
				and _layers[_netherlands_provinces_layer_idx]["visible"] \
				and is_instance_valid(_netherlands_provinces_provider) \
				and _try_pick_netherlands_province(click_pos):
			return
		if _provinces_iberia_layer_idx >= 0 and _provinces_iberia_layer_idx < _layers.size() \
				and _layers[_provinces_iberia_layer_idx]["visible"] \
				and is_instance_valid(_provinces_iberia_provider) \
				and _try_pick_province(click_pos):
			return
		if _world_provinces_layer_idx >= 0 and _world_provinces_layer_idx < _layers.size() \
				and _layers[_world_provinces_layer_idx]["visible"] \
				and is_instance_valid(_world_provinces_provider) \
				and _try_pick_world_province(click_pos):
			return


## Кнопка "Сохранить города" (прямая просьба пользователя 2026-07-13) —
## перетаскивание маркера мышкой уже двигает его сразу (см. try_begin_drag/
## update_drag в ProvinceCityMarkersLayer.gd), кнопка нужна только чтобы
## записать текущие позиции ВСЕХ маркеров обратно в
## assets/province_cities_iberia.json (иначе правка пропадёт при
## следующем запуске игры).
func _build_city_markers_panel(ui_layer: CanvasLayer) -> void:
	var panel := VBoxContainer.new()
	panel.offset_left = 1440.0
	panel.offset_top = 20.0
	panel.offset_right = 1896.0
	panel.offset_bottom = 90.0
	ui_layer.add_child(panel)

	var title := Label.new()
	title.add_theme_color_override("font_color", Color(1.0, 0.92, 0.72, 1.0))
	title.text = "Города провинций (слой 4)"
	panel.add_child(title)

	var hint := Label.new()
	hint.add_theme_font_size_override("font_size", 13)
	hint.text = "ЛКМ на маркере — потянуть; отпустить — новое место"
	panel.add_child(hint)

	var save_button := Button.new()
	save_button.text = "Сохранить города"
	save_button.pressed.connect(func():
		var n := 0
		if is_instance_valid(_province_city_markers):
			n = _province_city_markers.save_to_file()
		_city_markers_status_label.text = "Сохранено городов: %d" % n
	)
	panel.add_child(save_button)

	_city_markers_status_label = Label.new()
	_city_markers_status_label.add_theme_font_size_override("font_size", 13)
	_city_markers_status_label.text = ""
	panel.add_child(_city_markers_status_label)


## Панель "Шрифт городов" (слой 4) — прямая просьба пользователя 2026-07-13:
## живая правка шрифта/размера/цвета подписей городов. Шторка (сворачивание)
## — тот же приём toggle-кнопки, что у _build_selection_style_panel.
## Все контролы применяются сразу через ProvinceCityMarkersLayer.apply_label_*,
## без пересоздания узлов — перетаскивание (см. _build_city_markers_panel)
## продолжает работать как раньше.
func _build_city_font_panel(ui_layer: CanvasLayer) -> void:
	_city_font_panel = VBoxContainer.new()
	_city_font_panel.offset_left = 1440.0
	_city_font_panel.offset_top = 100.0
	_city_font_panel.offset_right = 1896.0
	_city_font_panel.offset_bottom = 500.0
	ui_layer.add_child(_city_font_panel)

	var toggle_button := Button.new()
	toggle_button.text = "Шрифт городов ▼"
	toggle_button.toggle_mode = true
	toggle_button.button_pressed = true
	toggle_button.pressed.connect(func() -> void:
		_city_font_collapsed = not toggle_button.button_pressed
		if is_instance_valid(_city_font_content):
			_city_font_content.visible = not _city_font_collapsed
		toggle_button.text = "Шрифт городов %s" % ("▶" if _city_font_collapsed else "▼")
	)
	_city_font_panel.add_child(toggle_button)

	_city_font_content = VBoxContainer.new()
	_city_font_panel.add_child(_city_font_content)

	# Выбор гарнитуры.
	var font_row := HBoxContainer.new()
	var font_label := Label.new()
	font_label.custom_minimum_size = Vector2(120, 0)
	font_label.add_theme_color_override("font_color", Color(1, 1, 1))
	font_label.text = "Шрифт"
	var font_option := OptionButton.new()
	font_option.custom_minimum_size = Vector2(200, 0)
	for font_name in CITY_LABEL_FONTS.keys():
		font_option.add_item(font_name)
	font_option.item_selected.connect(func(idx: int) -> void:
		var font_name: String = font_option.get_item_text(idx)
		var font_path: String = CITY_LABEL_FONTS[font_name]
		var font: Font = load(font_path) if not font_path.is_empty() else ThemeDB.fallback_font
		if is_instance_valid(_province_city_markers):
			_province_city_markers.apply_label_font(font)
	)
	font_row.add_child(font_label)
	font_row.add_child(font_option)
	_city_font_content.add_child(font_row)

	# Размер шрифта.
	var size_row := HBoxContainer.new()
	var size_label := Label.new()
	size_label.custom_minimum_size = Vector2(260, 0)
	size_label.add_theme_color_override("font_color", Color(1, 1, 1))
	size_label.text = "Размер: 13"
	var size_slider := HSlider.new()
	size_slider.min_value = 6
	size_slider.max_value = 40
	size_slider.step = 1
	size_slider.value = 13
	size_slider.custom_minimum_size = Vector2(170, 0)
	size_slider.value_changed.connect(func(value: float) -> void:
		size_label.text = "Размер: %d" % int(value)
		if is_instance_valid(_province_city_markers):
			_province_city_markers.apply_label_style(
				int(value), _city_label_fill_color, _city_label_outline_color, 0)
	)
	size_row.add_child(size_label)
	size_row.add_child(size_slider)
	_city_font_content.add_child(size_row)

	# Цвет текста.
	var fill_row := HBoxContainer.new()
	var fill_label := Label.new()
	fill_label.custom_minimum_size = Vector2(260, 0)
	fill_label.add_theme_color_override("font_color", Color(1, 1, 1))
	fill_label.text = "Цвет текста"
	var fill_picker := ColorPickerButton.new()
	fill_picker.color = _city_label_fill_color
	fill_picker.custom_minimum_size = Vector2(80, 24)
	fill_picker.color_changed.connect(func(color: Color) -> void:
		_city_label_fill_color = color
		if is_instance_valid(_province_city_markers):
			_province_city_markers.apply_label_style(
				int(size_slider.value), _city_label_fill_color, _city_label_outline_color, 0)
	)
	fill_row.add_child(fill_label)
	fill_row.add_child(fill_picker)
	fill_row.add_child(_make_eyedropper_button(fill_picker))
	_city_font_content.add_child(fill_row)

	# Цвет обводки текста.
	var outline_row := HBoxContainer.new()
	var outline_label := Label.new()
	outline_label.custom_minimum_size = Vector2(260, 0)
	outline_label.add_theme_color_override("font_color", Color(1, 1, 1))
	outline_label.text = "Цвет обводки"
	var outline_picker := ColorPickerButton.new()
	outline_picker.color = _city_label_outline_color
	outline_picker.custom_minimum_size = Vector2(80, 24)
	outline_picker.color_changed.connect(func(color: Color) -> void:
		_city_label_outline_color = color
		if is_instance_valid(_province_city_markers):
			_province_city_markers.apply_label_style(
				int(size_slider.value), _city_label_fill_color, _city_label_outline_color, 0)
	)
	outline_row.add_child(outline_label)
	outline_row.add_child(outline_picker)
	outline_row.add_child(_make_eyedropper_button(outline_picker))
	_city_font_content.add_child(outline_row)

	# Толщина обводки текста.
	var outline_w_row := HBoxContainer.new()
	var outline_w_label := Label.new()
	outline_w_label.custom_minimum_size = Vector2(260, 0)
	outline_w_label.add_theme_color_override("font_color", Color(1, 1, 1))
	outline_w_label.text = "Толщина обводки: авто"
	var outline_w_slider := HSlider.new()
	outline_w_slider.min_value = 0
	outline_w_slider.max_value = 8
	outline_w_slider.step = 1
	outline_w_slider.value = 0
	outline_w_slider.custom_minimum_size = Vector2(170, 0)
	outline_w_slider.value_changed.connect(func(value: float) -> void:
		outline_w_label.text = "Толщина обводки: авто" if value == 0 else "Толщина обводки: %d" % int(value)
		if is_instance_valid(_province_city_markers):
			_province_city_markers.apply_label_style(
				int(size_slider.value), _city_label_fill_color, _city_label_outline_color, int(value))
	)
	outline_w_row.add_child(outline_w_label)
	outline_w_row.add_child(outline_w_slider)
	_city_font_content.add_child(outline_w_row)

	# Курсив (синтетический наклон через FontVariation.variation_transform,
	# см. ProvinceCityMarkerNode._rebuild_font) — работает для любого шрифта
	# из CITY_LABEL_FONTS без отдельных italic-файлов.
	var italic_row := HBoxContainer.new()
	var italic_check := CheckBox.new()
	italic_check.text = "Курсив"
	italic_check.button_pressed = _city_label_italic
	italic_check.toggled.connect(func(pressed: bool) -> void:
		_city_label_italic = pressed
		if is_instance_valid(_province_city_markers):
			_province_city_markers.apply_text_effects(
				_city_label_italic, _city_label_bold_amount, _city_label_spacing_percent)
	)
	italic_row.add_child(italic_check)
	_city_font_content.add_child(italic_row)

	# Жирность (синтетическая, FontVariation.variation_embolden 0..1.2) —
	# единый слайдер для всех шрифтов, включая нестатические (Roboto/Lato/
	# PT Sans Caption), где нет отдельного bold-начертания в assets/fonts/.
	var bold_row := HBoxContainer.new()
	var bold_label := Label.new()
	bold_label.custom_minimum_size = Vector2(260, 0)
	bold_label.add_theme_color_override("font_color", Color(1, 1, 1))
	bold_label.text = "Жирность: 0%"
	var bold_slider := HSlider.new()
	bold_slider.min_value = 0
	bold_slider.max_value = 100
	bold_slider.step = 1
	bold_slider.value = 0
	bold_slider.custom_minimum_size = Vector2(170, 0)
	bold_slider.value_changed.connect(func(value: float) -> void:
		bold_label.text = "Жирность: %d%%" % int(value)
		_city_label_bold_amount = value / 100.0 * 1.2
		if is_instance_valid(_province_city_markers):
			_province_city_markers.apply_text_effects(
				_city_label_italic, _city_label_bold_amount, _city_label_spacing_percent)
	)
	bold_row.add_child(bold_label)
	bold_row.add_child(bold_slider)
	_city_font_content.add_child(bold_row)

	# Разрядка (доп. расстояние между буквами, % от размера шрифта; типичный
	# читаемый диапазон для подписей на карте — 10-16%, прямая просьба
	# пользователя 2026-07-13), см. FontVariation.set_spacing(SPACING_GLYPH).
	var spacing_row := HBoxContainer.new()
	var spacing_label := Label.new()
	spacing_label.custom_minimum_size = Vector2(260, 0)
	spacing_label.add_theme_color_override("font_color", Color(1, 1, 1))
	spacing_label.text = "Разрядка: 0%"
	var spacing_slider := HSlider.new()
	spacing_slider.min_value = 0
	spacing_slider.max_value = 25
	spacing_slider.step = 1
	spacing_slider.value = 0
	spacing_slider.custom_minimum_size = Vector2(170, 0)
	spacing_slider.value_changed.connect(func(value: float) -> void:
		spacing_label.text = "Разрядка: %d%%" % int(value)
		_city_label_spacing_percent = value
		if is_instance_valid(_province_city_markers):
			_province_city_markers.apply_text_effects(
				_city_label_italic, _city_label_bold_amount, _city_label_spacing_percent)
	)
	spacing_row.add_child(spacing_label)
	spacing_row.add_child(spacing_slider)
	_city_font_content.add_child(spacing_row)

	# Дефолт подписи городов (прямая просьба пользователя 2026-07-13):
	# PT Sans Caption/15/#F3E8D2/#33434A/обводка 2px/курсив выкл/жирность
	# 60%/разрядка 5%. set_value_no_signal — чтобы не звать колбэки слайдеров
	# по одному вразнобой с промежуточными значениями; итоговое состояние
	# применяется одним explicit-вызовом apply_* ниже.
	const DEFAULT_FONT_NAME := "PT Sans Caption"
	const DEFAULT_FONT_SIZE := 15
	const DEFAULT_OUTLINE_WIDTH := 2
	const DEFAULT_BOLD_PERCENT := 60.0
	const DEFAULT_SPACING_PERCENT := 5.0
	_city_label_fill_color = Color("F3E8D2")
	_city_label_outline_color = Color("33434A")
	_city_label_italic = false
	_city_label_bold_amount = DEFAULT_BOLD_PERCENT / 100.0 * 1.2
	_city_label_spacing_percent = DEFAULT_SPACING_PERCENT

	for i in font_option.get_item_count():
		if font_option.get_item_text(i) == DEFAULT_FONT_NAME:
			font_option.select(i)
			break
	fill_picker.color = _city_label_fill_color
	outline_picker.color = _city_label_outline_color
	italic_check.button_pressed = false
	size_slider.set_value_no_signal(DEFAULT_FONT_SIZE)
	size_label.text = "Размер: %d" % DEFAULT_FONT_SIZE
	outline_w_slider.set_value_no_signal(DEFAULT_OUTLINE_WIDTH)
	outline_w_label.text = "Толщина обводки: %d" % DEFAULT_OUTLINE_WIDTH
	bold_slider.set_value_no_signal(DEFAULT_BOLD_PERCENT)
	bold_label.text = "Жирность: %d%%" % int(DEFAULT_BOLD_PERCENT)
	spacing_slider.set_value_no_signal(DEFAULT_SPACING_PERCENT)
	spacing_label.text = "Разрядка: %d%%" % int(DEFAULT_SPACING_PERCENT)

	if is_instance_valid(_province_city_markers):
		var default_font_path: String = CITY_LABEL_FONTS[DEFAULT_FONT_NAME]
		_province_city_markers.apply_label_font(load(default_font_path))
		_province_city_markers.apply_label_style(
			DEFAULT_FONT_SIZE, _city_label_fill_color, _city_label_outline_color, DEFAULT_OUTLINE_WIDTH)
		_province_city_markers.apply_text_effects(
			_city_label_italic, _city_label_bold_amount, _city_label_spacing_percent)


func _build_regions_iberia_panel(ui_layer: CanvasLayer) -> void:
	_regions_iberia_panel = VBoxContainer.new()
	_regions_iberia_panel.offset_left = 1440.0
	_regions_iberia_panel.offset_top = 520.0
	_regions_iberia_panel.offset_right = 1896.0
	_regions_iberia_panel.offset_bottom = 640.0
	_regions_iberia_panel.visible = false
	ui_layer.add_child(_regions_iberia_panel)

	var title := Label.new()
	title.add_theme_color_override("font_color", Color(1.0, 0.92, 0.72, 1.0))
	title.text = "Исторические регионы Иберии"
	_regions_iberia_panel.add_child(title)

	var rs: Dictionary = BORDER_STYLE["region"]
	var width_row := HBoxContainer.new()
	var width_label := Label.new()
	width_label.custom_minimum_size = Vector2(260, 0)
	width_label.add_theme_color_override("font_color", Color(1, 1, 1))
	width_label.text = "Толщина границ: %.2f" % float(rs["width"])
	var width_slider := HSlider.new()
	width_slider.min_value = 0.05
	width_slider.max_value = 2.0
	width_slider.step = 0.05
	width_slider.value = float(rs["width"])
	width_slider.custom_minimum_size = Vector2(170, 0)
	width_slider.value_changed.connect(func(value: float) -> void:
		if is_instance_valid(_regions_iberia_provider):
			_regions_iberia_provider.set_border_width(value)
			_clear_layer_tiles(_regions_iberia_layer_idx)
		width_label.text = "Толщина границ: %.2f" % value
	)
	width_row.add_child(width_label)
	width_row.add_child(width_slider)
	_regions_iberia_panel.add_child(width_row)


func _build_provinces_iberia_panel(ui_layer: CanvasLayer) -> void:
	_provinces_iberia_panel = VBoxContainer.new()
	_provinces_iberia_panel.offset_left = 1440.0
	_provinces_iberia_panel.offset_top = 780.0
	_provinces_iberia_panel.offset_right = 1896.0
	_provinces_iberia_panel.offset_bottom = 1020.0
	_provinces_iberia_panel.visible = false
	ui_layer.add_child(_provinces_iberia_panel)

	var title := Label.new()
	title.add_theme_color_override("font_color", Color(1.0, 0.92, 0.72, 1.0))
	title.text = "Провинции Иберии"
	_provinces_iberia_panel.add_child(title)

	var ps: Dictionary = BORDER_STYLE["province"]

	var width_row := HBoxContainer.new()
	var width_label := Label.new()
	width_label.custom_minimum_size = Vector2(260, 0)
	width_label.add_theme_color_override("font_color", Color(1, 1, 1))
	width_label.text = "Толщина контура: %.2f" % float(ps["width"])
	var width_slider := HSlider.new()
	width_slider.min_value = 0.01
	width_slider.max_value = 1.5
	width_slider.step = 0.01
	width_slider.value = float(ps["width"])
	width_slider.custom_minimum_size = Vector2(170, 0)
	width_slider.value_changed.connect(func(value: float) -> void:
		if is_instance_valid(_provinces_iberia_provider):
			_provinces_iberia_provider.set_border_width(value)
			_clear_layer_tiles(_provinces_iberia_layer_idx)
		width_label.text = "Толщина контура: %.2f" % value
	)
	width_row.add_child(width_label)
	width_row.add_child(width_slider)
	_provinces_iberia_panel.add_child(width_row)

	var feather_row := HBoxContainer.new()
	var feather_label := Label.new()
	feather_label.custom_minimum_size = Vector2(260, 0)
	feather_label.add_theme_color_override("font_color", Color(1, 1, 1))
	feather_label.text = "Размытие контура: %.2f" % float(ps["feather"])
	var feather_slider := HSlider.new()
	feather_slider.min_value = 0.01
	feather_slider.max_value = 4.0
	feather_slider.step = 0.01
	feather_slider.value = float(ps["feather"])
	feather_slider.custom_minimum_size = Vector2(170, 0)
	feather_slider.value_changed.connect(func(value: float) -> void:
		if is_instance_valid(_provinces_iberia_provider):
			_provinces_iberia_provider.set_border_feather(value)
			_clear_layer_tiles(_provinces_iberia_layer_idx)
		feather_label.text = "Размытие контура: %.2f" % value
	)
	feather_row.add_child(feather_label)
	feather_row.add_child(feather_slider)
	_provinces_iberia_panel.add_child(feather_row)

	var smoothing_row := HBoxContainer.new()
	var smoothing_label := Label.new()
	smoothing_label.custom_minimum_size = Vector2(260, 0)
	smoothing_label.add_theme_color_override("font_color", Color(1, 1, 1))
	smoothing_label.text = "Сглаживание углов: 0"
	var smoothing_slider := HSlider.new()
	smoothing_slider.min_value = 0
	smoothing_slider.max_value = 4
	smoothing_slider.step = 1
	smoothing_slider.value = 0
	smoothing_slider.custom_minimum_size = Vector2(170, 0)
	smoothing_slider.value_changed.connect(func(value: float) -> void:
		if is_instance_valid(_provinces_iberia_provider):
			_provinces_iberia_provider.set_border_smoothing_steps(int(value))
			_clear_layer_tiles(_provinces_iberia_layer_idx)
		smoothing_label.text = "Сглаживание углов: %d" % int(value)
	)
	smoothing_row.add_child(smoothing_label)
	smoothing_row.add_child(smoothing_slider)
	_provinces_iberia_panel.add_child(smoothing_row)

	var gap_row := HBoxContainer.new()
	var gap_label := Label.new()
	gap_label.custom_minimum_size = Vector2(260, 0)
	gap_label.add_theme_color_override("font_color", Color(1, 1, 1))
	gap_label.text = "Закрытие щелей: 0 px"
	var gap_slider := HSlider.new()
	gap_slider.min_value = 0
	gap_slider.max_value = 4
	gap_slider.step = 1
	gap_slider.value = 0
	gap_slider.custom_minimum_size = Vector2(170, 0)
	gap_slider.value_changed.connect(func(value: float) -> void:
		if is_instance_valid(_provinces_iberia_provider):
			_provinces_iberia_provider.set_gap_fill_radius_px(int(value))
			_clear_layer_tiles(_provinces_iberia_layer_idx)
		gap_label.text = "Закрытие щелей: %d px" % int(value)
	)
	gap_row.add_child(gap_label)
	gap_row.add_child(gap_slider)
	_provinces_iberia_panel.add_child(gap_row)

	var color_row := HBoxContainer.new()
	var color_label := Label.new()
	color_label.custom_minimum_size = Vector2(260, 0)
	color_label.add_theme_color_override("font_color", Color(1, 1, 1))
	color_label.text = "Цвет контура"
	var color_picker := ColorPickerButton.new()
	color_picker.color = ps["color"]
	color_picker.custom_minimum_size = Vector2(80, 24)
	color_picker.color_changed.connect(func(color: Color) -> void:
		if is_instance_valid(_provinces_iberia_provider):
			_provinces_iberia_provider.set_border_color(color)
			_clear_layer_tiles(_provinces_iberia_layer_idx)
	)
	color_row.add_child(color_label)
	color_row.add_child(color_picker)
	_provinces_iberia_panel.add_child(color_row)


func _clear_layer_tiles(layer_idx: int) -> void:
	for key in _active.keys():
		var sep := (key as String).find("|")
		if sep < 0 or int((key as String).substr(0, sep)) != layer_idx:
			continue
		_active[key].queue_free()
		_active.erase(key)


func _apply_selection_overlay_style() -> void:
	if is_instance_valid(_selected_cell_overlay):
		var fill_color: Color = _selection_fill_color
		if _selected_cell_overlay_fill_override != null:
			fill_color = _selected_cell_overlay_fill_override
		_selected_cell_overlay.set_style(
			fill_color,
			_selection_outline_color,
			_selection_outline_width,
			_selection_outline_blur)


func _build_selection_style_panel(ui_layer: CanvasLayer) -> void:
	_selection_style_panel = VBoxContainer.new()
	_selection_style_panel.offset_left = 1440.0
	_selection_style_panel.offset_top = 430.0
	_selection_style_panel.offset_right = 1896.0
	_selection_style_panel.offset_bottom = 700.0
	_selection_style_panel.visible = false
	ui_layer.add_child(_selection_style_panel)

	var toggle_button := Button.new()
	toggle_button.text = "Выделение провинций ▼"
	toggle_button.toggle_mode = true
	toggle_button.button_pressed = true
	toggle_button.pressed.connect(func() -> void:
		_selection_style_collapsed = not toggle_button.button_pressed
		if is_instance_valid(_selection_style_content):
			_selection_style_content.visible = not _selection_style_collapsed
		toggle_button.text = "Выделение провинций %s" % ("▶" if _selection_style_collapsed else "▼")
	)
	_selection_style_panel.add_child(toggle_button)

	_selection_style_content = VBoxContainer.new()
	_selection_style_panel.add_child(_selection_style_content)

	var fill_color_row := HBoxContainer.new()
	var fill_color_label := Label.new()
	fill_color_label.custom_minimum_size = Vector2(260, 0)
	fill_color_label.add_theme_color_override("font_color", Color(1, 1, 1))
	fill_color_label.text = "Цвет заливки"
	var fill_color_picker := ColorPickerButton.new()
	fill_color_picker.color = _selection_fill_color
	fill_color_picker.custom_minimum_size = Vector2(80, 24)
	fill_color_picker.color_changed.connect(func(color: Color) -> void:
		_selection_fill_color.r = color.r
		_selection_fill_color.g = color.g
		_selection_fill_color.b = color.b
		_apply_selection_overlay_style()
	)
	fill_color_row.add_child(fill_color_label)
	fill_color_row.add_child(fill_color_picker)
	_selection_style_content.add_child(fill_color_row)

	var fill_alpha_row := HBoxContainer.new()
	var fill_alpha_label := Label.new()
	fill_alpha_label.custom_minimum_size = Vector2(260, 0)
	fill_alpha_label.add_theme_color_override("font_color", Color(1, 1, 1))
	fill_alpha_label.text = "Прозрачность заливки: %.2f" % _selection_fill_color.a
	var fill_alpha_slider := HSlider.new()
	fill_alpha_slider.min_value = 0.0
	fill_alpha_slider.max_value = 0.8
	fill_alpha_slider.step = 0.01
	fill_alpha_slider.value = _selection_fill_color.a
	fill_alpha_slider.custom_minimum_size = Vector2(170, 0)
	fill_alpha_slider.value_changed.connect(func(value: float) -> void:
		_selection_fill_color.a = value
		fill_alpha_label.text = "Прозрачность заливки: %.2f" % value
		_apply_selection_overlay_style()
	)
	fill_alpha_row.add_child(fill_alpha_label)
	fill_alpha_row.add_child(fill_alpha_slider)
	_selection_style_content.add_child(fill_alpha_row)

	var outline_color_row := HBoxContainer.new()
	var outline_color_label := Label.new()
	outline_color_label.custom_minimum_size = Vector2(260, 0)
	outline_color_label.add_theme_color_override("font_color", Color(1, 1, 1))
	outline_color_label.text = "Цвет контура"
	var outline_color_picker := ColorPickerButton.new()
	outline_color_picker.color = _selection_outline_color
	outline_color_picker.custom_minimum_size = Vector2(80, 24)
	outline_color_picker.color_changed.connect(func(color: Color) -> void:
		_selection_outline_color.r = color.r
		_selection_outline_color.g = color.g
		_selection_outline_color.b = color.b
		_apply_selection_overlay_style()
	)
	outline_color_row.add_child(outline_color_label)
	outline_color_row.add_child(outline_color_picker)
	_selection_style_content.add_child(outline_color_row)

	var outline_alpha_row := HBoxContainer.new()
	var outline_alpha_label := Label.new()
	outline_alpha_label.custom_minimum_size = Vector2(260, 0)
	outline_alpha_label.add_theme_color_override("font_color", Color(1, 1, 1))
	outline_alpha_label.text = "Прозрачность контура: %.2f" % _selection_outline_color.a
	var outline_alpha_slider := HSlider.new()
	outline_alpha_slider.min_value = 0.0
	outline_alpha_slider.max_value = 1.0
	outline_alpha_slider.step = 0.01
	outline_alpha_slider.value = _selection_outline_color.a
	outline_alpha_slider.custom_minimum_size = Vector2(170, 0)
	outline_alpha_slider.value_changed.connect(func(value: float) -> void:
		_selection_outline_color.a = value
		outline_alpha_label.text = "Прозрачность контура: %.2f" % value
		_apply_selection_overlay_style()
	)
	outline_alpha_row.add_child(outline_alpha_label)
	outline_alpha_row.add_child(outline_alpha_slider)
	_selection_style_content.add_child(outline_alpha_row)

	var width_row := HBoxContainer.new()
	var width_label := Label.new()
	width_label.custom_minimum_size = Vector2(260, 0)
	width_label.add_theme_color_override("font_color", Color(1, 1, 1))
	width_label.text = "Толщина контура: %.1f px" % _selection_outline_width
	var width_slider := HSlider.new()
	width_slider.min_value = 0.0
	width_slider.max_value = 16.0
	width_slider.step = 0.1
	width_slider.value = _selection_outline_width
	width_slider.custom_minimum_size = Vector2(170, 0)
	width_slider.value_changed.connect(func(value: float) -> void:
		_selection_outline_width = value
		width_label.text = "Толщина контура: %.1f px" % value
		_apply_selection_overlay_style()
	)
	width_row.add_child(width_label)
	width_row.add_child(width_slider)
	_selection_style_content.add_child(width_row)

	var blur_row := HBoxContainer.new()
	var blur_label := Label.new()
	blur_label.custom_minimum_size = Vector2(260, 0)
	blur_label.add_theme_color_override("font_color", Color(1, 1, 1))
	blur_label.text = "Размытость контура: %.1f px" % _selection_outline_blur
	var blur_slider := HSlider.new()
	blur_slider.min_value = 0.0
	blur_slider.max_value = 32.0
	blur_slider.step = 0.5
	blur_slider.value = _selection_outline_blur
	blur_slider.custom_minimum_size = Vector2(170, 0)
	blur_slider.value_changed.connect(func(value: float) -> void:
		_selection_outline_blur = value
		blur_label.text = "Размытость контура: %.1f px" % value
		_apply_selection_overlay_style()
	)
	blur_row.add_child(blur_label)
	blur_row.add_child(blur_slider)
	_selection_style_content.add_child(blur_row)


func _apply_water_cells_provider_style() -> void:
	if not is_instance_valid(_water_cells_provider):
		return
	_water_cells_provider.set_uniform_fill_color(_water_cells_fill_color)
	_water_cells_provider.set_border_color(_water_cells_border_color)
	_water_cells_provider.set_border_width(_water_cells_border_width)
	_water_cells_provider.set_border_feather(_water_cells_border_blur)
	_clear_layer_tiles(_water_cells_layer_idx)


func _apply_water_selected_style() -> void:
	if _selected_cell_overlay_layer_idx != _water_cells_layer_idx:
		return
	_selected_cell_overlay_fill_override = _water_selected_fill_color
	if is_instance_valid(_selected_cell_overlay):
		_selected_cell_overlay.set_style(
			_water_selected_fill_color,
			_water_selected_outline_color,
			_water_selected_outline_width,
			_water_selected_outline_blur)


func _build_water_cells_panel(ui_layer: CanvasLayer) -> void:
	_water_cells_panel = VBoxContainer.new()
	_water_cells_panel.offset_left = 1440.0
	_water_cells_panel.offset_top = 710.0
	_water_cells_panel.offset_right = 1896.0
	_water_cells_panel.offset_bottom = 1040.0
	_water_cells_panel.visible = false
	ui_layer.add_child(_water_cells_panel)

	var toggle_button := Button.new()
	toggle_button.text = "Морские клетки ▼"
	toggle_button.toggle_mode = true
	toggle_button.button_pressed = true
	toggle_button.pressed.connect(func() -> void:
		_water_cells_panel_collapsed = not toggle_button.button_pressed
		if is_instance_valid(_water_cells_panel_content):
			_water_cells_panel_content.visible = not _water_cells_panel_collapsed
		toggle_button.text = "Морские клетки %s" % ("▶" if _water_cells_panel_collapsed else "▼")
	)
	_water_cells_panel.add_child(toggle_button)

	_water_cells_panel_content = VBoxContainer.new()
	_water_cells_panel.add_child(_water_cells_panel_content)

	var border_color_row := HBoxContainer.new()
	var border_color_label := Label.new()
	border_color_label.custom_minimum_size = Vector2(260, 0)
	border_color_label.add_theme_color_override("font_color", Color(1, 1, 1))
	border_color_label.text = "Цвет контура"
	var border_color_picker := ColorPickerButton.new()
	border_color_picker.color = _water_cells_border_color
	border_color_picker.custom_minimum_size = Vector2(80, 24)
	border_color_picker.color_changed.connect(func(color: Color) -> void:
		_water_cells_border_color = color
		_apply_water_cells_provider_style()
	)
	border_color_row.add_child(border_color_label)
	border_color_row.add_child(border_color_picker)
	_water_cells_panel_content.add_child(border_color_row)

	var border_alpha_row := HBoxContainer.new()
	var border_alpha_label := Label.new()
	border_alpha_label.custom_minimum_size = Vector2(260, 0)
	border_alpha_label.add_theme_color_override("font_color", Color(1, 1, 1))
	border_alpha_label.text = "Прозрачность контура: %.2f" % _water_cells_border_color.a
	var border_alpha_slider := HSlider.new()
	border_alpha_slider.min_value = 0.0
	border_alpha_slider.max_value = 1.0
	border_alpha_slider.step = 0.01
	border_alpha_slider.value = _water_cells_border_color.a
	border_alpha_slider.custom_minimum_size = Vector2(170, 0)
	border_alpha_slider.value_changed.connect(func(value: float) -> void:
		_water_cells_border_color.a = value
		border_alpha_label.text = "Прозрачность контура: %.2f" % value
		_apply_water_cells_provider_style()
	)
	border_alpha_row.add_child(border_alpha_label)
	border_alpha_row.add_child(border_alpha_slider)
	_water_cells_panel_content.add_child(border_alpha_row)

	var fill_color_row := HBoxContainer.new()
	var fill_color_label := Label.new()
	fill_color_label.custom_minimum_size = Vector2(260, 0)
	fill_color_label.add_theme_color_override("font_color", Color(1, 1, 1))
	fill_color_label.text = "Цвет заливки"
	var fill_color_picker := ColorPickerButton.new()
	fill_color_picker.color = _water_cells_fill_color
	fill_color_picker.custom_minimum_size = Vector2(80, 24)
	fill_color_picker.color_changed.connect(func(color: Color) -> void:
		_water_cells_fill_color.r = color.r
		_water_cells_fill_color.g = color.g
		_water_cells_fill_color.b = color.b
		_apply_water_cells_provider_style()
	)
	fill_color_row.add_child(fill_color_label)
	fill_color_row.add_child(fill_color_picker)
	_water_cells_panel_content.add_child(fill_color_row)

	var fill_alpha_row := HBoxContainer.new()
	var fill_alpha_label := Label.new()
	fill_alpha_label.custom_minimum_size = Vector2(260, 0)
	fill_alpha_label.add_theme_color_override("font_color", Color(1, 1, 1))
	fill_alpha_label.text = "Прозрачность заливки: %.2f" % _water_cells_fill_color.a
	var fill_alpha_slider := HSlider.new()
	fill_alpha_slider.min_value = 0.0
	fill_alpha_slider.max_value = 0.8
	fill_alpha_slider.step = 0.01
	fill_alpha_slider.value = _water_cells_fill_color.a
	fill_alpha_slider.custom_minimum_size = Vector2(170, 0)
	fill_alpha_slider.value_changed.connect(func(value: float) -> void:
		_water_cells_fill_color.a = value
		fill_alpha_label.text = "Прозрачность заливки: %.2f" % value
		_apply_water_cells_provider_style()
	)
	fill_alpha_row.add_child(fill_alpha_label)
	fill_alpha_row.add_child(fill_alpha_slider)
	_water_cells_panel_content.add_child(fill_alpha_row)

	var width_row := HBoxContainer.new()
	var width_label := Label.new()
	width_label.custom_minimum_size = Vector2(260, 0)
	width_label.add_theme_color_override("font_color", Color(1, 1, 1))
	width_label.text = "Толщина контура: %.2f" % _water_cells_border_width
	var width_slider := HSlider.new()
	width_slider.min_value = 0.0
	width_slider.max_value = 2.0
	width_slider.step = 0.025
	width_slider.value = _water_cells_border_width
	width_slider.custom_minimum_size = Vector2(170, 0)
	width_slider.value_changed.connect(func(value: float) -> void:
		_water_cells_border_width = value
		width_label.text = "Толщина контура: %.2f" % value
		_apply_water_cells_provider_style()
	)
	width_row.add_child(width_label)
	width_row.add_child(width_slider)
	_water_cells_panel_content.add_child(width_row)

	var blur_row := HBoxContainer.new()
	var blur_label := Label.new()
	blur_label.custom_minimum_size = Vector2(260, 0)
	blur_label.add_theme_color_override("font_color", Color(1, 1, 1))
	blur_label.text = "Размытость контура: %.1f" % _water_cells_border_blur
	var blur_slider := HSlider.new()
	blur_slider.min_value = 0.01
	blur_slider.max_value = 8.0
	blur_slider.step = 0.1
	blur_slider.value = _water_cells_border_blur
	blur_slider.custom_minimum_size = Vector2(170, 0)
	blur_slider.value_changed.connect(func(value: float) -> void:
		_water_cells_border_blur = value
		blur_label.text = "Размытость контура: %.1f" % value
		_apply_water_cells_provider_style()
	)
	blur_row.add_child(blur_label)
	blur_row.add_child(blur_slider)
	_water_cells_panel_content.add_child(blur_row)

	var selected_color_row := HBoxContainer.new()
	var selected_color_label := Label.new()
	selected_color_label.custom_minimum_size = Vector2(260, 0)
	selected_color_label.add_theme_color_override("font_color", Color(1, 1, 1))
	selected_color_label.text = "Цвет выделения"
	var selected_color_picker := ColorPickerButton.new()
	selected_color_picker.color = _water_selected_outline_color
	selected_color_picker.custom_minimum_size = Vector2(80, 24)
	selected_color_picker.color_changed.connect(func(color: Color) -> void:
		_water_selected_outline_color = color
		_apply_water_selected_style()
	)
	selected_color_row.add_child(selected_color_label)
	selected_color_row.add_child(selected_color_picker)
	_water_cells_panel_content.add_child(selected_color_row)

	var selected_width_row := HBoxContainer.new()
	var selected_width_label := Label.new()
	selected_width_label.custom_minimum_size = Vector2(260, 0)
	selected_width_label.add_theme_color_override("font_color", Color(1, 1, 1))
	selected_width_label.text = "Толщина выделения: %.1f px" % _water_selected_outline_width
	var selected_width_slider := HSlider.new()
	selected_width_slider.min_value = 0.0
	selected_width_slider.max_value = 16.0
	selected_width_slider.step = 0.1
	selected_width_slider.value = _water_selected_outline_width
	selected_width_slider.custom_minimum_size = Vector2(170, 0)
	selected_width_slider.value_changed.connect(func(value: float) -> void:
		_water_selected_outline_width = value
		selected_width_label.text = "Толщина выделения: %.1f px" % value
		_apply_water_selected_style()
	)
	selected_width_row.add_child(selected_width_label)
	selected_width_row.add_child(selected_width_slider)
	_water_cells_panel_content.add_child(selected_width_row)

	var selected_blur_row := HBoxContainer.new()
	var selected_blur_label := Label.new()
	selected_blur_label.custom_minimum_size = Vector2(260, 0)
	selected_blur_label.add_theme_color_override("font_color", Color(1, 1, 1))
	selected_blur_label.text = "Размытость выделения: %.1f px" % _water_selected_outline_blur
	var selected_blur_slider := HSlider.new()
	selected_blur_slider.min_value = 0.0
	selected_blur_slider.max_value = 32.0
	selected_blur_slider.step = 0.5
	selected_blur_slider.value = _water_selected_outline_blur
	selected_blur_slider.custom_minimum_size = Vector2(170, 0)
	selected_blur_slider.value_changed.connect(func(value: float) -> void:
		_water_selected_outline_blur = value
		selected_blur_label.text = "Размытость выделения: %.1f px" % value
		_apply_water_selected_style()
	)
	selected_blur_row.add_child(selected_blur_label)
	selected_blur_row.add_child(selected_blur_slider)
	_water_cells_panel_content.add_child(selected_blur_row)


func _show_selected_cell_overlay(layer_idx: int, rings: Array, _color: Color) -> void:
	_selected_cell_overlay_layer_idx = layer_idx
	_selected_cell_overlay_fill_override = null
	if is_instance_valid(_selected_cell_overlay):
		_selected_cell_overlay.set_rings(rings, _selection_fill_color)
		_apply_selection_overlay_style()


func _show_selected_cell_outline_only(layer_idx: int, rings: Array) -> void:
	_selected_cell_overlay_layer_idx = layer_idx
	_selected_cell_overlay_fill_override = _water_selected_fill_color
	if is_instance_valid(_selected_cell_overlay):
		_selected_cell_overlay.set_rings(rings, _selected_cell_overlay_fill_override)
		_apply_water_selected_style()


func _try_pick_cell(world_pos: Vector2) -> bool:
	if not is_instance_valid(_cells_test_provider):
		return false
	var cell_id := _cells_test_provider.get_cell_id_at(world_pos)
	if cell_id.is_empty() or not _test_cells_by_id.has(cell_id):
		return false
	var rings := _cells_test_provider.get_cell_rings_by_id(cell_id)
	_selected_cell_overlay_layer_idx = _cells_test_layer_idx
	_selected_cell_overlay_fill_override = _cells_test_selected_fill_color
	if is_instance_valid(_selected_cell_overlay):
		_selected_cell_overlay.set_rings(rings, _cells_test_selected_fill_color)
		_selected_cell_overlay.set_style(
			_cells_test_selected_fill_color,
			_cells_test_selected_outline_color,
			_cells_test_selected_outline_width,
			_cells_test_selected_outline_blur)
	var cell: Cell = _test_cells_by_id[cell_id]
	_show_cell_info(cell)
	return true


func _try_pick_iberia_land_cell(world_pos: Vector2) -> bool:
	if not is_instance_valid(_iberia_land_cells_provider):
		return false
	var cell_id := _iberia_land_cells_provider.get_cell_id_at(world_pos)
	if cell_id.is_empty():
		return false
	_selected_iberia_land_cell_id = cell_id
	var cell_name := _iberia_land_cells_provider.get_cell_name_at(world_pos)
	_show_selected_cell_overlay(
		_iberia_land_cells_layer_idx,
		_iberia_land_cells_provider.get_cell_rings_by_id(cell_id),
		Color(0.98, 0.82, 0.34, 0.38))
	if is_instance_valid(_cell_info_label):
		_cell_info_label.visible = false
	_show_top_info("%s [%s]" % [cell_name, cell_id])
	return true


func _try_pick_province(world_pos: Vector2) -> bool:
	var province_name := _provinces_iberia_provider.get_cell_name_at(world_pos)
	if province_name.is_empty():
		return false
	_selected_province_name = province_name
	var selection_rings := _provinces_iberia_provider.get_cell_rings_by_name(province_name)
	if is_instance_valid(_provinces_iberia_selection_provider):
		var clipped_rings := _provinces_iberia_selection_provider.get_cell_rings_by_name(province_name)
		if not clipped_rings.is_empty():
			selection_rings = clipped_rings
	_show_selected_cell_overlay(
		_provinces_iberia_layer_idx,
		selection_rings,
		Color(0.95, 0.76, 0.34, 0.34))
	_show_province_info(province_name)
	return true


func _try_pick_world_province(world_pos: Vector2) -> bool:
	var province_id := _world_provinces_provider.get_cell_id_at(world_pos)
	if province_id.is_empty():
		return false
	var province_name := _world_provinces_provider.get_cell_name_at(world_pos)
	_selected_world_province_id = province_id
	_show_selected_cell_overlay(
		_world_provinces_layer_idx,
		_world_provinces_provider.get_cell_rings_by_id(province_id),
		Color(0.96, 0.78, 0.30, 0.34))
	_show_province_info("%s [%s]" % [province_name, province_id])
	return true


func _build_world_provinces_panel(ui_layer: CanvasLayer) -> void:
	_world_provinces_panel = VBoxContainer.new()
	_world_provinces_panel.offset_left = 1440.0
	_world_provinces_panel.offset_top = 300.0
	_world_provinces_panel.offset_right = 1896.0
	_world_provinces_panel.offset_bottom = 420.0
	_world_provinces_panel.visible = false
	ui_layer.add_child(_world_provinces_panel)

	var title_row := HBoxContainer.new()
	var title := Label.new()
	title.add_theme_color_override("font_color", Color(1.0, 0.92, 0.72, 1.0))
	title.text = "Провинции мира (слой 8)"
	title_row.add_child(title)

	var content := VBoxContainer.new()

	# Кнопка-шторка — сворачивает/разворачивает всё содержимое панели (слайдер
	# порога + чекбоксы диагностики), кроме самого заголовка. По просьбе
	# пользователя 2026-07-13 — панель слоя 8 разрослась и стала мешать на
	# экране, когда просто нужно быстро включить/выключить слой.
	var collapse_button := Button.new()
	collapse_button.text = "▾"
	collapse_button.custom_minimum_size = Vector2(28, 0)
	collapse_button.toggle_mode = true
	collapse_button.button_pressed = false
	collapse_button.toggled.connect(func(pressed: bool) -> void:
		content.visible = not pressed
		collapse_button.text = "▸" if pressed else "▾"
	)
	title_row.add_child(collapse_button)
	_world_provinces_panel.add_child(title_row)
	_world_provinces_panel.add_child(content)

	var area_row := HBoxContainer.new()
	var area_label := Label.new()
	area_label.custom_minimum_size = Vector2(280, 0)
	area_label.add_theme_color_override("font_color", Color(1, 1, 1))
	var initial_hidden := _world_provinces_provider.get_area_hidden_count() if is_instance_valid(_world_provinces_provider) else 0
	area_label.text = "Скрывать меньше: %.0f км² (%d)" % [DEFAULT_WORLD_PROVINCE_AREA_HIDE_THRESHOLD_KM2, initial_hidden]
	var area_slider := HSlider.new()
	area_slider.min_value = 0.0
	area_slider.max_value = 5000.0
	area_slider.step = 50.0
	area_slider.value = DEFAULT_WORLD_PROVINCE_AREA_HIDE_THRESHOLD_KM2
	area_slider.custom_minimum_size = Vector2(170, 0)
	area_slider.value_changed.connect(func(value: float) -> void:
		var hidden_count := 0
		if is_instance_valid(_world_provinces_provider):
			hidden_count = _world_provinces_provider.set_area_hidden_threshold(value)
			_clear_layer_tiles(_world_provinces_layer_idx)
		area_label.text = "Скрывать меньше: %.0f км² (%d)" % [value, hidden_count]
	)
	area_row.add_child(area_label)
	area_row.add_child(area_slider)
	content.add_child(area_row)

	# Диагностика площади/осколков (2026-07-12) — офлайн-предпосчитанные точки
	# (build_small_provinces_markers.py/build_island_piece_markers.py), НЕ
	# завязаны на видимость самого слоя 8 (только на свои чекбоксы), поэтому
	# просто переключают .visible у готовых слоёв-нод.
	var small_check := CheckBox.new()
	small_check.text = "< 300 км² (с площадью)"
	small_check.add_theme_color_override("font_color", Color(1, 1, 1))
	small_check.toggled.connect(func(pressed: bool) -> void:
		if is_instance_valid(_small_provinces_markers):
			_small_provinces_markers.visible = pressed
	)
	content.add_child(small_check)

	var island_check := CheckBox.new()
	island_check.text = "Островные куски"
	island_check.add_theme_color_override("font_color", Color(1, 1, 1))
	island_check.toggled.connect(func(pressed: bool) -> void:
		if is_instance_valid(_island_piece_markers):
			_island_piece_markers.visible = pressed
	)
	content.add_child(island_check)


func _try_pick_netherlands_province(world_pos: Vector2) -> bool:
	var province_id := _netherlands_provinces_provider.get_cell_id_at(world_pos)
	if province_id.is_empty():
		return false
	_selected_netherlands_province_id = province_id
	_show_selected_cell_overlay(
		_netherlands_provinces_layer_idx,
		_netherlands_provinces_provider.get_cell_rings_by_id(province_id),
		Color(0.96, 0.78, 0.30, 0.34))
	_show_top_info(province_id)
	return true


func _try_pick_water_cell(world_pos: Vector2) -> bool:
	var cell_id := _water_cells_provider.get_cell_id_at(world_pos)
	if cell_id.is_empty():
		return false
	_selected_water_cell_id = cell_id
	_show_selected_cell_outline_only(
		_water_cells_layer_idx,
		_water_cells_provider.get_cell_rings_by_id(cell_id))
	_show_top_info(cell_id)
	return true


func _build_province_info_label() -> void:
	_province_info_label = Label.new()
	_province_info_label.offset_left = 720.0
	_province_info_label.offset_top = 24.0
	_province_info_label.offset_right = 1320.0
	_province_info_label.offset_bottom = 70.0
	_province_info_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_province_info_label.add_theme_color_override("font_color", Color(1.0, 0.94, 0.78, 1.0))
	_province_info_label.add_theme_color_override("font_shadow_color", Color(0.02, 0.02, 0.02, 0.85))
	_province_info_label.add_theme_constant_override("shadow_offset_x", 1)
	_province_info_label.add_theme_constant_override("shadow_offset_y", 1)
	_province_info_label.add_theme_font_size_override("font_size", 20)
	_province_info_label.visible = false
	$UI.add_child(_province_info_label)


func _show_province_info(province_name: String) -> void:
	if not is_instance_valid(_province_info_label):
		return
	_province_info_label.text = "Провинция: %s" % province_name
	_province_info_label.visible = true


func _show_top_info(text: String) -> void:
	if not is_instance_valid(_province_info_label):
		return
	_province_info_label.text = text
	_province_info_label.visible = true


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

	# Глубина/мелководье слоя V — не тайловые (не в _layers/request_tile),
	# синхронизируем видимость с флагом слоя V вручную, тот же приём, что у
	# спрайтов слоя "2" ниже.
	if _ocean_v_layer_idx >= 0 and _ocean_v_layer_idx < _layers.size():
		var v_visible: bool = _layers[_ocean_v_layer_idx]["visible"]
		for spr in _ocean_v_depth_sprites:
			if is_instance_valid(spr):
				spr.visible = v_visible
		for spr in _ocean_v_mariana_depth_sprites:
			if is_instance_valid(spr):
				spr.visible = v_visible
		for spr in _ocean_v_shallow_sprites:
			if is_instance_valid(spr):
				spr.visible = v_visible
		if is_instance_valid(_ocean_v_panel):
			_ocean_v_panel.visible = v_visible

	if _provinces_iberia_layer_idx >= 0 and is_instance_valid(_provinces_iberia_panel):
		_provinces_iberia_panel.visible = _layers[_provinces_iberia_layer_idx]["visible"]
	if _world_provinces_layer_idx >= 0 and _world_provinces_layer_idx < _layers.size() \
			and is_instance_valid(_world_provinces_panel):
		_world_provinces_panel.visible = _layers[_world_provinces_layer_idx]["visible"]
	if _cells_test_layer_idx >= 0 and _cells_test_layer_idx < _layers.size():
		var cells_visible: bool = _layers[_cells_test_layer_idx]["visible"]
		if is_instance_valid(_cell_boundary_tool_panel):
			_cell_boundary_tool_panel.visible = cells_visible
		if is_instance_valid(_cell_boundary_draft_layer):
			_cell_boundary_draft_layer.visible = cells_visible
	if _water_cells_layer_idx >= 0 and _water_cells_layer_idx < _layers.size() \
			and is_instance_valid(_water_cells_panel):
		_water_cells_panel.visible = _layers[_water_cells_layer_idx]["visible"]
	if is_instance_valid(_selection_style_panel):
		var selection_panel_visible: bool = (_provinces_iberia_layer_idx >= 0 \
				and _provinces_iberia_layer_idx < _layers.size() \
				and _layers[_provinces_iberia_layer_idx]["visible"]) \
			or (_world_provinces_layer_idx >= 0 \
				and _world_provinces_layer_idx < _layers.size() \
				and _layers[_world_provinces_layer_idx]["visible"]) \
			or (_netherlands_provinces_layer_idx >= 0 \
				and _netherlands_provinces_layer_idx < _layers.size() \
				and _layers[_netherlands_provinces_layer_idx]["visible"])
		_selection_style_panel.visible = selection_panel_visible
	if is_instance_valid(_province_info_label):
		var iberia_info_visible: bool = _provinces_iberia_layer_idx >= 0 \
			and _provinces_iberia_layer_idx < _layers.size() \
			and _layers[_provinces_iberia_layer_idx]["visible"] \
			and not _selected_province_name.is_empty()
		var world_info_visible: bool = _world_provinces_layer_idx >= 0 \
			and _world_provinces_layer_idx < _layers.size() \
			and _layers[_world_provinces_layer_idx]["visible"] \
			and not _selected_world_province_id.is_empty()
		var netherlands_info_visible: bool = _netherlands_provinces_layer_idx >= 0 \
			and _netherlands_provinces_layer_idx < _layers.size() \
			and _layers[_netherlands_provinces_layer_idx]["visible"] \
			and not _selected_netherlands_province_id.is_empty()
		var water_info_visible: bool = _water_cells_layer_idx >= 0 \
			and _water_cells_layer_idx < _layers.size() \
			and _layers[_water_cells_layer_idx]["visible"] \
			and not _selected_water_cell_id.is_empty()
		var iberia_land_cell_info_visible: bool = _iberia_land_cells_layer_idx >= 0 \
			and _iberia_land_cells_layer_idx < _layers.size() \
			and _layers[_iberia_land_cells_layer_idx]["visible"] \
			and not _selected_iberia_land_cell_id.is_empty()
		_province_info_label.visible = iberia_info_visible or world_info_visible or netherlands_info_visible \
			or water_info_visible or iberia_land_cell_info_visible
	if is_instance_valid(_selected_cell_overlay):
		_selected_cell_overlay.visible = _selected_cell_overlay_layer_idx >= 0 \
			and _selected_cell_overlay_layer_idx < _layers.size() \
			and _layers[_selected_cell_overlay_layer_idx]["visible"]

	if _regions_iberia_layer_idx >= 0 and is_instance_valid(_regions_iberia_panel):
		_regions_iberia_panel.visible = _layers[_regions_iberia_layer_idx]["visible"]


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
	if _provinces_iberia_layer_idx >= 0 and is_instance_valid(_province_city_markers):
		var cities_zoom_ready := absf(lod_zoom - 8.0) < 0.01
		_province_city_markers.visible = _layers[_provinces_iberia_layer_idx]["visible"] and lod == 7 and cities_zoom_ready
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


## Sentinel "не задан" для z_index_override НЕ может быть отрицательным
## int — слою "V" нужен явный z_index=-10 (заведомо ниже всех), который
## раньше ошибочно принимался за "не задан" (проверка была `>= 0`) и
## отбрасывался обратно на layer_idx. Единственный вызывающий код (см.
## _process) ВСЕГДА передаёт уже разрешённое значение явно, так что этот
## sentinel практически не используется, но пусть он не ломает отрицательные
## z_index, если понадобятся ещё раз.
const _Z_INDEX_UNSET := 1000000000

func _make_tile(tex: Texture2D, layer_idx: int, x: int, y: int,
		tile_world: float, z_index_override: int = _Z_INDEX_UNSET) -> Sprite2D:
	var spr := Sprite2D.new()
	spr.centered = false
	spr.texture = tex
	var s := tile_world / spr.texture.get_width()
	spr.scale = Vector2(s, s)
	spr.position = Vector2(x * tile_world, y * tile_world)
	# оверлеи поверх базового слоя (по умолчанию) — или явный override
	# (_layers[li]["z_index"], см. вызов в _process), если слою нужен
	# порядок отрисовки, не совпадающий с порядком добавления в _layers.
	spr.z_index = z_index_override if z_index_override != _Z_INDEX_UNSET else layer_idx
	# Билинейная фильтрация (по умолчанию) смешивает цвет с краем СОСЕДНЕГО
	# тайла на стыке (доля пикселя несовпадения от масштабирования) — тонкая
	# линия другого оттенка на границе тайлов, мерцающая при зуме (несовпадение
	# "плавает"). NEAREST убирает смешивание на стыке ценой чуть менее гладкой
	# картинки при сильном приближении внутри одного тайла.
	spr.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	container.add_child(spr)
	return spr


## lon/lat под курсором — для подбора --region у bake-скриптов (см.
## scripts/tools/bake_ocean_v_*.py) без угадывания координат по скриншоту.
func _mouse_world_lonlat_text() -> String:
	if not is_instance_valid(camera):
		return ""
	var pos := camera.get_global_mouse_position()
	var lon := pos.x / WORLD_PX * 360.0 - 180.0
	var n := 0.5 - pos.y / WORLD_PX
	var lat_rad := 2.0 * atan(exp(2.0 * PI * n)) - PI / 2.0
	return "   |   курсор: %.2f, %.2f" % [lon, rad_to_deg(lat_rad)]


func _update_status(lod: int, cam_zoom: float) -> void:
	if not status_label:
		return
	var names: Array = []
	for l in _layers:
		if l["visible"]:
			names.append(l["name"])
	status_label.text = "Слои: %s   |   LOD z%d   |   zoom %.2f   |   тайлов: %d%s" % [
		", ".join(names), lod, cam_zoom, _active.size(), _mouse_world_lonlat_text()]
