#!/usr/bin/env python3
"""Finalize Layer-8 small-province merges with geographic and sovereignty guards.

The base planner is intentionally permissive so every tiny logical family gets a
candidate. This pass turns that candidate list into a safe historical-strategy
plan:
- never merge across a current country/dependency prefix;
- preserve the Low Countries future-superregion boundary;
- preserve user-locked and protected historical islands;
- keep touching same-country merges;
- for isolated same-country territories, use real haversine distance;
- if no safe same-country target exists within the configured distance, keep the
  tiny province instead of deleting a sovereign/dependency territory.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from shapely.geometry import Polygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
PLAN_ASSET = ROOT / "assets" / "game_data" / "layer8_small_province_merge_plan.json"
PLAN_REPORT = ROOT / "reports" / "layer8_small_province_merge_plan.json"
PLAN_MD = ROOT / "reports" / "layer8_small_province_merge_plan.md"
GEOMETRY_PATH = ROOT / "assets" / "map_geometry" / "provinces.json"
SUPERREGION_RULES_PATH = ROOT / "assets" / "game_data" / "world_superregion_rules.json"
ISLAND_RULES_PATH = ROOT / "assets" / "game_data" / "world_island_region_rules.json"
WORLD_PX = 8192.0
EARTH_RADIUS_KM = 6371.0088
EPS = 1e-9
DEFAULT_MAX_ISOLATED_MERGE_KM = 300.0


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def polygon_from_entry(entry: dict[str, Any]):
    rings = entry.get("rings", [])
    if not rings:
        return Polygon()
    geom = Polygon(rings[0], rings[1:])
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom


def world_xy_to_lon_lat(x: float, y: float) -> tuple[float, float]:
    lon = x / WORLD_PX * 360.0 - 180.0
    mercator_n = math.pi - 2.0 * math.pi * y / WORLD_PX
    lat = math.degrees(math.atan(math.sinh(mercator_n)))
    return lon, lat


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    h = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def load_low_countries_core() -> set[str]:
    doc = read_json(SUPERREGION_RULES_PATH)
    for item in doc.get("superregions", []):
        if item.get("id") == "superregion:low_countries":
            return {str(x) for x in item.get("core_region_names", [])}
    return set()


def load_max_isolated_merge_km() -> float:
    rules = read_json(ISLAND_RULES_PATH)
    protection = rules.get("historical_province_protection", {})
    return float(protection.get("max_same_country_isolated_merge_distance_km", DEFAULT_MAX_ISOLATED_MERGE_KM))


def clear_target_fields(action: dict[str, Any]) -> None:
    for key in (
        "target_family_id", "target_family_key", "target_province_id", "target_name",
        "target_country_prefix", "target_region_name", "cross_country", "score",
        "score_parts", "distance_units", "distance_km", "selection_tier",
    ):
        action.pop(key, None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    plan = read_json(PLAN_ASSET)
    if plan.get("format") != "layer8_small_province_merge_plan/v2":
        raise RuntimeError(f"Unexpected plan format: {plan.get('format')}")

    actions = [dict(x) for x in plan.get("family_actions", [])]
    action_by_family = {str(x["family_id"]): x for x in actions}
    if len(actions) != 2903 or len(action_by_family) != 2903:
        raise RuntimeError(f"Unexpected family coverage: {len(actions)}")

    geom_by_pid: dict[str, Any] = {}
    for entry in read_json(GEOMETRY_PATH).get("provinces", []):
        pid = str(entry.get("id", ""))
        geom = polygon_from_entry(entry)
        if pid and not geom.is_empty:
            geom_by_pid[pid] = geom
    if len(geom_by_pid) != 4027:
        raise RuntimeError(f"Expected 4027 render geometries, got {len(geom_by_pid)}")

    family_centroid: dict[str, tuple[float, float]] = {}
    for action in actions:
        family_id = str(action["family_id"])
        members = [str(x) for x in action.get("member_ids", [])]
        geom = unary_union([geom_by_pid[p] for p in members])
        point = geom.centroid
        family_centroid[family_id] = world_xy_to_lon_lat(float(point.x), float(point.y))

    low_countries_core = load_low_countries_core()
    max_isolated_merge_km = load_max_isolated_merge_km()

    def crosses_low_countries(source: dict[str, Any], target: dict[str, Any]) -> bool:
        source_inside = str(source.get("region_name", "")) in low_countries_core
        target_inside = str(target.get("region_name", "")) in low_countries_core
        return source_inside != target_inside

    def is_hard_locked(action: dict[str, Any]) -> bool:
        return action.get("status") == "LOCKED_APPROVED"

    def is_protected(action: dict[str, Any]) -> bool:
        return action.get("status") == "PROTECTED_HISTORICAL_ISLAND"

    def target_allowed(source: dict[str, Any], target: dict[str, Any]) -> bool:
        if source["family_id"] == target["family_id"]:
            return False
        if str(source.get("country_prefix", "")) != str(target.get("country_prefix", "")):
            return False
        if is_hard_locked(target):
            return False
        if crosses_low_countries(source, target):
            return False
        source_area = float(source.get("area_km2", 0.0))
        target_area = float(target.get("area_km2", 0.0))
        target_is_small = target_area < 500.0
        if target_is_small and not is_protected(target) and target_area <= source_area + EPS:
            return False
        return True

    def nearest_same_country(source: dict[str, Any]) -> tuple[dict[str, Any], float] | None:
        source_id = str(source["family_id"])
        ranked: list[tuple[float, int, float, str, dict[str, Any]]] = []
        for target in actions:
            if not target_allowed(source, target):
                continue
            target_id = str(target["family_id"])
            distance = haversine_km(family_centroid[source_id], family_centroid[target_id])
            same_region_rank = 0 if source.get("region_name") == target.get("region_name") else 1
            ranked.append((distance, same_region_rank, -float(target.get("area_km2", 0.0)), target_id, target))
        if not ranked:
            return None
        ranked.sort(key=lambda x: x[:4])
        distance, _, _, _, target = ranked[0]
        if distance > max_isolated_merge_km:
            return None
        return target, distance

    original_auto_count = sum(1 for x in actions if str(x.get("status", "")).startswith("AUTO_MERGE"))
    target_change_count = 0
    converted_to_keep_count = 0
    changes: list[dict[str, Any]] = []

    for source in actions:
        status = str(source.get("status", ""))
        if not status.startswith("AUTO_MERGE"):
            continue

        old_target_id = str(source.get("target_family_id", ""))
        old_target = action_by_family.get(old_target_id)
        touching_same_country_ok = (
            status == "AUTO_MERGE_TOUCHING"
            and old_target is not None
            and target_allowed(source, old_target)
        )
        if touching_same_country_ok:
            source["cross_country"] = False
            continue

        fallback = nearest_same_country(source)
        if fallback is None:
            old_target_name = str(source.get("target_name", ""))
            clear_target_fields(source)
            source["status"] = "KEEP_ISOLATED_SMALL"
            source["reason"] = "no_safe_same_country_target_within_distance_limit"
            source["max_isolated_merge_distance_km"] = max_isolated_merge_km
            converted_to_keep_count += 1
            changes.append({
                "family_id": source["family_id"],
                "name": source.get("name", ""),
                "change": "merge_cancelled_keep_isolated",
                "old_target_family_id": old_target_id,
                "old_target_name": old_target_name,
            })
            continue

        target, distance = fallback
        new_target_id = str(target["family_id"])
        source["status"] = "AUTO_MERGE_NEAREST_SAME_COUNTRY"
        source["reason"] = "isolated_small_family_nearest_same_country_within_distance_limit"
        source["target_family_id"] = new_target_id
        source["target_family_key"] = target.get("family_key", "")
        source["target_province_id"] = target.get("anchor_province_id", "")
        source["target_name"] = target.get("name", "")
        source["target_country_prefix"] = target.get("country_prefix", "")
        source["target_region_name"] = target.get("region_name", "")
        source["cross_country"] = False
        source["distance_km"] = round(distance, 3)
        source["max_isolated_merge_distance_km"] = max_isolated_merge_km
        source["selection_tier"] = "true_geographic_nearest_same_country"
        source.pop("distance_units", None)
        source.pop("score", None)
        source.pop("score_parts", None)
        if old_target_id != new_target_id or status != source["status"]:
            target_change_count += 1
            changes.append({
                "family_id": source["family_id"],
                "name": source.get("name", ""),
                "change": "target_refined_same_country",
                "old_target_family_id": old_target_id,
                "new_target_family_id": new_target_id,
                "new_target_name": target.get("name", ""),
                "distance_km": round(distance, 3),
            })

    direct_parent: dict[str, str] = {}
    for action in actions:
        family_id = str(action["family_id"])
        if str(action.get("status", "")).startswith("AUTO_MERGE"):
            target = str(action.get("target_family_id", ""))
            if target not in action_by_family:
                raise RuntimeError(f"Missing target after refinement: {family_id} -> {target}")
            direct_parent[family_id] = target
        else:
            direct_parent[family_id] = family_id

    max_depth = 0
    cycle_count = 0
    for start in direct_parent:
        current = start
        seen: set[str] = set()
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

    auto_actions = [x for x in actions if str(x.get("status", "")).startswith("AUTO_MERGE")]
    isolated_keeps = [x for x in actions if x.get("status") == "KEEP_ISOLATED_SMALL"]
    protected_absorbed = sum(1 for x in auto_actions if is_protected(x))
    hard_lock_source_merge = sum(1 for x in auto_actions if is_hard_locked(x))
    cross_country_count = 0
    low_countries_bad = 0
    too_far_count = 0
    for source in auto_actions:
        target = action_by_family[str(source["target_family_id"])]
        if source.get("country_prefix") != target.get("country_prefix"):
            cross_country_count += 1
        if crosses_low_countries(source, target):
            low_countries_bad += 1
        if "distance_km" in source and float(source["distance_km"]) > max_isolated_merge_km + EPS:
            too_far_count += 1

    plan["family_actions"] = actions
    plan.setdefault("policy", {})["modern_country_boundary_is_preference_not_hard_constraint"] = False
    plan["policy"]["cross_country_province_merge_forbidden"] = True
    plan["policy"]["isolated_fallback_uses_true_geographic_distance"] = True
    plan["policy"]["max_same_country_isolated_merge_distance_km"] = max_isolated_merge_km
    plan["summary"]["base_candidate_merge_count"] = original_auto_count
    plan["summary"]["automatic_merge_count"] = len(auto_actions)
    plan["summary"]["cross_country_automatic_merge_count"] = cross_country_count
    plan["summary"]["geographic_refined_target_count"] = target_change_count
    plan["summary"]["isolated_small_keep_count"] = len(isolated_keeps)
    plan["summary"]["family_status_counts"] = dict(sorted(CounterLike(str(x.get("status", "")) for x in actions).items()))
    plan["validations"]["cross_country_auto_merge_count"] = cross_country_count
    plan["validations"]["geographic_refinement_cycle_count"] = cycle_count
    plan["validations"]["geographic_refinement_max_merge_depth"] = max_depth
    plan["validations"]["geographic_refinement_protected_source_merge_count"] = protected_absorbed
    plan["validations"]["geographic_refinement_hard_lock_source_merge_count"] = hard_lock_source_merge
    plan["validations"]["low_countries_superregion_constraint_violation_count"] = low_countries_bad
    plan["validations"]["isolated_merge_over_distance_limit_count"] = too_far_count
    plan["geographic_refinement"] = {
        "target_refined_count": target_change_count,
        "converted_to_keep_isolated_count": converted_to_keep_count,
        "distance_metric": "haversine_km_between_logical_family_geometry_centroids",
        "same_country_required": True,
        "max_isolated_merge_distance_km": max_isolated_merge_km,
        "changes": changes,
    }

    write_json(PLAN_ASSET, plan)
    write_json(PLAN_REPORT, plan)

    protected_counts = CounterLike(
        str(x.get("reason", "")) for x in actions if x.get("status") == "PROTECTED_HISTORICAL_ISLAND"
    )
    lines = [
        "# Layer 8 — финальный план объединения маленьких провинций",
        "",
        "> План неразрушающий. Государственные/территориальные границы не пересекаются; изолированные цели проверены по реальному расстоянию.",
        "",
        "## Сводка",
        "",
        f"- Layer 8 записей: **{plan['summary']['layer8_record_count']}**",
        f"- Исходных одноклеточных <500 км²: **{plan['summary']['raw_one_cell_under_500_count']}**",
        f"- Логических source-family: **{plan['summary']['logical_family_count']}**",
        f"- Логических family <500 км²: **{plan['summary']['logical_family_under_500_count']}**",
        f"- Исходных кандидатов на merge: **{original_auto_count}**",
        f"- Финальных безопасных merge: **{len(auto_actions)}**",
        f"- Изолированных маленьких, оставленных самостоятельными: **{len(isolated_keeps)}**",
        f"- Cross-country merge: **{cross_country_count}**",
        f"- REVIEW: **{plan['summary']['review_count']}**",
        "",
        "## Инварианты",
        "",
        f"- Merge-циклы: **{cycle_count}**",
        f"- Поглощённых protected-source: **{protected_absorbed}**",
        f"- Нарушений hard-lock source: **{hard_lock_source_merge}**",
        f"- Нарушений «Нижних земель»: **{low_countries_bad}**",
        f"- Изолированных merge дальше {max_isolated_merge_km:.0f} км: **{too_far_count}**",
        "",
        "## Защищённые островные группы",
        "",
    ]
    for key, count in sorted(protected_counts.items()):
        lines.append(f"- `{key}`: **{count}** logical family")

    lines.extend(["", "## Финальные автоматические merge", ""])
    for action in auto_actions:
        distance = f", {action['distance_km']:.1f} км" if "distance_km" in action else ""
        lines.append(
            f"- **{action['name']}** ({float(action['area_km2']):.1f} км²) → "
            f"**{action.get('target_name', '?')}** [same-country{distance}] — `{action['status']}`"
        )

    lines.extend(["", "## Изолированные маленькие провинции, которые нельзя безопасно поглотить", ""])
    for action in isolated_keeps:
        lines.append(
            f"- **{action['name']}** ({float(action['area_km2']):.1f} км²), "
            f"{action.get('country_prefix', '')} — `{action.get('reason', '')}`"
        )
    PLAN_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = {
        "base_candidate_merge_count": original_auto_count,
        "final_auto_merge_count": len(auto_actions),
        "isolated_small_keep_count": len(isolated_keeps),
        "target_refined_count": target_change_count,
        "cycle_count": cycle_count,
        "max_merge_depth": max_depth,
        "protected_source_merge_count": protected_absorbed,
        "hard_lock_source_merge_count": hard_lock_source_merge,
        "low_countries_violation_count": low_countries_bad,
        "cross_country_merge_count": cross_country_count,
        "too_far_isolated_merge_count": too_far_count,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    failures = []
    if cycle_count:
        failures.append(f"merge cycles: {cycle_count}")
    if protected_absorbed:
        failures.append(f"protected source merges: {protected_absorbed}")
    if hard_lock_source_merge:
        failures.append(f"hard-lock source merges: {hard_lock_source_merge}")
    if low_countries_bad:
        failures.append(f"Low Countries violations: {low_countries_bad}")
    if cross_country_count:
        failures.append(f"cross-country merges: {cross_country_count}")
    if too_far_count:
        failures.append(f"isolated merges over distance limit: {too_far_count}")
    if args.check and failures:
        raise SystemExit("; ".join(failures))


class CounterLike(dict[str, int]):
    def __init__(self, values):
        super().__init__()
        for value in values:
            self[value] = self.get(value, 0) + 1


if __name__ == "__main__":
    main()
