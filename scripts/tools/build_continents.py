"""Офлайн-препроцессинг: контуры континентов из ГОТОВОГО картографического
датасета (Esri "World Continents", живой feature layer ArcGIS) — реальные
полигоны континентов, проведённые картографами по географическому принципу
(Урал/Кавказ, Суэц, Панама и т.д. уже учтены авторами датасета), а НЕ
самодельные прямоугольники и НЕ политические границы стран.

История вопроса (см. TODO.md "Иерархия географических слоёв" за подробностями):
  1) Первая версия красила по атрибуту CONTINENT у стран
     (ne_10m_admin_0_countries) — оказалось неверно (вся Россия одной
     страной с CONTINENT=Europe, вся Франция — с Французской Гвианой в ЮА
     туда же).
  2) Вторая версия делила реальную береговую линию (ne_10m_land) вручную
     нарисованными прямоугольниками (Урал/Кавказ, Суэц, Панама) — работало
     по смыслу, но швы прямоугольников были ВИДНЫ на карте (прямые
     искусственные линии поверх Казахстана/Каспия и Синая/Израиля).
  3) Эта версия — просто берёт готовые полигоны континентов Esri, без
     самодельной геометрии вообще.

Источник (публичный ArcGIS Living Atlas feature layer, живой запрос):
  https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/
  World_Continents/FeatureServer/0/query?where=1=1&outFields=*&f=geojson
  сохранён локально в scripts/tools/_work/world_continents_esri.geojson.
Esri держит "Australia" и "Oceania" отдельными континентами (8 всего) —
здесь объединяются в один индекс OCEANIA (см. CONTINENT_NAMES, 6 штук).

Не запускается в Godot — отдельный шаг подготовки данных (как build_land_cells.py/
build_sea_borders.py). Результат: assets/continents.json — тот же формат, что
у land_cells.json ({"world_px":...,"cells":[{"rings":...,"bbox":...,"cont":idx}]}),
плюс "names" (индекс -> название) на верхнем уровне.
"""
import json, math, time

SRC = "scripts/tools/_work/world_continents_esri.geojson"
# Esri "World Continents" не вырезает озёра дырками (Великие озёра/Байкал/
# Виктория и т.п. иначе красятся как суша) — вычитаем тем же источником, что и
# build_land_sea.py/build_land_cells.py. ОТДЕЛЬНО: Каспий в ne_10m_lakes НЕТ
# (Natural Earth считает его не озером, а "морем" и вырезает дыркой прямо в
# ne_10m_land) — берём такие дыры напрямую из береговой линии, см. _load_land_holes.
LAKES_SRC = "scripts/tools/_work/ne_10m_lakes.geojson"
LAND_SRC = "scripts/tools/_work/ne_10m_land.geojson"
OUT = "assets/continents.json"
WORLD_PX = 8192.0
R_KM = 6371.0

# Те же полярные пороги, что и в build_land_cells.py/TileMapViewer.gd (~76N/~58S).
LAT_NORTH = 76.0
LAT_SOUTH = -58.0

MIN_LAKE_AREA_KM2 = 15.0

SIMPLIFY_TOLERANCE_DEG = 0.02  # градусы lon/lat — лёгкое упрощение контура
CHAIKIN_ITERATIONS = 2  # сглаживание углов после simplify (см. chaikin_smooth)

CONTINENT_NAMES = ["Европа", "Азия", "Африка", "Северная Америка", "Южная Америка", "Океания"]
EUROPE, ASIA, AFRICA, N_AMERICA, S_AMERICA, OCEANIA = 0, 1, 2, 3, 4, 5

# Esri держит Australia/Oceania раздельно -> оба в наш единый индекс OCEANIA.
_NAME_MAP = {
    "Europe": EUROPE,
    "Asia": ASIA,
    "Africa": AFRICA,
    "North America": N_AMERICA,
    "South America": S_AMERICA,
    "Australia": OCEANIA,
    "Oceania": OCEANIA,
    # "Antarctica" сознательно не сопоставлена -> пропускается (южнее
    # LAT_SOUTH клеток/слоёв всё равно нет нигде в проекте).
}


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


