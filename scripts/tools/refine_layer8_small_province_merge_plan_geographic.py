#!/usr/bin/env python3
"""Geographically refine isolated Layer-8 small-province merge targets.

The first planner resolves touching land neighbors using shared boundaries and
historical region/country preferences. For isolated islands, a broad region can
span thousands of kilometres, so this pass replaces AUTO_MERGE_NEAREST and
AUTO_MERGE_ARCHIPELAGO targets with the genuinely nearest allowed logical
province measured by haversine distance between family geometry centroids.
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
WORLD_PX = 8192.0
EARTH_RADIUS_KM = 6371.0088
EPS = 1e-9


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

    refined_count = 0
    changes: list[dict[str, Any]] = []
    for source in actions:
        status = str(source.get("status", ""))
        if status not in {"AUTO_MERGE_NEAREST", "AUTO_MERGE_ARCHIPELAGO"}:
            continue
        source_id = str(source["family_id"])
        ranked: list[tuple[float, int, int, float, str, dict[str, Any]]] = []
        for target in actions:
            if not target_allowed(source, target):
                continue
            target_id = str(target["family_id"])
            distance = haversine_km(family_centroid[source_id], family_centroid[target_id])
            same_country_rank = 0 if source.get("country_prefix") == target.get("country_prefix") else 1
            same_region_rank = 0 if source.get("region_name") == target.get("region_name") else 1
            ranked.append((
                distance,
                same_country_rank,
                same_region_rank,
                -float(target.get("area_km2", 0.0)),
                target_id,
                target,
            ))
        if not ranked:
            raise RuntimeError(f"No geographic fallback target for {source_id}")
        ranked.sort(key=lambda x: x[:5])
        distance, _, _, _, _, target = ranked[0]
        old_target = str(source.get("target_family_id", ""))
        new_target = str(target["family_id"])
        source["target_family_id"] = new_target
        source["target_family_key"] = target.get("family_key", "")
        source["target_province_id"] = target.get("anchor_province_id", "")
        source["target_name"] = target.get("name", "")
        source["target_country_prefix"] = target.get("country_prefix", "")
        source["target_region_name"] = target.get("region_name", "")
        source["cross_country"] = target.get("country_prefix") != source.get("country_prefix")
        source["distance_km"] = round(distance, 3)
        source["selection_tier"] = "true_geographic_nearest_allowed_family"
        source["reason"] = "isolated_small_family_true_geographic_nearest"
        source.pop("distance_units", None)
        if old_target != new_target:
            refined_count += 1
            changes.append({
                "family_id": source_id,
                "name": source.get("name", ""),
                "old_target_family_id": old_target,
                "new_target_family_id": new_target,
                "new_target_name": target.get("name", ""),
                "distance_km": round(distance, 3),
            })

    # Verify directed merge graph remains acyclic and every edge eventually ends
    # at KEEP / LOCKED / PROTECTED root.
    direct_parent: dict[str, str] = {}
    for action in actions:
        family_id = str(action["family_id"])
        if str(action.get("status", "")).startswith("AUTO_MERGE"):
            direct_parent[family_id] = str(action.get("target_family_id", ""))
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

    protected_absorbed = sum(
        1 for action in actions
        if is_protected(action) and str(action.get("status", "")).startswith("AUTO_MERGE")
    )
    hard_lock_source_merge = sum(
        1 for action in actions
        if is_hard_locked(action) and str(action.get("status", "")).startswith("AUTO_MERGE")
    )
    low_countries_bad = 0
    cross_country_count = 0
    for source in actions:
        if not str(source.get("status", "")).startswith("AUTO_MERGE"):
            continue
        target = action_by_family[str(source["target_family_id"])]
        if crosses_low_countries(source, target):
            low_countries_bad += 1
        if source.get("country_prefix") != target.get("country_prefix"):
            cross_country_count += 1

    plan["family_actions"] = actions
    plan.setdefault("policy", {})["isolated_fallback_uses_true_geographic_distance"] = True
    plan["summary"]["cross_country_automatic_merge_count"] = cross_country_count
    plan["summary"]["geographic_refined_target_count"] = refined_count
    plan["validations"]["cross_country_auto_merge_count"] = cross_country_count
    plan["validations"]["geographic_refinement_cycle_count"] = cycle_count
    plan["validations"]["geographic_refinement_max_merge_depth"] = max_depth
    plan["validations"]["geographic_refinement_protected_source_merge_count"] = protected_absorbed
    plan["validations"]["geographic_refinement_hard_lock_source_merge_count"] = hard_lock_source_merge
    plan["validations"]["low_countries_superregion_constraint_violation_count"] = low_countries_bad
    plan["geographic_refinement"] = {
        "refined_target_count": refined_count,
        "distance_metric": "haversine_km_between_logical_family_geometry_centroids",
        "changes": changes,
    }

    write_json(PLAN_ASSET, plan)
    write_json(PLAN_REPORT, plan)

    auto_actions = [x for x in actions if str(x.get("status", "")).startswith("AUTO_MERGE")]
    protected_counts = CounterLike(
        str(x.get("reason", "")) for x in actions if x.get("status") == "PROTECTED_HISTORICAL_ISLAND"
    )
    lines = [
        "# Layer 8 — план объединения маленьких провинций",
        "",
        "> План неразрушающий; изолированные merge-цели уточнены по реальному географическому расстоянию.",
        "",
        "## Сводка",
        "",
        f"- Layer 8 записей: **{plan['summary']['layer8_record_count']}**",
        f"- Исходных одноклеточных <500 км²: **{plan['summary']['raw_one_cell_under_500_count']}**",
        f"- Логических source-family: **{plan['summary']['logical_family_count']}**",
        f"- Логических family <500 км²: **{plan['summary']['logical_family_under_500_count']}**",
        f"- Автоматических merge: **{plan['summary']['automatic_merge_count']}**",
        f"- Целей изменено географическим вторым проходом: **{refined_count}**",
        f"- Cross-country merge: **{cross_country_count}**",
        f"- REVIEW: **{plan['summary']['review_count']}**",
        "",
        "## Инварианты",
        "",
        f"- Merge-циклы: **{cycle_count}**",
        f"- Поглощённых protected-source: **{protected_absorbed}**",
        f"- Нарушений hard-lock source: **{hard_lock_source_merge}**",
        f"- Нарушений «Нижних земель»: **{low_countries_bad}**",
        "",
        "## Защищённые островные группы",
        "",
    ]
    for key, count in sorted(protected_counts.items()):
        lines.append(f"- `{key}`: **{count}** logical family")
    lines.extend(["", "## Все автоматические merge", ""])
    for action in auto_actions:
        border = "cross-country" if action.get("cross_country") else "same-country"
        distance = f", {action['distance_km']:.1f} км" if "distance_km" in action else ""
        lines.append(
            f"- **{action['name']}** ({float(action['area_km2']):.1f} км²) → "
            f"**{action.get('target_name', '?')}** [{border}{distance}] — `{action['status']}`"
        )
    PLAN_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = {
        "refined_target_count": refined_count,
        "cycle_count": cycle_count,
        "max_merge_depth": max_depth,
        "protected_source_merge_count": protected_absorbed,
        "hard_lock_source_merge_count": hard_lock_source_merge,
        "low_countries_violation_count": low_countries_bad,
        "cross_country_merge_count": cross_country_count,
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
    if args.check and failures:
        raise SystemExit("; ".join(failures))


class CounterLike(dict[str, int]):
    def __init__(self, values):
        super().__init__()
        for value in values:
            self[value] = self.get(value, 0) + 1


if __name__ == "__main__":
    main()
