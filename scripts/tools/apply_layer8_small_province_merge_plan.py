#!/usr/bin/env python3
"""Apply the reviewed Layer-8 merge plan as logical gameplay province groups.

This intentionally does NOT rewrite polygon geometry. Layer-8 render records
remain stable; gameplay parents group one or more source-feature families and
one or more render polygons. This is required for islands and other disconnected
MultiPolygon territories where drawing an artificial land bridge would be wrong.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "assets" / "game_data" / "layer8_small_province_merge_plan.json"
OUT_GROUPS = ROOT / "assets" / "game_data" / "layer8_normalized_province_groups.json"
OUT_JSON = ROOT / "reports" / "layer8_normalized_province_groups.json"
OUT_MD = ROOT / "reports" / "layer8_normalized_province_groups.md"

EXPECTED_RENDER_RECORDS = 4027
EXPECTED_SOURCE_FAMILIES = 2903


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    plan = read_json(PLAN_PATH)
    if plan.get("format") != "layer8_small_province_merge_plan/v2":
        raise RuntimeError(f"Unexpected merge plan format: {plan.get('format')}")

    actions = [dict(x) for x in plan.get("family_actions", [])]
    if len(actions) != EXPECTED_SOURCE_FAMILIES:
        raise RuntimeError(f"Expected {EXPECTED_SOURCE_FAMILIES} family actions, got {len(actions)}")

    action_by_family = {str(x["family_id"]): x for x in actions}
    if len(action_by_family) != len(actions):
        raise RuntimeError("Duplicate family_id in merge plan")

    direct_parent: dict[str, str] = {}
    for family_id, action in action_by_family.items():
        if str(action.get("status", "")).startswith("AUTO_MERGE"):
            target = str(action.get("target_family_id", ""))
            if not target or target not in action_by_family:
                raise RuntimeError(f"Missing merge target for {family_id}: {target}")
            direct_parent[family_id] = target
        else:
            direct_parent[family_id] = family_id

    resolved_cache: dict[str, tuple[str, int]] = {}

    def resolve(family_id: str) -> tuple[str, int]:
        if family_id in resolved_cache:
            return resolved_cache[family_id]
        seen: set[str] = set()
        current = family_id
        depth = 0
        while direct_parent[current] != current:
            if current in seen:
                chain = " -> ".join(list(seen) + [current])
                raise RuntimeError(f"Merge cycle detected: {chain}")
            seen.add(current)
            current = direct_parent[current]
            depth += 1
            if depth > len(actions):
                raise RuntimeError(f"Merge chain overflow from {family_id}")
        resolved_cache[family_id] = (current, depth)
        return current, depth

    members_by_root: dict[str, list[str]] = defaultdict(list)
    for family_id in sorted(action_by_family):
        root, _ = resolve(family_id)
        members_by_root[root].append(family_id)

    groups: list[dict[str, Any]] = []
    render_to_parent: dict[str, str] = {}
    family_to_parent: dict[str, str] = {}
    render_seen: set[str] = set()

    for root_family_id in sorted(members_by_root):
        member_family_ids = sorted(members_by_root[root_family_id])
        root_action = action_by_family[root_family_id]
        parent_id = "gameplay:" + root_family_id.removeprefix("family:")
        render_ids: list[str] = []
        source_names: list[str] = []
        source_country_prefixes: set[str] = set()
        source_region_names: set[str] = set()
        protected_group_ids: set[str] = set()
        total_area = 0.0
        max_depth = 0
        merge_lineage: list[dict[str, Any]] = []

        for family_id in member_family_ids:
            action = action_by_family[family_id]
            _, depth = resolve(family_id)
            max_depth = max(max_depth, depth)
            ids = [str(x) for x in action.get("member_ids", [])]
            render_ids.extend(ids)
            source_names.append(str(action.get("name", "")))
            source_country_prefixes.add(str(action.get("country_prefix", "")))
            source_region_names.add(str(action.get("region_name", "")))
            total_area += float(action.get("area_km2", 0.0))
            if action.get("status") == "PROTECTED_HISTORICAL_ISLAND":
                protected_group_ids.add(str(action.get("reason", "")))
            if family_id != root_family_id:
                merge_lineage.append({
                    "family_id": family_id,
                    "name": action.get("name", ""),
                    "status": action.get("status", ""),
                    "direct_target_family_id": action.get("target_family_id", ""),
                    "resolved_root_family_id": root_family_id,
                    "cross_country": bool(action.get("cross_country", False)),
                })
            family_to_parent[family_id] = parent_id

        render_ids = sorted(set(render_ids))
        for render_id in render_ids:
            if render_id in render_seen:
                raise RuntimeError(f"Render province assigned to more than one gameplay parent: {render_id}")
            render_seen.add(render_id)
            render_to_parent[render_id] = parent_id

        groups.append({
            "gameplay_parent_id": parent_id,
            "root_family_id": root_family_id,
            "root_province_id": root_action.get("anchor_province_id", ""),
            "display_name": root_action.get("name", ""),
            "root_country_prefix": root_action.get("country_prefix", ""),
            "root_region_id": root_action.get("region_id", ""),
            "root_region_name": root_action.get("region_name", ""),
            "area_km2": round(total_area, 6),
            "member_family_ids": member_family_ids,
            "member_family_count": len(member_family_ids),
            "render_province_ids": render_ids,
            "render_province_count": len(render_ids),
            "source_names": sorted(set(source_names)),
            "source_country_prefixes": sorted(x for x in source_country_prefixes if x),
            "source_region_names": sorted(x for x in source_region_names if x),
            "protected_group_ids": sorted(x for x in protected_group_ids if x),
            "is_user_locked": root_action.get("status") == "LOCKED_APPROVED",
            "max_merge_depth": max_depth,
            "merge_lineage": merge_lineage,
        })

    auto_merge_count = sum(1 for x in actions if str(x.get("status", "")).startswith("AUTO_MERGE"))
    expected_group_count = len(actions) - auto_merge_count
    cross_country_groups = sum(1 for g in groups if len(g["source_country_prefixes"]) > 1)
    merged_groups = [g for g in groups if g["member_family_count"] > 1]
    protected_groups = [g for g in groups if g["protected_group_ids"]]
    locked_groups = [g for g in groups if g["is_user_locked"]]

    slovenia_render_ids = {
        rid
        for action in actions if action.get("country_prefix") == "slovenia"
        for rid in action.get("member_ids", [])
    }
    slovenia_parent_ids = {render_to_parent[rid] for rid in slovenia_render_ids}
    london_actions = [x for x in actions if x.get("reason") == "user_locked_greater_london_layer8"]
    london_render_ids = {
        rid for action in london_actions for rid in action.get("member_ids", [])
    }
    london_parent_ids = {render_to_parent[rid] for rid in london_render_ids}

    protected_source_absorbed = 0
    for action in actions:
        if action.get("status") == "PROTECTED_HISTORICAL_ISLAND":
            root, depth = resolve(str(action["family_id"]))
            if depth != 0 or root != action["family_id"]:
                protected_source_absorbed += 1

    validation = {
        "source_family_count": len(actions),
        "gameplay_parent_count": len(groups),
        "expected_gameplay_parent_count": expected_group_count,
        "render_record_coverage": len(render_seen),
        "render_record_coverage_ok": len(render_seen) == EXPECTED_RENDER_RECORDS,
        "family_coverage_ok": len(family_to_parent) == EXPECTED_SOURCE_FAMILIES,
        "group_count_ok": len(groups) == expected_group_count,
        "protected_source_absorbed_count": protected_source_absorbed,
        "slovenia_gameplay_parent_count": len(slovenia_parent_ids),
        "slovenia_unchanged": len(slovenia_parent_ids) == len([x for x in actions if x.get("country_prefix") == "slovenia"]),
        "greater_london_gameplay_parent_count": len(london_parent_ids),
        "greater_london_unchanged": len(london_parent_ids) == 1 and len(london_actions) == 1,
    }

    summary = {
        "render_record_count": EXPECTED_RENDER_RECORDS,
        "source_family_count": len(actions),
        "automatic_merge_source_count": auto_merge_count,
        "gameplay_parent_count": len(groups),
        "reduction_from_render_records": EXPECTED_RENDER_RECORDS - len(groups),
        "reduction_from_source_families": len(actions) - len(groups),
        "merged_gameplay_parent_count": len(merged_groups),
        "cross_country_gameplay_parent_count": cross_country_groups,
        "protected_gameplay_parent_count": len(protected_groups),
        "user_locked_gameplay_parent_count": len(locked_groups),
        "max_merge_depth": max((g["max_merge_depth"] for g in groups), default=0),
        "root_status_counts": dict(sorted(Counter(action_by_family[g["root_family_id"]].get("status", "") for g in groups).items())),
    }

    doc = {
        "schema_version": 1,
        "format": "layer8_normalized_province_groups/v1",
        "content_version": "2026.08.21",
        "source_merge_plan": str(PLAN_PATH.relative_to(ROOT)),
        "architecture": {
            "render_geometry_remains_4027_records": True,
            "gameplay_uses_logical_parent_groups": True,
            "disconnected_island_members_do_not_get_artificial_land_bridges": True,
            "internal_render_boundaries_should_be_suppressed_for_same_gameplay_parent": True,
        },
        "summary": summary,
        "validation": validation,
        "groups": groups,
        "family_to_gameplay_parent": family_to_parent,
        "render_to_gameplay_parent": render_to_parent,
    }
    write_json(OUT_GROUPS, doc)
    write_json(OUT_JSON, doc)

    lines = [
        "# Layer 8 — нормализованные gameplay-провинции",
        "",
        "> Merge-план применён **логически**. Исходные 4027 полигонов не уничтожаются: они становятся render-pieces gameplay-провинций.",
        "",
        "## Сводка",
        "",
        f"- Render records: **{summary['render_record_count']}**",
        f"- Source-feature family после восстановления multipart: **{summary['source_family_count']}**",
        f"- Применённых small merge: **{summary['automatic_merge_source_count']}**",
        f"- Итоговых gameplay-провинций: **{summary['gameplay_parent_count']}**",
        f"- Снижение относительно 4027 render records: **{summary['reduction_from_render_records']}**",
        f"- Снижение относительно 2903 source-family: **{summary['reduction_from_source_families']}**",
        f"- Gameplay-провинций, состоящих из нескольких family: **{summary['merged_gameplay_parent_count']}**",
        f"- Gameplay-провинций с источниками из нескольких современных стран: **{summary['cross_country_gameplay_parent_count']}**",
        f"- Защищённых островных gameplay-провинций: **{summary['protected_gameplay_parent_count']}**",
        "",
        "## Проверки",
        "",
        f"- Покрытие всех 4027 render records: **{validation['render_record_coverage_ok']}**",
        f"- Покрытие всех 2903 family: **{validation['family_coverage_ok']}**",
        f"- Поглощённых protected-source: **{validation['protected_source_absorbed_count']}**",
        f"- Словения без изменения gameplay-parent структуры: **{validation['slovenia_unchanged']}**",
        f"- Большой Лондон без изменения: **{validation['greater_london_unchanged']}**",
        "",
        "## Изменённые gameplay-провинции",
        "",
    ]
    for group in merged_groups:
        lines.append(
            f"- **{group['display_name']}** — {group['area_km2']:.1f} км²; "
            f"family: {group['member_family_count']}; render-pieces: {group['render_province_count']}; "
            f"источники: {', '.join(group['source_names'])}"
        )
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({"summary": summary, "validation": validation}, ensure_ascii=False, indent=2))

    failures = []
    if not validation["render_record_coverage_ok"]:
        failures.append("render coverage is not 4027")
    if not validation["family_coverage_ok"]:
        failures.append("family coverage is not 2903")
    if not validation["group_count_ok"]:
        failures.append("unexpected gameplay parent count")
    if validation["protected_source_absorbed_count"]:
        failures.append("protected historical island source was absorbed")
    if not validation["slovenia_unchanged"]:
        failures.append("Slovenia changed")
    if not validation["greater_london_unchanged"]:
        failures.append("Greater London changed")
    if args.check and failures:
        raise SystemExit("; ".join(failures))


if __name__ == "__main__":
    main()
