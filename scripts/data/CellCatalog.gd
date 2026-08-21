class_name CellCatalog
extends RefCounted
## Загружает игровые данные Cell из JSON, посчитанного офлайн (сейчас —
## scripts/tools/build_cells_test.py -> assets/cells_test.json, тестовая
## нарезка одной провинции — Ла-Корунья). id/area_km2/name и тестовые
## игровые атрибуты (природа/освоение, см. TEST_CELL_ATTRS в генераторе) в
## JSON УЖЕ посчитаны/расставлены в Python — здесь их просто переносим в
## Cell, без пересчёта. area_factor/settlement_factor/rural_capacity — это
## посчитано ЗДЕСЬ (раздел 23 ПЛОЩАДЬ_КЛЕТОК_И_ПОЛЕЗНОСТЬ.md: "площадь и
## пригодность считаются один раз при генерации/загрузке карты, не каждый
## ход"), по формулам из GameplayTables.gd/Cell.gd.
##
## Геометрия (rings/bbox) сюда НЕ грузится — за отрисовку тех же клеток
## отвечает IrregularCellProvider (see TileMapViewer.gd, слой "Клетки (тест:
## Ла-Корунья)"), у него свой, уже готовый парсер JSON. Здесь только данные:
## id клетки в обоих местах совпадает (JSON "id"), этого достаточно, чтобы
## позже связать геометрию конкретной клетки с её игровыми данными.


## Разбирает JSON по пути path, возвращает Array[Cell] (пустой, если файла
## нет или он не разобрался — так же тихо, как остальные *TileProvider).
static func load_cells(path: String) -> Array[Cell]:
	var result: Array[Cell] = []
	if not FileAccess.file_exists(path):
		push_warning("CellCatalog: нет файла %s" % path)
		return result
	var text := FileAccess.get_file_as_string(path)
	var parsed = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		push_warning("CellCatalog: не удалось разобрать %s" % path)
		return result
	for entry in parsed.get("cells", []):
		var cell := Cell.new(str(entry.get("id", "")))
		cell.display_name = str(entry.get("name", ""))
		cell.region_id = str(entry.get("region_id", cell.region_id))
		cell.city_id = str(entry.get("city_id", cell.city_id))
		cell.owner_id = str(entry.get("owner_id", cell.owner_id))
		cell.area_km2 = float(entry.get("area_km2", 0.0))
		cell.recompute_area_factor()

		cell.province_center_status = str(entry.get("province_center_status", cell.province_center_status))
		cell.cell_type = str(entry.get("cell_type", cell.cell_type))
		cell.surface_type = str(entry.get("surface_type", cell.surface_type))
		cell.relief_type = str(entry.get("relief_type", cell.relief_type))
		cell.natural_cover_type = str(entry.get("natural_cover_type", cell.natural_cover_type))
		cell.soil_type = str(entry.get("soil_type", cell.soil_type))
		cell.climate_type = str(entry.get("climate_type", cell.climate_type))
		cell.moisture_type = str(entry.get("moisture_type", cell.moisture_type))
		cell.resource = str(entry.get("resource", cell.resource))
		var features_raw: Array = entry.get("features", [])
		var features: Array[String] = []
		for f in features_raw:
			features.append(str(f))
		cell.features = features

		# settlement_factor: если явно не задан в JSON — берём дефолт по
		# relief_type (раздел 1 ПЛОЩАДЬ_КЛЕТОК_И_ПОЛЕЗНОСТЬ.md), а не голую
		# 1.0 из Cell.gd по умолчанию.
		if entry.has("settlement_factor"):
			cell.settlement_factor = float(entry["settlement_factor"])
		else:
			cell.settlement_factor = GameplayTables.default_settlement_factor(cell.relief_type)
		cell.usable_land_factor = float(entry.get("usable_land_factor", cell.usable_land_factor))

		cell.development_type = str(entry.get("development_type", cell.development_type))
		cell.development_level = int(entry.get("development_level", cell.development_level))
		cell.maturity = float(entry.get("maturity", cell.maturity))
		cell.damage = float(entry.get("damage", cell.damage))
		cell.road_level = int(entry.get("road_level", cell.road_level))
		cell.irrigation_level = int(entry.get("irrigation_level", cell.irrigation_level))
		var infrastructure_raw: Array = entry.get("infrastructure_flags", [])
		var infrastructure_flags: Array[String] = []
		for flag in infrastructure_raw:
			infrastructure_flags.append(str(flag))
		cell.infrastructure_flags = infrastructure_flags
		var states_raw: Array = entry.get("state_flags", [])
		var state_flags: Array[String] = []
		for flag in states_raw:
			state_flags.append(str(flag))
		cell.state_flags = state_flags

		# rural_capacity — раздел 5: считается один раз здесь, при загрузке,
		# region_base_rural_density/infrastructure/health/security берём из
		# временных тестовых констант GameplayTables (см. их комментарий —
		# заменить настоящим Region, когда он появится).
		cell.compute_rural_capacity(
			GameplayTables.TEST_GALICIA_BASE_RURAL_DENSITY,
			GameplayTables.TEST_GALICIA_INFRASTRUCTURE_FACTOR,
			GameplayTables.TEST_GALICIA_HEALTH_FACTOR,
			GameplayTables.TEST_GALICIA_SECURITY_FACTOR)
		# rural_population — тестовое "текущее" население: доля от ёмкости по
		# зрелости освоения (maturity), а не сразу вся ёмкость (в реальной
		# игре население растёт к ёмкости постепенно, см. раздел 8 доки).
		cell.rural_population = int(round(cell.rural_capacity * cell.maturity))
		cell.apply_minimum_population_if_settled()

		result.append(cell)
	return result
