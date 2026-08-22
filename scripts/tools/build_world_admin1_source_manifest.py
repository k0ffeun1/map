#!/usr/bin/env python3
"""Build a clean, immutable source-feature manifest for Natural Earth Admin-1.

This is the parent-identity layer that the old 4027 polygon-piece table lacks.
It intentionally does NOT use area, neighbour size, topology growth, terrain,
relief, rivers, or any other heuristic to merge administrative units.

Each Natural Earth source feature receives a stable source_feature_id based on
`adm1_code` whenever possible. Polygon parts are properties of that parent,
not independent gameplay provinces. Explicit mixed-level aggregations are
represented separately and never destroy source-feature lineage.

The script can also compare the current `world_province_cell_targets.json`
against the clean source identities. This comparison is diagnostic: existing
corrupted geometry is not modified here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import shapefile
from pyproj import Geod
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[2]
TARGETS = ROOT / "assets/game_data/world_province_cell_targets.json"
OUT_MANIFEST = ROOT / "assets/game_data/world_admin1_source_manifest.json"
OUT_MIGRATION = ROOT / "reports/world_admin1_source_migration_audit.json"
OUT_MD = ROOT / "reports/world_admin1_source_migration_audit.md"
GEOD = Geod(ellps="WGS84")

# This mirrors the only named source-level correction that the project had
# explicitly approved. It is lineage-preserving: every raw borough remains a
# source feature and merely points to one logical aggregate parent.
EXPLICIT_AGGREGATIONS = {
    ("United Kingdom", "Greater London"): {
        "logical_admin1_id": "admin1:explicit:united_kingdom__greater_london",
        "logical_name": "Большой Лондон",
        "reason": "Natural Earth mixes London borough detail into an Admin-1 world layer",
    },
}

FINE_TYPES = {
    "Commune|Municipality", "Municipality", "London Borough", "London Borough (city)",
    "Metropolitan Borough", "Quarter", "Unitary District", "Unitary District (city)",
    "Municipality|Governarate", "Parish", "Canton",
}

PIECE_SUFFIX_RE = re.compile(r"(?:_ov\d+|_\d+)$")


def fix_text(value: Any) -> str:
    s = "" if value is None else str(value)
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def slug(value: str) -> str:
    """Match the legacy ASCII-slug behavior used by build_provinces.py."""
    out: list[str] = []
    prev_underscore = False
    for ch in value.lower():
        if ch.isascii() and ch.isalnum():
            out.append(ch)
            prev_underscore = False
        elif not prev_underscore:
            out.append("_")
            prev_underscore = True
    return "".join(out).strip("_") or "unnamed"


def geodesic_area_km2(geom: Any) -> float:
    if geom.is_empty:
        return 0.0
    area_m2, _ = GEOD.geometry_area_perimeter(geom)
    return abs(float(area_m2)) / 1_000_000.0


def source_feature_id(props: dict[str, Any], geom: Any, duplicate_codes: set[str]) -> str:
    adm1_code = fix_text(props.get("adm1_code"))
    if adm1_code and adm1_code not in duplicate_codes:
        return f"ne10m-adm1:{adm1_code}"
    # Deterministic fallback. This is intentionally based on source semantics +
    # rounded source bbox, not project polygon-piece order.
    admin = fix_text(props.get("admin"))
    name = fix_text(props.get("name") or props.get("name_en") or admin)
    type_en = fix_text(props.get("type_en"))
    iso = fix_text(props.get("iso_3166_2"))
    bbox = ",".join(f"{x:.6f}" for x in geom.bounds)
    raw = "|".join((admin, name, type_en, iso, adm1_code, bbox))
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"ne10m-adm1:fallback:{digest}"


def peel_to_known_base(legacy_id: str, known: set[str]) -> str | None:
    candidate = legacy_id
    if candidate in known:
        return candidate
    seen = set()
    while candidate and candidate not in seen:
        seen.add(candidate)
        newer = PIECE_SUFFIX_RE.sub("", candidate)
        if newer == candidate:
            break
        candidate = newer
        if candidate in known:
            return candidate
    return None


def logical_parent_for(feature: dict[str, Any]) -> tuple[str, str, str, bool]:
    key = (feature["admin"], feature["region"])
    explicit = EXPLICIT_AGGREGATIONS.get(key)
    if explicit:
        return (
            explicit["logical_admin1_id"],
            explicit["logical_name"],
            explicit["reason"],
            True,
        )
    return feature["source_feature_id"], feature["name"], "raw Natural Earth source feature", False


def render_md(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "# Clean Admin-1 source lineage / migration audit",
        "",
        "## Source identity layer",
        "",
        f"- Raw Natural Earth features: **{s['raw_source_feature_count']}**.",
        f"- Stable source feature IDs: **{s['unique_source_feature_id_count']}**.",
        f"- Logical parents after explicit-only aggregation: **{s['logical_parent_count']}**.",
        f"- Source features participating in explicit aggregation: **{s['explicit_aggregation_member_count']}**.",
        f"- Fine-type source features requiring an explicit level policy: **{s['fine_type_feature_count']}**.",
        f"- Heuristic area/neighbour merges: **0**.",
        "",
        "## Migration of current 4027 records",
        "",
        f"- Current target records: **{s['current_target_record_count']}**.",
        f"- Records that can be linked to exactly one raw source feature by legacy base: **{s['current_unique_source_match_count']}**.",
        f"- Records whose legacy base matches multiple raw source features: **{s['current_ambiguous_source_match_count']}**.",
        f"- Records with no raw source-name base match: **{s['current_unmatched_source_count']}**.",
        f"- Polygon-piece records (`_2/_3/_ovN`) resolved to a parent base: **{s['current_piece_suffix_record_count']}**.",
        f"- Distinct clean source parents referenced by uniquely matched current records: **{s['distinct_unique_matched_source_parent_count']}**.",
        "",
        "## Why the old 4027 count cannot be the new parent count",
        "",
        "A single raw Admin-1 may be a MultiPolygon or later split into many render pieces. Each piece must share one parent identity and one target-cell budget. "
        "Conversely, exact display names are not sufficient as a primary key: Natural Earth can contain different source features with the same name and ISO code but different `adm1_code` (Jekabpils is the concrete example).",
        "",
        "## Watched source parents",
        "",
        "| Source ID | Admin | Name | type | adm1_code | ISO | km² | parts | logical parent |",
        "|---|---|---|---|---|---|---:|---:|---|",
    ]
    for x in report.get("watch_source_features", []):
        lines.append(
            f"| {x['source_feature_id']} | {x['admin']} | {x['name']} | {x['type_en']} | {x['adm1_code']} | "
            f"{x['iso_3166_2']} | {x['geodesic_area_km2']:.1f} | {x['geometry_part_count']} | {x['logical_admin1_id']} |"
        )
    lines += [
        "",
        "## Ambiguous current records — first 50",
        "",
        "| Current ID | legacy_id | name | candidate source IDs |",
        "|---|---|---|---|",
    ]
    for x in report.get("ambiguous_current_records", [])[:50]:
        lines.append(
            f"| {x['province_id']} | {x['legacy_id']} | {x['name']} | {', '.join(x['candidate_source_feature_ids'])} |"
        )
    lines += [
        "",
        "## Contract locked by this manifest",
        "",
        "1. `source_feature_id` identifies an untouched Natural Earth feature and prefers `adm1_code`.",
        "2. `logical_admin1_id` owns region assignment and target-cell count.",
        "3. Polygon/render pieces are children and never receive independent minimum-one-cell budgets.",
        "4. Small area, neighbour size and `type_en` are review signals only; they cannot silently merge boundaries.",
        "5. Mixed-level corrections are explicit named aggregations with lineage, not destructive geometry heuristics.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("shp", type=Path)
    args = parser.parse_args()

    reader = shapefile.Reader(str(args.shp), encoding="utf-8")
    fields = [f[0] for f in reader.fields[1:]]
    raw_rows = list(reader.iterShapeRecords())
    code_counts = Counter(fix_text(dict(zip(fields, sr.record)).get("adm1_code")) for sr in raw_rows)
    duplicate_codes = {code for code, n in code_counts.items() if code and n > 1}

    features: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    for sr in raw_rows:
        props = dict(zip(fields, sr.record))
        admin = fix_text(props.get("admin"))
        name = fix_text(props.get("name") or props.get("name_en") or admin)
        region = fix_text(props.get("region"))
        type_en = fix_text(props.get("type_en"))
        adm1_code = fix_text(props.get("adm1_code"))
        iso = fix_text(props.get("iso_3166_2"))
        geom = shape(sr.shape.__geo_interface__)
        sid = source_feature_id(props, geom, duplicate_codes)
        if sid in source_ids:
            raise SystemExit(f"duplicate generated source_feature_id: {sid}")
        source_ids.add(sid)
        part_count = len(getattr(geom, "geoms", [geom]))
        item = {
            "source_feature_id": sid,
            "admin": admin,
            "name": name,
            "region": region,
            "type_en": type_en,
            "adm1_code": adm1_code,
            "iso_3166_2": iso,
            "legacy_base_id": f"{slug(admin)}__{slug(name)}",
            "geodesic_area_km2": round(geodesic_area_km2(geom), 6),
            "geometry_type": geom.geom_type,
            "geometry_part_count": part_count,
            "bbox_lonlat": [round(float(x), 7) for x in geom.bounds],
            "fine_type_review": type_en in FINE_TYPES,
        }
        logical_id, logical_name, reason, explicit = logical_parent_for(item)
        item["logical_admin1_id"] = logical_id
        item["logical_name"] = logical_name
        item["logical_parent_reason"] = reason
        item["explicit_aggregation_member"] = explicit
        features.append(item)

    logical_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in features:
        logical_groups[f["logical_admin1_id"]].append(f)
    logical_parents = []
    for logical_id, members in sorted(logical_groups.items()):
        logical_parents.append({
            "logical_admin1_id": logical_id,
            "name": members[0]["logical_name"],
            "admin": members[0]["admin"],
            "source_feature_ids": [m["source_feature_id"] for m in members],
            "source_feature_count": len(members),
            "source_geodesic_area_km2_sum": round(sum(m["geodesic_area_km2"] for m in members), 6),
            "explicit_aggregation": any(m["explicit_aggregation_member"] for m in members),
            "reason": members[0]["logical_parent_reason"],
        })

    manifest = {
        "schema_version": 1,
        "format": "world_admin1_source_manifest/v1",
        "source": {
            "dataset": "Natural Earth 1:10m Admin 1 – States, Provinces",
            "shapefile_name": args.shp.name,
            "feature_count": len(features),
            "identity_priority": ["adm1_code", "deterministic semantic+bbox fallback"],
        },
        "policy": {
            "heuristic_area_merge": False,
            "heuristic_neighbor_merge": False,
            "terrain_relief_rivers_used": False,
            "polygon_parts_are_independent_game_provinces": False,
            "explicit_mixed_level_aggregation_only": True,
        },
        "source_features": sorted(features, key=lambda x: x["source_feature_id"]),
        "logical_parents": logical_parents,
    }
    OUT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    by_legacy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in features:
        by_legacy[f["legacy_base_id"]].append(f)
    known_bases = set(by_legacy)
    targets_doc = json.loads(TARGETS.read_text(encoding="utf-8")) if TARGETS.exists() else {"provinces": []}
    current = list(targets_doc.get("provinces", []))
    unique_matches = []
    ambiguous = []
    unmatched = []
    piece_suffix_count = 0
    for rec in current:
        legacy_id = str(rec.get("legacy_id", ""))
        base = peel_to_known_base(legacy_id, known_bases)
        if base and base != legacy_id:
            piece_suffix_count += 1
        candidates = by_legacy.get(base or "", [])
        base_item = {
            "province_id": str(rec.get("province_id", "")),
            "legacy_id": legacy_id,
            "resolved_legacy_base_id": base or "",
            "name": str(rec.get("name", "")),
            "country_prefix": str(rec.get("country_prefix", "")),
            "current_area_km2": float(rec.get("area_km2", 0.0)),
            "current_target_cell_count": int(rec.get("target_cell_count", 0)),
        }
        if len(candidates) == 1:
            x = dict(base_item)
            x["source_feature_id"] = candidates[0]["source_feature_id"]
            x["logical_admin1_id"] = candidates[0]["logical_admin1_id"]
            unique_matches.append(x)
        elif len(candidates) > 1:
            x = dict(base_item)
            x["candidate_source_feature_ids"] = [c["source_feature_id"] for c in candidates]
            x["candidate_adm1_codes"] = [c["adm1_code"] for c in candidates]
            ambiguous.append(x)
        else:
            unmatched.append(base_item)

    distinct_unique_parents = {x["source_feature_id"] for x in unique_matches}
    watch_names = {"Appenzell Innerrhoden", "Jekabpils", "Northumberland"}
    watch = [x for x in features if x["name"] in watch_names]
    report = {
        "schema_version": 1,
        "format": "world_admin1_source_migration_audit/v1",
        "summary": {
            "raw_source_feature_count": len(features),
            "unique_source_feature_id_count": len(source_ids),
            "logical_parent_count": len(logical_parents),
            "explicit_aggregation_member_count": sum(1 for f in features if f["explicit_aggregation_member"]),
            "fine_type_feature_count": sum(1 for f in features if f["fine_type_review"]),
            "duplicate_nonempty_adm1_code_count": len(duplicate_codes),
            "current_target_record_count": len(current),
            "current_unique_source_match_count": len(unique_matches),
            "current_ambiguous_source_match_count": len(ambiguous),
            "current_unmatched_source_count": len(unmatched),
            "current_piece_suffix_record_count": piece_suffix_count,
            "distinct_unique_matched_source_parent_count": len(distinct_unique_parents),
            "migration_is_safe_without_rebuild": False,
        },
        "watch_source_features": sorted(watch, key=lambda x: (x["admin"], x["name"], x["adm1_code"])),
        "ambiguous_current_records": ambiguous,
        "unmatched_current_records": unmatched,
        "explicit_aggregation_parents": [x for x in logical_parents if x["explicit_aggregation"]],
        "notes": [
            "Unique legacy-name matching is lineage assistance only; current geometry remains untrusted because old preprocessing merged neighbours destructively.",
            "A clean geometry rebuild from raw source is required before recalculating world cell targets.",
            "adm1_code is preferred over ISO because different raw source features may share the same ISO code.",
        ],
    }
    OUT_MIGRATION.parent.mkdir(parents=True, exist_ok=True)
    OUT_MIGRATION.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_MD.write_text(render_md(report), encoding="utf-8")
    print("WORLD_ADMIN1_SOURCE_MANIFEST", json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
