#!/usr/bin/env python3
"""Audit world Admin-1 identity, geometry and area integrity before splitting.

This stage is read-only with respect to source map data.  It verifies that the
4027 target records still point to the same province passports and canonical
Layer-8 geometry, recomputes the current project area formula, computes an
independent WGS84 geodesic area, checks geometry validity, and surfaces strong
within-country area outliers for manual source review.

No province geometry, cell geometry, region assignment, or target count is
modified by this script.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pyproj import Geod
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.validation import explain_validity

ROOT = Path(__file__).resolve().parents[2]
WORLD_PX = 8192.0
EARTH_RADIUS_KM = 6371.0088
EXPECTED = 4027

TARGETS_PATH = ROOT / "assets" / "game_data" / "world_province_cell_targets.json"
IDENTITY_PATH = ROOT / "assets" / "game_data" / "provinces.json"
CANONICAL_PATH = ROOT / "assets" / "provinces.json"
MIRROR_PATH = ROOT / "assets" / "map_geometry" / "provinces.json"
SPLIT_AUDIT_PATH = ROOT / "reports" / "world_game_province_split_candidates.json"
OUTPUT_JSON = ROOT / "reports" / "world_province_identity_geometry_audit.json"
OUTPUT_MD = ROOT / "reports" / "world_province_identity_geometry_audit.md"

GEOD = Geod(ellps="WGS84")
NAMED_DIAGNOSTICS = {"Appenzell Innerrhoden", "Jekabpils", "Northumberland"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def duplicate_values(values: list[str]) -> list[str]:
    counts = Counter(values)
    return sorted(k for k, v in counts.items() if k and v > 1)


def geometry_hash(entry: dict[str, Any]) -> str:
    payload = json.dumps(entry.get("rings", []), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def bbox_from_rings(rings: Any) -> list[float]:
    points: list[list[Any]] = []
    if isinstance(rings, list):
        for ring in rings:
            if isinstance(ring, list):
                points.extend(p for p in ring if isinstance(p, list) and len(p) >= 2)
    if not points:
        return []
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def raw_geometry(entry: dict[str, Any]) -> Polygon:
    rings = entry.get("rings", [])
    if not isinstance(rings, list) or not rings:
        return Polygon()
    try:
        return Polygon(rings[0], rings[1:])
    except Exception:
        return Polygon()


def repaired_geometry(entry: dict[str, Any]) -> Any:
    geom = raw_geometry(entry)
    if geom.is_empty:
        return geom
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom


def polygon_parts(geometry: Any) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, (MultiPolygon, GeometryCollection)) or hasattr(geometry, "geoms"):
        return [g for g in geometry.geoms if isinstance(g, Polygon) and not g.is_empty]
    return []


def world_to_lonlat(x: float, y: float) -> tuple[float, float]:
    lon = float(x) / WORLD_PX * 360.0 - 180.0
    mercator_n = math.pi - 2.0 * math.pi * float(y) / WORLD_PX
    lat = math.degrees(math.atan(math.sinh(mercator_n)))
    return lon, lat


def km_per_world_px(y: float) -> float:
    _lon, latitude = world_to_lonlat(0.0, y)
    return 2.0 * math.pi * EARTH_RADIUS_KM / WORLD_PX * math.cos(math.radians(latitude))


def project_area_km2(geometry: Any) -> float:
    if geometry is None or geometry.is_empty:
        return 0.0
    scale = km_per_world_px(float(geometry.representative_point().y))
    return float(geometry.area) * scale * scale


def geodesic_ring_area_km2(coords: Any) -> float:
    pts = list(coords)
    if len(pts) < 3:
        return 0.0
    lonlat = [world_to_lonlat(float(x), float(y)) for x, y, *_rest in pts]
    lons = [p[0] for p in lonlat]
    lats = [p[1] for p in lonlat]
    area_m2, _perimeter_m = GEOD.polygon_area_perimeter(lons, lats)
    return abs(float(area_m2)) / 1_000_000.0


def geodesic_area_km2(geometry: Any) -> float:
    total = 0.0
    for part in polygon_parts(geometry):
        area = geodesic_ring_area_km2(part.exterior.coords)
        for hole in part.interiors:
            area -= geodesic_ring_area_km2(hole.coords)
        total += max(0.0, area)
    return total


def percent_error(a: float, b: float) -> float:
    if b <= 0.0:
        return 0.0 if abs(a) <= 1e-9 else float("inf")
    return abs(a - b) / b * 100.0


def country_prefix_from_legacy(legacy_id: str) -> str:
    return legacy_id.split("__", 1)[0] if "__" in legacy_id else ""


def split_class(area_km2: float, target_cells: int) -> str:
    if target_cells < 8:
        return "untouched"
    if area_km2 < 20_000.0:
        return "compact_protected"
    if area_km2 < 40_000.0:
        return "review"
    return "split"


def compact_issue(pid: str, name: str, legacy_id: str, detail: str) -> dict[str, Any]:
    return {"province_id": pid, "legacy_id": legacy_id, "name": name, "detail": detail}


def render_md(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "# Аудит identity ↔ geometry для мировых Admin-1",
        "",
        "> Диагностический этап. Исходная геометрия, цели клеток и границы не изменяются.",
        "",
        "## Итог",
        "",
        f"- Target records: **{s['target_count']}**.",
        f"- Identity records: **{s['identity_count']}**.",
        f"- Canonical Layer-8 geometries: **{s['canonical_count']}**.",
        f"- Numeric mirror geometries: **{s['mirror_count']}**.",
        f"- Жёстких integrity failures: **{s['hard_integrity_failure_count']}**.",
        f"- Невалидных исходных Polygon до repair: **{s['invalid_raw_geometry_count']}**.",
        f"- Расхождений stored area ↔ текущий project area: **{s['stored_area_recompute_mismatch_count']}**.",
        f"- Geodesic discrepancy >5%: **{s['geodesic_discrepancy_gt_5pct_count']}**.",
        f"- Geodesic discrepancy >20%: **{s['geodesic_discrepancy_gt_20pct_count']}**.",
        f"- Смена split-класса при WGS84 площади: **{s['split_classification_change_count']}**.",
        f"- Сильных внутристрановых area-outlier: **{s['strong_country_area_outlier_count']}**.",
        f"- Из текущих 366 split-кандидатов требуют проверки integrity/area/outlier: **{s['split_candidates_requiring_review_count']}**.",
        f"- Безопасно автоматически делить текущие split-кандидаты: **{'ДА' if s['safe_to_proceed_with_split_candidates'] else 'НЕТ'}**.",
        "",
        "## Как читать диагноз",
        "",
        "- `stored_vs_project`: проверяет, воспроизводится ли площадь тем же алгоритмом, которым строились target counts.",
        "- `project_vs_geodesic`: независимая проверка площади на эллипсоиде WGS84.",
        "- `country_area_ratio_to_median`: статистический сигнал; сам по себе не доказывает ошибку, но хорошо ловит неправильную identity↔geometry пару.",
        "- Никакие записи автоматически не исправляются этим аудитом.",
        "",
        "## Именные диагностические случаи",
        "",
        "| Province | ID | Country | Stored km² | Project km² | WGS84 km² | Δ WGS84 | x country median | Current class | WGS84 class | Valid |",
        "|---|---|---|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for r in report.get("named_diagnostics", []):
        lines.append(
            f"| {r['name']} | {r['province_id']} | {r['country_prefix']} | {r['stored_area_km2']:.1f} | "
            f"{r['project_area_km2']:.1f} | {r['geodesic_area_km2']:.1f} | {r['project_vs_geodesic_error_pct']:.2f}% | "
            f"{r.get('country_area_ratio_to_median', 0.0):.2f}× | {r['current_split_class']} | {r['geodesic_split_class']} | "
            f"{'yes' if r['raw_geometry_valid'] else 'NO'} |"
        )
    lines += [
        "",
        "## Split-кандидаты, требующие проверки",
        "",
        "| Province | Country | Cells | Stored km² | WGS84 km² | Δ | x median | Reasons |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in report.get("split_candidates_requiring_review", []):
        reasons = ", ".join(r.get("review_reasons", []))
        lines.append(
            f"| {r['name']} | {r['country_prefix']} | {r['target_cell_count']} | {r['stored_area_km2']:.1f} | "
            f"{r['geodesic_area_km2']:.1f} | {r['project_vs_geodesic_error_pct']:.2f}% | "
            f"{r.get('country_area_ratio_to_median', 0.0):.2f}× | {reasons} |"
        )
    lines += ["", "## Hard integrity failures", ""]
    if report.get("hard_integrity_failures"):
        for r in report["hard_integrity_failures"]:
            lines.append(f"- `{r.get('province_id', '')}` {r.get('name', '')}: {r.get('detail', '')}")
    else:
        lines.append("- Нет.")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    targets_doc = read_json(TARGETS_PATH)
    identity_doc = read_json(IDENTITY_PATH)
    canonical_doc = read_json(CANONICAL_PATH)
    mirror_doc = read_json(MIRROR_PATH)
    split_doc = read_json(SPLIT_AUDIT_PATH) if SPLIT_AUDIT_PATH.exists() else {}

    targets = list(targets_doc.get("provinces", []))
    identities_list = list(identity_doc.get("provinces", []))
    canonical_list = list(canonical_doc.get("cells", []))
    mirror_list = list(mirror_doc.get("provinces", []))

    target_ids = [str(x.get("province_id", "")) for x in targets]
    identity_ids = [str(x.get("id", "")) for x in identities_list]
    identity_legacy_ids = [str(x.get("legacy_id", "")) for x in identities_list]
    canonical_ids = [str(x.get("id", "")) for x in canonical_list]
    mirror_ids = [str(x.get("id", "")) for x in mirror_list]

    identities = {str(x.get("id", "")): x for x in identities_list if str(x.get("id", ""))}
    canonical = {str(x.get("id", "")): x for x in canonical_list if str(x.get("id", ""))}
    mirror = {str(x.get("id", "")): x for x in mirror_list if str(x.get("id", ""))}

    split_class_by_id: dict[str, str] = {}
    for class_name in ("compact_protected", "review", "split"):
        for item in split_doc.get(class_name, []):
            split_class_by_id[str(item.get("province_id", ""))] = class_name

    hard: list[dict[str, Any]] = []
    duplicate_summary = {
        "target_province_ids": duplicate_values(target_ids),
        "identity_province_ids": duplicate_values(identity_ids),
        "identity_legacy_ids": duplicate_values(identity_legacy_ids),
        "canonical_legacy_ids": duplicate_values(canonical_ids),
        "mirror_province_ids": duplicate_values(mirror_ids),
    }
    for kind, values in duplicate_summary.items():
        for value in values:
            hard.append(compact_issue(value, "", "", f"duplicate {kind}: {value}"))

    if len(targets) != EXPECTED:
        hard.append(compact_issue("", "", "", f"target count {len(targets)} != {EXPECTED}"))
    if len(identities_list) != EXPECTED:
        hard.append(compact_issue("", "", "", f"identity count {len(identities_list)} != {EXPECTED}"))
    if len(canonical_list) != EXPECTED:
        hard.append(compact_issue("", "", "", f"canonical count {len(canonical_list)} != {EXPECTED}"))
    if len(mirror_list) != EXPECTED:
        hard.append(compact_issue("", "", "", f"mirror count {len(mirror_list)} != {EXPECTED}"))

    identity_id_set = set(identity_ids)
    target_id_set = set(target_ids)
    mirror_id_set = set(mirror_ids)
    canonical_id_set = set(canonical_ids)
    for pid in sorted(target_id_set - identity_id_set):
        hard.append(compact_issue(pid, "", "", "target province_id missing from identity passport"))
    for pid in sorted(identity_id_set - target_id_set):
        hard.append(compact_issue(pid, str(identities.get(pid, {}).get("name", "")), str(identities.get(pid, {}).get("legacy_id", "")), "identity passport missing from targets"))
    for pid in sorted(identity_id_set - mirror_id_set):
        hard.append(compact_issue(pid, str(identities.get(pid, {}).get("name", "")), str(identities.get(pid, {}).get("legacy_id", "")), "identity passport missing numeric mirror geometry"))
    for pid in sorted(mirror_id_set - identity_id_set):
        hard.append(compact_issue(pid, "", "", "numeric mirror geometry has no identity passport"))
    for legacy in sorted(set(identity_legacy_ids) - canonical_id_set):
        hard.append(compact_issue("", "", legacy, "identity legacy_id missing canonical Layer-8 geometry"))
    for legacy in sorted(canonical_id_set - set(identity_legacy_ids)):
        hard.append(compact_issue("", "", legacy, "canonical Layer-8 geometry has no identity passport"))

    records: list[dict[str, Any]] = []
    invalid_raw: list[dict[str, Any]] = []
    stored_recompute_mismatch: list[dict[str, Any]] = []
    metadata_mismatch: list[dict[str, Any]] = []
    geometry_copy_mismatch: list[dict[str, Any]] = []

    for target in targets:
        pid = str(target.get("province_id", ""))
        identity = identities.get(pid)
        mirror_entry = mirror.get(pid)
        if identity is None or mirror_entry is None:
            continue
        legacy = str(identity.get("legacy_id", ""))
        name = str(identity.get("name", ""))
        canonical_entry = canonical.get(legacy)
        if canonical_entry is None:
            continue

        target_legacy = str(target.get("legacy_id", ""))
        target_name = str(target.get("name", ""))
        target_country = str(target.get("country_prefix", ""))
        identity_country = country_prefix_from_legacy(legacy)
        if target_legacy != legacy:
            issue = compact_issue(pid, name, legacy, f"target legacy_id={target_legacy!r} != identity legacy_id={legacy!r}")
            metadata_mismatch.append(issue)
            hard.append(issue)
        if target_name != name:
            issue = compact_issue(pid, name, legacy, f"target name={target_name!r} != identity name={name!r}")
            metadata_mismatch.append(issue)
            hard.append(issue)
        if target_country and identity_country and target_country != identity_country:
            issue = compact_issue(pid, name, legacy, f"target country_prefix={target_country!r} != legacy prefix={identity_country!r}")
            metadata_mismatch.append(issue)
            hard.append(issue)

        if geometry_hash(canonical_entry) != geometry_hash(mirror_entry):
            issue = compact_issue(pid, name, legacy, "canonical legacy geometry != numeric mirror geometry")
            geometry_copy_mismatch.append(issue)
            hard.append(issue)

        raw = raw_geometry(mirror_entry)
        raw_valid = (not raw.is_empty) and raw.is_valid
        validity_reason = "" if raw_valid else ("empty" if raw.is_empty else explain_validity(raw))
        if not raw_valid:
            invalid_raw.append(compact_issue(pid, name, legacy, validity_reason))
        geom = repaired_geometry(mirror_entry)
        if geom.is_empty:
            hard.append(compact_issue(pid, name, legacy, "geometry empty after repair"))
            continue

        stored_area = float(target.get("area_km2", 0.0))
        project_area = project_area_km2(geom)
        geod_area = geodesic_area_km2(geom)
        stored_vs_project_pct = percent_error(stored_area, project_area)
        project_vs_geod_pct = percent_error(project_area, geod_area)
        if stored_vs_project_pct > 0.01 and abs(stored_area - project_area) > 0.1:
            stored_recompute_mismatch.append({
                "province_id": pid,
                "legacy_id": legacy,
                "name": name,
                "stored_area_km2": stored_area,
                "recomputed_project_area_km2": project_area,
                "error_pct": stored_vs_project_pct,
            })

        target_cells = int(target.get("target_cell_count", 0))
        current_class = split_class_by_id.get(pid, split_class(stored_area, target_cells))
        geod_class = split_class(geod_area, target_cells)
        bbox = bbox_from_rings(mirror_entry.get("rings", []))
        rep = geom.representative_point()
        lon, lat = world_to_lonlat(float(rep.x), float(rep.y))
        records.append({
            "province_id": pid,
            "legacy_id": legacy,
            "name": name,
            "country_prefix": target_country or identity_country,
            "target_cell_count": target_cells,
            "stored_area_km2": stored_area,
            "project_area_km2": project_area,
            "geodesic_area_km2": geod_area,
            "stored_vs_project_error_pct": stored_vs_project_pct,
            "project_vs_geodesic_error_pct": project_vs_geod_pct,
            "current_split_class": current_class,
            "geodesic_split_class": geod_class,
            "raw_geometry_valid": raw_valid,
            "raw_geometry_validity_reason": validity_reason,
            "geometry_part_count_after_repair": len(polygon_parts(geom)),
            "bbox_world_px": [round(x, 6) for x in bbox],
            "representative_lon": round(lon, 6),
            "representative_lat": round(lat, 6),
            "region_name": str(target.get("region_name", "")),
        })

    country_areas: dict[str, list[float]] = defaultdict(list)
    for r in records:
        if r["geodesic_area_km2"] > 0:
            country_areas[r["country_prefix"]].append(r["geodesic_area_km2"])
    country_medians = {c: statistics.median(v) for c, v in country_areas.items() if v}

    strong_outliers: list[dict[str, Any]] = []
    for r in records:
        median = country_medians.get(r["country_prefix"], 0.0)
        ratio = r["geodesic_area_km2"] / median if median > 0 else 0.0
        r["country_median_geodesic_area_km2"] = median
        r["country_area_ratio_to_median"] = ratio
        # Statistical review signal only.  The country-size floor avoids tiny
        # samples and the high ratio intentionally favors precision over recall.
        if len(country_areas.get(r["country_prefix"], [])) >= 6 and r["geodesic_area_km2"] >= 40_000.0 and ratio >= 8.0:
            strong_outliers.append(r)

    gt5 = [r for r in records if r["project_vs_geodesic_error_pct"] > 5.0]
    gt20 = [r for r in records if r["project_vs_geodesic_error_pct"] > 20.0]
    class_changes = [r for r in records if r["current_split_class"] != r["geodesic_split_class"]]

    strong_outlier_ids = {r["province_id"] for r in strong_outliers}
    gt20_ids = {r["province_id"] for r in gt20}
    class_change_ids = {r["province_id"] for r in class_changes}
    invalid_ids = {r["province_id"] for r in invalid_raw}
    hard_ids = {str(r.get("province_id", "")) for r in hard if str(r.get("province_id", ""))}

    split_review: list[dict[str, Any]] = []
    for r in records:
        if r["current_split_class"] != "split":
            continue
        reasons: list[str] = []
        pid = r["province_id"]
        if pid in hard_ids:
            reasons.append("hard_integrity")
        if pid in invalid_ids:
            reasons.append("invalid_raw_geometry")
        if pid in gt20_ids:
            reasons.append("project_vs_WGS84_gt20pct")
        if pid in class_change_ids:
            reasons.append("split_class_changes_with_WGS84")
        if pid in strong_outlier_ids:
            reasons.append("country_area_outlier_ge8x")
        if reasons:
            item = dict(r)
            item["review_reasons"] = reasons
            split_review.append(item)

    named = sorted((r for r in records if r["name"] in NAMED_DIAGNOSTICS), key=lambda r: r["name"])
    strong_outliers.sort(key=lambda r: (-r["country_area_ratio_to_median"], -r["geodesic_area_km2"], r["name"]))
    gt20.sort(key=lambda r: (-r["project_vs_geodesic_error_pct"], r["name"]))
    class_changes.sort(key=lambda r: (r["current_split_class"], r["geodesic_split_class"], r["country_prefix"], r["name"]))
    split_review.sort(key=lambda r: (-len(r["review_reasons"]), -r["country_area_ratio_to_median"], r["country_prefix"], r["name"]))

    safe = not hard and not split_review
    report = {
        "schema_version": 1,
        "format": "world_province_identity_geometry_audit/v1",
        "sources": {
            "targets": str(TARGETS_PATH.relative_to(ROOT)).replace("\\", "/"),
            "identities": str(IDENTITY_PATH.relative_to(ROOT)).replace("\\", "/"),
            "canonical_geometry": str(CANONICAL_PATH.relative_to(ROOT)).replace("\\", "/"),
            "numeric_geometry_mirror": str(MIRROR_PATH.relative_to(ROOT)).replace("\\", "/"),
            "split_candidate_audit": str(SPLIT_AUDIT_PATH.relative_to(ROOT)).replace("\\", "/"),
        },
        "policy": {
            "expected_records": EXPECTED,
            "geodesic_model": "WGS84 via pyproj.Geod",
            "current_project_area_recomputed_with_same_representative_latitude_scale": True,
            "geodesic_discrepancy_review_pct": 20.0,
            "country_area_outlier_min_country_records": 6,
            "country_area_outlier_min_geodesic_area_km2": 40_000.0,
            "country_area_outlier_ratio_to_country_median": 8.0,
            "outlier_is_diagnostic_not_auto_fix": True,
        },
        "summary": {
            "target_count": len(targets),
            "identity_count": len(identities_list),
            "canonical_count": len(canonical_list),
            "mirror_count": len(mirror_list),
            "audited_record_count": len(records),
            "hard_integrity_failure_count": len(hard),
            "metadata_mismatch_count": len(metadata_mismatch),
            "geometry_copy_mismatch_count": len(geometry_copy_mismatch),
            "invalid_raw_geometry_count": len(invalid_raw),
            "stored_area_recompute_mismatch_count": len(stored_recompute_mismatch),
            "geodesic_discrepancy_gt_5pct_count": len(gt5),
            "geodesic_discrepancy_gt_20pct_count": len(gt20),
            "split_classification_change_count": len(class_changes),
            "strong_country_area_outlier_count": len(strong_outliers),
            "split_candidates_requiring_review_count": len(split_review),
            "safe_to_proceed_with_split_candidates": safe,
        },
        "duplicate_ids": duplicate_summary,
        "hard_integrity_failures": hard[:500],
        "metadata_mismatches": metadata_mismatch[:500],
        "geometry_copy_mismatches": geometry_copy_mismatch[:500],
        "invalid_raw_geometries": invalid_raw[:500],
        "stored_area_recompute_mismatches": stored_recompute_mismatch[:500],
        "geodesic_discrepancy_gt_20pct": gt20[:500],
        "split_classification_changes": class_changes[:500],
        "strong_country_area_outliers": strong_outliers[:500],
        "split_candidates_requiring_review": split_review,
        "named_diagnostics": named,
        "notes": [
            "No source geometry or target count is modified.",
            "A country area outlier is a review signal, not proof of incorrect geography.",
            "If stored area exactly reproduces but WGS84 is sane, the project area approximation is the likely cause.",
            "If project and WGS84 both agree on an implausibly huge shape while metadata links are consistent, inspect the upstream identity-to-source-geometry pairing.",
        ],
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_MD.write_text(render_md(report), encoding="utf-8")
    print("WORLD_PROVINCE_IDENTITY_GEOMETRY_AUDIT", json.dumps(report["summary"], ensure_ascii=False))
    for r in named:
        print("NAMED_DIAGNOSTIC", json.dumps(r, ensure_ascii=False))

    if len(targets) != EXPECTED or len(identities_list) != EXPECTED or len(canonical_list) != EXPECTED or len(mirror_list) != EXPECTED:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
