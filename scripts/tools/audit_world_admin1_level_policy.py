#!/usr/bin/env python3
"""Audit Natural Earth Admin-1 level consistency without changing geometry.

Reads the clean source manifest and explicit level policy. Fine administrative
labels are review signals only. The report identifies countries/regions where
Natural Earth mixes coarse and fine administrative levels so explicit policies
can be added instead of heuristic area/neighbour merges.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "assets/game_data/world_admin1_source_manifest.json"
POLICY = ROOT / "assets/game_data/world_admin1_level_policy.json"
OUT_JSON = ROOT / "reports/world_admin1_level_policy_audit.json"
OUT_MD = ROOT / "reports/world_admin1_level_policy_audit.md"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def classify(total: int, fine: int) -> str:
    if fine == 0:
        return "coarse_clean"
    if fine == total:
        return "uniform_fine"
    ratio = fine / max(total, 1)
    if 0.05 <= ratio <= 0.95:
        return "mixed_level"
    return "fine_minor_or_dominant"


def main() -> None:
    manifest = load(MANIFEST)
    policy = load(POLICY)
    features = list(manifest.get("source_features", []))
    fine_labels = set(policy.get("fine_type_review_labels", []))

    by_country: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_country_region: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for f in features:
        by_country[str(f.get("admin", ""))].append(f)
        region = str(f.get("region", ""))
        if region:
            by_country_region[(str(f.get("admin", "")), region)].append(f)

    approved_matches = []
    for p in policy.get("explicit_aggregations", []):
        if p.get("status") != "approved":
            continue
        match = p.get("match", {})
        members = [f for f in features if all(str(f.get(k, "")) == str(v) for k, v in match.items())]
        approved_matches.append({
            "policy_id": p.get("policy_id"),
            "logical_admin1_id": p.get("logical_admin1_id"),
            "logical_name": p.get("logical_name"),
            "match": match,
            "source_feature_count": len(members),
            "fine_feature_count": sum(1 for f in members if str(f.get("type_en", "")) in fine_labels),
            "source_area_km2_sum": round(sum(float(f.get("geodesic_area_km2", 0.0)) for f in members), 3),
        })

    countries = []
    mixed = []
    fine_total = 0
    for country, items in by_country.items():
        types = Counter(str(f.get("type_en", "")) for f in items)
        fine_items = [f for f in items if str(f.get("type_en", "")) in fine_labels]
        fine_total += len(fine_items)
        c = classify(len(items), len(fine_items))
        row = {
            "admin": country,
            "source_feature_count": len(items),
            "fine_feature_count": len(fine_items),
            "fine_fraction": round(len(fine_items) / max(len(items), 1), 6),
            "classification": c,
            "type_en_counts": dict(types.most_common()),
            "total_source_area_km2": round(sum(float(f.get("geodesic_area_km2", 0.0)) for f in items), 3),
        }
        countries.append(row)
        if c == "mixed_level":
            mixed.append(row)

    region_candidates = []
    for (country, region), items in by_country_region.items():
        fine = [f for f in items if str(f.get("type_en", "")) in fine_labels]
        nonfine = [f for f in items if str(f.get("type_en", "")) not in fine_labels]
        if len(fine) < 2:
            continue
        region_candidates.append({
            "admin": country,
            "region": region,
            "source_feature_count": len(items),
            "fine_feature_count": len(fine),
            "nonfine_feature_count": len(nonfine),
            "type_en_counts": dict(Counter(str(f.get("type_en", "")) for f in items).most_common()),
            "source_area_km2_sum": round(sum(float(f.get("geodesic_area_km2", 0.0)) for f in items), 3),
            "is_already_covered_by_approved_policy": any(
                all(str(f.get(k, "")) == str(v) for k, v in x.get("match", {}).items())
                for x in policy.get("explicit_aggregations", []) if x.get("status") == "approved"
                for f in items[:1]
            ),
        })

    countries.sort(key=lambda x: (-x["fine_feature_count"], -x["source_feature_count"], x["admin"]))
    mixed.sort(key=lambda x: (-x["fine_feature_count"], -x["source_feature_count"], x["admin"]))
    region_candidates.sort(key=lambda x: (-x["fine_feature_count"], -x["source_feature_count"], x["admin"], x["region"]))

    summary = {
        "source_feature_count": len(features),
        "country_count": len(by_country),
        "fine_type_feature_count": fine_total,
        "coarse_clean_country_count": sum(1 for x in countries if x["classification"] == "coarse_clean"),
        "uniform_fine_country_count": sum(1 for x in countries if x["classification"] == "uniform_fine"),
        "mixed_level_country_count": len(mixed),
        "fine_minor_or_dominant_country_count": sum(1 for x in countries if x["classification"] == "fine_minor_or_dominant"),
        "region_group_review_candidate_count": len(region_candidates),
        "approved_explicit_aggregation_count": len(approved_matches),
        "approved_explicit_aggregation_source_feature_count": sum(x["source_feature_count"] for x in approved_matches),
        "automatic_merge_count": 0,
        "ready_for_blind_global_parent_generation": fine_total == 0,
    }

    report = {
        "schema_version": 1,
        "format": "world_admin1_level_policy_audit/v1",
        "summary": summary,
        "approved_policy_matches": approved_matches,
        "mixed_level_countries": mixed,
        "all_countries": countries,
        "region_group_review_candidates": region_candidates,
        "decision": {
            "default": "preserve_source_feature",
            "fine_type_action": "review_only",
            "automatic_area_or_neighbor_merge": "forbidden",
            "next_required_step": "add explicit country/region policies only where a source level is demonstrably inconsistent with the intended world Admin-1 layer",
        },
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Аудит уровней Natural Earth Admin-1",
        "",
        "> Ничего не объединяется автоматически. Это очередь для явных правил.",
        "",
        "## Итог",
        "",
        f"- Source features: **{summary['source_feature_count']}**.",
        f"- Countries: **{summary['country_count']}**.",
        f"- Fine-type features: **{summary['fine_type_feature_count']}**.",
        f"- Coarse-clean countries: **{summary['coarse_clean_country_count']}**.",
        f"- Uniform-fine countries: **{summary['uniform_fine_country_count']}**.",
        f"- Mixed-level countries: **{summary['mixed_level_country_count']}**.",
        f"- Minor/dominant-fine mixed edge cases: **{summary['fine_minor_or_dominant_country_count']}**.",
        f"- Region groups worth explicit review: **{summary['region_group_review_candidate_count']}**.",
        f"- Approved explicit aggregations: **{summary['approved_explicit_aggregation_count']}**.",
        "",
        "## Mixed-level countries",
        "",
        "| Country | Features | Fine | Share | Types |",
        "|---|---:|---:|---:|---|",
    ]
    for x in mixed:
        types = "; ".join(f"{k}:{v}" for k, v in list(x["type_en_counts"].items())[:8])
        lines.append(f"| {x['admin']} | {x['source_feature_count']} | {x['fine_feature_count']} | {x['fine_fraction']:.1%} | {types} |")
    lines += [
        "",
        "## Top region-level review candidates",
        "",
        "| Country | Region | Features | Fine | Non-fine | Approved |",
        "|---|---|---:|---:|---:|---|",
    ]
    for x in region_candidates[:100]:
        lines.append(f"| {x['admin']} | {x['region']} | {x['source_feature_count']} | {x['fine_feature_count']} | {x['nonfine_feature_count']} | {'yes' if x['is_already_covered_by_approved_policy'] else 'no'} |")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("WORLD_ADMIN1_LEVEL_POLICY_AUDIT", json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
