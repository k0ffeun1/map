#!/usr/bin/env python3
"""Audit one-cell extremes on the FINAL normalized gameplay-parent layer."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGETS_PATH = ROOT / "assets" / "game_data" / "layer8_normalized_cell_targets.json"
OUT_JSON = ROOT / "reports" / "layer8_normalized_one_cell_extremes.json"
OUT_MD = ROOT / "reports" / "layer8_normalized_one_cell_extremes.md"

BANDS = [
    (0, 100, "<100"),
    (100, 500, "100–500"),
    (500, 1000, "500–1000"),
    (1000, 5000, "1000–5000"),
    (5000, 10000, "5000–10000"),
    (10000, 20000, "10000–20000"),
    (20000, 40000, "20000–40000"),
    (40000, 80000, "40000–80000"),
    (80000, float("inf"), ">=80000"),
]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def band_for(area: float) -> str:
    for lo, hi, label in BANDS:
        if lo <= area < hi:
            return label
    return ">=80000"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    doc = read_json(TARGETS_PATH)
    if doc.get("format") != "layer8_normalized_cell_targets/v1":
        raise RuntimeError(f"Unexpected targets format: {doc.get('format')}")
    provinces = [dict(x) for x in doc.get("provinces", [])]
    one = [x for x in provinces if int(x.get("target_cell_count", 0)) == 1]
    one.sort(key=lambda x: (float(x.get("area_km2", 0.0)), str(x.get("gameplay_parent_id", ""))))
    largest = sorted(one, key=lambda x: (-float(x.get("area_km2", 0.0)), str(x.get("gameplay_parent_id", ""))))
    bands = Counter(band_for(float(x.get("area_km2", 0.0))) for x in one)

    large20 = [x for x in one if float(x.get("area_km2", 0.0)) >= 20_000.0]
    large10 = [x for x in one if float(x.get("area_km2", 0.0)) >= 10_000.0]
    under500 = [x for x in one if float(x.get("area_km2", 0.0)) < 500.0]

    summary = {
        "gameplay_parent_count": len(provinces),
        "one_cell_count": len(one),
        "one_cell_under_500_count": len(under500),
        "one_cell_ge_10000_count": len(large10),
        "one_cell_ge_20000_count": len(large20),
        "area_band_counts": {label: bands.get(label, 0) for _, _, label in BANDS},
        "largest_one_cell_area_km2": round(float(largest[0]["area_km2"]), 3) if largest else 0.0,
    }
    report = {
        "schema_version": 1,
        "format": "layer8_normalized_one_cell_extremes/v1",
        "content_version": "2026.08.22",
        "source": str(TARGETS_PATH.relative_to(ROOT)),
        "summary": summary,
        "smallest_one_cell": one[:40],
        "largest_one_cell": largest[:40],
        "large_one_cell_ge_20000": large20,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Layer 8 — финальный аудит одноклеточных gameplay-провинций",
        "",
        "> Аудит работает по нормализованным gameplay-parent, а не по 4027 техническим render-pieces.",
        "",
        "## Сводка",
        "",
        f"- Gameplay-провинций: **{len(provinces)}**",
        f"- Одноклеточных: **{len(one)}**",
        f"- Одноклеточных <500 км²: **{len(under500)}**",
        f"- Одноклеточных >=10 000 км²: **{len(large10)}**",
        f"- Одноклеточных >=20 000 км²: **{len(large20)}**",
        f"- Самая большая оставшаяся одноклеточная: **{summary['largest_one_cell_area_km2']:.1f} км²**",
        "",
        "## Распределение по площади",
        "",
    ]
    for _, _, label in BANDS:
        lines.append(f"- {label} км²: **{bands.get(label, 0)}**")

    lines.extend(["", "## Самые большие оставшиеся одноклеточные", ""])
    if not largest:
        lines.append("- Нет.")
    for item in largest[:30]:
        lines.append(
            f"- **{item.get('display_name', '?')}** — {float(item.get('area_km2', 0.0)):.1f} км² — "
            f"{item.get('country_prefix', '?')} / {item.get('region_name', '?')}"
        )
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.check and large20:
        raise SystemExit(f"Large one-cell gameplay provinces remain: {len(large20)}")


if __name__ == "__main__":
    main()
