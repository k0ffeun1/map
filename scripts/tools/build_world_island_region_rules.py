#!/usr/bin/env python3
"""Build/validate world island-region rules before final cell generation.

This stage formalizes the project rules agreed for islands:

1. Small standalone islands should normally become ONE gameplay cell.
2. A province/archipelago with several significant disconnected islands is
   allocated at least one cell per significant island; larger islands may get
   additional cells from the normal regional target-area formula.
3. Satellite islands inherit the region of their natural parent island/main
   territory instead of being assigned independently by nearest regional seed.
4. Remote North-Atlantic European islands form one explicit region with Iceland.
5. Near-shore Scottish islands remain with their appropriate Scottish region.

The script emits configuration/audit data only. It does not alter source Admin-1
geometry and does not generate gameplay-cell polygons.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

OUT_RULES = ROOT / "assets" / "game_data" / "world_island_region_rules.json"
OUT_REPORT = ROOT / "reports" / "world_island_region_rules.json"

# Explicit groups are intentionally semantic rather than proximity-only.
# Additional aliases can be added after the audit exposes source-layer names.
RULES = {
    "schema_version": 1,
    "format": "world_island_region_rules/v1",
    "content_version": "2026.08.21",
    "principles": {
        "small_island_default_cell_count": 1,
        "significant_disconnected_island_minimum_cells": 1,
        "cross_sea_cell_merge_forbidden": True,
        "satellite_island_inherits_parent_region": True,
        "terrain_or_relief_used": False,
    },
    "regions": [
        {
            "id": "region:world:north_atlantic_european_islands",
            "name": "Северо-Атлантические острова Европы",
            "profile_id": "P4",
            "target_cell_area_km2": 4500,
            "min_cells_per_province": 1,
            "max_cells_per_province": 12,
            "members_by_name": [
                "Iceland",
                "Faroe Islands",
            ],
            "notes": "Удалённые североатлантические европейские острова объединяются с Исландией; прибрежные острова Шотландии сюда не входят.",
        },
        {
            "id": "region:world:atlantic_european_islands",
            "name": "Атлантические острова Европы",
            "profile_id": "P3",
            "target_cell_area_km2": 1800,
            "min_cells_per_province": 1,
            "max_cells_per_province": 10,
            "members_by_region_name": [
                "Азорские острова",
                "Мадейра",
            ],
            "notes": "Азоры и Мадейра получают единый регион вместо временного P3 fallback. Канары можно добавить после проверки их текущей привязки в слое 8.",
        },
    ],
    "inheritance_rules": [
        {
            "name": "Scottish near-shore islands",
            "country_prefix": "united_kingdom",
            "policy": "inherit_nearest_same_country_main_region",
            "allowed_parent_region_names": ["Шотландская низменность", "Шотландское нагорье"],
            "notes": "Оркнейские, Шетландские, Гебридские и прочие прибрежные шотландские острова не выделяются в Северо-Атлантический регион автоматически.",
        },
        {
            "name": "Gotland satellites",
            "country_prefix": "sweden",
            "policy": "inherit_parent_admin1_region",
            "parent_name_contains": "Gotland",
            "notes": "Малые острова рядом с Готландом должны наследовать регион самого Готланда.",
        },
    ],
    "cell_allocation": {
        "small_island_area_threshold_km2": 1200,
        "significant_component_area_km2": 25,
        "significant_component_relative_area": 0.02,
        "algorithm": [
            "split province geometry into disconnected polygon components",
            "ignore tiny rocks below both absolute and relative significant thresholds",
            "allocate >=1 cell to each significant island",
            "if significant island area <= small_island_area_threshold_km2, keep exactly 1 cell unless explicit override",
            "allocate remaining cells to larger islands proportionally using regional target-area rule",
            "never create a gameplay cell spanning two significant islands across sea",
        ],
    },
}


def main() -> None:
    OUT_RULES.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_RULES.write_text(json.dumps(RULES, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "schema_version": 1,
        "format": "world_island_region_rules_report/v1",
        "status": "RULES_DEFINED_AUDIT_REQUIRED",
        "rule_region_count": len(RULES["regions"]),
        "inheritance_rule_count": len(RULES["inheritance_rules"]),
        "small_island_area_threshold_km2": RULES["cell_allocation"]["small_island_area_threshold_km2"],
        "next": "Apply these rules to world_region_assignments_draft and world_province_cell_targets, then audit all multipart/island provinces.",
    }
    OUT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("WORLD_ISLAND_RULES_OK", "regions=", report["rule_region_count"], "inheritance=", report["inheritance_rule_count"])


if __name__ == "__main__":
    main()
