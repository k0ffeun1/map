#!/usr/bin/env python3
"""Build/validate world island-region rules before final cell generation.

Agreed project rules:
1. Small standalone island = one gameplay cell by default.
2. Separate significant islands never share one gameplay cell across sea.
3. Satellite islands inherit the region of their natural parent island/mainland.
4. European Atlantic remote islands use ONE common region (Iceland, Faroes,
   Azores, Madeira, Canaries and matching source aliases).
5. Near-shore Scottish islands stay in their Scottish region and are explicitly
   excluded from the common Atlantic-islands region.

This file defines semantics only. It does not invent a new density profile for
that region; profile/target values remain pending until explicitly chosen.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_RULES = ROOT / "assets" / "game_data" / "world_island_region_rules.json"
OUT_REPORT = ROOT / "reports" / "world_island_region_rules.json"

RULES = {
    "schema_version": 1,
    "format": "world_island_region_rules/v2",
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
            "id": "region:world:atlantic_european_islands",
            "name": "Атлантические острова Европы",
            "profile_status": "PENDING_USER_CHOICE",
            "members_by_name_or_alias": [
                "Iceland",
                "Faroe Islands",
                "Azores / Açores",
                "Madeira",
                "Canary Islands / Canarias",
            ],
            "explicit_exclusions": [
                "Orkney",
                "Shetland",
                "Hebrides",
                "other near-shore Scottish islands",
            ],
            "notes": "Один общий атлантический европейский островной регион. Шотландские прибрежные острова наследуют шотландский регион.",
        }
    ],
    "inheritance_rules": [
        {
            "name": "Scottish near-shore islands",
            "country_prefix": "united_kingdom",
            "policy": "inherit_scottish_parent_region",
            "allowed_parent_region_names": ["Шотландская низменность", "Шотландское нагорье"],
        },
        {
            "name": "Gotland satellites",
            "country_prefix": "sweden",
            "policy": "inherit_parent_admin1_region",
            "parent_name_contains": "Gotland",
        },
    ],
    "cell_allocation": {
        "small_island_definition": "component_area_km2 <= active_region_target_cell_area_km2",
        "small_island_cell_count": 1,
        "significant_component_policy": "at least one cell per significant disconnected island component",
        "tiny_rock_policy": "tiny components may attach logically to the nearest island cell; they do not force a standalone gameplay cell",
        "algorithm": [
            "split province geometry into disconnected polygon components",
            "separate significant islands from tiny rocks",
            "give each significant island at least one cell",
            "if island area <= active regional target area, keep one cell unless explicit override",
            "larger islands use the normal regional target-area formula",
            "never create one gameplay cell spanning two significant islands across sea",
        ],
    },
}


def main() -> None:
    OUT_RULES.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_RULES.write_text(json.dumps(RULES, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "schema_version": 1,
        "format": "world_island_region_rules_report/v2",
        "status": "RULES_DEFINED_PROFILE_PENDING",
        "rule_region_count": 1,
        "inheritance_rule_count": len(RULES["inheritance_rules"]),
        "profile_pending_region": "Атлантические острова Европы",
        "next": "Audit source-layer island names, apply region corrections, preserve existing profile values until the common island-region density profile is explicitly chosen.",
    }
    OUT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("WORLD_ISLAND_RULES_OK", "regions=1", "inheritance=", report["inheritance_rule_count"])


if __name__ == "__main__":
    main()
