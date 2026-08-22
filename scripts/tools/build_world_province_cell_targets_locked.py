#!/usr/bin/env python3
"""Locked runner for the world province cell-count prepass.

Adds the assignment confidence semantics from world_region_assignments_draft/v1
without duplicating the main calculator. In that format review status is stored
as confidence == "review" (not a boolean `review` field).
"""
from __future__ import annotations

import argparse

import build_world_province_cell_targets as core


def build_documents():
    profiles, targets, report = core.build_documents()
    assignment_doc = core.read_json(core.ASSIGNMENTS_PATH)
    confidence_by_id = {
        str(a.get("province_id", "")): str(a.get("confidence", ""))
        for a in assignment_doc.get("assignments", [])
    }

    by_id = {}
    for item in targets.get("provinces", []):
        pid = str(item.get("province_id", ""))
        confidence = confidence_by_id.get(pid, "")
        item["region_assignment_confidence"] = confidence
        item["region_assignment_review"] = confidence == "review"
        by_id[pid] = item

    report["region_assignment_review_count"] = sum(
        1 for item in targets.get("provinces", []) if item.get("region_assignment_review")
    )
    for sample in report.get("control_samples", []):
        full = by_id.get(str(sample.get("province_id", "")))
        if full is not None:
            sample["region_assignment_review"] = bool(full.get("region_assignment_review", False))
            sample["region_assignment_confidence"] = str(full.get("region_assignment_confidence", ""))

    return profiles, targets, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    profiles, targets, report = build_documents()
    core.check_or_write(core.PROFILE_JSON_PATH, profiles, args.check)
    core.check_or_write(core.TARGETS_PATH, targets, args.check)
    core.check_or_write(core.REPORT_PATH, report, args.check)
    print("WORLD_CELL_TARGETS_PROVINCES=", report["province_count"])
    print("WORLD_CELL_TARGETS_TOTAL_CELLS=", report["total_target_cells"])
    print("WORLD_CELL_TARGETS_REVIEW=", report["region_assignment_review_count"])
    print("WORLD_CELL_TARGETS_FALLBACK_PROVINCES=", report["special_fallback_province_count"])
    print("WORLD_CELL_TARGETS_FALLBACK_REGIONS=", report["special_fallback_regions"])
    print("WORLD_CELL_TARGETS_PROFILE_COUNTS=", report["province_count_by_profile"])
    for item in report["control_samples"]:
        print("CONTROL", item["name"], "region=", item["region_name"], "profile=", item["profile_id"], "count=", item["target_cell_count"], "confidence=", item.get("region_assignment_confidence", ""))


if __name__ == "__main__":
    main()
