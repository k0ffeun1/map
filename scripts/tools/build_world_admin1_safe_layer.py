#!/usr/bin/env python3
"""Build a clean logical Natural Earth Admin-1 layer for the world map.

This is the replacement path for the legacy 4027 post-processed province table.
It deliberately does NOT call build_provinces._merge_small_pieces and does not
use area/neighbour/type heuristics to merge real administrative units.

Identity model:
  source_feature_id -> immutable Natural Earth feature (prefers adm1_code)
  logical_admin1_id -> gameplay/map Admin-1 parent
  piece_id          -> one render Polygon child of a logical parent

Only explicit aggregations from assets/game_data/world_admin1_level_policy.json
are allowed to combine several source features.  Polygon parts are never
independent logical Admin-1 identities.

Inputs:
  - Natural Earth 10m Admin-1 shapefile (CLI argument)
  - assets/game_data/world_admin1_source_manifest.json
  - assets/game_data/world_admin1_level_policy.json

Outputs:
  - assets/game_data/world_admin1_logical_parents.json
  - assets/map_geometry/world_admin1_safe_pieces.json
  - reports/world_admin1_safe_layer_build.json
  - reports/world_admin1_safe_layer_build.md
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import shapefile
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "assets/game_data/world_admin1_source_manifest.json"
POLICY_PATH = ROOT / "assets/game_data/world_admin1_level_policy.json"
OUT_PARENTS = ROOT / "assets/game_data/world_admin1_logical_parents.json"
OUT_PIECES = ROOT / "assets/map_geometry/world_admin1_safe_pieces.json"
OUT_REPORT = ROOT / "reports/world_admin1_safe_layer_build.json"
OUT_MD = ROOT / "reports/world_admin1_safe_layer_build.md"

WORLD_PX = 8192.0
LAT_NORTH = 76.0
LAT_SOUTH = -58.0
SIMPLIFY_TOLERANCE_DEG = 0.01
EXPECTED_SOURCE_FEATURES = 4596
EXPECTED_LOGICAL_PARENTS = 4564


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fix_text(value: Any) -> str:
    s = "" if value is None else str(value)
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def explode(geom: Any) -> list[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, (MultiPolygon, GeometryCollection)) or hasattr(geom, "geoms"):
        result: list[Polygon] = []
        for child in geom.geoms:
            result.extend(explode(child))
        return result
    return []


def lonlat_to_world(lon: float, lat: float) -> tuple[float, float]:
    lat = max(-85.05112878, min(85.05112878, float(lat)))
    x = (float(lon) + 180.0) / 360.0 * WORLD_PX
    lat_rad = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * WORLD_PX
    return x, y


def project_ring(coords: Any) -> list[list[float]]:
    return [[round(x, 2), round(y, 2)] for x, y in (lonlat_to_world(*p[:2]) for p in coords)]


def polygon_to_piece(piece_id: str, logical_id: str, source_ids: list[str], geom: Polygon) -> dict[str, Any]:
    rings = [project_ring(geom.exterior.coords)]
    for hole in geom.interiors:
        ring = project_ring(hole.coords)
        if len(ring) >= 4:
            rings.append(ring)
    pts = rings[0]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return {
        "piece_id": piece_id,
        "logical_admin1_id": logical_id,
        "source_feature_ids": source_ids,
        "rings": rings,
        "bbox": [min(xs), min(ys), max(xs), max(ys)],
    }


def manifest_index(manifest: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    features = {str(x["source_feature_id"]): x for x in manifest.get("source_features", [])}
    parents = {str(x["logical_admin1_id"]): x for x in manifest.get("logical_parents", [])}
    return features, parents


def shapefile_key(props: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        fix_text(props.get("adm1_code")),
        fix_text(props.get("admin")),
        fix_text(props.get("name") or props.get("name_en") or props.get("admin")),
        fix_text(props.get("type_en")),
        fix_text(props.get("iso_3166_2")),
    )


def manifest_key(item: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(item.get("adm1_code", "")),
        str(item.get("admin", "")),
        str(item.get("name", "")),
        str(item.get("type_en", "")),
        str(item.get("iso_3166_2", "")),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("shp", type=Path, help="Natural Earth ne_10m_admin_1_states_provinces.shp")
    args = parser.parse_args()

    manifest = read_json(MANIFEST_PATH)
    policy = read_json(POLICY_PATH)
    feature_by_id, parent_by_id = manifest_index(manifest)
    if len(feature_by_id) != EXPECTED_SOURCE_FEATURES:
        raise SystemExit(f"manifest source feature count mismatch: {len(feature_by_id)}")
    if len(parent_by_id) != EXPECTED_LOGICAL_PARENTS:
        raise SystemExit(f"manifest logical parent count mismatch: {len(parent_by_id)}")

    # Match shapefile rows to immutable manifest identities.  adm1_code is the
    # normal stable key; full semantic tuple resolves the rare duplicate-code
    # fallback cases without relying on row order.
    manifest_by_semantic: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    manifest_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in feature_by_id.values():
        manifest_by_semantic[manifest_key(item)].append(item)
        code = str(item.get("adm1_code", ""))
        if code:
            manifest_by_code[code].append(item)

    reader = shapefile.Reader(str(args.shp), encoding="utf-8")
    fields = [f[0] for f in reader.fields[1:]]
    raw_rows = list(reader.iterShapeRecords())
    if len(raw_rows) != EXPECTED_SOURCE_FEATURES:
        raise SystemExit(f"source shapefile feature count mismatch: {len(raw_rows)}")

    geometry_by_source: dict[str, Any] = {}
    unmatched_rows: list[dict[str, Any]] = []
    ambiguous_rows: list[dict[str, Any]] = []

    for sr in raw_rows:
        props = dict(zip(fields, sr.record))
        key = shapefile_key(props)
        code = key[0]
        candidates = manifest_by_semantic.get(key, [])
        if len(candidates) != 1 and code and len(manifest_by_code.get(code, [])) == 1:
            candidates = manifest_by_code[code]
        if len(candidates) != 1:
            view = {"adm1_code": code, "admin": key[1], "name": key[2], "type_en": key[3], "iso_3166_2": key[4]}
            if not candidates:
                unmatched_rows.append(view)
            else:
                view["candidate_source_feature_ids"] = [x["source_feature_id"] for x in candidates]
                ambiguous_rows.append(view)
            continue
        source_id = str(candidates[0]["source_feature_id"])
        if source_id in geometry_by_source:
            ambiguous_rows.append({"source_feature_id": source_id, "reason": "matched twice"})
            continue
        geom = shape(sr.shape.__geo_interface__)
        if not geom.is_valid:
            geom = geom.buffer(0)
        geometry_by_source[source_id] = geom

    if unmatched_rows or ambiguous_rows or len(geometry_by_source) != EXPECTED_SOURCE_FEATURES:
        raise SystemExit(
            f"source identity match failed: matched={len(geometry_by_source)} "
            f"unmatched={len(unmatched_rows)} ambiguous={len(ambiguous_rows)}"
        )

    crop = box(-180.0, LAT_SOUTH, 180.0, LAT_NORTH)
    pieces: list[dict[str, Any]] = []
    parents_out: list[dict[str, Any]] = []
    source_to_parent: dict[str, str] = {}

    for parent_id in sorted(parent_by_id):
        meta = parent_by_id[parent_id]
        source_ids = [str(x) for x in meta.get("source_feature_ids", [])]
        for sid in source_ids:
            source_to_parent[sid] = parent_id
        geoms = [geometry_by_source[sid] for sid in source_ids]
        # This union is legal because source_ids share one logical parent only
        # through an explicit policy. For ordinary parents len(geoms)==1, so
        # no administrative boundary is altered at all.
        geom = unary_union(geoms) if len(geoms) > 1 else geoms[0]
        if not geom.is_valid:
            geom = geom.buffer(0)
        geom = geom.intersection(crop)
        if geom.is_empty:
            # Polar clipping may legitimately remove a source feature from the
            # rendered world while its logical parent remains in the identity
            # catalog. Keep it with zero render pieces.
            parent_piece_ids: list[str] = []
        else:
            geom = geom.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
            parent_piece_ids = []
            for index, poly in enumerate(explode(geom), start=1):
                if poly.is_empty or len(poly.exterior.coords) < 4:
                    continue
                piece_id = f"piece:{parent_id}:{index}"
                parent_piece_ids.append(piece_id)
                pieces.append(polygon_to_piece(piece_id, parent_id, source_ids, poly))

        source_area = float(meta.get("source_geodesic_area_km2_sum", 0.0) or 0.0)
        parents_out.append({
            "logical_admin1_id": parent_id,
            "name": str(meta.get("name", "")),
            "admin": str(meta.get("admin", "")),
            "source_feature_ids": source_ids,
            "source_feature_count": len(source_ids),
            "source_geodesic_area_km2": source_area,
            "explicit_aggregation": bool(meta.get("explicit_aggregation", False)),
            "reason": str(meta.get("reason", "")),
            "piece_ids": parent_piece_ids,
            "piece_count": len(parent_piece_ids),
        })

    explicit_parents = [x for x in parents_out if x["explicit_aggregation"]]
    zero_piece_parents = [x for x in parents_out if x["piece_count"] == 0]
    multi_piece_parents = [x for x in parents_out if x["piece_count"] > 1]

    parent_doc = {
        "schema_version": 1,
        "format": "world_admin1_logical_parents/v1",
        "source_manifest": "assets/game_data/world_admin1_source_manifest.json",
        "policy_source": "assets/game_data/world_admin1_level_policy.json",
        "invariants": {
            "heuristic_area_merge": False,
            "heuristic_neighbor_merge": False,
            "polygon_piece_is_logical_admin1": False,
            "terrain_relief_rivers_used": False,
            "explicit_aggregation_only": True,
        },
        "logical_parent_count": len(parents_out),
        "parents": parents_out,
    }
    piece_doc = {
        "schema_version": 1,
        "format": "world_admin1_safe_pieces/v1",
        "world_px": WORLD_PX,
        "logical_parent_count": len(parents_out),
        "piece_count": len(pieces),
        "pieces": pieces,
    }

    report = {
        "schema_version": 1,
        "format": "world_admin1_safe_layer_build/v1",
        "summary": {
            "source_feature_count": len(feature_by_id),
            "logical_parent_count": len(parents_out),
            "render_piece_count": len(pieces),
            "explicit_aggregation_parent_count": len(explicit_parents),
            "explicit_aggregation_source_feature_count": sum(x["source_feature_count"] for x in explicit_parents),
            "multi_piece_parent_count": len(multi_piece_parents),
            "zero_piece_parent_count_after_world_crop": len(zero_piece_parents),
            "heuristic_merge_count": 0,
        },
        "explicit_aggregation_parents": explicit_parents,
        "zero_piece_parents_after_world_crop": zero_piece_parents,
        "watched": [
            x for x in parents_out
            if x["name"] in {"Appenzell Innerrhoden", "Jekabpils", "Northumberland", "Большой Лондон"}
        ],
    }

    write_json(OUT_PARENTS, parent_doc)
    write_json(OUT_PIECES, piece_doc)
    write_json(OUT_REPORT, report)

    lines = [
        "# Safe world Admin-1 layer build",
        "",
        "> Новый parent/piece слой. Старый `assets/provinces.json` этим этапом не перезаписывается.",
        "",
        "## Итог",
        "",
        f"- Natural Earth source features: **{len(feature_by_id)}**.",
        f"- Logical Admin-1 parents: **{len(parents_out)}**.",
        f"- Render Polygon pieces: **{len(pieces)}**.",
        f"- Explicit aggregation parents: **{len(explicit_parents)}**.",
        f"- Heuristic merges: **0**.",
        f"- Multi-piece logical parents: **{len(multi_piece_parents)}**.",
        f"- Parents clipped completely outside game latitude bounds: **{len(zero_piece_parents)}**.",
        "",
        "## Диагностические родители",
        "",
        "| Admin | Name | Source km² | source features | render pieces | explicit |",
        "|---|---|---:|---:|---:|---|",
    ]
    for x in report["watched"]:
        lines.append(
            f"| {x['admin']} | {x['name']} | {x['source_geodesic_area_km2']:.1f} | "
            f"{x['source_feature_count']} | {x['piece_count']} | {'yes' if x['explicit_aggregation'] else 'no'} |"
        )
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("WORLD_ADMIN1_SAFE_LAYER_BUILD", json.dumps(report["summary"], ensure_ascii=False))
    if len(parents_out) != EXPECTED_LOGICAL_PARENTS:
        raise SystemExit(2)
    if report["summary"]["heuristic_merge_count"] != 0:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
