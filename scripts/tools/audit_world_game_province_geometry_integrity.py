#!/usr/bin/env python3
"""Audit world Admin-1 geometry integrity before automatic gameplay-province splitting.

The split-candidate audit intentionally uses only target cell count and area.  A
few records have implausibly large areas, which can happen if an identity is
paired with a country-scale or otherwise overlapping polygon.  This audit does
NOT mutate geometry.  It checks a stronger invariant instead: canonical Admin-1
polygons belonging to the same country should not substantially overlap.

Outputs:
  reports/world_game_province_geometry_integrity_audit.json
  reports/world_game_province_geometry_integrity_audit.md
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any

from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parents[2]
GEOMETRY = ROOT / "assets" / "provinces.json"
IDENTITIES = ROOT / "assets" / "game_data" / "provinces.json"
TARGETS = ROOT / "assets" / "game_data" / "world_province_cell_targets.json"
OUT_JSON = ROOT / "reports" / "world_game_province_geometry_integrity_audit.json"
OUT_MD = ROOT / "reports" / "world_game_province_geometry_integrity_audit.md"
EXPECTED = 4027

# We only hard-block on substantial same-country overlap.  Tiny Natural Earth
# seams/slivers are reported separately but are not allowed to stop generation.
REPORT_OVERLAP_RATIO = 0.01
SUSPICIOUS_OVERLAP_RATIO = 0.20
SEVERE_CONTAINMENT_RATIO = 0.85
SPLIT_CELL_THRESHOLD = 8
SPLIT_AREA_THRESHOLD_KM2 = 40_000.0


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def polygon_from_rings(raw_rings: Any) -> Polygon | None:
    if not isinstance(raw_rings, list) or not raw_rings:
        return None
    rings: list[list[tuple[float, float]]] = []
    for raw_ring in raw_rings:
        if not isinstance(raw_ring, list):
            continue
        pts: list[tuple[float, float]] = []
        for p in raw_ring:
            if isinstance(p, list) and len(p) >= 2:
                try:
                    pts.append((float(p[0]), float(p[1])))
                except (TypeError, ValueError):
                    pass
        if len(pts) >= 3:
            rings.append(pts)
    if not rings:
        return None
    try:
        poly = Polygon(rings[0], rings[1:])
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty:
            return None
        # The canonical file is expected to contain one polygon per layer-8
        # record.  buffer(0) can theoretically return MultiPolygon; keep the
        # unioned geometry object because area/intersection still work.
        return poly
    except Exception:
        return None


def country_from_legacy(legacy_id: str) -> str:
    return legacy_id.split("__", 1)[0] if "__" in legacy_id else legacy_id


def intersects_bbox(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def main() -> None:
    geometry_doc = read(GEOMETRY)
    identity_doc = read(IDENTITIES)
    target_doc = read(TARGETS)

    canonical = {
        str(x.get("id", "")): x
        for x in geometry_doc.get("cells", [])
        if str(x.get("id", ""))
    }
    identities = {
        str(x.get("id", "")): x
        for x in identity_doc.get("provinces", [])
        if str(x.get("id", ""))
    }
    targets = {
        str(x.get("province_id", "")): x
        for x in target_doc.get("provinces", [])
        if str(x.get("province_id", ""))
    }

    rows: list[dict[str, Any]] = []
    missing_geometry: list[dict[str, Any]] = []
    invalid_geometry: list[dict[str, Any]] = []

    for pid, ident in identities.items():
        legacy = str(ident.get("legacy_id", ""))
        raw = canonical.get(legacy)
        if raw is None:
            missing_geometry.append({"province_id": pid, "legacy_id": legacy, "name": ident.get("name", "")})
            continue
        poly = polygon_from_rings(raw.get("rings", []))
        if poly is None:
            invalid_geometry.append({"province_id": pid, "legacy_id": legacy, "name": ident.get("name", "")})
            continue
        target = targets.get(pid, {})
        rows.append({
            "province_id": pid,
            "legacy_id": legacy,
            "name": str(ident.get("name", "")),
            "country_prefix": country_from_legacy(legacy),
            "geometry": poly,
            "bounds": tuple(float(v) for v in poly.bounds),
            "planar_area": float(poly.area),
            "area_km2": float(target.get("area_km2", 0.0) or 0.0),
            "target_cell_count": int(target.get("target_cell_count", 0) or 0),
            "region_name": str(target.get("region_name", "")),
        })

    by_country: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_country[row["country_prefix"]].append(row)

    overlap_pairs: list[dict[str, Any]] = []
    province_overlap: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "partner_count": 0,
        "suspicious_partner_count": 0,
        "max_smaller_overlap_ratio": 0.0,
        "max_self_overlap_ratio": 0.0,
        "partners": [],
    })

    for country, group in by_country.items():
        n = len(group)
        for i in range(n):
            a = group[i]
            ga = a["geometry"]
            aa = max(float(a["planar_area"]), 1e-15)
            for j in range(i + 1, n):
                b = group[j]
                if not intersects_bbox(a["bounds"], b["bounds"]):
                    continue
                gb = b["geometry"]
                try:
                    inter = ga.intersection(gb)
                except Exception:
                    continue
                ia = float(inter.area)
                if ia <= 0.0:
                    continue
                ab = max(float(b["planar_area"]), 1e-15)
                ratio_a = ia / aa
                ratio_b = ia / ab
                smaller_ratio = ia / min(aa, ab)
                if smaller_ratio < REPORT_OVERLAP_RATIO:
                    continue
                suspicious = smaller_ratio >= SUSPICIOUS_OVERLAP_RATIO
                severe = smaller_ratio >= SEVERE_CONTAINMENT_RATIO
                pair = {
                    "country_prefix": country,
                    "a_province_id": a["province_id"],
                    "a_name": a["name"],
                    "a_area_km2": round(a["area_km2"], 3),
                    "b_province_id": b["province_id"],
                    "b_name": b["name"],
                    "b_area_km2": round(b["area_km2"], 3),
                    "overlap_of_a": round(ratio_a, 6),
                    "overlap_of_b": round(ratio_b, 6),
                    "overlap_of_smaller": round(smaller_ratio, 6),
                    "suspicious": suspicious,
                    "severe_containment": severe,
                }
                overlap_pairs.append(pair)
                for me, other, self_ratio in ((a, b, ratio_a), (b, a, ratio_b)):
                    stat = province_overlap[me["province_id"]]
                    stat["partner_count"] += 1
                    if suspicious:
                        stat["suspicious_partner_count"] += 1
                    stat["max_smaller_overlap_ratio"] = max(stat["max_smaller_overlap_ratio"], smaller_ratio)
                    stat["max_self_overlap_ratio"] = max(stat["max_self_overlap_ratio"], self_ratio)
                    if len(stat["partners"]) < 20:
                        stat["partners"].append({
                            "province_id": other["province_id"],
                            "name": other["name"],
                            "overlap_of_smaller": round(smaller_ratio, 6),
                            "overlap_of_self": round(self_ratio, 6),
                        })

    # Country-relative area outliers are diagnostics only.  They never hard
    # block a valid huge Admin-1 by themselves.
    area_outliers: list[dict[str, Any]] = []
    for country, group in by_country.items():
        positive = [x["area_km2"] for x in group if x["area_km2"] > 0]
        if len(positive) < 4:
            continue
        med = median(positive)
        if med <= 0:
            continue
        for row in group:
            ratio = row["area_km2"] / med if row["area_km2"] > 0 else 0.0
            if row["area_km2"] >= SPLIT_AREA_THRESHOLD_KM2 and ratio >= 8.0:
                area_outliers.append({
                    "province_id": row["province_id"],
                    "legacy_id": row["legacy_id"],
                    "name": row["name"],
                    "country_prefix": country,
                    "area_km2": round(row["area_km2"], 3),
                    "country_median_area_km2": round(med, 3),
                    "median_ratio": round(ratio, 3),
                    "target_cell_count": row["target_cell_count"],
                    "has_suspicious_overlap": province_overlap[row["province_id"]]["suspicious_partner_count"] > 0,
                })

    split_candidates: list[dict[str, Any]] = []
    blocked_candidates: list[dict[str, Any]] = []
    safe_candidates: list[dict[str, Any]] = []
    for row in rows:
        if row["target_cell_count"] < SPLIT_CELL_THRESHOLD or row["area_km2"] < SPLIT_AREA_THRESHOLD_KM2:
            continue
        stat = province_overlap[row["province_id"]]
        blocked = stat["suspicious_partner_count"] > 0
        item = {
            "province_id": row["province_id"],
            "legacy_id": row["legacy_id"],
            "name": row["name"],
            "country_prefix": row["country_prefix"],
            "area_km2": round(row["area_km2"], 3),
            "target_cell_count": row["target_cell_count"],
            "region_name": row["region_name"],
            "decision": "blocked_geometry_overlap" if blocked else "safe_for_split_geometry_gate",
            "suspicious_overlap_partner_count": stat["suspicious_partner_count"],
            "max_smaller_overlap_ratio": round(stat["max_smaller_overlap_ratio"], 6),
            "max_self_overlap_ratio": round(stat["max_self_overlap_ratio"], 6),
            "overlap_partners": stat["partners"],
        }
        split_candidates.append(item)
        (blocked_candidates if blocked else safe_candidates).append(item)

    overlap_pairs.sort(key=lambda x: (-x["overlap_of_smaller"], x["country_prefix"], x["a_name"], x["b_name"]))
    blocked_candidates.sort(key=lambda x: (-x["max_smaller_overlap_ratio"], -x["area_km2"], x["country_prefix"], x["name"]))
    safe_candidates.sort(key=lambda x: (-x["target_cell_count"], -x["area_km2"], x["country_prefix"], x["name"]))
    area_outliers.sort(key=lambda x: (-x["median_ratio"], -x["area_km2"]))

    report = {
        "schema_version": 1,
        "format": "world_game_province_geometry_integrity_audit/v1",
        "sources": {
            "canonical_geometry": "assets/provinces.json",
            "identity": "assets/game_data/provinces.json",
            "cell_targets": "assets/game_data/world_province_cell_targets.json",
        },
        "policy": {
            "same_country_overlap_report_ratio": REPORT_OVERLAP_RATIO,
            "same_country_overlap_hard_block_ratio": SUSPICIOUS_OVERLAP_RATIO,
            "severe_containment_ratio": SEVERE_CONTAINMENT_RATIO,
            "split_cell_threshold": SPLIT_CELL_THRESHOLD,
            "split_area_threshold_km2": SPLIT_AREA_THRESHOLD_KM2,
            "area_outlier_is_diagnostic_only": True,
        },
        "summary": {
            "identity_count": len(identities),
            "geometry_count": len(canonical),
            "valid_geometry_count": len(rows),
            "missing_geometry_count": len(missing_geometry),
            "invalid_geometry_count": len(invalid_geometry),
            "reported_overlap_pair_count": len(overlap_pairs),
            "suspicious_overlap_pair_count": sum(1 for x in overlap_pairs if x["suspicious"]),
            "severe_containment_pair_count": sum(1 for x in overlap_pairs if x["severe_containment"]),
            "split_candidate_count": len(split_candidates),
            "blocked_split_candidate_count": len(blocked_candidates),
            "geometry_safe_split_candidate_count": len(safe_candidates),
            "area_outlier_count": len(area_outliers),
        },
        "missing_geometry": missing_geometry,
        "invalid_geometry": invalid_geometry,
        "blocked_split_candidates": blocked_candidates,
        "geometry_safe_split_candidates": safe_candidates,
        "suspicious_overlap_pairs": [x for x in overlap_pairs if x["suspicious"]],
        "reported_overlap_pairs": overlap_pairs,
        "area_outliers_diagnostic": area_outliers,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md: list[str] = [
        "# Аудит геометрической целостности игровых провинций мира",
        "",
        "> Геометрию не изменяет. Проверяет, можно ли безопасно запускать автоматическое деление крупных Admin-1.",
        "",
        "## Правило",
        "",
        f"- Перекрытие менее {REPORT_OVERLAP_RATIO:.0%} меньшего полигона игнорируется как микроскопический шов/шум.",
        f"- От {REPORT_OVERLAP_RATIO:.0%} до {SUSPICIOUS_OVERLAP_RATIO:.0%}: только отчёт.",
        f"- Перекрытие ≥ {SUSPICIOUS_OVERLAP_RATIO:.0%} меньшего полигона внутри одной страны: **hard block** для автоделения.",
        f"- Перекрытие ≥ {SEVERE_CONTAINMENT_RATIO:.0%}: почти полное вложение/дубликат, отмечается отдельно.",
        "- Аномально большая площадь относительно медианы страны сама по себе НЕ блокирует деление: это только диагностический сигнал.",
        "",
        "## Итог",
        "",
        f"- Исходных identity: **{len(identities)}**.",
        f"- Валидных геометрий: **{len(rows)}**.",
        f"- Кандидатов автоделения (8+ клеток, ≥40 000 км²): **{len(split_candidates)}**.",
        f"- Заблокировано из-за существенного перекрытия: **{len(blocked_candidates)}**.",
        f"- Прошли геометрический gate: **{len(safe_candidates)}**.",
        f"- Существенных пар перекрытия: **{sum(1 for x in overlap_pairs if x['suspicious'])}**.",
        f"- Почти полных вложений/дубликатов: **{sum(1 for x in overlap_pairs if x['severe_containment'])}**.",
        f"- Диагностических area-outlier: **{len(area_outliers)}**.",
        "",
        "## Заблокированные кандидаты на деление",
        "",
        "| Страна | Провинция | Площадь, км² | Клеток | Перекрытий | Max overlap меньшего |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for x in blocked_candidates:
        md.append(
            f"| {x['country_prefix']} | {x['name']} | {x['area_km2']:.1f} | {x['target_cell_count']} | "
            f"{x['suspicious_overlap_partner_count']} | {x['max_smaller_overlap_ratio']:.1%} |"
        )

    md += [
        "",
        "## Существенные пары перекрытия",
        "",
        "| Страна | A | B | overlap меньшего | A covered | B covered | severe |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for x in [p for p in overlap_pairs if p["suspicious"]]:
        md.append(
            f"| {x['country_prefix']} | {x['a_name']} | {x['b_name']} | {x['overlap_of_smaller']:.1%} | "
            f"{x['overlap_of_a']:.1%} | {x['overlap_of_b']:.1%} | {'YES' if x['severe_containment'] else ''} |"
        )

    md += [
        "",
        "## Area-outlier — только диагностика",
        "",
        "| Страна | Провинция | Площадь, км² | Медиана страны | x медианы | Клеток | Есть overlap |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for x in area_outliers:
        md.append(
            f"| {x['country_prefix']} | {x['name']} | {x['area_km2']:.1f} | {x['country_median_area_km2']:.1f} | "
            f"{x['median_ratio']:.1f} | {x['target_cell_count']} | {'YES' if x['has_suspicious_overlap'] else ''} |"
        )

    OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(
        "WORLD_GAME_PROVINCE_GEOMETRY_INTEGRITY_AUDIT",
        f"valid={len(rows)}",
        f"split_candidates={len(split_candidates)}",
        f"blocked={len(blocked_candidates)}",
        f"safe={len(safe_candidates)}",
        f"suspicious_pairs={sum(1 for x in overlap_pairs if x['suspicious'])}",
        f"severe_pairs={sum(1 for x in overlap_pairs if x['severe_containment'])}",
    )

    if len(identities) != EXPECTED or len(canonical) != EXPECTED:
        raise SystemExit(2)
    if missing_geometry or invalid_geometry:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
