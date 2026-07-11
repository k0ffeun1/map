"""Офлайн-препроцессинг: ГЛАВНЫЙ слой суша/море — простая бинарная маска
(суша/не суша), реальная береговая линия (Natural Earth ne_10m_land) с
вычетом крупных озёр (ne_10m_lakes, см. MIN_LAKE_AREA_KM2) — та же логика
очистки данных, что и в build_land_cells.py, но БЕЗ Voronoi-нарезки на
клетки и БЕЗ волнистости: это не игровые клетки, а фундамент, на который
дальше опираются остальные системы (клик "суша или море", генерация
провинций/клеток, движение юнитов и т.п. — см. TODO.md).

Независим от build_land_cells.py/build_continents.py (сам грузит и обрабатывает
исходники) — при этом использует ТЕ ЖЕ raw-данные Natural Earth
(scripts/tools/_work/ne_10m_land.geojson, ne_10m_lakes.geojson), что и они,
чтобы контур совпадал с остальными "реальными" слоями.

Не запускается в Godot — отдельный шаг подготовки данных. Результат:
assets/land_sea.json — тот же формат, что у остальных слоёв-клеток
({"world_px":...,"cells":[{"rings":...,"bbox":...}]}) — каждая запись это
кусок СУШИ; всё, что не покрыто ни одной записью, считается морем.
"""
import json, math, time

LAND_SRC = "scripts/tools/_work/ne_10m_land.geojson"
LAKES_SRC = "scripts/tools/_work/ne_10m_lakes.geojson"
OUT = "assets/land_sea.json"
WORLD_PX = 8192.0
R_KM = 6371.0

# Те же полярные пороги, что и в build_land_cells.py/build_continents.py/
# TileMapViewer.gd (~76N/~58S) — этот слой обрезается по той же полосе.
LAT_NORTH = 76.0
LAT_SOUTH = -58.0

# Тот же порог, что у build_land_cells.py — крупные озёра (Эйсселмер,
# Великие озёра, Ладога, Байкал...) не размечены дырками в ne_10m_land
# (только берег океана), без вычитания стали бы "сушей".
MIN_LAKE_AREA_KM2 = 15.0

# Лёгкое упрощение контура — этот слой про "суша/не суша" в целом, а не про
# точную детализацию отдельного залива; полная точность остаётся в
# ne_10m_land для тех, кому она нужна напрямую.
SIMPLIFY_TOLERANCE_DEG = 0.01

# Совсем мелкий мусор берега (< 1 км²) не нужен фундаментальному слою.
MIN_PIECE_AREA_KM2 = 1.0


def project(lon, lat):
    lat = max(-85.05112878, min(85.05112878, lat))
    x = (lon + 180.0) / 360.0 * WORLD_PX
    lat_rad = math.radians(lat)
    y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
    return (x, y)


def ring_area_km2_lonlat(ring):
    lats = [p[1] for p in ring]
    lat0 = math.radians(sum(lats) / len(lats))
    pts = []
    for lon, lat in ring:
        x = math.radians(lon) * math.cos(lat0) * R_KM
        y = math.radians(lat) * R_KM
        pts.append((x, y))
    a = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return abs(a) * 0.5


def _explode(geom) -> list:
    from shapely.geometry import Polygon, MultiPolygon, GeometryCollection
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    if isinstance(geom, GeometryCollection):
        out = []
        for g in geom.geoms:
            out.extend(_explode(g))
        return out
    return []


def _emit_cell(out_cells: list, ext: list, holes: list) -> None:
    """Добавляет клетку(и) из УЖЕ округлённых (0.01) координат ext/holes —
    округление само по себе может сделать контур самопересекающимся
    ("бабочка"), даже если геометрия до округления была валидна (тот же
    баг, что и в build_land_cells.py/_add_wavy_cell — рендерер Godot
    рисует на самопересечении лишний тёмный кусок вместо чистой заливки).
    Проверяем ПОСЛЕ округления и чиним buffer(0), при необходимости разбивая
    на несколько простых клеток."""
    from shapely.geometry import Polygon as ShPolygon, MultiPolygon

    try:
        poly = ShPolygon(ext, holes)
    except Exception:
        return
    if not poly.is_valid:
        poly = poly.buffer(0)
    pieces = list(poly.geoms) if isinstance(poly, MultiPolygon) else [poly]
    for piece in pieces:
        if piece.is_empty or piece.area < 0.01:
            continue
        piece_ext = [(round(x, 2), round(y, 2)) for x, y in piece.exterior.coords]
        if len(piece_ext) < 3:
            continue
        xs = [q[0] for q in piece_ext]
        ys = [q[1] for q in piece_ext]
        if (max(xs) - min(xs)) * (max(ys) - min(ys)) < 2.0:
            continue
        rings_out = [[[x, y] for x, y in piece_ext]]
        for hole in piece.interiors:
            hole_ring = [(round(x, 2), round(y, 2)) for x, y in hole.coords]
            if len(hole_ring) < 3:
                continue
            rings_out.append([[x, y] for x, y in hole_ring])
        out_cells.append({
            "rings": rings_out,
            "bbox": [min(xs), min(ys), max(xs), max(ys)],
        })


