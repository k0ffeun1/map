#!/usr/bin/env python3
"""Build playable clean Admin-1 parents, then migrate regions and cell targets.

The clean source layer intentionally preserves all 4564 logical source parents.
Three of them have no render geometry after the project's world crop (two
Antarctica records and Pituffik). They remain in lineage but are not gameplay
provinces and must not receive historical regions or cell budgets.
"""
from __future__ import annotations

import json
from pathlib import Path

import build_world_admin1_safe_regions_and_targets as core

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "assets/game_data/world_admin1_logical_parents.json"
OUT = ROOT / "assets/game_data/world_admin1_playable_parents.json"
EXPECTED_SOURCE = 4564
EXPECTED_PLAYABLE = 4561
EXPECTED_EXCLUDED = 3


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    all_parents = list(source.get("parents", []))
    if len(all_parents) != EXPECTED_SOURCE:
        raise RuntimeError(f"source logical parent count mismatch: {len(all_parents)}")

    playable = [x for x in all_parents if int(x.get("piece_count", 0)) > 0]
    excluded = [x for x in all_parents if int(x.get("piece_count", 0)) <= 0]
    if len(playable) != EXPECTED_PLAYABLE or len(excluded) != EXPECTED_EXCLUDED:
        raise RuntimeError(f"world crop contract mismatch playable={len(playable)} excluded={len(excluded)}")

    playable_doc = {
        "schema_version": 1,
        "format": "world_admin1_playable_parents/v1",
        "source_logical_parent_layer": str(SOURCE.relative_to(ROOT)),
        "source_logical_parent_count": len(all_parents),
        "playable_parent_count": len(playable),
        "excluded_world_crop_parent_count": len(excluded),
        "exclusion_rule": "piece_count == 0 after project world crop",
        "excluded_world_crop_parents": [{
            "logical_admin1_id": x.get("logical_admin1_id", ""),
            "name": x.get("name", ""),
            "admin": x.get("admin", ""),
            "area_km2": x.get("source_geodesic_area_km2", 0.0),
            "piece_count": x.get("piece_count", 0),
        } for x in excluded],
        "parents": playable,
    }
    OUT.write_text(json.dumps(playable_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Reuse the migration engine against the explicit playable-parent contract.
    core.SAFE_PARENTS = OUT
    core.EXPECTED_PARENTS = EXPECTED_PLAYABLE
    core.main()

    # Add the source/playable distinction to the machine and human reports.
    report = json.loads(core.OUT_REPORT.read_text(encoding="utf-8"))
    report["world_crop"] = {
        "source_logical_parent_count": len(all_parents),
        "playable_parent_count": len(playable),
        "excluded_world_crop_parent_count": len(excluded),
        "excluded_world_crop_parents": playable_doc["excluded_world_crop_parents"],
    }
    core.OUT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with core.OUT_MD.open("a", encoding="utf-8") as fh:
        fh.write("\n## World-crop parent policy\n\n")
        fh.write(f"- Clean source logical parents: **{len(all_parents)}**.\n")
        fh.write(f"- Playable/rendered logical parents: **{len(playable)}**.\n")
        fh.write(f"- Excluded after project world crop: **{len(excluded)}**.\n")
        for x in playable_doc["excluded_world_crop_parents"]:
            fh.write(f"  - `{x['logical_admin1_id']}` — {x['admin']} / {x['name']} (piece_count=0).\n")

    print("WORLD_ADMIN1_PLAYABLE_PARENT_COUNT=", len(playable))
    print("WORLD_ADMIN1_WORLD_CROP_EXCLUDED=", [x["logical_admin1_id"] for x in playable_doc["excluded_world_crop_parents"]])


if __name__ == "__main__":
    main()
