#!/usr/bin/env python3
"""Audit source provinces that are candidates for splitting into game provinces.

This is a planning/audit stage only. It never changes province or cell geometry.

Policy (v1):
- target_cell_count < 8: untouched
- target_cell_count >= 8 and area < 20,000 km²: compact_protected
- target_cell_count >= 8 and 20,000 <= area < 40,000 km²: review
- target_cell_count >= 8 and area >= 40,000 km²: split

For split candidates, proposed game-province count is ceil(target_cell_count / 7),
matching the India test's preferred maximum of 7 whole cells per game province.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "assets/game_data/world_province_cell_targets.json"
OUTPUT_JSON = ROOT / "reports/world_game_province_split_candidates.json"
OUTPUT_MD = ROOT / "reports/world_game_province_split_candidates.md"

CELL_THRESHOLD = 8
COMPACT_MAX_AREA_KM2 = 20_000.0
REVIEW_MAX_AREA_KM2 = 40_000.0
PREFERRED_MAX_CELLS_PER_GAME_PROVINCE = 7


def classify(area_km2: float, target_cells: int) -> str:
    if target_cells < CELL_THRESHOLD:
        return "untouched"
    if area_km2 < COMPACT_MAX_AREA_KM2:
        return "compact_protected"
    if area_km2 < REVIEW_MAX_AREA_KM2:
        return "review"
    return "split"


def proposed_piece_count(audit_class: str, target_cells: int) -> int:
    if audit_class != "split":
        return 1
    return max(2, math.ceil(target_cells / PREFERRED_MAX_CELLS_PER_GAME_PROVINCE))


def compact_record(p: dict, audit_class: str, pieces: int) -> dict:
    return {
        "province_id": p.get("province_id", ""),
        "legacy_id": p.get("legacy_id", ""),
        "name": p.get("name", ""),
        "country_prefix": p.get("country_prefix", ""),
        "region_id": p.get("region_id", ""),
        "region_name": p.get("region_name", ""),
        "area_km2": float(p.get("area_km2", 0.0)),
        "target_cell_count": int(p.get("target_cell_count", 0)),
        "profile_id": p.get("profile_id", ""),
        "region_assignment_confidence": p.get("region_assignment_confidence", ""),
        "region_assignment_review": bool(p.get("region_assignment_review", False)),
        "audit_class": audit_class,
        "proposed_game_province_count": pieces,
    }


def country_summary(records: list[dict]) -> list[dict]:
    per_country: dict[str, dict[str, int]] = defaultdict(lambda: {
        "candidate_count": 0,
        "compact_protected_count": 0,
        "review_count": 0,
        "split_count": 0,
        "extra_game_provinces_if_split": 0,
    })
    for r in records:
        c = r["country_prefix"] or "unknown"
        d = per_country[c]
        d["candidate_count"] += 1
        d[f'{r["audit_class"]}_count'] += 1
        if r["audit_class"] == "split":
            d["extra_game_provinces_if_split"] += r["proposed_game_province_count"] - 1
    rows = [{"country_prefix": c, **v} for c, v in per_country.items()]
    rows.sort(key=lambda r: (-r["split_count"], -r["candidate_count"], r["country_prefix"]))
    return rows


def render_md(report: dict) -> str:
    s = report["summary"]
    lines = [
        "# Аудит кандидатов на деление игровых провинций мира",
        "",
        "> Это только аудит. Геометрия клеток и исходных Admin-1 не изменяется.",
        "",
        "## Правило v1",
        "",
        f"- `< {CELL_THRESHOLD}` клеток: не рассматриваем.",
        f"- `>= {CELL_THRESHOLD}` клеток и площадь `< {int(COMPACT_MAX_AREA_KM2):,}` км²: **compact_protected** — не делить.",
        f"- `>= {CELL_THRESHOLD}` клеток и площадь `{int(COMPACT_MAX_AREA_KM2):,}–{int(REVIEW_MAX_AREA_KM2):,}` км²: **review** — вручную проверить, пока не делить.",
        f"- `>= {CELL_THRESHOLD}` клеток и площадь `>= {int(REVIEW_MAX_AREA_KM2):,}` км²: **split** — можно автоматически делить по готовым клеткам.",
        f"- При делении стараемся держать не более `{PREFERRED_MAX_CELLS_PER_GAME_PROVINCE}` клеток на игровую провинцию.",
        "",
        "## Итог",
        "",
        f"- Исходных записей: **{s['source_province_count']}**.",
        f"- Кандидатов с {CELL_THRESHOLD}+ клетками: **{s['candidate_count']}**.",
        f"- Защищённых компактных: **{s['compact_protected_count']}**.",
        f"- На ручную проверку: **{s['review_count']}**.",
        f"- Автоматически делить: **{s['split_count']}**.",
        f"- Не затрагиваются вообще: **{s['untouched_count']}**.",
        f"- Проекция числа игровых провинций, если делить только `split`: **{s['projected_game_province_count']}** (из {s['source_province_count']}, +{s['projected_extra_game_provinces']}).",
        "",
        "## Compact protected — полный список",
        "",
        "| Страна | Провинция | Площадь, км² | Клеток | Регион |",
        "|---|---|---:|---:|---|",
    ]
    for r in report["compact_protected"]:
        lines.append(f"| {r['country_prefix']} | {r['name']} | {r['area_km2']:.1f} | {r['target_cell_count']} | {r['region_name']} |")
    lines += [
        "",
        "## Review — полный список",
        "",
        "| Страна | Провинция | Площадь, км² | Клеток | Регион |",
        "|---|---|---:|---:|---|",
    ]
    for r in report["review"]:
        lines.append(f"| {r['country_prefix']} | {r['name']} | {r['area_km2']:.1f} | {r['target_cell_count']} | {r['region_name']} |")
    lines += [
        "",
        "## Split — полный список",
        "",
        "| Страна | Провинция | Площадь, км² | Клеток | Игровых провинций | Регион |",
        "|---|---|---:|---:|---:|---|",
    ]
    for r in report["split"]:
        lines.append(f"| {r['country_prefix']} | {r['name']} | {r['area_km2']:.1f} | {r['target_cell_count']} | {r['proposed_game_province_count']} | {r['region_name']} |")
    lines += [
        "",
        "## Важное ограничение",
        "",
        "Этот отчёт работает по текущим 4027 исходным записям. Перед фактической мировой генерацией необходимо отдельно объединить записи, которые являются геометрическими частями одной логической Admin-1 (например, островные/разорванные куски с одинаковым родителем), чтобы маленькие острова не становились самостоятельными игровыми провинциями по ошибке.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    provinces = data.get("provinces", [])
    if len(provinces) != int(data.get("province_count", len(provinces))):
        raise SystemExit("province_count mismatch in source target file")

    candidates: list[dict] = []
    by_class: dict[str, list[dict]] = {
        "compact_protected": [],
        "review": [],
        "split": [],
    }
    class_counts = Counter()
    cell_counts_by_class: dict[str, Counter] = defaultdict(Counter)

    projected_extra = 0
    for p in provinces:
        target_cells = int(p.get("target_cell_count", 0))
        area_km2 = float(p.get("area_km2", 0.0))
        audit_class = classify(area_km2, target_cells)
        class_counts[audit_class] += 1
        cell_counts_by_class[audit_class][target_cells] += 1
        if audit_class == "untouched":
            continue
        pieces = proposed_piece_count(audit_class, target_cells)
        r = compact_record(p, audit_class, pieces)
        candidates.append(r)
        by_class[audit_class].append(r)
        projected_extra += pieces - 1

    for rows in by_class.values():
        rows.sort(key=lambda r: (r["area_km2"], r["country_prefix"], r["name"], r["province_id"]))

    candidate_cell_sum = sum(r["target_cell_count"] for r in candidates)
    report = {
        "schema_version": 1,
        "format": "world_game_province_split_candidates/v1",
        "source": str(INPUT.relative_to(ROOT)).replace("\\", "/"),
        "policy": {
            "cell_candidate_threshold": CELL_THRESHOLD,
            "compact_protected_area_lt_km2": COMPACT_MAX_AREA_KM2,
            "review_area_from_km2_inclusive": COMPACT_MAX_AREA_KM2,
            "review_area_to_km2_exclusive": REVIEW_MAX_AREA_KM2,
            "split_area_gte_km2": REVIEW_MAX_AREA_KM2,
            "preferred_max_cells_per_game_province": PREFERRED_MAX_CELLS_PER_GAME_PROVINCE,
            "review_is_split_by_default": False,
        },
        "summary": {
            "source_province_count": len(provinces),
            "untouched_count": class_counts["untouched"],
            "candidate_count": len(candidates),
            "compact_protected_count": len(by_class["compact_protected"]),
            "review_count": len(by_class["review"]),
            "split_count": len(by_class["split"]),
            "candidate_target_cell_sum": candidate_cell_sum,
            "projected_extra_game_provinces": projected_extra,
            "projected_game_province_count": len(provinces) + projected_extra,
        },
        "count_distribution_by_class": {
            k: {str(cell_count): count for cell_count, count in sorted(v.items())}
            for k, v in sorted(cell_counts_by_class.items())
        },
        "country_summary": country_summary(candidates),
        "compact_protected": by_class["compact_protected"],
        "review": by_class["review"],
        "split": by_class["split"],
        "notes": [
            "Audit only; no geometry is changed.",
            "compact_protected and review remain one game province in this projection.",
            "Before actual world splitting, logical Admin-1 multipart/island records must be grouped by parent identity.",
        ],
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_MD.write_text(render_md(report), encoding="utf-8")

    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
