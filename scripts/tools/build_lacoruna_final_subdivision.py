"""Stage 5: build final playable Admin-2 polygons for La Coruna.

Pipeline:
    Q microcells -> K ownership -> Stage 4 political boundary cleanup
    -> Stage 5 polygonization + topology lock.

The authoritative coastal outline is NOT the Natural Earth ADM1 coastline.
For coastal provinces we use the exact gameplay coastline already produced by
layer 4 in assets/provinces_iberia_selection_2km.json. That dataset applies the
project-wide GAME_WATER_LAND_MARGIN_KM = 2.0 rule.

This script deliberately runs offline. Godot should only load the resulting
four polygons; it must not union 600 microcells or polygonize linework at
runtime.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Iterable

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.ops import polygonize, snap, unary_union

ROOT = Path(__file__).resolve().parents[2]

GROWTH_PATH = ROOT / "assets/subdivision_stages/lacoruna_competitive_growth.json"
MESH_PATH = ROOT / "assets/subdivision_stages/lacoruna_microcells.json"
GAMEPLAY_COAST_PATH = ROOT / "assets/provinces_iberia_selection_2km.json"
OUT_PATH = ROOT / "assets/subdivision_stages/lacoruna_final_subdivision.json"

EXPECTED_GROWTH_FORMAT = "province_competitive_growth/v1"
EXPECTED_MESH_FORMAT = "province_microcell_mesh/v1"
GAMEPLAY_PROVINCE_ID = "spain__la_coru_a"
GAMEPLAY_COAST_RULE_KM = 2.0
EXPECTED_ZONE_COUNT = 4

# Keep these values synchronized with SubdivisionBoundaryCleanupStage.gd.
RDP_TOLERANCE = 0.34
RESAMPLE_SPACING = 0.95
WAVINESS_AMPLITUDE = 0.22
WAVINESS_MACRO_CYCLES = 1.35
WAVINESS_MESO_CYCLES = 3.40
POINT_KEY_SCALE = 100000.0
ENDPOINT_EPSILON = 0.0001
SNAP_TOLERANCE = 0.00001
MIN_FACE_AREA = 1.0e-7
VALIDATION_AREA_REL_EPS = 2.0e-7
ADJACENCY_LENGTH_EPS = 1.0e-5


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise RuntimeError(f"{path}: expected JSON object")
    return data


def _polygon_from_rings(rings: list) -> Polygon:
    if not rings or len(rings[0]) < 3:
        return Polygon()
    poly = Polygon(rings[0], rings[1:])
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly


def _iter_polygons(geom) -> Iterable[Polygon]:
    if geom.is_empty:
        return
    if isinstance(geom, Polygon):
        yield geom
        return
    if isinstance(geom, MultiPolygon):
        for part in geom.geoms:
            if not part.is_empty:
                yield part
        return
    if isinstance(geom, GeometryCollection):
        for item in geom.geoms:
            yield from _iter_polygons(item)


def _iter_lines(geom) -> Iterable[LineString]:
    if geom.is_empty:
        return
    if isinstance(geom, LineString):
        if len(geom.coords) >= 2 and geom.length > 0.0:
            yield geom
        return
    if isinstance(geom, MultiLineString):
        for item in geom.geoms:
            yield from _iter_lines(item)
        return
    if isinstance(geom, GeometryCollection):
        for item in geom.geoms:
            yield from _iter_lines(item)


def _point_key(point: tuple[float, float]) -> tuple[int, int]:
    return (round(point[0] * POINT_KEY_SCALE), round(point[1] * POINT_KEY_SCALE))


def _points_close(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 <= ENDPOINT_EPSILON**2


def _pair_key(a: str, b: str) -> str:
    return f"{a}|{b}" if a < b else f"{b}|{a}"


def _stitch_pair_pieces(raw_pieces: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    pieces = [list(piece) for piece in raw_pieces if len(piece) >= 2]
    if not pieces:
        return []

    endpoint_map: dict[tuple[int, int], list[int]] = {}
    for index, piece in enumerate(pieces):
        for point in (piece[0], piece[-1]):
            endpoint_map.setdefault(_point_key(point), []).append(index)

    starts: list[int] = []
    for index, piece in enumerate(pieces):
        a_degree = len(endpoint_map.get(_point_key(piece[0]), []))
        b_degree = len(endpoint_map.get(_point_key(piece[-1]), []))
        if a_degree != 2 or b_degree != 2:
            starts.append(index)
    starts.extend(index for index in range(len(pieces)) if index not in starts)

    used: set[int] = set()
    result: list[list[tuple[float, float]]] = []

    def extend(chain: list[tuple[float, float]], at_end: bool) -> list[tuple[float, float]]:
        while True:
            anchor = chain[-1] if at_end else chain[0]
            candidates = endpoint_map.get(_point_key(anchor), [])
            # Degree != 2 means endpoint or political junction: never stitch through it.
            if len(candidates) != 2:
                break
            next_index = next((idx for idx in candidates if idx not in used), -1)
            if next_index < 0:
                break
            piece = pieces[next_index]
            ordered = piece if _points_close(piece[0], anchor) else list(reversed(piece))
            if not _points_close(ordered[0], anchor):
                break
            used.add(next_index)
            if at_end:
                chain.extend(ordered[1:])
            else:
                # Mirrors the Godot preview: insert each next point at index 0.
                for point in ordered[1:]:
                    chain.insert(0, point)
        return chain

    for start in starts:
        if start in used:
            continue
        chain = list(pieces[start])
        used.add(start)
        chain = extend(chain, True)
        chain = extend(chain, False)
        result.append(chain)
    return result


def _point_segment_distance(point, a, b) -> float:
    abx = b[0] - a[0]
    aby = b[1] - a[1]
    length_sq = abx * abx + aby * aby
    if length_sq <= 1.0e-12:
        return math.hypot(point[0] - a[0], point[1] - a[1])
    t = ((point[0] - a[0]) * abx + (point[1] - a[1]) * aby) / length_sq
    t = max(0.0, min(1.0, t))
    px = a[0] + abx * t
    py = a[1] + aby * t
    return math.hypot(point[0] - px, point[1] - py)


def _rdp(points: list[tuple[float, float]], epsilon: float) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return list(points)
    start = points[0]
    finish = points[-1]
    max_distance = -1.0
    split_index = -1
    for index in range(1, len(points) - 1):
        distance = _point_segment_distance(points[index], start, finish)
        if distance > max_distance:
            max_distance = distance
            split_index = index
    if max_distance <= epsilon or split_index < 0:
        return [start, finish]
    left = _rdp(points[: split_index + 1], epsilon)
    right = _rdp(points[split_index:], epsilon)
    return left + right[1:]


def _resample(points: list[tuple[float, float]], spacing: float) -> list[tuple[float, float]]:
    if len(points) <= 2 or spacing <= 0.0:
        return list(points)
    cumulative = [0.0]
    total = 0.0
    for index in range(1, len(points)):
        total += math.dist(points[index - 1], points[index])
        cumulative.append(total)
    if total <= spacing:
        return [points[0], points[-1]]

    result = [points[0]]
    target = spacing
    segment = 1
    while target < total and segment < len(points):
        while segment < len(cumulative) and cumulative[segment] < target:
            segment += 1
        if segment >= len(points):
            break
        prev_distance = cumulative[segment - 1]
        segment_length = max(cumulative[segment] - prev_distance, 1.0e-8)
        t = (target - prev_distance) / segment_length
        a = points[segment - 1]
        b = points[segment]
        result.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        target += spacing
    result.append(points[-1])
    return result


def _stable_phase(value: str) -> float:
    hash_value = 2166136261
    for byte in value.encode("utf-8"):
        hash_value = ((hash_value ^ byte) * 16777619) & 0x7FFFFFFF
    return math.fmod(float(hash_value) * 0.000001, math.tau)


def _cleanup_chain(raw: list[tuple[float, float]], pair: str) -> list[tuple[float, float]]:
    if len(raw) <= 2:
        return list(raw)
    simplified = _rdp(raw, RDP_TOLERANCE)
    if len(simplified) <= 2:
        return simplified
    sampled = _resample(simplified, RESAMPLE_SPACING)
    if len(sampled) <= 2:
        return sampled

    phase = _stable_phase(pair)
    result = list(sampled)
    for index in range(1, len(result) - 1):
        t = index / (len(result) - 1)
        tx = result[index + 1][0] - result[index - 1][0]
        ty = result[index + 1][1] - result[index - 1][1]
        length = math.hypot(tx, ty)
        if length <= 1.0e-8:
            continue
        nx = -ty / length
        ny = tx / length
        endpoint_weight = math.sin(math.pi * t)
        macro = math.sin(math.tau * WAVINESS_MACRO_CYCLES * t + phase)
        meso = math.sin(math.tau * WAVINESS_MESO_CYCLES * t + phase * 1.73)
        offset = (macro * 0.68 + meso * 0.32) * WAVINESS_AMPLITUDE * endpoint_weight
        result[index] = (result[index][0] + nx * offset, result[index][1] + ny * offset)
    result[0] = raw[0]
    result[-1] = raw[-1]
    return result


def _load_gameplay_area() -> MultiPolygon | Polygon:
    data = _load_json(GAMEPLAY_COAST_PATH)
    polygons: list[Polygon] = []
    part_prefix = GAMEPLAY_PROVINCE_ID + "__selection_part_"
    for cell in data.get("cells", []):
        if not isinstance(cell, dict):
            continue
        cell_id = str(cell.get("id", ""))
        if cell_id != GAMEPLAY_PROVINCE_ID and not cell_id.startswith(part_prefix):
            continue
        poly = _polygon_from_rings(cell.get("rings", []))
        if not poly.is_empty:
            polygons.append(poly)
    if not polygons:
        raise RuntimeError(f"gameplay coastline does not contain {GAMEPLAY_PROVINCE_ID}")
    area = unary_union(polygons)
    if not area.is_valid:
        area = area.buffer(0)
    return area


def _build_original_zone_geometry(mesh: dict, claims: dict[str, str], gameplay_area) -> dict[str, object]:
    by_zone: dict[str, list[Polygon]] = {}
    for cell in mesh.get("microcells", []):
        if not isinstance(cell, dict):
            continue
        cell_id = str(cell.get("id", ""))
        zone_id = claims.get(cell_id)
        if not zone_id:
            continue
        poly = _polygon_from_rings(cell.get("rings", []))
        if not poly.is_empty:
            by_zone.setdefault(zone_id, []).append(poly)

    result: dict[str, object] = {}
    for zone_id, parts in by_zone.items():
        geom = unary_union(parts).intersection(gameplay_area)
        if not geom.is_valid:
            geom = geom.buffer(0)
        result[zone_id] = geom
    return result


def _build_stage4_components(growth: dict, claims: dict[str, str], gameplay_area) -> list[dict]:
    pieces_by_pair: dict[str, list[list[tuple[float, float]]]] = {}
    for segment in growth.get("boundary_segments", []):
        if not isinstance(segment, dict):
            continue
        microcells = segment.get("microcells", [])
        points = segment.get("points", [])
        if not isinstance(microcells, list) or len(microcells) != 2 or not isinstance(points, list):
            continue
        zone_a = claims.get(str(microcells[0]), "")
        zone_b = claims.get(str(microcells[1]), "")
        if not zone_a or not zone_b or zone_a == zone_b:
            continue
        line = [(float(p[0]), float(p[1])) for p in points if isinstance(p, list) and len(p) >= 2]
        if len(line) < 2:
            continue
        pieces_by_pair.setdefault(_pair_key(zone_a, zone_b), []).append(line)

    components: list[dict] = []
    for pair in sorted(pieces_by_pair):
        for raw_chain in _stitch_pair_pieces(pieces_by_pair[pair]):
            clipped = LineString(raw_chain).intersection(gameplay_area)
            for raw_line in _iter_lines(clipped):
                raw = [(float(x), float(y)) for x, y in raw_line.coords]
                if len(raw) < 2:
                    continue
                cleaned = _cleanup_chain(raw, pair)
                clean_line = LineString(cleaned)
                used_fallback = False
                if not clean_line.is_simple or not gameplay_area.buffer(SNAP_TOLERANCE).covers(clean_line):
                    cleaned = _rdp(raw, RDP_TOLERANCE * 0.55)
                    clean_line = LineString(cleaned)
                    used_fallback = True
                if not gameplay_area.buffer(SNAP_TOLERANCE).covers(clean_line):
                    cleaned = raw
                    clean_line = LineString(cleaned)
                    used_fallback = True
                if not gameplay_area.buffer(SNAP_TOLERANCE).covers(clean_line):
                    raise RuntimeError(f"Stage 4 line {pair} still leaves gameplay coastline after fallback")
                components.append({
                    "pair": pair,
                    "raw": raw,
                    "clean": cleaned,
                    "fallback": used_fallback,
                })
    if not components:
        raise RuntimeError("no Stage 4 boundary components survived 2 km coast clipping")
    return components


def _point_is_endpoint(point: Point, line: LineString) -> bool:
    p = (point.x, point.y)
    a = tuple(line.coords[0])
    b = tuple(line.coords[-1])
    return _points_close(p, a) or _points_close(p, b)


def _intersection_is_allowed(intersection, first: LineString, second: LineString) -> bool:
    if intersection.is_empty:
        return True
    if isinstance(intersection, Point):
        return _point_is_endpoint(intersection, first) and _point_is_endpoint(intersection, second)
    if intersection.geom_type == "MultiPoint":
        return all(_point_is_endpoint(item, first) and _point_is_endpoint(item, second) for item in intersection.geoms)
    # Shared line segments between distinct political chains are never legal.
    return False


def _remove_cleanup_crossings(components: list[dict]) -> int:
    """Fallback cleaned components that create crossings absent in K topology."""
    fallback_indices: set[int] = set()
    lines = [LineString(item["clean"]) for item in components]
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            intersection = lines[i].intersection(lines[j])
            if not _intersection_is_allowed(intersection, lines[i], lines[j]):
                fallback_indices.add(i)
                fallback_indices.add(j)
    for index in fallback_indices:
        components[index]["clean"] = components[index]["raw"]
        components[index]["fallback"] = True

    # K raw topology must be planar. If this fails, stop instead of silently
    # producing a different administrative graph.
    lines = [LineString(item["clean"]) for item in components]
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            if not _intersection_is_allowed(lines[i].intersection(lines[j]), lines[i], lines[j]):
                raise RuntimeError(
                    f"boundary crossing remains after fallback: {components[i]['pair']} vs {components[j]['pair']}"
                )
    return len(fallback_indices)


def _polygonize_faces(gameplay_area, components: list[dict]) -> list[Polygon]:
    boundary_lines = [LineString(item["clean"]) for item in components]
    # Snap coastal endpoints to the exact layer-4 coastline, then node the full
    # network once. The same noded edge is therefore shared by both zones.
    boundary_lines = [snap(line, gameplay_area.boundary, SNAP_TOLERANCE) for line in boundary_lines]
    network = unary_union([gameplay_area.boundary, *boundary_lines])
    raw_faces = list(polygonize(network))

    faces: list[Polygon] = []
    for face in raw_faces:
        if face.area <= MIN_FACE_AREA:
            continue
        clipped = face.intersection(gameplay_area)
        for part in _iter_polygons(clipped):
            if part.area > MIN_FACE_AREA and gameplay_area.covers(part.representative_point()):
                faces.append(part)
    if not faces:
        raise RuntimeError("polygonize produced no faces")
    return faces


def _assign_faces_to_zones(
    faces: list[Polygon], original_zones: dict[str, object], zone_ids: list[str]
) -> dict[str, object]:
    assigned: dict[str, list[Polygon]] = {zone_id: [] for zone_id in zone_ids}
    for face in faces:
        overlaps = []
        for zone_id in zone_ids:
            source_geom = original_zones.get(zone_id)
            overlap_area = face.intersection(source_geom).area if source_geom is not None else 0.0
            overlaps.append((overlap_area, zone_id))
        overlaps.sort(key=lambda item: (item[0], item[1]), reverse=True)
        if overlaps[0][0] <= MIN_FACE_AREA:
            raise RuntimeError("polygonized face has no overlap with any K zone")
        assigned[overlaps[0][1]].append(face)

    result: dict[str, object] = {}
    for zone_id in zone_ids:
        if not assigned[zone_id]:
            raise RuntimeError(f"final zone {zone_id} received no polygon faces")
        geom = unary_union(assigned[zone_id])
        if not geom.is_valid:
            geom = geom.buffer(0)
        if geom.is_empty:
            raise RuntimeError(f"final zone {zone_id} is empty")
        result[zone_id] = geom
    return result


def _adjacency_pairs(zone_geoms: dict[str, object]) -> set[str]:
    zone_ids = sorted(zone_geoms)
    pairs: set[str] = set()
    for i, first_id in enumerate(zone_ids):
        for second_id in zone_ids[i + 1 :]:
            shared = zone_geoms[first_id].boundary.intersection(zone_geoms[second_id].boundary)
            if shared.length > ADJACENCY_LENGTH_EPS:
                pairs.add(_pair_key(first_id, second_id))
    return pairs


def _validate(
    gameplay_area,
    final_zones: dict[str, object],
    growth: dict,
    expected_pairs: set[str],
) -> dict:
    zone_ids = sorted(final_zones)
    if len(zone_ids) != EXPECTED_ZONE_COUNT:
        raise RuntimeError(f"expected {EXPECTED_ZONE_COUNT} final zones, got {len(zone_ids)}")

    area_eps = max(1.0e-6, gameplay_area.area * VALIDATION_AREA_REL_EPS)
    union = unary_union(list(final_zones.values()))
    missing_area = gameplay_area.difference(union).area
    extra_area = union.difference(gameplay_area).area
    if missing_area > area_eps:
        raise RuntimeError(f"final subdivision leaves uncovered gameplay area: {missing_area:.9f}")
    if extra_area > area_eps:
        raise RuntimeError(f"final subdivision leaves gameplay polygon: {extra_area:.9f}")

    max_overlap = 0.0
    for i, first_id in enumerate(zone_ids):
        geom = final_zones[first_id]
        if not geom.is_valid:
            raise RuntimeError(f"final zone {first_id} is invalid")
        for second_id in zone_ids[i + 1 :]:
            overlap = geom.intersection(final_zones[second_id]).area
            max_overlap = max(max_overlap, overlap)
            if overlap > area_eps:
                raise RuntimeError(f"final zones overlap: {first_id} / {second_id} = {overlap:.9f}")

    zone_meta = {str(zone.get("id", "")): zone for zone in growth.get("zones", []) if isinstance(zone, dict)}
    for zone_id in zone_ids:
        seed = zone_meta.get(zone_id, {}).get("seed_point", [])
        if isinstance(seed, list) and len(seed) >= 2:
            if not final_zones[zone_id].buffer(SNAP_TOLERANCE).covers(Point(float(seed[0]), float(seed[1]))):
                raise RuntimeError(f"seed left its final zone: {zone_id}")

    capital_anchor = growth.get("capital_anchor", {}).get("point", [])
    capital_zone_id = next(
        (zone_id for zone_id, meta in zone_meta.items() if str(meta.get("role", "")) == "capital"),
        "",
    )
    if capital_zone_id and isinstance(capital_anchor, list) and len(capital_anchor) >= 2:
        capital = Point(float(capital_anchor[0]), float(capital_anchor[1]))
        if not final_zones[capital_zone_id].buffer(SNAP_TOLERANCE).covers(capital):
            raise RuntimeError("provincial capital anchor left the capital final zone")

    final_pairs = _adjacency_pairs(final_zones)
    if final_pairs != expected_pairs:
        missing = sorted(expected_pairs - final_pairs)
        added = sorted(final_pairs - expected_pairs)
        raise RuntimeError(f"Stage 5 changed K/Stage4 adjacency; missing={missing}, added={added}")

    return {
        "zone_count": len(zone_ids),
        "gameplay_area_world_px2": round(gameplay_area.area, 9),
        "coverage_missing_world_px2": round(missing_area, 12),
        "coverage_extra_world_px2": round(extra_area, 12),
        "max_pair_overlap_world_px2": round(max_overlap, 12),
        "adjacency_pairs": sorted(final_pairs),
        "capital_zone_id": capital_zone_id,
        "capital_anchor_preserved": True,
        "seeds_preserved": True,
        "topology_locked": True,
    }


def _rings_from_polygon(poly: Polygon) -> list[list[list[float]]]:
    rings: list[list[list[float]]] = []
    rings.append([[round(float(x), 6), round(float(y), 6)] for x, y in poly.exterior.coords])
    for interior in poly.interiors:
        rings.append([[round(float(x), 6), round(float(y), 6)] for x, y in interior.coords])
    return rings


def _serialize_zone(zone_id: str, geom, meta: dict, total_area: float) -> dict:
    polygons = sorted(_iter_polygons(geom), key=lambda poly: poly.area, reverse=True)
    bounds = geom.bounds
    representative = geom.representative_point()
    return {
        "id": zone_id,
        "name": str(meta.get("name", zone_id)),
        "role": str(meta.get("role", "")),
        "source_id": str(meta.get("source_id", "")),
        "color": meta.get("color", [0.8, 0.8, 0.8, 0.45]),
        "seed_microcell_id": str(meta.get("seed_microcell_id", "")),
        "seed_point": meta.get("seed_point", []),
        "is_capital_zone": str(meta.get("role", "")) == "capital",
        "area_world_px2": round(geom.area, 9),
        "area_share": round(geom.area / total_area, 9) if total_area > 0 else 0.0,
        "bbox": [round(float(value), 6) for value in bounds],
        "label_point": [round(representative.x, 6), round(representative.y, 6)],
        "neighbors": [],
        "polygon_part_count": len(polygons),
        "polygons": [{"rings": _rings_from_polygon(poly)} for poly in polygons],
    }


def build() -> dict:
    growth = _load_json(GROWTH_PATH)
    mesh = _load_json(MESH_PATH)
    if growth.get("format") != EXPECTED_GROWTH_FORMAT:
        raise RuntimeError(f"unexpected growth format: {growth.get('format')}")
    if mesh.get("format") != EXPECTED_MESH_FORMAT:
        raise RuntimeError(f"unexpected mesh format: {mesh.get('format')}")

    zone_meta = {str(zone.get("id", "")): zone for zone in growth.get("zones", []) if isinstance(zone, dict)}
    zone_ids = sorted(zone_id for zone_id in zone_meta if zone_id)
    if len(zone_ids) != EXPECTED_ZONE_COUNT:
        raise RuntimeError(f"K must contain exactly {EXPECTED_ZONE_COUNT} zones, got {len(zone_ids)}")

    claims: dict[str, str] = {}
    for claim in growth.get("claims", []):
        if not isinstance(claim, dict):
            continue
        microcell_id = str(claim.get("microcell_id", ""))
        zone_id = str(claim.get("zone_id", ""))
        if microcell_id and zone_id:
            claims[microcell_id] = zone_id
    if not claims:
        raise RuntimeError("K contains no microcell claims")

    gameplay_area = _load_gameplay_area()
    original_zones = _build_original_zone_geometry(mesh, claims, gameplay_area)
    if set(original_zones) != set(zone_ids):
        raise RuntimeError("Q/K union did not produce all four source zones")

    components = _build_stage4_components(growth, claims, gameplay_area)
    crossing_fallback_count = _remove_cleanup_crossings(components)
    expected_pairs = {str(item["pair"]) for item in components}

    faces = _polygonize_faces(gameplay_area, components)
    final_zones = _assign_faces_to_zones(faces, original_zones, zone_ids)
    validation = _validate(gameplay_area, final_zones, growth, expected_pairs)

    zones = [_serialize_zone(zone_id, final_zones[zone_id], zone_meta[zone_id], gameplay_area.area) for zone_id in zone_ids]
    neighbors_by_id = {zone_id: [] for zone_id in zone_ids}
    for pair in validation["adjacency_pairs"]:
        first, second = pair.split("|", 1)
        neighbors_by_id[first].append(second)
        neighbors_by_id[second].append(first)
    for zone in zones:
        zone["neighbors"] = sorted(neighbors_by_id[zone["id"]])

    shared_boundaries = []
    for pair in validation["adjacency_pairs"]:
        first, second = pair.split("|", 1)
        shared = final_zones[first].boundary.intersection(final_zones[second].boundary)
        lines = []
        for line in _iter_lines(shared):
            lines.append([[round(float(x), 6), round(float(y), 6)] for x, y in line.coords])
        shared_boundaries.append({"pair": pair, "lines": lines, "length_world_px": round(shared.length, 9)})

    result = {
        "format": "province_final_subdivision/v1",
        "stage": {"number": 5, "name": "Финальные игровые полигоны и фиксация топологии"},
        "contract_id": str(growth.get("contract_id", "province_subdivision:la_coruna")),
        "province_id": str(growth.get("province_id", "province:2848")),
        "province_name": str(growth.get("province_name", "Ла-Корунья")),
        "world_px": float(mesh.get("world_px", 8192.0)),
        "source_growth_path": "res://assets/subdivision_stages/lacoruna_competitive_growth.json",
        "source_mesh_path": "res://assets/subdivision_stages/lacoruna_microcells.json",
        "source_stage4_algorithm": "res://scripts/SubdivisionBoundaryCleanupStage2km.gd",
        "gameplay_coast": {
            "source_path": "res://assets/provinces_iberia_selection_2km.json",
            "province_id": GAMEPLAY_PROVINCE_ID,
            "land_inset_km": GAMEPLAY_COAST_RULE_KM,
            "authoritative_outer_boundary": True,
        },
        "generation": {
            "method": "stage4_shared_boundary_polygonization",
            "zone_assignment": "maximum_overlap_with_K_microcell_union",
            "stage4_component_count": len(components),
            "stage4_fallback_component_count": sum(1 for item in components if item["fallback"]),
            "crossing_fallback_component_count": crossing_fallback_count,
            "polygonized_face_count": len(faces),
            "shared_boundary_storage": "single_geometry_per_zone_pair",
        },
        "capital_anchor": growth.get("capital_anchor", {}),
        "zones": zones,
        "shared_boundaries": shared_boundaries,
        "validation": validation,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate existing output against a freshly built result")
    args = parser.parse_args()

    result = build()
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not OUT_PATH.exists():
            raise SystemExit(f"missing {OUT_PATH.relative_to(ROOT)}")
        existing = OUT_PATH.read_text(encoding="utf-8")
        if existing != encoded:
            raise SystemExit("Stage 5 asset is stale; rerun build_lacoruna_final_subdivision.py")
        print("Stage 5 check OK")
        return

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(encoded, encoding="utf-8")
    validation = result["validation"]
    print(
        "Stage 5 built: "
        f"zones={validation['zone_count']}, "
        f"faces={result['generation']['polygonized_face_count']}, "
        f"missing={validation['coverage_missing_world_px2']}, "
        f"extra={validation['coverage_extra_world_px2']}, "
        f"adjacency={len(validation['adjacency_pairs'])}, "
        f"coast={GAMEPLAY_COAST_RULE_KM:.1f}km"
    )
    print(OUT_PATH.relative_to(ROOT))


if __name__ == "__main__":
    main()