def main():
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union

    t0 = time.time()
    land_data = json.load(open(LAND_SRC, encoding="utf-8"))

    land_polys = []
    for f in land_data["features"]:
        geom = f["geometry"]
        parts = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for part in parts:
            if ring_area_km2_lonlat(part[0]) < MIN_PIECE_AREA_KM2:
                continue
            try:
                p = Polygon(part[0], part[1:])
                if not p.is_valid:
                    p = p.buffer(0)
                if not p.is_empty:
                    land_polys.append(p)
            except Exception:
                continue

    print(f"[{time.time()-t0:.1f}s] land pieces loaded: {len(land_polys)}")

    # Некоторые озёра — НЕ отдельная запись в ne_10m_lakes, а дырка, уже
    # встроенная прямо в береговую линию ne_10m_land (как Каспий, см.
    # build_continents.py/_load_land_holes; то же бывает у рифтовых озёр
    # Африки). Остров внутри такой дырки — самостоятельный кусок суши в
    # данных, никак не связанный с "вычитанием озера" (вычитать там нечего
    # — дырка уже есть) — раньше вылезал как оторванная клякса. Общее
    # решение: любой кусок суши, ЦЕЛИКОМ лежащий внутри дырки ДРУГОГО куска
    # — остров в озере, выбрасываем его вообще, независимо от источника.
    from shapely.strtree import STRtree
    water_holes = []
    for p in land_polys:
        for hole in p.interiors:
            try:
                hp = Polygon(hole)
                if not hp.is_valid:
                    hp = hp.buffer(0)
                if not hp.is_empty:
                    water_holes.append(hp)
            except Exception:
                continue
    if water_holes:
        tree = STRtree(water_holes)
        before = len(land_polys)
        filtered = []
        for p in land_polys:
            c = p.centroid
            is_island_in_hole = False
            for idx in tree.query(c):
                if water_holes[int(idx)].contains(c):
                    is_island_in_hole = True
                    break
            if not is_island_in_hole:
                filtered.append(p)
        land_polys = filtered
        print(f"[{time.time()-t0:.1f}s] dropped islands sitting inside native "
              f"coastline holes (Caspian-like lakes): {before - len(land_polys)}")

    # ТОЛЬКО внешний контур озера (part[0]) — дырки-острова (part[1:])
    # намеренно отбрасываются: это полигон для ВЫЧИТАНИЯ озера из суши, и
    # если оставить в нём дырки-острова, вычитание НЕ уберёт острова из
    # суши (они не входят в вычитаемую область) — они останутся отдельными
    # оторванными от материка кусочками суши прямо посреди озера (баг,
    # найден по чёрным "кляксам"-островам на Виктории и похожих озёрах).
    lake_polys = []
    try:
        lakes_data = json.load(open(LAKES_SRC, encoding="utf-8"))
        for f in lakes_data["features"]:
            geom = f["geometry"]
            parts = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
            for part in parts:
                if ring_area_km2_lonlat(part[0]) < MIN_LAKE_AREA_KM2:
                    continue
                try:
                    p = Polygon(part[0])
                    if not p.is_valid:
                        p = p.buffer(0)
                    if not p.is_empty:
                        lake_polys.append(p)
                except Exception:
                    continue
    except FileNotFoundError:
        print(f"WARNING: {LAKES_SRC} not found, lakes will NOT be excluded")

    print(f"[{time.time()-t0:.1f}s] lakes loaded (> {MIN_LAKE_AREA_KM2:.0f}km2): {len(lake_polys)}")

    land = unary_union(land_polys)
    if lake_polys:
        land = land.difference(unary_union(lake_polys))
    if not land.is_valid:
        land = land.buffer(0)

    crop_box = box(-180.0, LAT_SOUTH, 180.0, LAT_NORTH)
    land = land.intersection(crop_box)
    land = land.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)

    out_cells = []
    for p in _explode(land):
        if p.is_empty:
            continue
        ext_ll = list(p.exterior.coords)
        if len(ext_ll) < 3:
            continue
        ext = [project(lon, lat) for lon, lat in ext_ll]
        ext = [(round(x, 2), round(y, 2)) for x, y in ext]
        # Дырки (озёра/внутренние моря) — ОБЯЗАТЕЛЬНО отдельными кольцами,
        # не просто отбрасывать: рендерер (IrregularCellProvider.gd) красит
        # rings[1..] как дырки чётно-нечётным правилом, без них озеро
        # закрашивается как суша (см. TODO.md).
        holes = []
        for hole in p.interiors:
            hole_ll = list(hole.coords)
            if len(hole_ll) < 3:
                continue
            hole_ring = [project(lon, lat) for lon, lat in hole_ll]
            hole_ring = [(round(x, 2), round(y, 2)) for x, y in hole_ring]
            holes.append(hole_ring)
        _emit_cell(out_cells, ext, holes)

    print(f"[{time.time()-t0:.1f}s] land pieces after union/crop/simplify: {len(out_cells)}")

    json.dump({"world_px": WORLD_PX, "cells": out_cells},
              open(OUT, "w", encoding="utf-8"), separators=(",", ":"))
    print(f"[{time.time()-t0:.1f}s] wrote {OUT}")


if __name__ == "__main__":
    main()
