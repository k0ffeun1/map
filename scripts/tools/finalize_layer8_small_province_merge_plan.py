#!/usr/bin/env python3
"""Finalize the Layer-8 small-province merge plan under hard gameplay rules.

This pass is intentionally conservative and runs after geometric refinement:
- never merge across country/territory prefixes;
- never absorb protected historical-island sources;
- never target protected render-piece split groups such as the eight Canaries;
- isolated sea merges are allowed only inside the same country/territory and
  only up to the configured maximum distance (300 km by current policy);
- a small province with no safe target remains an independent gameplay parent.

The script rewrites the plan asset/report in place so the application step and
Godot debug viewer consume the same final decisions.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PLAN_ASSET = ROOT / "assets" / "game_data" / "layer8_small_province_merge_plan.json"
PLAN_REPORT = ROOT / "reports" / "layer8_small_province_merge_plan.json"
PLAN_MD = ROOT / "reports" / "layer8_small_province_merge_plan.md"
ISLAND_RULES = ROOT / "assets" / "game_data" / "world_island_region_rules.json"

AUTO_PREFIX = "AUTO_MERGE"
TARGET_KEYS = (
    "target_family_id",
    "target_family_key",
    "target_province_id",
    "target_name",
    "target_country_prefix",
    "target_region_name",
    "cross_country",
    "score",
    "score_parts",
    "distance_units",
    "distance_km",
    "selection_tier",
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def protected_render_split_ids(rules: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    protection = rules.get("historical_province_protection", {})
    for group in protection.get("protected_groups", []):
        if bool(group.get("preserve_current_layer8_render_pieces_as_gameplay_provinces", False)):
            result.add(str(group.get("id", "")))
    return result


def convert_to_keep(action: dict[str, Any], reason: str) -> None:
    rejected = {
        "status": action.get("status", ""),
        "target_family_id": action.get("target_family_id", ""),
        "target_name": action.get("target_name", ""),
        "target_country_prefix": action.get("target_country_prefix", ""),
        "distance_km": action.get("distance_km"),
        "reason": reason,
    }
    action["status"] = "KEEP_ISOLATED_SMALL"
    action["reason"] = reason
    action["rejected_merge"] = rejected
    for key in TARGET_KEYS:
        action.pop(key, None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    plan = read_json(PLAN_ASSET)
    if plan.get("format") != "layer8_small_province_merge_plan/v2":
        raise RuntimeError(f"Unexpected plan format: {plan.get('format')}")

    rules = read_json(ISLAND_RULES)
    protection = rules.get("historical_province_protection", {})
    max_distance_km = float(protection.get("max_same_country_isolated_merge_distance_km", 300.0))
    split_protected_ids = protected_render_split_ids(rules)

    actions = [dict(x) for x in plan.get("family_actions", [])]
    if len(actions) != 2903:
        raise RuntimeError(f"Expected 2903 logical families, got {len(actions)}")
    by_family = {str(x.get("family_id", "")): x for x in actions}
    if len(by_family) != len(actions):
        raise RuntimeError("Duplicate family_id in merge plan")

    converted_cross_country = 0
    converted_over_distance = 0
    converted_split_target = 0

    for action in actions:
        status = str(action.get("status", ""))
        if not status.startswith(AUTO_PREFIX):
            continue
        target_id = str(action.get("target_family_id", ""))
        target = by_family.get(target_id)
        if target is None:
            convert_to_keep(action, "final_no_target_family")
            continue

        source_country = str(action.get("country_prefix", ""))
        target_country = str(target.get("country_prefix", ""))
        if source_country != target_country:
            converted_cross_country += 1
            convert_to_keep(action, "final_cross_country_merge_forbidden")
            continue

        target_protected_id = str(target.get("reason", "")) if target.get("status") == "PROTECTED_HISTORICAL_ISLAND" else ""
        if target_protected_id in split_protected_ids:
            converted_split_target += 1
            convert_to_keep(action, "final_protected_render_split_target_forbidden")
            continue

        if status in {"AUTO_MERGE_NEAREST", "AUTO_MERGE_ARCHIPELAGO"}:
            distance = action.get("distance_km")
            if distance is None:
                convert_to_keep(action, "final_missing_geographic_distance")
                continue
            if float(distance) > max_distance_km:
                converted_over_distance += 1
                convert_to_keep(action, "final_same_country_target_beyond_max_distance")
                continue

    direct_parent: dict[str, str] = {}
    for action in actions:
        family_id = str(action["family_id"])
        if str(action.get("status", "")).startswith(AUTO_PREFIX):
            target_id = str(action.get("target_family_id", ""))
            if target_id not in by_family:
                raise RuntimeError(f"Final merge target missing: {family_id} -> {target_id}")
            direct_parent[family_id] = target_id
        else:
            direct_parent[family_id] = family_id

    cycle_count = 0
    max_depth = 0
    for start in direct_parent:
        seen: set[str] = set()
        current = start
        depth = 0
        while direct_parent[current] != current:
            if current in seen:
                cycle_count += 1
                break
            seen.add(current)
            current = direct_parent[current]
            depth += 1
            max_depth = max(max_depth, depth)
            if depth > len(actions):
                cycle_count += 1
                break

    final_auto = [a for a in actions if str(a.get("status", "")).startswith(AUTO_PREFIX)]
    isolated_keeps = [a for a in actions if a.get("status") == "KEEP_ISOLATED_SMALL"]
    protected = [a for a in actions if a.get("status") == "PROTECTED_HISTORICAL_ISLAND"]
    cross_country_final = 0
    over_distance_final = 0
    protected_source_merge = 0
    split_target_final = 0

    for action in final_auto:
        target = by_family[str(action["target_family_id"])]
        if str(action.get("country_prefix", "")) != str(target.get("country_prefix", "")):
            cross_country_final += 1
        if str(action.get("status", "")) in {"AUTO_MERGE_NEAREST", "AUTO_MERGE_ARCHIPELAGO"}:
            if float(action.get("distance_km", 0.0)) > max_distance_km:
                over_distance_final += 1
        target_protected_id = str(target.get("reason", "")) if target.get("status") == "PROTECTED_HISTORICAL_ISLAND" else ""
        if target_protected_id in split_protected_ids:
            split_target_final += 1

    for action in actions:
        if action.get("status") == "PROTECTED_HISTORICAL_ISLAND" and str(action.get("status", "")).startswith(AUTO_PREFIX):
            protected_source_merge += 1

    plan["family_actions"] = actions
    plan.setdefault("policy", {})["cross_country_province_merge_forbidden"] = True
    plan["policy"]["max_same_country_isolated_merge_distance_km"] = max_distance_km
    plan["policy"]["small_without_safe_target_remains_independent"] = True
    plan["summary"]["automatic_merge_count"] = len(final_auto)
    plan["summary"]["cross_country_automatic_merge_count"] = cross_country_final
    plan["summary"]["isolated_small_keep_count"] = len(isolated_keeps)
    plan["summary"]["finalizer_rejected_cross_country_count"] = converted_cross_country
    plan["summary"]["finalizer_rejected_over_distance_count"] = converted_over_distance
    plan["summary"]["finalizer_rejected_protected_split_target_count"] = converted_split_target
    plan["summary"]["family_status_counts"] = dict(sorted(Counter(str(a.get("status", "")) for a in actions).items()))
    plan["validations"]["cross_country_auto_merge_count"] = cross_country_final
    plan["validations"]["final_cross_country_auto_merge_count"] = cross_country_final
    plan["validations"]["final_over_distance_auto_merge_count"] = over_distance_final
    plan["validations"]["final_protected_render_split_target_count"] = split_target_final
    plan["validations"]["final_merge_cycle_count"] = cycle_count
    plan["validations"]["final_max_merge_depth"] = max_depth
    plan["validations"]["final_protected_source_merge_count"] = protected_source_merge
    plan["finalization"] = {
        "max_same_country_isolated_merge_distance_km": max_distance_km,
        "rejected_cross_country_count": converted_cross_country,
        "rejected_over_distance_count": converted_over_distance,
        "rejected_protected_render_split_target_count": converted_split_target,
        "isolated_small_keep_count": len(isolated_keeps),
    }

    write_json(PLAN_ASSET, plan)
    write_json(PLAN_REPORT, plan)

    protected_counts = Counter(str(a.get("reason", "")) for a in protected)
    lines = [
        "# Layer 8 — финальный план объединения маленьких провинций",
        "",
        "> Государственные/территориальные границы жёсткие. Защищённые острова не поглощаются. Изолированная мелкая провинция без безопасного соседа остаётся самостоятельной.",
        "",
        "## Сводка",
        "",
        f"- Layer 8 render records: **{plan['summary']['layer8_record_count']}**",
        f"- Логических source-family: **{plan['summary']['logical_family_count']}**",
        f"- Настоящих logical family <500 км²: **{plan['summary']['logical_family_under_500_count']}**",
        f"- Финальных автоматических merge: **{len(final_auto)}**",
        f"- Маленьких family, оставленных самостоятельными: **{len(isolated_keeps)}**",
        f"- Защищённых исторических островных family: **{len(protected)}**",
        f"- Отброшено cross-country предложений: **{converted_cross_country}**",
        f"- Отброшено слишком дальних островных предложений >{max_distance_km:.0f} км: **{converted_over_distance}**",
        "",
        "## Проверки",
        "",
        f"- Cross-country merge после финализации: **{cross_country_final}**",
        f"- Sea/nearest merge дальше лимита: **{over_distance_final}**",
        f"- Merge в protected render-split target: **{split_target_final}**",
        f"- Merge-циклы: **{cycle_count}**",
        "",
        "## Защищённые островные группы",
        "",
    ]
    for key, count in sorted(protected_counts.items()):
        lines.append(f"- `{key}`: **{count}** logical family")

    lines.extend(["", "## Финальные автоматические merge", ""])
    if not final_auto:
        lines.append("- Нет.")
    for action in final_auto:
        distance = f", {float(action['distance_km']):.1f} км" if action.get("distance_km") is not None else ""
        lines.append(
            f"- **{action.get('name', '?')}** ({float(action.get('area_km2', 0.0)):.1f} км²) → "
            f"**{action.get('target_name', '?')}**{distance} — `{action.get('status', '')}`"
        )

    lines.extend(["", "## Маленькие, оставленные самостоятельными", ""])
    if not isolated_keeps:
        lines.append("- Нет.")
    for action in isolated_keeps:
        rejected = action.get("rejected_merge", {})
        target_text = str(rejected.get("target_name", ""))
        detail = f"; отклонённая цель: {target_text}" if target_text else ""
        lines.append(
            f"- **{action.get('name', '?')}** ({float(action.get('area_km2', 0.0)):.1f} км²), "
            f"{action.get('country_prefix', '?')} — `{action.get('reason', '')}`{detail}"
        )
    PLAN_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = {
        "automatic_merge_count": len(final_auto),
        "isolated_small_keep_count": len(isolated_keeps),
        "cross_country_auto_merge_count": cross_country_final,
        "over_distance_auto_merge_count": over_distance_final,
        "protected_render_split_target_count": split_target_final,
        "cycle_count": cycle_count,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    failures: list[str] = []
    if cross_country_final:
        failures.append(f"cross-country merges: {cross_country_final}")
    if over_distance_final:
        failures.append(f"over-distance merges: {over_distance_final}")
    if split_target_final:
        failures.append(f"protected render-split targets: {split_target_final}")
    if cycle_count:
        failures.append(f"merge cycles: {cycle_count}")
    if protected_source_merge:
        failures.append(f"protected sources merged: {protected_source_merge}")
    if args.check and failures:
        raise SystemExit("; ".join(failures))


# Temporary CI trigger marker; no gameplay behavior.
if __name__ == "__main__":
    main()
