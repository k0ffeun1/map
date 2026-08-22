#!/usr/bin/env python3
"""Inspect the SAFE logical Admin-1 source around Britain and the North Atlantic.

The legacy Layer-8 source has a known pathological family around Scotland
(`united_kingdom__northumberland*`).  This audit checks the newer SAFE source so the
regional Britain build can start from correct source features without altering any old
layer.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "assets" / "game_data" / "world_admin1_source_manifest.json"
PIECES = ROOT / "assets" / "map_geometry" / "world_admin1_safe_pieces.json"
REPORT = ROOT / "reports" / "britain_north_atlantic_safe_admin1_audit.json"
WORLD_PX = 8192.0


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


def main() -> None:
    manifest = read_json(MANIFEST)
    pieces_doc = read_json(PIECES)
    meta = {str(x.get("logical_admin1_id", "")): x for x in manifest.get("source_features", []) if isinstance(x, dict)}
    piece_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in pieces_doc.get("pieces", []):
        if isinstance(p, dict):
            pid = str(p.get("logical_admin1_id", ""))
            if pid:
                piece_groups[pid].append(p)

    rows: list[dict[str, Any]] = []
    for pid, parts in piece_groups.items():
        minx=min(float(p["bbox"][0]) for p in parts if isinstance(p.get("bbox"), list) and len(p["bbox"]) >= 4)
        miny=min(float(p["bbox"][1]) for p in parts if isinstance(p.get("bbox"), list) and len(p["bbox"]) >= 4)
        maxx=max(float(p["bbox"][2]) for p in parts if isinstance(p.get("bbox"), list) and len(p["bbox"]) >= 4)
        maxy=max(float(p["bbox"][3]) for p in parts if isinstance(p.get("bbox"), list) and len(p["bbox"]) >= 4)
        lon, lat = world_to_lonlat((minx+maxx)*0.5, (miny+maxy)*0.5)
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
    rows.sort(key=lambda r:(r["bucket"], r["admin"], r["centroid_lat"], r["centroid_lon"], r["name"]))
    by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_bucket[r["bucket"]].append(r)

    out = {
        "format": "britain_north_atlantic_safe_admin1_audit/v1",
        "selected_parent_count": len(rows),
        "bucket_counts": {k: len(v) for k,v in sorted(by_bucket.items())},
        "admin_counts": dict(sorted(__import__('collections').Counter(r['admin'] for r in rows).items())),
        "rows": rows,
        "notes": [
            "SAFE Admin-1 is inspected only as source geometry; no existing layer is modified.",
            "Final gameplay provinces may group multiple SAFE features and may split a large SAFE feature by generated cells.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print('SAFE_TOTAL', len(rows))
    print('SAFE_BUCKET_COUNTS', json.dumps(out['bucket_counts'], ensure_ascii=False))
    print('SAFE_ADMIN_COUNTS', json.dumps(out['admin_counts'], ensure_ascii=False))
    for r in rows:
        print('SAFE_ROW', json.dumps(r, ensure_ascii=False))


if __name__ == '__main__':
    main()
