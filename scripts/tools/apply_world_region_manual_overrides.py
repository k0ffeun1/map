#!/usr/bin/env python3
"""Apply persistent manual region-editor overrides after automatic cleanup."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "assets" / "game_data" / "world_region_assignments_cleaned.json"
OVERRIDES = ROOT / "assets" / "game_data" / "world_region_manual_overrides.json"
OUTPUT = ROOT / "assets" / "game_data" / "world_region_assignments_final.json"
REPORT = ROOT / "reports" / "world_region_manual_overrides.json"
EXPECTED = 4027


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def text(value: Any, compact: bool = False) -> str:
    if compact:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    source = read(INPUT)
    assignments = [dict(x) for x in source.get("assignments", [])]
    if len(assignments) != EXPECTED:
        raise RuntimeError(f"expected {EXPECTED} assignments, got {len(assignments)}")
    by_id = {str(x["province_id"]): x for x in assignments}

    overrides = read(OVERRIDES)
    if overrides.get("format") != "world_region_manual_overrides/v1":
        raise RuntimeError("bad manual override format")

    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for index, raw in enumerate(overrides.get("operations", [])):
        op = dict(raw)
        mode = str(op.get("mode", ""))
        target_id = str(op.get("target_region_id", ""))
        target_name = str(op.get("target_region_name", target_id))
        if not target_id:
            skipped.append({"index": index, "reason": "missing_target_region_id", "operation": op})
            continue

        affected: list[dict[str, str]] = []
        if mode == "move_province":
            pid = str(op.get("source_province_id", ""))
            item = by_id.get(pid)
            if item is None:
                skipped.append({"index": index, "reason": "province_not_found", "operation": op})
                continue
            if str(item.get("region_id", "")) == target_id:
                skipped.append({"index": index, "reason": "already_in_target", "operation": op})
                continue
            affected.append({"province_id": pid, "from_region_id": str(item.get("region_id", "")), "from_region_name": str(item.get("region_name", ""))})
            item["region_id"] = target_id
            item["region_name"] = target_name
            item["method"] = "manual_region_editor_move_province"
            item["confidence"] = "locked"
        elif mode == "merge_region":
            source_region = str(op.get("source_region_id", ""))
            if not source_region or source_region == target_id:
                skipped.append({"index": index, "reason": "bad_source_region", "operation": op})
                continue
            for item in assignments:
                if str(item.get("region_id", "")) != source_region:
                    continue
                affected.append({"province_id": str(item.get("province_id", "")), "from_region_id": source_region, "from_region_name": str(item.get("region_name", ""))})
                item["region_id"] = target_id
                item["region_name"] = target_name
                item["method"] = "manual_region_editor_merge_region"
                item["confidence"] = "locked"
            if not affected:
                skipped.append({"index": index, "reason": "source_region_empty", "operation": op})
                continue
        else:
            skipped.append({"index": index, "reason": "unknown_mode", "operation": op})
            continue

        applied.append({"index": index, "mode": mode, "target_region_id": target_id, "target_region_name": target_name, "affected_count": len(affected), "affected": affected})

    output = dict(source)
    output["format"] = "world_region_assignments_final/v1"
    output["source"] = str(INPUT)
    output["manual_override_source"] = str(OVERRIDES)
    output["province_count"] = len(assignments)
    output["assignments"] = assignments

    report = {
        "schema_version": 1,
        "format": "world_region_manual_overrides_report/v1",
        "province_count": len(assignments),
        "operation_count": len(overrides.get("operations", [])),
        "applied_operation_count": len(applied),
        "skipped_operation_count": len(skipped),
        "applied": applied,
        "skipped": skipped,
        "hard_fail": False,
    }

    for path, value, compact in ((OUTPUT, output, True), (REPORT, report, False)):
        payload = text(value, compact)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != payload:
                raise RuntimeError(f"--check mismatch: {path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")

    print("WORLD_REGION_MANUAL_OVERRIDES_OK", f"operations={report['operation_count']}", f"applied={len(applied)}", f"skipped={len(skipped)}")


if __name__ == "__main__":
    main()
