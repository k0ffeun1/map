#!/usr/bin/env python3
"""Compile topological boundary graphs into game land cells.

This is intentionally a different model from the earlier land-cell
generators.  A source file describes a planar graph: boundary anchors,
interior junctions and the shared lines between them.  The compiler turns
the faces of that graph into cell polygons.  It never invents Voronoi seeds,
does not recursively cut a polygon and does not add procedural waviness.

The graph is the source of truth.  Cell polygons are a derived, validated
rendering/game cache and may be rebuilt whenever the user edits graph nodes
or edges.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, MultiPolygon, Point, Polygon
from shapely.geometry import box
from shapely.ops import nearest_points, polygonize, snap, unary_union


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GRAPH = ROOT / "assets" / "cell_topology" / "lacoruna_boundary_graph.json"
DEFAULT_PROVINCES = ROOT / "assets" / "map_geometry" / "provinces.json"
# Unlike disposable raster bakes, this compact geometry cache is required by
# the runtime layer and is therefore intentionally kept in tracked assets.
DEFAULT_OUT = ROOT / "assets" / "cells_lacoruna_topology.json"
DEFAULT_REPORT = ROOT / "assets" / "cell_topology" / "lacoruna_cells_validation.json"
WORLD_OCEAN = ROOT / "assets" / "world_ocean.json"
EARTH_RADIUS_KM = 6371.0


# Стартовые игровые профили для текущего эталонного слоя T (Ла-Корунья).
# Это курируемая начальная классификация по модели из
# «КЛЕТКИ_КАРТЫ_ПОЛНЫЙ_АНАЛИЗ.md», а не утверждение, что каждая деталь уже
# подтверждена отдельным GIS-растром. Когда появится тематический источник
# высот/почв/покровов, он заменит только эти поля, не геометрию клеток.
# Первый профиль всегда закреплён за клеткой с городом — compile_graph()
# переносит её в начало ordered_faces.
CELL_CHARACTERISTICS = [
    {
        "cell_type": "urban",
        "surface_type": "land",
        "relief_type": "plain",
        "natural_cover_type": "grassland",
        "soil_type": "fertile",
        "climate_type": "oceanic",
        "moisture_type": "humid",
        "features": ["coast", "natural_harbor"],
        "resource": "fish",
        "development_type": "urban_periphery",
        "development_level": 3,
        "maturity": 0.92,
        "damage": 0.0,
        "road_level": 2,
        "irrigation_level": 0,
        "settlement_factor": 1.25,
        "usable_land_factor": 1.25,
        "province_center_status": "actual",
        "infrastructure_flags": ["port", "market"],
        "state_flags": [],
    },
    {
        "cell_type": "rural",
        "surface_type": "land",
        "relief_type": "hills",
        "natural_cover_type": "mixed_forest",
        "soil_type": "normal",
        "climate_type": "oceanic",
        "moisture_type": "humid",
        "features": ["coast", "rocky_shore"],
        "resource": "timber",
        "development_type": "forestry",
        "development_level": 1,
        "maturity": 0.55,
        "damage": 0.0,
        "road_level": 1,
        "irrigation_level": 0,
        "settlement_factor": 0.72,
        "usable_land_factor": 0.82,
        "infrastructure_flags": ["road"],
        "state_flags": [],
    },
    {
        "cell_type": "rural",
        "surface_type": "land",
        "relief_type": "hills",
        "natural_cover_type": "grassland",
        "soil_type": "fertile",
        "climate_type": "oceanic",
        "moisture_type": "humid",
        "features": ["coast", "river_valley"],
        "resource": "fish",
        "development_type": "villages",
        "development_level": 1,
        "maturity": 0.64,
        "damage": 0.0,
        "road_level": 1,
        "irrigation_level": 0,
        "settlement_factor": 0.88,
        "usable_land_factor": 1.04,
        "infrastructure_flags": ["road"],
        "state_flags": [],
    },
    {
        "cell_type": "rural",
        "surface_type": "land",
        "relief_type": "plain",
        "natural_cover_type": "grassland",
        "soil_type": "normal",
        "climate_type": "oceanic",
        "moisture_type": "humid",
        "features": ["river_valley"],
        "resource": "",
        "development_type": "farmland",
        "development_level": 2,
        "maturity": 0.76,
        "damage": 0.0,
        "road_level": 1,
        "irrigation_level": 0,
        "settlement_factor": 1.05,
        "usable_land_factor": 1.12,
        "infrastructure_flags": ["road"],
        "state_flags": [],
    },
]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def unproject_lat(y: float, world_px: float) -> float:
    n = math.pi - 2.0 * math.pi * y / world_px
    return math.degrees(math.atan(math.sinh(n)))


def km_per_world_px(y: float, world_px: float) -> float:
    lat = unproject_lat(y, world_px)
    return (2.0 * math.pi * EARTH_RADIUS_KM / world_px) * math.cos(math.radians(lat))


def polygon_parts(geometry: Any) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [] if geometry.is_empty else [geometry]
    if isinstance(geometry, MultiPolygon):
        return [part for part in geometry.geoms if not part.is_empty]
    if isinstance(geometry, GeometryCollection):
        return [part for part in geometry.geoms if isinstance(part, Polygon) and not part.is_empty]
    return []


def line_parts(geometry: Any) -> list[LineString]:
    if isinstance(geometry, LineString):
        return [] if geometry.is_empty else [geometry]
    if isinstance(geometry, MultiLineString):
        return [part for part in geometry.geoms if not part.is_empty]
    if isinstance(geometry, GeometryCollection):
        return [part for part in geometry.geoms if isinstance(part, LineString) and not part.is_empty]
    return []


def load_world_ocean(path: Path = WORLD_OCEAN) -> list[Polygon]:
    data = load_json(path)
    parts: list[Polygon] = []
    for cell in data.get("cells", []):
        rings = cell.get("rings", [])
        if not rings:
            continue
        polygon = Polygon(rings[0], rings[1:])
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        parts.extend(polygon_parts(polygon))
    return parts


def as_polygon(entry: dict[str, Any]) -> Polygon:
    rings = entry.get("rings", [])
    if not rings or len(rings[0]) < 3:
        raise ValueError("province has no usable rings")
    polygon: Polygon | MultiPolygon = Polygon(rings[0], rings[1:])
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if isinstance(polygon, MultiPolygon):
        polygon = max(polygon.geoms, key=lambda item: item.area)
    if polygon.is_empty or not isinstance(polygon, Polygon):
        raise ValueError("province geometry is not a polygon")
    return polygon


def rings_from_polygon(polygon: Polygon) -> list[list[list[float]]]:
    def points(coords: Iterable[tuple[float, float]]) -> list[list[float]]:
        return [[round(float(x), 6), round(float(y), 6)] for x, y in coords]

    return [points(polygon.exterior.coords)] + [points(ring.coords) for ring in polygon.interiors]


def line_coordinates(line: LineString) -> list[list[float]]:
    return [[round(float(x), 6), round(float(y), 6)] for x, y in line.coords]


def load_province(path: Path, province_id: str) -> tuple[dict[str, Any], Polygon]:
    entries = load_json(path).get("provinces", [])
    entry = next((item for item in entries if item.get("id") == province_id), None)
    if entry is None:
        raise ValueError(f"province not found: {province_id}")
    return entry, as_polygon(entry)


def playable_polygon_with_coast_offset(province: Polygon, world_px: float, offset_km: float) -> tuple[Polygon, float]:
    if offset_km <= 0.0:
        return province, 0.0

    margin_px = offset_km / max(km_per_world_px(province.representative_point().y, world_px), 0.001)
    clip = box(*province.bounds).buffer(margin_px + 3.0)
    nearby_ocean = []
    for ocean_polygon in load_world_ocean():
        if ocean_polygon.intersects(clip):
            part = ocean_polygon.intersection(clip)
            if not part.is_empty:
                nearby_ocean.append(part)
    if not nearby_ocean:
        return province, margin_px

    ocean_margin = unary_union(nearby_ocean).buffer(margin_px, quad_segs=8)
    playable = province.difference(ocean_margin)
    if not playable.is_valid:
        playable = playable.buffer(0)
    parts = polygon_parts(playable)
    if not parts:
        raise ValueError("coast offset removed the whole province")
    return max(parts, key=lambda item: item.area), margin_px


def build_edges(graph: dict[str, Any], province: Polygon) -> tuple[dict[str, Point], dict[str, LineString]]:
    smooth_iterations = int(graph.get("smooth_iterations", 0))
    roughen_iterations = int(graph.get("roughen_iterations", 0))
    roughen_amplitude_px = float(graph.get("roughen_amplitude_px", 0.0))
    roughen_decay = float(graph.get("roughen_decay", 0.55))
    admin_step_px = float(graph.get("admin_jagged_step_px", 0.0))
    admin_amplitude_px = float(graph.get("admin_jagged_amplitude_px", 0.0))
    admin_correlation = float(graph.get("admin_jagged_correlation", 0.55))
    nodes: dict[str, Point] = {}
    for raw_node in graph.get("nodes", []):
        node_id = str(raw_node["id"])
        point = Point(raw_node["point"])
        if raw_node.get("kind") == "boundary":
            point = nearest_points(point, province.boundary)[1]
        elif not province.covers(point):
            raise ValueError(f"interior node {node_id} is outside the province")
        nodes[node_id] = point

    edges: dict[str, LineString] = {}
    for raw_edge in graph.get("edges", []):
        edge_id = str(raw_edge["id"])
        start = nodes[str(raw_edge["from"])]
        end = nodes[str(raw_edge["to"])]
        middle = raw_edge.get("points", [])
        coords = [(start.x, start.y), *middle, (end.x, end.y)]
        coords = roughen_polyline(coords, edge_id, roughen_iterations, roughen_amplitude_px, roughen_decay)
        coords = admin_jagged_polyline(coords, edge_id, admin_step_px, admin_amplitude_px, admin_correlation)
        coords = smooth_polyline(coords, smooth_iterations)
        line = LineString(coords)
        if not line.is_simple or line.length <= 1e-6:
            raise ValueError(f"edge {edge_id} is self-intersecting or empty")
        if not province.buffer(1e-7).covers(line):
            raise ValueError(f"edge {edge_id} leaves the province")
        edges[edge_id] = line
    return nodes, edges


def sample_polyline(points: list[tuple[float, float]], step_px: float) -> list[tuple[float, float, float, float]]:
    samples: list[tuple[float, float, float, float]] = []
    if len(points) < 2:
        return [(points[0][0], points[0][1], 1.0, 0.0)] if points else []
    samples.append((points[0][0], points[0][1], points[1][0] - points[0][0], points[1][1] - points[0][1]))
    for left, right in zip(points, points[1:]):
        dx = right[0] - left[0]
        dy = right[1] - left[1]
        length = math.hypot(dx, dy)
        if length <= 1e-6:
            continue
        count = max(1, int(math.floor(length / max(step_px, 0.1))))
        for index in range(1, count + 1):
            t = min(1.0, index / count)
            samples.append((left[0] + dx * t, left[1] + dy * t, dx, dy))
    return samples


def admin_jagged_polyline(
    coords: list[Any],
    edge_id: str,
    step_px: float,
    amplitude_px: float,
    correlation: float,
) -> list[tuple[float, float]]:
    points = [(float(item[0]), float(item[1])) for item in coords]
    if len(points) < 2 or step_px <= 0.0 or amplitude_px <= 0.0:
        return points
    sampled = sample_polyline(points, step_px)
    if len(sampled) <= 2:
        return points
    corr = min(max(correlation, 0.0), 0.95)
    out: list[tuple[float, float]] = []
    previous_offset = 0.0
    for index, (x, y, dx, dy) in enumerate(sampled):
        if index == 0 or index == len(sampled) - 1:
            out.append((x, y))
            continue
        length = math.hypot(dx, dy)
        if length <= 1e-6:
            out.append((x, y))
            continue
        noise = stable_noise(edge_id, 1000, index)
        previous_offset = previous_offset * corr + noise * amplitude_px * (1.0 - corr)
        # Small tangent jitter keeps the border from looking like a sinusoid,
        # while the normal offset supplies the administrative-border teeth.
        tangent_noise = stable_noise(edge_id, 2000, index) * amplitude_px * 0.18
        nx = -dy / length
        ny = dx / length
        tx = dx / length
        ty = dy / length
        out.append((
            x + nx * previous_offset + tx * tangent_noise,
            y + ny * previous_offset + ty * tangent_noise,
        ))
    return out


def stable_noise(edge_id: str, iteration: int, segment_index: int) -> float:
    value = 2166136261
    for ch in f"{edge_id}:{iteration}:{segment_index}":
        value ^= ord(ch)
        value = (value * 16777619) & 0xFFFFFFFF
    return (value / 0xFFFFFFFF) * 2.0 - 1.0


def roughen_polyline(
    coords: list[Any],
    edge_id: str,
    iterations: int,
    amplitude_px: float,
    decay: float,
) -> list[tuple[float, float]]:
    points = [(float(item[0]), float(item[1])) for item in coords]
    amp = max(0.0, amplitude_px)
    for iteration in range(max(0, iterations)):
        if len(points) < 2 or amp <= 0.0:
            return points
        roughened: list[tuple[float, float]] = [points[0]]
        for segment_index, (left, right) in enumerate(zip(points, points[1:])):
            dx = right[0] - left[0]
            dy = right[1] - left[1]
            length = math.hypot(dx, dy)
            if length <= 1e-6:
                roughened.append(right)
                continue
            nx = -dy / length
            ny = dx / length
            capped_amp = min(amp, length * 0.32)
            offset = stable_noise(edge_id, iteration, segment_index) * capped_amp
            mx = (left[0] + right[0]) * 0.5 + nx * offset
            my = (left[1] + right[1]) * 0.5 + ny * offset
            roughened.append((mx, my))
            roughened.append(right)
        points = roughened
        amp *= decay
    return points


def smooth_polyline(coords: list[Any], iterations: int) -> list[tuple[float, float]]:
    points = [(float(item[0]), float(item[1])) for item in coords]
    for _ in range(max(0, iterations)):
        if len(points) < 3:
            return points
        smoothed: list[tuple[float, float]] = [points[0]]
        for left, right in zip(points, points[1:]):
            qx = left[0] * 0.75 + right[0] * 0.25
            qy = left[1] * 0.75 + right[1] * 0.25
            rx = left[0] * 0.25 + right[0] * 0.75
            ry = left[1] * 0.25 + right[1] * 0.75
            smoothed.append((qx, qy))
            smoothed.append((rx, ry))
        smoothed.append(points[-1])
        points = smoothed
    return points


def make_faces(province: Polygon, nodes: dict[str, Point], edges: dict[str, LineString]) -> list[Polygon]:
    # ``nearest_points`` gives an exact-looking floating point coordinate, but
    # GEOS will still treat it as a dangling endpoint unless the province ring
    # is explicitly noded at that anchor.  Snap only the outer border to the
    # graph's boundary nodes; interior edge shape remains untouched.
    boundary_nodes = MultiPoint([
        point for point in nodes.values() if point.distance(province.boundary) <= 1e-7
    ])
    noded_boundary = snap(province.boundary, boundary_nodes, 1e-5)
    network = unary_union([noded_boundary, *edges.values()])
    faces = [face for face in polygonize(network) if province.covers(face.representative_point())]
    if len(faces) < 2:
        raise ValueError("graph did not create more than one face")
    coverage = unary_union(faces)
    missing = province.difference(coverage).area
    outside = coverage.difference(province).area
    tolerance = max(1e-7, province.area * 1e-8)
    if missing > tolerance or outside > tolerance:
        raise ValueError(f"graph faces do not cover the province (missing={missing}, outside={outside})")
    return faces


def face_border_chains(face: Polygon, all_edges: dict[str, LineString]) -> tuple[list[list[list[float]]], list[str]]:
    chains: list[list[list[float]]] = []
    edge_ids: list[str] = []
    for edge_id, edge in all_edges.items():
        shared = face.boundary.intersection(edge)
        parts = [part for part in line_parts(shared) if part.length > 1e-5]
        if not parts:
            continue
        edge_ids.append(edge_id)
        chains.extend(line_coordinates(part) for part in parts)
    return chains, edge_ids


def compile_graph(graph_path: Path, provinces_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    graph = load_json(graph_path)
    province_id = str(graph["province_id"])
    province_entry, province = load_province(provinces_path, province_id)
    world_px = float(graph.get("world_px", 8192.0))
    coast_offset_km = float(graph.get("coast_offset_km", 0.0))
    topology_area, coast_offset_px = playable_polygon_with_coast_offset(province, world_px, coast_offset_km)
    nodes, edges = build_edges(graph, topology_area)
    faces = make_faces(topology_area, nodes, edges)
    city = Point(graph["city_point"]) if graph.get("city_point") else None
    city_source = city
    if city is not None and not topology_area.covers(city):
        city = nearest_points(city, topology_area)[1]
    source_area_km2 = float(province_entry.get("area_km2", 0.0))
    target_area = float(graph.get("target_area_km2", source_area_km2 / len(faces)))
    bounds = graph.get("area_ratio_limits", [0.5, 1.7])
    if len(bounds) != 2:
        raise ValueError("area_ratio_limits must contain min/max")

    ordered_faces = sorted(faces, key=lambda item: (item.centroid.y, item.centroid.x))
    city_index = next((index for index, face in enumerate(ordered_faces) if city is not None and face.covers(city)), None)
    if city is not None and city_index is None:
        city_index = min(range(len(ordered_faces)), key=lambda index: ordered_faces[index].distance(city))
    if city_index is not None:
        ordered_faces.insert(0, ordered_faces.pop(city_index))

    cells: list[dict[str, Any]] = []
    cell_edge_ids: dict[str, list[str]] = {}
    for index, face in enumerate(ordered_faces, start=1):
        cell_id = f"land_cell:{province_id.split(':')[-1]}:topology:{index:02d}"
        area_km2 = source_area_km2 * face.area / province.area
        ratio = area_km2 / target_area
        if not float(bounds[0]) <= ratio <= float(bounds[1]):
            raise ValueError(f"{cell_id} violates area profile: {area_km2:.1f} km² ({ratio:.2f}x)")
        outline, edge_ids = face_border_chains(face, edges)
        cell_edge_ids[cell_id] = edge_ids
        label = face.representative_point()
        name_suffix = "городская клетка" if city is not None and face.covers(city) else f"клетка {index:02d}"
        characteristics = CELL_CHARACTERISTICS[min(index - 1, len(CELL_CHARACTERISTICS) - 1)].copy()
        cells.append({
            "id": cell_id,
            "name": f"{graph.get('province_name', province_id)} — {name_suffix}",
            "province_id": province_id,
            "profile_id": graph.get("profile_id", "manual"),
            "area_km2": round(area_km2, 2),
            "target_area_km2": target_area,
            "rings": rings_from_polygon(face),
            "bbox": [round(value, 4) for value in face.bounds],
            "center": [round(face.centroid.x, 4), round(face.centroid.y, 4)],
            "label_point": [round(label.x, 4), round(label.y, 4)],
            "brd_open": outline,
            "topology_edge_ids": edge_ids,
            "color": [0.32, 0.84, 0.50, 0.0],
            **characteristics,
        })

    neighbours: dict[str, set[str]] = {cell["id"]: set() for cell in cells}
    for left_index, left in enumerate(cells):
        for right in cells[left_index + 1:]:
            if set(cell_edge_ids[left["id"]]) & set(cell_edge_ids[right["id"]]):
                neighbours[left["id"]].add(right["id"])
                neighbours[right["id"]].add(left["id"])
    for cell in cells:
        cell["neighbours"] = sorted(neighbours[cell["id"]])

    payload = {
        "world_px": world_px,
        "cells": cells,
        "provenance": {
            "method": "topology_first_boundary_graph_v1",
            "graph_source": str(graph_path.relative_to(ROOT)).replace("\\", "/"),
            "province_id": province_id,
            "coast_offset_km": coast_offset_km,
            "coast_offset_px": round(coast_offset_px, 6),
            "description": "Cells are faces of explicit shared boundary edges; no Voronoi, grid or recursive cuts.",
            "characteristics_source": "КЛЕТКИ_КАРТЫ_ПОЛНЫЙ_АНАЛИЗ.md; curated La Coruna baseline",
        },
    }
    report = {
        "ok": True,
        "graph": str(graph_path.relative_to(ROOT)).replace("\\", "/"),
        "province_id": province_id,
        "nodes": len(nodes),
        "edges": len(edges),
        "faces": len(cells),
        "city_cell_id": cells[0]["id"] if city_index is not None else "",
        "city_source_point": [round(city_source.x, 6), round(city_source.y, 6)] if city_source is not None else [],
        "city_used_point": [round(city.x, 6), round(city.y, 6)] if city is not None else [],
        "coast_offset_km": coast_offset_km,
        "coast_offset_px": round(coast_offset_px, 6),
        "topology_area_ratio": round(topology_area.area / province.area, 6),
        "cell_areas_km2": {cell["id"]: cell["area_km2"] for cell in cells},
        "adjacency": {cell["id"]: cell["neighbours"] for cell in cells},
    }
    return payload, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--provinces", type=Path, default=DEFAULT_PROVINCES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    payload, report = compile_graph(args.graph, args.provinces)
    write_json(args.out, payload)
    write_json(args.report, report)
    print(f"wrote {args.out.relative_to(ROOT)}: {report['faces']} cells, {report['edges']} shared edges")


if __name__ == "__main__":
    main()
