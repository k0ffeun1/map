"""Dissolve historical regions from assets/regions_iberia.json into zones.

This is the level above regions in УРОВНЕЙ_ТЕРРИТОРИЙ.md. The interactive
layer is bound to `O` in TileMapViewer.gd.
"""

from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from build_regions_iberia import clean_geometry, clean_ring, slugify


SRC = Path("assets/regions_iberia.json")
OUT = Path("assets/zones_iberia.json")

ZONE_BY_REGION = {
    "Галисия": "Галисийско-Астурийская зона",
    "Астурия": "Галисийско-Астурийская зона",
    "Леон": "Леонская зона",
    "Кантабрийско-Баскское побережье": "Баско-Кантабрийская зона",
    "Наварра": "Наварро-Пиренейская зона",
    "Старая Кастилия": "Старокастильская Месета",
    "Новая Кастилия": "Новокастильская Месета",
    "Ла-Манча": "Новокастильская Месета",
    "Эстремадура": "Эстремадурская зона",
    "Арагон": "Арагонская зона Эбро",
    "Каталония": "Каталонская зона",
    "Валенсия": "Валенсийско-Мурсийская зона",
    "Мурсия": "Валенсийско-Мурсийская зона",
    "Балеарские острова": "Балеарская зона",
    "Верхняя Андалусия": "Верхнеандалусская зона",
    "Нижняя Андалусия": "Нижнеандалусская зона",
    "Минью": "Северопортугальская зона",
    "Траз-уш-Монтиш": "Северопортугальская зона",
    "Бейра-Литорал": "Бейрская зона",
    "Бейра-Интериор": "Бейрская зона",
    "Эштремадура-и-Рибатежу": "Лиссабонско-Рибатежская зона",
    "Алентежу": "Алентежская зона",
    "Алгарве": "Алгарвская зона",
}

ZONE_COLORS = {
    "Галисийско-Астурийская зона": [0.18, 0.52, 0.58, 0.36],
    "Леонская зона": [0.48, 0.52, 0.30, 0.36],
    "Баско-Кантабрийская зона": [0.20, 0.46, 0.34, 0.36],
    "Наварро-Пиренейская зона": [0.56, 0.42, 0.24, 0.36],
    "Старокастильская Месета": [0.62, 0.54, 0.34, 0.36],
    "Новокастильская Месета": [0.66, 0.50, 0.34, 0.36],
    "Эстремадурская зона": [0.42, 0.54, 0.30, 0.36],
    "Арагонская зона Эбро": [0.70, 0.36, 0.30, 0.36],
    "Каталонская зона": [0.58, 0.36, 0.66, 0.36],
    "Валенсийско-Мурсийская зона": [0.82, 0.46, 0.24, 0.36],
    "Балеарская зона": [0.32, 0.56, 0.78, 0.36],
    "Верхнеандалусская зона": [0.58, 0.36, 0.24, 0.36],
    "Нижнеандалусская зона": [0.76, 0.46, 0.26, 0.36],
    "Северопортугальская зона": [0.22, 0.58, 0.48, 0.36],
    "Бейрская зона": [0.28, 0.52, 0.62, 0.36],
    "Лиссабонско-Рибатежская зона": [0.76, 0.58, 0.30, 0.36],
    "Алентежская зона": [0.50, 0.58, 0.34, 0.36],
    "Алгарвская зона": [0.82, 0.50, 0.28, 0.36],
}


def polygon_from_cell(cell: dict) -> Polygon | None:
    rings = cell.get("rings", [])
    if not rings or len(rings[0]) < 3:
        return None
    poly = Polygon(rings[0], rings[1:])
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty:
        return None
    return poly


def polygon_to_cells(zone_name: str, geom) -> list[dict]:
    geoms = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    cells = []
    for idx, poly in enumerate(geoms):
        if poly.is_empty or poly.area <= 0.0001:
            continue
        minx, miny, maxx, maxy = poly.bounds
        exterior = clean_ring(list(poly.exterior.coords[:-1]))
        suffix = "" if len(geoms) == 1 else "_%02d" % idx
        cells.append({
            "id": "%s%s" % (slugify(zone_name), suffix),
            "name": zone_name,
            "color_key": zone_name,
            "color": ZONE_COLORS[zone_name],
            "rings": [[[round(x, 2), round(y, 2)] for x, y in exterior]],
            "bbox": [round(minx, 2), round(miny, 2), round(maxx, 2), round(maxy, 2)],
        })
    return cells


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    grouped: dict[str, list[Polygon]] = {}
    skipped = []

    for cell in data.get("cells", []):
        region = cell.get("name", "")
        zone = ZONE_BY_REGION.get(region)
        if zone is None:
            skipped.append(region)
            continue
        poly = polygon_from_cell(cell)
        if poly is not None:
            grouped.setdefault(zone, []).append(poly)

    out_cells = []
    for zone_name in ZONE_COLORS:
        pieces = grouped.get(zone_name, [])
        if not pieces:
            print("warning: no pieces for", zone_name)
            continue
        dissolved = clean_geometry(unary_union(pieces))
        if not dissolved.is_valid:
            dissolved = clean_geometry(dissolved.buffer(0))
        out_cells.extend(polygon_to_cells(zone_name, dissolved))

    OUT.write_text(json.dumps({
        "world_px": data.get("world_px", 8192.0),
        "source": str(SRC),
        "cells": out_cells,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print("zones:", len(grouped), "cells:", len(out_cells), "written:", OUT)
    print("skipped regions:", len(skipped))


if __name__ == "__main__":
    main()
