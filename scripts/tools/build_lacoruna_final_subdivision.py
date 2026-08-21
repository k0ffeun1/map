"""Build Stage 5 final playable polygons for La Coruna.

Q (600 microcells) -> K (4 connected owners) -> Stage 4 cleaned shared borders
-> Stage 5 four real polygons with stable IDs and locked topology.

The coastal outer boundary is the exact layer-4 gameplay coastline from
provinces_iberia_selection_2km.json (GAME_WATER_LAND_MARGIN_KM = 2.0).
All heavy geometry stays offline; Godot only loads the generated JSON.
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
COAST_PATH = ROOT / "assets/provinces_iberia_selection_2km.json"
OUT_PATH = ROOT / "assets/subdivision_stages/lacoruna_final_subdivision.json"

GAMEPLAY_PROVINCE_ID = "spain__la_coru_a"
COAST_RULE_KM = 2.0
EXPECTED_ZONE_COUNT = 4

# Must match SubdivisionBoundaryCleanupStage.gd.
RDP_TOLERANCE = 0.34
RESAMPLE_SPACING = 0.95
WAVINESS_AMPLITUDE = 0.22
WAVINESS_MACRO_CYCLES = 1.35
WAVINESS_MESO_CYCLES = 3.40
POINT_KEY_SCALE = 100000.0
ENDPOINT_EPSILON = 0.0001
SNAP_EPSILON = 0.00001
AREA_REL_EPSILON = 2.0e-7
ADJACENCY_EPSILON = 1.0e-5


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise RuntimeError(f"{path}: expected object")
    return data


def polygon_from_rings(rings: list) -> Polygon:
    if not rings or len(rings[0]) < 3:
        return Polygon()
    poly = Polygon(rings[0], rings[1:])
    return poly if poly.is_valid else poly.buffer(0)


def polygons(geom) -> Iterable[Polygon]:
    if geom.is_empty:
        return
    if isinstance(geom, Polygon):
        yield geom
    elif isinstance(geom, MultiPolygon):
        yield from geom.geoms
    elif isinstance(geom, GeometryCollection):
        for part in geom.geoms:
            yield from polygons(part)


def lines(geom) -> Iterable[LineString]:
    if geom.is_empty:
        return
    if isinstance(geom, LineString):
        if geom.length > 0 and len(geom.coords) >= 2:
            yield geom
    elif isinstance(geom, MultiLineString):
        for part in geom.geoms:
            yield from lines(part)
    elif isinstance(geom, GeometryCollection):
        for part in geom.geoms:
            yield from lines(part)


def pair_key(a: str, b: str) -> str:
    return f"{a}|{b}" if a < b else f"{b}|{a}"


def point_key(p: tuple[float, float]) -> tuple[int, int]:
    return round(p[0] * POINT_KEY_SCALE), round(p[1] * POINT_KEY_SCALE)


def close(a, b) -> bool:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 <= ENDPOINT_EPSILON**2


def stitch(raw_pieces: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    pieces = [list(p) for p in raw_pieces if len(p) >= 2]
    endpoint_map: dict[tuple[int, int], list[int]] = {}
    for i, piece in enumerate(pieces):
        endpoint_map.setdefault(point_key(piece[0]), []).append(i)
        endpoint_map.setdefault(point_key(piece[-1]), []).append(i)

    starts = []
    for i, piece in enumerate(pieces):
        if len(endpoint_map.get(point_key(piece[0]), [])) != 2 or len(endpoint_map.get(point_key(piece[-1]), [])) != 2:
            starts.append(i)
    starts += [i for i in range(len(pieces)) if i not in starts]
    used: set[int] = set()
    result = []

    def extend(chain, at_end: bool):
        while True:
            anchor = chain[-1] if at_end else chain[0]
            candidates = endpoint_map.get(point_key(anchor), [])
            if len(candidates) != 2:  # endpoint or political junction
                break
            nxt = next((i for i in candidates if i not in used), -1)
            if nxt < 0:
                break
            ordered = pieces[nxt] if close(pieces[nxt][0], anchor) else list(reversed(pieces[nxt]))
            if not close(ordered[0], anchor):
                break
            used.add(nxt)
            if at_end:
                chain.extend(ordered[1:])
            else:
                for p in ordered[1:]:
                    chain.insert(0, p)
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


def segment_distance(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if length2 <= 1e-12:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    return math.dist(p, (a[0] + dx * t, a[1] + dy * t))


def rdp(points_: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    if len(points_) <= 2:
        return list(points_)
    best, split = -1.0, -1
    for i in range(1, len(points_) - 1):
        d = segment_distance(points_[i], points_[0], points_[-1])
        if d > best:
            best, split = d, i
    if best <= eps or split < 0:
        return [points_[0], points_[-1]]
    left = rdp(points_[: split + 1], eps)
    right = rdp(points_[split:], eps)
    return left + right[1:]


def resample(points_: list[tuple[float, float]], spacing: float) -> list[tuple[float, float]]:
    if len(points_) <= 2:
        return list(points_)
    cumulative = [0.0]
    for i in range(1, len(points_)):
        cumulative.append(cumulative[-1] + math.dist(points_[i - 1], points_[i]))
    total = cumulative[-1]
    if total <= spacing:
        return [points_[0], points_[-1]]
    result = [points_[0]]
    target, segment = spacing, 1
    while target < total:
        while segment < len(cumulative) and cumulative[segment] < target:
            segment += 1
        if segment >= len(points_):
            break
        prev = cumulative[segment - 1]
        t = (target - prev) / max(cumulative[segment] - prev, 1e-8)
        a, b = points_[segment - 1], points_[segment]
        result.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        target += spacing
    result.append(points_[-1])
    return result


def stable_phase(value: str) -> float:
    h = 2166136261
    for byte in value.encode("utf-8"):
        h = ((h ^ byte) * 16777619) & 0x7FFFFFFF
    return math.fmod(h * 0.000001, math.tau)


def cleanup(raw: list[tuple[float, float]], pair: str) -> list[tuple[float, float]]:
    simplified = rdp(raw, RDP_TOLERANCE)
    if len(simplified) <= 2:
        return simplified
    sampled = resample(simplified, RESAMPLE_SPACING)
    if len(sampled) <= 2:
        return sampled
    phase = stable_phase(pair)
    out = list(sampled)
    for i in range(1, len(out) - 1):
        t = i / (len(out) - 1)
        tx, ty = out[i + 1][0] - out[i - 1][0], out[i + 1][1] - out[i - 1][1]
        length = math.hypot(tx, ty)
        if length <= 1e-8:
            continue
        nx, ny = -ty / length, tx / length
        macro = math.sin(math.tau * WAVINESS_MACRO_CYCLES * t + phase)
        meso = math.sin(math.tau * WAVINESS_MESO_CYCLES * t + phase * 1.73)
        offset = (macro * 0.68 + meso * 0.32) * WAVINESS_AMPLITUDE * math.sin(math.pi * t)
        out[i] = out[i][0] + nx * offset, out[i][1] + ny * offset
    out[0], out[-1] = raw[0], raw[-1]
    return out


def gameplay_area():
    data = load_json(COAST_PATH)
    found = []
    prefix = GAMEPLAY_PROVINCE_ID + "__selection_part_"
    for cell in data.get("cells", []):
        if not isinstance(cell, dict):
            continue
        cid = str(cell.get("id", ""))
        if cid == GAMEPLAY_PROVINCE_ID or cid.startswith(prefix):
            poly = polygon_from_rings(cell.get("rings", []))
            if not poly.is_empty:
                found.append(poly)
    if not found:
        raise RuntimeError("2 km layer-4 La Coruna polygon not found")
    geom = unary_union(found)
    return geom if geom.is_valid else geom.buffer(0)


def source_zone_geometries(mesh: dict, claims: dict[str, str], land) -> dict[str, object]:
    grouped: dict[str, list[Polygon]] = {}
    # Q format calls the 600 atoms `cells` (not `microcells`).
    for cell in mesh.get("cells", []):
        if not isinstance(cell, dict):
            continue
        zid = claims.get(str(cell.get("id", "")), "")
        if not zid:
            continue
        poly = polygon_from_rings(cell.get("rings", []))
        if not poly.is_empty:
            grouped.setdefault(zid, []).append(poly)
    result = {}
    for zid, parts in grouped.items():
        geom = unary_union(parts).intersection(land)
        result[zid] = geom if geom.is_valid else geom.buffer(0)
    return result


def stage4_components(growth: dict, claims: dict[str, str], land) -> list[dict]:
    grouped: dict[str, list[list[tuple[float, float]]]] = {}
    for seg in growth.get("boundary_segments", []):
        if not isinstance(seg, dict):
            continue
        mids, raw_points = seg.get("microcells", []), seg.get("points", [])
        if len(mids) != 2:
            continue
        za, zb = claims.get(str(mids[0]), ""), claims.get(str(mids[1]), "")
        if not za or not zb or za == zb:
            continue
        pts = [(float(p[0]), float(p[1])) for p in raw_points if isinstance(p, list) and len(p) >= 2]
        if len(pts) >= 2:
            grouped.setdefault(pair_key(za, zb), []).append(pts)

    result = []
    safe_land = land.buffer(SNAP_EPSILON)
    for pair in sorted(grouped):
        for chain in stitch(grouped[pair]):
            for clipped in lines(LineString(chain).intersection(land)):
                raw = [(float(x), float(y)) for x, y in clipped.coords]
                if len(raw) < 2:
                    continue
                clean = cleanup(raw, pair)
                line = LineString(clean)
                fallback = False
                if not line.is_simple or not safe_land.covers(line):
                    clean, fallback = rdp(raw, RDP_TOLERANCE * 0.55), True
                    line = LineString(clean)
                if not safe_land.covers(line):
                    clean, fallback = raw, True
                    line = LineString(clean)
                if not safe_land.covers(line):
                    raise RuntimeError(f"boundary {pair} leaves 2 km gameplay land")
                result.append({"pair": pair, "raw": raw, "clean": clean, "fallback": fallback})
    if not result:
        raise RuntimeError("no Stage 4 components after 2 km clip")
    return result


def endpoint(point: Point, line: LineString) -> bool:
    p = (point.x, point.y)
    return close(p, tuple(line.coords[0])) or close(p, tuple(line.coords[-1]))


def allowed_intersection(hit, a: LineString, b: LineString) -> bool:
    if hit.is_empty:
        return True
    if isinstance(hit, Point):
        return endpoint(hit, a) and endpoint(hit, b)
    if hit.geom_type == "MultiPoint":
        return all(endpoint(p, a) and endpoint(p, b) for p in hit.geoms)
    return False


def remove_cleanup_crossings(components: list[dict]) -> int:
    current = [LineString(item["clean"]) for item in components]
    bad: set[int] = set()
    for i in range(len(current)):
        for j in range(i + 1, len(current)):
            if not allowed_intersection(current[i].intersection(current[j]), current[i], current[j]):
                bad.update((i, j))
    for i in bad:
        components[i]["clean"] = components[i]["raw"]
        components[i]["fallback"] = True
    current = [LineString(item["clean"]) for item in components]
    for i in range(len(current)):
        for j in range(i + 1, len(current)):
            if not allowed_intersection(current[i].intersection(current[j]), current[i], current[j]):
                raise RuntimeError(f"raw K topology crosses: {components[i]['pair']} / {components[j]['pair']}")
    return len(bad)


def build_faces(land, components: list[dict]) -> list[Polygon]:
    political = [snap(LineString(item["clean"]), land.boundary, SNAP_EPSILON) for item in components]
    noded = unary_union([land.boundary, *political])
    result: list[Polygon] = []
    for face in polygonize(noded):
        clipped = face.intersection(land)
        for part in polygons(clipped):
            if part.area > 1e-7 and land.covers(part.representative_point()):
                result.append(part)
    if not result:
        raise RuntimeError("polygonize produced zero faces")
    return result


def assign_faces(faces: list[Polygon], source: dict[str, object], zone_ids: list[str]) -> dict[str, object]:
    assigned: dict[str, list[Polygon]] = {zid: [] for zid in zone_ids}
    for face in faces:
        scored = sorted(
            ((face.intersection(source[zid]).area, zid) for zid in zone_ids),
            reverse=True,
        )
        if scored[0][0] <= 1e-7:
            raise RuntimeError("polygonized face has no K owner")
        assigned[scored[0][1]].append(face)
    final = {}
    for zid in zone_ids:
        if not assigned[zid]:
            raise RuntimeError(f"final zone {zid} is empty")
        geom = unary_union(assigned[zid])
        final[zid] = geom if geom.is_valid else geom.buffer(0)
    return final


def adjacency(final: dict[str, object]) -> set[str]:
    ids = sorted(final)
    result = set()
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if final[a].boundary.intersection(final[b].boundary).length > ADJACENCY_EPSILON:
                result.add(pair_key(a, b))
    return result


def validate(land, final: dict[str, object], growth: dict, expected_pairs: set[str]) -> dict:
    ids = sorted(final)
    if len(ids) != EXPECTED_ZONE_COUNT:
        raise RuntimeError(f"expected 4 final zones, got {len(ids)}")
    eps = max(1e-6, land.area * AREA_REL_EPSILON)
    union = unary_union(list(final.values()))
    missing = land.difference(union).area
    extra = union.difference(land).area
    if missing > eps or extra > eps:
        raise RuntimeError(f"coverage failure: missing={missing}, extra={extra}")
    max_overlap = 0.0
    for i, a in enumerate(ids):
        if not final[a].is_valid:
            raise RuntimeError(f"invalid final polygon {a}")
        for b in ids[i + 1 :]:
            overlap = final[a].intersection(final[b]).area
            max_overlap = max(max_overlap, overlap)
            if overlap > eps:
                raise RuntimeError(f"overlap {a}/{b}: {overlap}")

    meta = {str(z.get("id", "")): z for z in growth.get("zones", []) if isinstance(z, dict)}
    for zid in ids:
        seed = meta[zid].get("seed_point", [])
        if len(seed) >= 2 and not final[zid].buffer(SNAP_EPSILON).covers(Point(float(seed[0]), float(seed[1]))):
            raise RuntimeError(f"seed left zone {zid}")
    capital_id = next((zid for zid in ids if str(meta[zid].get("role", "")) == "capital"), "")
    cap = growth.get("capital_anchor", {}).get("point", [])
    if capital_id and len(cap) >= 2 and not final[capital_id].buffer(SNAP_EPSILON).covers(Point(float(cap[0]), float(cap[1]))):
        raise RuntimeError("capital anchor left capital zone")

    actual_pairs = adjacency(final)
    if actual_pairs != expected_pairs:
        raise RuntimeError(
            f"adjacency changed: missing={sorted(expected_pairs-actual_pairs)}, added={sorted(actual_pairs-expected_pairs)}"
        )
    return {
        "zone_count": len(ids),
        "gameplay_area_world_px2": round(land.area, 9),
        "coverage_missing_world_px2": round(missing, 12),
        "coverage_extra_world_px2": round(extra, 12),
        "max_pair_overlap_world_px2": round(max_overlap, 12),
        "adjacency_pairs": sorted(actual_pairs),
        "capital_zone_id": capital_id,
        "capital_anchor_preserved": True,
        "seeds_preserved": True,
        "topology_locked": True,
    }


def rings(poly: Polygon) -> list[list[list[float]]]:
    out = [[[round(float(x), 6), round(float(y), 6)] for x, y in poly.exterior.coords]]
    out += [[[round(float(x), 6), round(float(y), 6)] for x, y in hole.coords] for hole in poly.interiors]
    return out


def serialize_zone(zid: str, geom, meta: dict, total: float) -> dict:
    parts = sorted(polygons(geom), key=lambda p: p.area, reverse=True)
    rp = geom.representative_point()
    return {
        "id": zid,
        "name": str(meta.get("name", zid)),
        "role": str(meta.get("role", "")),
        "source_id": str(meta.get("source_id", "")),
        "color": meta.get("color", [0.8, 0.8, 0.8, 0.45]),
        "seed_microcell_id": str(meta.get("seed_microcell_id", "")),
        "seed_point": meta.get("seed_point", []),
        "is_capital_zone": str(meta.get("role", "")) == "capital",
        "area_world_px2": round(geom.area, 9),
        "area_share": round(geom.area / total, 9),
        "bbox": [round(float(v), 6) for v in geom.bounds],
        "label_point": [round(rp.x, 6), round(rp.y, 6)],
        "neighbors": [],
        "polygon_part_count": len(parts),
        "polygons": [{"rings": rings(p)} for p in parts],
    }


def build() -> dict:
    growth, mesh, land = load_json(GROWTH_PATH), load_json(MESH_PATH), gameplay_area()
    if growth.get("format") != "province_competitive_growth/v1":
        raise RuntimeError("wrong K format")
    if mesh.get("format") != "province_microcell_mesh/v1":
        raise RuntimeError("wrong Q format")

    meta = {str(z.get("id", "")): z for z in growth.get("zones", []) if isinstance(z, dict)}
    zone_ids = sorted(zid for zid in meta if zid)
    if len(zone_ids) != EXPECTED_ZONE_COUNT:
        raise RuntimeError(f"K contains {len(zone_ids)} zones, expected 4")
    claims = {
        str(c.get("microcell_id", "")): str(c.get("zone_id", ""))
        for c in growth.get("claims", [])
        if isinstance(c, dict) and c.get("microcell_id") and c.get("zone_id")
    }
    source = source_zone_geometries(mesh, claims, land)
    if set(source) != set(zone_ids):
        raise RuntimeError(f"Q/K source-zone mismatch: source={sorted(source)}, K={zone_ids}")

    components = stage4_components(growth, claims, land)
    crossing_fallbacks = remove_cleanup_crossings(components)
    expected_pairs = {item["pair"] for item in components}
    faces = build_faces(land, components)
    final = assign_faces(faces, source, zone_ids)
    checks = validate(land, final, growth, expected_pairs)

    zone_records = [serialize_zone(zid, final[zid], meta[zid], land.area) for zid in zone_ids]
    neighbor_map = {zid: [] for zid in zone_ids}
    for pair in checks["adjacency_pairs"]:
        a, b = pair.split("|", 1)
        neighbor_map[a].append(b)
        neighbor_map[b].append(a)
    for zone in zone_records:
        zone["neighbors"] = sorted(neighbor_map[zone["id"]])

    shared = []
    for pair in checks["adjacency_pairs"]:
        a, b = pair.split("|", 1)
        border = final[a].boundary.intersection(final[b].boundary)
        shared.append({
            "pair": pair,
            "length_world_px": round(border.length, 9),
            "lines": [
                [[round(float(x), 6), round(float(y), 6)] for x, y in line.coords]
                for line in lines(border)
            ],
        })

    return {
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
            "land_inset_km": COAST_RULE_KM,
            "authoritative_outer_boundary": True,
        },
        "generation": {
            "method": "stage4_shared_boundary_polygonization",
            "zone_assignment": "maximum_overlap_with_K_microcell_union",
            "stage4_component_count": len(components),
            "stage4_fallback_component_count": sum(1 for c in components if c["fallback"]),
            "crossing_fallback_component_count": crossing_fallbacks,
            "polygonized_face_count": len(faces),
            "shared_boundary_storage": "single_geometry_per_zone_pair",
        },
        "capital_anchor": growth.get("capital_anchor", {}),
        "zones": zone_records,
        "shared_boundaries": shared,
        "validation": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = build()
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not OUT_PATH.exists() or OUT_PATH.read_text(encoding="utf-8") != encoded:
            raise SystemExit("Stage 5 asset missing or stale")
        print("Stage 5 check OK")
        return
    OUT_PATH.write_text(encoded, encoding="utf-8")
    v = result["validation"]
    print(
        f"Stage 5 built: zones={v['zone_count']}, faces={result['generation']['polygonized_face_count']}, "
        f"missing={v['coverage_missing_world_px2']}, extra={v['coverage_extra_world_px2']}, "
        f"overlap={v['max_pair_overlap_world_px2']}, coast={COAST_RULE_KM:.1f}km"
    )
    print(OUT_PATH.relative_to(ROOT))


if __name__ == "__main__":
    main()
