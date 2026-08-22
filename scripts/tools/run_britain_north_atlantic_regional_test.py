#!/usr/bin/env python3
"""Run the Britain/North Atlantic regional builder with final regional refinements.

Besides the Scotland gameplay regrouping this wrapper performs a topology-aware
anti-spike pass on Britain/North-Atlantic political boundaries.

The macro pass never edits the authoritative outer land/coast boundary.  It first
normalizes inherited SAFE-source overlap into a true partition, then detects thin
out-and-back detours only on a boundary shared by exactly two gameplay provinces.
Each accepted detour forms a tiny closed pocket.  The pocket is atomically moved
from its current owner to the neighbour, so A+B, the coastline, coverage and the
neighbour graph stay invariant.

The same detector is wrapped around Stage-6 cell-boundary cleanup for this regional
build. Existing world/Layer-8 geometry is never rewritten.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union

import build_britain_north_atlantic_regional_test as build

SCOTLAND_REFINEMENT_PATH = (
    Path(__file__).resolve().parents[2]
    / "assets" / "game_data" / "britain_north_atlantic_scotland_refinement.json"
)
_BASE_READ_JSON = build.read_json
_BASE_BUILD_MACRO_PROVINCES = build.build_macro_provinces
_BASE_STAGE5_CLEANUP = build.s.stage5.cleanup

# World coordinates are 8192 px wide. Around Britain 1 world-px is roughly
# 2.5-3 km. These limits target only visually line-like local artifacts.
MACRO_RDP_TOLERANCE = 0.02
MACRO_MAX_EFFECTIVE_WIDTH = 0.48
CELL_MAX_EFFECTIVE_WIDTH = 0.38
DETOUR_MIN_PATH = 1.10
DETOUR_MAX_PATH = 18.0
DETOUR_MIN_STRETCH = 1.72
DETOUR_MIN_EXCESS = 0.55
DETOUR_MIN_CHORD = 0.035
DETOUR_MAX_PASSES = 24
MACRO_TRANSFER_LIMIT = 240
MACRO_MIN_OWNER_SHARE = 0.80
MACRO_MAX_THIRD_PARTY_SHARE = 0.005
GEOM_EPS = 1.0e-7

MACRO_CLEANUP_STATS: dict[str, Any] = {
    "shared_components": 0,
    "changed_components": 0,
    "detours_removed": 0,
    "points_removed": 0,
    "skipped_candidates": 0,
    "remaining_candidates": 0,
    "adjacency_preserved": False,
    "outer_boundary_preserved": False,
}
CELL_CLEANUP_STATS: Counter[str] = Counter()


def _path_length(points: list[tuple[float, float]]) -> float:
    return sum(math.dist(points[i - 1], points[i]) for i in range(1, len(points)))


def _closed_area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    total = 0.0
    for i, point in enumerate(points):
        other = points[(i + 1) % len(points)]
        total += point[0] * other[1] - other[0] * point[1]
    return abs(total) * 0.5


def _candidate_metrics(points: list[tuple[float, float]], i: int, j: int) -> tuple[float, float, float, float] | None:
    if j <= i + 1:
        return None
    sub = points[i : j + 1]
    path = _path_length(sub)
    if path < DETOUR_MIN_PATH or path > DETOUR_MAX_PATH:
        return None
    chord = math.dist(sub[0], sub[-1])
    if chord < DETOUR_MIN_CHORD:
        return None
    stretch = path / max(chord, 1.0e-9)
    excess = path - chord
    area = _closed_area(sub)
    # For a long narrow U-turn this approximates the average ribbon width.
    effective_width = 2.0 * area / max(path, 1.0e-9)
    return path, stretch, excess, effective_width


def _find_best_detour(points: list[tuple[float, float]], max_width: float) -> tuple[int, int] | None:
    best: tuple[float, int, int] | None = None
    n = len(points)
    for i in range(0, n - 2):
        running = 0.0
        for j in range(i + 1, n):
            running += math.dist(points[j - 1], points[j])
            if running > DETOUR_MAX_PATH:
                break
            if j <= i + 1:
                continue
            metrics = _candidate_metrics(points, i, j)
            if metrics is None:
                continue
            _path, stretch, excess, width = metrics
            if stretch < DETOUR_MIN_STRETCH or excess < DETOUR_MIN_EXCESS or width > max_width:
                continue
            severity = (stretch - 1.0) * excess * (1.0 + (max_width - width) / max(max_width, 1.0e-9))
            if best is None or severity > best[0]:
                best = (severity, i, j)
    return None if best is None else (best[1], best[2])


def remove_thin_detours(
    raw_points: list[tuple[float, float]],
    max_width: float,
) -> tuple[list[tuple[float, float]], dict[str, int]]:
    points = list(raw_points)
    removed_detours = 0
    removed_points = 0
    for _pass in range(DETOUR_MAX_PASSES):
        hit = _find_best_detour(points, max_width)
        if hit is None:
            break
        i, j = hit
        removed = max(0, j - i - 1)
        if removed <= 0:
            break
        points = points[: i + 1] + points[j:]
        removed_detours += 1
        removed_points += removed

    deduped: list[tuple[float, float]] = []
    for point in points:
        if not deduped or math.dist(deduped[-1], point) > 1.0e-8:
            deduped.append(point)
    if len(deduped) < 2:
        deduped = list(raw_points)
    remaining = 1 if _find_best_detour(deduped, max_width) is not None else 0
    return deduped, {
        "detours_removed": removed_detours,
        "points_removed": removed_points,
        "remaining_candidates": remaining,
    }


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


def _polygon_parts(geometry: Any) -> list[Polygon]:
    return build.s.polygon_parts(geometry)


def _line_parts(geometry: Any) -> list[LineString]:
    return build.s.line_parts(geometry)


def _adjacency(geometries: dict[str, Any]) -> set[str]:
    ids = sorted(geometries)
    result: set[str] = set()
    for index, left in enumerate(ids):
        for right in ids[index + 1 :]:
            if geometries[left].boundary.intersection(geometries[right].boundary).length > 1.0e-5:
                result.add(build.s.stage5.pair_key(left, right))
    return result


def _partition_from_network(land: Any, lines: list[Any], source: dict[str, Any]) -> dict[str, Any]:
    network = unary_union([land.boundary, *lines])
    faces: list[Polygon] = []
    for face in polygonize(network):
        clipped = face.intersection(land)
        for part in _polygon_parts(clipped):
            if part.area > GEOM_EPS and land.covers(part.representative_point()):
                faces.append(part)

    assigned: dict[str, list[Polygon]] = {gid: [] for gid in source}
    for face in faces:
        scores = sorted(
            ((face.intersection(source[gid]).area, gid) for gid in source),
            reverse=True,
        )
        if not scores or scores[0][0] <= GEOM_EPS:
            raise RuntimeError("macro cleanup face has no original province owner")
        assigned[scores[0][1]].append(face)

    result: dict[str, Any] = {}
    for gid, pieces in assigned.items():
        if not pieces:
            raise RuntimeError(f"macro overlap-normalization emptied province {gid}")
        geometry = unary_union(pieces).intersection(land)
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        if geometry.is_empty:
            raise RuntimeError(f"macro overlap-normalization produced empty province {gid}")
        result[gid] = geometry
    return result


def _shared_chains(geometries: dict[str, Any]) -> list[tuple[str, list[tuple[float, float]]]]:
    grouped: dict[str, list[list[tuple[float, float]]]] = defaultdict(list)
    ids = sorted(geometries)
    for index, left in enumerate(ids):
        for right in ids[index + 1 :]:
            shared = geometries[left].boundary.intersection(geometries[right].boundary)
            if shared.length <= 1.0e-5:
                continue
            pair = build.s.stage5.pair_key(left, right)
            for line in _line_parts(shared):
                coords = [(float(x), float(y)) for x, y in line.coords]
                if len(coords) >= 2:
                    grouped[pair].append(coords)

    chains: list[tuple[str, list[tuple[float, float]]]] = []
    for pair in sorted(grouped):
        for chain in build.s.stage5.stitch(grouped[pair]):
            raw = build.s.stage5.rdp(chain, MACRO_RDP_TOLERANCE)
            if len(raw) >= 2:
                chains.append((pair, raw))
    return chains


def _candidate_key(pair: str, sub: list[tuple[float, float]]) -> str:
    a, b = sub[0], sub[-1]
    return f"{pair}:{a[0]:.4f},{a[1]:.4f}:{b[0]:.4f},{b[1]:.4f}:{len(sub)}"


def _next_macro_candidate(
    geometries: dict[str, Any],
    banned: set[str],
) -> tuple[str, list[tuple[float, float]], str] | None:
    for pair, chain in _shared_chains(geometries):
        hit = _find_best_detour(chain, MACRO_MAX_EFFECTIVE_WIDTH)
        if hit is None:
            continue
        i, j = hit
        sub = chain[i : j + 1]
        key = _candidate_key(pair, sub)
        if key in banned:
            continue
        return pair, sub, key
    return None


def _apply_pocket_transfer(
    geometries: dict[str, Any],
    land: Any,
    pair: str,
    sub: list[tuple[float, float]],
) -> bool:
    left, right = pair.split("|", 1)
    if left not in geometries or right not in geometries:
        return False
    pocket: Any = Polygon(sub)
    if not pocket.is_valid:
        pocket = pocket.buffer(0)
    pocket = pocket.intersection(land)
    if pocket.is_empty or pocket.area <= GEOM_EPS:
        return False

    pair_union = unary_union([geometries[left], geometries[right]])
    third_party = pocket.difference(pair_union).area
    if third_party > pocket.area * MACRO_MAX_THIRD_PARTY_SHARE:
        return False

    left_area = pocket.intersection(geometries[left]).area
    right_area = pocket.intersection(geometries[right]).area
    owner_area = max(left_area, right_area)
    if owner_area / max(pocket.area, GEOM_EPS) < MACRO_MIN_OWNER_SHARE:
        return False

    owner = left if left_area >= right_area else right
    receiver = right if owner == left else left
    transfer = pocket.intersection(geometries[owner])
    if transfer.is_empty or transfer.area <= GEOM_EPS:
        return False

    before_pair = unary_union([geometries[owner], geometries[receiver]])
    owner_parts_before = len(_polygon_parts(geometries[owner]))
    new_owner = geometries[owner].difference(transfer)
    new_receiver = unary_union([geometries[receiver], transfer])
    if not new_owner.is_valid:
        new_owner = new_owner.buffer(0)
    if not new_receiver.is_valid:
        new_receiver = new_receiver.buffer(0)
    if new_owner.is_empty or new_receiver.is_empty:
        return False
    # Do not cut a legitimate corridor and fragment a province just to remove a spike.
    if len(_polygon_parts(new_owner)) > owner_parts_before:
        return False

    after_pair = unary_union([new_owner, new_receiver])
    if before_pair.symmetric_difference(after_pair).area > max(GEOM_EPS, before_pair.area * 1.0e-10):
        return False

    geometries[owner] = new_owner
    geometries[receiver] = new_receiver
    return True


def _count_remaining_candidates(geometries: dict[str, Any], banned: set[str]) -> int:
    count = 0
    for pair, chain in _shared_chains(geometries):
        hit = _find_best_detour(chain, MACRO_MAX_EFFECTIVE_WIDTH)
        if hit is None:
            continue
        i, j = hit
        key = _candidate_key(pair, chain[i : j + 1])
        if key not in banned:
            count += 1
    return count


def _clean_macro_partition(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source = {str(record["id"]): record["_geometry"] for record in records}
    land = unary_union(list(source.values()))
    if not land.is_valid:
        land = land.buffer(0)
    original_outer = land.boundary

    # Normalize inherited SAFE-source overlap once. After this every square unit
    # of land has exactly one gameplay-province owner.
    base = _partition_from_network(land, [geometry.boundary for geometry in source.values()], source)
    before_adjacency = _adjacency(base)
    before_union = unary_union(list(base.values()))

    banned: set[str] = set()
    changed_pairs: Counter[str] = Counter()
    removed = 0
    points_removed = 0
    skipped = 0
    for _step in range(MACRO_TRANSFER_LIMIT):
        candidate = _next_macro_candidate(base, banned)
        if candidate is None:
            break
        pair, sub, key = candidate
        if _apply_pocket_transfer(base, land, pair, sub):
            removed += 1
            points_removed += max(0, len(sub) - 2)
            changed_pairs[pair] += 1
        else:
            banned.add(key)
            skipped += 1
    else:
        raise RuntimeError("macro anti-spike transfer limit reached")

    after_union = unary_union(list(base.values()))
    after_adjacency = _adjacency(base)
    outer_preserved = original_outer.symmetric_difference(after_union.boundary).length <= 1.0e-6
    if before_union.symmetric_difference(after_union).area > 1.0e-8:
        raise RuntimeError("macro anti-spike cleanup changed total land coverage")
    if before_adjacency != after_adjacency:
        raise RuntimeError(
            "macro anti-spike cleanup changed province adjacency: "
            f"missing={sorted(before_adjacency-after_adjacency)} added={sorted(after_adjacency-before_adjacency)}"
        )
    if not outer_preserved:
        raise RuntimeError("macro anti-spike cleanup changed authoritative outer boundary")

    final_chains = _shared_chains(base)
    MACRO_CLEANUP_STATS.update({
        "shared_components": len(final_chains),
        "changed_components": len(changed_pairs),
        "detours_removed": removed,
        "points_removed": points_removed,
        "skipped_candidates": skipped,
        "remaining_candidates": _count_remaining_candidates(base, banned),
        "adjacency_preserved": True,
        "outer_boundary_preserved": True,
    })

    for record in records:
        gid = str(record["id"])
        geometry = base[gid]
        point = geometry.representative_point()
        record["_geometry"] = geometry
        record["area_km2"] = round(build.s.area_km2(geometry), 4)
        record["label_point"] = [round(float(point.x), 6), round(float(point.y), 6)]
        record["bbox"] = [round(float(x), 6) for x in geometry.bounds]
        record["parts"] = build.s.shape_parts_payload(geometry)
    return records


def build_macro_provinces_cleaned(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    records = _BASE_BUILD_MACRO_PROVINCES(*args, **kwargs)
    return _clean_macro_partition(records)


def stage5_cleanup_without_hairpins(raw: list[tuple[float, float]], pair: str) -> list[tuple[float, float]]:
    clean = _BASE_STAGE5_CLEANUP(raw, pair)
    filtered, stats = remove_thin_detours(clean, CELL_MAX_EFFECTIVE_WIDTH)
    if len(filtered) >= 2:
        filtered[0] = raw[0]
        filtered[-1] = raw[-1]
    CELL_CLEANUP_STATS["components"] += 1
    CELL_CLEANUP_STATS["detours_removed"] += int(stats["detours_removed"])
    CELL_CLEANUP_STATS["points_removed"] += int(stats["points_removed"])
    CELL_CLEANUP_STATS["remaining_candidates"] += int(stats["remaining_candidates"])
    return filtered


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
        "anti_spike_cleanup": dict(MACRO_CLEANUP_STATS),
    }


def main() -> None:
    build.read_json = read_json_with_refinements
    build.build_macro_provinces = build_macro_provinces_cleaned
    build.s.stage5.cleanup = stage5_cleanup_without_hairpins
    build.validate_macro_coverage = validate_macro_coverage
    build.main()
    print("BRITAIN_MACRO_ANTI_SPIKE=", json.dumps(MACRO_CLEANUP_STATS, ensure_ascii=False, sort_keys=True))
    print("BRITAIN_CELL_ANTI_SPIKE=", json.dumps(dict(CELL_CLEANUP_STATS), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
