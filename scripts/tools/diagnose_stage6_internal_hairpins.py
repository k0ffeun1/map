#!/usr/bin/env python3
"""Diagnose long narrow internal hairpins in final Stage-6 province cells.

The important distinction is that this operates on the FINAL polygons emitted
by Stage 6, after polygonize/assignment/topology locking.  Shapely can expose a
single visual shared border as many tiny LineString fragments at this point, so
we first stitch those fragments back into continuous chains and only then rank
returning (hairpin-like) subchains.

This is intentionally diagnostic only.  It does not touch coastline cleanup or
mutate generated geometry.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

import build_lacoruna_final_subdivision as stage5
import build_stage6_universal_subdivisions as stage6

ROOT = Path(__file__).resolve().parents[2]
TARGET_LEGACY_ID = "gb_england_lancashire_manchester"
REPORT_PATH = ROOT / "reports" / "stage6_lancashire_hairpin_diagnostic.json"
EPS = 1.0e-9


def polygon_from_part(part: dict[str, Any]) -> Polygon:
    rings = part.get("rings", [])
    if not rings or len(rings[0]) < 3:
        return Polygon()
    geometry = Polygon(rings[0], rings[1:])
    return geometry if geometry.is_valid else geometry.buffer(0)


def geometry_from_zone(zone: dict[str, Any]) -> Any:
    parts = [polygon_from_part(part) for part in zone.get("parts", [])]
    parts = [part for part in parts if not part.is_empty]
    if not parts:
        return Polygon()
    geometry = unary_union(parts)
    return geometry if geometry.is_valid else geometry.buffer(0)


def cumulative_lengths(points: list[tuple[float, float]]) -> list[float]:
    result = [0.0]
    for first, second in zip(points, points[1:]):
        result.append(result[-1] + math.dist(first, second))
    return result


def subchain_metrics(points: list[tuple[float, float]], cumulative: list[float], first: int, last: int) -> dict[str, Any]:
    section = points[first:last + 1]
    arc = cumulative[last] - cumulative[first]
    chord = math.dist(section[0], section[-1])
    xs = [point[0] for point in section]
    ys = [point[1] for point in section]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    major = max(width, height)
    minor = min(width, height)
    return_ratio = arc / max(chord, EPS)
    slenderness = major / max(minor, 0.0025)
    # Favour a long excursion whose endpoints return close together and whose
    # footprint is narrow. Arc length prevents microscopic zig-zags from
    # outranking the visible defect.
    score = arc * return_ratio * math.sqrt(max(1.0, slenderness))
    return {
        "start_index": first,
        "end_index": last,
        "vertex_span": last - first + 1,
        "arc_length_world_px": round(arc, 9),
        "chord_length_world_px": round(chord, 9),
        "return_ratio_arc_to_chord": round(return_ratio, 6),
        "bbox_width_world_px": round(width, 9),
        "bbox_height_world_px": round(height, 9),
        "slenderness": round(slenderness, 6),
        "score": round(score, 9),
        "start": [round(section[0][0], 9), round(section[0][1], 9)],
        "end": [round(section[-1][0], 9), round(section[-1][1], 9)],
        "coordinates": [[round(x, 9), round(y, 9)] for x, y in section],
    }


def rank_hairpin_subchains(points: list[tuple[float, float]], limit: int = 12) -> list[dict[str, Any]]:
    if len(points) < 5:
        return []
    cumulative = cumulative_lengths(points)
    total = cumulative[-1]
    minimum_arc = max(0.035, total * 0.06)
    candidates: list[dict[str, Any]] = []
    for first in range(len(points) - 4):
        for last in range(first + 4, len(points)):
            arc = cumulative[last] - cumulative[first]
            if arc < minimum_arc:
                continue
            chord = math.dist(points[first], points[last])
            if chord > arc * 0.48:
                continue
            metrics = subchain_metrics(points, cumulative, first, last)
            if metrics["slenderness"] < 2.0:
                continue
            candidates.append(metrics)
    candidates.sort(key=lambda item: (item["score"], item["arc_length_world_px"]), reverse=True)

    # Keep ranked candidates but suppress near-identical index windows so the
    # report exposes distinct suspicious excursions rather than the same one
    # shifted by one vertex many times.
    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        a0, a1 = candidate["start_index"], candidate["end_index"]
        duplicate = False
        for existing in selected:
            b0, b1 = existing["start_index"], existing["end_index"]
            intersection = max(0, min(a1, b1) - max(a0, b0) + 1)
            union = max(a1, b1) - min(a0, b0) + 1
            if union and intersection / union >= 0.80:
                duplicate = True
                break
        if not duplicate:
            selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


def diagnose_pair(left_id: str, left: Any, right_id: str, right: Any) -> dict[str, Any] | None:
    shared = left.boundary.intersection(right.boundary)
    if shared.is_empty or shared.length <= 1.0e-5:
        return None
    lines = stage6.line_parts(shared)
    raw = [[(float(x), float(y)) for x, y in line.coords] for line in lines]
    raw = [coords for coords in raw if len(coords) >= 2]
    stitched = stage5.stitch(raw)

    chains = []
    for chain_index, chain in enumerate(stitched):
        points = [(float(x), float(y)) for x, y in chain]
        line = LineString(points)
        chains.append({
            "chain_index": chain_index,
            "point_count": len(points),
            "length_world_px": round(float(line.length), 9),
            "is_simple": bool(line.is_simple),
            "coordinates": [[round(x, 9), round(y, 9)] for x, y in points],
            "hairpin_candidates": rank_hairpin_subchains(points),
        })

    best = None
    for chain in chains:
        for candidate in chain["hairpin_candidates"]:
            item = dict(candidate)
            item["chain_index"] = chain["chain_index"]
            if best is None or item["score"] > best["score"]:
                best = item

    return {
        "pair": f"{left_id}|{right_id}",
        "shared_length_world_px": round(float(shared.length), 9),
        "segment_count_before_stitch": len(raw),
        "stitched_chain_count": len(stitched),
        "raw_segments": [
            [[round(x, 9), round(y, 9)] for x, y in coords]
            for coords in raw
        ],
        "chains": chains,
        "best_hairpin_candidate": best,
    }


def main() -> None:
    sources = stage6.Sources()
    identity = sources.by_legacy.get(TARGET_LEGACY_ID)
    if identity is None:
        raise SystemExit(f"Target legacy_id not found: {TARGET_LEGACY_ID}")
    province_id = str(identity["id"])

    record = stage6.build_province(sources, province_id, "internal_hairpin_regression")
    zones = {str(zone["local_id"]): geometry_from_zone(zone) for zone in record["zones"]}
    pairs = []
    zone_ids = sorted(zones)
    for index, left_id in enumerate(zone_ids):
        for right_id in zone_ids[index + 1:]:
            pair = diagnose_pair(left_id, zones[left_id], right_id, zones[right_id])
            if pair is not None:
                pairs.append(pair)

    ranked = []
    for pair in pairs:
        candidate = pair.get("best_hairpin_candidate")
        if candidate is None:
            continue
        ranked.append({
            "pair": pair["pair"],
            "segment_count_before_stitch": pair["segment_count_before_stitch"],
            **candidate,
        })
    ranked.sort(key=lambda item: item["score"], reverse=True)

    payload = {
        "format": "stage6_internal_hairpin_diagnostic/v1",
        "target": {
            "province_id": province_id,
            "legacy_id": TARGET_LEGACY_ID,
            "name": record["name"],
            "zone_count": len(zones),
        },
        "stage6_validation": record["validation"],
        "pair_count": len(pairs),
        "ranked_hairpin_candidates": ranked,
        "pairs": pairs,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        "STAGE6_HAIRPIN_TARGET=",
        province_id,
        record["name"],
        "zones=",
        len(zones),
        flush=True,
    )
    for pair in pairs:
        best = pair.get("best_hairpin_candidate")
        print(
            "STAGE6_HAIRPIN_PAIR=",
            pair["pair"],
            "segments=",
            pair["segment_count_before_stitch"],
            "chains=",
            pair["stitched_chain_count"],
            "best_score=",
            None if best is None else best["score"],
            flush=True,
        )
    if ranked:
        print("STAGE6_HAIRPIN_TOP=", ranked[0], flush=True)
    print(REPORT_PATH.relative_to(ROOT), flush=True)


if __name__ == "__main__":
    main()
