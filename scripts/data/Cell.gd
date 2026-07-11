class_name Cell
extends Resource
## Клетка — минимальная игровая территориальная единица (самый нижний уровень
## лестницы "Клетка → Провинция → Регион → ... → Мир", см. УРОВНЕЙ_ТЕРРИТОРИЙ.md).
##
## Клетка НЕ делится на подклетки — площадь используется только для расчёта
## масштаба (area_factor), а не для внутреннего деления территории
## (см. раздел 1 ПЛОЩАДЬ_КЛЕТОК_И_ПОЛЕЗНОСТЬ.md).
##
## Это чистый слой данных: геометрия (полигон/центроид на карте) сюда
## намеренно не входит — она приходит из слоя рендера (см. TODO.md,
## "Клетки суши сейчас только картинка, не игровые данные"). Когда для клетки
## появится стабильная геометрия, id этого объекта должен совпасть со
## стабильным id клетки в геометрии.

## -- Идентификация и принадлежность --
var id: String = ""
var display_name: String = ""
var region_id: String = ""
var city_id: String = ""  ## пусто, если на клетке нет города

## "" — нет статуса; "potential" — потенциальный центр провинции (кандидат
## на столицу, ещё не подтверждён игровой логикой); "actual" зарезервировано
## на будущее (реально выбранная столица). Пока используется только тестовым
## слоем "Клетки (тест: Ла-Корунья)" — см. build_cells_test.py.
var province_center_status: String = ""

## -- Тип клетки (раздел 4 УРОВНЕЙ_ТЕРРИТОРИЙ.md) --
## "urban" / "rural" / "sea" / "resource"
var cell_type: String = "rural"

## -- Площадь --
var area_km2: float = 0.0
var area_factor: float = 1.0  ## пересчитывается из area_km2, см. recompute_area_factor()

## -- Природа --
var surface_type: String = ""        ## напр. "coast", "inland"
var relief_type: String = ""         ## напр. "plain", "hills", "mountains", "tundra"
var natural_cover_type: String = ""  ## напр. "meadow", "forest", "scrub"
var soil_type: String = ""
var climate_type: String = ""
var moisture_type: String = ""
var features: Array[String] = []     ## напр. ["coast", "rocky_shore"]
var resource: String = ""            ## напр. "fish", "iron", "furs"; пусто = нет ресурса

## -- Пригодность (раздел 1 ПЛОЩАДЬ_КЛЕТОК_И_ПОЛЕЗНОСТЬ.md) --
## Клетка остаётся единой ячейкой — эти факторы не делят её на части,
## а описывают её ЦЕЛИКОМ как лучше/хуже подходящую для жизни и хозяйства.
var settlement_factor: float = 1.0    ## пригодность для поселений
var usable_land_factor: float = 1.0   ## общая полезность земли

## -- Освоение --
var development_type: String = "none"  ## ключ в GameplayTables.DEVELOPMENT_FACTOR
var development_level: int = 0          ## напр. уровень построек (I/II/III -> 1/2/3)
var maturity: float = 0.0               ## 0..1, зрелость освоения
var damage: float = 0.0                 ## 0..1, повреждение (война/бедствия)

## -- Население --
var rural_population: int = 0
var rural_capacity: float = 0.0  ## пересчитывается через compute_rural_capacity()

## -- Инфраструктура --
var road_level: int = 0
var irrigation_level: int = 0


func _init(p_id: String = "") -> void:
	id = p_id


## area_factor = clamp(sqrt(area_km2 / 1000), 0.4, 4.0) — раздел 2.1.
## Вызывать один раз при генерации/загрузке карты (раздел 23), не каждый ход.
func recompute_area_factor() -> void:
	area_factor = GameplayTables.area_factor(area_km2)


## rural_capacity = area_km2 × region_base_rural_density × cell_settlement_factor
##   × development_factor × infrastructure_factor × health_factor × security_factor
## (раздел 5). region_base_rural_density передаётся числом, а не объектом
## Region — уровня "Регион" в проекте пока нет (сознательно, см. CLAUDE.md/
## обсуждение: на этом шаге закладывается только Cell). Инфраструктура/
## здоровье/безопасность тоже передаются отдельно — они не хранятся на
## клетке напрямую, а собираются из дорог/событий/региона, когда те появятся.
func compute_rural_capacity(
	region_base_rural_density: float,
	infrastructure_factor: float = 1.0,
	health_factor: float = 1.0,
	security_factor: float = 1.0
) -> float:
	var dev_factor := GameplayTables.development_factor(development_type)
	var capacity := area_km2 * region_base_rural_density * settlement_factor \
		* dev_factor * infrastructure_factor * health_factor * security_factor
	rural_capacity = capacity
	return capacity


## Применяет мягкий минимум населения для уже заселённой клетки (раздел 8).
func apply_minimum_population_if_settled() -> void:
	if development_type != "none" and rural_population < GameplayTables.MIN_RURAL_POPULATION_IF_SETTLED:
		rural_population = GameplayTables.MIN_RURAL_POPULATION_IF_SETTLED


## Человекочитаемая карточка клетки для будущего UI (раздел 4 УРОВНЕЙ_ТЕРРИТОРИЙ.md).
## Числа здесь — то, что можно показать игроку напрямую (раздел 13), без
## сырых множителей.
##
## "factors" — ИСКЛЮЧЕНИЕ из правила выше: area_factor/settlement_factor и
## т.п. — это как раз "сырые множители", но их сознательно включили сюда для
## отладочной карточки клика по тестовому слою "Клетки (тест: Ла-Корунья)"
## (см. ПЛОЩАДЬ_КЛЕТОК_И_ПОЛЕЗНОСТЬ.md) — проверить, что формулы документа
## реально считаются правильно. Когда появится "чистая" игровая карточка для
## обычного игрока, этот блок можно убрать оттуда, оставив только в debug-виде.
func to_display_dict() -> Dictionary:
	return {
		"id": id,
		"name": display_name,
		"type": cell_type,
		"province_center_status": province_center_status,
		"area": {
			"area_km2": area_km2,
			"area_factor": area_factor,
		},
		"nature": {
			"surface": surface_type,
			"relief": relief_type,
			"cover": natural_cover_type,
			"soil": soil_type,
			"climate": climate_type,
			"moisture": moisture_type,
			"features": features.duplicate(),
		},
		"resource": resource,
		"development": {
			"type": development_type,
			"level": development_level,
			"maturity": maturity,
			"damage": damage,
		},
		"population": {
			"rural_population": rural_population,
			"rural_capacity": rural_capacity,
		},
		"infrastructure": {
			"road_level": road_level,
			"irrigation_level": irrigation_level,
		},
		"factors": {
			"settlement_factor": settlement_factor,
			"usable_land_factor": usable_land_factor,
		},
	}
