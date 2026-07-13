"""Validate stable map ids and parent links.

This is intentionally about game/entity ids, not every physical helper layer.
The zone level is not part of the contract: it was removed from the planned
territory ladder on 2026-07-13.

Проверки новой архитектуры (см. АРХИТЕКТУРА_РЕГИОНОВ_И_ПРОВИНЦИЙ_АНАЛИЗ.md §24):
- уникальность id / numeric_id / legacy_id;
- формат id по уровням (province:<цифры>, region:<macro>:<slug>, macroregion:<slug>);
- совпадение наборов геометрия <-> паспорт (id, numeric_id, legacy_id);
- иерархия: macroregion_id провинции == macroregion_id её региона;
- запрещённые динамические поля в паспорте и геометрии;
- запрещённые статические поля в сценарии;
- реестр numeric_id: паспорт не расходится с реестром, номера не переиспользованы;
- aliases указывают на существующие id.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]

ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?::[a-z0-9_]+)*$")

PROVINCE_ID_RE = re.compile(r"^province:[0-9]+$")
REGION_ID_RE = re.compile(r"^region:[a-z0-9_]+:[a-z0-9_]+$")
MACROREGION_ID_RE = re.compile(r"^macroregion:[a-z0-9_]+$")

GEOMETRY_PATH = "assets/map_geometry/provinces.json"
PASSPORT_PATH = "assets/game_data/provinces.json"
REGIONS_PATH = "assets/game_data/regions.json"
MACROREGIONS_PATH = "assets/game_data/macroregions.json"
SCENARIO_PATH = "assets/scenarios/1444/province_state.json"
REGISTRY_PATH = "assets/migrations/province_numeric_id_registry.json"
ALIASES_PATH = "assets/migrations/map_id_aliases.json"

# Динамика (владение/культура/состояние) запрещена в паспорте и геометрии.
FORBIDDEN_STATIC_FIELDS = {
	"owner_country_id",
	"controller_country_id",
	"culture_id",
	"religion_id",
	"population",
	"buildings",
	"province_buildings",
	"devastation",
	"occupation",
	"garrison",
	"army_id",
	"city_state",
	"zone_id",
}

# Статика (геометрия/классификация) запрещена в сценарном состоянии.
FORBIDDEN_SCENARIO_FIELDS = {"rings", "bbox", "region_id", "macroregion_id", "zone_id"}


ENTITY_LAYERS = [
	{
		"level": "macroregion",
		"path": MACROREGIONS_PATH,
		"container": "macroregions",
		"required": False,
		"allow_duplicate_ids": False,
		"id_format": MACROREGION_ID_RE,
	},
	{
		"level": "region",
		"path": REGIONS_PATH,
		"container": "regions",
		"required": False,
		"allow_duplicate_ids": False,
		"id_format": REGION_ID_RE,
	},
	{
		"level": "province",
		"path": GEOMETRY_PATH,
		"container": "provinces",
		"required": False,
		"allow_duplicate_ids": False,
		"id_format": PROVINCE_ID_RE,
	},
	{
		"level": "province",
		"path": PASSPORT_PATH,
		"container": "provinces",
		"required": False,
		"allow_duplicate_ids": False,
		"id_format": PROVINCE_ID_RE,
	},
	{
		"level": "legacy_cell",
		"path": "assets/provinces.json",
		"container": "cells",
		"required": True,
		"allow_duplicate_ids": False,
	},
	{
		"level": "legacy_cell",
		"path": "assets/provinces_iberia.json",
		"container": "cells",
		"required": False,
		"allow_duplicate_ids": False,
	},
	{
		"level": "legacy_cell",
		"path": "assets/provinces_netherlands.json",
		"container": "cells",
		"required": False,
		# Several separate island pieces intentionally share one province id.
		"allow_duplicate_ids": True,
	},
	{
		"level": "legacy_region_cell",
		"path": "assets/regions_iberia.json",
		"container": "cells",
		"required": False,
		"allow_duplicate_ids": False,
	},
	{
		"level": "cell",
		"path": "assets/cells_test.json",
		"container": "cells",
		"required": False,
		"allow_duplicate_ids": False,
	},
	{
		"level": "cell",
		"path": "assets/cells_lacoruna_grid.json",
		"container": "cells",
		"required": False,
		"allow_duplicate_ids": False,
	},
]


def load_json(path: Path) -> Any:
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


def iter_items(data: Any, container: str) -> list[dict]:
	if not isinstance(data, dict):
		return []
	raw = data.get(container, [])
	return raw if isinstance(raw, list) else []


def load_items(rel_path: str, container: str) -> list[dict] | None:
	path = ROOT / rel_path
	if not path.exists():
		return None
	return iter_items(load_json(path), container)


def validate_entity_layer(spec: dict, ids_by_level: dict[str, set[str]], errors: list[str], warnings: list[str]) -> None:
	path = ROOT / spec["path"]
	level = spec["level"]
	if not path.exists():
		msg = f"{spec['path']}: missing"
		if spec.get("required", False):
			errors.append(msg)
		else:
			warnings.append(msg)
		return

	data = load_json(path)
	if isinstance(data, dict) and spec["path"].startswith(("assets/game_data/", "assets/map_geometry/", "assets/scenarios/")):
		if "schema_version" not in data:
			errors.append(f"{spec['path']}: missing schema_version")

	items = iter_items(data, spec["container"])
	id_format = spec.get("id_format")
	ids: list[str] = []
	for idx, item in enumerate(items):
		if not isinstance(item, dict):
			errors.append(f"{spec['path']}[{idx}]: item is not an object")
			continue
		entity_id = str(item.get("id", "")).strip()
		if not entity_id:
			errors.append(f"{spec['path']}[{idx}]: empty id")
			continue
		if not ID_RE.match(entity_id):
			errors.append(f"{spec['path']}[{idx}] {entity_id!r}: invalid id format")
		elif id_format is not None and not id_format.match(entity_id):
			errors.append(f"{spec['path']}[{idx}] {entity_id!r}: does not match {level} id format {id_format.pattern}")
		ids.append(entity_id)
		ids_by_level[level].add(entity_id)

	counts = Counter(ids)
	duplicates = sorted(entity_id for entity_id, count in counts.items() if count > 1)
	if duplicates and not spec.get("allow_duplicate_ids", False):
		errors.append(f"{spec['path']}: duplicate ids: {duplicates[:20]}")

	print(
		f"{spec['path']}: level={level}, items={len(items)}, ids={len(ids)}, "
		f"duplicates={len(duplicates)}"
	)


def validate_unique_field(rel_path: str, items: list[dict], field: str, errors: list[str]) -> None:
	values = [item.get(field) for item in items if item.get(field) not in (None, "")]
	counts = Counter(values)
	duplicates = sorted(str(v) for v, count in counts.items() if count > 1)
	if duplicates:
		errors.append(f"{rel_path}: duplicate {field}: {duplicates[:20]}")


def validate_forbidden_fields(rel_path: str, items: list[dict], forbidden: set[str], errors: list[str]) -> None:
	for idx, item in enumerate(items):
		if not isinstance(item, dict):
			continue
		bad = sorted(forbidden & set(item.keys()))
		zone_like = sorted(k for k in item.keys() if k.startswith("zone_") or k == "parents" and isinstance(item.get("parents"), dict) and "zone" in item["parents"])
		for field in bad + zone_like:
			errors.append(f"{rel_path}[{idx}] {item.get('id', item.get('province_id', ''))}: forbidden field {field!r}")


def validate_geometry_vs_passport(errors: list[str]) -> None:
	geometry = load_items(GEOMETRY_PATH, "provinces")
	passport = load_items(PASSPORT_PATH, "provinces")
	if geometry is None or passport is None:
		return
	geo_by_id = {item.get("id"): item for item in geometry}
	pass_by_id = {item.get("id"): item for item in passport}
	only_geo = sorted(set(geo_by_id) - set(pass_by_id))
	only_pass = sorted(set(pass_by_id) - set(geo_by_id))
	if only_geo:
		errors.append(f"{GEOMETRY_PATH}: provinces without passport: {only_geo[:10]} (+{max(0, len(only_geo) - 10)})")
	if only_pass:
		errors.append(f"{PASSPORT_PATH}: provinces without geometry: {only_pass[:10]} (+{max(0, len(only_pass) - 10)})")
	for entity_id in set(geo_by_id) & set(pass_by_id):
		for field in ("numeric_id", "legacy_id"):
			if geo_by_id[entity_id].get(field) != pass_by_id[entity_id].get(field):
				errors.append(
					f"{entity_id}: {field} mismatch geometry={geo_by_id[entity_id].get(field)!r} "
					f"passport={pass_by_id[entity_id].get(field)!r}"
				)
	print(f"geometry<->passport: common={len(set(geo_by_id) & set(pass_by_id))}")


def validate_hierarchy(errors: list[str]) -> None:
	passport = load_items(PASSPORT_PATH, "provinces")
	regions = load_items(REGIONS_PATH, "regions")
	macroregions = load_items(MACROREGIONS_PATH, "macroregions")
	if passport is None or regions is None or macroregions is None:
		return
	macro_ids = {item.get("id") for item in macroregions}
	region_macro = {item.get("id"): item.get("macroregion_id") for item in regions}
	for item in regions:
		if item.get("macroregion_id") not in macro_ids:
			errors.append(f"{REGIONS_PATH} {item.get('id')}: macroregion_id={item.get('macroregion_id')!r} does not exist")
	checked = 0
	for item in passport:
		region_id = str(item.get("region_id", "")).strip()
		macroregion_id = str(item.get("macroregion_id", "")).strip()
		if not region_id:
			if macroregion_id:
				errors.append(f"{PASSPORT_PATH} {item.get('id')}: macroregion_id without region_id")
			continue
		if region_id not in region_macro:
			errors.append(f"{PASSPORT_PATH} {item.get('id')}: region_id={region_id!r} does not exist")
			continue
		expected = region_macro[region_id]
		if macroregion_id != expected:
			errors.append(
				f"{PASSPORT_PATH} {item.get('id')}: macroregion mismatch: "
				f"province says {macroregion_id!r}, region says {expected!r}"
			)
		checked += 1
	print(f"hierarchy: provinces with region_id checked={checked}")


def validate_numeric_registry(errors: list[str], warnings: list[str]) -> None:
	passport = load_items(PASSPORT_PATH, "provinces")
	path = ROOT / REGISTRY_PATH
	if passport is None:
		return
	if not path.exists():
		warnings.append(f"{REGISTRY_PATH}: missing")
		return
	registry = load_json(path)
	by_legacy = registry.get("by_legacy_id", {})
	next_numeric = int(registry.get("next_numeric_id", 0))
	used = Counter(by_legacy.values())
	reused = sorted(str(n) for n, c in used.items() if c > 1)
	if reused:
		errors.append(f"{REGISTRY_PATH}: numeric_id issued twice: {reused[:20]}")
	if by_legacy and max(by_legacy.values()) >= next_numeric:
		errors.append(f"{REGISTRY_PATH}: next_numeric_id={next_numeric} <= max issued {max(by_legacy.values())}")
	for item in passport:
		legacy_id = str(item.get("legacy_id", ""))
		if legacy_id not in by_legacy:
			errors.append(f"{PASSPORT_PATH} {item.get('id')}: legacy_id {legacy_id!r} not in numeric id registry")
		elif by_legacy[legacy_id] != item.get("numeric_id"):
			errors.append(
				f"{PASSPORT_PATH} {item.get('id')}: numeric_id={item.get('numeric_id')} "
				f"!= registry {by_legacy[legacy_id]} for legacy_id {legacy_id!r}"
			)
		expected_id = f"province:{item.get('numeric_id')}"
		if item.get("id") != expected_id:
			errors.append(f"{PASSPORT_PATH} {item.get('id')}: id != province:<numeric_id> ({expected_id})")
	print(f"numeric id registry: entries={len(by_legacy)}, next={next_numeric}")


def validate_scenario(ids_by_level: dict[str, set[str]], errors: list[str], warnings: list[str]) -> None:
	path = ROOT / SCENARIO_PATH
	if not path.exists():
		warnings.append(f"{SCENARIO_PATH}: missing")
		return
	data = load_json(path)
	items = iter_items(data, "province_states")
	if "schema_version" not in data:
		errors.append(f"{SCENARIO_PATH}: missing schema_version")
	province_ids = ids_by_level.get("province", set())
	seen: Counter[str] = Counter()
	for idx, item in enumerate(items):
		if not isinstance(item, dict):
			errors.append(f"{SCENARIO_PATH}[{idx}]: item is not an object")
			continue
		province_id = str(item.get("province_id", "")).strip()
		if not province_id:
			errors.append(f"{SCENARIO_PATH}[{idx}]: empty province_id")
			continue
		seen[province_id] += 1
		if province_id not in province_ids:
			errors.append(f"{SCENARIO_PATH}[{idx}]: province_id={province_id!r} does not exist")
	duplicates = sorted(pid for pid, count in seen.items() if count > 1)
	if duplicates:
		errors.append(f"{SCENARIO_PATH}: duplicate province_id: {duplicates[:20]}")
	validate_forbidden_fields(SCENARIO_PATH, items, FORBIDDEN_SCENARIO_FIELDS, errors)
	print(f"{SCENARIO_PATH}: references={len(items)}")


def validate_aliases(ids_by_level: dict[str, set[str]], errors: list[str], warnings: list[str]) -> None:
	path = ROOT / ALIASES_PATH
	if not path.exists():
		warnings.append(f"{ALIASES_PATH}: missing")
		return
	data = load_json(path)
	aliases = data.get("aliases", {})
	all_ids: set[str] = set()
	for ids in ids_by_level.values():
		all_ids |= ids
	for old_id, new_id in aliases.items():
		if new_id not in all_ids:
			errors.append(f"{ALIASES_PATH}: alias target {new_id!r} (from {old_id!r}) does not exist")
		if old_id in all_ids and old_id != new_id:
			errors.append(f"{ALIASES_PATH}: alias source {old_id!r} still exists as a real id")
	print(f"{ALIASES_PATH}: aliases={len(aliases)}")


def validate_global_collisions(ids_by_level: dict[str, set[str]], errors: list[str]) -> None:
	owner_by_id: dict[str, list[str]] = defaultdict(list)
	for level, ids in ids_by_level.items():
		for entity_id in ids:
			owner_by_id[entity_id].append(level)
	for entity_id, levels in sorted(owner_by_id.items()):
		unique_levels = set(levels)
		# Легаси-слои и новая архитектура намеренно живут параллельно.
		unique_levels.discard("legacy_cell")
		unique_levels.discard("legacy_region_cell")
		if len(unique_levels) > 1:
			errors.append(f"global id collision {entity_id!r}: levels={sorted(set(levels))}")


def main() -> int:
	ids_by_level: dict[str, set[str]] = defaultdict(set)
	errors: list[str] = []
	warnings: list[str] = []

	for spec in ENTITY_LAYERS:
		validate_entity_layer(spec, ids_by_level, errors, warnings)

	validate_global_collisions(ids_by_level, errors)

	for rel_path in (GEOMETRY_PATH, PASSPORT_PATH):
		items = load_items(rel_path, "provinces")
		if items is not None:
			validate_unique_field(rel_path, items, "numeric_id", errors)
			validate_unique_field(rel_path, items, "legacy_id", errors)
			validate_forbidden_fields(rel_path, items, FORBIDDEN_STATIC_FIELDS, errors)

	validate_geometry_vs_passport(errors)
	validate_hierarchy(errors)
	validate_numeric_registry(errors, warnings)
	validate_scenario(ids_by_level, errors, warnings)
	validate_aliases(ids_by_level, errors, warnings)

	for warning in warnings:
		print(f"WARNING: {warning}")
	if errors:
		print("\nID VALIDATION FAILED:")
		for error in errors:
			print(f"- {error}")
		return 1
	print("\nID VALIDATION OK")
	return 0


if __name__ == "__main__":
	sys.exit(main())
