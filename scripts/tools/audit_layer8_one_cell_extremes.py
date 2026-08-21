#!/usr/bin/env python3
"""Audit one-cell Layer-8 gameplay provinces by area.

Diagnostic only. Reads the existing 4027-province Layer-8 target table and
produces a report of very small and very large provinces that currently receive
exactly one gameplay cell. No geometry, region assignment, or cell target is
modified.

This report intentionally uses Layer 8 rather than raw Safe Admin-1, so trusted
existing grouping choices such as Slovenia and Greater London are left intact.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGETS = ROOT / "assets/game_data/world_province_cell_targets.json"
OUT_JSON = ROOT / "reports/layer8_one_cell_extremes.json"
OUT_MD = ROOT / "reports/layer8_one_cell_extremes.md"

EXPECTED_PROVINCES = 4027

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


def band(area: float) -> str:
    for upper, label in AREA_BANDS:
        if area < upper:
            return label
    return ">=80,000 km²"


def main() -> None:
    doc = read_json(TARGETS)
    provinces = list(doc.get("provinces", []))
    if len(provinces) != EXPECTED_PROVINCES:
        raise RuntimeError(f"expected {EXPECTED_PROVINCES} Layer-8 provinces, got {len(provinces)}")

    # Same country + same displayed name is a safe diagnostic for render-piece
    # multiplicity without trying to reverse-engineer fragile _2/_ovN suffixes.
    same_name_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for p in provinces:
        key = (str(p.get("country_prefix", "")), str(p.get("name", "")).casefold())
        same_name_groups[key].append(p)

    one = [p for p in provinces if int(p.get("target_cell_count", 0)) == 1]
    records: list[dict[str, Any]] = []
    area_counts: Counter[str] = Counter()

    for p in one:
        area = float(p.get("area_km2", 0.0))
        key = (str(p.get("country_prefix", "")), str(p.get("name", "")).casefold())
        siblings = same_name_groups[key]
        repeated_name_piece = len(siblings) > 1
        sibling_area = sum(float(x.get("area_km2", 0.0)) for x in siblings)
        sibling_cells = sum(int(x.get("target_cell_count", 0)) for x in siblings)
        item = {
            "province_id": str(p.get("province_id", "")),
            "legacy_id": str(p.get("legacy_id", "")),
            "name": str(p.get("name", "")),
            "country_prefix": str(p.get("country_prefix", "")),
            "area_km2": round(area, 3),
            "area_band": band(area),
            "region_name": str(p.get("region_name", "")),
            "profile_id": str(p.get("profile_id", "")),
            "region_target_cell_area_km2": float(p.get("region_target_cell_area_km2", 0.0)),
            "raw_area_count": round(float(p.get("raw_area_count", 0.0)), 6),
            "area_count": int(p.get("area_count", 0)),
            "target_cell_count": 1,
            "region_assignment_review": bool(p.get("region_assignment_review", False)),
            "region_assignment_confidence": str(p.get("region_assignment_confidence", "")),
            "repeated_country_name": repeated_name_piece,
            "same_name_record_count": len(siblings),
            "same_name_total_area_km2": round(sibling_area, 3),
            "same_name_total_target_cells": sibling_cells,
        }
        records.append(item)
        area_counts[item["area_band"]] += 1

    smallest = sorted(records, key=lambda x: (x["area_km2"], x["country_prefix"], x["name"]))
    largest = sorted(records, key=lambda x: (-x["area_km2"], x["country_prefix"], x["name"]))

    summary = {
        "layer8_province_count": len(provinces),
        "one_cell_count": len(records),
        "under_100_km2": sum(x["area_km2"] < 100 for x in records),
        "under_500_km2": sum(x["area_km2"] < 500 for x in records),
        "under_1000_km2": sum(x["area_km2"] < 1000 for x in records),
        "under_5000_km2": sum(x["area_km2"] < 5000 for x in records),
        "over_10000_km2": sum(x["area_km2"] >= 10000 for x in records),
        "over_20000_km2": sum(x["area_km2"] >= 20000 for x in records),
        "over_40000_km2": sum(x["area_km2"] >= 40000 for x in records),
        "over_80000_km2": sum(x["area_km2"] >= 80000 for x in records),
        "repeated_country_name_one_cell_count": sum(x["repeated_country_name"] for x in records),
        "region_assignment_review_count": sum(x["region_assignment_review"] for x in records),
    }

    report = {
        "schema_version": 1,
        "format": "layer8_one_cell_extremes/v1",
        "source": str(TARGETS.relative_to(ROOT)),
        "summary": summary,
        "area_band_counts": {label: area_counts[label] for _, label in AREA_BANDS},
        "smallest_one_cell": smallest[:150],
        "largest_one_cell": largest[:150],
        "very_small_under_500": [x for x in smallest if x["area_km2"] < 500],
        "small_under_1000": [x for x in smallest if x["area_km2"] < 1000],
        "large_20k_plus": [x for x in largest if x["area_km2"] >= 20000],
        "very_large_40k_plus": [x for x in largest if x["area_km2"] >= 40000],
        "huge_80k_plus": [x for x in largest if x["area_km2"] >= 80000],
        "likely_render_piece_fragments": [x for x in smallest if x["repeated_country_name"]],
    }
    write_json(OUT_JSON, report)

    lines = [
        "# Layer 8 — одноклеточные провинции: слишком маленькие и слишком большие",
        "",
        "Диагностика только по текущим 4027 провинциям Layer 8. Ничего не меняет.",
        "",
        "## Итог",
        "",
        f"- Провинций Layer 8: **{summary['layer8_province_count']}**.",
        f"- Из них с 1 клеткой: **{summary['one_cell_count']}**.",
        f"- <100 км²: **{summary['under_100_km2']}**.",
        f"- <500 км²: **{summary['under_500_km2']}**.",
        f"- <1 000 км²: **{summary['under_1000_km2']}**.",
        f"- >=20 000 км²: **{summary['over_20000_km2']}**.",
        f"- >=40 000 км²: **{summary['over_40000_km2']}**.",
        f"- >=80 000 км²: **{summary['over_80000_km2']}**.",
        f"- Одноклеточных записей с повторяющимся country+name (вероятные отдельные polygon-pieces): **{summary['repeated_country_name_one_cell_count']}**.",
        "",
        "## Распределение по площади",
        "",
        "| Площадь | 1-cell провинций |",
        "|---|---:|",
    ]
    for _, label in AREA_BANDS:
        lines.append(f"| {label} | {area_counts[label]} |")

    def add_table(title: str, rows: list[dict[str, Any]], limit: int) -> None:
        lines.extend(["", f"## {title}", "", "| Страна | Провинция | км² | legacy_id | region | raw cells | повтор имени |", "|---|---|---:|---|---|---:|---|"])
        for x in rows[:limit]:
            lines.append(
                f"| {x['country_prefix']} | {x['name']} | {x['area_km2']:.1f} | `{x['legacy_id']}` | "
                f"{x['region_name']} | {x['raw_area_count']:.3f} | {x['repeated_country_name']} |"
            )

    add_table("Самые маленькие одноклеточные — первые 60", smallest, 60)
    add_table("Самые большие одноклеточные — первые 60", largest, 60)
    add_table("Крупные одноклеточные >=20 000 км²", [x for x in largest if x["area_km2"] >= 20000], 200)
    add_table("Вероятные отдельные polygon-pieces среди одноклеточных — первые 80", [x for x in smallest if x["repeated_country_name"]], 80)

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("LAYER8_ONE_CELL_EXTREMES_OK", summary)


if __name__ == "__main__":
    main()

# Temporary no-op marker used only to trigger the audit workflow from a draft PR.
