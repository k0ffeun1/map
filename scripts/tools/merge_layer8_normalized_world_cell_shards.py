#!/usr/bin/env python3
"""Validate and aggregate sharded normalized Layer-8 land-cell generation."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGETS_PATH = ROOT / "assets" / "game_data" / "layer8_normalized_cell_targets.json"
GROUPS_PATH = ROOT / "assets" / "game_data" / "layer8_normalized_province_groups.json"
DEFAULT_REPORT = ROOT / "reports" / "layer8_normalized_world_cells_world_diagnostic.json"
DEFAULT_MANIFEST = ROOT / "assets" / "land_cells_normalized" / "world_manifest.json"

EXPECTED_PARENTS = 2886
EXPECTED_CELLS = 12902


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()

    targets_doc = read_json(TARGETS_PATH)
    groups_doc = read_json(GROUPS_PATH)
    target_by_parent = {
        str(item["gameplay_parent_id"]): int(item["target_cell_count"])
        for item in targets_doc.get("provinces", [])
    }
    if len(target_by_parent) != EXPECTED_PARENTS:
        raise RuntimeError(f"Expected {EXPECTED_PARENTS} targets, got {len(target_by_parent)}")
    if sum(target_by_parent.values()) != EXPECTED_CELLS:
        raise RuntimeError("Canonical target total changed unexpectedly")
    expected_parents = set(target_by_parent)

    shard_records: list[dict[str, Any]] = []
    built_parent_ids: set[str] = set()
    requested_parent_ids: set[str] = set()
    duplicate_parent_ids: set[str] = set()
    cell_ids: set[str] = set()
    duplicate_cell_ids: set[str] = set()
    failures: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    built_cells = 0
    requested_cells = 0
    multipart_cells = 0
    real_capital_anchors = 0
    technical_anchors = 0

    for shard_index in range(args.shard_count):
        stem = f"shard_{shard_index:03d}_of_{args.shard_count:03d}"
        data_path = args.input_dir / f"{stem}.json"
        report_path = args.input_dir / f"{stem}.report.json"
        if not data_path.exists() or not report_path.exists():
            failures.append({
                "type": "missing_shard_file",
                "shard_index": shard_index,
                "data_exists": data_path.exists(),
                "report_exists": report_path.exists(),
            })
            continue
        payload = read_json(data_path)
        report = read_json(report_path)
        if payload.get("format") != "layer8_normalized_land_cells/v1":
            failures.append({"type": "bad_shard_format", "shard_index": shard_index})
            continue

        shard_requested_parents: list[str] = []
        for province in payload.get("provinces", []):
            pid = str(province.get("gameplay_parent_id", ""))
            if not pid:
                failures.append({"type": "empty_parent_id", "shard_index": shard_index})
                continue
            shard_requested_parents.append(pid)
            if pid in built_parent_ids:
                duplicate_parent_ids.add(pid)
            built_parent_ids.add(pid)
            status_counts[str(province.get("validation", {}).get("status", ""))] += 1
            source = str(province.get("capital_anchor", {}).get("source", ""))
            if source == "real_province_capital":
                real_capital_anchors += 1
            else:
                technical_anchors += 1
            for cell in province.get("cells", []):
                cid = str(cell.get("id", ""))
                if cid in cell_ids:
                    duplicate_cell_ids.add(cid)
                cell_ids.add(cid)
                multipart_cells += int(bool(cell.get("multipart", False)))

        # The generator report knows requested parents including failed ones only
        # as a count, so recover failures explicitly and combine them with built IDs.
        shard_failures = [dict(item) for item in report.get("failures", [])]
        failure_parent_ids = {str(item.get("gameplay_parent_id", "")) for item in shard_failures if item.get("gameplay_parent_id")}
        shard_all_requested = set(shard_requested_parents) | failure_parent_ids
        for pid in shard_all_requested:
            if pid in requested_parent_ids:
                duplicate_parent_ids.add(pid)
            requested_parent_ids.add(pid)

        failures.extend({"shard_index": shard_index, **item} for item in shard_failures)
        built_cells += int(report.get("built_cell_count", 0))
        requested_cells += int(report.get("requested_cell_count", 0))

        shard_records.append({
            "shard_index": shard_index,
            "file": f"shards/{stem}.json",
            "requested_province_count": int(report.get("requested_province_count", 0)),
            "built_province_count": int(report.get("built_province_count", 0)),
            "failed_province_count": int(report.get("failed_province_count", 0)),
            "requested_cell_count": int(report.get("requested_cell_count", 0)),
            "built_cell_count": int(report.get("built_cell_count", 0)),
            "multipart_cell_count": int(report.get("multipart_cell_count", 0)),
            "status_counts": dict(report.get("status_counts", {})),
        })

    missing_requested_parents = sorted(expected_parents - requested_parent_ids)
    unexpected_requested_parents = sorted(requested_parent_ids - expected_parents)
    missing_built_parents = sorted(expected_parents - built_parent_ids)
    unexpected_built_parents = sorted(built_parent_ids - expected_parents)

    successful = (
        len(shard_records) == args.shard_count
        and not failures
        and not duplicate_parent_ids
        and not duplicate_cell_ids
        and not missing_requested_parents
        and not unexpected_requested_parents
        and not missing_built_parents
        and not unexpected_built_parents
        and len(built_parent_ids) == EXPECTED_PARENTS
        and built_cells == EXPECTED_CELLS
        and requested_cells == EXPECTED_CELLS
        and len(cell_ids) == EXPECTED_CELLS
    )

    summary = {
        "expected_shard_count": args.shard_count,
        "found_shard_count": len(shard_records),
        "expected_parent_count": EXPECTED_PARENTS,
        "requested_parent_count": len(requested_parent_ids),
        "built_parent_count": len(built_parent_ids),
        "expected_cell_count": EXPECTED_CELLS,
        "requested_cell_count": requested_cells,
        "built_cell_count": built_cells,
        "unique_cell_id_count": len(cell_ids),
        "failed_parent_count": len([x for x in failures if x.get("gameplay_parent_id")]),
        "diagnostic_issue_count": len(failures),
        "duplicate_parent_count": len(duplicate_parent_ids),
        "duplicate_cell_count": len(duplicate_cell_ids),
        "missing_requested_parent_count": len(missing_requested_parents),
        "missing_built_parent_count": len(missing_built_parents),
        "multipart_cell_count": multipart_cells,
        "real_capital_anchor_count": real_capital_anchors,
        "technical_anchor_count": technical_anchors,
        "validation_status_counts": dict(sorted(status_counts.items())),
        "complete_and_valid": successful,
    }

    diagnostic = {
        "schema_version": 1,
        "format": "layer8_normalized_world_cells_diagnostic/v1",
        "content_version": "2026.08.22",
        "summary": summary,
        "failures": failures,
        "duplicate_parent_ids": sorted(duplicate_parent_ids),
        "duplicate_cell_ids": sorted(duplicate_cell_ids),
        "missing_requested_parent_ids": missing_requested_parents,
        "missing_built_parent_ids": missing_built_parents,
        "unexpected_requested_parent_ids": unexpected_requested_parents,
        "unexpected_built_parent_ids": unexpected_built_parents,
        "shards": shard_records,
    }
    write_json(args.report, diagnostic)

    manifest = {
        "schema_version": 1,
        "format": "layer8_normalized_land_cells_manifest/v1",
        "content_version": "2026.08.22",
        "source_groups": str(GROUPS_PATH.relative_to(ROOT)),
        "source_targets": str(TARGETS_PATH.relative_to(ROOT)),
        "province_count": len(built_parent_ids),
        "cell_count": len(cell_ids),
        "expected_province_count": EXPECTED_PARENTS,
        "expected_cell_count": EXPECTED_CELLS,
        "complete_and_valid": successful,
        "status_counts": dict(sorted(status_counts.items())),
        "multipart_cell_count": multipart_cells,
        "shards": shard_records,
    }
    write_json(args.manifest, manifest)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.require_complete and not successful:
        raise SystemExit("World normalized cell generation is incomplete or invalid; inspect diagnostic report")


if __name__ == "__main__":
    main()
