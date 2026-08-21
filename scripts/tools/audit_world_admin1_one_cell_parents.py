#!/usr/bin/env python3
"""Audit playable clean Admin-1 parents that currently receive exactly one gameplay cell.

This is diagnostic only. It does not modify geometry, region assignments or cell
budgets. The goal is to explain what the large one-cell population actually is:
ordinary Admin-1, fine/mixed-level Natural Earth features, islands/municipalities,
and potentially over-large parents that deserve a cell-target review.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGETS = ROOT / "assets/game_data/world_admin1_safe_cell_targets.json"
MANIFEST = ROOT / "assets/game_data/world_admin1_source_manifest.json"
POLICY = ROOT / "assets/game_data/world_admin1_level_policy.json"
OUT_JSON = ROOT / "reports/world_admin1_one_cell_audit.json"
OUT_MD = ROOT / "reports/world_admin1_one_cell_audit.md"

EXPECTED_ONE_CELL = 2549

AREA_BANDS = [
    (100.0, "<100 km²"),
    (500.0, "100–500 km²"),
    (1000.0, "500–1,000 km²"),
    (5000.0, "1,000–5,000 km²"),
    (10000.0, "5,000–10,000 km²"),
    (20000.0, "10,000–20,000 km²"),
    (40000.0, "20,000–40,000 km²"),
    (80000.0, "40,000–80,000 km²"),
    (float("inf"), ">=80,000 km²"),
]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def area_band(area: float) -> str:
    low = 0.0
    for upper, label in AREA_BANDS:
        if area < upper:
            return label
        low = upper
    return ">=80,000 km²"


def representative_type(types: list[str]) -> str:
    clean = [x for x in types if x]
    if not clean:
        return "<empty>"
    counts = Counter(clean)
    return counts.most_common(1)[0][0]


def main() -> None:
    targets_doc = read_json(TARGETS)
    manifest = read_json(MANIFEST)
    policy = read_json(POLICY)

    one = [x for x in targets_doc.get("provinces", []) if int(x.get("target_cell_count", 0)) == 1]
    if len(one) != EXPECTED_ONE_CELL:
        raise RuntimeError(f"expected {EXPECTED_ONE_CELL} one-cell parents, got {len(one)}")

    fine_labels = set(str(x) for x in policy.get("fine_type_review_labels", []))
    features_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in manifest.get("source_features", []):
        logical_id = str(f.get("logical_admin1_id", ""))
        if logical_id:
            features_by_parent[logical_id].append(f)

    records: list[dict[str, Any]] = []
    type_counts: Counter[str] = Counter()
    country_counts: Counter[str] = Counter()
    area_counts: Counter[str] = Counter()
    fine_type_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    very_large = []
    large = []

    for t in one:
        logical_id = str(t.get("logical_admin1_id", ""))
        members = features_by_parent.get(logical_id, [])
        source_types = sorted({str(m.get("type_en", "")) for m in members if str(m.get("type_en", ""))})
        source_names = sorted({str(m.get("name", "")) for m in members if str(m.get("name", ""))})
        fine = bool(t.get("fine_type_review", False)) or any(
            str(m.get("type_en", "")) in fine_labels or bool(m.get("fine_type_review", False)) for m in members
        )
        typ = representative_type(source_types)
        area = float(t.get("area_km2", 0.0))
        raw = float(t.get("raw_area_count", 0.0))
        area_count = int(t.get("area_count", 0))
        minimum = int(t.get("region_min_cells", 1))
        anchor_min = int(t.get("anchor_min", 1))

        if raw < 1.5:
            reason = "area_formula_rounds_to_1_or_less"
        elif area_count <= 1:
            reason = "rounded_area_count_1"
        elif int(t.get("target_cell_count", 0)) == 1 and int(t.get("region_max_cells", 1)) == 1:
            reason = "regional_profile_caps_at_1"
        else:
            reason = "other_or_override"

        item = {
            "logical_admin1_id": logical_id,
            "admin": str(t.get("admin", "")),
            "name": str(t.get("name", logical_id)),
            "area_km2": round(area, 3),
            "region_id": str(t.get("region_id", "")),
            "region_name": str(t.get("region_name", "")),
            "profile_id": str(t.get("profile_id", "")),
            "region_target_cell_area_km2": float(t.get("region_target_cell_area_km2", 0.0)),
            "raw_area_count": round(raw, 6),
            "area_count": area_count,
            "region_min_cells": minimum,
            "region_max_cells": int(t.get("region_max_cells", 0)),
            "anchor_min": anchor_min,
            "fine_type_review": fine,
            "source_types": source_types,
            "source_names": source_names,
            "source_feature_count": len(members),
            "piece_count": int(t.get("piece_count", 0)),
            "area_band": area_band(area),
            "one_cell_reason": reason,
            "region_assignment_review": bool(t.get("region_assignment_review", False)),
        }
        records.append(item)
        type_counts[typ] += 1
        country_counts[item["admin"] or "<empty>"] += 1
        area_counts[item["area_band"]] += 1
        fine_type_counts["fine/mixed-level review"] += int(fine)
        fine_type_counts["ordinary/non-fine"] += int(not fine)
        reason_counts[reason] += 1
        if area >= 40000.0:
            very_large.append(item)
        elif area >= 20000.0:
            large.append(item)

    smallest = sorted(records, key=lambda x: (x["area_km2"], x["admin"], x["name"]))[:60]
    largest = sorted(records, key=lambda x: (-x["area_km2"], x["admin"], x["name"]))[:100]
    fine_examples = sorted([x for x in records if x["fine_type_review"]], key=lambda x: (x["area_km2"], x["admin"], x["name"]))[:100]
    ordinary_examples = sorted([x for x in records if not x["fine_type_review"]], key=lambda x: (-x["area_km2"], x["admin"], x["name"]))[:100]

    area_band_order = [label for _, label in AREA_BANDS]
    summary = {
        "one_cell_parent_count": len(records),
        "fine_type_review_count": sum(1 for x in records if x["fine_type_review"]),
        "ordinary_non_fine_count": sum(1 for x in records if not x["fine_type_review"]),
        "area_under_1000_count": sum(1 for x in records if x["area_km2"] < 1000.0),
        "area_under_5000_count": sum(1 for x in records if x["area_km2"] < 5000.0),
        "area_under_10000_count": sum(1 for x in records if x["area_km2"] < 10000.0),
        "area_20000_plus_count": sum(1 for x in records if x["area_km2"] >= 20000.0),
        "area_40000_plus_count": sum(1 for x in records if x["area_km2"] >= 40000.0),
        "area_80000_plus_count": sum(1 for x in records if x["area_km2"] >= 80000.0),
        "region_assignment_review_count": sum(1 for x in records if x["region_assignment_review"]),
    }

    report = {
        "schema_version": 1,
        "format": "world_admin1_one_cell_audit/v1",
        "summary": summary,
        "area_band_counts": {label: area_counts[label] for label in area_band_order},
        "top_source_types": [{"type_en": k, "count": v} for k, v in type_counts.most_common(40)],
        "top_countries": [{"admin": k, "count": v} for k, v in country_counts.most_common(50)],
        "one_cell_reason_counts": dict(sorted(reason_counts.items())),
        "largest_one_cell_parents": largest,
        "smallest_one_cell_parents": smallest,
        "fine_type_examples": fine_examples,
        "ordinary_large_examples": ordinary_examples,
        "large_20k_to_40k": sorted(large, key=lambda x: (-x["area_km2"], x["name"])),
        "very_large_40k_plus": sorted(very_large, key=lambda x: (-x["area_km2"], x["name"])),
    }
    write_json(OUT_JSON, report)

    lines = [
        "# Audit: playable Admin-1 with exactly one gameplay cell",
        "",
        "Diagnostic only; no geometry, regions or target counts are changed.",
        "",
        "## Summary",
        "",
        f"- One-cell parents: **{summary['one_cell_parent_count']}**.",
        f"- Ordinary/non-fine Admin-1: **{summary['ordinary_non_fine_count']}**.",
        f"- Fine/mixed-level review parents: **{summary['fine_type_review_count']}**.",
        f"- Area <1,000 km²: **{summary['area_under_1000_count']}**.",
        f"- Area <5,000 km²: **{summary['area_under_5000_count']}**.",
        f"- Area <10,000 km²: **{summary['area_under_10000_count']}**.",
        f"- Area >=20,000 km²: **{summary['area_20000_plus_count']}**.",
        f"- Area >=40,000 km²: **{summary['area_40000_plus_count']}**.",
        f"- Area >=80,000 km²: **{summary['area_80000_plus_count']}**.",
        f"- Region-assignment review among one-cell parents: **{summary['region_assignment_review_count']}**.",
        "",
        "## Area distribution",
        "",
        "| Area | Parents |",
        "|---|---:|",
    ]
    for label in area_band_order:
        lines.append(f"| {label} | {area_counts[label]} |")
    lines += ["", "## Most common Natural Earth source types", "", "| type_en | Parents |", "|---|---:|"]
    for k, v in type_counts.most_common(25):
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Countries with most one-cell parents", "", "| Country/admin | Parents |", "|---|---:|"]
    for k, v in country_counts.most_common(25):
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "## Largest one-cell parents — first 50",
        "",
        "| Admin | Name | km² | type | Region | raw count | profile target km² | fine review |",
        "|---|---|---:|---|---|---:|---:|---|",
    ]
    for x in largest[:50]:
        typ = ", ".join(x["source_types"]) or "<empty>"
        lines.append(
            f"| {x['admin']} | {x['name']} | {x['area_km2']:.1f} | {typ} | {x['region_name']} | "
            f"{x['raw_area_count']:.3f} | {x['region_target_cell_area_km2']:.0f} | {x['fine_type_review']} |"
        )
    lines += [
        "",
        "## Small/fine examples — first 50",
        "",
        "| Admin | Name | km² | type | Region |",
        "|---|---|---:|---|---|",
    ]
    for x in fine_examples[:50]:
        typ = ", ".join(x["source_types"]) or "<empty>"
        lines.append(f"| {x['admin']} | {x['name']} | {x['area_km2']:.1f} | {typ} | {x['region_name']} |")
    lines += [
        "",
        "## Interpretation",
        "",
        "A one-cell result is not automatically an error. It means the regional profile plus the clean parent area currently rounds/clamps to one cell. "
        "The important review groups are (a) fine/mixed-level source features that may need an explicit level policy and (b) unusually large ordinary Admin-1 that still receive one cell.",
        "",
    ]
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print("ONE_CELL_AUDIT_OK", summary)


if __name__ == "__main__":
    main()
