class_name GameplayTables
extends RefCounted
## Числовые таблицы и формулы общего назначения для игровых данных клетки.
##
## Источник значений — диздоки в корне проекта:
## ПЛОЩАДЬ_КЛЕТОК_И_ПОЛЕЗНОСТЬ.md (формулы) и УРОВНЕЙ_ТЕРРИТОРИЙ.md (уровни лестницы).
## Держать таблицы здесь, а не разбросанными по Cell/City — при балансировке
## правится один файл.

const BASE_AREA_KM2 := 1000.0
const AREA_FACTOR_MIN := 0.4
const AREA_FACTOR_MAX := 4.0

const BASE_MARCH_DISTANCE_KM := 40.0
const MOVEMENT_COST_MIN := 0.5
const MOVEMENT_COST_MAX := 5.0

## settlement_factor по умолчанию для relief_type, если он не задан явно
## на самой клетке (раздел 1 ПЛОЩАДЬ_КЛЕТОК_И_ПОЛЕЗНОСТЬ.md).
## Не строгий справочник — конкретная клетка почти всегда переопределяет
## своё собственное значение (влажность, почва и т.п. корректируют базу).
const SETTLEMENT_FACTOR_BY_RELIEF := {
	"fertile_plain": 1.20,
	"plain": 1.00,
	"hills": 0.75,
	"mountains": 0.25,
	"tundra": 0.10,
	"marsh": 0.05,
	"desert": 0.03,
}

## development_factor для сельской ёмкости (раздел 6).
const DEVELOPMENT_FACTOR := {
	"none": 0.05,
	"sparse_settlement": 0.20,
	"hunting_grounds": 0.15,
	"pasture": 0.50,
	"villages": 1.00,
	"farmland": 1.30,
	"fertile_farmland": 1.50,
	"irrigated_fields": 1.80,
	"rice_paddies": 2.20,
	"vineyards": 0.90,
	"olive_groves": 0.80,
	"orchards": 1.10,
	"forestry": 0.40,
	"mining": 0.60,
	"quarry": 0.40,
	"salt_works": 0.50,
	"urban_periphery": 2.00,
}

## Мягкий минимум сельского населения для заселённой клетки (раздел 8).
const MIN_RURAL_POPULATION_IF_SETTLED := 300

## -- Тестовый "регион" для слоя "Клетки (тест: Ла-Корунья)" --------------
## Уровня Region.gd в проекте ещё нет (сознательно, см. CLAUDE.md/Cell.gd —
## рано заводить целую систему регионов ради одной тестовой провинции).
## Эти константы — временная замена region_base_rural_density и внешних
## факторов (инфраструктура/здоровье/безопасность) конкретно для теста
## Ла-Коруньи, взяты из примера раздела 7 ПЛОЩАДЬ_КЛЕТОК_И_ПОЛЕЗНОСТЬ.md
## (Галисия: base_rural_density 30-45 чел/км², пример клетки — 35/1.10/0.95/1.00).
## Удалить/заменить настоящим Region, когда он появится.
const TEST_GALICIA_BASE_RURAL_DENSITY := 35.0
const TEST_GALICIA_INFRASTRUCTURE_FACTOR := 1.10
const TEST_GALICIA_HEALTH_FACTOR := 0.95
const TEST_GALICIA_SECURITY_FACTOR := 1.00


## area_factor = clamp(sqrt(area_km2 / BASE_AREA_KM2), MIN, MAX) — раздел 2.1.
static func area_factor(area_km2: float) -> float:
	var raw := sqrt(max(area_km2, 0.0) / BASE_AREA_KM2)
	return clampf(raw, AREA_FACTOR_MIN, AREA_FACTOR_MAX)


## Значение по умолчанию settlement_factor для указанного relief_type.
## Возвращает 1.0 (обычная равнина), если тип не найден в таблице.
static func default_settlement_factor(relief_type: String) -> float:
	return SETTLEMENT_FACTOR_BY_RELIEF.get(relief_type, 1.0)


## development_factor для указанного типа освоения.
## Возвращает фактор "нет освоения", если тип не найден в таблице.
static func development_factor(development_type: String) -> float:
	return DEVELOPMENT_FACTOR.get(development_type, DEVELOPMENT_FACTOR["none"])


## Стоимость движения через клетку/ребро соседства (раздел 20).
static func movement_cost(
	distance_km: float,
	terrain_modifier: float = 1.0,
	cover_modifier: float = 1.0,
	road_modifier: float = 1.0,
	river_modifier: float = 1.0,
	weather_modifier: float = 1.0,
	base_march_distance: float = BASE_MARCH_DISTANCE_KM
) -> float:
	var raw := (distance_km / base_march_distance) \
		* terrain_modifier * cover_modifier * road_modifier \
		* river_modifier * weather_modifier
	return clampf(raw, MOVEMENT_COST_MIN, MOVEMENT_COST_MAX)


## Стоимость контроля территории (раздел 21). Без верхнего/нижнего клампа —
## документ не задаёт диапазон, значение используется относительно других клеток.
static func control_cost(
	area_factor_value: float,
	remoteness_factor: float = 1.0,
	terrain_control_modifier: float = 1.0,
	population_modifier: float = 1.0,
	road_modifier: float = 1.0,
	security_modifier: float = 1.0
) -> float:
	return area_factor_value * remoteness_factor * terrain_control_modifier \
		* population_modifier * road_modifier * security_modifier
