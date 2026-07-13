"""Build the v1 separated map data architecture.

The current playable layers still read the legacy assets/provinces.json file.
This script creates the mature data layout next to it:

- assets/map_geometry/provinces.json: only shapes and bbox.
- assets/game_data/provinces.json: stable province passport data.
- assets/game_data/regions.json + macroregions.json: static geography levels.
- assets/scenarios/1444/province_state.json: mutable start-state data.

Key rules (см. АРХИТЕКТУРА_РЕГИОНОВ_И_ПРОВИНЦИЙ_АНАЛИЗ.md):

- Стабильный ID провинции — province:<numeric_id> (например province:2839).
  Он не зависит ни от владельца, ни от региона, ни от названия и никогда
  не меняется. Читаемость обеспечивают поля slug/name/display_name_ru.
- numeric_id выдаётся через постоянный реестр
  assets/migrations/province_numeric_id_registry.json: legacy_id получает
  номер один раз и навсегда, номера удалённых провинций не переиспользуются.
- region_id — источник истины принадлежности; macroregion_id в паспорте —
  денормализованный кэш, вычисляется отсюда из regions.json и проверяется
  валидатором (validate_map_ids.py).
- При смене стабильных ID старые ID дописываются в
  assets/migrations/map_id_aliases.json (старый -> новый), существующие
  записи оттуда никогда не удаляются.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import unicodedata
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "assets/provinces.json"

GEOMETRY_OUT = ROOT / "assets/map_geometry/provinces.json"
PROVINCES_OUT = ROOT / "assets/game_data/provinces.json"
REGIONS_OUT = ROOT / "assets/game_data/regions.json"
MACROREGIONS_OUT = ROOT / "assets/game_data/macroregions.json"
LAND_CELL_PROFILES_OUT = ROOT / "assets/game_data/land_cell_generation_profiles.json"
PROVINCE_CELL_OVERRIDES_OUT = ROOT / "assets/game_data/province_cell_generation_overrides.json"
SCENARIO_OUT = ROOT / "assets/scenarios/1444/province_state.json"

NUMERIC_ID_REGISTRY = ROOT / "assets/migrations/province_numeric_id_registry.json"
ALIASES_OUT = ROOT / "assets/migrations/map_id_aliases.json"


# Историко-географическая классификация уже размеченных провинций.
# Ключ — legacy_id (замороженный id клетки из assets/provinces.json).
# ID провинции здесь больше НЕ задаётся — он всегда province:<numeric_id>.
CANONICAL_OVERRIDES: dict[str, dict[str, str]] = {
	"spain__sevilla": {
		"region_id": "region:iberia:andalusia",
		"display_name_ru": "Севилья",
	},
	"spain__huelva": {
		"region_id": "region:iberia:andalusia",
		"display_name_ru": "Уэльва",
	},
	"spain__c_diz": {
		"region_id": "region:iberia:andalusia",
		"display_name_ru": "Кадис",
	},
	"spain__c_rdoba": {
		"region_id": "region:iberia:andalusia",
		"display_name_ru": "Кордова",
	},
	"spain__granada": {
		"region_id": "region:iberia:andalusia",
		"display_name_ru": "Гранада",
	},
	"spain__ja_n": {
		"region_id": "region:iberia:andalusia",
		"display_name_ru": "Хаэн",
	},
	"spain__almer_a": {
		"region_id": "region:iberia:andalusia",
		"display_name_ru": "Альмерия",
	},
	"spain__m_laga": {
		"region_id": "region:iberia:andalusia",
		"display_name_ru": "Малага",
	},
	"france__mayenne": {
		"region_id": "region:france:pays_de_la_loire",
		"display_name_ru": "Майенн",
	},
}

IBERIA_REGION_BY_PROVINCE_NAME = {
	"La Coruña": "galicia",
	"Lugo": "galicia",
	"Orense": "galicia",
	"Pontevedra": "galicia",
	"Asturias": "asturias",
	"Cantabria": "cantabrian_basque_coast",
	"Bizkaia": "cantabrian_basque_coast",
	"Gipuzkoa": "cantabrian_basque_coast",
	"Álava": "cantabrian_basque_coast",
	"Navarra": "navarre",
	"León": "leon",
	"Zamora": "leon",
	"Salamanca": "leon",
	"Burgos": "old_castile",
	"Palencia": "old_castile",
	"Valladolid": "old_castile",
	"Segovia": "old_castile",
	"Soria": "old_castile",
	"Ávila": "old_castile",
	"La Rioja": "old_castile",
	"Madrid": "new_castile",
	"Toledo": "new_castile",
	"Guadalajara": "new_castile",
	"Cuenca": "new_castile",
	"Ciudad Real": "la_mancha",
	"Albacete": "la_mancha",
	"Badajoz": "extremadura",
	"Cáceres": "extremadura",
	"Huesca": "aragon",
	"Zaragoza": "aragon",
	"Teruel": "aragon",
	"Barcelona": "catalonia",
	"Gerona": "catalonia",
	"Lérida": "catalonia",
	"Tarragona": "catalonia",
	"Castellón": "valencia",
	"Valencia": "valencia",
	"Alicante": "valencia",
	"Murcia": "murcia",
	"Córdoba": "upper_andalusia",
	"Jaén": "upper_andalusia",
	"Granada": "upper_andalusia",
	"Almería": "upper_andalusia",
	"Sevilla": "lower_andalusia",
	"Cádiz": "lower_andalusia",
	"Huelva": "lower_andalusia",
	"Málaga": "lower_andalusia",
	"Baleares": "balearic_islands",
	"Viana do Castelo": "minho",
	"Braga": "minho",
	"Porto": "minho",
	"Vila Real": "tras_os_montes",
	"Bragança": "tras_os_montes",
	"Aveiro": "beira_litoral",
	"Coimbra": "beira_litoral",
	"Viseu": "beira_interior",
	"Guarda": "beira_interior",
	"Castelo Branco": "beira_interior",
	"Leiria": "estremadura_ribatejo",
	"Lisboa": "estremadura_ribatejo",
	"Santarém": "estremadura_ribatejo",
	"Setúbal": "estremadura_ribatejo",
	"Portalegre": "alentejo",
	"Évora": "alentejo",
	"Beja": "alentejo",
	"Faro": "algarve",
}


LAND_CELL_GENERATION_PROFILES = [
	{
		"id": "P0",
		"name": "Metropolitan core",
		"display_name_ru": "Метропольное ядро",
		"target_cell_area_km2": 500,
		"min_cells_per_province": 3,
		"max_cells_per_province": 8,
		"examples": "Лондон, Парижское ядро, крупнейшие городские агломерации",
		"rule": "Только подтверждённые исключения; городской минимум 4–5 клеток",
	},
	{
		"id": "P1",
		"name": "Ultra-dense historical",
		"display_name_ru": "Сверхплотный исторический",
		"target_cell_area_km2": 800,
		"min_cells_per_province": 1,
		"max_cells_per_province": 10,
		"examples": "Фландрия, Голландия, дельта Янцзы, Ява",
		"rule": "Очень плотная сеть городов, портов, дорог и коротких маршрутов",
	},
	{
		"id": "P2",
		"name": "Dense historical",
		"display_name_ru": "Плотный исторический",
		"target_cell_area_km2": 1400,
		"min_cells_per_province": 1,
		"max_cells_per_province": 12,
		"examples": "Северная Италия, Каталония, Гангская равнина, Япония",
		"rule": "Плотная историческая сеть поселений и высокая стратегическая насыщенность",
	},
	{
		"id": "P3",
		"name": "Normal historical",
		"display_name_ru": "Обычный исторический",
		"target_cell_area_km2": 2200,
		"min_cells_per_province": 1,
		"max_cells_per_province": 14,
		"examples": "Галисия, Франция, Англия, Германия, Балканы",
		"rule": "Базовый профиль развитых исторических территорий",
	},
	{
		"id": "P4",
		"name": "Broad agrarian",
		"display_name_ru": "Широкий аграрный",
		"target_cell_area_km2": 4000,
		"min_cells_per_province": 1,
		"max_cells_per_province": 16,
		"examples": "Внутренняя Иберия, Украина, Анатолия, Декан",
		"rule": "Крупные сельские пространства без чрезмерного укрупнения",
	},
	{
		"id": "P5",
		"name": "Sparse agrarian or steppe",
		"display_name_ru": "Редкий аграрный/степной",
		"target_cell_area_km2": 8000,
		"min_cells_per_province": 1,
		"max_cells_per_province": 16,
		"examples": "Великие равнины, Поволжье, южная степь, часть Африки",
		"rule": "Большие клетки, но сохраняется локальная география",
	},
	{
		"id": "P6",
		"name": "Frontier",
		"display_name_ru": "Фронтирный",
		"target_cell_area_km2": 18000,
		"min_cells_per_province": 1,
		"max_cells_per_province": 14,
		"examples": "Патагония, Сахель, горные окраины, север Канады",
		"rule": "Низкая плотность, длинные маршруты и крупные провинции",
	},
	{
		"id": "P7",
		"name": "Sparse",
		"display_name_ru": "Редкий",
		"target_cell_area_km2": 45000,
		"min_cells_per_province": 1,
		"max_cells_per_province": 12,
		"examples": "Амазония, пустыни, тайга, внутренние плато",
		"rule": "Очень крупные клетки; локальные центры дают исключения",
	},
	{
		"id": "P8",
		"name": "Extremely sparse",
		"display_name_ru": "Крайне редкий",
		"target_cell_area_km2": 150000,
		"min_cells_per_province": 1,
		"max_cells_per_province": 12,
		"examples": "Центральная Сибирь, Арктика, Сахара, Австралийская глубинка",
		"rule": "Гигантские клетки; число клеток жёстко ограничено",
	},
]


IBERIA_REGIONS = [
	("galicia", "Galicia", "Галисия", "P3", 2100, 1, 10, 1.3, 1.15, "Влажное атлантическое побережье; Ла-Корунья ≈ 4 клетки"),
	("asturias", "Asturias", "Астурия", "P3", 1800, 1, 10, 1.1, 1.25, "Узкая прибрежно-горная территория"),
	("cantabrian_basque_coast", "Cantabrian-Basque Coast", "Кантабрийско-Баскское побережье", "P2", 1300, 1, 12, 1.55, 1.25, "Плотная портовая и рельефно сложная зона"),
	("navarre", "Navarre", "Наварра", "P3", 1900, 1, 10, 1.2, 1.2, "Пиренейские проходы и переход к равнинам"),
	("leon", "Leon", "Леон", "P4", 3000, 1, 12, 0.9, 1.05, "Широкое внутреннее плато"),
	("old_castile", "Old Castile", "Старая Кастилия", "P4", 2800, 1, 14, 1.0, 1.05, "Крупные аграрные пространства и исторические города"),
	("new_castile", "New Castile", "Новая Кастилия", "P3", 2400, 1, 14, 1.2, 1.05, "Мадрид и Толедо создают локальные исключения"),
	("la_mancha", "La Mancha", "Ла-Манча", "P4", 4300, 1, 12, 0.75, 0.95, "Открытые сухие равнины"),
	("extremadura", "Extremadura", "Эстремадура", "P4", 4200, 1, 12, 0.75, 1.0, "Редкая историческая сеть поселений"),
	("aragon", "Aragon", "Арагон", "P4", 3200, 1, 14, 0.95, 1.15, "Долина Эбро и горные окраины"),
	("catalonia", "Catalonia", "Каталония", "P2", 1300, 1, 12, 1.65, 1.2, "Плотная портово-городская сеть"),
	("valencia", "Valencia", "Валенсия", "P2", 1450, 1, 12, 1.5, 1.15, "Плотная прибрежная аграрно-городская полоса"),
	("murcia", "Murcia", "Мурсия", "P3", 2200, 1, 10, 1.1, 1.1, "Прибрежные центры, более редкая внутренняя часть"),
	("upper_andalusia", "Upper Andalusia", "Верхняя Андалусия", "P3", 2300, 1, 14, 1.15, 1.25, "Горные системы, долины и исторические центры"),
	("lower_andalusia", "Lower Andalusia", "Нижняя Андалусия", "P2", 1700, 1, 14, 1.45, 1.15, "Гвадалквивир, Севилья, Кадис и порты"),
	("balearic_islands", "Balearic Islands", "Балеарские острова", "P1", 900, 1, 8, 1.3, 1.35, "Островная геометрия; отдельные острова и проливы"),
	("minho", "Minho", "Минью", "P2", 1350, 1, 10, 1.55, 1.15, "Очень плотная сеть Северной Португалии"),
	("tras_os_montes", "Tras-os-Montes", "Траз-уш-Монтиш", "P4", 2800, 1, 10, 0.85, 1.2, "Горная внутренняя территория"),
	("beira_litoral", "Beira Litoral", "Бейра-Литорал", "P3", 1700, 1, 12, 1.35, 1.15, "Плотное побережье и речные долины"),
	("beira_interior", "Beira Interior", "Бейра-Интериор", "P4", 3000, 1, 10, 0.85, 1.15, "Внутренняя горная и платообразная часть"),
	("estremadura_ribatejo", "Estremadura and Ribatejo", "Эштремадура-и-Рибатежу", "P2", 1500, 1, 12, 1.55, 1.15, "Лиссабон, Тежу и плотная прибрежная система"),
	("alentejo", "Alentejo", "Алентежу", "P4", 4000, 1, 12, 0.7, 0.95, "Крупные сельскохозяйственные пространства"),
	("algarve", "Algarve", "Алгарве", "P3", 1700, 1, 10, 1.2, 1.2, "Узкая прибрежная полоса с портами"),
]


PROVINCE_CELL_OVERRIDES_BY_LEGACY_ID = [
	{
		"legacy_id": "spain__madrid",
		"minimum_cell_count": 4,
		"forced_cell_count": None,
		"reason": "major_metropolitan_core_madrid",
	},
	{
		"legacy_id": "portugal__lisboa_2",
		"minimum_cell_count": 4,
		"forced_cell_count": None,
		"reason": "major_metropolitan_core_lisbon",
	},
	{
		"legacy_id": "portugal__porto",
		"minimum_cell_count": 3,
		"forced_cell_count": None,
		"reason": "major_port_metropolitan_core_porto",
	},
]


MACROREGIONS = [
	{
		"id": "macroregion:iberia",
		"slug": "iberia",
		"name": "Iberia",
		"display_name_ru": "Иберия",
	},
	{
		"id": "macroregion:france",
		"slug": "france",
		"name": "France",
		"display_name_ru": "Франция",
	},
]


REGIONS = [
	{
		"id": f"region:iberia:{slug}",
		"macroregion_id": "macroregion:iberia",
		"slug": slug,
		"name": name,
		"display_name_ru": display_name_ru,
		"land_cell_generation": {
			"profile_id": profile_id,
			"target_cell_area_km2": target,
			"min_cells_per_province": min_cells,
			"max_cells_per_province": max_cells,
			"historical_density_index": historical_density,
			"geographic_complexity_index": geographic_complexity,
			"note": note,
		},
	}
	for (
		slug,
		name,
		display_name_ru,
		profile_id,
		target,
		min_cells,
		max_cells,
		historical_density,
		geographic_complexity,
		note,
	) in IBERIA_REGIONS
] + [
	{
		"id": "region:france:pays_de_la_loire",
		"macroregion_id": "macroregion:france",
		"slug": "pays_de_la_loire",
		"name": "Pays de la Loire",
		"display_name_ru": "Пеи-де-ла-Луар",
	},
]


def load_json(path: Path) -> Any:
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


def write_json(path: Path, data: Any, compact: bool = True) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", encoding="utf-8", newline="\n") as f:
		if compact:
			json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
		else:
			json.dump(data, f, ensure_ascii=False, indent=1)
		f.write("\n")


def slugify(value: str) -> str:
	"""ASCII-slug с транслитерацией диакритики: 'Ríos' -> 'rios', 'Sør' -> 'sor'."""
	value = unicodedata.normalize("NFKD", value)
	value = "".join(ch for ch in value if not unicodedata.combining(ch))
	value = value.lower()
	value = re.sub(r"[^a-z0-9]+", "_", value)
	value = re.sub(r"_+", "_", value).strip("_")
	return value or "unnamed"


def load_registry() -> dict[str, Any]:
	if NUMERIC_ID_REGISTRY.exists():
		return load_json(NUMERIC_ID_REGISTRY)
	return {
		"schema_version": 1,
		"comment": (
			"Постоянные numeric_id провинций. Номер выдаётся legacy_id один раз "
			"и навсегда; удалённые номера не переиспользуются. Файл обновляется "
			"генератором build_map_architecture_v1.py, вручную не редактировать."
		),
		"next_numeric_id": 0,
		"by_legacy_id": {},
	}


def load_aliases() -> dict[str, Any]:
	if ALIASES_OUT.exists():
		return load_json(ALIASES_OUT)
	return {
		"schema_version": 1,
		"comment": (
			"Старые ID карты -> актуальные. Записи только добавляются и никогда "
			"не удаляются: по ним загрузчики и мигаторы понимают старые сценарии, "
			"сейвы и ссылки."
		),
		"aliases": {},
	}


def content_version() -> str:
	return _dt.date.today().strftime("%Y.%m.%d")


def main() -> int:
	source = load_json(SRC)
	cells = source.get("cells", [])
	world_px = source.get("world_px")

	registry = load_registry()
	by_legacy: dict[str, int] = registry["by_legacy_id"]
	next_id = int(registry["next_numeric_id"])
	new_numbers = 0

	aliases_doc = load_aliases()
	aliases: dict[str, str] = aliases_doc["aliases"]

	# Старые стабильные ID из прошлой версии паспорта -> aliases.
	old_passport_ids: dict[str, str] = {}
	if PROVINCES_OUT.exists():
		old_doc = load_json(PROVINCES_OUT)
		for item in old_doc.get("provinces", []):
			old_passport_ids[str(item.get("legacy_id", ""))] = str(item.get("id", ""))

	region_to_macro = {r["id"]: r["macroregion_id"] for r in REGIONS}

	geometry_provinces: list[dict[str, Any]] = []
	game_provinces: list[dict[str, Any]] = []
	province_states: list[dict[str, Any]] = []
	new_aliases = 0
	stable_id_by_legacy: dict[str, str] = {}

	for cell in cells:
		legacy_id = str(cell.get("id", "")).strip()
		name = str(cell.get("name", "")).strip()
		override = dict(CANONICAL_OVERRIDES.get(legacy_id, {}))
		is_iberian_source = legacy_id.startswith(("spain__", "portugal__"))
		iberia_region_slug = IBERIA_REGION_BY_PROVINCE_NAME.get(name) if is_iberian_source else None
		if iberia_region_slug is not None:
			override["region_id"] = f"region:iberia:{iberia_region_slug}"

		numeric_id = by_legacy.get(legacy_id)
		if numeric_id is None:
			numeric_id = next_id
			by_legacy[legacy_id] = numeric_id
			next_id += 1
			new_numbers += 1
		stable_id = f"province:{numeric_id}"
		stable_id_by_legacy[legacy_id] = stable_id

		old_id = old_passport_ids.get(legacy_id, "")
		if old_id and old_id != stable_id and old_id not in aliases:
			aliases[old_id] = stable_id
			new_aliases += 1

		region_id = override.get("region_id", "")
		macroregion_id = region_to_macro.get(region_id, "") if region_id else ""

		geometry_provinces.append(
			{
				"id": stable_id,
				"legacy_id": legacy_id,
				"numeric_id": numeric_id,
				"bbox": cell.get("bbox", []),
				"rings": cell.get("rings", []),
			}
		)

		game_provinces.append(
			{
				"id": stable_id,
				"legacy_id": legacy_id,
				"numeric_id": numeric_id,
				"slug": slugify(name),
				"name": name,
				"display_name_ru": override.get("display_name_ru", ""),
				"region_id": region_id,
				"macroregion_id": macroregion_id,
				"terrain_id": "",
				"climate_id": "",
			}
		)

		province_states.append(
			{
				"province_id": stable_id,
				"owner_country_id": "",
				"controller_country_id": "",
				"culture_id": "",
				"religion_id": "",
				"population": None,
				"province_buildings": {},
			}
		)

	registry["next_numeric_id"] = next_id
	version = content_version()

	write_json(NUMERIC_ID_REGISTRY, registry, compact=False)
	write_json(ALIASES_OUT, aliases_doc, compact=False)
	write_json(
		GEOMETRY_OUT,
		{
			"schema_version": 2,
			"geometry_version": version,
			"world_px": world_px,
			"source": "assets/provinces.json",
			"provinces": geometry_provinces,
		},
	)
	write_json(
		PROVINCES_OUT,
		{
			"schema_version": 2,
			"content_version": version,
			"source": "assets/provinces.json",
			"provinces": game_provinces,
		},
	)
	write_json(
		MACROREGIONS_OUT,
		{
			"schema_version": 2,
			"content_version": version,
			"macroregions": MACROREGIONS,
		},
	)
	write_json(
		REGIONS_OUT,
		{
			"schema_version": 2,
			"content_version": version,
			"regions": REGIONS,
		},
	)
	write_json(
		LAND_CELL_PROFILES_OUT,
		{
			"schema_version": 1,
			"content_version": version,
			"profiles": LAND_CELL_GENERATION_PROFILES,
		},
	)
	province_cell_overrides = []
	for item in PROVINCE_CELL_OVERRIDES_BY_LEGACY_ID:
		legacy_id = item["legacy_id"]
		province_id = stable_id_by_legacy.get(legacy_id)
		if not province_id:
			raise ValueError(f"Не найден legacy_id для override клеток: {legacy_id}")
		province_cell_overrides.append({
			"province_id": province_id,
			"legacy_id": legacy_id,
			"minimum_cell_count": item.get("minimum_cell_count"),
			"forced_cell_count": item.get("forced_cell_count"),
			"reason": item["reason"],
		})
	write_json(
		PROVINCE_CELL_OVERRIDES_OUT,
		{
			"schema_version": 1,
			"content_version": version,
			"overrides": province_cell_overrides,
		},
	)
	write_json(
		SCENARIO_OUT,
		{
			"schema_version": 2,
			"scenario_id": "scenario:1444",
			"map_content_version": version,
			"province_states": province_states,
		},
	)

	print(f"wrote {GEOMETRY_OUT.relative_to(ROOT)}: {len(geometry_provinces)} provinces")
	print(f"wrote {PROVINCES_OUT.relative_to(ROOT)}: {len(game_provinces)} provinces")
	print(f"wrote {REGIONS_OUT.relative_to(ROOT)}: {len(REGIONS)} regions")
	print(f"wrote {LAND_CELL_PROFILES_OUT.relative_to(ROOT)}: {len(LAND_CELL_GENERATION_PROFILES)} profiles")
	print(f"wrote {PROVINCE_CELL_OVERRIDES_OUT.relative_to(ROOT)}: {len(province_cell_overrides)} overrides")
	print(f"wrote {SCENARIO_OUT.relative_to(ROOT)}: {len(province_states)} province states")
	print(f"numeric ids: new={new_numbers}, next_numeric_id={next_id}")
	print(f"aliases: +{new_aliases} (всего {len(aliases)})")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
