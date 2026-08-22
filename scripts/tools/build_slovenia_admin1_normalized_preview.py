#!/usr/bin/env python3
"""Build a Slovenia-only Admin-1 normalization preview.

Natural Earth mixes 181 Commune|Municipality records with 12 Statistical Region
records in Slovenia. All 193 source features carry a `region` value. This
preview groups the safe source geometry by that explicit Natural Earth region
field, producing 12 normalized statistical-region parents without heuristic
area/neighbour merging.

This is a review/debug artifact, not yet the global normalization policy.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "assets/game_data/world_admin1_source_manifest.json"
SAFE_PIECES = ROOT / "assets/map_geometry/world_admin1_safe_pieces.json"
OUT_PARENTS = ROOT / "assets/game_data/slovenia_admin1_normalized_preview.json"
OUT_PIECES = ROOT / "assets/map_geometry/slovenia_admin1_normalized_preview_pieces.json"
OUT_REPORT = ROOT / "reports/slovenia_admin1_normalized_preview.json"
OUT_MD = ROOT / "reports/slovenia_admin1_normalized_preview.md"

EXPECTED_SOURCE_FEATURES = 193
EXPECTED_REGIONS = 12
COUNTRY = "Slovenia"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slug(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "unnamed"


def polygon_from_rings(rings: list[Any]) -> Polygon:
    outer = rings[0]
    holes = [r for r in rings[1:] if len(r) >= 4]
    geom = Polygon(outer, holes)
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom


def explode(geom: Any) -> list[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, (MultiPolygon, GeometryCollection)) or hasattr(geom, "geoms"):
        out: list[Polygon] = []
        for child in geom.geoms:
            out.extend(explode(child))
        return out
    return []


def rings_from_polygon(poly: Polygon) -> list[list[list[float]]]:
    rings: list[list[list[float]]] = []
    rings.append([[round(float(x), 2), round(float(y), 2)] for x, y in poly.exterior.coords])
    for hole in poly.interiors:
        coords = [[round(float(x), 2), round(float(y), 2)] for x, y in hole.coords]
        if len(coords) >= 4:
            rings.append(coords)
    return rings


def bbox_of(poly: Polygon) -> list[float]:
    minx, miny, maxx, maxy = poly.bounds
    return [round(minx, 2), round(miny, 2), round(maxx, 2), round(maxy, 2)]


def main() -> None:
    manifest = read_json(MANIFEST)
    safe = read_json(SAFE_PIECES)

    source_features = [x for x in manifest.get("source_features", []) if str(x.get("admin", "")) == COUNTRY]
    if len(source_features) != EXPECTED_SOURCE_FEATURES:
        raise RuntimeError(f"Slovenia source count mismatch: {len(source_features)}")

    pieces_by_parent: dict[str, list[Polygon]] = defaultdict(list)
    for raw in safe.get("pieces", []):
        parent_id = str(raw.get("logical_admin1_id", ""))
        rings = raw.get("rings", [])
        if not parent_id or not rings:
            continue
        geom = polygon_from_rings(rings)
        if not geom.is_empty:
            pieces_by_parent[parent_id].append(geom)

    region_sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
    region_parent_ids: dict[str, set[str]] = defaultdict(set)
    parent_to_region: dict[str, str] = {}
    empty_region: list[str] = []
    for feature in source_features:
        region = str(feature.get("region", "")).strip()
        source_id = str(feature.get("source_feature_id", ""))
        parent_id = str(feature.get("logical_admin1_id", ""))
        if not region:
            empty_region.append(source_id)
            continue
        if not parent_id or parent_id not in pieces_by_parent:
            raise RuntimeError(f"Missing safe geometry for {source_id} / {parent_id}")
        previous = parent_to_region.get(parent_id)
        if previous and previous != region:
            raise RuntimeError(f"Logical parent {parent_id} appears in two Slovenia regions: {previous}, {region}")
        parent_to_region[parent_id] = region
        region_sources[region].append(feature)
        region_parent_ids[region].add(parent_id)

    if empty_region:
        raise RuntimeError(f"Slovenia source features without region: {empty_region[:10]}")
    if len(region_sources) != EXPECTED_REGIONS:
        raise RuntimeError(f"Slovenia region count mismatch: {len(region_sources)}")

    normalized_parents: list[dict[str, Any]] = []
    normalized_pieces: list[dict[str, Any]] = []
    normalized_geoms: dict[str, Any] = {}

    for region in sorted(region_sources):
        parent_ids = sorted(region_parent_ids[region])
        source_items = region_sources[region]
        geoms: list[Any] = []
        for parent_id in parent_ids:
            geoms.extend(pieces_by_parent[parent_id])
        merged = unary_union(geoms)
        if not merged.is_valid:
            merged = merged.buffer(0)
        normalized_id = f"admin1:preview:slovenia:{slug(region)}"
        normalized_geoms[normalized_id] = merged
        piece_ids: list[str] = []
        for index, poly in enumerate(explode(merged), start=1):
            piece_id = f"piece:{normalized_id}:{index}"
            piece_ids.append(piece_id)
            normalized_pieces.append({
                "piece_id": piece_id,
                "normalized_admin1_id": normalized_id,
                "name": region,
                "rings": rings_from_polygon(poly),
                "bbox": bbox_of(poly),
            })
        normalized_parents.append({
            "normalized_admin1_id": normalized_id,
            "name": region,
            "admin": COUNTRY,
            "normalization_method": "group_by_natural_earth_region_field",
            "source_logical_admin1_ids": parent_ids,
            "source_logical_admin1_count": len(parent_ids),
            "source_feature_ids": sorted(str(x.get("source_feature_id", "")) for x in source_items),
            "source_feature_count": len(source_items),
            "source_names": sorted(str(x.get("name", "")) for x in source_items),
            "source_type_en_counts": dict(sorted(__import__("collections").Counter(str(x.get("type_en", "")) for x in source_items).items())),
            "source_geodesic_area_km2_sum": round(sum(float(x.get("geodesic_area_km2", 0.0) or 0.0) for x in source_items), 6),
            "piece_ids": piece_ids,
            "piece_count": len(piece_ids),
        })

    raw_union = unary_union([g for pid in sorted(parent_to_region) for g in pieces_by_parent[pid]])
    normalized_union = unary_union(list(normalized_geoms.values()))
    symdiff = raw_union.symmetric_difference(normalized_union).area
    raw_area = raw_union.area
    union_match_ratio = 1.0 if raw_area <= 0 else max(0.0, 1.0 - symdiff / raw_area)

    overlap_total = 0.0
    ids = list(normalized_geoms)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            overlap_total += normalized_geoms[a].intersection(normalized_geoms[b]).area

    source_ids = [str(x.get("source_feature_id", "")) for x in source_features]
    used_source_ids = [sid for p in normalized_parents for sid in p["source_feature_ids"]]
    source_used_once = len(used_source_ids) == len(source_ids) and len(set(used_source_ids)) == len(source_ids) and set(used_source_ids) == set(source_ids)

    parents_doc = {
        "schema_version": 1,
        "format": "slovenia_admin1_normalized_preview/v1",
        "status": "REVIEW_PREVIEW_NOT_GLOBAL_POLICY",
        "country": COUNTRY,
        "method": "group_by_natural_earth_region_field",
        "source_manifest": str(MANIFEST.relative_to(ROOT)),
        "source_safe_pieces": str(SAFE_PIECES.relative_to(ROOT)),
        "source_feature_count": len(source_features),
        "normalized_parent_count": len(normalized_parents),
        "parents": normalized_parents,
    }
    pieces_doc = {
        "schema_version": 1,
        "format": "slovenia_admin1_normalized_preview_pieces/v1",
        "country": COUNTRY,
        "normalized_parent_count": len(normalized_parents),
        "piece_count": len(normalized_pieces),
        "pieces": normalized_pieces,
    }
    summary = {
        "source_feature_count": len(source_features),
        "source_logical_parent_count": len(parent_to_region),
        "normalized_parent_count": len(normalized_parents),
        "normalized_piece_count": len(normalized_pieces),
        "source_used_exactly_once": source_used_once,
        "union_match_ratio": round(union_match_ratio, 9),
        "normalized_pair_overlap_world_px2": round(overlap_total, 9),
        "source_geodesic_area_km2_sum": round(sum(float(x.get("geodesic_area_km2", 0.0) or 0.0) for x in source_features), 3),
    }
    report = {
        "schema_version": 1,
        "format": "slovenia_admin1_normalized_preview_audit/v1",
        "summary": summary,
        "regions": normalized_parents,
    }

    write_json(OUT_PARENTS, parents_doc)
    write_json(OUT_PIECES, pieces_doc)
    write_json(OUT_REPORT, report)

    lines = [
        "# Slovenia Admin-1 normalized preview",
        "",
        "> REVIEW PREVIEW: этот результат ещё не является глобальной normalization policy.",
        "",
        "## Итог",
        "",
        f"- Natural Earth source features: **{len(source_features)}**.",
        f"- Safe logical parents used: **{len(parent_to_region)}**.",
        f"- Normalized Statistical Regions: **{len(normalized_parents)}**.",
        f"- Source used exactly once: **{'yes' if source_used_once else 'NO'}**.",
        f"- Union match ratio: **{union_match_ratio:.9f}**.",
        f"- Pair overlap after normalization: **{overlap_total:.9f} world px²**.",
        "",
        "| Region | source features | source km² | pieces |",
        "|---|---:|---:|---:|",
    ]
    for parent in normalized_parents:
        lines.append(f"| {parent['name']} | {parent['source_feature_count']} | {parent['source_geodesic_area_km2_sum']:.1f} | {parent['piece_count']} |")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("SLOVENIA_ADMIN1_NORMALIZED_PREVIEW", json.dumps(summary, ensure_ascii=False))
    if not source_used_once or len(normalized_parents) != EXPECTED_REGIONS or union_match_ratio < 0.999999:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
