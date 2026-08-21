#!/usr/bin/env python3
"""Build final world-region dissolve from automatic cleanup + manual overrides."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import build_world_regions_island_corrected as core

ROOT = Path(__file__).resolve().parents[2]
ASSIGNMENTS = ROOT / "assets" / "game_data" / "world_region_assignments_final.json"
OUT = ROOT / "assets" / "regions_world_final.json"
REPORT = ROOT / "reports" / "world_regions_final.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    core.ASSIGNMENTS_PATH = ASSIGNMENTS
    data, report = core.build()
    data["format"] = "world_regions_final/v1"
    data["source_assignments"] = str(ASSIGNMENTS)
    data["method"] = "dissolve_whole_layer8_provinces_after_auto_cleanup_and_manual_overrides"
    report["format"] = "world_regions_final_report/v1"

    outputs = ((OUT, data, True), (REPORT, report, False))
    for path, value, compact in outputs:
        payload = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) if compact else json.dumps(value, ensure_ascii=False, indent=2)) + "\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != payload:
                raise RuntimeError(f"--check mismatch: {path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")

    print("WORLD_REGIONS_FINAL_OK", f"provinces={report['province_count']}", f"regions={report['region_count']}", f"parts={report['polygon_piece_count']}")


if __name__ == "__main__":
    main()
