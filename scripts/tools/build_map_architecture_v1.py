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
		"id": "region:iberia:andalusia",
		"macroregion_id": "macroregion:iberia",
		"slug": "andalusia",
		"name": "Andalusia",
		"display_name_ru": "Андалусия",
	},
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

	for cell in cells:
		legacy_id = str(cell.get("id", "")).strip()
		name = str(cell.get("name", "")).strip()
		override = CANONICAL_OVERRIDES.get(legacy_id, {})

		numeric_id = by_legacy.get(legacy_id)
		if numeric_id is None:
			numeric_id = next_id
			by_legacy[legacy_id] = numeric_id
			next_id += 1
			new_numbers += 1
		stable_id = f"province:{numeric_id}"

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
	print(f"wrote {SCENARIO_OUT.relative_to(ROOT)}: {len(province_states)} province states")
	print(f"numeric ids: new={new_numbers}, next_numeric_id={next_id}")
	print(f"aliases: +{new_aliases} (всего {len(aliases)})")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
