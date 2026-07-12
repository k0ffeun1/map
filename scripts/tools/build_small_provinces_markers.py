"""Диагностический слой поверх слоя "8" (assets/provinces.json): точки на
всех провинциях площадью < AREA_THRESHOLD_KM2 с подписанной площадью —
чекбокс "< 300 км²" в панели слоя 8 (TileMapViewer.gd,
SmallProvinceMarkersLayer/SmallProvinceMarkerNode). Не тайловый слой (см.
ProvinceCityMarkersLayer.gd) — векторные узлы, площадь посчитана здесь один
раз офлайн, в рантайме только читается.

Площадь — той же геодезической формулой, что и живой слой "8"
(IrregularCellProvider._rings_area_km2/_ring_signed_area_km2): локальная
эквидистантная проекция вокруг средней широты кольца, EARTH_RADIUS_KM.
Точка маркера — representative_point() (shapely) вместо центроида: центроид
у вытянутых/вогнутых провинций может оказаться ЗА пределами полигона (напр.
у полумесяца), representative_point гарантированно внутри.

"id" клетки — тот же fallback "province_%04d" по порядковому индексу, что и
в IrregularCellProvider._load_data (там же используется, когда в JSON нет
поля "id" — сейчас в provinces.json такого поля нет вообще, см. сессию
2026-07-12), чтобы клик по этой же провинции на живом слое 8 показывал тот
же id, что и подпись здесь.
"""
import json
import math

from shapely.geometry import Polygon

SRC = "assets/provinces.json"
OUT = "assets/small_provinces_markers.json"
WORLD_PX = 8192.0
EARTH_RADIUS_KM = 6371.0088
AREA_THRESHOLD_KM2 = 300.0


def world_px_to_lonlat(x: float, y: float) -> tuple:
    lon = x / WORLD_PX * 360.0 - 180.0
    n = math.pi - 2.0 * math.pi * y / WORLD_PX
    lat = math.degrees(math.atan(math.sinh(n)))
    return lon, lat


def ring_area_km2(points: list) -> float:
    if len(points) < 3:
        return 0.0
    lonlat = [world_px_to_lonlat(x, y) for x, y in points]
    lat0 = math.radians(sum(p[1] for p in lonlat) / len(lonlat))
    pts_km = [(math.radians(lon) * math.cos(lat0) * EARTH_RADIUS_KM,
               math.radians(lat) * EARTH_RADIUS_KM) for lon, lat in lonlat]
    s = 0.0
    n = len(pts_km)
    for i in range(n):
        ax, ay = pts_km[i]
        bx, by = pts_km[(i + 1) % n]
        s += ax * by - bx * ay
    return abs(s) * 0.5


def rings_area_km2(rings: list) -> float:
    if not rings:
        return 0.0
    total = ring_area_km2(rings[0])
    for hole in rings[1:]:
        total -= ring_area_km2(hole)
    return max(0.0, total)


def main() -> None:
    cells = json.load(open(SRC, encoding="utf-8"))["cells"]
    markers = []
    for idx, c in enumerate(cells):
        rings = c.get("rings", [])
        if not rings or len(rings[0]) < 3:
            continue
        area = rings_area_km2(rings)
        if area >= AREA_THRESHOLD_KM2:
            continue
        cell_id = str(c.get("id", "") or f"province_{idx:04d}")
        try:
            poly = Polygon(rings[0], rings[1:])
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty:
                continue
            rp = poly.representative_point()
        except Exception:
            continue
        markers.append({
            "id": cell_id,
            "name": c.get("name", ""),
            "pos": [round(rp.x, 1), round(rp.y, 1)],
            "area_km2": round(area, 1),
        })

    json.dump({"markers": markers}, open(OUT, "w", encoding="utf-8"),
               ensure_ascii=False, separators=(",", ":"))
    print(f"провинций < {AREA_THRESHOLD_KM2:.0f} км^2: {len(markers)}, записано {OUT}")


if __name__ == "__main__":
    main()
