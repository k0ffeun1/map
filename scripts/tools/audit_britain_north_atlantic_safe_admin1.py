#!/usr/bin/env python3
"""Inspect the SAFE logical Admin-1 source around Britain and the North Atlantic.

The legacy Layer-8 source has a known pathological family around Scotland
(`united_kingdom__northumberland*`). This audit checks the newer SAFE source and also
prints atomic polygon-piece hits for the Scottish archipelagos, so the regional build
can route islands independently without changing any old layer.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "assets" / "game_data" / "world_admin1_source_manifest.json"
PIECES = ROOT / "assets" / "map_geometry" / "world_admin1_safe_pieces.json"
REPORT = ROOT / "reports" / "britain_north_atlantic_safe_admin1_audit.json"
WORLD_PX = 8192.0

ISLAND_BOXES = {
    "outer_hebrides": (-8.8, -5.6, 56.6, 58.8),
    "inner_hebrides": (-7.2, -4.8, 55.2, 57.8),
    "orkney": (-3.8, -2.0, 58.7, 59.5),
    "shetland": (-2.2, -0.6, 59.7, 61.0),
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def world_to_lonlat(x: float, y: float) -> tuple[float, float]:
    lon = x / WORLD_PX * 360.0 - 180.0
    n = math.pi - 2.0 * math.pi * y / WORLD_PX
    lat = math.degrees(math.atan(math.sinh(n)))
    return lon, lat


def bucket(lon: float, lat: float) -> str:
    if -25.5 <= lon <= -12.0 and 62.5 <= lat <= 67.5:
        return "Iceland"
    if -8.2 <= lon <= -5.8 and 61.0 <= lat <= 63.0:
        return "Faroe Islands"
    if -11.5 <= lon <= -5.0 and 51.0 <= lat <= 56.1:
        return "Ireland"
    if -5.2 <= lon <= -4.0 and 53.9 <= lat <= 54.6:
        return "Isle of Man"
    if -3.2 <= lon <= -1.7 and 48.9 <= lat <= 50.1:
        return "Channel Islands"
    if -8.8 <= lon <= 2.5 and 49.4 <= lat <= 61.5:
        if lat >= 55.45:
            return "Scotland candidate"
        if -5.6 <= lon <= -2.5 and 51.25 <= lat <= 53.65:
            return "Wales candidate"
        return "England candidate"
    return ""


def piece_centroid_bbox(piece: dict[str, Any]) -> tuple[float, float] | None:
    bbox = piece.get("bbox")
    if not isinstance(bbox, list) or len(bbox) < 4:
        return None
    return world_to_lonlat((float(bbox[0]) + float(bbox[2])) * 0.5, (float(bbox[1]) + float(bbox[3])) * 0.5)


def island_box_hits(lon: float, lat: float) -> list[str]:
    hits: list[str] = []
    for name, (min_lon, max_lon, min_lat, max_lat) in ISLAND_BOXES.items():
        if min_lon <= lon <= max_lon and min_lat <= lat <= max_lat:
            hits.append(name)
    return hits


def main() -> None:
    manifest = read_json(MANIFEST)
    pieces_doc = read_json(PIECES)
    meta = {str(x.get("logical_admin1_id", "")): x for x in manifest.get("source_features", []) if isinstance(x, dict)}
    piece_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_pieces: list[dict[str, Any]] = []
    for p in pieces_doc.get("pieces", []):
        if isinstance(p, dict):
            pid = str(p.get("logical_admin1_id", ""))
            if pid:
                piece_groups[pid].append(p)
                all_pieces.append(p)

    rows: list[dict[str, Any]] = []
    for pid, parts in piece_groups.items():
        valid = [p for p in parts if isinstance(p.get("bbox"), list) and len(p["bbox"]) >= 4]
        if not valid:
            continue
        minx = min(float(p["bbox"][0]) for p in valid)
        miny = min(float(p["bbox"][1]) for p in valid)
        maxx = max(float(p["bbox"][2]) for p in valid)
        maxy = max(float(p["bbox"][3]) for p in valid)
        lon, lat = world_to_lonlat((minx + maxx) * 0.5, (miny + maxy) * 0.5)
        b = bucket(lon, lat)
        if not b:
            continue
        m = meta.get(pid, {})
        rows.append({
            "bucket": b,
            "logical_admin1_id": pid,
            "admin": str(m.get("admin", "")),
            "name": str(m.get("name", pid)),
            "type": str(m.get("type", m.get("type_en", ""))),
            "postal": str(m.get("postal", "")),
            "piece_count": len(parts),
            "centroid_lon": round(lon, 4),
            "centroid_lat": round(lat, 4),
        })
    rows.sort(key=lambda r: (r["bucket"], r["admin"], r["centroid_lat"], r["centroid_lon"], r["name"]))
    by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_bucket[r["bucket"]].append(r)

    island_hits: list[dict[str, Any]] = []
    for index, piece in enumerate(all_pieces):
        centroid = piece_centroid_bbox(piece)
        if centroid is None:
            continue
        lon, lat = centroid
        hits = island_box_hits(lon, lat)
        if not hits:
            continue
        pid = str(piece.get("logical_admin1_id", ""))
        m = meta.get(pid, {})
        if str(m.get("admin", "")) != "United Kingdom":
            continue
        island_hits.append({
            "piece_index": index,
            "piece_id": str(piece.get("id", piece.get("piece_id", ""))),
            "logical_admin1_id": pid,
            "name": str(m.get("name", pid)),
            "type": str(m.get("type", m.get("type_en", ""))),
            "boxes": hits,
            "centroid_lon": round(lon, 4),
            "centroid_lat": round(lat, 4),
            "bbox": piece.get("bbox", []),
        })
    island_hits.sort(key=lambda r: (r["boxes"][0], r["centroid_lat"], r["centroid_lon"], r["name"], r["piece_index"]))

    out = {
        "format": "britain_north_atlantic_safe_admin1_audit/v2",
        "selected_parent_count": len(rows),
        "bucket_counts": {k: len(v) for k, v in sorted(by_bucket.items())},
        "admin_counts": dict(sorted(Counter(r["admin"] for r in rows).items())),
        "rows": rows,
        "scottish_island_piece_hits": island_hits,
        "notes": [
            "SAFE Admin-1 is inspected only as source geometry; no existing layer is modified.",
            "Final gameplay provinces may group multiple SAFE features and may route individual polygon pieces into island provinces.",
            "Island boxes are diagnostic only; final routing is explicit in the regional rules file.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("SAFE_TOTAL", len(rows))
    print("SAFE_BUCKET_COUNTS", json.dumps(out["bucket_counts"], ensure_ascii=False))
    print("SAFE_ADMIN_COUNTS", json.dumps(out["admin_counts"], ensure_ascii=False))
    for r in rows:
        print("SAFE_ROW", json.dumps(r, ensure_ascii=False))
    for hit in island_hits:
        print("ISLAND_PIECE", json.dumps(hit, ensure_ascii=False))


if __name__ == "__main__":
    main()
