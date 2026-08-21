#!/usr/bin/env python3
"""Recursive boundary-to-boundary political subdivision geometry.

Every accepted operation is one open jagged LineString splitting one existing
Polygon into exactly two connected Polygons.  This rules out the round enclosed
"blobs" produced by isotropic raster growth and keeps shared edges canonical.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point, Polygon
from shapely.ops import linemerge, split, unary_union


CANDIDATE_COUNT = 32
TOP_CANDIDATES = 20


@dataclass
class SplitCandidate:
    score: float
    left: Polygon
    right: Polygon
    left_count: int
    right_count: int
    shared: LineString
    variant: int
    compactness: tuple[float, float]
    outer_contact: tuple[float, float]
    sinuosity: float


def _polygon_parts(geometry: Any) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [] if geometry.is_empty else [geometry]
    if isinstance(geometry, GeometryCollection) or hasattr(geometry, "geoms"):
        return [
            part for part in geometry.geoms
            if isinstance(part, Polygon) and not part.is_empty and part.area > 1e-8
        ]
    return []


def _line_parts(geometry: Any) -> list[LineString]:
    if isinstance(geometry, LineString):
        return [] if geometry.is_empty else [geometry]
    if isinstance(geometry, (MultiLineString, GeometryCollection)) or hasattr(geometry, "geoms"):
        return [line for part in geometry.geoms for line in _line_parts(part)]
    return []


def _hash01(seed: int, index: int) -> float:
    value = math.sin((seed * 12.9898 + index * 78.233) * math.pi / 180.0) * 43758.5453
    return value - math.floor(value)


def _interpolate(ts: list[float], values: list[float], t: float) -> float:
    position = max(0.0, min(len(ts) - 1.0, (t - ts[0]) / max(ts[-1] - ts[0], 1e-9) * (len(ts) - 1)))
    index = min(len(ts) - 2, int(position))
    fraction = position - index
    return values[index] * (1.0 - fraction) + values[index + 1] * fraction


def _samples(polygon: Polygon, target_count: int = 800) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = polygon.bounds
    step = max(0.30, math.sqrt(polygon.area / target_count))
    result: list[tuple[float, float]] = []
    y = y0 + step * 0.5
    while y < y1:
        x = x0 + step * 0.5
        while x < x1:
            if polygon.covers(Point(x, y)):
                result.append((x, y))
            x += step
        y += step
    if not result:
        point = polygon.representative_point()
        result.append((point.x, point.y))
    return result


def _quantile(values: list[float], position: float) -> float:
    ordered = sorted(values)
    scaled = (len(ordered) - 1) * position
    index = int(scaled)
    fraction = scaled - index
    return ordered[index] * (1.0 - fraction) + ordered[min(index + 1, len(ordered) - 1)] * fraction


def _compactness(polygon: Polygon) -> float:
    return 4.0 * math.pi * polygon.area / max(polygon.length ** 2, 1e-9)


def _line_character(line: LineString) -> tuple[float, float]:
    coordinates = list(line.coords)
    if len(coordinates) < 2:
        return 1.0, 0.0
    x0, y0 = coordinates[0]
    x1, y1 = coordinates[-1]
    chord = math.hypot(x1 - x0, y1 - y0)
    if chord <= 1e-9:
        return float("inf"), float("inf")
    maximum_deviation = max(
        abs((x1 - x0) * (y0 - y) - (x0 - x) * (y1 - y0)) / chord
        for x, y in coordinates[1:-1]
    ) if len(coordinates) > 2 else 0.0
    return line.length / chord, maximum_deviation


def _support_offsets(segment_count: int, amplitude: float, seed: int, variant: int) -> list[float]:
    raw = [2.0 * _hash01(seed + variant * 101, index + 17) - 1.0 for index in range(segment_count + 1)]
    smoothed: list[float] = []
    for index in range(segment_count + 1):
        lower = max(0, index - 1)
        upper = min(segment_count, index + 1)
        smoothed.append(sum(raw[lower:upper + 1]) / (upper - lower + 1))
    # Remove the endpoint-to-endpoint trend so the visible middle really bends
    # instead of becoming one translated almost-straight chord.
    start, end = smoothed[0], smoothed[-1]
    detrended = [
        value - (start + (end - start) * index / segment_count)
        for index, value in enumerate(smoothed)
    ]
    scale = max((abs(value) for value in detrended[1:-1]), default=0.0)
    if scale <= 1e-6:
        detrended[segment_count // 2] = 1.0
        scale = 1.0
    result = [value / scale * amplitude for value in detrended]
    result[0] = 0.0
    result[-1] = 0.0
    return result


def _allocation_pairs(count: int) -> list[tuple[int, int]]:
    balanced = count // 2
    result = [(balanced, count - balanced)]
    if count >= 7:
        lobe = max(1, round(count * 0.35))
        if lobe != balanced:
            result.append((lobe, count - lobe))
    return result


def _candidate_splits(
    piece: Polygon,
    original: Polygon,
    count: int,
    seed: int,
    anchor: Point,
    junctions: tuple[Point, ...],
    final_count: int,
    compactness_floor: float,
) -> list[SplitCandidate]:
    center = piece.centroid
    exterior = list(piece.exterior.coords)
    samples = _samples(piece)
    province_scale = math.sqrt(original.area)
    cell_scale = math.sqrt(original.area / max(final_count, 1))
    junction_clearance = 0.16 * cell_scale
    anchor_clearance = 0.10 * cell_scale
    minimum_outer_contact = max(0.25, original.length * 0.002)
    allocations = _allocation_pairs(count)
    variants_per_allocation = max(12, CANDIDATE_COUNT // len(allocations))
    candidates: list[SplitCandidate] = []

    for allocation_index, (left_count, right_count) in enumerate(allocations):
        desired_ratio = min(left_count, right_count) / count
        for local_variant in range(variants_per_allocation):
            variant = allocation_index * 101 + local_variant
            angle = ((local_variant * 0.61803398875 + _hash01(seed + allocation_index * 997, local_variant) * 0.055) % 1.0) * math.pi
            direction_x, direction_y = math.cos(angle), math.sin(angle)
            normal_x, normal_y = -direction_y, direction_x
            projections = [
                ((x - center.x) * direction_x + (y - center.y) * direction_y,
                 (x - center.x) * normal_x + (y - center.y) * normal_y)
                for x, y in exterior
            ]
            tangent_min = min(value[0] for value in projections)
            tangent_max = max(value[0] for value in projections)
            normal_min = min(value[1] for value in projections)
            normal_max = max(value[1] for value in projections)
            tangent_span = tangent_max - tangent_min
            normal_span = normal_max - normal_min
            if min(tangent_span, normal_span) <= 1e-6:
                continue
            segment_count = 4 + local_variant % 5
            margin = max(2.0, math.hypot(tangent_span, normal_span) * 0.30)
            support_t = [
                tangent_min - margin + (tangent_span + 2.0 * margin) * index / segment_count
                for index in range(segment_count + 1)
            ]
            amplitude = min(normal_span * 0.20, tangent_span * 0.12) * (0.82 + 0.34 * _hash01(seed, variant + 83))
            offsets = _support_offsets(segment_count, amplitude, seed, variant)
            signed_samples = []
            for x, y in samples:
                tangent = (x - center.x) * direction_x + (y - center.y) * direction_y
                normal = (x - center.x) * normal_x + (y - center.y) * normal_y
                signed_samples.append(normal - _interpolate(support_t, offsets, tangent))
            quantile_position = desired_ratio if local_variant % 2 == 0 else 1.0 - desired_ratio
            quantile_position += ((local_variant // 2) % 5 - 2) * 0.012
            line_offset = _quantile(signed_samples, max(0.08, min(0.92, quantile_position)))
            line = LineString([
                (center.x + direction_x * tangent + normal_x * (line_offset + local_offset),
                 center.y + direction_y * tangent + normal_y * (line_offset + local_offset))
                for tangent, local_offset in zip(support_t, offsets)
            ])
            if not line.is_simple or (piece.covers(anchor) and line.distance(anchor) < anchor_clearance):
                continue
            try:
                children = _polygon_parts(split(piece, line))
            except Exception:
                continue
            if len(children) != 2:
                continue
            left, right = children
            if left.area > right.area:
                left, right = right, left
            if piece.symmetric_difference(unary_union([left, right])).area > 1e-7 or left.intersection(right).area > 1e-8:
                continue
            shared_parts = [part for part in _line_parts(left.boundary.intersection(right.boundary)) if part.length > 1e-8]
            if not shared_parts:
                continue
            shared_geometry = shared_parts[0] if len(shared_parts) == 1 else linemerge(unary_union(shared_parts))
            if not isinstance(shared_geometry, LineString) or shared_geometry.is_ring:
                continue
            endpoints = (Point(shared_geometry.coords[0]), Point(shared_geometry.coords[-1]))
            if any(
                endpoint.distance(original.boundary) > 1e-6
                and any(endpoint.distance(existing) < junction_clearance for existing in junctions)
                for endpoint in endpoints
            ):
                continue
            contact_left = left.boundary.intersection(original.boundary).length
            contact_right = right.boundary.intersection(original.boundary).length
            if min(contact_left, contact_right) < minimum_outer_contact:
                continue
            compact_left, compact_right = _compactness(left), _compactness(right)
            if min(compact_left, compact_right) < compactness_floor:
                continue
            sinuosity, deviation = _line_character(shared_geometry)
            if shared_geometry.length >= province_scale * 0.20:
                if len(shared_geometry.coords) < 3 or sinuosity < 1.015 or deviation < province_scale * 0.008:
                    continue
            for assigned_left, assigned_right in (
                ((left_count, right_count), (right_count, left_count))
                if left_count != right_count else ((left_count, right_count),)
            ):
                area_error = abs(left.area / piece.area - assigned_left / count)
                line_style_penalty = abs(min(sinuosity, 1.18) - 1.07) * 1.8
                score = (
                    area_error * 14.0
                    + shared_geometry.length / math.sqrt(piece.area) * 0.035
                    + 0.075 * (1.0 / compact_left + 1.0 / compact_right)
                    + 0.010 * (piece.length / contact_left + piece.length / contact_right)
                    + line_style_penalty
                )
                candidates.append(SplitCandidate(
                    score, left, right, assigned_left, assigned_right,
                    shared_geometry, variant, (compact_left, compact_right),
                    (contact_left, contact_right), sinuosity,
                ))
    return sorted(candidates, key=lambda candidate: candidate.score)


def _recursive_partition(
    piece: Polygon,
    original: Polygon,
    count: int,
    final_count: int,
    anchor: Point,
    seed: int,
    junctions: tuple[Point, ...],
    compactness_floor: float,
) -> tuple[list[Polygon], list[dict[str, Any]], tuple[Point, ...]]:
    if count == 1:
        return [piece], [], junctions
    candidates = _candidate_splits(
        piece, original, count, seed, anchor, junctions, final_count, compactness_floor,
    )
    for candidate in candidates[:TOP_CANDIDATES]:
        new_junctions = list(junctions)
        for coordinate in (candidate.shared.coords[0], candidate.shared.coords[-1]):
            point = Point(coordinate)
            if point.distance(original.boundary) > 1e-6:
                new_junctions.append(point)
        try:
            left_leaves, left_decisions, after_left = _recursive_partition(
                candidate.left, original, candidate.left_count, final_count, anchor,
                seed * 37 + candidate.variant * 5 + 11, tuple(new_junctions), compactness_floor,
            )
            right_leaves, right_decisions, after_right = _recursive_partition(
                candidate.right, original, candidate.right_count, final_count, anchor,
                seed * 41 + candidate.variant * 7 + 19, after_left, compactness_floor,
            )
        except ValueError:
            continue
        decision = {
            "basis": ["boundary_to_boundary", "recursive_binary_claims", "broad_angular_supports"],
            "strategy": "recursive_vector_boundary_split",
            "candidate_count": CANDIDATE_COUNT,
            "selected_variant": candidate.variant,
            "score": round(candidate.score, 6),
            "left_final_cells": candidate.left_count,
            "right_final_cells": candidate.right_count,
            "shared_support_points": len(candidate.shared.coords),
            "shared_sinuosity": round(candidate.sinuosity, 6),
        }
        return left_leaves + right_leaves, [decision, *left_decisions, *right_decisions], after_right
    raise ValueError(f"no recursive boundary split for count={count}, area={piece.area:.3f}, candidates={len(candidates)}")


def partition(
    province: Polygon,
    final_count: int,
    anchor: Point,
    seed: int,
    grid_step: float = 0.70,
) -> tuple[list[Polygon], list[dict[str, Any]]]:
    del grid_step  # Kept in the API so caller provenance remains explicit.
    if final_count <= 1:
        return [province], []
    last_error: ValueError | None = None
    for compactness_floor in (0.085, 0.065, 0.050):
        try:
            polygons, decisions, _junctions = _recursive_partition(
                province, province, final_count, final_count, anchor, seed, (), compactness_floor,
            )
            break
        except ValueError as error:
            last_error = error
    else:
        raise last_error or ValueError("recursive boundary partition failed")
    union = unary_union(polygons)
    overlap = sum(
        left.intersection(right).area
        for index, left in enumerate(polygons)
        for right in polygons[index + 1:]
    )
    if province.symmetric_difference(union).area > 1e-7 or overlap > 1e-8:
        raise ValueError("recursive boundary partition broke exact cover")
    minimum_contact = max(0.20, province.length * 0.0015)
    if any(polygon.boundary.intersection(province.boundary).length < minimum_contact for polygon in polygons):
        raise ValueError("recursive boundary partition produced an enclosed cell")
    anchor_owner = next((index for index, polygon in enumerate(polygons) if polygon.covers(anchor)), None)
    if anchor_owner is None:
        raise ValueError("recursive boundary partition lost the primary anchor")
    polygons[0], polygons[anchor_owner] = polygons[anchor_owner], polygons[0]
    for index, decision in enumerate(decisions, 1):
        decision["split_id"] = f"split:{index:02d}"
    return polygons, decisions
