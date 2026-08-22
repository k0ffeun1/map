#!/usr/bin/env python3
"""Robust Britain/North-Atlantic anti-spike runner.

There are two different artifact classes in the regional political geometry:

1. thin out-and-back detours on a boundary shared by two gameplay provinces;
2. equally thin land needles on the *outer coastline*.

The first class is fixed by atomically transferring the tiny pocket from one
province to its neighbour (the land mask stays identical).  The second class
cannot be fixed while requiring an identical land mask: by definition the bad
needle is part of the source coastline.  For coast artifacts this runner trims
only extremely thin, high-stretch land protrusions and records the exact amount
of removed land.  Bays/inlets are never filled, no new land may appear, province
adjacency must remain unchanged, and small island parts are excluded.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from shapely.geometry import Polygon
from shapely.ops import unary_union

import run_britain_north_atlantic_regional_test as v1

# Coastal cleanup is deliberately much stricter than internal-boundary cleanup.
# Around Britain one world pixel is roughly 2.5-3 km.  Effective width is the
# ribbon-width estimate used by the existing detector, so 0.24 targets only
# almost line-like needles rather than normal capes/peninsulas.
COAST_MAX_EFFECTIVE_WIDTH = 0.24
COAST_MIN_STRETCH = 2.15
COAST_MIN_EXCESS = 0.80
COAST_MIN_PART_AREA_KM2 = 250.0
COAST_MAX_SINGLE_REMOVAL_KM2 = 35.0
COAST_MAX_SINGLE_REMOVAL_FRACTION = 0.0030
COAST_MAX_TOTAL_REMOVAL_RATIO = 8.0e-5
COAST_OWNER_SHARE = 0.92
COAST_MAX_PASSES_PER_PART = 12
COAST_AREA_EPS = 1.0e-8

COAST_CLEANUP_STATS: dict[str, Any] = {
    "detours_removed": 0,
    "points_removed": 0,
    "changed_province_count": 0,
    "removed_area_world": 0.0,
    "removed_area_km2": 0.0,
    "added_area_world": 0.0,
    "remaining_candidates": 0,
    "details": [],
}


def _find_best_coastal_detour(points: list[tuple[float, float]]) -> tuple[int, int] | None:
    """Return the strongest line-like exterior-ring land detour.

    We reuse the already-tested path/chord/area metrics but use stricter coastal
    thresholds.  Ring wrap-around at the arbitrary first vertex is intentionally
    not forced; a later regeneration can move the start vertex, while avoiding a
    risky whole-ring rewrite is more important than catching every candidate in
    one pass.
    """
    best: tuple[float, int, int] | None = None
    n = len(points)
    for i in range(0, n - 2):
        running = 0.0
        for j in range(i + 1, n):
            running += v1.math.dist(points[j - 1], points[j])
            if running > v1.DETOUR_MAX_PATH:
                break
            if j <= i + 1:
                continue
            metrics = v1._candidate_metrics(points, i, j)
            if metrics is None:
                continue
            _path, stretch, excess, width = metrics
            if stretch < COAST_MIN_STRETCH:
                continue
            if excess < COAST_MIN_EXCESS:
                continue
            if width > COAST_MAX_EFFECTIVE_WIDTH:
                continue
            severity = (stretch - 1.0) * excess * (
                1.0 + (COAST_MAX_EFFECTIVE_WIDTH - width) / COAST_MAX_EFFECTIVE_WIDTH
            )
            if best is None or severity > best[0]:
                best = (severity, i, j)
    return None if best is None else (best[1], best[2])


def _part_has_coastal_candidate(part: Polygon) -> bool:
    if v1.build.s.area_km2(part) < COAST_MIN_PART_AREA_KM2:
        return False
    points = [(float(x), float(y)) for x, y in part.exterior.coords]
    return _find_best_coastal_detour(points) is not None


def _trim_one_coastal_spike(part: Polygon) -> tuple[Any, dict[str, Any] | None]:
    """Trim one exterior land needle from a polygon part, or return it unchanged."""
    part_area_km2 = v1.build.s.area_km2(part)
    if part_area_km2 < COAST_MIN_PART_AREA_KM2:
        return part, None

    points = [(float(x), float(y)) for x, y in part.exterior.coords]
    hit = _find_best_coastal_detour(points)
    if hit is None:
        return part, None
    i, j = hit
    sub = points[i : j + 1]
    metrics = v1._candidate_metrics(points, i, j)
    if metrics is None:
        return part, None
    path, stretch, excess, width = metrics

    pocket: Any = Polygon(sub)
    if not pocket.is_valid:
        pocket = pocket.buffer(0)
    if pocket.is_empty or pocket.area <= COAST_AREA_EPS:
        return part, None

    land_inside = pocket.intersection(part)
    owner_share = land_inside.area / max(pocket.area, COAST_AREA_EPS)
    # A narrow bay/inlet makes the closed pocket mostly water.  We only remove
    # protruding land, never fill water, so reject those candidates.
    if owner_share < COAST_OWNER_SHARE:
        return part, None

    removed = land_inside
    removed_km2 = v1.build.s.area_km2(removed)
    if removed_km2 <= 0.0 or removed_km2 > COAST_MAX_SINGLE_REMOVAL_KM2:
        return part, None
    if removed.area / max(part.area, COAST_AREA_EPS) > COAST_MAX_SINGLE_REMOVAL_FRACTION:
        return part, None

    before_parts = len(v1._polygon_parts(part))
    cleaned = part.difference(removed)
    if not cleaned.is_valid:
        cleaned = cleaned.buffer(0)
    if cleaned.is_empty:
        return part, None
    after_parts = v1._polygon_parts(cleaned)
    # Never cut a real isthmus/corridor and fragment a province.
    if len(after_parts) != before_parts or len(after_parts) != 1:
        return part, None

    cleaned_part = after_parts[0]
    added = cleaned_part.difference(part).area
    actual_removed = part.difference(cleaned_part).area
    if added > COAST_AREA_EPS or actual_removed <= COAST_AREA_EPS:
        return part, None
    # The edit must materially shorten the outline; otherwise it is numerical
    # churn rather than the long visual needle we are trying to remove.
    if part.length - cleaned_part.length < 0.25:
        return part, None

    return cleaned_part, {
        "path": path,
        "stretch": stretch,
        "excess": excess,
        "effective_width": width,
        "points_removed": max(0, len(sub) - 2),
        "removed_area_world": actual_removed,
        "removed_area_km2": v1.build.s.area_km2(part.difference(cleaned_part)),
        "owner_share": owner_share,
        "bbox": [float(x) for x in removed.bounds],
    }


def _clean_coastal_spikes(geometries: dict[str, Any]) -> dict[str, Any]:
    changed_ids: set[str] = set()
    details: list[dict[str, Any]] = []
    removed_world = 0.0
    removed_km2 = 0.0
    points_removed = 0
    detours_removed = 0

    for gid in sorted(geometries):
        original = geometries[gid]
        cleaned_parts: list[Any] = []
        province_changed = False
        for original_part in v1._polygon_parts(original):
            current: Any = original_part
            for _pass in range(COAST_MAX_PASSES_PER_PART):
                next_part, change = _trim_one_coastal_spike(current)
                if change is None:
                    break
                current = next_part
                province_changed = True
                detours_removed += 1
                points_removed += int(change["points_removed"])
                removed_world += float(change["removed_area_world"])
                removed_km2 += float(change["removed_area_km2"])
                details.append({"province_id": gid, **change})
            cleaned_parts.extend(v1._polygon_parts(current))

        if province_changed:
            merged = unary_union(cleaned_parts)
            if not merged.is_valid:
                merged = merged.buffer(0)
            if merged.is_empty:
                raise RuntimeError(f"coastal cleanup emptied province {gid}")
            geometries[gid] = merged
            changed_ids.add(gid)

    remaining = 0
    for geometry in geometries.values():
        for part in v1._polygon_parts(geometry):
            if _part_has_coastal_candidate(part):
                remaining += 1

    stats = {
        "detours_removed": detours_removed,
        "points_removed": points_removed,
        "changed_province_count": len(changed_ids),
        "removed_area_world": removed_world,
        "removed_area_km2": removed_km2,
        "remaining_candidates": remaining,
        "details": details,
    }
    COAST_CLEANUP_STATS.update(stats)
    return stats


def clean_macro_partition_v2(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source = {str(record["id"]): record["_geometry"] for record in records}
    land = unary_union(list(source.values()))
    if not land.is_valid:
        land = land.buffer(0)

    # Resolve inherited SAFE-source overlap once into a real, gap-free partition.
    base = v1._partition_from_network(land, [geometry.boundary for geometry in source.values()], source)
    before_adjacency = v1._adjacency(base)
    before_union = unary_union(list(base.values()))

    # Pass A: internal shared-boundary spike transfer.  This must preserve land.
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

    after_internal_union = unary_union(list(base.values()))
    internal_delta = before_union.symmetric_difference(after_internal_union).area
    if internal_delta > 1.0e-8:
        raise RuntimeError(f"internal anti-spike cleanup changed land coverage: {internal_delta}")

    # Pass B: outer-coast land needles.  This intentionally removes only the
    # tiny source-geometry artifact itself; no land may be added.
    coastal = _clean_coastal_spikes(base)

    after_union = unary_union(list(base.values()))
    after_adjacency = v1._adjacency(base)
    added_area = after_union.difference(before_union).area
    removed_area = before_union.difference(after_union).area
    removal_ratio = removed_area / max(before_union.area, COAST_AREA_EPS)
    if added_area > 1.0e-8:
        raise RuntimeError(f"coastal cleanup added land: {added_area}")
    if removal_ratio > COAST_MAX_TOTAL_REMOVAL_RATIO:
        raise RuntimeError(
            f"coastal cleanup removed too much land: ratio={removal_ratio} "
            f"limit={COAST_MAX_TOTAL_REMOVAL_RATIO}"
        )
    if before_adjacency != after_adjacency:
        raise RuntimeError(
            "anti-spike cleanup changed province adjacency: "
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
        # The outer line is intentionally allowed to change only through the
        # constrained coastal cleanup below.
        "outer_boundary_preserved": coastal["detours_removed"] == 0,
        "outer_boundary_changed_only_by_coastal_cleanup": True,
        "land_mask_symmetric_difference_area": before_union.symmetric_difference(after_union).area,
        "coastal_detours_removed": int(coastal["detours_removed"]),
        "coastal_points_removed": int(coastal["points_removed"]),
        "coastal_changed_province_count": int(coastal["changed_province_count"]),
        "coastal_removed_area_world": removed_area,
        "coastal_removed_area_km2": float(coastal["removed_area_km2"]),
        "coastal_added_area_world": added_area,
        "coastal_removal_ratio": removal_ratio,
        "coastal_remaining_candidates": int(coastal["remaining_candidates"]),
        "coastal_details": coastal["details"],
    })

    for record in records:
        gid = str(record["id"])
        geometry = base[gid]
        point = geometry.representative_point()
        record["_geometry"] = geometry
        record["area_km2"] = round(v1.build.s.area_km2(geometry), 4)
        record["label_point"] = [round(float(point.x), 6) for point in [point]][0:0]  # replaced below
        record["label_point"] = [round(float(point.x), 6), round(float(point.y), 6)]
        record["bbox"] = [round(float(x), 6) for x in geometry.bounds]
        record["parts"] = v1.build.s.shape_parts_payload(geometry)
    return records


def validate_macro_coverage_v2(
    records: list[dict[str, Any]],
    assignment: dict[str, str],
    geometry_by_id: dict[str, Any],
) -> dict[str, Any]:
    source_geometries = [geometry_by_id[pid] for pid in assignment]
    source_union = unary_union(source_geometries)
    macro_geometries = [record["_geometry"] for record in records]
    macro_union = unary_union(macro_geometries)
    source_area = max(source_union.area, 1.0e-9)

    missing = source_union.difference(macro_union).area / source_area
    extra = macro_union.difference(source_union).area / source_area
    source_raw_overlap = max(0.0, sum(g.area for g in source_geometries) - source_union.area) / source_area
    macro_raw_overlap = max(0.0, sum(g.area for g in macro_geometries) - macro_union.area) / source_area
    introduced_overlap = max(0.0, macro_raw_overlap - source_raw_overlap)
    expected_cleanup_missing = float(v1.MACRO_CLEANUP_STATS.get("coastal_removed_area_world", 0.0)) / source_area
    allowed_missing = expected_cleanup_missing + 1.0e-8

    return {
        "coverage_missing_ratio": missing,
        "coverage_extra_ratio": extra,
        "source_baseline_overlap_ratio": source_raw_overlap,
        "macro_raw_overlap_ratio": macro_raw_overlap,
        "introduced_overlap_ratio": introduced_overlap,
        "overlap_ratio": introduced_overlap,
        "coastal_cleanup_expected_missing_ratio": expected_cleanup_missing,
        "coastal_cleanup_allowed_missing_ratio": allowed_missing,
        "hard_validation_passed": (
            missing <= allowed_missing
            and extra <= 1.0e-8
            and introduced_overlap <= 1.0e-8
        ),
        "anti_spike_cleanup": dict(v1.MACRO_CLEANUP_STATS),
    }


def main() -> None:
    # build_macro_provinces_cleaned and v1.main resolve these globals at call time.
    v1._clean_macro_partition = clean_macro_partition_v2
    v1.validate_macro_coverage = validate_macro_coverage_v2
    v1.main()
    print("BRITAIN_COAST_ANTI_SPIKE=", json.dumps(COAST_CLEANUP_STATS, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
