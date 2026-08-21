"""Черновая мировая регионализация поверх финального слоя провинций (старый слой 8).

Цель этапа:
- НЕ менять утверждённые провинции;
- сохранить точную ручную Иберию;
- для остального мира построить полный кандидат province -> region;
- геометрия региона получается dissolve/union уже готовых провинций слоя 8;
- сомнительные назначения не прячутся, а попадают в отчёт.

Мировые названия регионов берутся из таблицы пользователя через
assets/game_data/world_region_seeds_draft.txt. Координаты в этом файле —
только опорные точки для первого массового черновика. Это не окончательная
историческая таксономия.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

WORLD_PX = 8192.0
GEOMETRY_PATH = Path("assets/provinces.json")
PASSPORTS_PATH = Path("assets/game_data/provinces.json")
IBERIA_REGIONS_PATH = Path("assets/game_data/regions.json")
IBERIA_MAPPING_SCRIPT = Path("scripts/tools/build_regions_iberia.py")
SEEDS_PATH = Path("assets/game_data/world_region_seeds_draft.txt")

OUT_GEOMETRY = Path("assets/regions_world_draft.json")
OUT_ASSIGNMENTS = Path("assets/game_data/world_region_assignments_draft.json")
OUT_REPORT = Path("reports/world_regions_draft_report.json")

IBERIA_SPECIAL_BY_NAME = {
    "Andorra la Vella": ("region:iberia:catalonia", "Каталония", "iberia_special_attach"),
    "Gibraltar": ("region:iberia:lower_andalusia", "Нижняя Андалусия", "iberia_special_attach"),
    "Canarias": ("region:iberia:canary_islands", "Канарские острова", "iberia_special_region"),
    "Canary Islands": ("region:iberia:canary_islands", "Канарские острова", "iberia_special_region"),
    "Madeira": ("region:iberia:madeira", "Мадейра", "iberia_special_region"),
    "Azores": ("region:iberia:azores", "Азорские острова", "iberia_special_region"),
    "Açores": ("region:iberia:azores", "Азорские острова", "iberia_special_region"),
    "Ceuta": ("region:iberia:ceuta_melilla", "Сеута и Мелилья", "iberia_special_region"),
    "Melilla": ("region:iberia:ceuta_melilla", "Сеута и Мелилья", "iberia_special_region"),
}

NAME_FORCED_REGION = {
    "Greenland": ("region:world:arkticheskaia_kanada", "Арктическая Канада"),
    "Iceland": ("region:world:severnaia_skandinaviia", "Северная Скандинавия"),
    "Faroe Islands": ("region:world:severnaia_skandinaviia", "Северная Скандинавия"),
    "Falkland Islands": ("region:world:patagoniia", "Патагония"),
}


def slugify(value: str) -> str:
    table = str.maketrans({
        "А":"a","Б":"b","В":"v","Г":"g","Д":"d","Е":"e","Ё":"e","Ж":"zh","З":"z","И":"i","Й":"y",
        "К":"k","Л":"l","М":"m","Н":"n","О":"o","П":"p","Р":"r","С":"s","Т":"t","У":"u","Ф":"f",
        "Х":"h","Ц":"c","Ч":"ch","Ш":"sh","Щ":"sch","Ы":"y","Э":"e","Ю":"yu","Я":"ya","Ь":"","Ъ":"",
        "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z","и":"i","й":"y",
        "к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f",
        "х":"h","ц":"c","ч":"ch","ш":"sh","щ":"sch","ы":"y","э":"e","ю":"yu","я":"ya","ь":"","ъ":"",
    })
    text = unicodedata.normalize("NFKD", value).translate(table).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "region"


def world_to_lonlat(x: float, y: float) -> tuple[float, float]:
    lon = (x / WORLD_PX) * 360.0 - 180.0
    merc_y = math.pi * (1.0 - 2.0 * y / WORLD_PX)
    lat = math.degrees(math.atan(math.sinh(merc_y)))
    return lon, lat


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(((lon2 - lon1 + 180.0) % 360.0) - 180.0)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r * math.asin(min(1.0, math.sqrt(a)))


def load_seeds() -> list[dict]:
    seeds = []
    seen_names = set()
    for raw in SEEDS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, lon_s, lat_s = line.split("|")
        name = name.strip()
        if name in seen_names:
            raise RuntimeError(f"duplicate world region seed name: {name}")
        seen_names.add(name)
        seeds.append({
            "name": name,
            "region_id": f"region:world:{slugify(name)}",
            "lon": float(lon_s),
            "lat": float(lat_s),
        })
    if len(seeds) != 273:
        raise RuntimeError(f"expected 273 world table region seeds, got {len(seeds)}")
    ids = [s["region_id"] for s in seeds]
    if len(ids) != len(set(ids)):
        raise RuntimeError("world region seed slug collision")
    return seeds


def load_iberia_mapping() -> tuple[dict[str, tuple[str, str]], set[str]]:
    spec = importlib.util.spec_from_file_location("build_regions_iberia", IBERIA_MAPPING_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Iberia region mapping")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    game_regions = json.loads(IBERIA_REGIONS_PATH.read_text(encoding="utf-8"))
    id_by_ru = {
        str(r.get("display_name_ru", "")): str(r.get("id", ""))
        for r in game_regions.get("regions", [])
        if str(r.get("display_name_ru", "")) and str(r.get("id", "")).startswith("region:iberia:")
    }

    out = {}
    missing = []
    for province_name, region_name in module.REGION_BY_PROVINCE.items():
        rid = id_by_ru.get(region_name)
        if not rid:
            missing.append(region_name)
            continue
        out[str(province_name)] = (rid, str(region_name))
    if missing:
        raise RuntimeError("missing Iberia stable region IDs: " + ", ".join(sorted(set(missing))))
    return out, set(id_by_ru.values())


def polygon_from_cell(cell: dict) -> Polygon | MultiPolygon | None:
    rings = cell.get("rings", cell.get("brd", []))
    if not isinstance(rings, list) or not rings or len(rings[0]) < 3:
        return None
    poly = Polygon(rings[0], rings[1:])
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty:
        return None
    return poly


def nearest_seed(lon: float, lat: float, seeds: list[dict]) -> tuple[dict, float, float]:
    ranked = sorted(
        ((haversine_km(lon, lat, s["lon"], s["lat"]), s) for s in seeds),
        key=lambda item: item[0],
    )
    first_d, first = ranked[0]
    second_d = ranked[1][0] if len(ranked) > 1 else first_d
    return first, first_d, second_d


def confidence_for(distance_km: float, second_km: float) -> tuple[str, float]:
    margin = max(0.0, (second_km - distance_km) / max(second_km, 1.0))
    if distance_km <= 220.0 and margin >= 0.12:
        return "high", margin
    if distance_km <= 500.0 and margin >= 0.06:
        return "medium", margin
    return "review", margin


def centroid_from_bbox(cell: dict) -> tuple[float, float, float, float]:
    bbox = cell.get("bbox", [])
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise RuntimeError(f"cell {cell.get('id')} missing bbox")
    x = (float(bbox[0]) + float(bbox[2])) * 0.5
    y = (float(bbox[1]) + float(bbox[3])) * 0.5
    lon, lat = world_to_lonlat(x, y)
    return x, y, lon, lat


def ring_points(poly: Polygon) -> list[list[list[float]]]:
    exterior = [[round(float(x), 2), round(float(y), 2)] for x, y in list(poly.exterior.coords)[:-1]]
    return [exterior]


def main() -> None:
    seeds = load_seeds()
    iberia_by_name, _iberia_region_ids = load_iberia_mapping()

    geometry_data = json.loads(GEOMETRY_PATH.read_text(encoding="utf-8"))
    passport_data = json.loads(PASSPORTS_PATH.read_text(encoding="utf-8"))

    geom_by_id = {str(c.get("id", "")): c for c in geometry_data.get("cells", []) if str(c.get("id", ""))}
    passports = passport_data.get("provinces", [])
    if len(passports) != 4027:
        print(f"warning: expected current 4027 passports, got {len(passports)}")

    assignments = []
    grouped_polys: dict[str, list] = defaultdict(list)
    region_names: dict[str, str] = {}
    region_methods: dict[str, set[str]] = defaultdict(set)
    province_ids_seen = set()
    missing_geometry = []

    for p in passports:
        province_id = str(p.get("id", ""))
        legacy_id = str(p.get("legacy_id", ""))
        name = str(p.get("name", ""))
        cell = geom_by_id.get(legacy_id)
        if cell is None:
            missing_geometry.append({"province_id": province_id, "legacy_id": legacy_id, "name": name})
            continue

        _x, _y, lon, lat = centroid_from_bbox(cell)
        method = "nearest_world_region_seed"
        distance_km = 0.0
        second_km = 0.0
        margin = 1.0
        confidence = "high"

        if name in iberia_by_name:
            region_id, region_name = iberia_by_name[name]
            method = "iberia_exact_mapping"
            confidence = "locked"
        elif name in IBERIA_SPECIAL_BY_NAME:
            region_id, region_name, method = IBERIA_SPECIAL_BY_NAME[name]
            confidence = "review" if method == "iberia_special_region" else "locked"
        elif name in NAME_FORCED_REGION:
            region_id, region_name = NAME_FORCED_REGION[name]
            method = "named_world_exception"
            confidence = "review"
        else:
            chosen, distance_km, second_km = nearest_seed(lon, lat, seeds)
            region_id = chosen["region_id"]
            region_name = chosen["name"]
            confidence, margin = confidence_for(distance_km, second_km)

        poly = polygon_from_cell(cell)
        if poly is None:
            missing_geometry.append({"province_id": province_id, "legacy_id": legacy_id, "name": name, "reason": "invalid_polygon"})
            continue

        grouped_polys[region_id].append(poly)
        region_names[region_id] = region_name
        region_methods[region_id].add(method)
        province_ids_seen.add(province_id)
        assignments.append({
            "province_id": province_id,
            "legacy_id": legacy_id,
            "name": name,
            "region_id": region_id,
            "region_name": region_name,
            "method": method,
            "centroid_lon": round(lon, 5),
            "centroid_lat": round(lat, 5),
            "seed_distance_km": round(distance_km, 1),
            "second_seed_distance_km": round(second_km, 1),
            "seed_margin": round(margin, 4),
            "confidence": confidence,
        })

    if missing_geometry:
        raise RuntimeError(f"world draft has {len(missing_geometry)} provinces without usable geometry")
    if len(assignments) != len(passports) or len(province_ids_seen) != len(passports):
        raise RuntimeError(f"assignment coverage incomplete: {len(assignments)}/{len(passports)}")

    out_cells = []
    region_stats = []
    for region_id in sorted(grouped_polys):
        unioned = unary_union(grouped_polys[region_id])
        if not unioned.is_valid:
            unioned = unioned.buffer(0)
        geoms = list(unioned.geoms) if isinstance(unioned, MultiPolygon) else [unioned]
        valid_parts = [g for g in geoms if isinstance(g, Polygon) and not g.is_empty and g.area > 1e-8]
        for part_index, poly in enumerate(valid_parts):
            minx, miny, maxx, maxy = poly.bounds
            out_cells.append({
                "id": f"{region_id}__part_{part_index:03d}",
                "region_id": region_id,
                "name": region_names[region_id],
                "rings": ring_points(poly),
                "bbox": [round(minx, 2), round(miny, 2), round(maxx, 2), round(maxy, 2)],
            })
        region_stats.append({
            "region_id": region_id,
            "name": region_names[region_id],
            "province_count": len(grouped_polys[region_id]),
            "polygon_part_count": len(valid_parts),
            "methods": sorted(region_methods[region_id]),
        })

    assignment_counts = defaultdict(int)
    for a in assignments:
        assignment_counts[a["region_id"]] += 1

    empty_seed_regions = [
        {"region_id": s["region_id"], "name": s["name"], "lon": s["lon"], "lat": s["lat"]}
        for s in seeds
        if assignment_counts[s["region_id"]] == 0
    ]
    review = [a for a in assignments if a["confidence"] == "review"]
    exact = [a for a in assignments if a["method"] == "iberia_exact_mapping"]
    multipart = sorted(
        [s for s in region_stats if s["polygon_part_count"] > 1],
        key=lambda s: (-s["polygon_part_count"], -s["province_count"], s["name"]),
    )
    worst = sorted(
        [a for a in assignments if a["method"] == "nearest_world_region_seed"],
        key=lambda a: (-a["seed_distance_km"], a["name"]),
    )[:100]

    OUT_GEOMETRY.write_text(json.dumps({
        "schema_version": 1,
        "format": "world_regions_draft/v1",
        "world_px": geometry_data.get("world_px", WORLD_PX),
        "source": str(GEOMETRY_PATH),
        "method": "dissolve_layer8_provinces_after_region_assignment",
        "province_count": len(assignments),
        "region_count": len(region_stats),
        "polygon_piece_count": len(out_cells),
        "cells": out_cells,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    OUT_ASSIGNMENTS.write_text(json.dumps({
        "schema_version": 1,
        "format": "world_region_assignments_draft/v1",
        "source_provinces": str(PASSPORTS_PATH),
        "source_geometry": str(GEOMETRY_PATH),
        "source_world_seed_catalog": str(SEEDS_PATH),
        "province_count": len(assignments),
        "assignments": assignments,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text(json.dumps({
        "schema_version": 1,
        "format": "world_regions_draft_report/v1",
        "province_count": len(assignments),
        "source_world_region_seed_count": len(seeds),
        "actual_region_count": len(region_stats),
        "polygon_piece_count": len(out_cells),
        "iberia_exact_assignment_count": len(exact),
        "review_assignment_count": len(review),
        "empty_world_table_region_count": len(empty_seed_regions),
        "empty_world_table_regions": empty_seed_regions,
        "multipart_region_count": len(multipart),
        "multipart_regions": multipart,
        "worst_seed_assignments": worst,
        "region_stats": region_stats,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        "WORLD_REGIONS_DRAFT",
        f"provinces={len(assignments)}",
        f"regions={len(region_stats)}",
        f"pieces={len(out_cells)}",
        f"iberia_locked={len(exact)}",
        f"review={len(review)}",
        f"empty_table_regions={len(empty_seed_regions)}",
        f"multipart_regions={len(multipart)}",
    )
    if empty_seed_regions:
        print("EMPTY_TABLE_REGIONS=" + "; ".join(r["name"] for r in empty_seed_regions))
    if worst:
        print("WORST_DISTANCE_KM=", worst[0]["seed_distance_km"], worst[0]["name"], "->", worst[0]["region_name"])


if __name__ == "__main__":
    main()
