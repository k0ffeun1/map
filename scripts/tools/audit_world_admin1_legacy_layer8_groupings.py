#!/usr/bin/env python3
"""Reconstruct legacy Layer-8 Admin-1 groupings against the safe Admin-1 layer.

This is an AUDIT ONLY. It never mutates Layer 8, safe Admin-1 geometry, or the
normalization policy. The goal is to explain what the legacy 4027-record layer
contains and which safe source parents were absorbed into each legacy shape.

Important: assets/provinces.json is a render-oriented legacy layer. One legacy
administrative cluster can be represented by several records after MultiPolygon
explode / overlap cleanup. We therefore reconstruct a stable legacy group from
(country slug + current display name) before comparing it with safe parents.

Inputs:
  assets/provinces.json
  assets/game_data/provinces.json
  assets/game_data/world_admin1_playable_parents.json
  assets/map_geometry/world_admin1_safe_pieces.json
  assets/game_data/world_admin1_source_manifest.json

Outputs:
  assets/game_data/world_admin1_legacy_layer8_groupings.json
  reports/world_admin1_legacy_layer8_groupings.json
  reports/world_admin1_legacy_layer8_groupings.md
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from shapely.geometry import GeometryCollection, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[2]
LEGACY_GEOMETRY = ROOT / "assets" / "provinces.json"
LEGACY_IDENTITIES = ROOT / "assets" / "game_data" / "provinces.json"
SAFE_PARENTS = ROOT / "assets" / "game_data" / "world_admin1_playable_parents.json"
SAFE_PIECES = ROOT / "assets" / "map_geometry" / "world_admin1_safe_pieces.json"
SOURCE_MANIFEST = ROOT / "assets" / "game_data" / "world_admin1_source_manifest.json"

OUT_GROUPINGS = ROOT / "assets" / "game_data" / "world_admin1_legacy_layer8_groupings.json"
OUT_REPORT = ROOT / "reports" / "world_admin1_legacy_layer8_groupings.json"
OUT_MD = ROOT / "reports" / "world_admin1_legacy_layer8_groupings.md"

EXPECTED_SAFE_PLAYABLE = 4561
EXPECTED_LEGACY_RECORDS = 4027
WATCH_COUNTRIES = {
    "Slovenia",
    "United Kingdom",
    "Latvia",
    "Macedonia",
    "Azerbaijan",
    "Malta",
}

# Pair selection is intentionally conservative. A safe parent is considered a
# member of a legacy group only when the legacy geometry covers at least half of
# that safe parent. Border slivers remain diagnostics instead of silently
# becoming membership.
PAIR_SOURCE_COVERAGE_MIN = 0.50
PAIR_DIAGNOSTIC_SOURCE_COVERAGE_MIN = 0.05

# Machine confidence only. This is NOT normalization-policy approval.
HIGH_LEGACY_COVERAGE = 0.985
HIGH_SOURCE_COVERAGE = 0.985
HIGH_IOU = 0.970
REVIEW_LEGACY_COVERAGE = 0.90
REVIEW_SOURCE_COVERAGE = 0.90


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slug(value: Any) -> str:
    s = "" if value is None else str(value)
    out: list[str] = []
    prev_underscore = False
    for ch in s.lower():
        if ch.isascii() and ch.isalnum():
            out.append(ch)
            prev_underscore = False
        elif not prev_underscore:
            out.append("_")
            prev_underscore = True
    return "".join(out).strip("_") or "unnamed"


def polygon_from_rings(rings: Any) -> Any:
    if not isinstance(rings, list) or not rings:
        return GeometryCollection()
    exterior = rings[0]
    holes = rings[1:] if len(rings) > 1 else []
    try:
        geom = Polygon(exterior, holes)
    except Exception:
        return GeometryCollection()
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom


def clean_union(geoms: list[Any]) -> Any:
    geoms = [g for g in geoms if g is not None and not g.is_empty]
    if not geoms:
        return GeometryCollection()
    geom = unary_union(geoms) if len(geoms) > 1 else geoms[0]
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom


def legacy_country_slug(cell_id: str) -> str:
    return cell_id.split("__", 1)[0] if "__" in cell_id else ""


def reconstruct_legacy_group_id(cell: dict[str, Any]) -> str:
    """Undo render-piece suffixing without parsing fragile _2/_ovN endings.

    build_provinces.py originally creates base_id as:
        slug(admin) + "__" + slug(name)
    and only then appends piece suffixes. Recomputing the name part is safer
    than regex-stripping a numeric suffix from arbitrary legacy ids.
    """
    cid = str(cell.get("id", ""))
    country = legacy_country_slug(cid)
    return f"{country}__{slug(cell.get('name', ''))}"


def classify_match(
    legacy_coverage: float,
    source_coverage: float,
    iou: float,
    selected_count: int,
    ambiguous_count: int,
    country_ok: bool,
) -> str:
    if selected_count == 0 or not country_ok:
        return "REJECTED_GEOMETRY"
    if (
        legacy_coverage >= HIGH_LEGACY_COVERAGE
        and source_coverage >= HIGH_SOURCE_COVERAGE
        and iou >= HIGH_IOU
        and ambiguous_count == 0
    ):
        return "HIGH_CONFIDENCE"
    if legacy_coverage >= REVIEW_LEGACY_COVERAGE and source_coverage >= REVIEW_SOURCE_COVERAGE:
        return "REVIEW"
    return "REJECTED_GEOMETRY"


def main() -> None:
    legacy_doc = read_json(LEGACY_GEOMETRY)
    legacy_identity_doc = read_json(LEGACY_IDENTITIES)
    safe_parent_doc = read_json(SAFE_PARENTS)
    safe_piece_doc = read_json(SAFE_PIECES)
    manifest_doc = read_json(SOURCE_MANIFEST)

    legacy_cells = list(legacy_doc.get("cells", []))
    legacy_identities = list(legacy_identity_doc.get("provinces", []))
    safe_parents = list(safe_parent_doc.get("parents", []))
    safe_pieces = list(safe_piece_doc.get("pieces", []))
    source_features = list(manifest_doc.get("source_features", []))

    if len(legacy_cells) != EXPECTED_LEGACY_RECORDS:
        raise RuntimeError(f"legacy Layer-8 record count mismatch: {len(legacy_cells)}")
    if len(legacy_identities) != EXPECTED_LEGACY_RECORDS:
        raise RuntimeError(f"legacy identity count mismatch: {len(legacy_identities)}")
    if len(safe_parents) != EXPECTED_SAFE_PLAYABLE:
        raise RuntimeError(f"safe playable parent count mismatch: {len(safe_parents)}")

    source_by_id = {
        str(x.get("source_feature_id", "")): x
        for x in source_features
        if str(x.get("source_feature_id", ""))
    }
    parent_by_id = {
        str(x.get("logical_admin1_id", "")): x
        for x in safe_parents
        if str(x.get("logical_admin1_id", ""))
    }

    # Safe logical-parent geometry is reconstructed from render pieces. This
    # keeps the comparison in the exact same projected/world-px coordinate
    # space as legacy assets/provinces.json and avoids a second GIS source.
    piece_geoms_by_parent: dict[str, list[Any]] = defaultdict(list)
    for piece in safe_pieces:
        pid = str(piece.get("logical_admin1_id", ""))
        if pid not in parent_by_id:
            continue
        geom = polygon_from_rings(piece.get("rings", []))
        if not geom.is_empty:
            piece_geoms_by_parent[pid].append(geom)

    safe_rows: list[dict[str, Any]] = []
    for pid in sorted(parent_by_id):
        parent = parent_by_id[pid]
        geom = clean_union(piece_geoms_by_parent.get(pid, []))
        if geom.is_empty:
            raise RuntimeError(f"playable safe parent has no geometry: {pid}")
        admin = str(parent.get("admin", ""))
        safe_rows.append({
            "logical_admin1_id": pid,
            "admin": admin,
            "country_slug": slug(admin),
            "name": str(parent.get("name", "")),
            "source_feature_ids": [str(x) for x in parent.get("source_feature_ids", [])],
            "source_feature_count": int(parent.get("source_feature_count", 0)),
            "source_geodesic_area_km2": float(parent.get("source_geodesic_area_km2", 0.0) or 0.0),
            "explicit_aggregation": bool(parent.get("explicit_aggregation", False)),
            "geom": geom,
        })

    # Reconstruct legacy clusters from render records. This also reveals how
    # much of the 4027 count is render-piece multiplicity rather than actual
    # administrative normalization.
    legacy_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cell in legacy_cells:
        legacy_bucket[reconstruct_legacy_group_id(cell)].append(cell)

    legacy_groups: list[dict[str, Any]] = []
    for group_id in sorted(legacy_bucket):
        cells = legacy_bucket[group_id]
        geoms = [polygon_from_rings(x.get("rings", [])) for x in cells]
        geom = clean_union(geoms)
        if geom.is_empty:
            continue
        country_slug = legacy_country_slug(str(cells[0].get("id", "")))
        legacy_groups.append({
            "legacy_group_id": group_id,
            "legacy_name": str(cells[0].get("name", "")),
            "country_slug": country_slug,
            "legacy_record_ids": [str(x.get("id", "")) for x in cells],
            "legacy_record_count": len(cells),
            "geom": geom,
        })

    # Spatial indexes per country prevent border-touch candidates in another
    # state from entering the membership calculation at all.
    safe_by_country: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in safe_rows:
        safe_by_country[row["country_slug"]].append(row)

    tree_by_country: dict[str, tuple[STRtree, list[dict[str, Any]], list[Any]]] = {}
    for country_slug, rows in safe_by_country.items():
        geoms = [x["geom"] for x in rows]
        tree_by_country[country_slug] = (STRtree(geoms), rows, geoms)

    safe_usage: Counter[str] = Counter()
    grouping_rows: list[dict[str, Any]] = []

    for legacy in legacy_groups:
        lgeom = legacy["geom"]
        larea = float(lgeom.area)
        country_slug = legacy["country_slug"]
        index_bundle = tree_by_country.get(country_slug)
        diagnostics: list[dict[str, Any]] = []
        selected: list[dict[str, Any]] = []

        if index_bundle is not None:
            tree, country_rows, country_geoms = index_bundle
            for raw_idx in tree.query(lgeom):
                idx = int(raw_idx)
                srow = country_rows[idx]
                sgeom = country_geoms[idx]
                inter_area = float(lgeom.intersection(sgeom).area)
                if inter_area <= 0.0:
                    continue
                source_area = float(sgeom.area)
                source_cov = inter_area / source_area if source_area > 0.0 else 0.0
                legacy_cov = inter_area / larea if larea > 0.0 else 0.0
                if source_cov < PAIR_DIAGNOSTIC_SOURCE_COVERAGE_MIN:
                    continue
                item = {
                    "logical_admin1_id": srow["logical_admin1_id"],
                    "name": srow["name"],
                    "admin": srow["admin"],
                    "source_coverage_by_legacy": round(source_cov, 6),
                    "legacy_coverage_by_source": round(legacy_cov, 6),
                    "intersection_world_px2": round(inter_area, 6),
                }
                diagnostics.append(item)
                if source_cov >= PAIR_SOURCE_COVERAGE_MIN:
                    selected.append(srow)

        diagnostics.sort(
            key=lambda x: (x["source_coverage_by_legacy"], x["intersection_world_px2"]),
            reverse=True,
        )

        selected_ids = {x["logical_admin1_id"] for x in selected}
        ambiguous = [
            x for x in diagnostics
            if x["logical_admin1_id"] not in selected_ids
            and x["source_coverage_by_legacy"] >= 0.20
        ]

        source_union = clean_union([x["geom"] for x in selected])
        if source_union.is_empty:
            inter_area = 0.0
            source_area = 0.0
            union_area = larea
        else:
            inter_area = float(lgeom.intersection(source_union).area)
            source_area = float(source_union.area)
            union_area = float(lgeom.union(source_union).area)

        legacy_coverage = inter_area / larea if larea > 0.0 else 0.0
        source_coverage = inter_area / source_area if source_area > 0.0 else 0.0
        iou = inter_area / union_area if union_area > 0.0 else 0.0
        area_ratio = larea / source_area if source_area > 0.0 else 0.0
        symmetric_difference = float(lgeom.symmetric_difference(source_union).area) if not source_union.is_empty else larea

        selected.sort(key=lambda x: x["logical_admin1_id"])
        selected_parent_ids = [x["logical_admin1_id"] for x in selected]
        for pid in selected_parent_ids:
            safe_usage[pid] += 1

        source_ids: list[str] = []
        for row in selected:
            source_ids.extend(row["source_feature_ids"])
        source_ids = list(dict.fromkeys(source_ids))

        source_names: list[str] = []
        source_types: list[str] = []
        for sid in source_ids:
            src = source_by_id.get(sid, {})
            source_names.append(str(src.get("name", "")))
            source_types.append(str(src.get("type_en", "")))

        admins = sorted({x["admin"] for x in selected})
        country_ok = len(admins) <= 1 and (not admins or slug(admins[0]) == country_slug)
        match_status = classify_match(
            legacy_coverage,
            source_coverage,
            iou,
            len(selected),
            len(ambiguous),
            country_ok,
        )

        grouping_rows.append({
            "legacy_group_id": legacy["legacy_group_id"],
            "legacy_name": legacy["legacy_name"],
            "country": admins[0] if len(admins) == 1 else "",
            "country_slug": country_slug,
            "legacy_record_ids": legacy["legacy_record_ids"],
            "legacy_record_count": legacy["legacy_record_count"],
            "safe_logical_admin1_ids": selected_parent_ids,
            "safe_logical_parent_count": len(selected_parent_ids),
            "source_logical_admin1_ids": selected_parent_ids,
            "source_feature_ids": source_ids,
            "source_feature_count": len(source_ids),
            "source_names": source_names,
            "source_type_en": sorted({x for x in source_types if x}),
            "source_geodesic_area_km2_sum": round(sum(x["source_geodesic_area_km2"] for x in selected), 6),
            "contains_existing_safe_explicit_aggregation": any(x["explicit_aggregation"] for x in selected),
            "legacy_coverage_ratio": round(legacy_coverage, 6),
            "source_coverage_ratio": round(source_coverage, 6),
            "intersection_over_union": round(iou, 6),
            "legacy_to_source_area_ratio": round(area_ratio, 6),
            "symmetric_difference_world_px2": round(symmetric_difference, 6),
            "match_status": match_status,
            "policy_status": "UNREVIEWED",
            "ambiguous_candidate_count": len(ambiguous),
            "ambiguous_candidates": ambiguous[:20],
            "pair_diagnostics": diagnostics[:50],
        })

    groups_by_country: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in grouping_rows:
        groups_by_country[row["country_slug"]].append(row)

    country_name_by_slug: dict[str, str] = {}
    for row in safe_rows:
        country_name_by_slug.setdefault(row["country_slug"], row["admin"])

    country_rows: list[dict[str, Any]] = []
    safe_count_by_country = Counter(x["country_slug"] for x in safe_rows)
    for country_slug in sorted(set(safe_count_by_country) | set(groups_by_country)):
        groups = groups_by_country.get(country_slug, [])
        selected_parent_ids = {
            pid for g in groups for pid in g["safe_logical_admin1_ids"]
        }
        country_rows.append({
            "country": country_name_by_slug.get(country_slug, ""),
            "country_slug": country_slug,
            "safe_playable_parent_count": int(safe_count_by_country.get(country_slug, 0)),
            "legacy_render_record_count": sum(g["legacy_record_count"] for g in groups),
            "legacy_reconstructed_group_count": len(groups),
            "safe_parents_matched_at_least_once": len(selected_parent_ids),
            "one_to_one_group_count": sum(g["safe_logical_parent_count"] == 1 for g in groups),
            "many_to_one_legacy_group_count": sum(g["safe_logical_parent_count"] > 1 for g in groups),
            "high_confidence_group_count": sum(g["match_status"] == "HIGH_CONFIDENCE" for g in groups),
            "review_group_count": sum(g["match_status"] == "REVIEW" for g in groups),
            "rejected_geometry_group_count": sum(g["match_status"] == "REJECTED_GEOMETRY" for g in groups),
        })

    unmatched_safe = [pid for pid in sorted(parent_by_id) if safe_usage[pid] == 0]
    multiply_used_safe = [
        {"logical_admin1_id": pid, "legacy_group_count": count}
        for pid, count in sorted(safe_usage.items())
        if count > 1
    ]

    summary = {
        "safe_playable_parent_count": len(safe_rows),
        "legacy_render_record_count": len(legacy_cells),
        "legacy_identity_record_count": len(legacy_identities),
        "legacy_reconstructed_group_count": len(legacy_groups),
        "render_piece_multiplicity_delta": len(legacy_cells) - len(legacy_groups),
        "matched_one_to_one_group_count": sum(x["safe_logical_parent_count"] == 1 for x in grouping_rows),
        "matched_many_to_one_group_count": sum(x["safe_logical_parent_count"] > 1 for x in grouping_rows),
        "unmatched_legacy_group_count": sum(x["safe_logical_parent_count"] == 0 for x in grouping_rows),
        "high_confidence_group_count": sum(x["match_status"] == "HIGH_CONFIDENCE" for x in grouping_rows),
        "review_group_count": sum(x["match_status"] == "REVIEW" for x in grouping_rows),
        "rejected_geometry_group_count": sum(x["match_status"] == "REJECTED_GEOMETRY" for x in grouping_rows),
        "safe_parent_used_zero_times_count": len(unmatched_safe),
        "safe_parent_used_multiple_times_count": len(multiply_used_safe),
    }

    grouping_doc = {
        "schema_version": 1,
        "format": "world_admin1_legacy_layer8_groupings/v1",
        "legacy_source": str(LEGACY_GEOMETRY.relative_to(ROOT)),
        "safe_parent_source": str(SAFE_PARENTS.relative_to(ROOT)),
        "safe_piece_source": str(SAFE_PIECES.relative_to(ROOT)),
        "source_manifest": str(SOURCE_MANIFEST.relative_to(ROOT)),
        "policy_note": "match_status is machine confidence only; policy_status stays UNREVIEWED until explicit normalization approval",
        "summary": summary,
        "groupings": grouping_rows,
    }
    write_json(OUT_GROUPINGS, grouping_doc)

    report = {
        "schema_version": 1,
        "format": "world_admin1_legacy_layer8_groupings_audit/v1",
        "summary": summary,
        "country_audit": country_rows,
        "watched_countries": [x for x in country_rows if x["country"] in WATCH_COUNTRIES],
        "safe_parents_not_recovered_from_layer8": unmatched_safe,
        "safe_parents_used_by_multiple_legacy_groups": multiply_used_safe,
        "lowest_iou_examples": sorted(
            grouping_rows,
            key=lambda x: (x["intersection_over_union"], x["legacy_group_id"]),
        )[:100],
    }
    write_json(OUT_REPORT, report)

    lines = [
        "# Layer 8 ↔ safe Admin-1 reconciliation",
        "",
        "> Это только аудит. Ни одно legacy-объединение автоматически не становится normalization policy.",
        "",
        "## Сводка",
        "",
        f"- Safe playable parents: **{summary['safe_playable_parent_count']}**.",
        f"- Legacy Layer-8 render records: **{summary['legacy_render_record_count']}**.",
        f"- Reconstructed legacy groups: **{summary['legacy_reconstructed_group_count']}**.",
        f"- Render-piece multiplicity delta: **{summary['render_piece_multiplicity_delta']}**.",
        f"- 1→1 legacy groups: **{summary['matched_one_to_one_group_count']}**.",
        f"- N→1 legacy groups: **{summary['matched_many_to_one_group_count']}**.",
        f"- Unmatched legacy groups: **{summary['unmatched_legacy_group_count']}**.",
        f"- HIGH_CONFIDENCE: **{summary['high_confidence_group_count']}**.",
        f"- REVIEW: **{summary['review_group_count']}**.",
        f"- REJECTED_GEOMETRY: **{summary['rejected_geometry_group_count']}**.",
        f"- Safe parents not recovered: **{summary['safe_parent_used_zero_times_count']}**.",
        f"- Safe parents used by >1 legacy group: **{summary['safe_parent_used_multiple_times_count']}**.",
        "",
        "## Контрольные страны",
        "",
        "| Country | Safe | L8 records | L8 groups | 1→1 | N→1 | High | Review | Rejected |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["watched_countries"]:
        lines.append(
            f"| {row['country']} | {row['safe_playable_parent_count']} | "
            f"{row['legacy_render_record_count']} | {row['legacy_reconstructed_group_count']} | "
            f"{row['one_to_one_group_count']} | {row['many_to_one_legacy_group_count']} | "
            f"{row['high_confidence_group_count']} | {row['review_group_count']} | "
            f"{row['rejected_geometry_group_count']} |"
        )

    lines.extend([
        "",
        "## Правило интерпретации",
        "",
        "- `HIGH_CONFIDENCE` означает только сильное геометрическое совпадение.",
        "- `policy_status` всегда остаётся `UNREVIEWED` на этом этапе.",
        "- Только проверенные legacy groupings позже переносятся в explicit normalization policy.",
        "- Старый `_merge_small_pieces` этим скриптом не вызывается и не восстанавливается.",
    ])
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("WORLD_ADMIN1_LEGACY_LAYER8_RECONCILIATION", json.dumps(summary, ensure_ascii=False))
    if multiply_used_safe:
        raise SystemExit(
            "audit completed, but at least one safe parent maps to multiple legacy groups; "
            "review reports/world_admin1_legacy_layer8_groupings.json"
        )


if __name__ == "__main__":
    main()
