"""Build the global "two irregular cells per province" overlay.

Input is the already cleaned and projected ``assets/provinces.json``.  Its
records are the source-of-truth province pieces rendered by layer 8.  Every
record is cut into two near-equal parts along its main axis; the cut is then
made gently wavy.  The original outline is never altered.

Output uses ``brd_open`` deliberately: it contains only the shared internal
divider.  The province outline remains the responsibility of layer 8, so two
almost coincident anti-aliased outlines cannot turn into a blurry line.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from shapely.geometry import LineString, Polygon
from shapely.ops import split


SRC = Path("assets/provinces.json")
OUT = Path("assets/province_cells_2.json")
WAVE_POINTS = 18
PRECISION = 4


def _seed(cell_id: str) -> int:
    return int.from_bytes(hashlib.sha256(cell_id.encode("utf-8")).digest()[:8], "big")


def _principal_axis(poly: Polygon) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return an orthogonal (long_axis, divider_axis) pair for *poly*."""
    rect = poly.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)
    edges = []
    for a, b in zip(coords, coords[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length > 1e-9:
            edges.append((length, dx / length, dy / length))
    if not edges:
        return (1.0, 0.0), (0.0, 1.0)
    _length, ux, uy = max(edges)
    return (ux, uy), (-uy, ux)


def _line_at(poly: Polygon, axis: tuple[float, float], divider: tuple[float, float], offset: float) -> LineString:
    """An infinite-in-practice straight divider at an axis projection."""
    ux, uy = axis
    vx, vy = divider
    minx, miny, maxx, maxy = poly.bounds
    span = math.hypot(maxx - minx, maxy - miny) * 3.0 + 10.0
    # A projection on ``axis`` alone is not a world point: preserve the
    # polygon's centre projection on the perpendicular axis as well.
    v_values = [x * vx + y * vy for x, y in poly.exterior.coords]
    v_mid = (min(v_values) + max(v_values)) * 0.5
    base_x, base_y = ux * offset + vx * v_mid, uy * offset + vy * v_mid
    return LineString([
        (base_x - vx * span, base_y - vy * span),
        (base_x + vx * span, base_y + vy * span),
    ])


def _polygon_parts(poly: Polygon, divider: LineString) -> list[Polygon]:
    result = split(poly, divider)
    return [g for g in result.geoms if isinstance(g, Polygon) and g.area > 1e-8]


def _two_part_straight_cut(poly: Polygon, primary_axis: tuple[float, float], primary_divider: tuple[float, float]) -> tuple[tuple[float, float], tuple[float, float], float, LineString, list[Polygon]]:
    """Find a sensible central divider without expensive repeated bisection.

    The normal path is one split of the province's main axis.  A few nearby
    offsets and alternative axes cover deeply concave coastlines while keeping
    global generation fast enough to be a normal build step.
    """
    axes = [
        (primary_axis, primary_divider),
        (primary_divider, (-primary_axis[0], -primary_axis[1])),
        ((1.0, 0.0), (0.0, 1.0)),
        ((0.0, 1.0), (1.0, 0.0)),
    ]
    for axis, divider in axes:
        ux, uy = axis
        projections = [x * ux + y * uy for x, y in poly.exterior.coords]
        lo, hi = min(projections), max(projections)
        # Start at the centre, then move symmetrically only if a concavity
        # turns that cut into more than two pieces.
        for fraction in (0.50, 0.46, 0.54, 0.40, 0.60, 0.32, 0.68):
            offset = lo + (hi - lo) * fraction
            line = _line_at(poly, axis, divider, offset)
            parts = _polygon_parts(poly, line)
            if len(parts) == 2 and min(p.area for p in parts) > poly.area * 0.01:
                return axis, divider, offset, line, parts
    # Fjord-like and archipelago outlines occasionally need a more distant
    # crossing.  This exhaustive scan is intentionally a last resort; it is
    # reached by only a handful of the 4k province pieces.
    best: tuple[tuple[float, float], tuple[float, float], float, LineString, list[Polygon], float] | None = None
    for axis, divider in axes:
        ux, uy = axis
        projections = [x * ux + y * uy for x, y in poly.exterior.coords]
        lo, hi = min(projections), max(projections)
        for i in range(97):
            offset = lo + (hi - lo) * i / 96.0
            line = _line_at(poly, axis, divider, offset)
            parts = _polygon_parts(poly, line)
            if len(parts) != 2 or min(p.area for p in parts) <= poly.area * 0.01:
                continue
            imbalance = abs(parts[0].area - parts[1].area)
            if best is None or imbalance < best[5]:
                best = (axis, divider, offset, line, parts, imbalance)
    if best is not None:
        return best[0], best[1], best[2], best[3], best[4]
    raise ValueError("cannot find a two-part cut")


def _wavy_line(poly: Polygon, axis: tuple[float, float], divider: tuple[float, float], offset: float, cell_id: str) -> LineString:
    """A deterministic low-amplitude wave around the balanced straight cut."""
    ux, uy = axis
    vx, vy = divider
    minx, miny, maxx, maxy = poly.bounds
    diag = math.hypot(maxx - minx, maxy - miny)
    span = diag * 2.0 + 10.0
    amplitude = min(max(diag * 0.028, 0.10), 5.0)
    phase = (_seed(cell_id) % 6283) / 1000.0
    v_values = [x * vx + y * vy for x, y in poly.exterior.coords]
    v_mid = (min(v_values) + max(v_values)) * 0.5
    base_x, base_y = ux * offset + vx * v_mid, uy * offset + vy * v_mid
    points = []
    for i in range(WAVE_POINTS + 1):
        t = -span + (2.0 * span * i / WAVE_POINTS)
        wobble = amplitude * (math.sin((i / WAVE_POINTS) * math.tau * 2.0 + phase) + 0.35 * math.sin((i / WAVE_POINTS) * math.tau * 5.0 + phase * 1.7))
        points.append((base_x + vx * t + ux * wobble, base_y + vy * t + uy * wobble))
    return LineString(points)


def _split_province(poly: Polygon, cell_id: str) -> tuple[list[Polygon], LineString]:
    axis, divider_axis = _principal_axis(poly)
    axis, divider_axis, offset, straight, straight_parts = _two_part_straight_cut(poly, axis, divider_axis)
    wavy = _wavy_line(poly, axis, divider_axis, offset, cell_id)
    wavy_parts = _polygon_parts(poly, wavy)
    # Waviness is cosmetic; a pathological concave outline must still produce
    # exactly two cells, so use its proven straight divider as a safe fallback.
    if len(wavy_parts) == 2 and min(p.area for p in wavy_parts) > poly.area * 0.02:
        return wavy_parts, wavy
    return straight_parts, straight


def _rings(poly: Polygon) -> list[list[list[float]]]:
    rings = []
    for ring in [poly.exterior, *poly.interiors]:
        points = [[round(x, PRECISION), round(y, PRECISION)] for x, y in ring.coords]
        if len(points) >= 4:
            rings.append(points)
    return rings


def _bbox(poly: Polygon) -> list[float]:
    return [round(v, PRECISION) for v in poly.bounds]


def _divider_chain(parts: list[Polygon]) -> list[list[list[float]]]:
    """Extract the actual shared edge after clipping the divider to a province."""
    shared = parts[0].boundary.intersection(parts[1].boundary)
    chains = []
    for geom in getattr(shared, "geoms", [shared]):
        if isinstance(geom, LineString) and geom.length > 1e-6:
            chains.append([[round(x, PRECISION), round(y, PRECISION)] for x, y in geom.coords])
    return chains


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    out_cells = []
    for index, source in enumerate(data["cells"], start=1):
        rings = source.get("rings", [])
        if not rings:
            raise ValueError("province without rings: %r" % source.get("id"))
        poly = Polygon(rings[0], rings[1:])
        if not poly.is_valid:
            poly = poly.buffer(0)
        if not isinstance(poly, Polygon) or poly.is_empty:
            raise ValueError("invalid province polygon: %s" % source.get("id"))
        parts, divider = _split_province(poly, source["id"])
        if len(parts) != 2:
            raise ValueError("not exactly two cells: %s" % source["id"])
        chains = _divider_chain(parts)
        if not chains:
            raise ValueError("missing divider: %s" % source["id"])
        for number, part in enumerate(sorted(parts, key=lambda p: (p.representative_point().x, p.representative_point().y)), start=1):
            out_cells.append({
                "id": f"{source['id']}__cell_{number}",
                "province_id": source["id"],
                "name": f"{source.get('name', source['id'])} — cell {number}",
                "rings": _rings(part),
                "brd_open": chains,
                "bbox": _bbox(part),
            })
        if index % 500 == 0:
            print(f"split {index}/{len(data['cells'])}")

    if len(out_cells) != len(data["cells"]) * 2:
        raise ValueError("output count is not exactly two cells per province")
    OUT.write_text(json.dumps({"world_px": data["world_px"], "cells": out_cells}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT}: {len(data['cells'])} provinces -> {len(out_cells)} cells")


if __name__ == "__main__":
    main()
