"""Dissolve Spanish and Portuguese provinces from assets/provinces_iberia.json
into historical-game regions for the interactive `I` layer.

The source layer intentionally contains the wider Iberia bbox, including
southern France and North Africa. This generator keeps only the Iberian
province names we explicitly map below, then uses Shapely unary_union to
remove internal province borders inside each region.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union


SRC = Path("assets/provinces_iberia.json")
OUT = Path("assets/regions_iberia.json")

REGION_BY_PROVINCE = {
    "La Coruña": "Галисия",
    "Lugo": "Галисия",
    "Orense": "Галисия",
    "Pontevedra": "Галисия",
    "Asturias": "Астурия",
    "Cantabria": "Кантабрийско-Баскское побережье",
    "Bizkaia": "Кантабрийско-Баскское побережье",
    "Gipuzkoa": "Кантабрийско-Баскское побережье",
    "Álava": "Кантабрийско-Баскское побережье",
    "Navarra": "Наварра",
    "León": "Леон",
    "Zamora": "Леон",
    "Salamanca": "Леон",
    "Burgos": "Старая Кастилия",
    "Palencia": "Старая Кастилия",
    "Valladolid": "Старая Кастилия",
    "Segovia": "Старая Кастилия",
    "Soria": "Старая Кастилия",
    "Ávila": "Старая Кастилия",
    "La Rioja": "Старая Кастилия",
    "Madrid": "Новая Кастилия",
    "Toledo": "Новая Кастилия",
    "Guadalajara": "Новая Кастилия",
    "Cuenca": "Новая Кастилия",
    "Ciudad Real": "Ла-Манча",
    "Albacete": "Ла-Манча",
    "Badajoz": "Эстремадура",
    "Cáceres": "Эстремадура",
    "Huesca": "Арагон",
    "Zaragoza": "Арагон",
    "Teruel": "Арагон",
    "Barcelona": "Каталония",
    "Gerona": "Каталония",
    "Lérida": "Каталония",
    "Tarragona": "Каталония",
    "Castellón": "Валенсия",
    "Valencia": "Валенсия",
    "Alicante": "Валенсия",
    "Murcia": "Мурсия",
    "Córdoba": "Верхняя Андалусия",
    "Jaén": "Верхняя Андалусия",
    "Granada": "Верхняя Андалусия",
    "Almería": "Верхняя Андалусия",
    "Sevilla": "Нижняя Андалусия",
    "Cádiz": "Нижняя Андалусия",
    "Huelva": "Нижняя Андалусия",
    "Málaga": "Нижняя Андалусия",
    "Baleares": "Балеарские острова",
    "Viana do Castelo": "Минью",
    "Braga": "Минью",
    "Porto": "Минью",
    "Vila Real": "Траз-уш-Монтиш",
    "Bragança": "Траз-уш-Монтиш",
    "Aveiro": "Бейра-Литорал",
    "Coimbra": "Бейра-Литорал",
    "Viseu": "Бейра-Интериор",
    "Guarda": "Бейра-Интериор",
    "Castelo Branco": "Бейра-Интериор",
    "Leiria": "Эштремадура-и-Рибатежу",
    "Lisboa": "Эштремадура-и-Рибатежу",
    "Santarém": "Эштремадура-и-Рибатежу",
    "Setúbal": "Эштремадура-и-Рибатежу",
    "Portalegre": "Алентежу",
    "Évora": "Алентежу",
    "Beja": "Алентежу",
    "Faro": "Алгарве",
}

REGION_COLORS = {
    "Галисия": [0.20, 0.56, 0.74, 0.42],
    "Астурия": [0.30, 0.62, 0.42, 0.42],
    "Кантабрийско-Баскское побережье": [0.16, 0.46, 0.34, 0.42],
    "Наварра": [0.70, 0.45, 0.28, 0.42],
    "Леон": [0.62, 0.50, 0.22, 0.42],
    "Старая Кастилия": [0.77, 0.62, 0.34, 0.42],
    "Новая Кастилия": [0.72, 0.46, 0.38, 0.42],
    "Ла-Манча": [0.66, 0.67, 0.36, 0.42],
    "Эстремадура": [0.45, 0.54, 0.27, 0.42],
    "Арагон": [0.74, 0.36, 0.30, 0.42],
    "Каталония": [0.56, 0.33, 0.67, 0.42],
    "Валенсия": [0.88, 0.55, 0.24, 0.42],
    "Мурсия": [0.82, 0.42, 0.22, 0.42],
    "Верхняя Андалусия": [0.58, 0.36, 0.25, 0.42],
    "Нижняя Андалусия": [0.80, 0.48, 0.25, 0.42],
    "Балеарские острова": [0.34, 0.58, 0.80, 0.42],
    "Минью": [0.24, 0.62, 0.50, 0.42],
    "Траз-уш-Монтиш": [0.48, 0.52, 0.34, 0.42],
    "Бейра-Литорал": [0.26, 0.52, 0.68, 0.42],
    "Бейра-Интериор": [0.56, 0.50, 0.32, 0.42],
    "Эштремадура-и-Рибатежу": [0.78, 0.58, 0.30, 0.42],
    "Алентежу": [0.52, 0.60, 0.35, 0.42],
    "Алгарве": [0.82, 0.50, 0.28, 0.42],
}


def clean_geometry(geom):
    """Drop zero-width spikes that are invisible in fill but visible in stroke."""
    # Natural Earth admin boundaries sometimes leave line-like whiskers after
    # dissolve. A tiny close/open pass removes those zero-area artifacts while
    # keeping the region outline visually in the same place at this map scale.
    cleaned = geom.buffer(0.25, join_style=2).buffer(-0.25, join_style=2)
    if cleaned.is_empty:
        return geom
    if not cleaned.is_valid:
        cleaned = cleaned.buffer(0)
    return cleaned if not cleaned.is_empty else geom


def clean_ring(coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Remove hairpin vertices where the exterior goes out and back."""
    if len(coords) < 4:
        return coords
    pts = list(coords)
    changed = True
    while changed and len(pts) >= 4:
        changed = False
        out = []
        n = len(pts)
        i = 0
        while i < n:
            prev = pts[(i - 1) % n]
            cur = pts[i]
            nxt = pts[(i + 1) % n]
            base = ((prev[0] - nxt[0]) ** 2 + (prev[1] - nxt[1]) ** 2) ** 0.5
            left = ((prev[0] - cur[0]) ** 2 + (prev[1] - cur[1]) ** 2) ** 0.5
            right = ((cur[0] - nxt[0]) ** 2 + (cur[1] - nxt[1]) ** 2) ** 0.5
            if base <= 0.75 and max(left, right) >= 1.5:
                changed = True
                i += 1
                continue
            out.append(cur)
            i += 1
        pts = out
    return pts


