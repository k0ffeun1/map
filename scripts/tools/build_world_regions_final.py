#!/usr/bin/env python3
"""Build final world-region geometry after automatic cleanup + manual overrides.

Besides dissolving whole layer-8 provinces, this final *display geometry* pass
removes only topology-artifact holes: tiny holes and very thin sliver holes
created by imperfect source seams. Assignment geometry itself is untouched.
Large/compact holes are preserved so real lakes/enclaves are not silently
filled.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from shapely.geometry import Polygon

import build_world_regions_island_corrected as core

ROOT = Path(__file__).resolve().parents[2]
ASSIGNMENTS = ROOT / "assets" / "game_data" / "world_region_assignments_final.json"
OUT = ROOT / "assets" / "regions_world_final.json"
REPORT = ROOT / "reports" / "world_regions_final.json"

WORLD_PX = 8192.0
EARTH_RADIUS_KM = 6371.0088
TINY_HOLE_KM2 = 80.0
SLIVER_HOLE_MAX_KM2 = 700.0
SLIVER_COMPACTNESS_MAX = 0.018


def km_per_world_px(y: float) -> float:
    n = math.pi - 2.0 * math.pi * y / WORLD_PX
    lat = math.degrees(math.atan(math.sinh(n)))
    return 2.0 * math.pi * EARTH_RADIUS_KM / WORLD_PX * math.cos(math.radians(lat))


def hole_metrics(ring: list[list[float]]) -> tuple[float, float]:
    try:
        p = Polygon(ring)
    except Exception:
        return 0.0, 0.0
    if p.is_empty or p.area <= 0.0:
        return 0.0, 0.0
    y = float(p.representative_point().y)
    s = km_per_world_px(y)
    area_km2 = float(p.area) * s * s
    perimeter = float(p.length)
    compactness = (4.0 * math.pi * float(p.area) / (perimeter * perimeter)) if perimeter > 1.0e-9 else 0.0
    return area_km2, compactness


def cleanup_display_holes(data: dict) -> dict:
    removed = []
    kept = 0
    for cell in data.get("cells", []):
        rings = cell.get("rings", [])
        if len(rings) <= 1:
            continue
        new_rings = [rings[0]]
        for hole_index, ring in enumerate(rings[1:], start=1):
            area_km2, compactness = hole_metrics(ring)
            is_tiny = area_km2 <= TINY_HOLE_KM2
            is_sliver = area_km2 <= SLIVER_HOLE_MAX_KM2 and compactness <= SLIVER_COMPACTNESS_MAX
            if is_tiny or is_sliver:
                removed.append({
                    "region_id": cell.get("region_id", ""),
                    "region_name": cell.get("name", ""),
                    "part_id": cell.get("id", ""),
                    "hole_index": hole_index,
                    "area_km2": round(area_km2, 3),
                    "compactness": round(compactness, 6),
                    "reason": "tiny_hole" if is_tiny else "thin_sliver_hole",
                })
            else:
                new_rings.append(ring)
                kept += 1
        cell["rings"] = new_rings
    return {
        "removed_hole_count": len(removed),
        "kept_hole_count": kept,
        "thresholds": {
            "tiny_hole_km2": TINY_HOLE_KM2,
            "sliver_hole_max_km2": SLIVER_HOLE_MAX_KM2,
            "sliver_compactness_max": SLIVER_COMPACTNESS_MAX,
        },
        "removed_holes": removed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    core.ASSIGNMENTS_PATH = ASSIGNMENTS
    data, report = core.build()
    data["format"] = "world_regions_final/v1"
    data["source_assignments"] = str(ASSIGNMENTS)
    data["method"] = "dissolve_whole_layer8_provinces_after_auto_cleanup_and_manual_overrides_plus_display_hole_cleanup"
    report["format"] = "world_regions_final_report/v1"

    hole_cleanup = cleanup_display_holes(data)
    data["display_hole_cleanup"] = hole_cleanup["thresholds"]
    report["display_hole_cleanup"] = hole_cleanup

    outputs = ((OUT, data, True), (REPORT, report, False))
    for path, value, compact in outputs:
        payload = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) if compact else json.dumps(value, ensure_ascii=False, indent=2)) + "\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != payload:
                raise RuntimeError(f"--check mismatch: {path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")

    print(
        "WORLD_REGIONS_FINAL_OK",
        f"provinces={report['province_count']}",
        f"regions={report['region_count']}",
        f"parts={report['polygon_piece_count']}",
        f"holes_removed={hole_cleanup['removed_hole_count']}",
        f"holes_kept={hole_cleanup['kept_hole_count']}",
    )


if __name__ == "__main__":
    main()
