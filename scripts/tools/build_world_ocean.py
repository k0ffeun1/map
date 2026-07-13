"""Офлайн-препроцессинг: ЕДИНАЯ маска мирового океана (пока БЕЗ клеток —
просто "это вода/не вода", один слой для проверки перед будущей нарезкой
воды на клетки). Маска целиком и нарезка на клетки — разные задачи, не путать.

Источник суши — assets/provinces.json (слой "Области", клавиша 8), по
решению пользователя (см. project_provinces_foundation_layer в памяти) —
provinces.json теперь основополагающий слой суши для всей карты, НЕ
assets/land_sea.json.

ВАЖНО:
соседние провинции в provinces.json не всегда идеально стыкуются друг с
другом (обычное дело для реальных административных векторных данных) —
без исправления получаются сотни мелких "дырок" мнимой воды прямо ВНУТРИ
материков, на стыках провинций (найдено на побережье Ла-Манша/Бретани/
Португалии в сессии 2026-07-10). Щели заклеиваются морфологическим
ЗАМЫКАНИЕМ (расширить на CLOSE_PX + сжать обратно, см. CLOSE_PX) — оно, в
отличие от простого раздувания, НЕ теряет детализацию берега; плюс мелкие
дырки/щепки-артефакты швов отбрасываются (MIN_HOLE_AREA_PX2/
MIN_WATER_PIECE_AREA_PX2).

Результат: assets/world_ocean.json — тот же формат, что у land_sea.json
({"world_px":...,"cells":[{"rings":...,"bbox":...}]}), только это ВОДА
(мир минус суша), а не суша.

Не запускается в Godot — отдельный шаг подготовки данных.
"""
import json
import math
import time

SRC = "assets/provinces.json"
OUT = "assets/world_ocean.json"
WORLD_PX = 8192.0

# Те же полярные пороги, что у остальных слоёв (build_land_sea.py и т.п.).
LAT_NORTH = 76.0
LAT_SOUTH = -58.0

# Морфологическое ЗАМЫКАНИЕ (closing) для заклейки щелей между провинциями:
# расширить объединение суши на CLOSE_PX, потом сжать обратно на столько же.
# Сравнивали (см. сессию 2026-07-10) с простым buffer(+0.5) на каждый кусок:
# то раздувало берег ~500 фейковыми точками-скруглениями, которые simplify
# потом схлопывал, ТЕРЯЯ реальную детализацию (111 точек берега у Ла-Коруньи
# против 232 у provinces.json). Замыкание возвращает берег на исходное
# место (сжатием -CLOSE_PX), сохраняя ~в 10 раз больше реальных точек берега
# (1137 в том же окне) — берег такой же чёткий, как у слоя провинций.
CLOSE_PX = 0.15
# Дырки-артефакты швов (мнимые "озёра"/точки воды внутри суши на стыках
# провинций) площадью меньше этого — заклеиваем (делаем сушей). Это те самые
# тёмные/светлые крапинки на берегу, что были видны у Бретани.
MIN_HOLE_AREA_PX2 = 4.0
# Мелкие отдельные куски воды (мнимые лужи-щепки от тех же швов) площадью
# меньше этого — выбрасываем из вывода.
MIN_WATER_PIECE_AREA_PX2 = 4.0
SIMPLIFY_TOLERANCE_PX = 0.1


def project(lon: float, lat: float) -> tuple:
    lat = max(-85.05112878, min(85.05112878, lat))
    x = (lon + 180.0) / 360.0 * WORLD_PX
    lat_rad = math.radians(lat)
    y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
    return x, y


def _explode(geom) -> list:
    from shapely.geometry import Polygon, MultiPolygon
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    if geom.geom_type == "GeometryCollection":
        out = []
        for g in geom.geoms:
            out.extend(_explode(g))
        return out
    return []


