#!/usr/bin/env python3
"""Migrate historical regions and cell targets to the clean logical Admin-1 layer.

This is a non-destructive migration stage. It never rewrites the legacy 4027
Layer-8 province data. New logical Admin-1 parents are assigned to the existing
FINAL historical-region system by geometric overlap with the legacy canonical
Layer-8 geometry. Target gameplay-cell counts are then recomputed from the
regional workbook profiles using the clean parent's geodesic area.

Project invariants:
- logical_admin1_id owns region assignment and target-cell budget;
- polygon pieces never receive independent cell minima;
- terrain/relief/rivers are not used;
- small/fine source features are preserved unless an explicit level policy says
  otherwise;
- the old 4027 layer remains available only as a migration/reference source.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

import build_world_province_cell_targets as legacy_targets

ROOT = Path(__file__).resolve().parents[2]

SAFE_PARENTS = ROOT / "assets/game_data/world_admin1_logical_parents.json"
SAFE_PIECES = ROOT / "assets/map_geometry/world_admin1_safe_pieces.json"
SOURCE_MANIFEST = ROOT / "assets/game_data/world_admin1_source_manifest.json"
LEVEL_POLICY = ROOT / "assets/game_data/world_admin1_level_policy.json"

LEGACY_GEOMETRY = ROOT / "assets/provinces.json"
LEGACY_IDENTITY = ROOT / "assets/game_data/provinces.json"
LEGACY_ASSIGNMENTS = ROOT / "assets/game_data/world_region_assignments_final.json"
LEGACY_OVERRIDES = ROOT / "assets/game_data/province_cell_generation_overrides.json"

OUT_ASSIGNMENTS = ROOT / "assets/game_data/world_admin1_safe_region_assignments.json"
OUT_REGION_GEOMETRY = ROOT / "assets/regions_world_admin1_safe.json"
OUT_TARGETS = ROOT / "assets/game_data/world_admin1_safe_cell_targets.json"
OUT_REPORT = ROOT / "reports/world_admin1_safe_regions_and_targets.json"
OUT_MD = ROOT / "reports/world_admin1_safe_regions_and_targets.md"

EXPECTED_PARENTS = 4564
EXPECTED_PIECES = 8175
PIECE_SUFFIX_RE = re.compile(r"(?:_ov\d+|_\d+)$")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    else:
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def geometry_from_rings(rings: Any) -> Any:
    if not isinstance(rings, list) or not rings:
        return Polygon()
    try:
        geom = Polygon(rings[0], rings[1:])
    except Exception:
        return Polygon()
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom


def polygon_parts(geometry: Any) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, (MultiPolygon, GeometryCollection)) or hasattr(geometry, "geoms"):
        return [g for g in geometry.geoms if isinstance(g, Polygon) and not g.is_empty and g.area > 1.0e-10]
    return []


def rings_payload(poly: Polygon) -> list[list[list[float]]]:
    def ring(coords: Any) -> list[list[float]]:
        return [[round(float(x), 2), round(float(y), 2)] for x, y in coords]
    return [ring(poly.exterior.coords)] + [ring(interior.coords) for interior in poly.interiors]


def peel_piece_suffix(value: str) -> str:
    current = value
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        newer = PIECE_SUFFIX_RE.sub("", current)
        if newer == current:
            break
        current = newer
    return current


def load_safe_geometry() -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, bool]]:
    parents_doc = read_json(SAFE_PARENTS)
    pieces_doc = read_json(SAFE_PIECES)
    manifest = read_json(SOURCE_MANIFEST)
    policy = read_json(LEVEL_POLICY)

    parents = {str(x["logical_admin1_id"]): x for x in parents_doc.get("parents", [])}
    if len(parents) != EXPECTED_PARENTS:
        raise RuntimeError(f"expected {EXPECTED_PARENTS} safe parents, got {len(parents)}")

    pieces = pieces_doc.get("pieces", [])
    if len(pieces) != EXPECTED_PIECES:
        raise RuntimeError(f"expected {EXPECTED_PIECES} safe pieces, got {len(pieces)}")

    by_parent: dict[str, list[Any]] = defaultdict(list)
    for item in pieces:
        logical_id = str(item.get("logical_admin1_id", ""))
        geom = geometry_from_rings(item.get("rings", []))
        if logical_id and not geom.is_empty:
            by_parent[logical_id].append(geom)

    geometry_by_parent: dict[str, Any] = {}
    for logical_id in parents:
        member_geoms = by_parent.get(logical_id, [])
        if not member_geoms:
            raise RuntimeError(f"safe parent has no render pieces: {logical_id}")
        geom = unary_union(member_geoms)
        if not geom.is_valid:
            geom = geom.buffer(0)
        geometry_by_parent[logical_id] = geom

    fine_labels = set(policy.get("fine_type_review_labels", []))
    fine_by_parent: dict[str, bool] = defaultdict(bool)
    for feature in manifest.get("source_features", []):
        logical_id = str(feature.get("logical_admin1_id", ""))
        if str(feature.get("type_en", "")) in fine_labels or bool(feature.get("fine_type_review", False)):
            fine_by_parent[logical_id] = True

    return parents, geometry_by_parent, dict(fine_by_parent)


def load_legacy_region_source() -> tuple[list[Any], list[dict[str, Any]]]:
    identity_doc = read_json(LEGACY_IDENTITY)
    id_by_legacy = {
        str(x.get("legacy_id", "")): str(x.get("id", ""))
        for x in identity_doc.get("provinces", [])
        if str(x.get("legacy_id", "")) and str(x.get("id", ""))
    }
    assignments = {
        str(x.get("province_id", "")): x
        for x in read_json(LEGACY_ASSIGNMENTS).get("assignments", [])
    }
    geoms: list[Any] = []
    meta: list[dict[str, Any]] = []
    for entry in read_json(LEGACY_GEOMETRY).get("cells", []):
        legacy_id = str(entry.get("id", ""))
        pid = id_by_legacy.get(legacy_id, "")
        assignment = assignments.get(pid)
        geom = geometry_from_rings(entry.get("rings", []))
        if not pid or assignment is None or geom.is_empty:
            continue
        geoms.append(geom)
        meta.append({
            "province_id": pid,
            "legacy_id": legacy_id,
            "region_id": str(assignment.get("region_id", "")),
            "region_name": str(assignment.get("region_name", "")),
            "legacy_method": str(assignment.get("method", "")),
            "legacy_review": bool(assignment.get("review", False)),
        })
    if len(geoms) != 4027:
        raise RuntimeError(f"legacy region migration source coverage mismatch: {len(geoms)}")
    return geoms, meta


def migrate_regions(
    parents: dict[str, dict[str, Any]],
    safe_geometry: dict[str, Any],
    fine_by_parent: dict[str, bool],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    legacy_geoms, legacy_meta = load_legacy_region_source()
    tree = STRtree(legacy_geoms)

    output: list[dict[str, Any]] = []
    method_counts: Counter[str] = Counter()
    review_count = 0
    low_dominance: list[dict[str, Any]] = []
    low_coverage: list[dict[str, Any]] = []

    for logical_id in sorted(parents):
        parent = parents[logical_id]
        geom = safe_geometry[logical_id]
        safe_area = float(geom.area)
        region_overlap: dict[str, float] = defaultdict(float)
        region_names: dict[str, str] = {}
        legacy_sources: list[str] = []

        candidate_indices = tree.query(geom, predicate="intersects")
        for raw_index in candidate_indices:
            index = int(raw_index)
            old_geom = legacy_geoms[index]
            inter = geom.intersection(old_geom)
            if inter.is_empty:
                continue
            overlap = float(inter.area)
            if overlap <= 1.0e-10:
                continue
            meta = legacy_meta[index]
            rid = str(meta["region_id"])
            if not rid:
                continue
            region_overlap[rid] += overlap
            region_names[rid] = str(meta["region_name"])
            legacy_sources.append(str(meta["province_id"]))

        if region_overlap:
            ranked = sorted(region_overlap.items(), key=lambda kv: (-kv[1], kv[0]))
            winner_id, winner_overlap = ranked[0]
            total_overlap = sum(region_overlap.values())
            dominance = winner_overlap / total_overlap if total_overlap > 0.0 else 0.0
            coverage = min(1.0, total_overlap / safe_area) if safe_area > 0.0 else 0.0
            method = "max_area_overlap_from_final_layer8_regions"
        else:
            # A geometry gap should not leave a parent without a region. Use the
            # nearest old final province, but force manual review.
            nearest_index = int(tree.nearest(geom))
            nearest_meta = legacy_meta[nearest_index]
            winner_id = str(nearest_meta["region_id"])
            region_names[winner_id] = str(nearest_meta["region_name"])
            dominance = 0.0
            coverage = 0.0
            total_overlap = 0.0
            method = "nearest_final_layer8_region_fallback"
            ranked = []
            legacy_sources = [str(nearest_meta["province_id"])]

        review = method != "max_area_overlap_from_final_layer8_regions" or dominance < 0.80 or coverage < 0.98
        if review:
            review_count += 1
        method_counts[method] += 1

        top_regions = [
            {
                "region_id": rid,
                "region_name": region_names.get(rid, rid),
                "overlap_share": round(area / total_overlap, 6) if total_overlap > 0.0 else 0.0,
            }
            for rid, area in ranked[:3]
        ]
        item = {
            "logical_admin1_id": logical_id,
            "name": str(parent.get("name", logical_id)),
            "admin": str(parent.get("admin", "")),
            "region_id": winner_id,
            "region_name": region_names.get(winner_id, winner_id),
            "method": method,
            "review": review,
            "overlap_dominance": round(dominance, 6),
            "geometry_coverage": round(coverage, 6),
            "fine_type_review": bool(fine_by_parent.get(logical_id, False)),
            "source_feature_count": int(parent.get("source_feature_count", 0)),
            "piece_count": int(parent.get("piece_count", 0)),
            "legacy_overlap_province_ids": sorted(set(legacy_sources)),
            "top_region_overlaps": top_regions,
        }
        output.append(item)
        if dominance < 0.80:
            low_dominance.append(item)
        if coverage < 0.98:
            low_coverage.append(item)

    report = {
        "assignment_count": len(output),
        "region_count": len({x["region_id"] for x in output}),
        "review_count": review_count,
        "fine_type_review_count": sum(1 for x in output if x["fine_type_review"]),
        "method_counts": dict(sorted(method_counts.items())),
        "low_dominance_count": len(low_dominance),
        "low_coverage_count": len(low_coverage),
        "low_dominance_examples": low_dominance[:40],
        "low_coverage_examples": low_coverage[:40],
    }
    return output, report


def migrate_overrides(manifest: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    logical_ids_by_legacy: dict[str, set[str]] = defaultdict(set)
    for feature in manifest.get("source_features", []):
        base = str(feature.get("legacy_base_id", ""))
        logical_id = str(feature.get("logical_admin1_id", ""))
        if base and logical_id:
            logical_ids_by_legacy[base].add(logical_id)

    migrated: dict[str, dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []
    for override in read_json(LEGACY_OVERRIDES).get("overrides", []):
        legacy_id = str(override.get("legacy_id", ""))
        base = peel_piece_suffix(legacy_id)
        candidates = sorted(logical_ids_by_legacy.get(base, set()))
        if len(candidates) == 1:
            x = dict(override)
            x["legacy_province_id"] = str(override.get("province_id", ""))
            x["legacy_id"] = legacy_id
            x["logical_admin1_id"] = candidates[0]
            migrated[candidates[0]] = x
        else:
            unresolved.append({
                "legacy_id": legacy_id,
                "resolved_base": base,
                "candidate_logical_admin1_ids": candidates,
                "override": override,
            })
    return migrated, {
        "legacy_override_count": len(read_json(LEGACY_OVERRIDES).get("overrides", [])),
        "migrated_override_count": len(migrated),
        "unresolved_override_count": len(unresolved),
        "unresolved": unresolved,
    }


def build_targets(
    parents: dict[str, dict[str, Any]],
    assignments: list[dict[str, Any]],
    fine_by_parent: dict[str, bool],
) -> tuple[dict[str, Any], dict[str, Any]]:
    _profiles, profiles_by_name = legacy_targets.load_profile_source()
    base_profiles = read_json(legacy_targets.BASE_PROFILES_PATH).get("profiles", {})
    neutral = dict(base_profiles.get("P3", {}))
    if not neutral:
        raise RuntimeError("P3 fallback profile is missing")

    manifest = read_json(SOURCE_MANIFEST)
    migrated_overrides, override_report = migrate_overrides(manifest)
    assignment_by_parent = {str(x["logical_admin1_id"]): x for x in assignments}

    output: list[dict[str, Any]] = []
    count_distribution: Counter[int] = Counter()
    profile_counts: Counter[str] = Counter()
    fallback_regions: Counter[str] = Counter()
    min_clamps = 0
    max_clamps = 0

    for logical_id in sorted(parents):
        parent = parents[logical_id]
        assignment = assignment_by_parent[logical_id]
        region_name = str(assignment.get("region_name", ""))
        profile = profiles_by_name.get(region_name)
        profile_source = "regional_workbook"
        if profile is None:
            fallback_regions[region_name or "<empty>"] += 1
            profile = {
                "region_id": str(assignment.get("region_id", "")),
                "name": region_name or "UNPROFILED_SPECIAL_REGION",
                "profile_id": "P3",
                "target_cell_area_km2": float(neutral["target_cell_area_km2"]),
                "min_cells_per_province": int(neutral["min_cells_per_province"]),
                "max_cells_per_province": int(neutral["max_cells_per_province"]),
                "historical_density_index": None,
                "geographic_complexity_index": None,
            }
            profile_source = "P3_fallback_region_not_in_workbook"

        area_km2 = float(parent.get("source_geodesic_area_km2", parent.get("source_geodesic_area_km2_sum", 0.0)))
        if area_km2 <= 0.0:
            raise RuntimeError(f"non-positive safe parent geodesic area: {logical_id}")

        target_area = float(profile["target_cell_area_km2"])
        raw_area_count = area_km2 / target_area
        area_count = max(1, legacy_targets.round_half_up(raw_area_count))
        minimum = int(profile["min_cells_per_province"])
        maximum = int(profile["max_cells_per_province"])
        anchor_min = int(legacy_targets.WORKBOOK_ANCHOR_MIN_BY_NAME.get(str(parent.get("name", "")), 1))

        override = migrated_overrides.get(logical_id)
        override_reason = ""
        if override is not None:
            override_reason = str(override.get("reason", ""))
            minimum_override = override.get("minimum_cell_count")
            if minimum_override is not None:
                anchor_min = max(anchor_min, int(minimum_override))

        pre_clamp = max(area_count, anchor_min)
        if pre_clamp < minimum:
            min_clamps += 1
        if pre_clamp > maximum:
            max_clamps += 1
        final_count = max(minimum, min(maximum, pre_clamp))
        if override is not None and override.get("forced_cell_count") is not None:
            final_count = int(override["forced_cell_count"])
        if final_count < 1:
            raise RuntimeError(f"invalid target count for {logical_id}: {final_count}")

        profile_id = str(profile["profile_id"])
        profile_counts[profile_id] += 1
        count_distribution[final_count] += 1
        output.append({
            "logical_admin1_id": logical_id,
            "name": str(parent.get("name", logical_id)),
            "admin": str(parent.get("admin", "")),
            "region_id": str(assignment.get("region_id", "")),
            "region_name": region_name,
            "region_assignment_method": str(assignment.get("method", "")),
            "region_assignment_review": bool(assignment.get("review", False)),
            "region_overlap_dominance": float(assignment.get("overlap_dominance", 0.0)),
            "region_geometry_coverage": float(assignment.get("geometry_coverage", 0.0)),
            "fine_type_review": bool(fine_by_parent.get(logical_id, False)),
            "source_feature_count": int(parent.get("source_feature_count", 0)),
            "piece_count": int(parent.get("piece_count", 0)),
            "area_km2": round(area_km2, 3),
            "profile_id": profile_id,
            "profile_source": profile_source,
            "region_target_cell_area_km2": target_area,
            "region_min_cells": minimum,
            "region_max_cells": maximum,
            "historical_density_index": profile.get("historical_density_index"),
            "geographic_complexity_index": profile.get("geographic_complexity_index"),
            "coast_factor": 1.0,
            "relief_factor": 1.0,
            "shape_factor": 1.0,
            "complexity": 1.0,
            "raw_area_count": round(raw_area_count, 6),
            "area_count": area_count,
            "anchor_min": anchor_min,
            "target_cell_count": final_count,
            "override_reason": override_reason,
        })

    total_target_cells = sum(int(x["target_cell_count"]) for x in output)
    targets = {
        "schema_version": 1,
        "format": "world_admin1_safe_cell_targets/v1",
        "content_version": "2026.08.21",
        "logical_parent_count": len(output),
        "total_target_cells": total_target_cells,
        "formula": "CLAMP(MAX(ROUND(area_km2 / region_target_cell_area_km2), anchor_min), region.min, region.max)",
        "area_source": "assets/game_data/world_admin1_logical_parents.json::source_geodesic_area_km2",
        "geometry_source": str(SAFE_PIECES.relative_to(ROOT)),
        "region_assignment_source": str(OUT_ASSIGNMENTS.relative_to(ROOT)),
        "relief_factor_policy": "1.0 locked: relief is generated after cells",
        "provinces": output,
    }
    report = {
        "logical_parent_count": len(output),
        "total_target_cells": total_target_cells,
        "count_distribution": {str(k): count_distribution[k] for k in sorted(count_distribution)},
        "province_count_by_profile": dict(sorted(profile_counts.items())),
        "special_fallback_province_count": sum(fallback_regions.values()),
        "special_fallback_regions": dict(sorted(fallback_regions.items())),
        "min_clamp_count": min_clamps,
        "max_clamp_count": max_clamps,
        "override_migration": override_report,
        "fine_type_review_count": sum(1 for x in output if x["fine_type_review"]),
        "region_assignment_review_count": sum(1 for x in output if x["region_assignment_review"]),
        "largest_target_counts": sorted(
            [{
                "logical_admin1_id": x["logical_admin1_id"],
                "name": x["name"],
                "admin": x["admin"],
                "region_name": x["region_name"],
                "area_km2": x["area_km2"],
                "target_cell_count": x["target_cell_count"],
            } for x in output],
            key=lambda x: (-int(x["target_cell_count"]), -float(x["area_km2"]), x["logical_admin1_id"]),
        )[:50],
    }
    return targets, report


def build_region_geometry(assignments: list[dict[str, Any]], safe_geometry: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    names: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for assignment in assignments:
        logical_id = str(assignment["logical_admin1_id"])
        rid = str(assignment["region_id"])
        grouped[rid].append(safe_geometry[logical_id])
        names[rid] = str(assignment["region_name"])
        counts[rid] += 1

    cells: list[dict[str, Any]] = []
    stats: list[dict[str, Any]] = []
    for rid in sorted(grouped):
        merged = unary_union(grouped[rid])
        if not merged.is_valid:
            merged = merged.buffer(0)
        parts = sorted(polygon_parts(merged), key=lambda p: (-p.area, p.centroid.x, p.centroid.y))
        for index, poly in enumerate(parts):
            minx, miny, maxx, maxy = poly.bounds
            cells.append({
                "id": f"{rid}__safe_part_{index:03d}",
                "region_id": rid,
                "name": names[rid],
                "rings": rings_payload(poly),
                "bbox": [round(minx, 2), round(miny, 2), round(maxx, 2), round(maxy, 2)],
            })
        stats.append({
            "region_id": rid,
            "name": names[rid],
            "logical_admin1_count": counts[rid],
            "polygon_piece_count": len(parts),
        })

    data = {
        "schema_version": 1,
        "format": "world_regions_admin1_safe/v1",
        "world_px": 8192.0,
        "logical_parent_count": len(assignments),
        "region_count": len(stats),
        "polygon_piece_count": len(cells),
        "source_assignments": str(OUT_ASSIGNMENTS.relative_to(ROOT)),
        "source_geometry": str(SAFE_PIECES.relative_to(ROOT)),
        "method": "dissolve_clean_logical_admin1_after_overlap_region_migration",
        "cells": cells,
    }
    return data, {
        "region_count": len(stats),
        "polygon_piece_count": len(cells),
        "region_stats": stats,
    }


def find_controls(targets: dict[str, Any], assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wanted = {
        "Большой Лондон", "Appenzell Innerrhoden", "Northumberland", "Jekabpils",
        "Madrid", "Lisboa", "Porto",
    }
    a_by_id = {str(x["logical_admin1_id"]): x for x in assignments}
    out = []
    for x in targets.get("provinces", []):
        if str(x.get("name", "")) not in wanted:
            continue
        a = a_by_id[str(x["logical_admin1_id"])]
        out.append({
            "logical_admin1_id": x["logical_admin1_id"],
            "name": x["name"],
            "admin": x["admin"],
            "area_km2": x["area_km2"],
            "region_name": x["region_name"],
            "target_cell_count": x["target_cell_count"],
            "overlap_dominance": a["overlap_dominance"],
            "geometry_coverage": a["geometry_coverage"],
            "review": a["review"],
            "fine_type_review": x["fine_type_review"],
        })
    return out


def render_md(report: dict[str, Any]) -> str:
    r = report["region_migration"]
    t = report["cell_targets"]
    g = report["region_geometry"]
    lines = [
        "# Safe Admin-1 → historical regions → target cells",
        "",
        "This report belongs to the new clean logical Admin-1 layer. The legacy 4027 Layer-8 is not modified.",
        "",
        "## Summary",
        "",
        f"- Logical Admin-1 parents: **{r['assignment_count']}**.",
        f"- Historical regions represented: **{r['region_count']}**.",
        f"- Region assignments flagged for review: **{r['review_count']}**.",
        f"- Fine-type parents retained for level-policy review: **{r['fine_type_review_count']}**.",
        f"- Dissolved safe-region polygon pieces: **{g['polygon_piece_count']}**.",
        f"- Recomputed target gameplay cells: **{t['total_target_cells']}**.",
        f"- Region-profile fallback parents: **{t['special_fallback_province_count']}**.",
        f"- Migrated explicit cell overrides: **{t['override_migration']['migrated_override_count']} / {t['override_migration']['legacy_override_count']}**.",
        "",
        "## Migration method",
        "",
        "1. Intersect each clean logical Admin-1 with the old FINAL Layer-8 provinces.",
        "2. Sum overlap area by historical region.",
        "3. Assign the region with the largest overlap share.",
        "4. Flag assignments with dominance < 0.80 or geometry coverage < 0.98.",
        "5. Recompute cell targets from the existing regional workbook profile using clean geodesic area.",
        "6. Polygon pieces never receive their own minimum-one-cell budget.",
        "",
        "## Control cases",
        "",
        "| Admin | Name | km² | Region | Cells | dominance | coverage | review | fine-type |",
        "|---|---|---:|---|---:|---:|---:|---|---|",
    ]
    for x in report.get("controls", []):
        lines.append(
            f"| {x['admin']} | {x['name']} | {x['area_km2']:.1f} | {x['region_name']} | {x['target_cell_count']} | "
            f"{x['overlap_dominance']:.3f} | {x['geometry_coverage']:.3f} | {x['review']} | {x['fine_type_review']} |"
        )
    lines += [
        "",
        "## Target-count distribution",
        "",
        "| Cells | Parents |",
        "|---:|---:|",
    ]
    for k, v in t.get("count_distribution", {}).items():
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "## Review policy",
        "",
        "Review flags do not modify geometry. They only identify parents whose migrated region should be inspected before the safe layer becomes canonical.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parents, safe_geometry, fine_by_parent = load_safe_geometry()
    assignments, region_report = migrate_regions(parents, safe_geometry, fine_by_parent)
    if len(assignments) != EXPECTED_PARENTS:
        raise RuntimeError(f"region assignment count mismatch: {len(assignments)}")

    assignment_doc = {
        "schema_version": 1,
        "format": "world_admin1_safe_region_assignments/v1",
        "logical_parent_count": len(assignments),
        "source_safe_parents": str(SAFE_PARENTS.relative_to(ROOT)),
        "source_safe_geometry": str(SAFE_PIECES.relative_to(ROOT)),
        "migration_source": str(LEGACY_ASSIGNMENTS.relative_to(ROOT)),
        "method": "maximum_geometric_overlap_with_final_legacy_region_assignments",
        "review_thresholds": {"overlap_dominance": 0.80, "geometry_coverage": 0.98},
        "assignments": assignments,
    }

    targets, target_report = build_targets(parents, assignments, fine_by_parent)
    region_geometry, geometry_report = build_region_geometry(assignments, safe_geometry)
    controls = find_controls(targets, assignments)

    report = {
        "schema_version": 1,
        "format": "world_admin1_safe_regions_and_targets_report/v1",
        "region_migration": region_report,
        "region_geometry": geometry_report,
        "cell_targets": target_report,
        "controls": controls,
        "hard_fail": False,
    }

    write_json(OUT_ASSIGNMENTS, assignment_doc)
    write_json(OUT_REGION_GEOMETRY, region_geometry, compact=True)
    write_json(OUT_TARGETS, targets)
    write_json(OUT_REPORT, report)
    OUT_MD.write_text(render_md(report) + "\n", encoding="utf-8")

    print(
        "WORLD_ADMIN1_SAFE_REGIONS_TARGETS_OK",
        f"parents={region_report['assignment_count']}",
        f"regions={region_report['region_count']}",
        f"review={region_report['review_count']}",
        f"fine_review={region_report['fine_type_review_count']}",
        f"region_parts={geometry_report['polygon_piece_count']}",
        f"cells={target_report['total_target_cells']}",
        f"fallback={target_report['special_fallback_province_count']}",
        f"overrides={target_report['override_migration']['migrated_override_count']}",
    )


if __name__ == "__main__":
    main()
