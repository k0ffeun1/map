#!/usr/bin/env python3
"""Stage 6: universal final subdivision generator.

This turns the proven La-Coruna pipeline into a province-agnostic offline
builder:

    province -> atomic Voronoi substrate -> connected competitive graph growth
    -> cleaned shared political borders -> topology-locked final polygons

The generator deliberately uses no terrain, rivers, relief or gameplay cities.
A real provincial capital is used only when an existing coordinate source is
available.  Otherwise an interior representative point is used as a technical
anchor.

Iberia keeps the existing regional-table district counts by reading the already
versioned Political Claims layer.  Coastal Iberian geometry uses the exact
layer-4 2 km gameplay coastline.  Non-Iberian stress cases derive the same
2 km sea inset from the project's world-ocean mask; land borders are untouched.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.ops import nearest_points, polygonize, unary_union
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_subdivision_microcells as q
import build_subdivision_competitive_growth as k
import build_lacoruna_final_subdivision as stage5

GEOMETRY_PATH = ROOT / "assets" / "map_geometry" / "provinces.json"
IDENTITY_PATH = ROOT / "assets" / "game_data" / "provinces.json"
IBERIA_2KM_PATH = ROOT / "assets" / "provinces_iberia_selection_2km.json"
IBERIA_BASELINE_PATH = ROOT / "assets" / "cells_iberia_regional_political_claims.json"
IBERIA_CITIES_PATH = ROOT / "assets" / "province_cities_iberia.json"
WORLD_OCEAN_PATH = ROOT / "assets" / "world_ocean.json"
OUT_PATH = ROOT / "assets" / "subdivision_stage6" / "final_subdivisions.json"
MANIFEST_PATH = ROOT / "assets" / "subdivision_stage6" / "test_manifest.json"
REPORT_PATH = ROOT / "reports" / "stage6_universal_subdivisions.json"

WORLD_PX = 8192.0
COAST_RULE_KM = 2.0
IBERIA_COUNTRY_PREFIXES = ("spain__", "portugal__", "andorra__")
ATOMS_PER_ZONE = 80
MIN_ATOMS = 120
MAX_ATOMS = 560
BALANCE_ITERATIONS = 160
BALANCE_GAIN = 1.35
COAST_CONTACT_EPSILON = 0.002
CUTTER_EXTENSION_WORLD_PX = 0.025
GEOMETRY_EPSILON = 1.0e-7
COVERAGE_EPSILON = 2.0e-6


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def polygon_parts(geometry: Any) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, (MultiPolygon, GeometryCollection)) or hasattr(geometry, "geoms"):
        return [part for part in geometry.geoms if isinstance(part, Polygon) and not part.is_empty and part.area > GEOMETRY_EPSILON]
    return []


def line_parts(geometry: Any) -> list[LineString]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry] if geometry.length > GEOMETRY_EPSILON and len(geometry.coords) >= 2 else []
    if isinstance(geometry, (MultiLineString, GeometryCollection)) or hasattr(geometry, "geoms"):
        result: list[LineString] = []
        for part in geometry.geoms:
            result.extend(line_parts(part))
        return result
    return []


def polygon_from_rings(rings: list[Any]) -> Polygon | None:
    if not rings or len(rings[0]) < 3:
        return None
    geometry = Polygon(rings[0], rings[1:])
    if not geometry.is_valid:
        geometry = geometry.buffer(0)
    parts = polygon_parts(geometry)
    return max(parts, key=lambda item: item.area) if parts else None


def rings_from_polygon(polygon: Polygon) -> list[list[list[float]]]:
    def pts(coords: Iterable[tuple[float, float]]) -> list[list[float]]:
        return [[round(float(x), 6), round(float(y), 6)] for x, y in coords]
    return [pts(polygon.exterior.coords)] + [pts(ring.coords) for ring in polygon.interiors]


def shape_parts_payload(geometry: Any) -> list[dict[str, Any]]:
    parts = sorted(polygon_parts(geometry), key=lambda item: (-item.area, item.centroid.x, item.centroid.y))
    return [{"rings": rings_from_polygon(part)} for part in parts]


def geometry_from_entry(entry: dict[str, Any]) -> Any:
    rings = entry.get("rings", [])
    if not rings:
        return Polygon()
    geometry = Polygon(rings[0], rings[1:])
    if not geometry.is_valid:
        geometry = geometry.buffer(0)
    return geometry


def km_per_world_px(y: float) -> float:
    mercator_n = math.pi - 2.0 * math.pi * y / WORLD_PX
    latitude = math.degrees(math.atan(math.sinh(mercator_n)))
    return 2.0 * math.pi * q.EARTH_RADIUS_KM / WORLD_PX * math.cos(math.radians(latitude))


def area_km2(geometry: Any) -> float:
    if geometry.is_empty:
        return 0.0
    scale = km_per_world_px(float(geometry.representative_point().y))
    return float(geometry.area) * scale * scale


def aspect_ratio(polygon: Polygon) -> float:
    rectangle = polygon.minimum_rotated_rectangle
    coords = list(rectangle.exterior.coords)
    if len(coords) < 5:
        return 1.0
    lengths = [math.dist(coords[index], coords[index + 1]) for index in range(4)]
    positive = [value for value in lengths if value > 1.0e-9]
    return max(positive) / min(positive) if positive else 1.0


def compactness(geometry: Any) -> float:
    if geometry.is_empty or geometry.length <= 1.0e-9:
        return 0.0
    return float(4.0 * math.pi * geometry.area / (geometry.length * geometry.length))


def world_xy(lon: float, lat: float) -> tuple[float, float]:
    x = (lon + 180.0) / 360.0 * WORLD_PX
    lat = max(-85.05112878, min(85.05112878, lat))
    mercator = math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))
    y = (1.0 - mercator / math.pi) * 0.5 * WORLD_PX
    return x, y


def numeric_seed(province_id: str) -> int:
    match = re.search(r"(\d+)$", province_id)
    if match:
        return int(match.group(1))
    value = 2166136261
    for byte in province_id.encode("utf-8"):
        value = ((value ^ byte) * 16777619) & 0x7FFFFFFF
    return value


class Sources:
    def __init__(self) -> None:
        identity_document = read_json(IDENTITY_PATH)
        self.identity = {str(item["id"]): item for item in identity_document.get("provinces", [])}
        self.by_legacy = {str(item.get("legacy_id", "")): item for item in self.identity.values()}

        geometry_document = read_json(GEOMETRY_PATH)
        self.geometry: dict[str, Any] = {}
        for entry in geometry_document.get("provinces", []):
            pid = str(entry.get("id", ""))
            geometry = geometry_from_entry(entry)
            if pid and not geometry.is_empty:
                self.geometry[pid] = geometry

        self.iberia_2km_by_legacy: dict[str, list[Polygon]] = defaultdict(list)
        selection = read_json(IBERIA_2KM_PATH)
        legacy_ids = sorted((legacy for legacy in self.by_legacy if legacy), key=len, reverse=True)
        for cell in selection.get("cells", []):
            cid = str(cell.get("id", ""))
            legacy = next((item for item in legacy_ids if cid == item or cid.startswith(item + "__selection_part_")), "")
            if not legacy:
                continue
            polygon = polygon_from_rings(cell.get("rings", []))
            if polygon is not None:
                self.iberia_2km_by_legacy[legacy].append(polygon)

        self.baseline_counts: Counter[str] = Counter()
        if IBERIA_BASELINE_PATH.exists():
            for cell in read_json(IBERIA_BASELINE_PATH).get("cells", []):
                pid = str(cell.get("province_id", ""))
                if pid:
                    self.baseline_counts[pid] += 1

        self.city_by_province_name: dict[str, dict[str, Any]] = {}
        if IBERIA_CITIES_PATH.exists():
            for city in read_json(IBERIA_CITIES_PATH).get("cities", []):
                self.city_by_province_name.setdefault(str(city.get("province", "")), city)

        self.ocean_parts: list[Polygon] = []
        if WORLD_OCEAN_PATH.exists():
            for entry in read_json(WORLD_OCEAN_PATH).get("cells", []):
                rings = entry.get("rings", [])
                if not rings:
                    continue
                geometry = Polygon(rings[0], rings[1:])
                if not geometry.is_valid:
                    geometry = geometry.buffer(0)
                self.ocean_parts.extend(polygon_parts(geometry))
        self.ocean_tree = STRtree(self.ocean_parts) if self.ocean_parts else None

    def name(self, province_id: str) -> str:
        item = self.identity.get(province_id, {})
        return str(item.get("name") or item.get("slug") or province_id)

    def legacy(self, province_id: str) -> str:
        return str(self.identity.get(province_id, {}).get("legacy_id", ""))

    def exact_iberia_gameplay_land(self, province_id: str) -> Any | None:
        parts = self.iberia_2km_by_legacy.get(self.legacy(province_id), [])
        if not parts:
            return None
        geometry = unary_union(parts)
        return geometry if geometry.is_valid else geometry.buffer(0)

    def coast_neighbours(self, province: Any, distance_world_px: float) -> list[Polygon]:
        if self.ocean_tree is None:
            return []
        query = province.envelope.buffer(distance_world_px * 1.5)
        result = []
        for raw_index in self.ocean_tree.query(query):
            ocean = self.ocean_parts[int(raw_index)]
            if ocean.distance(province) <= distance_world_px * 1.2:
                result.append(ocean)
        return result

    def dynamic_gameplay_land(self, province: Any) -> tuple[Any, bool]:
        distance = COAST_RULE_KM / max(km_per_world_px(province.representative_point().y), 1.0e-9)
        oceans = self.coast_neighbours(province, distance)
        if not oceans:
            return province, False
        water = unary_union(oceans)
        if province.boundary.distance(water) > distance * 0.10:
            return province, False
        inset = province.difference(water.buffer(distance, join_style=2))
        if not inset.is_valid:
            inset = inset.buffer(0)
        if inset.is_empty or inset.area < province.area * 0.55:
            raise RuntimeError("2 km gameplay coast removed an implausible amount of province land")
        return inset, True

    def gameplay_land(self, province_id: str) -> tuple[Any, str, bool]:
        exact = self.exact_iberia_gameplay_land(province_id)
        if exact is not None:
            return exact, "assets/provinces_iberia_selection_2km.json", True
        parent = self.geometry[province_id]
        derived, coastal = self.dynamic_gameplay_land(parent)
        return derived, "derived_from_world_ocean_2km" if coastal else "source_admin1_inland", coastal

    def capital_anchor(self, province_id: str, land: Any) -> tuple[Point, str, str]:
        name = self.name(province_id)
        city = self.city_by_province_name.get(name)
        if city is not None:
            raw = city.get("pos", [])
            if isinstance(raw, list) and len(raw) >= 2:
                point = Point(float(raw[0]), float(raw[1]))
                if land.buffer(0.00001).covers(point):
                    return point, str(city.get("name", name)), "real_province_capital"
        point = land.representative_point()
        return point, name, "technical_interior_anchor"


def target_zone_count(sources: Sources, province_id: str, land: Any, iberia: bool) -> tuple[int, str]:
    if iberia and sources.baseline_counts.get(province_id, 0) > 0:
        return int(sources.baseline_counts[province_id]), "existing_regional_table"
    area = area_km2(land)
    count = max(2, min(8, int(round(area / 2100.0))))
    return count, "stress_test_area_fallback"


def allocate_zone_counts(parts: list[Polygon], total: int) -> tuple[list[tuple[Polygon, int]], list[Polygon]]:
    parts = sorted(parts, key=lambda item: -item.area)
    if not parts:
        return [], []
    if total <= 1:
        return [(parts[0], 1)], parts[1:]

    total_area = sum(part.area for part in parts)
    significant = [part for part in parts if part.area >= total_area * 0.012]
    process_count = min(total, max(1, len(significant)))
    processed = parts[:process_count]
    allocations = [1] * len(processed)
    remaining = total - len(processed)
    while remaining > 0:
        index = max(range(len(processed)), key=lambda i: processed[i].area / allocations[i])
        allocations[index] += 1
        remaining -= 1
    return list(zip(processed, allocations)), parts[process_count:]


def shared_edge_lengths(polygons: list[Polygon], adjacency: list[list[int]]) -> dict[tuple[int, int], float]:
    result: dict[tuple[int, int], float] = {}
    for first, neighbours in enumerate(adjacency):
        for second in neighbours:
            if second <= first:
                continue
            length = polygons[first].boundary.intersection(polygons[second].boundary).length
            if length > GEOMETRY_EPSILON:
                result[(first, second)] = float(length)
    return result


def micro_partition(component: Polygon, zone_count: int, anchor: Point, seed: int, zone_id_offset: int) -> tuple[dict[str, Any], dict[str, Any]]:
    if zone_count == 1:
        zid = f"zone:{zone_id_offset + 1:02d}"
        return {zid: component}, {
            "atom_count": 0,
            "seed_strategy": "single_zone",
            "selected_balance_iteration": 0,
            "boundary_component_count": 0,
            "welded_outer_endpoints": 0,
            "polygonized_face_count": 1,
        }

    atom_target = max(MIN_ATOMS, min(MAX_ATOMS, zone_count * ATOMS_PER_ZONE))
    spacing = max(0.035, math.sqrt(component.area / atom_target) * 0.52)
    usable_anchor = anchor if component.covers(anchor) else component.representative_point()
    points, actual_spacing = q.poisson_disk_samples(component, atom_target, spacing, seed, usable_anchor)
    owned = q.build_clipped_voronoi_cells(component, points)
    owned = q.merge_tiny_fragments(owned, component.area / atom_target * 0.05, atom_target, usable_anchor)
    atoms = [polygon for _owner, polygon in owned]
    adjacency = q.adjacency(atoms)
    if any(not neighbours for neighbours in adjacency):
        raise RuntimeError("Stage 6 atom without adjacency neighbour")

    positions = [(float(poly.centroid.x), float(poly.centroid.y)) for poly in atoms]
    capital_candidates = [index for index, poly in enumerate(atoms) if poly.covers(usable_anchor)]
    capital_index = capital_candidates[0] if capital_candidates else min(
        range(len(atoms)), key=lambda index: atoms[index].distance(usable_anchor)
    )
    seeds, distance_fields = k.choose_seeds(adjacency, positions, capital_index, zone_count)
    areas = [float(poly.area) for poly in atoms]
    edges = shared_edge_lengths(atoms, adjacency)
    atom_ids = [f"atom:{seed}:{index + 1:04d}" for index in range(len(atoms))]
    owners, zone_areas, biases, selected_iteration = k.assign_weighted_graph_voronoi(
        atom_ids,
        areas,
        adjacency,
        seeds,
        distance_fields,
        edges,
        BALANCE_ITERATIONS,
        BALANCE_GAIN,
    )

    zone_ids = [f"zone:{zone_id_offset + zone + 1:02d}" for zone in range(zone_count)]
    source: dict[str, Any] = {}
    for zone, zid in enumerate(zone_ids):
        pieces = [atoms[index] for index, owner in enumerate(owners) if owner == zone]
        geometry = unary_union(pieces)
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        source[zid] = geometry

    grouped: dict[str, list[list[tuple[float, float]]]] = defaultdict(list)
    for (first, second), _length in edges.items():
        za, zb = owners[first], owners[second]
        if za == zb:
            continue
        pair = stage5.pair_key(zone_ids[za], zone_ids[zb])
        shared = atoms[first].boundary.intersection(atoms[second].boundary)
        for line in line_parts(shared):
            coords = [(float(x), float(y)) for x, y in line.coords]
            if len(coords) >= 2:
                grouped[pair].append(coords)

    components: list[dict[str, Any]] = []
    safe = component.buffer(0.00002)
    for pair in sorted(grouped):
        for raw in stage5.stitch(grouped[pair]):
            clean = stage5.cleanup(raw, pair)
            clean_line = LineString(clean)
            fallback = False
            if not clean_line.is_simple or not safe.covers(clean_line):
                clean = stage5.rdp(raw, stage5.RDP_TOLERANCE * 0.55)
                clean_line = LineString(clean)
                fallback = True
            if not safe.covers(clean_line):
                clean = raw
                clean_line = LineString(clean)
                fallback = True
            if not safe.covers(clean_line):
                raise RuntimeError(f"clean political boundary leaves component: {pair}")
            components.append({"pair": pair, "raw": raw, "clean": clean, "fallback": fallback})
    stage5.remove_cleanup_crossings(components)

    cutters: list[LineString] = []
    welded = 0
    for item in components:
        points2 = list(item["clean"])
        if len(points2) < 2:
            continue
        for endpoint_index, neighbour_index in ((0, 1), (-1, -2)):
            point = Point(points2[endpoint_index])
            if point.distance(component.boundary) > COAST_CONTACT_EPSILON:
                continue
            boundary_point = nearest_points(point, component.boundary)[1]
            anchor2 = (float(boundary_point.x), float(boundary_point.y))
            neighbour = points2[neighbour_index]
            dx, dy = anchor2[0] - neighbour[0], anchor2[1] - neighbour[1]
            length = math.hypot(dx, dy)
            if length <= 1.0e-12:
                points2[endpoint_index] = anchor2
            else:
                points2[endpoint_index] = (
                    anchor2[0] + dx / length * CUTTER_EXTENSION_WORLD_PX,
                    anchor2[1] + dy / length * CUTTER_EXTENSION_WORLD_PX,
                )
            welded += 1
        cutters.append(LineString(points2))

    network = unary_union([component.boundary, *cutters])
    faces: list[Polygon] = []
    for face in polygonize(network):
        clipped = face.intersection(component)
        for part in polygon_parts(clipped):
            if part.area > GEOMETRY_EPSILON and component.covers(part.representative_point()):
                faces.append(part)
    if len(faces) < zone_count:
        raise RuntimeError(f"polygonize produced {len(faces)} faces for {zone_count} zones")

    assigned: dict[str, list[Polygon]] = {zid: [] for zid in zone_ids}
    for face in faces:
        scores = sorted(((face.intersection(source[zid]).area, zid) for zid in zone_ids), reverse=True)
        if not scores or scores[0][0] <= GEOMETRY_EPSILON:
            raise RuntimeError("final face has no graph-growth owner")
        assigned[scores[0][1]].append(face)

    final: dict[str, Any] = {}
    for zid in zone_ids:
        if not assigned[zid]:
            raise RuntimeError(f"final zone empty: {zid}")
        geometry = unary_union(assigned[zid]).intersection(component)
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        final[zid] = geometry

    return final, {
        "atom_count": len(atoms),
        "requested_atom_count": atom_target,
        "actual_minimum_seed_distance_world_px": round(actual_spacing, 6),
        "seed_strategy": "capital_or_interior_plus_graph_farthest",
        "selected_balance_iteration": selected_iteration,
        "balance_biases": [round(float(value), 6) for value in biases],
        "boundary_component_count": len(components),
        "cleanup_fallback_count": sum(bool(item["fallback"]) for item in components),
        "welded_outer_endpoints": welded,
        "polygonized_face_count": len(faces),
        "source_zone_area_ratio": round(max(zone_areas) / max(min(zone_areas), GEOMETRY_EPSILON), 6),
    }


def attach_satellites(final: dict[str, Any], satellites: list[Polygon]) -> int:
    attached = 0
    for satellite in satellites:
        zid = min(final, key=lambda item: final[item].distance(satellite))
        geometry = unary_union([final[zid], satellite])
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        final[zid] = geometry
        attached += 1
    return attached


def validate_final(land: Any, final: dict[str, Any], expected_count: int) -> dict[str, Any]:
    geoms = list(final.values())
    union = unary_union(geoms)
    missing = land.difference(union).area / max(land.area, GEOMETRY_EPSILON)
    extra = union.difference(land).area / max(land.area, GEOMETRY_EPSILON)
    overlap = max(0.0, (sum(item.area for item in geoms) - union.area) / max(land.area, GEOMETRY_EPSILON))
    invalid = [zid for zid, geom in final.items() if not geom.is_valid]
    empty = [zid for zid, geom in final.items() if geom.is_empty]
    multiparts = [zid for zid, geom in final.items() if len(polygon_parts(geom)) > 1]

    neighbours: dict[str, list[str]] = {zid: [] for zid in final}
    zone_ids = sorted(final)
    adjacency_pairs: list[str] = []
    for index, left in enumerate(zone_ids):
        for right in zone_ids[index + 1:]:
            shared = final[left].boundary.intersection(final[right].boundary)
            if shared.length > 1.0e-5:
                neighbours[left].append(right)
                neighbours[right].append(left)
                adjacency_pairs.append(f"{left}|{right}")

    areas = [geom.area for geom in geoms]
    compacts = [compactness(geom) for geom in geoms]
    primary_aspects = [max((aspect_ratio(part) for part in polygon_parts(geom)), default=1.0) for geom in geoms]
    area_ratio = max(areas) / max(min(areas), GEOMETRY_EPSILON)
    hard_ok = (
        len(final) == expected_count
        and missing <= COVERAGE_EPSILON
        and extra <= COVERAGE_EPSILON
        and overlap <= COVERAGE_EPSILON
        and not invalid
        and not empty
    )
    warnings: list[str] = []
    if multiparts:
        warnings.append("satellite island pieces attached to zones: " + ", ".join(multiparts))
    if min(compacts, default=1.0) < 0.075:
        warnings.append("very low compactness")
    if max(primary_aspects, default=1.0) > 15.0:
        warnings.append("very elongated final zone")
    if area_ratio > 3.5:
        warnings.append("large final-zone area imbalance")
    status = "PASS" if hard_ok and len(warnings) == 0 else ("ACCEPTED_WITH_WARNINGS" if hard_ok else "FAIL")
    return {
        "status": status,
        "hard_validation_passed": hard_ok,
        "zone_count": len(final),
        "coverage_missing_ratio": round(float(missing), 10),
        "coverage_extra_ratio": round(float(extra), 10),
        "overlap_ratio": round(float(overlap), 10),
        "invalid_zone_ids": invalid,
        "multipart_zone_ids": multiparts,
        "area_max_to_min_ratio": round(float(area_ratio), 6),
        "min_compactness": round(float(min(compacts, default=0.0)), 6),
        "max_primary_aspect_ratio": round(float(max(primary_aspects, default=1.0)), 6),
        "adjacency_pairs": adjacency_pairs,
        "neighbours": {zid: sorted(items) for zid, items in neighbours.items()},
        "warnings": warnings,
    }


def build_province(sources: Sources, province_id: str, role: str) -> dict[str, Any]:
    parent = sources.geometry.get(province_id)
    if parent is None or parent.is_empty:
        raise RuntimeError("source Admin-1 geometry missing")
    iberia = sources.legacy(province_id).startswith(IBERIA_COUNTRY_PREFIXES)
    land, coast_source, coastal = sources.gameplay_land(province_id)
    if not land.is_valid:
        land = land.buffer(0)
    parts = sorted(polygon_parts(land), key=lambda item: -item.area)
    if not parts:
        raise RuntimeError("gameplay land has no polygon parts")

    count, count_source = target_zone_count(sources, province_id, land, iberia)
    count = max(1, min(count, 12))
    anchor, anchor_name, anchor_source = sources.capital_anchor(province_id, land)
    allocations, satellites = allocate_zone_counts(parts, count)

    final: dict[str, Any] = {}
    generation_parts: list[dict[str, Any]] = []
    zone_offset = 0
    for component_index, (component, local_count) in enumerate(allocations):
        local_anchor = anchor if component.covers(anchor) else component.representative_point()
        local_final, stats = micro_partition(
            component,
            local_count,
            local_anchor,
            numeric_seed(province_id) + component_index * 100003,
            zone_offset,
        )
        final.update(local_final)
        stats["component_index"] = component_index
        stats["local_zone_count"] = local_count
        stats["component_area_km2"] = round(area_km2(component), 4)
        generation_parts.append(stats)
        zone_offset += local_count

    satellite_count = attach_satellites(final, satellites)
    validation = validate_final(land, final, count)
    if not validation["hard_validation_passed"]:
        raise RuntimeError(
            "hard final validation failed: missing=%s extra=%s overlap=%s zones=%s/%s"
            % (
                validation["coverage_missing_ratio"],
                validation["coverage_extra_ratio"],
                validation["overlap_ratio"],
                validation["zone_count"],
                count,
            )
        )

    zone_records: list[dict[str, Any]] = []
    neighbours = validation["neighbours"]
    for zid in sorted(final):
        geometry = final[zid]
        point = geometry.representative_point()
        min_x, min_y, max_x, max_y = geometry.bounds
        zone_records.append({
            "id": f"{province_id}:{zid}",
            "local_id": zid,
            "province_id": province_id,
            "parts": shape_parts_payload(geometry),
            "area_km2": round(area_km2(geometry), 4),
            "label_point": [round(float(point.x), 6), round(float(point.y), 6)],
            "bbox": [round(float(min_x), 6), round(float(min_y), 6), round(float(max_x), 6), round(float(max_y), 6)],
            "neighbors": [f"{province_id}:{other}" for other in neighbours.get(zid, [])],
            "multipart": len(polygon_parts(geometry)) > 1,
        })

    return {
        "province_id": province_id,
        "legacy_id": sources.legacy(province_id),
        "name": sources.name(province_id),
        "role": role,
        "country_prefix": sources.legacy(province_id).split("__", 1)[0],
        "target_zone_count": count,
        "target_count_source": count_source,
        "coastal": coastal,
        "gameplay_coast_rule_km": COAST_RULE_KM if coastal else 0.0,
        "gameplay_coast_source": coast_source,
        "source_area_km2": round(area_km2(parent), 4),
        "gameplay_area_km2": round(area_km2(land), 4),
        "capital_anchor": {
            "name": anchor_name,
            "point": [round(float(anchor.x), 6), round(float(anchor.y), 6)],
            "source": anchor_source,
        },
        "generation": {
            "method": "microcell_graph_growth_stage4_cleanup_topology_lock",
            "component_count": len(parts),
            "processed_component_count": len(allocations),
            "attached_satellite_component_count": satellite_count,
            "parts": generation_parts,
        },
        "validation": validation,
        "zones": zone_records,
    }


def find_named(sources: Sources, tokens: list[str], country_hints: tuple[str, ...] = ()) -> str | None:
    normalized = [token.casefold() for token in tokens]
    candidates: list[tuple[int, str]] = []
    for pid, item in sources.identity.items():
        if pid not in sources.geometry:
            continue
        name = str(item.get("name", "")).casefold()
        legacy = str(item.get("legacy_id", "")).casefold()
        if country_hints and not any(legacy.startswith(prefix) for prefix in country_hints):
            continue
        score = max((100 if name == token else 50 if token in name else 40 if token in legacy else 0) for token in normalized)
        if score:
            candidates.append((score, pid))
    return max(candidates, default=(0, ""))[1] or None


def nearest_named_fallback(sources: Sources, lon: float, lat: float, country_hints: tuple[str, ...] = ()) -> str:
    target = Point(world_xy(lon, lat))
    candidates = []
    for pid, geometry in sources.geometry.items():
        legacy = sources.legacy(pid).casefold()
        if country_hints and not any(legacy.startswith(prefix) for prefix in country_hints):
            continue
        candidates.append((geometry.distance(target), pid))
    if not candidates:
        raise RuntimeError("no province available for named fallback")
    return min(candidates)[1]


def select_controls(sources: Sources) -> dict[str, str]:
    lacoruna = "province:2848"
    london = find_named(sources, ["greater london", "london"], ("united_kingdom__", "england__"))
    if london is None:
        london = nearest_named_fallback(sources, -0.12, 51.51, ("united_kingdom__", "england__"))
    sicily = find_named(sources, ["sicily", "sicilia"], ("italy__",))
    if sicily is None:
        sicily = nearest_named_fallback(sources, 14.0, 37.6, ("italy__",))
    brittany = find_named(sources, ["bretagne", "brittany"], ("france__",))
    if brittany is None:
        brittany = nearest_named_fallback(sources, -3.0, 48.2, ("france__",))

    used = {lacoruna, london, sicily, brittany}
    europe: list[tuple[str, Polygon, float, float]] = []
    for pid, geometry in sources.geometry.items():
        if pid in used:
            continue
        parts = polygon_parts(geometry)
        if len(parts) != 1:
            continue
        polygon = parts[0]
        center = polygon.representative_point()
        if not (3500.0 <= center.x <= 5200.0 and 1550.0 <= center.y <= 3350.0):
            continue
        area = area_km2(polygon)
        if area < 45.0:
            continue
        europe.append((pid, polygon, area, aspect_ratio(polygon)))

    long_narrow_candidates = [item for item in europe if 500.0 <= item[2] <= 30000.0]
    long_narrow = max(long_narrow_candidates or europe, key=lambda item: (item[3], item[2]))[0]
    used.add(long_narrow)

    inland_candidates = []
    for pid, polygon, area, aspect in europe:
        if pid in used or area < 5000.0:
            continue
        scale = COAST_RULE_KM / max(km_per_world_px(polygon.representative_point().y), 1.0e-9)
        if not sources.coast_neighbours(polygon, scale):
            inland_candidates.append((pid, polygon, area, aspect))
    if not inland_candidates:
        inland_candidates = [item for item in europe if item[0] not in used]
    large_inland = max(inland_candidates, key=lambda item: item[2])[0]
    used.add(large_inland)

    small_candidates = [item for item in europe if item[0] not in used and 45.0 <= item[2] <= 1500.0]
    small = min(small_candidates or [item for item in europe if item[0] not in used], key=lambda item: item[2])[0]

    return {
        "ordinary_coastal": lacoruna,
        "dense_complex_london": london,
        "island_sicily": sicily,
        "complex_coast_brittany": brittany,
        "long_narrow_stress": long_narrow,
        "large_inland_stress": large_inland,
        "small_space_stress": small,
    }


def iberia_ids(sources: Sources) -> list[str]:
    result = []
    for pid in sources.geometry:
        legacy = sources.legacy(pid)
        if not legacy.startswith(IBERIA_COUNTRY_PREFIXES):
            continue
        if sources.exact_iberia_gameplay_land(pid) is None:
            continue
        result.append(pid)
    return sorted(result, key=lambda pid: numeric_seed(pid))


def build_all(include_controls: bool, include_iberia: bool, limit: int | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    sources = Sources()
    controls = select_controls(sources) if include_controls else {}
    roles: dict[str, list[str]] = defaultdict(list)
    for role, pid in controls.items():
        roles[pid].append(role)
    if include_iberia:
        for pid in iberia_ids(sources):
            roles[pid].append("iberia_full_set")

    ordered = sorted(roles, key=lambda pid: ("ordinary_coastal" not in roles[pid], numeric_seed(pid)))
    if limit is not None:
        ordered = ordered[:limit]

    provinces: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, pid in enumerate(ordered, start=1):
        role = "+".join(roles[pid])
        print(f"[{index}/{len(ordered)}] Stage6 {pid} {sources.name(pid)} role={role}", flush=True)
        try:
            record = build_province(sources, pid, role)
            provinces.append(record)
            print(
                f"  OK zones={record['target_zone_count']} status={record['validation']['status']} "
                f"coast={record['gameplay_coast_rule_km']}km",
                flush=True,
            )
        except Exception as error:
            failures.append({
                "province_id": pid,
                "name": sources.name(pid),
                "role": role,
                "error": f"{type(error).__name__}: {error}",
            })
            print(f"  FAIL {type(error).__name__}: {error}", flush=True)

    status_counts = Counter(item["validation"]["status"] for item in provinces)
    zone_count = sum(len(item["zones"]) for item in provinces)
    payload = {
        "format": "universal_final_subdivision/v1",
        "stage": {"number": 6, "name": "Универсальный генератор провинций"},
        "world_px": WORLD_PX,
        "coast_rule_km": COAST_RULE_KM,
        "generation_method": "Q_microcells__K_graph_growth__U_boundary_cleanup__Y_topology_lock",
        "province_count": len(provinces),
        "zone_count": zone_count,
        "provinces": provinces,
    }
    manifest = {
        "format": "stage6_test_manifest/v1",
        "controls": [
            {
                "role": role,
                "province_id": pid,
                "name": sources.name(pid),
                "legacy_id": sources.legacy(pid),
            }
            for role, pid in controls.items()
        ],
        "iberia_province_count": len(iberia_ids(sources)) if include_iberia else 0,
    }
    report = {
        "format": "stage6_validation_report/v1",
        "requested_province_count": len(ordered),
        "built_province_count": len(provinces),
        "failed_province_count": len(failures),
        "zone_count": zone_count,
        "status_counts": dict(sorted(status_counts.items())),
        "failures": failures,
        "hard_fail": bool(failures),
    }
    return payload, manifest, report


def encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Stage 6 universal province subdivisions")
    parser.add_argument("--controls-only", action="store_true")
    parser.add_argument("--iberia-only", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args()

    include_controls = not args.iberia_only
    include_iberia = not args.controls_only
    payload, manifest, report = build_all(include_controls, include_iberia, args.limit)

    outputs = ((OUT_PATH, payload), (MANIFEST_PATH, manifest), (REPORT_PATH, report))
    if args.check:
        stale = [str(path.relative_to(ROOT)) for path, value in outputs if not path.exists() or path.read_text(encoding="utf-8") != encoded(value)]
        if stale:
            raise SystemExit("Stage 6 outputs missing or stale: " + ", ".join(stale))
        print("Stage 6 check OK")
    else:
        for path, value in outputs:
            write_json(path, value)
        print(
            "Stage 6 built: provinces=%d zones=%d failures=%d statuses=%s"
            % (payload["province_count"], payload["zone_count"], report["failed_province_count"], report["status_counts"])
        )
        print(OUT_PATH.relative_to(ROOT))

    if report["failures"] and not args.allow_failures:
        raise SystemExit("Stage 6 has failed provinces; see reports/stage6_universal_subdivisions.json")


if __name__ == "__main__":
    main()