def main() -> None:
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union
    from shapely.strtree import STRtree

    t0 = time.time()
    data = json.load(open(SRC, encoding="utf-8"))

    land_polys_raw = []
    for c in data["cells"]:
        rings = c["rings"]
        if len(rings[0]) < 3:
            continue
        try:
            p = Polygon(rings[0], rings[1:])
            if not p.is_valid:
                p = p.buffer(0)
            if not p.is_empty:
                land_polys_raw.append(p)
        except Exception:
            continue
    print(f"[{time.time() - t0:.1f}s] land pieces loaded (raw): {len(land_polys_raw)}", flush=True)

    # НЕ буферим ВСЕ куски подряд (было раньше) — buffer(+CLOSE_PX).buffer(-CLOSE_PX)
    # сглаживает ЛЮБУЮ вогнутую деталь у́же 2×CLOSE_PX, а не только настоящие щели
    # между провинциями. Найдено инструментально (2026-07-10, обсуждение с
    # пользователем): у Ла-Коруньи, которая УЖЕ идеально стыкуется с соседями
    # без всякого буфера (проверено — она в одной группе с континентальной
    # Европой даже при CLOSE_PX=0), настоящая береговая линия (риасы,
    # вогнутости у́же ~0.3 px) всё равно портилась этим буфером — потому что он
    # применялся вообще ко ВСЕМ 454 кускам региона разом, включая те, что ни в
    # каком замыкании не нуждались. Из-за этого "Мировой океан" (клавиша 2)
    # не совпадал с точным контуром той же провинции у слоя "Клетки (тест:
    # Ла-Корунья)" (клавиша C, cells_test.json — берёт provinces.json БЕЗ
    # буфера вообще).
    #
    # Правильный фикс — буферить ТОЛЬКО те куски, у которых реально есть щель
    # с соседом (найдено через STRtree: раздутые тестовые копии пересеклись,
    # а исходные НЕТ — значит между ними щель у́же CLOSE_PX). Остальные куски
    # (подавляющее большинство, включая Ла-Корунью) идут в land_union их
    # ТОЧНЫМ исходным контуром, без единого буфера — 1-в-1 как у cells_test.json.
    test_buf = [p.buffer(CLOSE_PX) for p in land_polys_raw]
    tree = STRtree(test_buf)
    needs_fix: set = set()
    n = len(land_polys_raw)
    for i in range(n):
        for j in tree.query(test_buf[i]):
            j = int(j)
            if j <= i:
                continue
            if test_buf[i].intersects(test_buf[j]) and not land_polys_raw[i].intersects(land_polys_raw[j]):
                needs_fix.add(i)
                needs_fix.add(j)
    print(f"[{time.time() - t0:.1f}s] кусков с реальной щелью у соседа: {len(needs_fix)} из {n}", flush=True)

    clean_polys = [land_polys_raw[i] for i in range(n) if i not in needs_fix]
    # Замыкание — ТОЛЬКО среди проблемных кусков (локально), остальной мир не задет.
    gap_fixed = []
    if needs_fix:
        gap_group = [land_polys_raw[i].buffer(CLOSE_PX) for i in needs_fix]
        closed = unary_union(gap_group).buffer(-CLOSE_PX)
        if not closed.is_valid:
            closed = closed.buffer(0)
        gap_fixed = _explode(closed)

    land_union = unary_union(clean_polys + gap_fixed)
    if not land_union.is_valid:
        land_union = land_union.buffer(0)
    print(f"[{time.time() - t0:.1f}s] land_union built (точечное замыкание только у щелей)", flush=True)

    north_y = project(0.0, LAT_NORTH)[1]
    south_y = project(0.0, LAT_SOUTH)[1]
    crop_box = box(0.0, north_y, WORLD_PX, south_y)

    ocean = crop_box.difference(land_union)
    if not ocean.is_valid:
        ocean = ocean.buffer(0)
    ocean = ocean.simplify(SIMPLIFY_TOLERANCE_PX, preserve_topology=True)
    print(f"[{time.time() - t0:.1f}s] ocean = crop_box - land_union", flush=True)

    out_cells = []
    dropped_pieces = 0
    filled_holes = 0
    for piece in _explode(ocean):
        if piece.is_empty:
            continue
        # Мнимые лужи-щепки от швов провинций — не выводим.
        if piece.area < MIN_WATER_PIECE_AREA_PX2:
            dropped_pieces += 1
            continue
        ext = [[round(x, 2), round(y, 2)] for x, y in piece.exterior.coords]
        if len(ext) < 3:
            continue
        rings = [ext]
        for hole in piece.interiors:
            # Мнимые "озёра"-крапинки на стыках провинций — заклеиваем (не
            # добавляем как дырку, значит остаются залиты водой... нет: дырка
            # в океане = суша, поэтому НЕ добавляя мелкую дырку, мы убираем
            # мнимый островок суши и делаем это место сплошной водой). Реальные
            # крупные внутренние воды (заливы/эстуарии) сохраняются.
            if Polygon(hole).area < MIN_HOLE_AREA_PX2:
                filled_holes += 1
                continue
            hole_pts = [[round(x, 2), round(y, 2)] for x, y in hole.coords]
            if len(hole_pts) >= 3:
                rings.append(hole_pts)
        xs = [p[0] for p in ext]
        ys = [p[1] for p in ext]
        out_cells.append({"rings": rings, "bbox": [min(xs), min(ys), max(xs), max(ys)]})

    print(f"[{time.time() - t0:.1f}s] ocean pieces: {len(out_cells)} "
          f"(dropped {dropped_pieces} sliver pieces, filled {filled_holes} seam holes)", flush=True)

    json.dump({"world_px": WORLD_PX, "cells": out_cells},
               open(OUT, "w", encoding="utf-8"), separators=(",", ":"))
    print(f"[{time.time() - t0:.1f}s] wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