def _load_lakes(path: str, min_area_km2: float) -> list:
    """Полигоны озёр — ТОЛЬКО внешний контур (part[0]), дырки-острова
    (part[1:]) намеренно отбрасываются: это полигон для ВЫЧИТАНИЯ озера из
    континента, и если оставить в нём дырки-острова, вычитание НЕ уберёт
    острова из континента (они не входят в вычитаемую область) — они
    останутся как отдельные оторванные от материка кусочки суши прямо
    посреди озера (баг, найден по чёрным "кляксам"-островам на Виктории и
    похожих озёрах). Сплошной контур озера убирает острова вместе с водой —
    то же решение, что и для lakes.json (острова внутри озёр не нужны)."""
    from shapely.geometry import Polygon
    try:
        data = json.load(open(path, encoding="utf-8"))
    except FileNotFoundError:
        print(f"WARNING: {path} not found, lakes will NOT be excluded")
        return []
    polys = []
    for f in data["features"]:
        geom = f["geometry"]
        parts = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for part in parts:
            if ring_area_km2_lonlat(part[0]) < min_area_km2:
                continue
            try:
                p = Polygon(part[0])
                if not p.is_valid:
                    p = p.buffer(0)
                if not p.is_empty:
                    polys.append(p)
            except Exception:
                continue
    return polys


def _load_land_holes(path: str, min_area_km2: float) -> list:
    """Дыры, УЖЕ вырезанные прямо в ne_10m_land (напр. Каспий — Natural Earth
    считает его морем, не озером, поэтому в ne_10m_lakes его нет, а из
    береговой линии он исключён напрямую). Общий, а не по имени "Каспий" —
    ловит любой похожий случай в датасете, а не только этот один."""
    from shapely.geometry import Polygon
    data = json.load(open(path, encoding="utf-8"))
    polys = []
    for f in data["features"]:
        geom = f["geometry"]
        parts = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for part in parts:
            for hole in part[1:]:
                if ring_area_km2_lonlat(hole) < min_area_km2:
                    continue
                try:
                    p = Polygon(hole)
                    if not p.is_valid:
                        p = p.buffer(0)
                    if not p.is_empty:
                        polys.append(p)
                except Exception:
                    continue
    return polys


def chaikin_smooth(ring: list, iterations: int = CHAIKIN_ITERATIONS, ratio: float = 0.25) -> list:
    """Сглаживание Чайкина (corner cutting) для ЗАМКНУТОГО кольца
    [(x,y), ..., (x0,y0)] — каждую итерацию каждое ребро p0->p1 заменяется
    двумя точками (на ratio и 1-ratio от ребра), острые углы simplify()
    скругляются без ухода геометрии от исходного контура (в отличие от
    сплайна, не может "перелететь" за пределы исходной ломаной). Работает в
    градусах lon/lat ДО проекции — сглаживание после Меркатора исказило бы
    форму сильнее у полюсов."""
    pts = ring[:-1]
    n = len(pts)
    if n < 3:
        return ring
    for _ in range(iterations):
        new_pts = []
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            new_pts.append((x0 + ratio * (x1 - x0), y0 + ratio * (y1 - y0)))
            new_pts.append((x0 + (1.0 - ratio) * (x1 - x0), y0 + (1.0 - ratio) * (y1 - y0)))
        pts = new_pts
        n = len(pts)
    pts.append(pts[0])
    return pts


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


def _emit_cell(out_cells: list, ext: list, holes: list, cont: int) -> None:
    """Добавляет клетку(и) из УЖЕ округлённых (0.01) координат ext/holes —
    округление само по себе может сделать контур самопересекающимся
    ("бабочка"), даже если геометрия до округления валидна (тот же баг, что
    в build_land_cells.py/_add_wavy_cell — рендерер Godot рисует на
    самопересечении лишний тёмный кусок вместо чистой заливки). Проверяем
    ПОСЛЕ округления и чиним buffer(0), при необходимости разбивая на
    несколько простых клеток."""
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
            "cont": cont,
        })


