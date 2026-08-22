#!/usr/bin/env python3
"""Generate internal land cells for normalized Layer-8 gameplay provinces.

Canonical inputs:
- layer8_normalized_province_groups.json — logical gameplay parents;
- layer8_normalized_cell_targets.json — approved target cell counts;
- map_geometry/provinces.json — unchanged Layer-8 render geometry.

Geometry algorithm is the already proven Stage-6 pipeline:
    microcells -> competitive graph growth -> political-boundary cleanup
    -> topology-locked polygons.

Important differences from the old Stage-6 stress runner:
- no temporary area/2100 cell-count fallback;
- no 2 km stress-test coastline inset;
- normalized gameplay-parent geometry is the source of truth;
- disconnected render pieces are unioned logically without artificial land bridges;
- tiny satellite components may belong to a multipart cell;
- generation is deterministic and shardable for the whole world.

No terrain, rivers, relief, climate or gameplay cities are used here. Existing
real provincial-capital coordinates are used only when the project already has
them; otherwise a technical interior anchor is explicitly marked as such.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import build_stage6_universal_subdivisions as stage6

GROUPS_PATH = ROOT / "assets" / "game_data" / "layer8_normalized_province_groups.json"
TARGETS_PATH = ROOT / "assets" / "game_data" / "layer8_normalized_cell_targets.json"
GEOMETRY_PATH = ROOT / "assets" / "map_geometry" / "provinces.json"
IDENTITY_PATH = ROOT / "assets" / "game_data" / "provinces.json"
CITIES_PATH = ROOT / "assets" / "province_cities_iberia.json"
DEFAULT_PREVIEW = ROOT / "assets" / "land_cells_normalized" / "control_preview.json"
DEFAULT_REPORT = ROOT / "reports" / "layer8_normalized_world_cells_control.json"

EXPECTED_GAMEPLAY_PARENTS = 2886
EXPECTED_TARGET_CELLS = 12902
GEOMETRY_EPSILON = 1.0e-9


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = json.dumps(value, ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8")


def stable_seed(value: str) -> int:
    digest = hashlib.sha256(("layer8-normalized-cells-v1:" + value).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "little") & 0x7FFFFFFF


def geometry_from_entry(entry: dict[str, Any]) -> Any:
    rings = entry.get("rings", [])
    if not rings or len(rings[0]) < 3:
        return Polygon()
    geom = Polygon(rings[0], rings[1:])
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom


def polygon_parts(geom: Any) -> list[Polygon]:
    return stage6.polygon_parts(geom)


def parent_slug(parent_id: str) -> str:
    value = parent_id.removeprefix("gameplay:")
    return value.replace(":", "_").replace("/", "_")


class NormalizedWorldSources:
    def __init__(self) -> None:
        groups_doc = read_json(GROUPS_PATH)
        targets_doc = read_json(TARGETS_PATH)
        if groups_doc.get("format") != "layer8_normalized_province_groups/v2":
            raise RuntimeError(f"Unexpected groups format: {groups_doc.get('format')}")
        if targets_doc.get("format") != "layer8_normalized_cell_targets/v1":
            raise RuntimeError(f"Unexpected targets format: {targets_doc.get('format')}")

        self.groups: dict[str, dict[str, Any]] = {
            str(item["gameplay_parent_id"]): dict(item) for item in groups_doc.get("groups", [])
        }
        self.targets: dict[str, dict[str, Any]] = {
            str(item["gameplay_parent_id"]): dict(item) for item in targets_doc.get("provinces", [])
        }
        if len(self.groups) != EXPECTED_GAMEPLAY_PARENTS or len(self.targets) != EXPECTED_GAMEPLAY_PARENTS:
            raise RuntimeError(
                f"Expected {EXPECTED_GAMEPLAY_PARENTS} normalized parents; "
                f"groups={len(self.groups)} targets={len(self.targets)}"
            )
        if set(self.groups) != set(self.targets):
            raise RuntimeError("Normalized groups/targets parent IDs do not match")
        target_total = sum(int(item.get("target_cell_count", 0)) for item in self.targets.values())
        if target_total != EXPECTED_TARGET_CELLS:
            raise RuntimeError(f"Expected {EXPECTED_TARGET_CELLS} target cells, got {target_total}")

        identity_doc = read_json(IDENTITY_PATH)
        self.identity = {str(item["id"]): dict(item) for item in identity_doc.get("provinces", [])}

        geometry_doc = read_json(GEOMETRY_PATH)
        self.geometry: dict[str, Any] = {}
        for entry in geometry_doc.get("provinces", []):
            pid = str(entry.get("id", ""))
            geom = geometry_from_entry(entry)
            if pid and not geom.is_empty:
                self.geometry[pid] = geom
        if len(self.geometry) != 4027:
            raise RuntimeError(f"Expected 4027 render geometries, got {len(self.geometry)}")

        self.city_by_province: dict[str, dict[str, Any]] = {}
        if CITIES_PATH.exists():
            for item in read_json(CITIES_PATH).get("cities", []):
                key = str(item.get("province", "")).strip().casefold()
                if key:
                    self.city_by_province.setdefault(key, dict(item))

    def ordered_parent_ids(self) -> list[str]:
        return sorted(self.groups)

    def parent_geometry(self, parent_id: str) -> Any:
        group = self.groups[parent_id]
        source = []
        for raw_pid in group.get("render_province_ids", []):
            pid = str(raw_pid)
            geom = self.geometry.get(pid)
            if geom is None or geom.is_empty:
                raise RuntimeError(f"{parent_id}: missing render geometry {pid}")
            source.append(geom)
        if not source:
            raise RuntimeError(f"{parent_id}: no render geometry members")
        geom = unary_union(source)
        if not geom.is_valid:
            geom = geom.buffer(0)
        if geom.is_empty:
            raise RuntimeError(f"{parent_id}: normalized geometry is empty")
        return geom

    def anchor(self, parent_id: str, land: Any) -> tuple[Point, str, str]:
        group = self.groups[parent_id]
        names: list[str] = []
        display_name = str(group.get("display_name", ""))
        if display_name:
            names.append(display_name)
        names.extend(str(value) for value in group.get("source_names", []) if str(value))
        root_pid = str(group.get("root_province_id", ""))
        root_identity = self.identity.get(root_pid, {})
        root_name = str(root_identity.get("name", ""))
        if root_name:
            names.append(root_name)

        for name in dict.fromkeys(names):
            city = self.city_by_province.get(name.strip().casefold())
            if city is None:
                continue
            pos = city.get("pos", [])
            if not isinstance(pos, list) or len(pos) < 2:
                continue
            point = Point(float(pos[0]), float(pos[1]))
            if land.buffer(1.0e-7).covers(point):
                return point, str(city.get("name", name)), "real_province_capital"

        point = land.representative_point()
        return point, display_name or parent_id, "technical_interior_anchor"


def allocate_parts(parts: list[Polygon], count: int) -> tuple[list[tuple[Polygon, int]], list[Polygon], int]:
    """Use Stage-6 allocation and report its significant-component estimate."""
    if not parts:
        return [], [], 0
    total_area = sum(part.area for part in parts)
    significant = [part for part in parts if part.area >= total_area * 0.012]
    allocations, satellites = stage6.allocate_zone_counts(parts, count)
    return allocations, satellites, len(significant)


def cell_parts_payload(geometry: Any) -> list[dict[str, Any]]:
    return stage6.shape_parts_payload(geometry)


def build_parent(sources: NormalizedWorldSources, parent_id: str) -> dict[str, Any]:
    group = sources.groups[parent_id]
    target = sources.targets[parent_id]
    requested_count = int(target.get("target_cell_count", 0))
    if requested_count < 1:
        raise RuntimeError(f"{parent_id}: invalid target cell count {requested_count}")

    land = sources.parent_geometry(parent_id)
    parts = sorted(polygon_parts(land), key=lambda item: (-item.area, item.centroid.x, item.centroid.y))
    if not parts:
        raise RuntimeError(f"{parent_id}: no polygon parts")

    anchor, anchor_name, anchor_source = sources.anchor(parent_id, land)
    allocations, satellites, significant_count = allocate_parts(parts, requested_count)
    if not allocations:
        raise RuntimeError(f"{parent_id}: no allocated components")

    final: dict[str, Any] = {}
    generation_parts: list[dict[str, Any]] = []
    zone_offset = 0
    base_seed = stable_seed(parent_id)
    for component_index, (component, local_count) in enumerate(allocations):
        local_anchor = anchor if component.buffer(1.0e-9).covers(anchor) else component.representative_point()
        local_final, stats = stage6.micro_partition(
            component,
            local_count,
            local_anchor,
            base_seed + component_index * 100003,
            zone_offset,
        )
        final.update(local_final)
        stats = dict(stats)
        stats.update({
            "component_index": component_index,
            "local_cell_count": local_count,
            "component_area_km2": round(stage6.area_km2(component), 4),
            "anchor_source": anchor_source if component.buffer(1.0e-9).covers(anchor) else "component_representative_point",
        })
        generation_parts.append(stats)
        zone_offset += local_count

    attached_satellite_count = stage6.attach_satellites(final, satellites)
    validation = stage6.validate_final(land, final, requested_count)
    if not validation.get("hard_validation_passed", False):
        raise RuntimeError(
            f"{parent_id}: hard validation failed "
            f"missing={validation.get('coverage_missing_ratio')} "
            f"extra={validation.get('coverage_extra_ratio')} "
            f"overlap={validation.get('overlap_ratio')} "
            f"count={validation.get('zone_count')}/{requested_count}"
        )

    neighbours = validation.get("neighbours", {})
    zone_ids = sorted(final)
    anchor_zone = ""
    for zid in zone_ids:
        if final[zid].buffer(1.0e-7).covers(anchor):
            anchor_zone = zid
            break

    cells: list[dict[str, Any]] = []
    for local_index, zid in enumerate(zone_ids, start=1):
        geometry = final[zid]
        point = geometry.representative_point()
        min_x, min_y, max_x, max_y = geometry.bounds
        cell_id = f"land_cell:{parent_slug(parent_id)}:{local_index:02d}"
        local_neighbours = []
        for other in neighbours.get(zid, []):
            try:
                other_index = zone_ids.index(other) + 1
            except ValueError:
                continue
            local_neighbours.append(f"land_cell:{parent_slug(parent_id)}:{other_index:02d}")
        cells.append({
            "id": cell_id,
            "gameplay_parent_id": parent_id,
            "local_index": local_index,
            "cell_role": "primary_candidate" if zid == anchor_zone and anchor_source == "real_province_capital" else "territory",
            "parts": cell_parts_payload(geometry),
            "multipart": len(polygon_parts(geometry)) > 1,
            "area_km2": round(stage6.area_km2(geometry), 4),
            "label_point": [round(float(point.x), 6), round(float(point.y), 6)],
            "bbox": [round(float(min_x), 6), round(float(min_y), 6), round(float(max_x), 6), round(float(max_y), 6)],
            "neighbor_land_cell_ids": sorted(local_neighbours),
        })

    generated_area = sum(float(item["area_km2"]) for item in cells)
    return {
        "gameplay_parent_id": parent_id,
        "display_name": str(group.get("display_name", parent_id)),
        "country_prefix": str(group.get("root_country_prefix", "")),
        "region_id": str(group.get("root_region_id", "")),
        "region_name": str(group.get("root_region_name", "")),
        "target_cell_count": requested_count,
        "target_profile_id": str(target.get("root_profile_id", "")),
        "target_area_km2": float(target.get("region_target_cell_area_km2", 0.0)),
        "normalized_area_km2": float(target.get("area_km2", 0.0)),
        "generated_cell_area_sum_km2": round(generated_area, 4),
        "source_render_province_ids": list(group.get("render_province_ids", [])),
        "source_render_province_count": int(group.get("render_province_count", 0)),
        "source_family_count": int(group.get("member_family_count", 0)),
        "protected_group_ids": list(group.get("protected_group_ids", [])),
        "geometry_component_count": len(parts),
        "significant_component_count_1p2pct": significant_count,
        "processed_component_count": len(allocations),
        "attached_satellite_component_count": attached_satellite_count,
        "capital_anchor": {
            "name": anchor_name,
            "point": [round(float(anchor.x), 6), round(float(anchor.y), 6)],
            "source": anchor_source,
            "cell_id": next((item["id"] for item in cells if item["cell_role"] == "primary_candidate"), ""),
        },
        "generation": {
            "method": "stage6_microcells_competitive_graph_growth_boundary_cleanup_topology_lock",
            "seed": base_seed,
            "parts": generation_parts,
        },
        "validation": validation,
        "cells": cells,
    }


def control_parent_ids(sources: NormalizedWorldSources) -> list[str]:
    groups = list(sources.groups.values())
    targets = sources.targets

    def find_name(token: str) -> str | None:
        token_cf = token.casefold()
        exact = [g for g in groups if str(g.get("display_name", "")).casefold() == token_cf]
        if exact:
            return str(exact[0]["gameplay_parent_id"])
        partial = [g for g in groups if token_cf in str(g.get("display_name", "")).casefold()]
        return str(partial[0]["gameplay_parent_id"]) if partial else None

    selected: list[str] = []
    for token in ("La Coruña", "Greater London", "Las Palmas", "Santa Cruz de Tenerife"):
        pid = find_name(token)
        if pid:
            selected.append(pid)

    merged = sorted(
        (g for g in groups if int(g.get("member_family_count", 1)) > 1),
        key=lambda g: (-int(g.get("member_family_count", 1)), str(g.get("gameplay_parent_id", ""))),
    )
    if merged:
        selected.append(str(merged[0]["gameplay_parent_id"]))

    slovenia = sorted(
        (g for g in groups if str(g.get("root_country_prefix", "")) == "slovenia"),
        key=lambda g: (-float(g.get("area_km2", 0.0)), str(g.get("gameplay_parent_id", ""))),
    )
    if slovenia:
        selected.append(str(slovenia[0]["gameplay_parent_id"]))

    huge_safety = sorted(
        (
            (pid, target) for pid, target in targets.items()
            if int(target.get("large_one_cell_safety_min", 1)) > 1
        ),
        key=lambda item: (-float(item[1].get("area_km2", 0.0)), item[0]),
    )
    if huge_safety:
        selected.append(huge_safety[0][0])

    return list(dict.fromkeys(selected))


def resolve_parent(sources: NormalizedWorldSources, value: str) -> str:
    if value in sources.groups:
        return value
    token = value.casefold().strip()
    exact = [pid for pid, group in sources.groups.items() if str(group.get("display_name", "")).casefold() == token]
    if len(exact) == 1:
        return exact[0]
    partial = [pid for pid, group in sources.groups.items() if token in str(group.get("display_name", "")).casefold()]
    if len(partial) == 1:
        return partial[0]
    raise KeyError(f"Gameplay parent not found or ambiguous: {value}")


def shard_parent_ids(parent_ids: list[str], shard_index: int, shard_count: int) -> list[str]:
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError(f"Invalid shard {shard_index}/{shard_count}")
    return [pid for index, pid in enumerate(parent_ids) if index % shard_count == shard_index]


def build_payload(sources: NormalizedWorldSources, parent_ids: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    provinces: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, parent_id in enumerate(parent_ids, start=1):
        group = sources.groups[parent_id]
        target = sources.targets[parent_id]
        print(
            f"[{index}/{len(parent_ids)}] {parent_id} {group.get('display_name')} "
            f"cells={target.get('target_cell_count')}",
            flush=True,
        )
        try:
            record = build_parent(sources, parent_id)
            provinces.append(record)
            print(
                f"  OK cells={len(record['cells'])} status={record['validation']['status']} "
                f"parts={record['geometry_component_count']} satellites={record['attached_satellite_component_count']}",
                flush=True,
            )
        except Exception as error:
            failures.append({
                "gameplay_parent_id": parent_id,
                "display_name": str(group.get("display_name", parent_id)),
                "target_cell_count": int(target.get("target_cell_count", 0)),
                "error": f"{type(error).__name__}: {error}",
            })
            print(f"  FAIL {type(error).__name__}: {error}", flush=True)

    cells = [cell for province in provinces for cell in province["cells"]]
    status_counts = Counter(str(item["validation"].get("status", "")) for item in provinces)
    multipart_cells = sum(bool(cell.get("multipart", False)) for cell in cells)
    real_capital_count = sum(
        item.get("capital_anchor", {}).get("source") == "real_province_capital" for item in provinces
    )
    payload = {
        "schema_version": 1,
        "format": "layer8_normalized_land_cells/v1",
        "content_version": "2026.08.22",
        "generation_method": "stage6_microcells_competitive_graph_growth_boundary_cleanup_topology_lock",
        "source": {
            "normalized_groups": str(GROUPS_PATH.relative_to(ROOT)),
            "normalized_targets": str(TARGETS_PATH.relative_to(ROOT)),
            "render_geometry": str(GEOMETRY_PATH.relative_to(ROOT)),
        },
        "policy": {
            "terrain_used": False,
            "rivers_used": False,
            "relief_used": False,
            "climate_used": False,
            "gameplay_cities_used": False,
            "coastline_inset_km": 0.0,
            "artificial_land_bridges_between_islands": False,
            "tiny_satellite_components_may_attach_to_nearest_cell_as_multipart": True,
            "deterministic": True,
        },
        "province_count": len(provinces),
        "cell_count": len(cells),
        "provinces": provinces,
        "cells": cells,
    }
    report = {
        "format": "layer8_normalized_land_cells_report/v1",
        "requested_province_count": len(parent_ids),
        "built_province_count": len(provinces),
        "failed_province_count": len(failures),
        "requested_cell_count": sum(int(sources.targets[pid]["target_cell_count"]) for pid in parent_ids),
        "built_cell_count": len(cells),
        "multipart_cell_count": multipart_cells,
        "real_capital_anchor_count": real_capital_count,
        "technical_anchor_count": len(provinces) - real_capital_count,
        "status_counts": dict(sorted(status_counts.items())),
        "failures": failures,
        "hard_fail": bool(failures),
    }
    return payload, report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", action="append", default=[], help="gameplay parent ID or unambiguous display name")
    parser.add_argument("--controls", action="store_true", help="generate representative world control set")
    parser.add_argument("--all", action="store_true", help="generate every normalized gameplay parent")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, default=DEFAULT_PREVIEW)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sources = NormalizedWorldSources()
    selected: list[str] = []
    for value in args.parent:
        selected.append(resolve_parent(sources, value))
    if args.controls:
        selected.extend(control_parent_ids(sources))
    if args.all:
        selected.extend(sources.ordered_parent_ids())
    if not selected:
        selected = control_parent_ids(sources)
    selected = list(dict.fromkeys(selected))
    if args.all or args.shard_count > 1:
        selected = shard_parent_ids(sorted(selected), args.shard_index, args.shard_count)
    if args.limit is not None:
        selected = selected[: max(0, args.limit)]

    payload, report = build_payload(sources, selected)
    output = args.output
    report_path = args.report
    if args.shard_count > 1:
        suffix = f"shard_{args.shard_index:03d}_of_{args.shard_count:03d}.json"
        if output == DEFAULT_PREVIEW:
            output = ROOT / "assets" / "land_cells_normalized" / "shards" / suffix
        if report_path == DEFAULT_REPORT:
            report_path = ROOT / "reports" / "land_cells_normalized" / suffix

    write_json(output, payload, compact=args.compact)
    write_json(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"wrote {output.relative_to(ROOT) if output.is_absolute() and ROOT in output.parents else output}")

    if report["failed_province_count"] and not args.allow_failures:
        raise SystemExit("Normalized cell generation has failures; see report")
    if report["built_cell_count"] != report["requested_cell_count"]:
        raise SystemExit(
            f"Cell count mismatch: built={report['built_cell_count']} requested={report['requested_cell_count']}"
        )


if __name__ == "__main__":
    main()
