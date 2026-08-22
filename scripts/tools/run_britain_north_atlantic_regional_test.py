#!/usr/bin/env python3
"""Run the Britain/North Atlantic regional builder with final regional refinements.

The base rules stay intact. This wrapper applies additive regional refinements in memory
before calling the builder, then validates regrouping against the SAFE Admin-1 baseline.
No existing world/Layer-8 geometry is rewritten.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shapely.ops import unary_union

import build_britain_north_atlantic_regional_test as build

SCOTLAND_REFINEMENT_PATH = (
    Path(__file__).resolve().parents[2]
    / "assets" / "game_data" / "britain_north_atlantic_scotland_refinement.json"
)
_BASE_READ_JSON = build.read_json


def read_json_with_refinements(path: Path) -> dict[str, Any]:
    doc = _BASE_READ_JSON(path)
    if path.resolve() != build.RULES_PATH.resolve():
        return doc

    refinement = json.loads(SCOTLAND_REFINEMENT_PATH.read_text(encoding="utf-8"))
    if refinement.get("format") != "britain_north_atlantic_scotland_refinement/v1":
        raise RuntimeError("unexpected Scotland refinement format")
    replacement = refinement.get("replace_scotland_gameplay_provinces", [])
    if not isinstance(replacement, list) or len(replacement) != 10:
        raise RuntimeError("Scotland refinement must contain exactly 10 gameplay provinces")

    old = doc.get("gameplay_provinces", [])
    non_scotland = [
        item for item in old
        if isinstance(item, dict) and str(item.get("territory", "")) != "scotland"
    ]
    doc["gameplay_provinces"] = replacement + non_scotland
    return doc


def validate_macro_coverage(
    records: list[dict[str, Any]],
    assignment: dict[str, str],
    geometry_by_id: dict[str, Any],
) -> dict[str, Any]:
    source_geometries = [geometry_by_id[pid] for pid in assignment]
    source_union = unary_union(source_geometries)
    macro_geometries = [record["_geometry"] for record in records]
    macro_union = unary_union(macro_geometries)
    source_area = max(source_union.area, 1e-9)

    missing = source_union.difference(macro_union).area / source_area
    extra = macro_union.difference(source_union).area / source_area
    source_raw_overlap = max(0.0, sum(g.area for g in source_geometries) - source_union.area) / source_area
    macro_raw_overlap = max(0.0, sum(g.area for g in macro_geometries) - macro_union.area) / source_area
    introduced_overlap = max(0.0, macro_raw_overlap - source_raw_overlap)

    return {
        "coverage_missing_ratio": missing,
        "coverage_extra_ratio": extra,
        "source_baseline_overlap_ratio": source_raw_overlap,
        "macro_raw_overlap_ratio": macro_raw_overlap,
        "introduced_overlap_ratio": introduced_overlap,
        "overlap_ratio": introduced_overlap,
        "hard_validation_passed": (
            missing <= 1e-8
            and extra <= 1e-8
            and introduced_overlap <= 1e-8
        ),
    }


def main() -> None:
    build.read_json = read_json_with_refinements
    build.validate_macro_coverage = validate_macro_coverage
    build.main()


if __name__ == "__main__":
    main()
