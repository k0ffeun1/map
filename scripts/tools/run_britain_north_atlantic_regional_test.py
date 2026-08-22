#!/usr/bin/env python3
"""Run the Britain/North Atlantic regional builder with baseline-aware overlap validation.

SAFE Admin-1 contains a tiny amount of overlap already present in its source features.
A regrouping pass must preserve that baseline, not pretend it created the overlap.  This
wrapper keeps the original additive builder untouched and tightens the actual contract:
zero missing/extra land and zero *introduced* overlap beyond the SAFE source baseline.
"""
from __future__ import annotations

from typing import Any

from shapely.ops import unary_union

import build_britain_north_atlantic_regional_test as build


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
        # Backward-compatible field now means overlap introduced by regrouping.
        "overlap_ratio": introduced_overlap,
        "hard_validation_passed": (
            missing <= 1e-8
            and extra <= 1e-8
            and introduced_overlap <= 1e-8
        ),
    }


def main() -> None:
    build.validate_macro_coverage = validate_macro_coverage
    build.main()


if __name__ == "__main__":
    main()
