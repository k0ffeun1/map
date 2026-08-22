#!/usr/bin/env python3
"""Build cell-count targets for normalized Layer-8 gameplay provinces.

The old target table is per 4027 render records. After logical reconstruction
and safe small-province merges, gameplay uses a smaller parent layer, so cell
counts must be recalculated from the parent area instead of summing render-piece
counts.

Rules:
- use the root province's approved regional cell profile;
- recompute area_count from normalized gameplay-parent area;
- preserve explicit anchor/override minima;
- never use terrain/relief at this stage;
- explicit significant-island groups may impose a component minimum;
- if a province >=20,000 km² would still receive only one cell, apply a small
  deterministic safety floor. This affects only one-cell outliers and does not
  flatten normal regional density differences.
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
GROUPS_PATH = ROOT / "assets" / "game_data" / "layer8_normalized_province_groups.json"
RENDER_TARGETS_PATH = ROOT / "assets" / "game_data" / "world_province_cell_targets.json"
ISLAND_RULES_PATH = ROOT / "assets" / "game_data" / "world_island_region_rules.json"
OUT_PATH = ROOT / "assets" / "game_data" / "layer8_normalized_cell_targets.json"
REPORT_JSON = ROOT / "reports" / "layer8_normalized_cell_targets.json"
REPORT_MD = ROOT / "reports" / "layer8_normalized_cell_targets.md"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def round_half_up(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def large_one_cell_floor(area_km2: float) -> int:
    """Safety floor only for provinces that would otherwise have one cell."""
    if area_km2 < 20_000.0:
        return 1
    if area_km2 < 40_000.0:
        return 2
    if area_km2 < 80_000.0:
        return 3
    if area_km2 < 120_000.0:
        return 4
    return 5


def explicit_component_minima() -> dict[str, int]:
    """Return protected-group minima only where the project explicitly lists islands."""
    rules = read_json(ISLAND_RULES_PATH)
    result: dict[str, int] = {}
    for raw in rules.get("historical_province_protection", {}).get("protected_groups", []):
        rule = dict(raw)
        group_id = str(rule.get("id", ""))
        families = rule.get("gameplay_province_families", [])
        if not group_id or not isinstance(families, list):
            continue
        # The minimum is applied per normalized gameplay parent by matching its
        # display/family name to one explicit family below.
        for family in families:
            if not isinstance(family, dict):
                continue
            name = str(family.get("name", ""))
            islands = family.get("islands", [])
            if name and isinstance(islands, list) and islands:
                result[f"{group_id}|{name}"] = len(islands)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    groups_doc = read_json(GROUPS_PATH)
    if groups_doc.get("format") != "layer8_normalized_province_groups/v2":
        raise RuntimeError(f"Unexpected groups format: {groups_doc.get('format')}")
    groups = [dict(x) for x in groups_doc.get("groups", [])]
    if len(groups) < 2800:
        raise RuntimeError(f"Unexpected normalized gameplay parent count: {len(groups)}")

    render_targets_doc = read_json(RENDER_TARGETS_PATH)
    render_targets = {
        str(x["province_id"]): dict(x) for x in render_targets_doc.get("provinces", [])
    }
    if len(render_targets) != 4027:
        raise RuntimeError(f"Expected 4027 render targets, got {len(render_targets)}")

    component_min_by_key = explicit_component_minima()
    rows: list[dict[str, Any]] = []
    safety_floor_applied = 0
    component_floor_applied = 0
    one_cell_before_safety = 0
    large_one_cell_before_safety = 0

    for group in sorted(groups, key=lambda x: str(x.get("gameplay_parent_id", ""))):
        parent_id = str(group.get("gameplay_parent_id", ""))
        root_pid = str(group.get("root_province_id", ""))
        if not parent_id or root_pid not in render_targets:
            raise RuntimeError(f"Missing root target for {parent_id}: {root_pid}")
        root = render_targets[root_pid]
        area = float(group.get("area_km2", 0.0))
        target_area = float(root.get("region_target_cell_area_km2", 0.0))
        if area <= 0.0 or target_area <= 0.0:
            raise RuntimeError(f"Invalid area/target area for {parent_id}: {area}/{target_area}")

        minimum = int(root.get("region_min_cells", 1))
        maximum = int(root.get("region_max_cells", max(minimum, 1)))
        raw_area_count = area / target_area
        area_count = max(1, round_half_up(raw_area_count))

        member_targets = [
            render_targets[str(pid)]
            for pid in group.get("render_province_ids", [])
            if str(pid) in render_targets
        ]
        anchor_min = max([int(x.get("anchor_min", 1)) for x in member_targets] or [1])
        explicit_override_min = max(
            [
                int(x.get("target_cell_count", 1))
                for x in member_targets
                if str(x.get("override_reason", "")).strip()
            ]
            or [1]
        )

        base_count = max(minimum, min(maximum, max(area_count, anchor_min, explicit_override_min)))
        if base_count == 1:
            one_cell_before_safety += 1
            if area >= 20_000.0:
                large_one_cell_before_safety += 1

        component_min = 1
        for protected_id in group.get("protected_group_ids", []):
            key = f"{protected_id}|{group.get('display_name', '')}"
            component_min = max(component_min, int(component_min_by_key.get(key, 1)))
        after_component = max(base_count, component_min)
        if after_component > base_count:
            component_floor_applied += 1

        safety_min = large_one_cell_floor(area) if after_component == 1 else 1
        final_count = max(after_component, safety_min)
        if final_count > after_component:
            safety_floor_applied += 1

        rows.append({
            "gameplay_parent_id": parent_id,
            "display_name": str(group.get("display_name", parent_id)),
            "country_prefix": str(group.get("root_country_prefix", "")),
            "region_id": str(group.get("root_region_id", root.get("region_id", ""))),
            "region_name": str(group.get("root_region_name", root.get("region_name", ""))),
            "area_km2": round(area, 3),
            "root_render_province_id": root_pid,
            "root_profile_id": str(root.get("profile_id", "")),
            "region_target_cell_area_km2": target_area,
            "region_min_cells": minimum,
            "region_max_cells": maximum,
            "raw_area_count": round(raw_area_count, 6),
            "area_count": area_count,
            "anchor_min": anchor_min,
            "explicit_override_min": explicit_override_min,
            "explicit_significant_island_min": component_min,
            "large_one_cell_safety_min": safety_min,
            "base_target_cell_count": base_count,
            "target_cell_count": final_count,
            "render_province_count": int(group.get("render_province_count", 0)),
            "member_family_count": int(group.get("member_family_count", 0)),
            "protected_group_ids": list(group.get("protected_group_ids", [])),
        })

    one_cell_after = [x for x in rows if int(x["target_cell_count"]) == 1]
    large_one_cell_after = [x for x in one_cell_after if float(x["area_km2"]) >= 20_000.0]
    total_cells = sum(int(x["target_cell_count"]) for x in rows)
    canaries = [x for x in rows if "protected:canary_islands" in x["protected_group_ids"]]

    summary = {
        "gameplay_parent_count": len(rows),
        "total_target_cells": total_cells,
        "one_cell_before_safety_count": one_cell_before_safety,
        "large_one_cell_before_safety_count": large_one_cell_before_safety,
        "large_one_cell_safety_floor_applied_count": safety_floor_applied,
        "explicit_component_floor_applied_count": component_floor_applied,
        "one_cell_after_count": len(one_cell_after),
        "large_one_cell_after_count": len(large_one_cell_after),
        "canary_gameplay_parent_count": len(canaries),
        "canary_target_cells": {
            str(x["display_name"]): int(x["target_cell_count"]) for x in canaries
        },
    }
    doc = {
        "schema_version": 1,
        "format": "layer8_normalized_cell_targets/v1",
        "content_version": "2026.08.22",
        "source_groups": str(GROUPS_PATH.relative_to(ROOT)),
        "source_render_targets": str(RENDER_TARGETS_PATH.relative_to(ROOT)),
        "policy": {
            "terrain_or_relief_used": False,
            "profile_selection": "root gameplay province regional profile",
            "render_piece_target_counts_are_not_summed": True,
            "large_one_cell_safety_floor": {
                "scope": "only when computed target would otherwise be exactly 1",
                "bands": [
                    {"area_km2": "20000-39999", "minimum_cells": 2},
                    {"area_km2": "40000-79999", "minimum_cells": 3},
                    {"area_km2": "80000-119999", "minimum_cells": 4},
                    {"area_km2": ">=120000", "minimum_cells": 5},
                ],
            },
            "explicit_significant_island_minimum": "only from explicit island lists in world_island_region_rules.json",
        },
        "summary": summary,
        "provinces": rows,
    }

    write_json(OUT_PATH, doc)
    write_json(REPORT_JSON, doc)
    lines = [
        "# Layer 8 — цели клеток нормализованных gameplay-провинций",
        "",
        "> Количество клеток пересчитано по площади логической gameplay-провинции. Target-значения технических render-pieces не суммируются.",
        "",
        "## Сводка",
        "",
        f"- Gameplay-провинций: **{len(rows)}**",
        f"- Всего целевых клеток: **{total_cells}**",
        f"- Одноклеточных до safety floor: **{one_cell_before_safety}**",
        f"- Огромных одноклеточных >=20 000 км² до safety floor: **{large_one_cell_before_safety}**",
        f"- Исправлено large-one-cell safety floor: **{safety_floor_applied}**",
        f"- Одноклеточных после policy: **{len(one_cell_after)}**",
        f"- Огромных одноклеточных >=20 000 км² после policy: **{len(large_one_cell_after)}**",
        f"- Канарских gameplay-провинций: **{len(canaries)}**",
        "",
        "## Канары",
        "",
    ]
    for item in sorted(canaries, key=lambda x: str(x["display_name"])):
        lines.append(
            f"- **{item['display_name']}** — {item['area_km2']:.1f} км² — **{item['target_cell_count']} клеток**"
        )
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.check:
        failures: list[str] = []
        if len(rows) != int(groups_doc.get("summary", {}).get("gameplay_parent_count", -1)):
            failures.append("normalized target coverage mismatch")
        if large_one_cell_after:
            failures.append(f"large one-cell provinces remain: {len(large_one_cell_after)}")
        if len(canaries) != 2:
            failures.append(f"expected 2 Canary gameplay parents, got {len(canaries)}")
        if failures:
            raise SystemExit("; ".join(failures))


if __name__ == "__main__":
    main()
