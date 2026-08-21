#!/usr/bin/env python3
"""Build a deterministic, non-destructive Layer-8 small-province merge plan.

The planner never edits province geometry. It operates on the current 4027
Layer-8 render records, first reconstructs split source-feature families, then
proposes logical merges for genuinely small families. Historical/strategic
islands, Slovenia and Greater London are protected by policy.

Outputs:
- assets/game_data/layer8_small_province_merge_plan.json
- reports/layer8_small_province_merge_plan.json
- reports/layer8_small_province_merge_plan.md
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[2]
GEOMETRY_PATH = ROOT / "assets" / "map_geometry" / "provinces.json"
IDENTITY_PATH = ROOT / "assets" / "game_data" / "provinces.json"
TARGET_PATH = ROOT / "assets" / "game_data" / "world_province_cell_targets.json"
ASSIGNMENT_PATH = ROOT / "assets" / "game_data" / "world_region_assignments_draft.json"
ISLAND_RULES_PATH = ROOT / "assets" / "game_data" / "world_island_region_rules.json"
SUPERREGION_RULES_PATH = ROOT / "assets" / "game_data" / "world_superregion_rules.json"
OUT_ASSET = ROOT / "assets" / "game_data" / "layer8_small_province_merge_plan.json"
OUT_JSON = ROOT / "reports" / "layer8_small_province_merge_plan.json"
OUT_MD = ROOT / "reports" / "layer8_small_province_merge_plan.md"

EXPECTED_LAYER8_COUNT = 4027
EXPECTED_RAW_SMALL_CANDIDATES = 878
SMALL_AREA_KM2 = 500.0
VERY_SMALL_AREA_KM2 = 100.0
NEIGHBOR_TOLERANCE_PX = 1.0
EPS = 1e-9


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def country_prefix(legacy_id: str) -> str:
    return legacy_id.split("__", 1)[0] if "__" in legacy_id else legacy_id


def family_key(legacy_id: str) -> str:
    return re.sub(r"_\d+$", "", legacy_id)


def norm_text(value: Any) -> str:
    return str(value or "").casefold().strip()


def geometry_from_entry(entry: dict[str, Any]):
    rings = entry.get("rings", [])
    if not rings:
        return Polygon()
    geom = Polygon(rings[0], rings[1:])
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom


def safe_compactness(geom: Any) -> float:
    if geom.is_empty or geom.area <= EPS or geom.length <= EPS:
        return 0.0
    return float(4.0 * math.pi * geom.area / (geom.length * geom.length))


def matches_rule(identity: dict[str, Any], rule_match: dict[str, Any]) -> bool:
    legacy = norm_text(identity.get("legacy_id"))
    name = norm_text(identity.get("name"))
    prefix = country_prefix(legacy)

    prefixes = {norm_text(x) for x in rule_match.get("country_prefixes", [])}
    if prefixes and prefix in prefixes:
        return True

    legacy_prefixes = [norm_text(x) for x in rule_match.get("legacy_id_prefixes", [])]
    if any(legacy.startswith(x) for x in legacy_prefixes if x):
        return True

    name_tokens = [norm_text(x) for x in rule_match.get("name_contains_any", [])]
    if any(token in name for token in name_tokens if token):
        return True

    return False


def load_protected_groups() -> list[dict[str, Any]]:
    rules = read_json(ISLAND_RULES_PATH)
    protection = rules.get("historical_province_protection", {})
    return [dict(x) for x in protection.get("protected_groups", [])]


def load_archipelago_merge_zones() -> list[dict[str, Any]]:
    rules = read_json(ISLAND_RULES_PATH)
    protection = rules.get("historical_province_protection", {})
    return [dict(x) for x in protection.get("declared_archipelago_merge_zones", [])]


def load_low_countries_core() -> set[str]:
    if not SUPERREGION_RULES_PATH.exists():
        return set()
    doc = read_json(SUPERREGION_RULES_PATH)
    for item in doc.get("superregions", []):
        if item.get("id") == "superregion:low_countries":
            return {str(x) for x in item.get("core_region_names", [])}
    return set()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail on invariant violations after writing the plan")
    args = parser.parse_args()

    geometry_doc = read_json(GEOMETRY_PATH)
    identity_doc = read_json(IDENTITY_PATH)
    target_doc = read_json(TARGET_PATH)
    assignment_doc = read_json(ASSIGNMENT_PATH)

    geometry_entries = geometry_doc.get("provinces", [])
    identities_list = identity_doc.get("provinces", [])
    targets_list = target_doc.get("provinces", [])
    assignments_list = assignment_doc.get("assignments", [])

    counts = {
        "geometry": len(geometry_entries),
        "identity": len(identities_list),
        "targets": len(targets_list),
        "assignments": len(assignments_list),
    }
    if any(v != EXPECTED_LAYER8_COUNT for v in counts.values()):
        raise RuntimeError(f"Layer-8 coverage mismatch: {counts}")

    identities = {str(x["id"]): dict(x) for x in identities_list}
    targets = {str(x["province_id"]): dict(x) for x in targets_list}
    assignments = {str(x["province_id"]): dict(x) for x in assignments_list}
    geometries: dict[str, Any] = {}
    for entry in geometry_entries:
        pid = str(entry.get("id", ""))
        geom = geometry_from_entry(entry)
        if pid and not geom.is_empty:
            geometries[pid] = geom
    if len(geometries) != EXPECTED_LAYER8_COUNT:
        raise RuntimeError(f"Geometry parse coverage mismatch: {len(geometries)}")

    raw_small_ids = {
        pid for pid, target in targets.items()
        if int(target.get("target_cell_count", 0)) == 1
        and float(target.get("area_km2", 0.0)) < SMALL_AREA_KM2
    }
    raw_very_small_ids = {
        pid for pid in raw_small_ids
        if float(targets[pid].get("area_km2", 0.0)) < VERY_SMALL_AREA_KM2
    }

    protected_rules = load_protected_groups()
    archipelago_zones = load_archipelago_merge_zones()
    low_countries_core = load_low_countries_core()

    family_members: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for pid, ident in identities.items():
        legacy = str(ident.get("legacy_id", ""))
        key = (country_prefix(legacy), family_key(legacy), norm_text(ident.get("name")))
        family_members[key].append(pid)

    families: list[dict[str, Any]] = []
    pid_to_family: dict[str, int] = {}
    for index, key in enumerate(sorted(family_members.keys())):
        members = sorted(family_members[key])
        member_geoms = [geometries[p] for p in members]
        merged_geom = unary_union(member_geoms)
        if not merged_geom.is_valid:
            merged_geom = merged_geom.buffer(0)
        total_area_km2 = sum(float(targets[p].get("area_km2", 0.0)) for p in members)
        anchor_pid = max(members, key=lambda p: float(targets[p].get("area_km2", 0.0)))
        anchor_ident = identities[anchor_pid]
        anchor_assignment = assignments[anchor_pid]
        prefix = key[0]
        region_name = str(anchor_assignment.get("region_name", ""))

        hard_lock_reason = ""
        if prefix == "slovenia":
            hard_lock_reason = "user_locked_slovenia_layer8"
        else:
            member_text = " ".join(
                norm_text(identities[p].get("legacy_id")) + " " + norm_text(identities[p].get("name"))
                for p in members
            )
            if (
                "greater_london" in member_text
                or "greater london" in member_text
                or region_name in {"Большой Лондон", "Greater London"}
            ):
                hard_lock_reason = "user_locked_greater_london_layer8"

        protected_group: dict[str, Any] | None = None
        for rule in protected_rules:
            match = dict(rule.get("match", {}))
            if any(matches_rule(identities[p], match) for p in members):
                protected_group = rule
                break

        family = {
            "index": index,
            "family_id": f"family:{key[1]}",
            "family_key": key[1],
            "country_prefix": prefix,
            "name": str(anchor_ident.get("name", "")),
            "member_ids": members,
            "member_count": len(members),
            "anchor_province_id": anchor_pid,
            "area_km2": round(total_area_km2, 6),
            "region_id": str(anchor_assignment.get("region_id", "")),
            "region_name": region_name,
            "geometry": merged_geom,
            "hard_lock_reason": hard_lock_reason,
            "protected_group_id": str(protected_group.get("id", "")) if protected_group else "",
            "protected_group_label": str(protected_group.get("label", "")) if protected_group else "",
            "protection_mode": str(protected_group.get("protection_mode", "")) if protected_group else "",
            "is_raw_small_member": any(p in raw_small_ids for p in members),
            "logical_small": total_area_km2 < SMALL_AREA_KM2,
            "logical_very_small": total_area_km2 < VERY_SMALL_AREA_KM2,
        }
        families.append(family)
        for pid in members:
            pid_to_family[pid] = index

    family_geoms = [f["geometry"] for f in families]
    tree = STRtree(family_geoms)

    country_to_family_indices: dict[str, list[int]] = defaultdict(list)
    for f in families:
        country_to_family_indices[f["country_prefix"]].append(f["index"])

    def in_archipelago_zone(family: dict[str, Any]) -> bool:
        for zone in archipelago_zones:
            if family["region_name"] in set(zone.get("region_names", [])):
                return True
        return False

    def target_allowed(source: dict[str, Any], target: dict[str, Any], *, cross_sea: bool) -> bool:
        if source["index"] == target["index"]:
            return False
        if source["country_prefix"] != target["country_prefix"]:
            return False
        if target["hard_lock_reason"]:
            return False
        if source["region_name"] in low_countries_core and target["region_name"] not in low_countries_core:
            return False
        if cross_sea:
            if not in_archipelago_zone(source):
                return False
            if source["region_name"] != target["region_name"]:
                return False
        return True

    def score_touching(source: dict[str, Any], target: dict[str, Any]) -> tuple[float, dict[str, float]]:
        sg = source["geometry"]
        tg = target["geometry"]
        shared = float(sg.boundary.intersection(tg.boundary).length)
        source_perimeter = max(float(sg.length), EPS)
        shared_ratio = shared / source_perimeter
        same_region = 1.0 if source["region_name"] == target["region_name"] else 0.0
        combined = unary_union([sg, tg])
        compact_before = safe_compactness(tg)
        compact_after = safe_compactness(combined)
        compact_delta = compact_after - compact_before
        target_area = float(target["area_km2"])
        area_stability = min(1.0, target_area / max(float(source["area_km2"]), 1.0))
        score = 6.0 * shared_ratio + 2.0 * same_region + 1.0 * area_stability + 1.0 * compact_delta
        return score, {
            "shared_boundary_units": round(shared, 6),
            "shared_boundary_ratio": round(shared_ratio, 6),
            "same_region": same_region,
            "compactness_delta": round(compact_delta, 6),
            "area_stability": round(area_stability, 6),
        }

    def touching_candidates(source: dict[str, Any]) -> list[tuple[float, dict[str, Any], dict[str, float]]]:
        sg = source["geometry"]
        hits = tree.query(sg.buffer(NEIGHBOR_TOLERANCE_PX))
        result: list[tuple[float, dict[str, Any], dict[str, float]]] = []
        for raw_index in hits:
            idx = int(raw_index)
            target = families[idx]
            if not target_allowed(source, target, cross_sea=False):
                continue
            shared = float(sg.boundary.intersection(target["geometry"].boundary).length)
            distance = float(sg.distance(target["geometry"]))
            if shared <= EPS and distance > NEIGHBOR_TOLERANCE_PX:
                continue
            score, parts = score_touching(source, target)
            if shared <= EPS:
                # Tiny simplification gaps are fallback only and must never beat a real shared border.
                score -= 4.0 + distance
                parts["gap_distance_units"] = round(distance, 6)
            result.append((score, target, parts))
        result.sort(key=lambda x: (-x[0], -float(x[1]["area_km2"]), x[1]["family_key"]))
        return result

    def archipelago_candidate(source: dict[str, Any]) -> tuple[dict[str, Any], float] | None:
        if not in_archipelago_zone(source):
            return None
        candidates: list[tuple[float, float, dict[str, Any]]] = []
        for idx in country_to_family_indices[source["country_prefix"]]:
            target = families[idx]
            if not target_allowed(source, target, cross_sea=True):
                continue
            distance = float(source["geometry"].distance(target["geometry"]))
            # Prefer a non-small anchor, then the physically closest family.
            small_penalty = 1.0 if target["logical_small"] and not target["protected_group_id"] else 0.0
            candidates.append((small_penalty, distance, target))
        if not candidates:
            return None
        candidates.sort(key=lambda x: (x[0], x[1], -float(x[2]["area_km2"]), x[2]["family_key"]))
        _, distance, target = candidates[0]
        return target, distance

    family_actions: list[dict[str, Any]] = []
    piece_actions: list[dict[str, Any]] = []

    for family in families:
        base = {
            "family_id": family["family_id"],
            "family_key": family["family_key"],
            "country_prefix": family["country_prefix"],
            "name": family["name"],
            "member_ids": family["member_ids"],
            "anchor_province_id": family["anchor_province_id"],
            "area_km2": family["area_km2"],
            "region_id": family["region_id"],
            "region_name": family["region_name"],
        }

        if family["hard_lock_reason"]:
            family_actions.append({**base, "status": "LOCKED_APPROVED", "reason": family["hard_lock_reason"]})
        elif family["protected_group_id"]:
            family_actions.append({
                **base,
                "status": "PROTECTED_HISTORICAL_ISLAND",
                "reason": family["protected_group_id"],
                "protected_group_label": family["protected_group_label"],
                "protection_mode": family["protection_mode"],
            })
        elif not family["logical_small"]:
            family_actions.append({**base, "status": "KEEP", "reason": "logical_family_area_at_least_500_km2"})
        else:
            candidates = touching_candidates(family)
            if candidates:
                score, target, parts = candidates[0]
                family_actions.append({
                    **base,
                    "status": "AUTO_MERGE_MAINLAND",
                    "reason": "best_same_country_touching_neighbor",
                    "target_family_id": target["family_id"],
                    "target_family_key": target["family_key"],
                    "target_province_id": target["anchor_province_id"],
                    "target_name": target["name"],
                    "target_region_name": target["region_name"],
                    "score": round(score, 6),
                    "score_parts": parts,
                })
            else:
                island_target = archipelago_candidate(family)
                if island_target is not None:
                    target, distance = island_target
                    family_actions.append({
                        **base,
                        "status": "AUTO_MERGE_ARCHIPELAGO_SATELLITE",
                        "reason": "declared_caribbean_archipelago_same_country_nearest_family",
                        "target_family_id": target["family_id"],
                        "target_family_key": target["family_key"],
                        "target_province_id": target["anchor_province_id"],
                        "target_name": target["name"],
                        "target_region_name": target["region_name"],
                        "distance_units": round(distance, 6),
                    })
                else:
                    family_actions.append({
                        **base,
                        "status": "REVIEW",
                        "reason": "no_safe_same_country_land_neighbor_or_declared_archipelago_target",
                    })

        # Render pieces belonging to one source feature are explicitly represented
        # in the plan. This is logical reassembly only: no polygon bridge is made.
        if len(family["member_ids"]) > 1:
            for pid in family["member_ids"]:
                if pid == family["anchor_province_id"]:
                    continue
                status = "LOCKED_APPROVED" if family["hard_lock_reason"] else "TECHNICAL_FAMILY_REASSEMBLY"
                piece_actions.append({
                    "province_id": pid,
                    "legacy_id": identities[pid].get("legacy_id", ""),
                    "name": identities[pid].get("name", ""),
                    "area_km2": round(float(targets[pid].get("area_km2", 0.0)), 6),
                    "status": status,
                    "target_province_id": family["anchor_province_id"] if status == "TECHNICAL_FAMILY_REASSEMBLY" else "",
                    "family_id": family["family_id"],
                    "reason": family["hard_lock_reason"] if family["hard_lock_reason"] else "same_source_feature_render_piece",
                })

    status_counts = Counter(x["status"] for x in family_actions)
    protected_group_counts = Counter(
        x.get("reason", "") for x in family_actions if x["status"] == "PROTECTED_HISTORICAL_ISLAND"
    )

    cross_country_auto_merges = 0
    hard_lock_violations = 0
    protected_absorption_violations = 0
    family_by_id = {f["family_id"]: f for f in families}
    action_by_family_id = {a["family_id"]: a for a in family_actions}
    for action in family_actions:
        if not action["status"].startswith("AUTO_MERGE"):
            continue
        target_family = family_by_id.get(str(action.get("target_family_id", "")))
        source_family = family_by_id[action["family_id"]]
        if not target_family or target_family["country_prefix"] != source_family["country_prefix"]:
            cross_country_auto_merges += 1
        if source_family["hard_lock_reason"] or (target_family and target_family["hard_lock_reason"]):
            hard_lock_violations += 1
        if source_family["protected_group_id"]:
            protected_absorption_violations += 1

    slovenia_actions = [a for a in family_actions if a["country_prefix"] == "slovenia"]
    london_actions = [a for a in family_actions if a.get("reason") == "user_locked_greater_london_layer8"]
    low_countries_bad_targets = 0
    for action in family_actions:
        if not action["status"].startswith("AUTO_MERGE"):
            continue
        if action["region_name"] in low_countries_core and action.get("target_region_name") not in low_countries_core:
            low_countries_bad_targets += 1

    validations = {
        "layer8_record_count_ok": len(identities) == EXPECTED_LAYER8_COUNT,
        "raw_small_candidate_count_ok": len(raw_small_ids) == EXPECTED_RAW_SMALL_CANDIDATES,
        "cross_country_auto_merge_count": cross_country_auto_merges,
        "hard_lock_violation_count": hard_lock_violations,
        "protected_island_absorption_violation_count": protected_absorption_violations,
        "low_countries_superregion_constraint_violation_count": low_countries_bad_targets,
        "slovenia_family_action_count": len(slovenia_actions),
        "slovenia_all_locked": bool(slovenia_actions) and all(a["status"] == "LOCKED_APPROVED" for a in slovenia_actions),
        "greater_london_family_action_count": len(london_actions),
        "greater_london_locked": len(london_actions) >= 1,
    }

    summary = {
        "layer8_record_count": len(identities),
        "raw_one_cell_under_500_count": len(raw_small_ids),
        "raw_one_cell_under_100_count": len(raw_very_small_ids),
        "logical_family_count": len(families),
        "logical_family_under_500_count": sum(1 for f in families if f["logical_small"]),
        "logical_family_under_100_count": sum(1 for f in families if f["logical_very_small"]),
        "multi_piece_family_count": sum(1 for f in families if f["member_count"] > 1),
        "technical_render_piece_reassembly_count": sum(1 for x in piece_actions if x["status"] == "TECHNICAL_FAMILY_REASSEMBLY"),
        "family_status_counts": dict(sorted(status_counts.items())),
        "protected_group_counts": dict(sorted(protected_group_counts.items())),
    }

    serializable_family_actions = family_actions
    doc = {
        "schema_version": 1,
        "format": "layer8_small_province_merge_plan/v1",
        "content_version": "2026.08.21",
        "source": {
            "geometry": str(GEOMETRY_PATH.relative_to(ROOT)),
            "identity": str(IDENTITY_PATH.relative_to(ROOT)),
            "targets": str(TARGET_PATH.relative_to(ROOT)),
            "assignments": str(ASSIGNMENT_PATH.relative_to(ROOT)),
            "island_rules": str(ISLAND_RULES_PATH.relative_to(ROOT)),
            "superregion_rules": str(SUPERREGION_RULES_PATH.relative_to(ROOT)),
        },
        "policy": {
            "small_threshold_km2": SMALL_AREA_KM2,
            "very_small_threshold_km2": VERY_SMALL_AREA_KM2,
            "plan_is_non_destructive": True,
            "cross_country_auto_merge_forbidden": True,
            "generic_cross_sea_auto_merge_forbidden": True,
            "declared_caribbean_same_country_archipelago_merge_allowed": True,
            "slovenia_layer8_locked": True,
            "greater_london_layer8_locked": True,
            "protected_historical_islands_locked": True,
            "low_countries_future_superregion_constraint_enabled": bool(low_countries_core),
        },
        "summary": summary,
        "validations": validations,
        "family_actions": serializable_family_actions,
        "piece_actions": piece_actions,
    }

    write_json(OUT_ASSET, doc)
    write_json(OUT_JSON, doc)

    merge_actions = [a for a in family_actions if a["status"].startswith("AUTO_MERGE")]
    review_actions = [a for a in family_actions if a["status"] == "REVIEW"]
    protected_actions = [a for a in family_actions if a["status"] == "PROTECTED_HISTORICAL_ISLAND"]

    lines = [
        "# Layer 8 — план объединения маленьких провинций",
        "",
        "> Это **неразрушающий план**. Геометрия Layer 8 этим шагом не изменяется.",
        "",
        "## Сводка",
        "",
        f"- Layer 8 записей: **{summary['layer8_record_count']}**",
        f"- Исходных одноклеточных <500 км²: **{summary['raw_one_cell_under_500_count']}**",
        f"- Исходных одноклеточных <100 км²: **{summary['raw_one_cell_under_100_count']}**",
        f"- Логических source-family после восстановления multipart: **{summary['logical_family_count']}**",
        f"- Логических family <500 км²: **{summary['logical_family_under_500_count']}**",
        f"- Технических render-piece для обратной сборки: **{summary['technical_render_piece_reassembly_count']}**",
        f"- Автоматических безопасных merge: **{len(merge_actions)}**",
        f"- На REVIEW: **{len(review_actions)}**",
        f"- Защищённых исторических островных family: **{len(protected_actions)}**",
        "",
        "## Инварианты",
        "",
        f"- Merge через государственную границу: **{cross_country_auto_merges}**",
        f"- Нарушения lock Словении/Большого Лондона: **{hard_lock_violations}**",
        f"- Поглощение защищённых островов: **{protected_absorption_violations}**",
        f"- Нарушения будущего суперрегиона «Нижние земли»: **{low_countries_bad_targets}**",
        f"- Словения полностью locked: **{validations['slovenia_all_locked']}**",
        f"- Большой Лондон locked: **{validations['greater_london_locked']}**",
        "",
        "## Защищённые островные группы",
        "",
    ]
    for key, count in sorted(protected_group_counts.items()):
        lines.append(f"- `{key}`: **{count}** logical family")

    lines.extend(["", "## Первые 100 автоматических merge", ""])
    for action in merge_actions[:100]:
        lines.append(
            f"- **{action['name']}** ({action['area_km2']:.1f} км²) → "
            f"**{action.get('target_name', '?')}** — `{action['status']}`"
        )

    lines.extend(["", "## Первые 100 REVIEW", ""])
    for action in review_actions[:100]:
        lines.append(
            f"- **{action['name']}** ({action['area_km2']:.1f} км²), "
            f"{action['country_prefix']}, {action['region_name']} — `{action['reason']}`"
        )

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({"summary": summary, "validations": validations}, ensure_ascii=False, indent=2))

    failures = []
    if len(raw_small_ids) != EXPECTED_RAW_SMALL_CANDIDATES:
        failures.append(f"raw small candidates expected {EXPECTED_RAW_SMALL_CANDIDATES}, got {len(raw_small_ids)}")
    if cross_country_auto_merges:
        failures.append(f"cross-country auto merges: {cross_country_auto_merges}")
    if hard_lock_violations:
        failures.append(f"hard lock violations: {hard_lock_violations}")
    if protected_absorption_violations:
        failures.append(f"protected island absorption violations: {protected_absorption_violations}")
    if low_countries_bad_targets:
        failures.append(f"Low Countries constraint violations: {low_countries_bad_targets}")
    if not validations["slovenia_all_locked"]:
        failures.append("Slovenia is not fully locked")
    if not validations["greater_london_locked"]:
        failures.append("Greater London lock was not found")
    if args.check and failures:
        raise SystemExit("; ".join(failures))


if __name__ == "__main__":
    main()
