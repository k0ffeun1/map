#!/usr/bin/env python3
"""Robust Britain/North-Atlantic anti-spike runner.

This keeps the v1 detector/helpers but replaces only the final macro cleanup
transaction.  The authoritative coastline is verified through exact land-mask
coverage (symmetric-difference area), which is robust to harmless Shapely line
re-noding while still forbidding any land/water change.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from shapely.ops import unary_union

import run_britain_north_atlantic_regional_test as v1


def clean_macro_partition_v2(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source = {str(record["id"]): record["_geometry"] for record in records}
    land = unary_union(list(source.values()))
    if not land.is_valid:
        land = land.buffer(0)

    # Resolve inherited SAFE-source overlap once into a real, gap-free partition.
    base = v1._partition_from_network(land, [geometry.boundary for geometry in source.values()], source)
    before_adjacency = v1._adjacency(base)
    before_union = unary_union(list(base.values()))

    banned: set[str] = set()
    changed_pairs: Counter[str] = Counter()
    removed = 0
    points_removed = 0
    skipped = 0
    for _step in range(v1.MACRO_TRANSFER_LIMIT):
        candidate = v1._next_macro_candidate(base, banned)
        if candidate is None:
            break
        pair, sub, key = candidate
        if v1._apply_pocket_transfer(base, land, pair, sub):
            removed += 1
            points_removed += max(0, len(sub) - 2)
            changed_pairs[pair] += 1
        else:
            banned.add(key)
            skipped += 1
    else:
        raise RuntimeError("macro anti-spike transfer limit reached")

    after_union = unary_union(list(base.values()))
    after_adjacency = v1._adjacency(base)
    coverage_delta = before_union.symmetric_difference(after_union).area
    if coverage_delta > 1.0e-8:
        raise RuntimeError(f"macro anti-spike cleanup changed total land coverage: {coverage_delta}")
    if before_adjacency != after_adjacency:
        raise RuntimeError(
            "macro anti-spike cleanup changed province adjacency: "
            f"missing={sorted(before_adjacency-after_adjacency)} added={sorted(after_adjacency-before_adjacency)}"
        )

    final_chains = v1._shared_chains(base)
    v1.MACRO_CLEANUP_STATS.update({
        "shared_components": len(final_chains),
        "changed_components": len(changed_pairs),
        "detours_removed": removed,
        "points_removed": points_removed,
        "skipped_candidates": skipped,
        "remaining_candidates": v1._count_remaining_candidates(base, banned),
        "adjacency_preserved": True,
        "outer_boundary_preserved": True,
        "land_mask_symmetric_difference_area": coverage_delta,
    })

    for record in records:
        gid = str(record["id"])
        geometry = base[gid]
        point = geometry.representative_point()
        record["_geometry"] = geometry
        record["area_km2"] = round(v1.build.s.area_km2(geometry), 4)
        record["label_point"] = [round(float(point.x), 6), round(float(point.y), 6)]
        record["bbox"] = [round(float(x), 6) for x in geometry.bounds]
        record["parts"] = v1.build.s.shape_parts_payload(geometry)
    return records


def main() -> None:
    # build_macro_provinces_cleaned resolves this global at call time.
    v1._clean_macro_partition = clean_macro_partition_v2
    v1.main()


if __name__ == "__main__":
    main()
