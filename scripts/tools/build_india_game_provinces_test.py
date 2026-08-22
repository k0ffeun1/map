#!/usr/bin/env python3
"""Group completed Indian Stage-6 cells into gameplay provinces.

Core rule: province borders are derived ONLY from existing cell borders.
No gameplay cell is cut or redrawn at this stage.

Policy for the test:
- 1..7 cells inside an Admin-1 -> one gameplay province;
- 8+ cells -> split into connected groups;
- target group size is about 6 cells;
- preferred maximum is 7 cells.
Thus an 18-cell Admin-1 normally becomes 3 gameplay provinces of ~6 cells.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
STAGE6_PATH = ROOT / "assets" / "subdivision_stage6" / "india_test_subdivisions.json"
OUT_PATH = ROOT / "assets" / "game_data" / "india_game_provinces_test.json"
REPORT_PATH = ROOT / "reports" / "india_game_provinces_test.json"

IDEAL_CELLS_PER_GAME_PROVINCE = 6
MAX_CELLS_PER_GAME_PROVINCE = 7
MIN_CELLS_BEFORE_SPLIT = 8


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
        return [g for g in geometry.geoms if isinstance(g, Polygon) and not g.is_empty]
    return []


def geometry_from_zone(zone: dict[str, Any]) -> Any:
    geoms = []
    for part in zone.get("parts", []):
        rings = part.get("rings", []) if isinstance(part, dict) else []
        if not rings:
            continue
        g = Polygon(rings[0], rings[1:])
        if not g.is_valid:
            g = g.buffer(0)
        if not g.is_empty:
            geoms.append(g)
    return unary_union(geoms) if geoms else Polygon()


def shape_parts_payload(geometry: Any) -> list[dict[str, Any]]:
    result = []
    for poly in sorted(polygon_parts(geometry), key=lambda p: (-p.area, p.centroid.x, p.centroid.y)):
        rings = [[[round(float(x), 6), round(float(y), 6)] for x, y in poly.exterior.coords]]
        for hole in poly.interiors:
            rings.append([[round(float(x), 6), round(float(y), 6)] for x, y in hole.coords])
        result.append({"rings": rings})
    return result


def desired_group_count(cell_count: int) -> int:
    if cell_count < MIN_CELLS_BEFORE_SPLIT:
        return 1
    minimum_groups = math.ceil(cell_count / MAX_CELLS_PER_GAME_PROVINCE)
    ideal_groups = max(1, round(cell_count / IDEAL_CELLS_PER_GAME_PROVINCE))
    return max(minimum_groups, ideal_groups)


def connected_partition(zones: list[dict[str, Any]], group_count: int) -> list[list[str]]:
    ids = [str(z["id"]) for z in zones]
    by_id = {str(z["id"]): z for z in zones}
    allowed = set(ids)
    adjacency = {zid: set(str(n) for n in by_id[zid].get("neighbors", []) if str(n) in allowed) for zid in ids}
    centers = {
        zid: tuple(float(v) for v in by_id[zid].get("label_point", [0.0, 0.0])[:2])
        for zid in ids
    }

    if group_count <= 1:
        return [ids]

    first = min(ids, key=lambda zid: (centers[zid][0], centers[zid][1], zid))
    seeds = [first]
    while len(seeds) < min(group_count, len(ids)):
        candidates = [zid for zid in ids if zid not in seeds]
        nxt = max(
            candidates,
            key=lambda zid: min(
                (centers[zid][0] - centers[s][0]) ** 2 + (centers[zid][1] - centers[s][1]) ** 2
                for s in seeds
            ),
        )
        seeds.append(nxt)

    target_sizes = [len(ids) // group_count] * group_count
    for i in range(len(ids) % group_count):
        target_sizes[i] += 1

    groups: list[list[str]] = [[seed] for seed in seeds]
    unassigned = set(ids) - set(seeds)

    while unassigned:
        progressed = False
        order = sorted(range(group_count), key=lambda gi: (len(groups[gi]) / max(1, target_sizes[gi]), gi))
        for gi in order:
            if len(groups[gi]) >= target_sizes[gi]:
                continue
            frontier: set[str] = set()
            for member in groups[gi]:
                frontier.update(adjacency[member] & unassigned)
            if not frontier:
                continue
            gx = sum(centers[m][0] for m in groups[gi]) / len(groups[gi])
            gy = sum(centers[m][1] for m in groups[gi]) / len(groups[gi])
            pick = min(frontier, key=lambda zid: ((centers[zid][0]-gx)**2 + (centers[zid][1]-gy)**2, zid))
            groups[gi].append(pick)
            unassigned.remove(pick)
            progressed = True
        if progressed:
            continue

        # Connectivity-first relaxed pass if target-size caps block all frontiers.
        for gi in order:
            frontier: set[str] = set()
            for member in groups[gi]:
                frontier.update(adjacency[member] & unassigned)
            if not frontier:
                continue
            pick = min(frontier)
            groups[gi].append(pick)
            unassigned.remove(pick)
            progressed = True
            break
        if progressed:
            continue

        # Disconnected source component fallback: nearest whole cell, never a cut.
        pick = min(unassigned)
        px, py = centers[pick]
        gi = min(
            range(group_count),
            key=lambda g: min((px-centers[m][0])**2 + (py-centers[m][1])**2 for m in groups[g]),
        )
        groups[gi].append(pick)
        unassigned.remove(pick)

    return groups


def main() -> None:
    if not STAGE6_PATH.exists():
        raise RuntimeError("Run scripts/tools/build_india_stage6_test.py first")

    stage6 = read_json(STAGE6_PATH)
    game_provinces: list[dict[str, Any]] = []
    admin_report: list[dict[str, Any]] = []

    for province in stage6.get("provinces", []):
        zones = list(province.get("zones", []))
        if not zones:
            continue
        groups = connected_partition(zones, desired_group_count(len(zones)))
        by_id = {str(z["id"]): z for z in zones}
        local_ids: list[str] = []

        for index, group in enumerate(groups, start=1):
            game_id = f"gameprov:india:{str(province['province_id']).split(':')[-1]}:{index}"
            local_ids.append(game_id)
            geometry = unary_union([geometry_from_zone(by_id[zid]) for zid in group])
            if not geometry.is_valid:
                geometry = geometry.buffer(0)
            point = geometry.representative_point()
            game_provinces.append({
                "id": game_id,
                "name": f"{province.get('name', province['province_id'])} {index}" if len(groups) > 1 else str(province.get("name", province["province_id"])),
                "source_admin1_id": province["province_id"],
                "source_admin1_name": province.get("name", province["province_id"]),
                "region_id": province.get("region_id", ""),
                "region_name": province.get("region_name", ""),
                "cell_count": len(group),
                "cell_ids": group,
                "parts": shape_parts_payload(geometry),
                "label_point": [round(float(point.x), 6), round(float(point.y), 6)],
                "neighbors": [],
            })

        zone_to_game = {}
        for gp_id, group in zip(local_ids, groups):
            for zid in group:
                zone_to_game[zid] = gp_id
        gp_neighbors: dict[str, set[str]] = {gp_id: set() for gp_id in local_ids}
        for zid, zone in by_id.items():
            left = zone_to_game[zid]
            for raw in zone.get("neighbors", []):
                other = str(raw)
                if other not in zone_to_game:
                    continue
                right = zone_to_game[other]
                if left != right:
                    gp_neighbors[left].add(right)
                    gp_neighbors[right].add(left)
        for record in game_provinces[-len(groups):]:
            record["neighbors"] = sorted(gp_neighbors[record["id"]])

        admin_report.append({
            "province_id": province["province_id"],
            "name": province.get("name", province["province_id"]),
            "cell_count": len(zones),
            "game_province_count": len(groups),
            "group_sizes": sorted((len(g) for g in groups), reverse=True),
        })

    output = {
        "schema_version": 1,
        "format": "india_game_provinces_test/v1",
        "source_stage6": str(STAGE6_PATH.relative_to(ROOT)).replace("\\", "/"),
        "policy": {
            "min_cells_before_split": MIN_CELLS_BEFORE_SPLIT,
            "ideal_cells_per_game_province": IDEAL_CELLS_PER_GAME_PROVINCE,
            "preferred_max_cells_per_game_province": MAX_CELLS_PER_GAME_PROVINCE,
            "cell_geometry_is_never_cut": True,
            "province_geometry_is_union_of_member_cells": True,
        },
        "source_admin1_count": len(admin_report),
        "game_province_count": len(game_provinces),
        "game_provinces": game_provinces,
    }
    report = {
        "schema_version": 1,
        "format": "india_game_provinces_test_report/v1",
        "source_admin1_count": len(admin_report),
        "source_cell_count": sum(x["cell_count"] for x in admin_report),
        "game_province_count": len(game_provinces),
        "split_admin1_count": sum(1 for x in admin_report if x["game_province_count"] > 1),
        "max_game_province_cell_count": max((g["cell_count"] for g in game_provinces), default=0),
        "admin1": admin_report,
        "hard_fail": False,
    }
    write_json(OUT_PATH, output)
    write_json(REPORT_PATH, report)
    print("INDIA_GAME_PROVINCES=", len(game_provinces))
    print("INDIA_SPLIT_ADMIN1=", report["split_admin1_count"])
    print("INDIA_MAX_CELLS_PER_GAME_PROVINCE=", report["max_game_province_cell_count"])


if __name__ == "__main__":
    main()
