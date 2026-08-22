#!/usr/bin/env python3
"""Diagnose whether current 4027 province records are logical Admin-1 units or pieces.

The current renderer format intentionally stores one Polygon per record. This
script groups records conservatively by (country_prefix, exact display name)
and also inspects generated legacy-id suffixes. It does NOT merge geometry or
change any game data. Its purpose is to quantify how much of the current
world-cell target table is piece-level rather than logical-Admin-1-level.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGETS = ROOT / "assets/game_data/world_province_cell_targets.json"
IDENTITY_AUDIT = ROOT / "reports/world_province_identity_geometry_audit.json"
OUT_JSON = ROOT / "reports/world_logical_admin1_groups.json"
OUT_MD = ROOT / "reports/world_logical_admin1_groups.md"
EXPECTED = 4027

# These suffixes are emitted by build_provinces.py for extra Polygon pieces and
# by _remove_overlaps() when a polygon difference splits into several pieces.
PIECE_SUFFIX_RE = re.compile(r"(?:_ov\d+|_\d+)$")


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def generated_base_id(legacy_id: str) -> str:
    value = legacy_id
    # _ovN can be appended after an already suffixed piece; peel repeatedly.
    while True:
        new = PIECE_SUFFIX_RE.sub("", value)
        if new == value:
            return value
        value = new


def group_key(rec: dict[str, Any]) -> tuple[str, str]:
    return str(rec.get("country_prefix", "")), str(rec.get("name", ""))


def member_view(rec: dict[str, Any], geod_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pid = str(rec.get("province_id", ""))
    geod = geod_by_id.get(pid, {})
    return {
        "province_id": pid,
        "legacy_id": str(rec.get("legacy_id", "")),
        "generated_base_id_guess": generated_base_id(str(rec.get("legacy_id", ""))),
        "area_km2": float(rec.get("area_km2", 0.0)),
        "geodesic_area_km2": float(geod.get("geodesic_area_km2", 0.0)),
        "target_cell_count": int(rec.get("target_cell_count", 0)),
        "region_name": str(rec.get("region_name", "")),
        "profile_id": str(rec.get("profile_id", "")),
        "region_target_cell_area_km2": float(rec.get("region_target_cell_area_km2", 0.0)),
        "region_min_cells": int(rec.get("region_min_cells", 0)),
        "region_max_cells": int(rec.get("region_max_cells", 0)),
    }


def summarize_group(country: str, name: str, members: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [str(m.get("legacy_id", "")) for m in members]
    guessed = [generated_base_id(x) for x in ids]
    profiles = sorted({str(m.get("profile_id", "")) for m in members})
    regions = sorted({str(m.get("region_name", "")) for m in members})
    areas = [float(m.get("area_km2", 0.0)) for m in members]
    cells = [int(m.get("target_cell_count", 0)) for m in members]
    same_generated_base = len(set(guessed)) == 1
    suffix_evidence = any(a != b for a, b in zip(ids, guessed))
    largest_area = max(areas) if areas else 0.0
    smallest_area = min(areas) if areas else 0.0
    return {
        "country_prefix": country,
        "name": name,
        "member_count": len(members),
        "members": members,
        "combined_area_km2": round(sum(areas), 6),
        "combined_target_cells_piece_level": sum(cells),
        "largest_piece_area_km2": round(largest_area, 6),
        "smallest_piece_area_km2": round(smallest_area, 6),
        "largest_to_smallest_area_ratio": round(largest_area / smallest_area, 3) if smallest_area > 0 else None,
        "region_names": regions,
        "profile_ids": profiles,
        "same_generated_base_id_guess": same_generated_base,
        "generated_suffix_evidence": suffix_evidence,
        "diagnostic_class": (
            "confirmed_piece_family" if same_generated_base and suffix_evidence
            else "same_name_multi_record_review"
        ),
    }


def render_md(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "# Аудит логических Admin-1 и Polygon-фрагментов",
        "",
        "> Только диагностика. Ничего не объединяется и не меняется.",
        "",
        "## Итог",
        "",
        f"- Текущих записей геометрии/targets: **{s['source_record_count']}**.",
        f"- Уникальных групп `(страна + точное имя)`: **{s['exact_country_name_group_count']}**.",
        f"- Одиночных групп: **{s['singleton_group_count']}**.",
        f"- Многозаписных групп: **{s['multi_record_group_count']}**.",
        f"- Записей внутри многозаписных групп: **{s['records_inside_multi_record_groups']}**.",
        f"- Групп с явным `_2/_3/_ovN` признаком общего generated base id: **{s['confirmed_piece_family_count']}**.",
        f"- Записей в таких подтверждённых семействах: **{s['records_inside_confirmed_piece_families']}**.",
        f"- Максимум Polygon-записей на одно имя: **{s['max_members_in_one_group']}**.",
        f"- Текущих target cells, назначенных по отдельным кускам в подтверждённых семействах: **{s['piece_level_target_cells_in_confirmed_families']}**.",
        "",
        "## Вывод",
        "",
        "Таблица из 4027 записей не должна автоматически считаться таблицей 4027 логических Admin-1. "
        "Формат карты хранит отдельные Polygon-куски как отдельные записи; для cell-targets нужен отдельный parent Admin-1 identity.",
        "",
        "## Именные случаи",
        "",
    ]
    for case in report.get("named_cases", []):
        lines += [
            f"### {case['country_prefix']} / {case['name']}",
            "",
            f"- Records: **{case['member_count']}**, combined area: **{case['combined_area_km2']:.1f} km²**, "
            f"piece-level targets sum: **{case['combined_target_cells_piece_level']}**.",
            f"- Class: `{case['diagnostic_class']}`; same generated base: `{case['same_generated_base_id_guess']}`.",
            "",
            "| province_id | legacy_id | km² | target cells | region |",
            "|---|---|---:|---:|---|",
        ]
        for m in case["members"]:
            lines.append(f"| {m['province_id']} | {m['legacy_id']} | {m['area_km2']:.1f} | {m['target_cell_count']} | {m['region_name']} |")
        lines.append("")

    lines += [
        "## Самые фрагментированные группы",
        "",
        "| Country | Name | Records | Combined km² | Piece-level targets | Class |",
        "|---|---|---:|---:|---:|---|",
    ]
    for g in report.get("top_fragmented_groups", []):
        lines.append(
            f"| {g['country_prefix']} | {g['name']} | {g['member_count']} | {g['combined_area_km2']:.1f} | "
            f"{g['combined_target_cells_piece_level']} | {g['diagnostic_class']} |"
        )
    lines += [
        "",
        "## Архитектурный контракт для исправления",
        "",
        "1. `admin1_id` — логическая административная единица, единственная сущность для target-cell count, региона и будущего деления.",
        "2. `piece_id` — отдельный Polygon только для геометрии/рендера; несколько `piece_id` могут ссылаться на один `admin1_id`.",
        "3. Нельзя сливать реальные Admin-1 только потому, что они маленькие по площади или меньше соседей.",
        "4. Исключения смешанного уровня (например Greater London) должны быть явными и воспроизводимыми, а не эвристикой по площади.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    doc = load(TARGETS)
    records = list(doc.get("provinces", []))
    if len(records) != EXPECTED:
        raise SystemExit(f"expected {EXPECTED} targets, got {len(records)}")

    geod_by_id: dict[str, dict[str, Any]] = {}
    if IDENTITY_AUDIT.exists():
        ia = load(IDENTITY_AUDIT)
        for section in ("named_diagnostics", "strong_country_area_outliers", "split_candidates_requiring_review"):
            for x in ia.get(section, []):
                geod_by_id[str(x.get("province_id", ""))] = x

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        grouped[group_key(rec)].append(member_view(rec, geod_by_id))

    groups = [summarize_group(country, name, members) for (country, name), members in grouped.items()]
    multi = [g for g in groups if g["member_count"] > 1]
    confirmed = [g for g in multi if g["diagnostic_class"] == "confirmed_piece_family"]
    review = [g for g in multi if g["diagnostic_class"] == "same_name_multi_record_review"]

    by_name = {(g["country_prefix"], g["name"]): g for g in groups}
    wanted = [
        ("switzerland", "Appenzell Innerrhoden"),
        ("latvia", "Jekabpils"),
        ("united_kingdom", "Northumberland"),
        ("canada", "Labrador"),
        ("solomon_islands", "Rennell and Bellona"),
    ]
    named_cases = [by_name[k] for k in wanted if k in by_name]

    size_dist = Counter(g["member_count"] for g in multi)
    top_fragmented = sorted(multi, key=lambda g: (-g["member_count"], -g["combined_area_km2"], g["country_prefix"], g["name"]))[:100]

    report = {
        "schema_version": 1,
        "format": "world_logical_admin1_groups/v1",
        "source": str(TARGETS.relative_to(ROOT)).replace("\\", "/"),
        "summary": {
            "source_record_count": len(records),
            "exact_country_name_group_count": len(groups),
            "singleton_group_count": sum(1 for g in groups if g["member_count"] == 1),
            "multi_record_group_count": len(multi),
            "records_inside_multi_record_groups": sum(g["member_count"] for g in multi),
            "confirmed_piece_family_count": len(confirmed),
            "records_inside_confirmed_piece_families": sum(g["member_count"] for g in confirmed),
            "same_name_multi_record_review_count": len(review),
            "max_members_in_one_group": max((g["member_count"] for g in groups), default=0),
            "piece_level_target_cells_in_confirmed_families": sum(g["combined_target_cells_piece_level"] for g in confirmed),
            "logical_parent_layer_required_before_world_generation": len(confirmed) > 0,
        },
        "multi_record_group_size_distribution": {str(k): v for k, v in sorted(size_dist.items())},
        "named_cases": named_cases,
        "top_fragmented_groups": top_fragmented,
        "confirmed_piece_families": sorted(confirmed, key=lambda g: (g["country_prefix"], g["name"])),
        "same_name_multi_record_review": sorted(review, key=lambda g: (g["country_prefix"], g["name"])),
        "architecture_decision": {
            "admin1_id": "logical administrative parent; owns target count, region assignment and future gameplay province split",
            "piece_id": "render/topology polygon piece; many pieces may reference one admin1_id",
            "heuristic_area_neighbor_merging_for_real_admin1": "forbidden",
            "explicit_mixed_level_merges": "allowed only as named reproducible exceptions",
        },
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_MD.write_text(render_md(report), encoding="utf-8")
    print("WORLD_LOGICAL_ADMIN1_GROUPS", json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
