#!/usr/bin/env python3
"""Build Stage-6 gameplay cells for every Indian Admin-1 using world target counts.

This is an isolated architecture test. It does NOT replace the existing Stage-6
Iberia/stress output. The generated Indian cells are written to a separate file
and keep the world target_cell_count literally, including 18-cell Admin-1s.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from shapely.ops import unary_union

import build_stage6_universal_subdivisions as s

ROOT = Path(__file__).resolve().parents[2]
TARGETS_PRIMARY = ROOT / "assets" / "game_data" / "world_province_cell_targets_island_corrected.json"
TARGETS_FALLBACK = ROOT / "assets" / "game_data" / "world_province_cell_targets.json"
OUT_PATH = ROOT / "assets" / "subdivision_stage6" / "india_test_subdivisions.json"
REPORT_PATH = ROOT / "reports" / "india_stage6_test.json"
COUNTRY_PREFIX = "india"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def targets() -> tuple[Path, list[dict[str, Any]]]:
    path = TARGETS_PRIMARY if TARGETS_PRIMARY.exists() else TARGETS_FALLBACK
    rows = [
        row for row in read_json(path).get("provinces", [])
        if str(row.get("country_prefix", "")) == COUNTRY_PREFIX
    ]
    if not rows:
        raise RuntimeError("India target rows are missing")
    return path, rows


def build_province(sources: s.Sources, province_id: str, forced_count: int, target_row: dict[str, Any]) -> dict[str, Any]:
    parent = sources.geometry.get(province_id)
    if parent is None or parent.is_empty:
        raise RuntimeError("source Admin-1 geometry missing")

    land, coast_source, coastal = sources.gameplay_land(province_id)
    if not land.is_valid:
        land = land.buffer(0)
    parts = sorted(s.polygon_parts(land), key=lambda item: -item.area)
    if not parts:
        raise RuntimeError("gameplay land has no polygon parts")

    count = max(1, int(forced_count))
    anchor, anchor_name, anchor_source = sources.capital_anchor(province_id, land)
    allocations, satellites = s.allocate_zone_counts(parts, count)

    final: dict[str, Any] = {}
    generation_parts: list[dict[str, Any]] = []
    zone_offset = 0
    for component_index, (component, local_count) in enumerate(allocations):
        local_anchor = anchor if component.covers(anchor) else component.representative_point()
        local_final, stats = s.micro_partition(
            component,
            local_count,
            local_anchor,
            s.numeric_seed(province_id) + component_index * 100003,
            zone_offset,
        )
        final.update(local_final)
        stats["component_index"] = component_index
        stats["local_zone_count"] = local_count
        stats["component_area_km2"] = round(s.area_km2(component), 4)
        generation_parts.append(stats)
        zone_offset += local_count

    satellite_count = s.attach_satellites(final, satellites)
    validation = s.validate_final(land, final, count)
    if not validation["hard_validation_passed"]:
        raise RuntimeError(
            "hard final validation failed: missing=%s extra=%s overlap=%s zones=%s/%s"
            % (
                validation["coverage_missing_ratio"], validation["coverage_extra_ratio"],
                validation["overlap_ratio"], validation["zone_count"], count,
            )
        )

    zone_records: list[dict[str, Any]] = []
    neighbours = validation["neighbours"]
    for zid in sorted(final):
        geometry = final[zid]
        point = geometry.representative_point()
        min_x, min_y, max_x, max_y = geometry.bounds
        zone_records.append({
            "id": f"{province_id}:{zid}",
            "local_id": zid,
            "province_id": province_id,
            "parts": s.shape_parts_payload(geometry),
            "area_km2": round(s.area_km2(geometry), 4),
            "label_point": [round(float(point.x), 6), round(float(point.y), 6)],
            "bbox": [round(float(min_x), 6), round(float(min_y), 6), round(float(max_x), 6), round(float(max_y), 6)],
            "neighbors": [f"{province_id}:{other}" for other in neighbours.get(zid, [])],
            "multipart": len(s.polygon_parts(geometry)) > 1,
        })

    return {
        "province_id": province_id,
        "legacy_id": sources.legacy(province_id),
        "name": sources.name(province_id),
        "role": "india_full_test",
        "country_prefix": COUNTRY_PREFIX,
        "target_zone_count": count,
        "target_count_source": "world_province_cell_targets",
        "region_id": str(target_row.get("region_id", "")),
        "region_name": str(target_row.get("region_name", "")),
        "coastal": coastal,
        "gameplay_coast_rule_km": s.COAST_RULE_KM if coastal else 0.0,
        "gameplay_coast_source": coast_source,
        "source_area_km2": round(s.area_km2(parent), 4),
        "gameplay_area_km2": round(s.area_km2(land), 4),
        "capital_anchor": {
            "name": anchor_name,
            "point": [round(float(anchor.x), 6), round(float(anchor.y), 6)],
            "source": anchor_source,
        },
        "generation": {
            "method": "stage6_universal_with_world_target_count",
            "component_count": len(parts),
            "processed_component_count": len(allocations),
            "attached_satellite_component_count": satellite_count,
            "parts": generation_parts,
        },
        "validation": validation,
        "zones": zone_records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build India Stage-6 cell test")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--strict", action="store_true", help="exit non-zero if any Indian Admin-1 fails")
    args = parser.parse_args()

    # 18 zones need more substrate than the old <=12-zone stress test.
    s.MAX_ATOMS = max(s.MAX_ATOMS, 960)

    target_path, rows = targets()
    rows = sorted(rows, key=lambda row: int(str(row["province_id"]).split(":")[-1]))
    if args.limit is not None:
        rows = rows[:args.limit]

    sources = s.Sources()
    provinces: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        pid = str(row["province_id"])
        count = int(row["target_cell_count"])
        print(f"[{index}/{len(rows)}] INDIA Stage6 {pid} {row.get('name')} cells={count}", flush=True)
        try:
            record = build_province(sources, pid, count, row)
            provinces.append(record)
            print(f"  OK zones={count} status={record['validation']['status']}", flush=True)
        except Exception as error:
            failures.append({
                "province_id": pid,
                "name": row.get("name", pid),
                "target_cell_count": count,
                "error": f"{type(error).__name__}: {error}",
            })
            print(f"  FAIL {type(error).__name__}: {error}", flush=True)

    status_counts = Counter(p["validation"]["status"] for p in provinces)
    zone_count = sum(len(p["zones"]) for p in provinces)
    payload = {
        "format": "india_stage6_test/v1",
        "world_px": s.WORLD_PX,
        "source_targets": str(target_path.relative_to(ROOT)).replace("\\", "/"),
        "province_count": len(provinces),
        "zone_count": zone_count,
        "provinces": provinces,
    }
    report = {
        "format": "india_stage6_test_report/v1",
        "requested_admin1_count": len(rows),
        "built_admin1_count": len(provinces),
        "failed_admin1_count": len(failures),
        "zone_count": zone_count,
        "status_counts": dict(sorted(status_counts.items())),
        "failures": failures,
        "target_count_distribution": dict(sorted(Counter(int(r["target_cell_count"]) for r in rows).items())),
        "hard_fail": bool(failures),
    }
    write_json(OUT_PATH, payload)
    write_json(REPORT_PATH, report)
    print("INDIA_STAGE6_ADMIN1=", len(provinces))
    print("INDIA_STAGE6_CELLS=", zone_count)
    print("INDIA_STAGE6_FAILURES=", len(failures))

    if args.strict and failures:
        raise SystemExit("India Stage-6 has failures; see reports/india_stage6_test.json")


if __name__ == "__main__":
    main()