def main():
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union

    t0 = time.time()
    data = json.load(open(SRC, encoding="utf-8"))

    by_cont: dict = {i: [] for i in range(len(CONTINENT_NAMES))}
    skipped = 0
    for f in data["features"]:
        cont = _NAME_MAP.get(f["properties"].get("CONTINENT"))
        if cont is None:
            skipped += 1
            continue
        geom = f["geometry"]
        parts = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for part in parts:
            try:
                p = Polygon(part[0], part[1:])
                if not p.is_valid:
                    p = p.buffer(0)
                if not p.is_empty:
                    by_cont[cont].append(p)
            except Exception:
                continue

    print(f"[{time.time()-t0:.1f}s] loaded, features skipped (Antarctica/unknown): {skipped}")

    # Некоторые озёра — дырка, уже встроенная прямо в исходный полигон (как
    # Каспий), а не отдельная запись в ne_10m_lakes. Остров внутри такой
    # дырки — самостоятельный кусок суши, никак не связанный с вычитанием
    # озера (см. ту же защиту в build_land_sea.py) — раньше вылезал как
    # оторванная клякса (см. TODO.md/скриншоты Виктории). Общее решение:
    # любой кусок, ЦЕЛИКОМ лежащий внутри дырки ДРУГОГО куска (в пределах
    # того же континента) — остров в озере, выбрасываем.
    from shapely.strtree import STRtree
    for cont, polys in by_cont.items():
        water_holes = []
        for p in polys:
            for hole in p.interiors:
                try:
                    hp = Polygon(hole)
                    if not hp.is_valid:
                        hp = hp.buffer(0)
                    if not hp.is_empty:
                        water_holes.append(hp)
                except Exception:
                    continue
        if not water_holes:
            continue
        tree = STRtree(water_holes)
        before = len(polys)
        filtered = []
        for p in polys:
            c = p.centroid
            is_island_in_hole = False
            for idx in tree.query(c):
                if water_holes[int(idx)].contains(c):
                    is_island_in_hole = True
                    break
            if not is_island_in_hole:
                filtered.append(p)
        by_cont[cont] = filtered
        if before != len(filtered):
            print(f"[{time.time()-t0:.1f}s] {CONTINENT_NAMES[cont]}: dropped "
                  f"{before - len(filtered)} island(s) inside native coastline holes")

    lake_polys = _load_lakes(LAKES_SRC, MIN_LAKE_AREA_KM2)
    lake_polys += _load_land_holes(LAND_SRC, MIN_LAKE_AREA_KM2)
    print(f"[{time.time()-t0:.1f}s] lakes + coastline holes loaded (> {MIN_LAKE_AREA_KM2:.0f}km2): {len(lake_polys)}")
    lakes_union = unary_union(lake_polys) if lake_polys else None

    crop_box = box(-180.0, LAT_SOUTH, 180.0, LAT_NORTH)

    out_cells = []
    for cont, polys in by_cont.items():
        if not polys:
            continue
        merged = unary_union(polys)
        if not merged.is_valid:
            merged = merged.buffer(0)
        if lakes_union is not None:
            merged = merged.difference(lakes_union)
        merged = merged.intersection(crop_box)
        if merged.is_empty:
            continue
        merged = merged.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
        pieces = _explode(merged)
        n_written = 0
        for p in pieces:
            if p.is_empty:
                continue
            ext_ll = list(p.exterior.coords)
            if len(ext_ll) < 3:
                continue
            ext_ll = chaikin_smooth(ext_ll)
            ext = [project(lon, lat) for lon, lat in ext_ll]
            ext = [(round(x, 2), round(y, 2)) for x, y in ext]
            # Дырки (озёра) — отдельными кольцами, см. IrregularCellProvider.gd
            # (rings[1..] вырезаются чётно-нечётным правилом).
            holes = []
            for hole in p.interiors:
                hole_ll = list(hole.coords)
                if len(hole_ll) < 3:
                    continue
                hole_ll = chaikin_smooth(hole_ll)
                hole_ring = [project(lon, lat) for lon, lat in hole_ll]
                hole_ring = [(round(x, 2), round(y, 2)) for x, y in hole_ring]
                holes.append(hole_ring)
            before = len(out_cells)
            _emit_cell(out_cells, ext, holes, cont)
            n_written += len(out_cells) - before
        print(f"[{time.time()-t0:.1f}s] {CONTINENT_NAMES[cont]}: {n_written} outline piece(s)")

    json.dump({"world_px": WORLD_PX, "names": CONTINENT_NAMES, "cells": out_cells},
              open(OUT, "w", encoding="utf-8"), separators=(",", ":"))
    print(f"[{time.time()-t0:.1f}s] wrote {OUT} ({len(out_cells)} pieces total)")


if __name__ == "__main__":
    main()
