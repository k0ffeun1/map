"""Экспорт четырёх фиксированных тестовых геометрий для ручной серии
итераций генератора сухопутных клеток.

Скрипт ничего не меняет в основных данных проекта. Он читает актуальные
assets/provinces.json, assets/game_data/provinces.json и
assets/province_cities_iberia.json, фиксирует геометрию Ла-Коруньи,
Большого Лондона, Бретани и главного острова Сицилия и пишет компактные
JSON в manual_land_cell_iterations/fixed_test_geometry.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path

from shapely.geometry import MultiPolygon, Point, Polygon, mapping
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
LEGACY_PATH = ROOT / "assets/provinces.json"
GAME_DATA_PATH = ROOT / "assets/game_data/provinces.json"
CITY_PATH = ROOT / "assets/province_cities_iberia.json"
OUT_DIR = ROOT / "manual_land_cell_iterations/fixed_test_geometry"
WORLD_PX = 8192.0


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", " ", value).strip()


def project(lon: float, lat: float) -> tuple[float, float]:
    lat = max(-85.05112878, min(85.05112878, lat))
    x = (lon + 180.0) / 360.0 * WORLD_PX
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) * 0.5 * WORLD_PX
    return x, y


def cell_geom(cell: dict):
    rings = cell.get("rings") or []
    if not rings:
        raise ValueError(f"У провинции {cell.get('name')} нет rings")
    geom = Polygon(rings[0], rings[1:])
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom


def largest_polygon(geom):
    if geom.geom_type == "Polygon":
        return geom
    if geom.geom_type == "MultiPolygon":
        return max(geom.geoms, key=lambda g: g.area)
    polys = [g for g in getattr(geom, "geoms", []) if g.geom_type == "Polygon"]
    if not polys:
        raise ValueError(f"Нет полигональной части: {geom.geom_type}")
    return max(polys, key=lambda g: g.area)


def rings_from_geom(geom) -> list:
    geom = largest_polygon(geom)
    rings = [[[round(x, 6), round(y, 6)] for x, y in geom.exterior.coords]]
    for hole in geom.interiors:
        rings.append([[round(x, 6), round(y, 6)] for x, y in hole.coords])
    return rings


def load_sources():
    legacy = json.loads(LEGACY_PATH.read_text(encoding="utf-8"))
    game = json.loads(GAME_DATA_PATH.read_text(encoding="utf-8"))
    cities = json.loads(CITY_PATH.read_text(encoding="utf-8"))
    by_legacy = {p.get("legacy_id"): p for p in game.get("provinces", [])}
    return legacy, by_legacy, cities


def describe(cell: dict, by_legacy: dict) -> dict:
    passport = by_legacy.get(cell.get("id"), {})
    return {
        "source_legacy_id": cell.get("id", ""),
        "source_id": passport.get("id", ""),
        "source_numeric_id": passport.get("numeric_id"),
        "source_name": cell.get("name", ""),
        "source_slug": passport.get("slug", ""),
    }


def choose_single(cells: list[dict], by_legacy: dict, aliases: list[str], label: str) -> dict:
    alias_norms = [norm(a) for a in aliases]
    matches = []
    for cell in cells:
        passport = by_legacy.get(cell.get("id"), {})
        hay = " | ".join([
            norm(cell.get("name", "")),
            norm(cell.get("id", "")),
            norm(passport.get("name", "")),
            norm(passport.get("slug", "")),
            norm(passport.get("display_name_ru", "")),
        ])
        if any(a and a in hay for a in alias_norms):
            matches.append(cell)
    if not matches:
        raise RuntimeError(f"Не найдена тестовая территория: {label}; aliases={aliases}")
    # При дубликатах берём крупнейшую геометрию, но сохраняем все совпадения в evidence.
    matches.sort(key=lambda c: cell_geom(c).area, reverse=True)
    return matches[0]


def choose_group(cells: list[dict], by_legacy: dict, aliases: list[str], label: str) -> list[dict]:
    alias_norms = [norm(a) for a in aliases]
    selected = []
    for cell in cells:
        passport = by_legacy.get(cell.get("id"), {})
        fields = [
            norm(cell.get("name", "")),
            norm(cell.get("id", "")),
            norm(passport.get("name", "")),
            norm(passport.get("slug", "")),
            norm(passport.get("display_name_ru", "")),
        ]
        if any(any(a == f or a in f for f in fields) for a in alias_norms):
            selected.append(cell)
    if not selected:
        raise RuntimeError(f"Не найдена группа: {label}; aliases={aliases}")
    # Удаляем случайные дубликаты legacy id.
    unique = {}
    for c in selected:
        unique[c.get("id")] = c
    return list(unique.values())


def city_from_file(cities: dict, city_name: str) -> tuple[float, float]:
    target = norm(city_name)
    for c in cities.get("cities", []):
        if norm(c.get("name", "")) == target:
            return float(c["pos"][0]), float(c["pos"][1])
    raise RuntimeError(f"Город {city_name} не найден в {CITY_PATH}")


def write_fixed(filename: str, territory_id: str, display_name: str, geom, city_pos,
                n_cells: int, evidence: list[dict], selection_rule: str) -> dict:
    geom = largest_polygon(geom)
    city = Point(city_pos)
    city_adjustment = None
    if not geom.contains(city):
        nearest = geom.representative_point()
        city_adjustment = {
            "reason": "исходная точка оказалась вне зафиксированного полигона",
            "original": [round(city.x, 6), round(city.y, 6)],
        }
        city = nearest
    minx, miny, maxx, maxy = geom.bounds
    payload = {
        "schema_version": 1,
        "territory_id": territory_id,
        "display_name": display_name,
        "world_px": WORLD_PX,
        "required_cell_count": n_cells,
        "rings": rings_from_geom(geom),
        "bbox": [round(minx, 6), round(miny, 6), round(maxx, 6), round(maxy, 6)],
        "city": {
            "pos": [round(city.x, 6), round(city.y, 6)],
            "inside": bool(geom.contains(city)),
            "adjustment": city_adjustment,
        },
        "source": {
            "repository": "k0ffeun1/map",
            "branch": "master",
            "legacy_geometry_file": "assets/provinces.json",
            "passport_file": "assets/game_data/provinces.json",
            "selection_rule": selection_rule,
            "members": evidence,
        },
    }
    path = OUT_DIR / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    legacy, by_legacy, cities = load_sources()
    cells = legacy["cells"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    la = choose_single(cells, by_legacy,
                       ["La Coruña", "A Coruña", "Coruna", "province:2848"],
                       "Ла-Корунья")
    london = choose_single(cells, by_legacy,
                           ["Большой Лондон", "Greater London", "province:4026"],
                           "Большой Лондон")

    brittany_members = choose_group(
        cells, by_legacy,
        ["Finistère", "Côtes-d'Armor", "Cotes d Armor", "Morbihan",
         "Ille-et-Vilaine", "Ille et Vilaine", "Loire-Atlantique",
         "Loire Atlantique"],
        "Бретань",
    )
    sicily_members = choose_group(
        cells, by_legacy,
        ["Sicilia", "Sicily", "Palermo", "Messina", "Catania", "Siracusa",
         "Agrigento", "Trapani", "Enna", "Caltanissetta", "Ragusa"],
        "Сицилия",
    )

    brittany_geom = unary_union([cell_geom(c) for c in brittany_members]).buffer(0)
    sicily_geom = largest_polygon(unary_union([cell_geom(c) for c in sicily_members]).buffer(0))

    results = {}
    results["la_coruna"] = write_fixed(
        "la_coruna.json", "test:la_coruna", "Ла-Корунья", cell_geom(la),
        city_from_file(cities, "Ла-Корунья"), 4, [describe(la, by_legacy)],
        "крупнейшее совпадение La Coruña/A Coruña/Coruna; приоритет актуального legacy polygon",
    )
    results["london"] = write_fixed(
        "london.json", "test:london", "Большой Лондон", cell_geom(london),
        project(-0.1276, 51.5072), 5, [describe(london, by_legacy)],
        "готовый объединённый полигон Greater London из MERGE_GROUPS build_provinces.py",
    )
    results["brittany"] = write_fixed(
        "brittany.json", "test:brittany", "Бретань", brittany_geom,
        project(-1.6778, 48.1173), 6,
        [describe(c, by_legacy) for c in brittany_members],
        "unary_union историко-географической Бретани: Finistère, Côtes-d'Armor, Morbihan, Ille-et-Vilaine, Loire-Atlantique",
    )
    results["sicily"] = write_fixed(
        "sicily.json", "test:sicily", "Сицилия", sicily_geom,
        project(13.3615, 38.1157), 6,
        [describe(c, by_legacy) for c in sicily_members],
        "unary_union совпадений Сицилии с последующим выбором крупнейшей связной части — главного острова",
    )

    summary = {
        "schema_version": 1,
        "files": list(results),
        "selected": {
            key: {
                "display_name": value["display_name"],
                "required_cell_count": value["required_cell_count"],
                "bbox": value["bbox"],
                "city": value["city"],
                "members": value["source"]["members"],
            }
            for key, value in results.items()
        },
    }
    (OUT_DIR / "SELECTION_REPORT.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
