#!/usr/bin/env python3
"""Build the layer-3 Galicia graph cells from the hand-drawn border style.

This is not Voronoi and it is not a rectangular grid.  Every province starts
with one long noisy spine.  Further splits happen inside existing faces, so
their borders end at the spine and form T/Y-like graph nodes.  The saved
La Coruña sketch supplies the scale of the turns; its raw mouse jitter is not
copied verbatim.

Profile source:
  * REPORT/Excel in ``Все про клетки``: Galicia is P3, target 2,100 km².
  * Consequently La Coruña (7,932 km²) = 4 cells, Lugo (9,869 km²) = 5,
    and Pontevedra (4,433 km²) = 2.

Only visual internal chains are cut back from the sea by two kilometres.  The
cell polygons still cover the whole province, while the province layer keeps
ownership of the coastline itself.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any, Iterable

from shapely import set_precision
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon, box
from shapely.ops import split, unary_union


ROOT = Path(__file__).resolve().parents[2]
GEOMETRY_PATH = ROOT / "assets" / "map_geometry" / "provinces.json"
FALLBACK_GEOMETRY_PATH = ROOT / "assets" / "provinces_iberia.json"
OCEAN_PATH = ROOT / "assets" / "world_ocean.json"
DRAFT_PATH = ROOT / "assets" / "cell_boundary_drafts_lacoruna_manual.json"
OUT_PATH = ROOT / "assets" / "cells_lacoruna_graph_layer3.json"

WORLD_PX = 8192.0
EARTH_CIRCUMFERENCE_KM = 40075.016686
PROFILE_ID = "P3"
TARGET_CELL_AREA_KM2 = 2100.0
MIN_AREA_FACTOR = 0.55
MAX_AREA_FACTOR = 1.65
COAST_CLEARANCE_KM = 2.0

# The two actual land neighbours of La Coruña, not Orense (which does not
# border it).  Their target counts come from the same Galicia P3 table.
TERRITORIES = (
    {"id": "province:2848", "name": "Ла-Корунья", "city": Point(3904.66, 2998.56), "seed": 2848},
    {"id": "province:2849", "name": "Луго", "city": Point(3924.04, 3009.84), "seed": 2849},
    {"id": "province:1753", "name": "Понтеведра", "city": Point(3897.57, 3034.57), "seed": 1753},
)
_OCEAN_CELLS: list[dict[str, Any]] | None = None


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def as_polygon(rings: list[list[list[float]]]) -> Polygon:
    polygon = Polygon(rings[0], rings[1:])
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if isinstance(polygon, MultiPolygon):
        polygon = max(polygon.geoms, key=lambda item: item.area)
    if polygon.is_empty or not isinstance(polygon, Polygon):
        raise ValueError("geometry is not a usable polygon")
    return polygon


def load_provinces() -> dict[str, dict[str, Any]]:
    for path in (GEOMETRY_PATH, FALLBACK_GEOMETRY_PATH):
        if path.exists():
            provinces = {entry["id"]: entry for entry in load_json(path).get("provinces", [])}
            if all(item["id"] in provinces for item in TERRITORIES):
                return provinces
    raise FileNotFoundError("The three Galicia province polygons were not found")


def line_parts(geometry) -> list[LineString]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry] if geometry.length > 1e-6 else []
    if isinstance(geometry, MultiLineString):
        return [part for part in geometry.geoms if part.length > 1e-6]
    if isinstance(geometry, GeometryCollection):
        result: list[LineString] = []
        for part in geometry.geoms:
            result.extend(line_parts(part))
        return result
    return []


def polygon_parts(geometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry] if geometry.area > 1e-6 else []
    if isinstance(geometry, MultiPolygon):
        return [part for part in geometry.geoms if part.area > 1e-6]
    if isinstance(geometry, GeometryCollection):
        return [part for part in geometry.geoms if isinstance(part, Polygon) and part.area > 1e-6]
    return []


def sketch_turn_amplitude() -> float:
    """Convert the manual sketch into a coarse bend amplitude in world pixels."""
    if not DRAFT_PATH.exists():
        return 0.95
    simplified = []
    for stroke in load_json(DRAFT_PATH).get("strokes", []):
        if len(stroke) >= 2:
            line = LineString(stroke).simplify(0.35, preserve_topology=False)
            if line.length > 1.0:
                simplified.append(line)
    if not simplified:
        return 0.95
    mean_length = sum(line.length for line in simplified) / len(simplified)
    # The saved drawing has deliberate 0.5–2px directional shifts.  This is
    # the broad edge shape, not one-pixel hand tremor.
    return max(0.78, min(1.35, mean_length / 13.0))


def chaotic_line(origin: Point, angle_deg: float, seed: int, amplitude: float, diameter: float) -> LineString:
    """A directional random walk: many irregular turns, no smooth sine wave."""
    rng = random.Random(seed)
    theta = math.radians(angle_deg)
    dx, dy = math.cos(theta), math.sin(theta)
    nx, ny = -dy, dx
    span = max(45.0, diameter * 1.55)
    # At the actual province crossing this leaves about 8–12 visible bends,
    # matching the density of the hand-drawn yellow lines in the reference.
    knot_count = max(27, min(45, int(round((2.0 * span) / 3.5))))
    offset = 0.0
    points = []
    for index in range(knot_count):
        if 0 < index < knot_count - 1:
            offset += rng.uniform(-amplitude * 0.92, amplitude * 0.92)
            offset = max(-amplitude * 2.15, min(amplitude * 2.15, offset))
        else:
            offset = 0.0
        t = -span + 2.0 * span * index / (knot_count - 1)
        points.append((origin.x + dx * t + nx * offset, origin.y + dy * t + ny * offset))
    return LineString(points)


def split_once(poly: Polygon, angle_deg: float, offset: float, seed: int, amplitude: float) -> tuple[Polygon, Polygon] | None:
    theta = math.radians(angle_deg)
    nx, ny = -math.sin(theta), math.cos(theta)
    center = poly.representative_point()
    origin = Point(center.x + nx * offset, center.y + ny * offset)
    min_x, min_y, max_x, max_y = poly.bounds
    cutter = chaotic_line(origin, angle_deg, seed, amplitude, math.hypot(max_x - min_x, max_y - min_y))
    pieces = polygon_parts(split(poly, cutter))
    return (pieces[0], pieces[1]) if len(pieces) == 2 else None


def best_balanced_split(poly: Polygon, angle_deg: float, seed: int, amplitude: float, city: Point | None) -> tuple[Polygon, Polygon]:
    best = None
    # Search the offset of a single graph edge rather than creating an
    # independent partition.  This preserves the branch-to-spine topology.
    # Area balancing only needs a handful of broad placements; a dense sweep
    # against the full high-detail province ring is slow without improving the
    # visible, hand-drawn character of the edge.
    # Select an offset against a light working outline, then perform exactly
    # one expensive split on the authoritative high-detail province geometry.
    # This matters for Galicia's very detailed coastline and does not affect
    # the final shared edge coordinates.
    scoring_poly = poly.simplify(0.12, preserve_topology=True)
    for step in (-20, -10, 0, 10, 20):
        candidate = split_once(scoring_poly, angle_deg, step * 0.30, seed, amplitude)
        if candidate is None:
            continue
        first, second = candidate
        ratio = first.area / max(second.area, 1e-9)
        score = abs(math.log(max(ratio, 1e-9)))
        if city is not None and poly.covers(city):
            border = first.boundary.intersection(second.boundary)
            distance = border.distance(city)
            if distance < 1.5:
                score += (1.5 - distance) * 6.0
        if best is None or score < best[0]:
            best = (score, step * 0.30)
    if best is None:
        raise RuntimeError("Unable to make a two-face graph split")
    # The chosen location normally works immediately; retain the other scored
    # offsets as a safety net for an intricate inlet in the exact contour.
    offsets = [best[1]] + [step * 0.30 for step in (-20, -10, 0, 10, 20) if step * 0.30 != best[1]]
    for offset in offsets:
        exact = split_once(poly, angle_deg, offset, seed, amplitude)
        if exact is not None:
            return exact
    raise RuntimeError("Unable to apply graph split to exact province contour")


def graph_faces(province: Polygon, count: int, city: Point, seed: int, amplitude: float) -> list[Polygon]:
    faces = [province]
    # After the first spine, every added edge only splits one existing face.
    # It thus terminates at an existing border and forms a graph branch, never
    # a rectangular cross or a radial Voronoi star.
    angles = (4.0, 78.0, 106.0, 49.0, 137.0, -31.0, 64.0)
    for split_index in range(count - 1):
        face_index = max(range(len(faces)), key=lambda index: faces[index].area)
        face = faces.pop(face_index)
        first, second = best_balanced_split(
            face,
            angles[split_index % len(angles)],
            seed + split_index * 97,
            # Plenty of visible turns, but restrained enough to avoid slicing
            # a thin accidental coastal sliver off the high-detail outline.
            amplitude * (0.68 if split_index == 0 else 0.60),
            city,
        )
        faces.extend((first, second))
    city_index = next(index for index, face in enumerate(faces) if face.covers(city))
    city_face = faces.pop(city_index)
    return [city_face] + sorted(faces, key=lambda face: (face.centroid.x, face.centroid.y))


def ray_to_boundary(poly: Polygon, screen_angle_deg: float) -> Point:
    """Farthest intersection of a screen-space ray with the outer contour."""
    center = poly.representative_point()
    angle = math.radians(screen_angle_deg)
    span = max(poly.bounds[2] - poly.bounds[0], poly.bounds[3] - poly.bounds[1]) * 4.0
    ray = LineString([(center.x, center.y), (center.x + math.cos(angle) * span, center.y + math.sin(angle) * span)])
    candidates = [part for part in ray.intersection(poly.boundary).geoms] if hasattr(ray.intersection(poly.boundary), "geoms") else [ray.intersection(poly.boundary)]
    points = [part for part in candidates if isinstance(part, Point)]
    if not points:
        raise RuntimeError("Unable to locate southwest contour endpoints")
    return max(points, key=lambda point: point.distance(center))


def southwest_arc(poly: Polygon) -> list[tuple[float, float]]:
    """Get the exterior arc between west and south rays that occupies SW."""
    coords = list(poly.exterior.coords)[:-1]
    west = ray_to_boundary(poly, 180.0)
    south = ray_to_boundary(poly, 90.0)
    west_index = min(range(len(coords)), key=lambda index: Point(coords[index]).distance(west))
    south_index = min(range(len(coords)), key=lambda index: Point(coords[index]).distance(south))

    def walk(start: int, finish: int) -> list[tuple[float, float]]:
        result = [coords[start]]
        index = start
        while index != finish:
            index = (index + 1) % len(coords)
            result.append(coords[index])
        return result

    first = walk(west_index, south_index)
    second = walk(south_index, west_index)
    center = poly.representative_point()
    width = max(poly.bounds[2] - poly.bounds[0], 1e-6)
    height = max(poly.bounds[3] - poly.bounds[1], 1e-6)
    # Screen y grows southwards.  The southwest arc maximises westness+southness.
    def southwest_score(path: list[tuple[float, float]]) -> float:
        return sum((center.x - x) / width + (y - center.y) / height for x, y in path) / len(path)
    return first if southwest_score(first) >= southwest_score(second) else second


def southwest_contour_split(poly: Polygon, city: Point, coast_clearance_px: float) -> tuple[Polygon, Polygon]:
    """Split by a displaced copy of the southwest provincial contour.

    The two short endpoint links only close the topological cut.  The visible
    central part is a genuine echo of the province outline, unlike a straight
    divider; the renderer later removes its last 2 km near the sea.
    """
    outer_arc = LineString(southwest_arc(poly)).simplify(0.12, preserve_topology=False)
    best = None
    # A few deliberate bands are enough here.  Exhaustively splitting this
    # detailed coastal contour dozens of times is needlessly slow.
    for depth in [coast_clearance_px + step * 0.65 for step in (2, 5, 8, 11, 14, 17, 20, 23)]:
        inner = poly.buffer(-depth, join_style=2)
        if inner.is_empty:
            continue
        if isinstance(inner, MultiPolygon):
            inner = max(inner.geoms, key=lambda item: item.area)
        if not isinstance(inner, Polygon):
            continue
        # Buffering gives a contour that is guaranteed to be inside the
        # province.  Its southwest arc is the geometric echo we want.
        inner_arc = LineString(southwest_arc(inner)).simplify(0.12, preserve_topology=False)
        cut = LineString([outer_arc.coords[0], *inner_arc.coords, outer_arc.coords[-1]])
        pieces = polygon_parts(split(poly, cut))
        if len(pieces) != 2:
            continue
        first, second = pieces
        ratio = first.area / max(second.area, 1e-9)
        border = first.boundary.intersection(second.boundary)
        score = abs(math.log(max(ratio, 1e-9)))
        if border.distance(city) < 1.5:
            score += (1.5 - border.distance(city)) * 6.0
        if best is None or score < best[0]:
            best = (score, first, second)
    if best is None:
        raise RuntimeError("Unable to make southwest contour-echo split")
    return best[1], best[2]


def southwest_contour_echo(poly: Polygon, depth: float) -> LineString:
    """A stable interior echo of the southwest provincial silhouette."""
    inner = poly.buffer(-depth, join_style=2)
    if isinstance(inner, MultiPolygon):
        inner = max(inner.geoms, key=lambda item: item.area)
    if inner.is_empty or not isinstance(inner, Polygon):
        raise RuntimeError("Southwest contour echo has collapsed")
    return LineString(southwest_arc(inner)).simplify(0.08, preserve_topology=False)


def km_to_world_px(poly: Polygon, km: float) -> float:
    # Web Mercator scale at the local latitude; this gives a true 2-km ground
    # offset instead of treating map pixels as kilometres.
    y = poly.representative_point().y
    mercator_n = math.pi * (1.0 - 2.0 * y / WORLD_PX)
    latitude = math.atan(math.sinh(mercator_n))
    return km * WORLD_PX / EARTH_CIRCUMFERENCE_KM / max(math.cos(latitude), 1e-6)


def local_ocean(poly: Polygon):
    """Return nearby coastline curves without constructing the huge ocean polygon.

    ``world_ocean.json`` stores one world-spanning water polygon with hundreds
    of holes.  Building that full polygon just to trim a few local line ends
    is expensive; its rings themselves are the coastline we need here.
    """
    global _OCEAN_CELLS
    if not OCEAN_PATH.exists():
        return GeometryCollection()
    clip = box(*poly.bounds).buffer(5.0)
    if _OCEAN_CELLS is None:
        _OCEAN_CELLS = load_json(OCEAN_PATH).get("cells", [])
    coast_lines = []
    for entry in _OCEAN_CELLS:
        bbox = entry.get("bbox", [])
        if len(bbox) != 4 or bbox[2] < clip.bounds[0] or bbox[0] > clip.bounds[2] \
                or bbox[3] < clip.bounds[1] or bbox[1] > clip.bounds[3]:
            continue
        for ring in entry.get("rings", []):
            if len(ring) < 2:
                continue
            xs = [point[0] for point in ring]
            ys = [point[1] for point in ring]
            if max(xs) < clip.bounds[0] or min(xs) > clip.bounds[2] \
                    or max(ys) < clip.bounds[1] or min(ys) > clip.bounds[3]:
                continue
            # Clip before buffering: the matching world-ocean ring is often a
            # 30k-point world coastline, but we only need a 50px local window.
            coast_lines.extend(line_parts(LineString(ring).intersection(clip)))
    return unary_union(coast_lines) if coast_lines else GeometryCollection()


def rings_from_polygon(poly: Polygon) -> list[list[list[float]]]:
    def points(coords: Iterable[tuple[float, float]]) -> list[list[float]]:
        return [[round(float(x), 7), round(float(y), 7)] for x, y in coords]
    return [points(poly.exterior.coords)] + [points(ring.coords) for ring in poly.interiors]


def coordinates(line: LineString) -> list[list[float]]:
    return [[round(float(x), 7), round(float(y), 7)] for x, y in line.coords]


def internal_render_chains(polygons: list[Polygon], index: int, coast_guard) -> list[list[list[float]]]:
    chains: list[list[list[float]]] = []
    seen: set[tuple[tuple[float, float], ...]] = set()
    current = polygons[index]
    for other_index, other in enumerate(polygons):
        if other_index == index:
            continue
        shared = current.boundary.intersection(other.boundary)
        # Keep the cell geometry complete, but end the DRAWN internal line at
        # least 2 km before seawater.  Provincial borders remain untouched.
        visible = shared.difference(coast_guard) if not coast_guard.is_empty else shared
        for line in line_parts(visible):
            if line.length < 0.18:
                continue
            chain = coordinates(line.simplify(0.025, preserve_topology=True))
            key = tuple((round(point[0], 4), round(point[1], 4)) for point in chain)
            canonical = min(key, tuple(reversed(key)))
            if canonical not in seen:
                seen.add(canonical)
                chains.append(chain)
    return chains


def make_cells(spec: dict[str, Any], province_entry: dict[str, Any], amplitude: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    province = as_polygon(province_entry["rings"])
    # The layer renders only brd_open, while layer 4 owns the real outer
    # province contour.  A light working copy makes graph construction fast
    # without ever substituting or redrawing that contour on screen.
    partition_poly = province.simplify(0.10, preserve_topology=True)
    source_area_km2 = float(province_entry["area_km2"])
    cell_count = max(1, min(10, int(math.floor(source_area_km2 / TARGET_CELL_AREA_KM2 + 0.5))))
    ocean = local_ocean(province)
    coast_clearance_px = km_to_world_px(province, COAST_CLEARANCE_KM)
    coast_guard = ocean.buffer(coast_clearance_px)
    faces = graph_faces(partition_poly, cell_count, spec["city"], spec["seed"], amplitude)
    faces = [set_precision(face, 0.00001) for face in faces]
    total_world_area = sum(face.area for face in faces)
    southwest_echo_chains: list[list[list[float]]] = []
    if spec["id"] == "province:1753":
        # Reference to Leon cell 2: the visible southwest divider is not a
        # straight random cut, but an inward echo of the provincial silhouette.
        echo = southwest_contour_echo(partition_poly, coast_clearance_px + 2.4)
        for part in line_parts(echo.difference(coast_guard)):
            if part.length >= 0.18:
                southwest_echo_chains.append(coordinates(part))

    cells = []
    for index, face in enumerate(faces, start=1):
        area_km2 = source_area_km2 * face.area / total_world_area
        ratio = area_km2 / TARGET_CELL_AREA_KM2
        if not (MIN_AREA_FACTOR <= ratio <= MAX_AREA_FACTOR):
            raise RuntimeError(f"{spec['name']} cell {index} violates P3: {area_km2:.1f} km²")
        label = face.representative_point()
        cells.append({
            "id": f"land_cell:{spec['id'].split(':')[-1]}:graph:{index:02d}",
            "name": f"{spec['name']} — {'городская клетка' if index == 1 else f'клетка {index}'}",
            "province_id": spec["id"],
            "profile_id": PROFILE_ID,
            "target_area_km2": TARGET_CELL_AREA_KM2,
            "area_km2": round(area_km2, 2),
            "rings": rings_from_polygon(face),
            "bbox": [round(value, 3) for value in face.bounds],
            "center": [round(face.centroid.x, 3), round(face.centroid.y, 3)],
            "label_point": [round(label.x, 3), round(label.y, 3)],
            # The two Pontevedra face polygons still follow the P3 area rule;
            # its shown SW boundary deliberately uses the province-contour
            # echo requested from the Leon-cell reference.
            "brd_open": southwest_echo_chains if spec["id"] == "province:1753" and index == 1 \
                else ([] if spec["id"] == "province:1753" else internal_render_chains(faces, index - 1, coast_guard)),
            "color": [0.18, 0.64, 0.95, 0.0],
        })
    meta = {
        "province_id": spec["id"],
        "name": spec["name"],
        "source_area_km2": source_area_km2,
        "cell_count": cell_count,
        "coast_clearance_km": COAST_CLEARANCE_KM,
        "coast_clearance_world_px": round(coast_clearance_px, 4),
        "areas_km2": [cell["area_km2"] for cell in cells],
    }
    return cells, meta


def main() -> None:
    provinces = load_provinces()
    amplitude = sketch_turn_amplitude()
    cells = []
    report = []
    for spec in TERRITORIES:
        province_cells, meta = make_cells(spec, provinces[spec["id"]], amplitude)
        cells.extend(province_cells)
        report.append(meta)
    payload = {
        "world_px": WORLD_PX,
        "cells": cells,
        "provenance": {
            "method": "manual_chaotic_graph_topology_v2",
            "manual_draft": "assets/cell_boundary_drafts_lacoruna_manual.json",
            "profile_source": "Все про клетки/ТАБЛИЦА_РЕГИОНАЛЬНЫХ_ПРОФИЛЕЙ_КЛЕТОК.xlsx",
            "profile": PROFILE_ID,
            "target_cell_area_km2": TARGET_CELL_AREA_KM2,
            "area_limits_km2": [TARGET_CELL_AREA_KM2 * MIN_AREA_FACTOR, TARGET_CELL_AREA_KM2 * MAX_AREA_FACTOR],
            "topology": "chaotic spine-and-branches graph; no Voronoi or grid",
            "coast_clearance_km": COAST_CLEARANCE_KM,
            "provinces": report,
        },
    }
    write_json(OUT_PATH, payload)
    print(f"wrote {OUT_PATH.relative_to(ROOT)}")
    for province in report:
        print(f"{province['name']}: {province['cell_count']} cells, {province['areas_km2']} km²")


if __name__ == "__main__":
    main()
