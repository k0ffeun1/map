#!/usr/bin/env python3
"""Conservative cleanup of tiny internal region slivers.

The world draft can assign tiny layer-8 polygon pieces to a neighbouring
historical region. Once regions are dissolved those mistakes appear as small
holes/shards inside an otherwise continuous region. This pass fixes only
high-confidence *domestic* slivers:

- never edits locked assignments;
- never crosses a country prefix (protects real international enclaves);
- candidate must be small relative to its table cell target;
- >=82% of its perimeter must touch other land pieces;
- >=84% of the covered perimeter must be surrounded by ONE other region;
- only review/medium assignments are eligible by default.

No geometry is modified. Only province -> region assignment changes.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from shapely.geometry import Polygon
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[2]
WORLD_PX = 8192.0
EARTH_RADIUS_KM = 6371.0088

GEOMETRY_PATH = ROOT / "assets" / "map_geometry" / "provinces.json"
IDENTITY_PATH = ROOT / "assets" / "game_data" / "provinces.json"
ASSIGNMENTS_PATH = ROOT / "assets" / "game_data" / "world_region_assignments_island_corrected.json"
TARGETS_PATH = ROOT / "assets" / "game_data" / "world_province_cell_targets_island_corrected.json"
OUT_ASSIGNMENTS = ROOT / "assets" / "game_data" / "world_region_assignments_cleaned.json"
OUT_REPORT = ROOT / "reports" / "world_region_sliver_cleanup.json"

EXPECTED = 4027
NEIGHBOR_EPS_WORLD_PX = 0.42
MIN_COVERED_PERIMETER = 0.82
MIN_DOMINANT_SHARE = 0.84
MAX_ABSOLUTE_AREA_KM2 = 1800.0
MAX_TARGET_RATIO = 0.80
MAX_PASSES = 4


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(value: Any, compact: bool = False) -> str:
    if compact:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def geom(entry: dict[str, Any]) -> Polygon:
    rings = entry.get("rings", [])
    if not rings:
        return Polygon()
    g = Polygon(rings[0], rings[1:])
    if not g.is_valid:
        g = g.buffer(0)
    if g.geom_type == "Polygon":
        return g
    # Layer-8 currently stores one polygon piece per record. buffer(0) can
    # exceptionally return MultiPolygon; use the largest repaired component.
    parts = [x for x in getattr(g, "geoms", []) if x.geom_type == "Polygon"]
    return max(parts, key=lambda x: x.area) if parts else Polygon()


def km_per_world_px(y: float) -> float:
    n = math.pi - 2.0 * math.pi * y / WORLD_PX
    lat = math.degrees(math.atan(math.sinh(n)))
    return 2.0 * math.pi * EARTH_RADIUS_KM / WORLD_PX * math.cos(math.radians(lat))


def area_km2(g: Polygon) -> float:
    if g.is_empty:
        return 0.0
    s = km_per_world_px(float(g.representative_point().y))
    return float(g.area) * s * s


def country_prefix(legacy_id: str) -> str:
    return legacy_id.split("__", 1)[0] if "__" in legacy_id else legacy_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    identities = {str(x["id"]): x for x in read(IDENTITY_PATH).get("provinces", [])}
    assignments_doc = read(ASSIGNMENTS_PATH)
    assignments = [dict(x) for x in assignments_doc.get("assignments", [])]
    by_id = {str(x["province_id"]): x for x in assignments}
    targets = {str(x["province_id"]): x for x in read(TARGETS_PATH).get("provinces", [])}

    ids: list[str] = []
    geoms: list[Polygon] = []
    for entry in read(GEOMETRY_PATH).get("provinces", []):
        pid = str(entry.get("id", ""))
        g = geom(entry)
        if pid and not g.is_empty:
            ids.append(pid)
            geoms.append(g)
    if not (len(ids) == len(assignments) == len(identities) == EXPECTED):
        raise RuntimeError(f"coverage mismatch geometry={len(ids)} assignments={len(assignments)} identities={len(identities)}")

    tree = STRtree(geoms)
    corrections: list[dict[str, Any]] = []
    pass_stats: list[dict[str, Any]] = []

    for pass_index in range(MAX_PASSES):
        changes: list[tuple[str, str, str, dict[str, Any]]] = []
        for index, pid in enumerate(ids):
            a = by_id[pid]
            confidence = str(a.get("confidence", ""))
            if confidence == "locked" or confidence not in {"review", "medium", ""}:
                continue
            identity = identities[pid]
            legacy = str(identity.get("legacy_id", ""))
            country = country_prefix(legacy)
            g = geoms[index]
            province_area = area_km2(g)
            target_area = float(targets.get(pid, {}).get("region_target_cell_area_km2", 2200.0) or 2200.0)
            if province_area > MAX_ABSOLUTE_AREA_KM2 or province_area > target_area * MAX_TARGET_RATIO:
                continue

            perimeter = float(g.length)
            if perimeter <= 1.0e-9:
                continue
            probe = g.buffer(NEIGHBOR_EPS_WORLD_PX)
            region_touch: dict[str, float] = defaultdict(float)
            region_name: dict[str, str] = {}
            covered = 0.0
            seen_neighbors = 0
            for raw_j in tree.query(probe):
                j = int(raw_j)
                if j == index:
                    continue
                other_pid = ids[j]
                other_identity = identities[other_pid]
                if country_prefix(str(other_identity.get("legacy_id", ""))) != country:
                    continue
                other = geoms[j]
                if not probe.intersects(other):
                    continue
                # Length of candidate boundary lying within a tiny buffer of
                # the neighbour. This tolerates source rounding/gap noise.
                touch = float(g.boundary.intersection(other.buffer(NEIGHBOR_EPS_WORLD_PX)).length)
                if touch <= 1.0e-8:
                    continue
                seen_neighbors += 1
                covered += touch
                oa = by_id[other_pid]
                rid = str(oa.get("region_id", ""))
                if rid:
                    region_touch[rid] += touch
                    region_name[rid] = str(oa.get("region_name", rid))

            if not region_touch or seen_neighbors < 2:
                continue
            covered_ratio = min(1.0, covered / perimeter)
            if covered_ratio < MIN_COVERED_PERIMETER:
                continue
            dominant_rid, dominant_touch = max(region_touch.items(), key=lambda kv: kv[1])
            dominant_share = dominant_touch / max(1.0e-9, sum(region_touch.values()))
            if dominant_share < MIN_DOMINANT_SHARE:
                continue
            if dominant_rid == str(a.get("region_id", "")):
                continue
            meta = {
                "province_id": pid,
                "legacy_id": legacy,
                "name": str(identity.get("name", "")),
                "area_km2": round(province_area, 3),
                "from_region_id": str(a.get("region_id", "")),
                "from_region": str(a.get("region_name", "")),
                "to_region_id": dominant_rid,
                "to_region": region_name.get(dominant_rid, dominant_rid),
                "covered_perimeter_ratio": round(covered_ratio, 4),
                "dominant_region_share": round(dominant_share, 4),
                "confidence_before": confidence,
                "pass": pass_index + 1,
            }
            changes.append((pid, dominant_rid, region_name.get(dominant_rid, dominant_rid), meta))

        # Apply simultaneously to avoid order-dependent flood fill.
        for pid, rid, rname, meta in changes:
            item = by_id[pid]
            item["region_id"] = rid
            item["region_name"] = rname
            item["method"] = "surrounded_domestic_sliver_cleanup"
            item["confidence"] = "high"
            corrections.append(meta)
        pass_stats.append({"pass": pass_index + 1, "correction_count": len(changes)})
        if not changes:
            break

    out = dict(assignments_doc)
    out["format"] = "world_region_assignments_cleaned/v1"
    out["source"] = str(ASSIGNMENTS_PATH)
    out["cleanup_method"] = "conservative_same_country_surrounded_sliver_cleanup"
    out["assignments"] = assignments
    out["province_count"] = len(assignments)

    report = {
        "schema_version": 1,
        "format": "world_region_sliver_cleanup_report/v1",
        "province_count": len(assignments),
        "correction_count": len(corrections),
        "pass_stats": pass_stats,
        "thresholds": {
            "neighbor_eps_world_px": NEIGHBOR_EPS_WORLD_PX,
            "min_covered_perimeter": MIN_COVERED_PERIMETER,
            "min_dominant_region_share": MIN_DOMINANT_SHARE,
            "max_absolute_area_km2": MAX_ABSOLUTE_AREA_KM2,
            "max_target_ratio": MAX_TARGET_RATIO,
        },
        "safety": {
            "locked_assignments_untouched": True,
            "cross_country_moves_forbidden": True,
            "eligible_confidence": ["review", "medium", ""],
        },
        "corrections": corrections,
        "hard_fail": False,
    }

    outputs = ((OUT_ASSIGNMENTS, out, True), (OUT_REPORT, report, False))
    for path, value, compact in outputs:
        text = dump(value, compact)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                raise RuntimeError(f"--check mismatch: {path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    print("WORLD_REGION_SLIVER_CLEANUP_OK", f"provinces={len(assignments)}", f"corrections={len(corrections)}", f"passes={len(pass_stats)}")


if __name__ == "__main__":
    main()
