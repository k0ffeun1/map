#!/usr/bin/env python3
"""Precompute target gameplay-cell counts for every world Admin-1 province.

This stage deliberately DOES NOT generate cell geometry. It implements the
order required by the user's regional-profile workbook:

    province -> assigned historical region -> table profile -> exact count

Inputs are all versioned project data. The regional source file is a compact
UTF-8 transcription of the uploaded workbook sheets "Мировые регионы v1" and
"Иберия". The generator expands it to a normal JSON catalog as one of its
outputs.

Important project rule: relief/terrain is generated AFTER cells, therefore
relief_factor is hard-locked to 1.0 here. The workbook does not define numeric
classifier thresholds for automatically converting coastline/shape geometry
into the discrete local coefficients, so coast_factor and shape_factor also
remain neutral (1.0) unless a future explicit per-province source/override is
added. We do not silently guess those classes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

ROOT = Path(__file__).resolve().parents[2]
WORLD_PX = 8192.0
EARTH_RADIUS_KM = 6371.0088

GEOMETRY_PATH = ROOT / "assets" / "map_geometry" / "provinces.json"
IDENTITY_PATH = ROOT / "assets" / "game_data" / "provinces.json"
ASSIGNMENTS_PATH = ROOT / "assets" / "game_data" / "world_region_assignments_draft.json"
PROFILE_SOURCE_PATH = ROOT / "assets" / "game_data" / "world_region_cell_profiles_source.txt"
BASE_PROFILES_PATH = ROOT / "assets" / "game_data" / "land_cell_generation_profiles.json"
OVERRIDES_PATH = ROOT / "assets" / "game_data" / "province_cell_generation_overrides.json"

PROFILE_JSON_PATH = ROOT / "assets" / "game_data" / "world_region_cell_profiles.json"
TARGETS_PATH = ROOT / "assets" / "game_data" / "world_province_cell_targets.json"
REPORT_PATH = ROOT / "reports" / "world_province_cell_targets.json"

EXPECTED_PROVINCES = 4027
EXPECTED_WORLD_PROFILES = 273
EXPECTED_IBERIA_PROFILES = 23

IBERIA_IDS = {
    "Галисия": "region:iberia:galicia",
    "Астурия": "region:iberia:asturias",
    "Кантабрийско-Баскское побережье": "region:iberia:cantabrian_basque_coast",
    "Наварра": "region:iberia:navarre",
    "Леон": "region:iberia:leon",
    "Старая Кастилия": "region:iberia:old_castile",
    "Новая Кастилия": "region:iberia:new_castile",
    "Ла-Манча": "region:iberia:la_mancha",
    "Эстремадура": "region:iberia:extremadura",
    "Арагон": "region:iberia:aragon",
    "Каталония": "region:iberia:catalonia",
    "Валенсия": "region:iberia:valencia",
    "Мурсия": "region:iberia:murcia",
    "Верхняя Андалусия": "region:iberia:upper_andalusia",
    "Нижняя Андалусия": "region:iberia:lower_andalusia",
    "Балеарские острова": "region:iberia:balearic_islands",
    "Минью": "region:iberia:minho",
    "Траз-уш-Монтиш": "region:iberia:tras_os_montes",
    "Бейра-Литорал": "region:iberia:beira_litoral",
    "Бейра-Интериор": "region:iberia:beira_interior",
    "Эштремадура-и-Рибатежу": "region:iberia:estremadura_ribatejo",
    "Алентежу": "region:iberia:alentejo",
    "Алгарве": "region:iberia:algarve",
}

# Workbook examples. These are not independent invented tuning values: they
# are copied from the uploaded sheet "Провинции — шаблон". London already has
# region.min=4, but keeping the anchor here preserves the workbook semantics.
WORKBOOK_ANCHOR_MIN_BY_NAME = {
    "La Coruña": 1,
    "Большой Лондон": 4,
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value), encoding="utf-8")


def slugify(value: str) -> str:
    table = str.maketrans({
        "А":"a","Б":"b","В":"v","Г":"g","Д":"d","Е":"e","Ё":"e","Ж":"zh","З":"z","И":"i","Й":"y",
        "К":"k","Л":"l","М":"m","Н":"n","О":"o","П":"p","Р":"r","С":"s","Т":"t","У":"u","Ф":"f",
        "Х":"h","Ц":"c","Ч":"ch","Ш":"sh","Щ":"sch","Ы":"y","Э":"e","Ю":"yu","Я":"ya","Ь":"","Ъ":"",
        "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z","и":"i","й":"y",
        "к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f",
        "х":"h","ц":"c","ч":"ch","ш":"sh","щ":"sch","ы":"y","э":"e","ю":"yu","я":"ya","ь":"","ъ":"",
    })
    text = unicodedata.normalize("NFKD", value).translate(table).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "region"


def round_half_up(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def polygon_parts(geometry: Any) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, (MultiPolygon, GeometryCollection)) or hasattr(geometry, "geoms"):
        return [g for g in geometry.geoms if isinstance(g, Polygon) and not g.is_empty]
    return []


def geometry_from_entry(entry: dict[str, Any]) -> Any:
    rings = entry.get("rings", [])
    if not rings:
        return Polygon()
    geometry = Polygon(rings[0], rings[1:])
    if not geometry.is_valid:
        geometry = geometry.buffer(0)
    return geometry


def km_per_world_px(y: float) -> float:
    mercator_n = math.pi - 2.0 * math.pi * y / WORLD_PX
    latitude = math.degrees(math.atan(math.sinh(mercator_n)))
    return 2.0 * math.pi * EARTH_RADIUS_KM / WORLD_PX * math.cos(math.radians(latitude))


def area_km2(geometry: Any) -> float:
    if geometry.is_empty:
        return 0.0
    scale = km_per_world_px(float(geometry.representative_point().y))
    return float(geometry.area) * scale * scale


def load_profile_source() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    profiles: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    for raw in PROFILE_SOURCE_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("|")
        if len(fields) != 10:
            raise RuntimeError(f"bad profile source row: {raw!r}")
        name, macroregion, continent, profile_id, target, minimum, maximum, historical, geographic, scope = fields
        region_id = IBERIA_IDS.get(name) if scope == "iberia" else f"region:world:{slugify(name)}"
        if not region_id:
            raise RuntimeError(f"missing Iberia region id for {name}")
        item = {
            "region_id": region_id,
            "name": name,
            "macroregion_name": macroregion,
            "continent": continent,
            "profile_id": profile_id,
            "target_cell_area_km2": float(target) if "." in target else int(target),
            "min_cells_per_province": int(minimum),
            "max_cells_per_province": int(maximum),
            "historical_density_index": float(historical),
            "geographic_complexity_index": float(geographic),
            "scope": scope,
        }
        if name in by_name:
            raise RuntimeError(f"duplicate profile name: {name}")
        by_name[name] = item
        profiles.append(item)
    world_count = sum(1 for p in profiles if p["scope"] == "world")
    iberia_count = sum(1 for p in profiles if p["scope"] == "iberia")
    if world_count != EXPECTED_WORLD_PROFILES or iberia_count != EXPECTED_IBERIA_PROFILES:
        raise RuntimeError(f"profile source count mismatch: world={world_count}, iberia={iberia_count}")
    return profiles, by_name


def load_geometry() -> dict[str, Any]:
    document = read_json(GEOMETRY_PATH)
    result: dict[str, Any] = {}
    for entry in document.get("provinces", []):
        pid = str(entry.get("id", ""))
        geometry = geometry_from_entry(entry)
        if pid and not geometry.is_empty:
            result[pid] = geometry
    return result


def sample_for(records: list[dict[str, Any]], *, name: str | None = None, legacy_contains: str | None = None) -> dict[str, Any] | None:
    for item in records:
        if name is not None and str(item.get("name", "")) == name:
            return item
        if legacy_contains is not None and legacy_contains in str(item.get("legacy_id", "")):
            return item
    return None


def build_documents() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    profiles, profiles_by_name = load_profile_source()
    base_profiles = read_json(BASE_PROFILES_PATH).get("profiles", {})
    neutral = dict(base_profiles.get("P3", {}))
    if not neutral:
        raise RuntimeError("P3 fallback profile is missing")

    identities = {str(p["id"]): p for p in read_json(IDENTITY_PATH).get("provinces", [])}
    assignments_doc = read_json(ASSIGNMENTS_PATH)
    assignments = assignments_doc.get("assignments", [])
    assignment_by_id = {str(a.get("province_id", "")): a for a in assignments}
    geometries = load_geometry()

    overrides = {str(o["province_id"]): o for o in read_json(OVERRIDES_PATH).get("overrides", [])}

    if len(identities) != EXPECTED_PROVINCES:
        raise RuntimeError(f"expected {EXPECTED_PROVINCES} identities, got {len(identities)}")
    if len(assignment_by_id) != EXPECTED_PROVINCES:
        raise RuntimeError(f"expected {EXPECTED_PROVINCES} region assignments, got {len(assignment_by_id)}")
    if len(geometries) != EXPECTED_PROVINCES:
        raise RuntimeError(f"expected {EXPECTED_PROVINCES} province geometries, got {len(geometries)}")

    output: list[dict[str, Any]] = []
    special_fallback_regions: Counter[str] = Counter()
    profile_counts: Counter[str] = Counter()
    count_distribution: Counter[int] = Counter()
    min_clamps = 0
    max_clamps = 0
    forced_count_count = 0
    override_min_count = 0

    for province_id in sorted(identities, key=lambda p: int(p.split(":")[-1])):
        identity = identities[province_id]
        assignment = assignment_by_id[province_id]
        geometry = geometries[province_id]
        province_area = area_km2(geometry)
        if province_area <= 0.0:
            raise RuntimeError(f"non-positive area for {province_id}")

        region_name = str(assignment.get("region_name", ""))
        profile = profiles_by_name.get(region_name)
        profile_source = "regional_workbook"
        if profile is None:
            special_fallback_regions[region_name or "<empty>"] += 1
            profile = {
                "region_id": str(assignment.get("region_id", "")),
                "name": region_name or "UNPROFILED_SPECIAL_REGION",
                "macroregion_name": "",
                "continent": "",
                "profile_id": "P3",
                "target_cell_area_km2": float(neutral["target_cell_area_km2"]),
                "min_cells_per_province": int(neutral["min_cells_per_province"]),
                "max_cells_per_province": int(neutral["max_cells_per_province"]),
                "historical_density_index": None,
                "geographic_complexity_index": None,
                "scope": "explicit_special_fallback",
            }
            profile_source = "P3_fallback_region_not_in_workbook"

        # Neutral local factors are intentional, not missing math. See module docstring.
        coast_factor = 1.0
        relief_factor = 1.0
        shape_factor = 1.0
        complexity = coast_factor * relief_factor * shape_factor
        target_area = float(profile["target_cell_area_km2"])
        raw_area_count = (province_area / target_area) * complexity
        area_count = max(1, round_half_up(raw_area_count))
        minimum = int(profile["min_cells_per_province"])
        maximum = int(profile["max_cells_per_province"])
        anchor_min = int(WORKBOOK_ANCHOR_MIN_BY_NAME.get(str(identity.get("name", "")), 1))

        override = overrides.get(province_id)
        override_reason = ""
        if override is not None:
            override_reason = str(override.get("reason", ""))
            minimum_override = override.get("minimum_cell_count")
            if minimum_override is not None:
                anchor_min = max(anchor_min, int(minimum_override))
                override_min_count += 1

        pre_clamp = max(area_count, anchor_min)
        if pre_clamp < minimum:
            min_clamps += 1
        if pre_clamp > maximum:
            max_clamps += 1
        final_count = max(minimum, min(maximum, pre_clamp))

        if override is not None and override.get("forced_cell_count") is not None:
            final_count = int(override["forced_cell_count"])
            forced_count_count += 1

        if final_count < 1:
            raise RuntimeError(f"invalid final count for {province_id}: {final_count}")

        profile_counts[str(profile["profile_id"])] += 1
        count_distribution[final_count] += 1
        legacy_id = str(identity.get("legacy_id", ""))
        country_prefix = legacy_id.split("__", 1)[0] if "__" in legacy_id else ""
        output.append({
            "province_id": province_id,
            "legacy_id": legacy_id,
            "name": str(identity.get("name") or identity.get("slug") or province_id),
            "country_prefix": country_prefix,
            "region_id": str(assignment.get("region_id", profile.get("region_id", ""))),
            "region_name": region_name,
            "region_assignment_method": str(assignment.get("method", "")),
            "region_assignment_review": bool(assignment.get("review", False)),
            "area_km2": round(province_area, 3),
            "profile_id": str(profile["profile_id"]),
            "profile_source": profile_source,
            "region_target_cell_area_km2": target_area,
            "region_min_cells": minimum,
            "region_max_cells": maximum,
            "historical_density_index": profile.get("historical_density_index"),
            "geographic_complexity_index": profile.get("geographic_complexity_index"),
            "coast_factor": coast_factor,
            "relief_factor": relief_factor,
            "shape_factor": shape_factor,
            "complexity": complexity,
            "raw_area_count": round(raw_area_count, 6),
            "area_count": area_count,
            "anchor_min": anchor_min,
            "target_cell_count": final_count,
            "override_reason": override_reason,
        })

    profile_catalog = {
        "schema_version": 1,
        "format": "world_region_cell_profiles/v1",
        "content_version": "2026.08.21",
        "source_workbook": "ТАБЛИЦА_РЕГИОНАЛЬНЫХ_ПРОФИЛЕЙ_КЛЕТОК(1).xlsx",
        "source_sheets": ["Мировые регионы v1", "Иберия", "Формула", "Коэффициенты", "Классы плотности"],
        "world_profile_count": EXPECTED_WORLD_PROFILES,
        "iberia_profile_count": EXPECTED_IBERIA_PROFILES,
        "profile_count": len(profiles),
        "formula": {
            "area_count": "ROUND((province_area_km2 / target_cell_area_km2) * complexity)",
            "complexity": "coast_factor * relief_factor * shape_factor",
            "final_count": "CLAMP(MAX(area_count, anchor_min), region.min, region.max)",
            "rounding": "half_up",
        },
        "pre_cell_policy": {
            "relief_factor": 1.0,
            "relief_reason": "Terrain/relief is generated after cells and cannot affect this stage.",
            "coast_factor_default": 1.0,
            "shape_factor_default": 1.0,
            "local_factor_reason": "Workbook gives coefficient classes but no authoritative automatic classifier thresholds; no classes are guessed.",
        },
        "profiles": profiles,
    }

    total_target_cells = sum(int(x["target_cell_count"]) for x in output)
    review_count = sum(1 for x in output if x["region_assignment_review"])
    fallback_province_count = sum(special_fallback_regions.values())
    biggest = sorted(output, key=lambda x: (-int(x["target_cell_count"]), -float(x["area_km2"]), x["province_id"]))[:30]

    sample_names = [
        ("Большой Лондон", None),
        ("La Coruña", None),
        ("Andorra la Vella", None),
        (None, "palermo"),
        (None, "c_tes_d_armor"),
        ("Kalmar", None),
        ("Vologda", None),
    ]
    samples = []
    for name, legacy in sample_names:
        item = sample_for(output, name=name, legacy_contains=legacy)
        if item is not None:
            samples.append({k: item[k] for k in (
                "province_id", "legacy_id", "name", "region_name", "profile_id", "area_km2",
                "region_target_cell_area_km2", "area_count", "anchor_min", "target_cell_count",
                "profile_source", "region_assignment_review")})

    report = {
        "schema_version": 1,
        "format": "world_province_cell_targets_report/v1",
        "province_count": len(output),
        "unique_province_count": len({x["province_id"] for x in output}),
        "table_profile_count": len(profiles),
        "world_table_profile_count": EXPECTED_WORLD_PROFILES,
        "iberia_table_profile_count": EXPECTED_IBERIA_PROFILES,
        "profiled_from_workbook_province_count": len(output) - fallback_province_count,
        "special_fallback_province_count": fallback_province_count,
        "special_fallback_regions": dict(sorted(special_fallback_regions.items())),
        "region_assignment_review_count": review_count,
        "total_target_cells": total_target_cells,
        "count_distribution": {str(k): count_distribution[k] for k in sorted(count_distribution)},
        "province_count_by_profile": {k: profile_counts[k] for k in sorted(profile_counts)},
        "min_clamp_count": min_clamps,
        "max_clamp_count": max_clamps,
        "override_minimum_count": override_min_count,
        "forced_count_count": forced_count_count,
        "local_factor_policy": {
            "coast_factor": "1.0 until an authoritative per-province classifier/override exists",
            "relief_factor": "1.0 locked by project architecture",
            "shape_factor": "1.0 until an authoritative classifier threshold is approved",
        },
        "largest_target_counts": [{
            "province_id": x["province_id"], "legacy_id": x["legacy_id"], "name": x["name"],
            "region_name": x["region_name"], "profile_id": x["profile_id"], "area_km2": x["area_km2"],
            "target_cell_count": x["target_cell_count"]
        } for x in biggest],
        "control_samples": samples,
        "hard_fail": False,
    }

    targets = {
        "schema_version": 1,
        "format": "world_province_cell_targets/v1",
        "content_version": "2026.08.21",
        "province_count": len(output),
        "total_target_cells": total_target_cells,
        "formula_source": "uploaded regional profile workbook / Формула",
        "geometry_source": "assets/map_geometry/provinces.json",
        "region_assignment_source": "assets/game_data/world_region_assignments_draft.json",
        "region_profile_source": "assets/game_data/world_region_cell_profiles.json",
        "local_factor_policy": report["local_factor_policy"],
        "provinces": output,
    }
    return profile_catalog, targets, report


def check_or_write(path: Path, document: Any, check: bool) -> None:
    text = canonical_json(document)
    if check:
        if not path.exists():
            raise RuntimeError(f"--check missing output: {path}")
        existing = path.read_text(encoding="utf-8")
        if existing != text:
            expected_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
            actual_hash = hashlib.sha256(existing.encode("utf-8")).hexdigest()[:12]
            raise RuntimeError(f"--check mismatch {path}: expected={expected_hash} actual={actual_hash}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Verify deterministic outputs without modifying them")
    args = parser.parse_args()

    profile_catalog, targets, report = build_documents()
    check_or_write(PROFILE_JSON_PATH, profile_catalog, args.check)
    check_or_write(TARGETS_PATH, targets, args.check)
    check_or_write(REPORT_PATH, report, args.check)

    print("WORLD_CELL_TARGETS_PROVINCES=", report["province_count"])
    print("WORLD_CELL_TARGETS_TOTAL_CELLS=", report["total_target_cells"])
    print("WORLD_CELL_TARGETS_REVIEW=", report["region_assignment_review_count"])
    print("WORLD_CELL_TARGETS_FALLBACK_PROVINCES=", report["special_fallback_province_count"])
    print("WORLD_CELL_TARGETS_FALLBACK_REGIONS=", report["special_fallback_regions"])
    print("WORLD_CELL_TARGETS_PROFILE_COUNTS=", report["province_count_by_profile"])
    for item in report["control_samples"]:
        print("CONTROL", item["name"], "region=", item["region_name"], "profile=", item["profile_id"], "count=", item["target_cell_count"])


if __name__ == "__main__":
    main()
