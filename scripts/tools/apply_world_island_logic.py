#!/usr/bin/env python3
"""Apply island-aware region corrections before final world cell generation.

The layer-8 source stores disconnected polygon pieces as separate province
records (for example Baleares, Azores, Gotland and many archipelagos). Therefore
island correctness is mainly a REGION-FAMILY problem, not a MultiPolygon
problem inside one province record.

Rules implemented here:
- All pieces originating from the same split source feature inherit the region
  of the largest piece. This fixes cases like Gotland_2 drifting into another
  Swedish region and the same class of error worldwide.
- Iceland + Faroes + Azores + Madeira + Canaries belong to ONE common region:
  "Атлантические острова Европы".
- Orkney/Shetland/Hebrides remain Scottish and are excluded from the common
  Atlantic region.
- Small island pieces keep one cell when their area is below the active regional
  target area. Separate layer-8 island pieces are never merged into one gameplay
  cell across water.
- No terrain or relief is used.

The common Atlantic-region density profile is intentionally NOT invented here.
Until the user chooses it, those provinces retain their previous numeric profile
and target-area values; only their region_id is corrected.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parents[2]
WORLD_PX = 8192.0
EARTH_RADIUS_KM = 6371.0088

GEOMETRY_PATH = ROOT / "assets" / "map_geometry" / "provinces.json"
IDENTITY_PATH = ROOT / "assets" / "game_data" / "provinces.json"
ASSIGN_PATH = ROOT / "assets" / "game_data" / "world_region_assignments_draft.json"
TARGET_PATH = ROOT / "assets" / "game_data" / "world_province_cell_targets.json"
PROFILE_PATH = ROOT / "assets" / "game_data" / "world_region_cell_profiles.json"
OUT_ASSIGN = ROOT / "assets" / "game_data" / "world_region_assignments_island_corrected.json"
OUT_TARGET = ROOT / "assets" / "game_data" / "world_province_cell_targets_island_corrected.json"
OUT_REPORT = ROOT / "reports" / "world_island_logic_report.json"

ATLANTIC_REGION_ID = "region:world:atlantic_european_islands"
ATLANTIC_REGION_NAME = "Атлантические острова Европы"
SCOTTISH_HIGHLANDS_ID = "region:world:shotlandskoe_nagore"
SCOTTISH_HIGHLANDS_NAME = "Шотландское нагорье"
SOUTH_EAST_ENGLAND_ID = "region:world:yugo_vostochnaya_angliya"
SOUTH_EAST_ENGLAND_NAME = "Юго-Восточная Англия"

SCOTTISH_NEARSHORE_TOKENS = (
    "orkney", "shetland", "hebr", "western_isles", "outer_hebrides",
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def round_half_up(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def km_per_world_px(y: float) -> float:
    mercator_n = math.pi - 2.0 * math.pi * y / WORLD_PX
    latitude = math.degrees(math.atan(math.sinh(mercator_n)))
    return 2.0 * math.pi * EARTH_RADIUS_KM / WORLD_PX * math.cos(math.radians(latitude))


def geometry_from_entry(entry: dict[str, Any]) -> Polygon:
    rings = entry.get("rings", [])
    if not rings:
        return Polygon()
    geometry = Polygon(rings[0], rings[1:])
    if not geometry.is_valid:
        geometry = geometry.buffer(0)
    return geometry


def area_km2(geometry: Any) -> float:
    if geometry.is_empty:
        return 0.0
    scale = km_per_world_px(float(geometry.representative_point().y))
    return float(geometry.area) * scale * scale


def family_key(legacy_id: str) -> str:
    """Return original split-feature key: foo__bar_2 -> foo__bar."""
    return re.sub(r"_\d+$", "", legacy_id)


def country_prefix(legacy_id: str) -> str:
    return legacy_id.split("__", 1)[0] if "__" in legacy_id else legacy_id


def text_for(identity: dict[str, Any]) -> str:
    return (str(identity.get("name", "")) + " " + str(identity.get("legacy_id", ""))).lower()


def is_scottish_nearshore(identity: dict[str, Any]) -> bool:
    legacy = str(identity.get("legacy_id", "")).lower()
    if not legacy.startswith("united_kingdom__"):
        return False
    text = text_for(identity)
    return any(token in text for token in SCOTTISH_NEARSHORE_TOKENS)


def is_isle_of_wight(identity: dict[str, Any]) -> bool:
    return "isle_of_wight" in str(identity.get("legacy_id", "")).lower()


def is_atlantic_europe_member(identity: dict[str, Any], assignment: dict[str, Any]) -> bool:
    legacy = str(identity.get("legacy_id", "")).lower()
    prefix = country_prefix(legacy)
    lon = float(assignment.get("centroid_lon", 999.0))
    lat = float(assignment.get("centroid_lat", 999.0))

    # Whole Iceland and Faroe source families.
    if prefix in {"iceland", "faroe_islands"}:
        return True

    # Portuguese Atlantic archipelagos.
    if legacy.startswith("portugal__azores") or legacy.startswith("portugal__a_ores"):
        return True
    if legacy.startswith("portugal__madeira"):
        return True

    # Canary Islands: source naming may be Las Palmas / Santa Cruz de Tenerife,
    # therefore use the stable Spanish country prefix + geographic box.
    if prefix == "spain" and -19.5 <= lon <= -13.0 and 27.0 <= lat <= 30.5:
        return True

    # Near-shore Scottish islands are explicitly NOT part of this region.
    return False


def profile_index() -> dict[str, dict[str, Any]]:
    return {str(p.get("name", "")): p for p in read_json(PROFILE_PATH).get("profiles", [])}


def recalc_from_profile(target: dict[str, Any], profile: dict[str, Any], *, force_small_island_one: bool) -> int:
    area = float(target.get("area_km2", 0.0))
    target_area = float(profile["target_cell_area_km2"])
    minimum = int(profile["min_cells_per_province"])
    maximum = int(profile["max_cells_per_province"])
    anchor = int(target.get("anchor_min", 1) or 1)

    if force_small_island_one and area <= target_area:
        count = 1
    else:
        raw = max(1, round_half_up(area / target_area))
        count = max(minimum, min(maximum, max(raw, anchor)))

    target["profile_id"] = str(profile["profile_id"])
    target["region_target_cell_area_km2"] = target_area
    target["region_min_cells"] = minimum
    target["region_max_cells"] = maximum
    target["raw_area_count"] = round(area / target_area, 6)
    target["area_count"] = max(1, round_half_up(area / target_area))
    target["target_cell_count"] = count
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    identities = {str(x["id"]): dict(x) for x in read_json(IDENTITY_PATH).get("provinces", [])}
    assignments_doc = read_json(ASSIGN_PATH)
    assignments = [dict(x) for x in assignments_doc.get("assignments", [])]
    targets_doc = read_json(TARGET_PATH)
    targets = [dict(x) for x in targets_doc.get("provinces", [])]
    targets_by_id = {str(x["province_id"]): x for x in targets}
    profiles = profile_index()

    geometries: dict[str, Any] = {}
    for entry in read_json(GEOMETRY_PATH).get("provinces", []):
        pid = str(entry.get("id", ""))
        geometry = geometry_from_entry(entry)
        if pid and not geometry.is_empty:
            geometries[pid] = geometry

    if len(assignments) != 4027 or len(targets) != 4027 or len(geometries) != 4027:
        raise RuntimeError(f"coverage mismatch assignments={len(assignments)} targets={len(targets)} geometry={len(geometries)}")

    assignment_by_id = {str(x["province_id"]): x for x in assignments}
    corrections: list[dict[str, Any]] = []
    explicit_atlantic_ids: set[str] = set()

    def set_region(pid: str, region_id: str, region_name: str, reason: str, confidence: str = "locked") -> None:
        assignment = assignment_by_id[pid]
        old_id = str(assignment.get("region_id", ""))
        old_name = str(assignment.get("region_name", ""))
        if old_id == region_id and old_name == region_name:
            return
        assignment["region_id"] = region_id
        assignment["region_name"] = region_name
        assignment["method"] = reason
        assignment["confidence"] = confidence
        identity = identities[pid]
        corrections.append({
            "province_id": pid,
            "legacy_id": identity.get("legacy_id", ""),
            "name": identity.get("name", ""),
            "from_region_id": old_id,
            "from_region": old_name,
            "to_region_id": region_id,
            "to_region": region_name,
            "reason": reason,
        })

    # 1) Explicit semantic island rules have priority over proximity and family.
    for assignment in assignments:
        pid = str(assignment["province_id"])
        identity = identities[pid]
        if is_scottish_nearshore(identity):
            set_region(pid, SCOTTISH_HIGHLANDS_ID, SCOTTISH_HIGHLANDS_NAME, "island_scottish_nearshore_inheritance")
        elif is_isle_of_wight(identity):
            set_region(pid, SOUTH_EAST_ENGLAND_ID, SOUTH_EAST_ENGLAND_NAME, "island_nearshore_parent_region")
        elif is_atlantic_europe_member(identity, assignment):
            explicit_atlantic_ids.add(pid)
            set_region(pid, ATLANTIC_REGION_ID, ATLANTIC_REGION_NAME, "island_atlantic_europe_group")

    # 2) Source-feature family inheritance. Layer 8 split parts use suffixes
    # _2/_3/...; all those parts belong to one Admin-1 source feature and must
    # not drift into different regions merely because their centroids differ.
    families: dict[str, list[str]] = defaultdict(list)
    for pid, identity in identities.items():
        legacy = str(identity.get("legacy_id", ""))
        families[family_key(legacy)].append(pid)

    family_mismatch_before = 0
    family_correction_count = 0
    family_examples: list[dict[str, Any]] = []
    for key in sorted(families):
        members = families[key]
        if len(members) <= 1:
            continue
        regions_before = {(str(assignment_by_id[p].get("region_id", "")), str(assignment_by_id[p].get("region_name", ""))) for p in members}
        if len(regions_before) > 1:
            family_mismatch_before += 1

        # If any split part is in the explicit Atlantic group, the full source
        # feature belongs there. Otherwise largest geometry part is the anchor.
        if any(p in explicit_atlantic_ids for p in members):
            anchor_region = (ATLANTIC_REGION_ID, ATLANTIC_REGION_NAME)
            anchor_pid = next(p for p in members if p in explicit_atlantic_ids)
            reason = "island_family_inherits_atlantic_group"
        else:
            anchor_pid = max(members, key=lambda p: area_km2(geometries[p]))
            anchor_assignment = assignment_by_id[anchor_pid]
            anchor_region = (str(anchor_assignment.get("region_id", "")), str(anchor_assignment.get("region_name", "")))
            reason = "split_source_family_inherits_largest_part_region"

        corrected_here = 0
        for pid in members:
            before = str(assignment_by_id[pid].get("region_id", ""))
            set_region(pid, anchor_region[0], anchor_region[1], reason)
            if str(assignment_by_id[pid].get("region_id", "")) != before:
                family_correction_count += 1
                corrected_here += 1
        if corrected_here and len(family_examples) < 100:
            family_examples.append({
                "family_key": key,
                "anchor_province_id": anchor_pid,
                "anchor_name": identities[anchor_pid].get("name", ""),
                "anchor_region": anchor_region[1],
                "member_count": len(members),
                "corrected_member_count": corrected_here,
            })

    # 3) Recalculate counts only when a corrected region has an approved table
    # profile. For the new Atlantic group the profile is pending, so preserve
    # the existing numeric profile/target values instead of inventing one.
    corrected_ids = {str(x["province_id"]) for x in corrections}
    cell_changes: list[dict[str, Any]] = []
    atlantic_pending_count = 0
    small_island_one_count = 0

    for target in targets:
        pid = str(target["province_id"])
        assignment = assignment_by_id[pid]
        identity = identities[pid]
        old_count = int(target.get("target_cell_count", 1))
        target["region_id"] = str(assignment.get("region_id", ""))
        target["region_name"] = str(assignment.get("region_name", ""))
        target["region_assignment_confidence"] = str(assignment.get("confidence", ""))
        target["region_assignment_review"] = str(assignment.get("confidence", "")) == "review"
        target["source_feature_family_key"] = family_key(str(identity.get("legacy_id", "")))
        target["cross_sea_cell_merge_forbidden"] = True if len(families[target["source_feature_family_key"]]) > 1 else False

        region_name = str(assignment.get("region_name", ""))
        if region_name == ATLANTIC_REGION_NAME:
            target["island_region_profile_status"] = "PENDING_USER_CHOICE"
            target["profile_source"] = "preserved_previous_profile_until_atlantic_profile_choice"
            atlantic_pending_count += 1
            # Enforce only the already-agreed small-island rule using the
            # province's current target area. Do not change profile numbers.
            current_target_area = float(target.get("region_target_cell_area_km2", 0.0) or 0.0)
            if current_target_area > 0.0 and float(target.get("area_km2", 0.0)) <= current_target_area:
                target["target_cell_count"] = 1
                small_island_one_count += 1
        elif pid in corrected_ids and region_name in profiles:
            # Family/nearshore correction landed in an existing table region.
            is_family_piece = len(families[target["source_feature_family_key"]]) > 1
            new_count = recalc_from_profile(target, profiles[region_name], force_small_island_one=is_family_piece or is_scottish_nearshore(identity) or is_isle_of_wight(identity))
            target["profile_source"] = "regional_workbook_after_island_region_correction"
            if new_count == 1 and (is_family_piece or is_scottish_nearshore(identity) or is_isle_of_wight(identity)):
                small_island_one_count += 1

        new_count = int(target.get("target_cell_count", 1))
        if new_count != old_count:
            cell_changes.append({
                "province_id": pid,
                "legacy_id": identity.get("legacy_id", ""),
                "name": identity.get("name", ""),
                "region_name": region_name,
                "old_count": old_count,
                "new_count": new_count,
                "reason": "island_region_or_family_correction",
            })

    total_cells_before = int(targets_doc.get("total_target_cells", 0))
    total_cells_after = sum(int(t.get("target_cell_count", 1)) for t in targets)
    review_after = sum(1 for a in assignments if str(a.get("confidence", "")) == "review")

    out_assign = dict(assignments_doc)
    out_assign["format"] = "world_region_assignments_island_corrected/v2"
    out_assign["province_count"] = len(assignments)
    out_assign["island_logic"] = "family inheritance + explicit European Atlantic island group"
    out_assign["assignments"] = assignments

    out_target = dict(targets_doc)
    out_target["format"] = "world_province_cell_targets_island_corrected/v2"
    out_target["province_count"] = len(targets)
    out_target["total_target_cells"] = total_cells_after
    out_target["atlantic_region_profile_status"] = "PENDING_USER_CHOICE"
    out_target["provinces"] = targets

    report = {
        "schema_version": 1,
        "format": "world_island_logic_report/v2",
        "province_count": len(targets),
        "region_correction_count": len(corrections),
        "family_region_mismatch_count_before": family_mismatch_before,
        "family_member_correction_count": family_correction_count,
        "family_correction_examples": family_examples,
        "atlantic_europe_region": {
            "region_id": ATLANTIC_REGION_ID,
            "region_name": ATLANTIC_REGION_NAME,
            "province_piece_count": atlantic_pending_count,
            "profile_status": "PENDING_USER_CHOICE",
        },
        "small_island_one_cell_enforcement_count": small_island_one_count,
        "cell_count_changed_province_count": len(cell_changes),
        "cell_count_changes": cell_changes,
        "region_assignment_review_count_after": review_after,
        "total_target_cells_before": total_cells_before,
        "total_target_cells_after": total_cells_after,
        "region_corrections": corrections,
        "hard_fail": False,
    }

    outputs = ((OUT_ASSIGN, out_assign), (OUT_TARGET, out_target), (OUT_REPORT, report))
    if args.check:
        for path, value in outputs:
            expected = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                raise RuntimeError(f"--check mismatch: {path}")
    else:
        for path, value in outputs:
            write_json(path, value)

    print(
        "WORLD_ISLAND_LOGIC_OK",
        f"region_corrections={len(corrections)}",
        f"family_mismatches={family_mismatch_before}",
        f"family_member_corrections={family_correction_count}",
        f"atlantic_pieces={atlantic_pending_count}",
        f"cell_changes={len(cell_changes)}",
        f"review_after={review_after}",
        f"cells={total_cells_before}->{total_cells_after}",
    )


if __name__ == "__main__":
    main()
