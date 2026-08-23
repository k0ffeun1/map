#!/usr/bin/env python3
"""Strict validator for the current historical Region layer (X).

Project invariant:
    assets/provinces.json (layer 8) is the ONLY geometry/source level.

Current stage:
    Province -> Region

C/V/B are intentionally absent until Region is approved. A visible gap is
preferred to a convenient but historically false grouping.

Usage from repository root:
    python scripts/tools/validate_historical_hierarchy.py

Exit code 0 = valid, 1 = at least one hard structural/source error.
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

FORBIDDEN_GEOMETRY_FIELDS = {
    "rings", "ring", "polygon", "polygons", "geometry", "bbox", "bounds",
    "coordinates", "points", "centroid", "center", "seed",
}
FORBIDDEN_UPPER_TIERS = {"zone", "superregion", "macroregion", "major_region"}
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


def source_id_exists(base_id: str, layer8_cell_ids: set[str]) -> bool:
    """A logical province may be represented by multiple _2/_3 geometry pieces."""
    if base_id in layer8_cell_ids:
        return True
    prefix = base_id + "_"
    return any(cell_id.startswith(prefix) for cell_id in layer8_cell_ids)


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    hierarchy = load_json(HIERARCHY_PATH)
    province_data = load_json(PROVINCES_PATH)

    if hierarchy.get("source_of_truth_layer") != 8:
        errors.append("source_of_truth_layer must be exactly 8")
    if hierarchy.get("strict") is not True:
        errors.append("historical_hierarchy.json must use strict=true")
    if hierarchy.get("stage") != "region_only":
        errors.append("current historical hierarchy stage must be region_only")
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

    if "region" not in tiers or not isinstance(tiers.get("region"), dict):
        errors.append("missing required tier: region")
        region_tier: dict[str, Any] = {}
    else:
        region_tier = tiers["region"]

    for forbidden_tier in sorted(FORBIDDEN_UPPER_TIERS.intersection(tiers)):
        errors.append(
            f"premature tier {forbidden_tier!r} is forbidden while stage=region_only; "
            "C/V/B must be rebuilt later from approved Regions"
        )

    raw_regions = region_tier.get("groups", [])
    if not isinstance(raw_regions, list) or not raw_regions:
        errors.append("region.groups must be a non-empty array")
        raw_regions = []

    region_ids: set[str] = set()
    province_owner: dict[str, str] = {}
    all_region_province_ids: set[str] = set()
    region_sizes: list[tuple[str, int]] = []
    country_stats: dict[str, dict[str, int]] = {}

    for pos, raw_region in enumerate(raw_regions):
        if not isinstance(raw_region, dict):
            errors.append(f"region.groups[{pos}] must be an object")
            continue

        region_id = str(raw_region.get("id", "")).strip()
        if not region_id:
            errors.append(f"region.groups[{pos}] has empty id")
            continue
        if region_id in region_ids:
            errors.append(f"duplicate Region id: {region_id}")
            continue
        region_ids.add(region_id)

        forbidden = FORBIDDEN_GEOMETRY_FIELDS.intersection(raw_region)
        if forbidden:
            errors.append(
                f"region/{region_id} contains forbidden custom geometry fields: "
                + ", ".join(sorted(forbidden))
            )
        if "children" in raw_region:
            errors.append(f"region/{region_id} must reference province_ids, not children")

        basis = str(raw_region.get("historical_basis", "")).strip()
        if not basis:
            errors.append(f"region/{region_id} has no historical_basis")
        else:
            lowered = basis.lower()
            for term in FORBIDDEN_CONVENIENCE_TERMS:
                if term in lowered:
                    errors.append(
                        f"region/{region_id} uses convenience-based basis term {term!r}"
                    )

        sources = raw_region.get("sources")
        if not isinstance(sources, list) or not sources:
            errors.append(f"region/{region_id} has no internet sources")
        else:
            for source_pos, source in enumerate(sources):
                value = str(source).strip()
                if not is_http_url(value):
                    errors.append(
                        f"region/{region_id} sources[{source_pos}] is not a valid http/https URL: {value!r}"
                    )

        province_ids = raw_region.get("province_ids")
        if not isinstance(province_ids, list) or not province_ids:
            errors.append(f"region/{region_id} must contain non-empty province_ids")
            continue

        local_seen: set[str] = set()
        countries: set[str] = set()
        for raw_pid in province_ids:
            pid = str(raw_pid).strip()
            if not pid:
                errors.append(f"region/{region_id} contains an empty province_id")
                continue
            if pid in local_seen:
                errors.append(f"region/{region_id} repeats province_id {pid}")
            local_seen.add(pid)

            previous = province_owner.get(pid)
            if previous is not None and previous != region_id:
                errors.append(
                    f"layer-8 province {pid} belongs to two Regions: {previous}, {region_id}"
                )
            province_owner[pid] = region_id
            all_region_province_ids.add(pid)

            prefix = country_prefix(pid)
            if prefix:
                countries.add(prefix)

        if len(countries) > 1:
            errors.append(
                f"region/{region_id} mixes countries ({', '.join(sorted(countries))}); "
                "foreign provinces may never be swallowed into a historical Region"
            )

        size = len(local_seen)
        region_sizes.append((region_id, size))
        for country in countries:
            stats = country_stats.setdefault(country, {"regions": 0, "provinces": 0})
            stats["regions"] += 1
            stats["provinces"] += size

        # 3-4 is a target average, not a historical hard rule.
        if size == 1:
            warnings.append(f"region/{region_id}: 1 province (allowed exception/fallback)")
        elif size > 5:
            warnings.append(f"region/{region_id}: {size} provinces (allowed source-backed exception)")

    for pid in sorted(all_region_province_ids):
        if not source_id_exists(pid, layer8_cell_ids):
            errors.append(f"province_id referenced by Region does not exist in layer 8: {pid}")

    matched_layer8_cells = 0
    for cell_id in layer8_cell_ids:
        if any(cell_id == pid or cell_id.startswith(pid + "_") for pid in all_region_province_ids):
            matched_layer8_cells += 1

    total_regions = len(region_sizes)
    total_province_ids = sum(size for _, size in region_sizes)
    avg_size = total_province_ids / total_regions if total_regions else 0.0

    print("Historical Region layer validation")
    print(f"  stage: region_only (X)")
    print(f"  source layer: 8 ({PROVINCES_PATH.relative_to(ROOT)})")
    print(f"  layer-8 geometry pieces: {len(layer8_cell_ids)}")
    print(f"  Regions: {total_regions}")
    print(f"  authored logical layer-8 province IDs: {len(all_region_province_ids)}")
    print(f"  matched layer-8 geometry pieces: {matched_layer8_cells}")
    print(f"  average provinces per Region: {avg_size:.2f}")

    for country in sorted(country_stats):
        stats = country_stats[country]
        country_avg = stats["provinces"] / stats["regions"] if stats["regions"] else 0.0
        print(
            f"  {country}: {stats['regions']} Regions, "
            f"{stats['provinces']} province IDs, avg={country_avg:.2f}"
        )

    if warnings:
        print("\nWARNINGS (historically allowed size exceptions):")
        for warning in warnings:
            print(f"  - {warning}")

    if errors:
        print("\nERRORS:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(f"\nFAILED: {len(errors)} hard error(s)", file=sys.stderr)
        return 1

    print("\nPASS: X Region layer is structurally consistent with layer 8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
