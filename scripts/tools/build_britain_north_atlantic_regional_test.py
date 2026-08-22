#!/usr/bin/env python3
"""Build an additive Britain + North Atlantic gameplay-province/cell prototype.

Source geometry is the SAFE logical Admin-1 piece layer.  Existing Layer-8/world-cell
assets are never rewritten.  The script first assembles deliberately coarser gameplay
provinces, then partitions each gameplay province into finished Stage-6 cells using the
same micro-partition machinery as the India architecture test.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from shapely.geometry import Polygon
from shapely.ops import unary_union

import build_stage6_universal_subdivisions as s

ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = ROOT / "assets" / "game_data" / "britain_north_atlantic_gameplay_province_rules.json"
MANIFEST_PATH = ROOT / "assets" / "game_data" / "world_admin1_source_manifest.json"
PIECES_PATH = ROOT / "assets" / "map_geometry" / "world_admin1_safe_pieces.json"
GEOMETRY_OUT = ROOT / "assets" / "game_data" / "britain_north_atlantic_gameplay_provinces.json"
CELLS_OUT = ROOT / "assets" / "subdivision_stage6" / "britain_north_atlantic_subdivisions.json"
REPORT_OUT = ROOT / "reports" / "britain_north_atlantic_regional_test.json"
WORLD_PX = 8192.0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def ring_points(raw: Any) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    if not isinstance(raw, list):
        return points
    for point in raw:
        if isinstance(point, list) and len(point) >= 2:
            points.append((float(point[0]), float(point[1])))
    if len(points) >= 2 and points[0] == points[-1]:
        points = points[:-1]
    return points


def piece_geometry(piece: dict[str, Any]) -> Any:
    raw_rings = piece.get("rings", [])
    if not isinstance(raw_rings, list) or not raw_rings:
        return Polygon()
    outer = ring_points(raw_rings[0])
    holes = [ring_points(ring) for ring in raw_rings[1:]]
    holes = [ring for ring in holes if len(ring) >= 3]
    if len(outer) < 3:
        return Polygon()
    geometry = Polygon(outer, holes)
    if not geometry.is_valid:
        geometry = geometry.buffer(0)
    return geometry


def world_to_lonlat(x: float, y: float) -> tuple[float, float]:
    lon = x / WORLD_PX * 360.0 - 180.0
    mercator_n = math.pi - 2.0 * math.pi * y / WORLD_PX
    lat = math.degrees(math.atan(math.sinh(mercator_n)))
    return lon, lat


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return radius * 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def source_lonlat(geometry: Any) -> tuple[float, float]:
    point = geometry.representative_point()
    return world_to_lonlat(float(point.x), float(point.y))


def source_scope(meta: dict[str, Any], geometry: Any, rules: dict[str, Any]) -> str:
    admin = str(meta.get("admin", ""))
    name = str(meta.get("name", ""))
    names = rules["territory_source_names"]
    if admin == "United Kingdom":
        if name in set(names["scotland"]):
            return "scotland"
        if name in set(names["wales"]):
            return "wales"
        if name in set(names["northern_ireland"]):
            return "ireland"
        lon, lat = source_lonlat(geometry)
        if -7.2 <= lon <= 2.2 and 49.2 <= lat <= 55.6:
            return "england"
        return ""
    if admin == "Ireland":
        return "ireland"
    if admin == "Iceland":
        return "iceland"
    if admin == "Faroe Islands":
        return "faroe"
    if admin == "Isle of Man":
        return "isle_of_man"
    if admin == "Jersey":
        return "channel_islands"
    if admin == "Guernsey":
        return "channel_islands"
    return ""


def load_sources() -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, int]]:
    manifest = read_json(MANIFEST_PATH)
    pieces_doc = read_json(PIECES_PATH)
    meta_by_id = {
        str(item.get("logical_admin1_id", "")): item
        for item in manifest.get("source_features", [])
        if isinstance(item, dict) and str(item.get("logical_admin1_id", ""))
    }
    geoms: dict[str, list[Any]] = defaultdict(list)
    piece_count: dict[str, int] = Counter()
    for raw in pieces_doc.get("pieces", []):
        if not isinstance(raw, dict):
            continue
        pid = str(raw.get("logical_admin1_id", ""))
        if not pid:
            continue
        geom = piece_geometry(raw)
        if geom.is_empty:
            continue
        geoms[pid].append(geom)
        piece_count[pid] += 1
    geometry_by_id: dict[str, Any] = {}
    for pid, parts in geoms.items():
        geom = unary_union(parts)
        if not geom.is_valid:
            geom = geom.buffer(0)
        if not geom.is_empty:
            geometry_by_id[pid] = geom
    return meta_by_id, geometry_by_id, dict(piece_count)


def build_assignment(rules: dict[str, Any], meta_by_id: dict[str, dict[str, Any]], geometry_by_id: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    gameplay = rules.get("gameplay_provinces", [])
    province_by_id = {str(p["id"]): p for p in gameplay}
    territory_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for province in gameplay:
        territory_groups[str(province.get("territory", ""))].append(province)

    scope_by_source: dict[str, str] = {}
    candidates_by_scope: dict[str, list[str]] = defaultdict(list)
    for pid, geometry in geometry_by_id.items():
        meta = meta_by_id.get(pid, {})
        scope = source_scope(meta, geometry, rules)
        if scope:
            scope_by_source[pid] = scope
            candidates_by_scope[scope].append(pid)

    assignment: dict[str, str] = {}

    # Exact source-name / source-id routes take priority.
    for province in gameplay:
        gid = str(province["id"])
        territory = str(province.get("territory", ""))
        exact_names = set(str(x) for x in province.get("source_names", []))
        exact_names.update(str(x) for x in province.get("locked_names", []))
        exact_ids = set(str(x) for x in province.get("locked_ids", []))
        allowed_scopes = {territory}
        if territory == "england_island":
            allowed_scopes = {"england"}
        for pid in candidates_by_scope.get(next(iter(allowed_scopes)), []):
            meta = meta_by_id.get(pid, {})
            if pid in exact_ids or str(meta.get("name", "")) in exact_names:
                if pid in assignment and assignment[pid] != gid:
                    raise RuntimeError(f"source {pid} assigned twice: {assignment[pid]} and {gid}")
                assignment[pid] = gid

    # Territory groups with seeds absorb every still-unassigned source in that scope.
    seed_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for province in gameplay:
        if isinstance(province.get("seed_lonlat"), list) and len(province["seed_lonlat"]) >= 2:
            seed_groups[str(province.get("territory", ""))].append(province)

    for scope, sources in candidates_by_scope.items():
        effective_territory = scope
        seeded = seed_groups.get(effective_territory, [])
        if not seeded:
            continue
        for pid in sources:
            if pid in assignment:
                continue
            lon, lat = source_lonlat(geometry_by_id[pid])
            best = min(
                seeded,
                key=lambda province: haversine_km(
                    lon, lat,
                    float(province["seed_lonlat"][0]), float(province["seed_lonlat"][1]),
                ),
            )
            assignment[pid] = str(best["id"])

    # Exact-only scopes must be fully routed.  England islands are already part of the
    # England source scope, so they are validated by explicit source-name matching.
    expected_scopes = {"scotland", "wales", "england", "ireland", "iceland", "faroe", "isle_of_man", "channel_islands"}
    unresolved: list[str] = []
    for pid, scope in scope_by_source.items():
        if scope not in expected_scopes:
            continue
        if pid not in assignment:
            unresolved.append(f"{scope}:{pid}:{meta_by_id.get(pid, {}).get('name', '')}")
    if unresolved:
        raise RuntimeError("unassigned regional SAFE sources: " + "; ".join(unresolved[:30]))

    for gid in province_by_id:
        if gid not in assignment.values():
            raise RuntimeError(f"gameplay province has no source geometry: {gid}")

    return assignment, scope_by_source


def build_macro_provinces(
    rules: dict[str, Any],
    meta_by_id: dict[str, dict[str, Any]],
    geometry_by_id: dict[str, Any],
    piece_count_by_id: dict[str, int],
    assignment: dict[str, str],
) -> list[dict[str, Any]]:
    members_by_group: dict[str, list[str]] = defaultdict(list)
    for pid, gid in assignment.items():
        members_by_group[gid].append(pid)

    records: list[dict[str, Any]] = []
    for province in rules.get("gameplay_provinces", []):
        gid = str(province["id"])
        members = sorted(members_by_group.get(gid, []))
        geometry = unary_union([geometry_by_id[pid] for pid in members])
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        if geometry.is_empty:
            raise RuntimeError(f"empty macro geometry {gid}")
        point = geometry.representative_point()
        records.append({
            "id": gid,
            "name": str(province["name"]),
            "territory": str(province.get("territory", "")),
            "target_cell_count": int(province.get("target_cells", 1)),
            "source_logical_admin1_ids": members,
            "source_names": [str(meta_by_id.get(pid, {}).get("name", pid)) for pid in members],
            "source_polygon_piece_count": sum(int(piece_count_by_id.get(pid, 0)) for pid in members),
            "area_km2": round(s.area_km2(geometry), 4),
            "label_point": [round(float(point.x), 6), round(float(point.y), 6)],
            "bbox": [round(float(x), 6) for x in geometry.bounds],
            "parts": s.shape_parts_payload(geometry),
            "_geometry": geometry,
        })
    return records


def generate_cells(record: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    geometry = record["_geometry"]
    count = max(1, int(record["target_cell_count"]))
    if count == 1:
        final = {"z01": geometry}
        generation_parts: list[dict[str, Any]] = []
        satellite_count = 0
    else:
        parts = sorted(s.polygon_parts(geometry), key=lambda item: -item.area)
        allocations, satellites = s.allocate_zone_counts(parts, count)
        final: dict[str, Any] = {}
        generation_parts = []
        offset = 0
        for component_index, (component, local_count) in enumerate(allocations):
            anchor = component.representative_point()
            local_final, stats = s.micro_partition(
                component,
                local_count,
                anchor,
                s.numeric_seed(str(record["id"])) + component_index * 100003,
                offset,
            )
            final.update(local_final)
            stats["component_index"] = component_index
            stats["local_zone_count"] = local_count
            stats["component_area_km2"] = round(s.area_km2(component), 4)
            generation_parts.append(stats)
            offset += local_count
        satellite_count = s.attach_satellites(final, satellites)

    validation = s.validate_final(geometry, final, count)
    if not validation.get("hard_validation_passed", False):
        raise RuntimeError(
            f"cell validation failed for {record['id']}: status={validation.get('status')} "
            f"missing={validation.get('coverage_missing_ratio')} extra={validation.get('coverage_extra_ratio')} "
            f"overlap={validation.get('overlap_ratio')} count={validation.get('zone_count')}/{count}"
        )
    neighbours = validation.get("neighbours", {})
    cells: list[dict[str, Any]] = []
    for local_index, zid in enumerate(sorted(final), start=1):
        zone = final[zid]
        point = zone.representative_point()
        cells.append({
            "id": f"{record['id']}:cell:{local_index:02d}",
            "local_id": zid,
            "local_index": local_index,
            "gameplay_province_id": record["id"],
            "parts": s.shape_parts_payload(zone),
            "area_km2": round(s.area_km2(zone), 4),
            "label_point": [round(float(point.x), 6), round(float(point.y), 6)],
            "bbox": [round(float(x), 6) for x in zone.bounds],
            "neighbor_cell_ids": [
                f"{record['id']}:cell:{sorted(final).index(other) + 1:02d}"
                for other in neighbours.get(zid, []) if other in final
            ],
            "multipart": len(s.polygon_parts(zone)) > 1,
        })
    generation = {
        "method": "stage6_micro_partition_on_safe_admin1_macro_geometry",
        "component_count": len(s.polygon_parts(geometry)),
        "attached_satellite_component_count": satellite_count,
        "parts": generation_parts,
        "validation": validation,
    }
    return cells, generation


def validate_macro_coverage(records: list[dict[str, Any]], assignment: dict[str, str], geometry_by_id: dict[str, Any]) -> dict[str, Any]:
    source_union = unary_union([geometry_by_id[pid] for pid in assignment])
    macro_union = unary_union([record["_geometry"] for record in records])
    source_area = max(source_union.area, 1e-9)
    missing = source_union.difference(macro_union).area / source_area
    extra = macro_union.difference(source_union).area / source_area
    sum_area = sum(record["_geometry"].area for record in records)
    overlap = max(0.0, sum_area - macro_union.area) / source_area
    return {
        "coverage_missing_ratio": missing,
        "coverage_extra_ratio": extra,
        "overlap_ratio": overlap,
        "hard_validation_passed": missing <= 1e-8 and extra <= 1e-8 and overlap <= 1e-8,
    }


def main() -> None:
    rules = read_json(RULES_PATH)
    if str(rules.get("format", "")) != "britain_north_atlantic_gameplay_province_rules/v1":
        raise RuntimeError("unexpected Britain/North Atlantic rules format")

    # Small counts do not need India's 18-cell maximum substrate, but a generous atom
    # budget improves irregular borders on large Iceland/Highland macro geometries.
    s.MAX_ATOMS = max(s.MAX_ATOMS, 720)

    meta_by_id, geometry_by_id, piece_count_by_id = load_sources()
    assignment, scope_by_source = build_assignment(rules, meta_by_id, geometry_by_id)
    records = build_macro_provinces(rules, meta_by_id, geometry_by_id, piece_count_by_id, assignment)
    coverage = validate_macro_coverage(records, assignment, geometry_by_id)
    if not coverage["hard_validation_passed"]:
        raise RuntimeError(f"macro coverage failed: {coverage}")

    geometry_payload_records: list[dict[str, Any]] = []
    cell_payload_records: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    total_cells = 0
    for index, record in enumerate(records, start=1):
        print(f"[{index}/{len(records)}] {record['id']} {record['name']} target={record['target_cell_count']}", flush=True)
        cells, generation = generate_cells(record)
        total_cells += len(cells)
        status_counts[str(generation["validation"].get("status", ""))] += 1
        clean = {key: value for key, value in record.items() if key != "_geometry"}
        geometry_payload_records.append(clean)
        cell_payload_records.append({**clean, "cells": cells, "generation": generation})
        print(f"  OK cells={len(cells)} area={record['area_km2']:.1f} status={generation['validation'].get('status')}", flush=True)

    territory_counts = Counter(record["territory"] for record in records)
    territory_cells = Counter()
    for record in records:
        territory_cells[record["territory"]] += int(record["target_cell_count"])

    scotland = [record for record in records if record["territory"] == "scotland"]
    scotland_ok = (
        len(scotland) == int(rules["principles"]["scotland_gameplay_province_count"])
        and all(2 <= int(record["target_cell_count"]) <= 3 for record in scotland)
    )
    london = next((record for record in records if record["id"] == "gb_england_london"), None)
    london_ok = bool(london and int(london["target_cell_count"]) == int(rules["principles"]["greater_london_target_cells"]))

    geometry_payload = {
        "format": "britain_north_atlantic_gameplay_provinces/v1",
        "world_px": WORLD_PX,
        "source": "SAFE logical Admin-1 polygon pieces",
        "gameplay_province_count": len(records),
        "territory_counts": dict(sorted(territory_counts.items())),
        "macro_coverage_validation": coverage,
        "provinces": geometry_payload_records,
    }
    cells_payload = {
        "format": "britain_north_atlantic_subdivisions/v1",
        "world_px": WORLD_PX,
        "source": "britain_north_atlantic_gameplay_provinces/v1",
        "gameplay_province_count": len(records),
        "cell_count": total_cells,
        "territory_counts": dict(sorted(territory_counts.items())),
        "territory_cell_counts": dict(sorted(territory_cells.items())),
        "provinces": cell_payload_records,
    }
    report = {
        "format": "britain_north_atlantic_regional_test_report/v1",
        "gameplay_province_count": len(records),
        "cell_count": total_cells,
        "assigned_safe_source_count": len(assignment),
        "source_scope_counts": dict(sorted(Counter(scope_by_source.values()).items())),
        "territory_counts": dict(sorted(territory_counts.items())),
        "territory_cell_counts": dict(sorted(territory_cells.items())),
        "validation_status_counts": dict(sorted(status_counts.items())),
        "macro_coverage_validation": coverage,
        "scotland_exactly_10_with_2_to_3_cells": scotland_ok,
        "greater_london_four_cells_preserved": london_ok,
        "all_cell_validations_hard_pass": sum(status_counts.values()) == len(records),
    }
    write_json(GEOMETRY_OUT, geometry_payload)
    write_json(CELLS_OUT, cells_payload)
    write_json(REPORT_OUT, report)

    print("BRITAIN_NA_PROVINCES=", len(records))
    print("BRITAIN_NA_CELLS=", total_cells)
    print("BRITAIN_NA_TERRITORIES=", json.dumps(dict(sorted(territory_counts.items())), ensure_ascii=False))
    print("BRITAIN_NA_TERRITORY_CELLS=", json.dumps(dict(sorted(territory_cells.items())), ensure_ascii=False))
    print("SCOTLAND_10_2_3=", scotland_ok)
    print("LONDON_4=", london_ok)
    print("MACRO_COVERAGE=", json.dumps(coverage, ensure_ascii=False))

    if not scotland_ok or not london_ok:
        raise SystemExit("Britain regional hard design constraints failed")


if __name__ == "__main__":
    main()
