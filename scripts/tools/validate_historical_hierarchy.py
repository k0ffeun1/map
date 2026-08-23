#!/usr/bin/env python3
"""Strict validator for the historical territorial hierarchy.

Project invariant:
    assets/provinces.json (layer 8) is the ONLY geometry/source level.

The hierarchy is authored bottom-up only:
    Province -> Region -> Superregion -> Macroregion -> Major Region.

Every authored object must have an external source and an explicit historical
or geographical basis. A visible gap is preferred to a convenient but false
territorial union.

Usage from repository root:
    python scripts/tools/validate_historical_hierarchy.py

Exit code 0 = valid, 1 = at least one hard structural/historical error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
HIERARCHY_PATH = ROOT / "assets" / "historical_hierarchy.json"
PROVINCES_PATH = ROOT / "assets" / "provinces.json"

TIER_ORDER = ("region", "superregion", "macroregion", "major_region")
EXPECTED_CHILD = {
    "superregion": "region",
    "macroregion": "superregion",
    "major_region": "macroregion",
}
FORBIDDEN_GEOMETRY_FIELDS = {
    "rings", "ring", "polygon", "polygons", "geometry", "bbox", "bounds",
    "coordinates", "points", "centroid", "center", "seed",
}
# These phrases indicate that convenience, rather than an external historical
# or geographical fact, is being used as the reason for a grouping.
FORBIDDEN_CONVENIENCE_TERMS = (
    "game grouping",
    "game geographic",
    "project grouping",
    "explicitly approved",
    "game-level grouping",
    "for gameplay",
    "game convenience",
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def country_prefix(province_id: str) -> str:
    return province_id.split("__", 1)[0] if "__" in province_id else ""


def is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_sources(
    tier: str,
    group_id: str,
    group: dict[str, Any],
    errors: list[str],
) -> None:
    sources = group.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append(f"{tier}/{group_id} has no internet sources")
        return
    for pos, source in enumerate(sources):
        value = str(source).strip()
        if not is_http_url(value):
            errors.append(
                f"{tier}/{group_id} sources[{pos}] is not a valid http/https URL: {value!r}"
            )


def validate_basis(
    tier: str,
    group_id: str,
    group: dict[str, Any],
    errors: list[str],
) -> None:
    field = "historical_basis" if tier == "region" else "basis"
    basis = str(group.get(field, "")).strip()
    if not basis:
        errors.append(f"{tier}/{group_id} has no {field}")
        return
    lowered = basis.lower()
    for term in FORBIDDEN_CONVENIENCE_TERMS:
        if term in lowered:
            errors.append(
                f"{tier}/{group_id} uses convenience-based basis term {term!r}; "
                "external historical/geographical evidence is required"
            )


def main() -> int:
    errors: list[str] = []

    hierarchy = load_json(HIERARCHY_PATH)
    province_data = load_json(PROVINCES_PATH)

    if hierarchy.get("source_of_truth_layer") != 8:
        errors.append("source_of_truth_layer must be exactly 8")
    if hierarchy.get("strict") is not True:
        errors.append("historical_hierarchy.json must use strict=true")
    if hierarchy.get("province_source") != "res://assets/provinces.json":
        errors.append("province_source must be res://assets/provinces.json")

    raw_cells = province_data.get("cells", [])
    if not isinstance(raw_cells, list) or not raw_cells:
        errors.append("assets/provinces.json has no non-empty 'cells' array")
        raw_cells = []

    layer8_cell_ids = {
        str(cell.get("id", ""))
        for cell in raw_cells
        if isinstance(cell, dict) and str(cell.get("id", ""))
    }

    tiers = hierarchy.get("tiers", {})
    if not isinstance(tiers, dict):
        errors.append("'tiers' must be an object")
        tiers = {}

    groups_by_tier: dict[str, dict[str, dict[str, Any]]] = {}
    for tier in TIER_ORDER:
        tier_data = tiers.get(tier)
        if not isinstance(tier_data, dict):
            errors.append(f"missing required tier: {tier}")
            groups_by_tier[tier] = {}
            continue

        raw_groups = tier_data.get("groups", [])
        if not isinstance(raw_groups, list):
            errors.append(f"{tier}.groups must be an array")
            raw_groups = []

        index: dict[str, dict[str, Any]] = {}
        for pos, raw_group in enumerate(raw_groups):
            if not isinstance(raw_group, dict):
                errors.append(f"{tier}.groups[{pos}] must be an object")
                continue
            group_id = str(raw_group.get("id", "")).strip()
            if not group_id:
                errors.append(f"{tier}.groups[{pos}] has empty id")
                continue
            if group_id in index:
                errors.append(f"duplicate group id on {tier}: {group_id}")
                continue

            forbidden = FORBIDDEN_GEOMETRY_FIELDS.intersection(raw_group)
            if forbidden:
                errors.append(
                    f"{tier}/{group_id} contains forbidden custom geometry fields: "
                    + ", ".join(sorted(forbidden))
                )

            validate_sources(tier, group_id, raw_group, errors)
            validate_basis(tier, group_id, raw_group, errors)
            index[group_id] = raw_group
        groups_by_tier[tier] = index

    # Region is the only tier allowed to reference layer-8 province IDs.
    region_owner: dict[str, str] = {}
    all_region_province_ids: set[str] = set()

    for region_id, group in groups_by_tier.get("region", {}).items():
        if "children" in group:
            errors.append(f"region/{region_id} must not contain children")
        province_ids = group.get("province_ids")
        if not isinstance(province_ids, list) or not province_ids:
            errors.append(f"region/{region_id} must contain non-empty province_ids")
            continue

        countries: set[str] = set()
        local_seen: set[str] = set()
        for raw_pid in province_ids:
            pid = str(raw_pid).strip()
            if not pid:
                errors.append(f"region/{region_id} contains an empty province_id")
                continue
            if pid in local_seen:
                errors.append(f"region/{region_id} repeats province_id {pid}")
            local_seen.add(pid)

            previous = region_owner.get(pid)
            if previous is not None and previous != region_id:
                errors.append(
                    f"layer-8 province {pid} belongs to two regions: {previous}, {region_id}"
                )
            region_owner[pid] = region_id
            all_region_province_ids.add(pid)
            prefix = country_prefix(pid)
            if prefix:
                countries.add(prefix)

        if len(countries) > 1:
            errors.append(
                f"region/{region_id} mixes countries ({', '.join(sorted(countries))}); "
                "a Region must not silently swallow foreign provinces"
            )

    # A base province id may have multiple geometry pieces with _2/_3 suffixes.
    def source_id_exists(base_id: str) -> bool:
        if base_id in layer8_cell_ids:
            return True
        prefix = base_id + "_"
        return any(cell_id.startswith(prefix) for cell_id in layer8_cell_ids)

    for pid in sorted(all_region_province_ids):
        if not source_id_exists(pid):
            errors.append(f"province_id referenced by hierarchy does not exist in layer 8: {pid}")

    # Upper tiers may use only direct children from the immediately lower tier.
    # A child may have only one parent on each tier.
    for tier, child_tier in EXPECTED_CHILD.items():
        child_index = groups_by_tier.get(child_tier, {})
        child_owner: dict[str, str] = {}
        for group_id, group in groups_by_tier.get(tier, {}).items():
            if "province_ids" in group:
                errors.append(f"{tier}/{group_id} illegally references province_ids directly")
            actual_child_tier = str(group.get("child_tier", ""))
            if actual_child_tier != child_tier:
                errors.append(
                    f"{tier}/{group_id} child_tier must be {child_tier}, got {actual_child_tier!r}"
                )
            children = group.get("children")
            if not isinstance(children, list) or not children:
                errors.append(f"{tier}/{group_id} must contain non-empty children")
                continue
            if tier == "superregion" and len(children) < 2:
                errors.append(
                    f"superregion/{group_id} contains {len(children)} region(s); minimum is 2"
                )

            local_seen: set[str] = set()
            for raw_child in children:
                child = str(raw_child).strip()
                if not child:
                    errors.append(f"{tier}/{group_id} contains an empty child id")
                    continue
                if child in local_seen:
                    errors.append(f"{tier}/{group_id} repeats child {child}")
                local_seen.add(child)
                if child not in child_index:
                    errors.append(f"{tier}/{group_id} references missing {child_tier}: {child}")
                    continue
                previous = child_owner.get(child)
                if previous is not None and previous != group_id:
                    errors.append(
                        f"{child_tier}/{child} has two {tier} parents: {previous}, {group_id}"
                    )
                child_owner[child] = group_id

    # Resolve each upper group down to layer 8. This catches cycles and empty shells.
    cache: dict[tuple[str, str], set[str]] = {}

    def resolve(
        tier: str,
        group_id: str,
        stack: tuple[tuple[str, str], ...] = (),
    ) -> set[str]:
        key = (tier, group_id)
        if key in cache:
            return set(cache[key])
        if key in stack:
            errors.append(
                "hierarchy cycle: " + " -> ".join(f"{t}/{g}" for t, g in (*stack, key))
            )
            return set()
        group = groups_by_tier.get(tier, {}).get(group_id)
        if group is None:
            return set()
        if tier == "region":
            result = {str(pid) for pid in group.get("province_ids", []) if str(pid)}
        else:
            child_tier = str(group.get("child_tier", ""))
            result: set[str] = set()
            for child in group.get("children", []):
                result.update(resolve(child_tier, str(child), (*stack, key)))
        cache[key] = set(result)
        return result

    for tier in TIER_ORDER:
        for group_id in groups_by_tier.get(tier, {}):
            if not resolve(tier, group_id):
                errors.append(f"{tier}/{group_id} resolves to zero layer-8 provinces")

    matched_layer8_cells = 0
    for cell_id in layer8_cell_ids:
        if any(cell_id == pid or cell_id.startswith(pid + "_") for pid in all_region_province_ids):
            matched_layer8_cells += 1

    print("Historical hierarchy validation")
    print(f"  source layer: 8 ({PROVINCES_PATH.relative_to(ROOT)})")
    print(f"  layer-8 geometry pieces: {len(layer8_cell_ids)}")
    print(f"  authored Region province IDs: {len(all_region_province_ids)}")
    print(f"  matched layer-8 geometry pieces: {matched_layer8_cells}")
    for tier in TIER_ORDER:
        print(f"  {tier}: {len(groups_by_tier.get(tier, {}))} groups")

    if errors:
        print("\nERRORS:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(f"\nFAILED: {len(errors)} hard error(s)", file=sys.stderr)
        return 1

    print("\nPASS: strict source-backed hierarchy is structurally consistent with layer 8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