def slugify(value: str) -> str:
    table = str.maketrans({
        "Г": "g", "А": "a", "К": "k", "Н": "n", "Л": "l", "М": "m",
        "С": "s", "Э": "e", "В": "v", "Б": "b", "а": "a", "б": "b",
        "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z",
        "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
        "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
        "ы": "y", "э": "e", "ю": "yu", "я": "ya", "ь": "", "ъ": "",
    })
    out = value.translate(table).lower()
    out = re.sub(r"[^a-z0-9]+", "_", out).strip("_")
    return out or "region"


def polygon_from_cell(cell: dict) -> Polygon | None:
    rings = cell.get("brd", cell.get("rings", []))
    if not rings or len(rings[0]) < 3:
        return None
    poly = Polygon(rings[0], rings[1:])
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty:
        return None
    return poly


def polygon_to_cell(region_name: str, geom) -> list[dict]:
    geoms = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    cells = []
    for idx, poly in enumerate(geoms):
        if poly.is_empty or poly.area <= 0.0001:
            continue
        minx, miny, maxx, maxy = poly.bounds
        # Natural Earth admin-1 pieces leave tiny topological gaps after
        # dissolve. For this gameplay overlay those holes are noise: if we
        # keep them, IrregularCellProvider correctly outlines every interior
        # ring and the map gets random black scratches inside regions.
        exterior = clean_ring(list(poly.exterior.coords[:-1]))
        rings = [
            [[round(x, 2), round(y, 2)] for x, y in exterior]
        ]
        suffix = "" if len(geoms) == 1 else "_%02d" % idx
        cells.append({
            "id": "%s%s" % (slugify(region_name), suffix),
            "name": region_name,
            "color_key": region_name,
            "color": REGION_COLORS[region_name],
            "rings": rings,
            "bbox": [round(minx, 2), round(miny, 2), round(maxx, 2), round(maxy, 2)],
        })
    return cells


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    grouped: dict[str, list[Polygon]] = {}
    skipped = []

    for cell in data.get("cells", []):
        name = cell.get("name", "")
        region = REGION_BY_PROVINCE.get(name)
        if region is None:
            skipped.append(name)
            continue
        poly = polygon_from_cell(cell)
        if poly is not None:
            grouped.setdefault(region, []).append(poly)

    out_cells = []
    for region_name in REGION_COLORS:
        pieces = grouped.get(region_name, [])
        if not pieces:
            print("warning: no pieces for", region_name)
            continue
        dissolved = clean_geometry(unary_union(pieces))
        if not dissolved.is_valid:
            dissolved = clean_geometry(dissolved.buffer(0))
        out_cells.extend(polygon_to_cell(region_name, dissolved))

    OUT.write_text(json.dumps({
        "world_px": data.get("world_px", 8192.0),
        "source": str(SRC),
        "cells": out_cells,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print("regions:", len(grouped), "cells:", len(out_cells), "written:", OUT)
    print("skipped non-Iberian/foreign province cells:", len(skipped))


if __name__ == "__main__":
    main()
