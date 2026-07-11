"""Офлайн-запекание слоя "Области (провинции)" — регион Пиренейского
полуострова (REGION_LONLAT, материк Испания/Португалия + Балеарские о-ва,
БЕЗ Канарских — они географически у берега Африки), ОТДЕЛЬНЫМ новым
слоем/клавишей — существующий живой слой "8" (assets/provinces.json целиком,
IrregularCellProvider, raster_px=1024) НЕ трогается, остаётся как есть.

История: сначала пробовали запечь весь Иберийский полуостров (первая версия
скрипта, БЕЗ фикса щелей — на стыках была видна тёмная "ложная граница",
просвечивал фон, см. done.md/TODO.md), потом сузили до тестового региона
Галисии (bake_provinces_galicia_tiles.py, 2026-07-10) — чтобы отладить фикс
щелей (GAP_FIX_PX) и фикс запечатанных гаваней (см. ниже) на малом регионе
быстрыми итерациями. Когда оба фикса подтверждены — расширено обратно на
всю Иберию (тот же файл переименован, 2026-07-10, продолжение).

Цвета повторяют вызов IrregularCellProvider.new(...) для провинций в
TileMapViewer.gd (fill_alpha=0.55, saturation=0.35, value=0.88) — если
поменяется один, поменяй и другой. Заливка клетки — тот же алгоритм хэша по
золотому сечению, что и в IrregularCellProvider._load_data
(idx * 0.61803398875, или хэш "color_key", если поле есть — см.
_godot_string_hash, повторяет String.hash() в Godot).

МЕХАНИКА ГРАНИЦЫ — НЕ векторные линии по контуру (пробовали, см. историю
правок в done.md/TODO.md этой сессии — у соседних провинций контуры рисуются
НЕЗАВИСИМО, из-за чего на части стыков видно ДВЕ слегка разные линии вместо
одной, даже без всякого буфера щелей). Вместо этого граница ищется ПРЯМО В
УЖЕ ЗАЛИТОЙ картинке (см. _draw_borders_from_fill): там, где два соседних
пикселя закрашены РАЗНЫМ цветом (или один закрашен, другой прозрачный —
истинный берег), этот стык помечается пикселем границы, дальше расширяется
до нужной толщины бинарной дилатацией диском (сглаживание даёт даунскейл
supersample; при этом чёрный кладётся ТОЛЬКО на непрозрачные пиксели — на
берегу граница уходит внутрь суши, не в воду). Ровно ОДНА линия на стык
гарантирована по построению — по цветам не может быть "двух" линий
физически, это один и тот же пиксельный переход.

УЗКИЕ ЗАЛИВЫ/ГАВАНИ (залив у Ла-Коруньи и т.п.) — решено двумя мерами
(2026-07-10, ранее рисовались сплошной чёрной кляксой, см. TODO.md/done.md):
1. Раздув GAP_FIX_PX больше НЕ вылезает в море: после buffer() из провинции
   вычитается точный полигон океана (assets/world_ocean.json — он уже
   доведён до идеального совпадения с контурами провинций). Щели между
   соседями океаном не являются и остаются закрытыми, а берег возвращается
   к точной линии — узкая гавань не сужается на 2*GAP_FIX_PX.
2. Граница на берегу рисуется ТОЛЬКО внутрь суши: чёрный никогда не кладётся
   на прозрачный (водяной) пиксель (маска opaque в _draw_borders_from_fill).
   Поэтому запечатать залив любой узости физически невозможно — вода остаётся
   видимой вплоть до одного пикселя supersample-растра. Побочный эффект:
   береговая линия вдвое тоньше внутренних границ (рисуется с одной стороны
   перепада) — осознанно, при необходимости компенсировать удвоением радиуса
   только для береговых пикселей.
"""
import colorsys
import json
import math
import os
import sys
import time

import numpy as np
from PIL import Image, ImageChops, ImageDraw
from scipy.ndimage import binary_dilation
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

WORLD_PX = 8192.0
# 1024, а не обычные 256 — региону всего ~22 тайла, дёшево себе позволить
# бОльшую итоговую детализацию (тот же смысл, что raster_px у живого слоя),
# по просьбе пользователя ("края провинций пиксельные при близком зуме").
# TileMapViewer._make_tile масштабирует спрайт под tile_world/texture.get_width()
# сам — размер текстуры больше 256 работает "бесплатно" по интеграции.
TILE_PX = 1024
SUPERSAMPLE = 8
BAKE_MAX_Z = 7
OUT_DIR = "assets/tiles_bundle/provinces_iberia_baked"
SRC = "assets/provinces.json"
# Точный полигон мирового океана — вычитается из раздутых (GAP_FIX_PX)
# провинций, чтобы фикс щелей не съедал море (узкие гавани), см. docstring.
OCEAN_SRC = "assets/world_ocean.json"

MIN_SCALE = 2.0
MARGIN_PX = 4

# Тонкая, резкая (минимальная растушёвка), НЕпрозрачная граница — совпадает
# с BORDER_STYLE["province"] в TileMapViewer.gd (живой слой "8"): width в
# МИРОВЫХ px (умножается на scale), а feather/min_half_w — уже в РАСТРОВЫХ px
# (см. комментарии у _border_feather/_border_min_half_w в
# IrregularCellProvider.gd — они НЕ умножаются на scale там же, только на
# native-холсте) — если один поменяется, поменяй и другой.
BORDER_WIDTH = 0.15       # мировые px
BORDER_FEATHER = 0.1      # РАСТРОВЫЕ (native) px, не мировые — как в живом слое
BORDER_MIN_HALF_W = 0.05  # РАСТРОВЫЕ (native) px
BORDER_COLOR = (0, 0, 0, 255)  # полностью непрозрачный чёрный
MAX_BORDER_PX = 2  # потолок толщины в финальных px тайла — не "плывёт" на близком зуме

FILL_ALPHA = 0.55
SATURATION = 0.35
VALUE = 0.88

# Небольшой раздув (buffer) каждой провинции ПЕРЕД заливкой — закрывает
# реальные щели между соседними провинциями в provinces.json (векторные
# данные не всегда стыкуются идеально, см. ту же находку у world_ocean.json
# в build_world_ocean.py). Только для ЭТОЙ картинки (визуал), не меняет
# provinces.json/игровую геометрию — соседи слегка перекрываются вместо
# зазора, на глаз незаметно. В сторону моря раздув срезается обратно
# точным океаном (OCEAN_SRC) — см. docstring, пункт 1.
GAP_FIX_PX = 0.15

# ВРЕМЕННО сужено до Северо-Запада Испании (Галисия + вход в Бискайский
# залив) — ТОТ ЖЕ REGION_LONLAT, что у bake_world_ocean_tiles.py/
# _preview_sea_depth.py/build_coast_distance_field.py (решение пользователя
# 2026-07-11: "не запекай весь мир, только регион где смотрели"). Раньше тут
# был весь Пиренейский п-ов + Балеары (-9.9, 35.95, 4.4, 44.0) — тот вариант
# НЕ удалён, просто закомментирован ниже, вернуть одной строкой, когда дойдёт
# очередь до полного региона/мира (имя файла/переменных - "iberia" - НЕ
# переименовано вслед за сужением, см. правило CLAUDE.md про переименование
# только по явной просьбе).
# REGION_LONLAT_FULL_IBERIA = (-9.9, 35.95, 4.4, 44.0)
REGION_LONLAT = (-10.5, 41.0, -6.0, 44.5)


def project(lon: float, lat: float) -> tuple:
    lat = max(-85.05112878, min(85.05112878, lat))
    x = (lon + 180.0) / 360.0 * WORLD_PX
    lat_rad = math.radians(lat)
    y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
    return x, y


def region_bbox_world_px() -> tuple:
    lon0, lat0, lon1, lat1 = REGION_LONLAT
    x0, y0 = project(lon0, lat1)
    x1, y1 = project(lon1, lat0)
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _resize_premultiplied(img: Image.Image, size: tuple) -> Image.Image:
    """LANCZOS-ресайз RGBA с premultiplied-alpha — обычный img.resize() на
    "сырых" RGBA смешивает RGB соседних пикселей с ЦВЕТОМ прозрачного фона
    (у нас чёрный (0,0,0,0)), даже когда его альфа=0 — классический баг
    тёмного "ободка" на любой границе заливка<->прозрачность. Премультипликация
    (умножение RGB на альфу) — средствами PIL в uint8 (лёгкий по памяти, важно
    на дальнем зуме, где MIN_SCALE поднимает supersample очень высоко);
    деление обратно — на маленькой итоговой картинке (после сжатия)."""
    r, g, b, a = img.split()
    premult_img = Image.merge("RGB", tuple(ImageChops.multiply(ch, a) for ch in (r, g, b)))
    premult_resized = premult_img.resize(size, Image.LANCZOS)
    alpha_resized = a.resize(size, Image.LANCZOS)

    p = np.asarray(premult_resized).astype(np.float32)
    a2 = np.asarray(alpha_resized).astype(np.float32)
    safe_a = np.where(a2 > 0, a2, 1.0)
    rgb_out = np.clip(p / (safe_a[..., None] / 255.0), 0, 255)
    rgb_out = np.where(a2[..., None] > 0, rgb_out, 0)
    out = np.dstack([rgb_out, a2]).astype(np.uint8)
    return Image.fromarray(out, mode="RGBA")


def _draw_borders_from_fill(img: Image.Image, half_w_px: float, half_feather_px: float,
                             feather_px: float) -> Image.Image:
    """Граница — по перепаду ЦВЕТА в уже залитой (без щелей) картинке, а не
    отдельными векторными линиями по контуру двух соседей независимо (см.
    docstring файла — так двоение линии физически невозможно). Пиксель
    считается границей, если у него есть непосредственный сосед (справа или
    снизу) другого цвета, либо сосед-суша/сосед-прозрачность (истинный
    берег).

    "Толщина" — НЕ жёсткий dilate (был раньше, но на очень узких деталях
    берега — типа маленький залив у́же самой линии — жёсткая заливка съедала
    всю деталь целиком сплошной кляксой, а у живого слоя "8" там мягкое
    затухание и сквозь него слегка видно исходный цвет). Вместо dilate —
    ТА ЖЕ формула плавного затухания по расстоянию, что в
    IrregularCellProvider._draw_segment: alpha = clamp((half_w + half_feather
    - dist) / feather, 0, 1), где dist — расстояние ДО БЛИЖАЙШЕГО пикселя-
    границы (scipy.ndimage.distance_transform_edt). Итог блендится (alpha-
    композиция), а не жёстко перезаписывается — поэтому даже на детали у́же
    самой линии останется хоть какой-то намёк на исходный цвет, а не сплошной
    чёрный.

    ВАЖНО (та же ловушка с памятью, что у _resize_premultiplied): на дальнем
    зуме холст огромный (MIN_SCALE), но реальный контент (залитые клетки)
    занимает лишь маленький уголок — остальное прозрачный фон. Работаем
    numpy'ем (int32/float-маски — тяжёлые по памяти) ТОЛЬКО в обрезке по
    реальному контенту (img.getbbox(), дёшево и в PIL), а не по всему
    холсту — иначе массив на холсте ~16000x16000 требует единицы ГБ и падает."""
    bbox = img.getbbox()
    if bbox is None:
        return img
    w, h = img.size
    reach = int(math.ceil(half_w_px + half_feather_px)) + 1
    x0 = max(0, bbox[0] - reach)
    y0 = max(0, bbox[1] - reach)
    x1 = min(w, bbox[2] + reach)
    y1 = min(h, bbox[3] + reach)

    arr = np.array(img.crop((x0, y0, x1, y1)))  # uint8, своя копия (для записи)
    rgb = arr[:, :, :3]
    opaque = arr[:, :, 3] > 0

    edge = np.zeros(opaque.shape, dtype=bool)
    diff_x = np.any(rgb[:, :-1] != rgb[:, 1:], axis=-1) | (opaque[:, :-1] != opaque[:, 1:])
    diff_y = np.any(rgb[:-1, :] != rgb[1:, :], axis=-1) | (opaque[:-1, :] != opaque[1:, :])
    edge[:, :-1] |= diff_x
    edge[:, 1:] |= diff_x
    edge[:-1, :] |= diff_y
    edge[1:, :] |= diff_y

    if not edge.any():
        return img

    # Толщина — бинарная дилатация диском радиуса half_w (+полфеатера), а не
    # честный distance_transform_edt с плавным затуханием, как раньше:
    # 1) сглаживание края даёт сам даунскейл supersample (LANCZOS), феатер в
    #    0.1 native px на его фоне неразличим; 2) EDT на полном тайле требовал
    #    сотни МБ (int64/float64 внутри scipy), bool-дилатация — на порядок
    #    меньше. Плавное затухание было нужно, чтобы узкая деталь не заливалась
    #    сплошняком, — теперь это гарантирует маска opaque ниже.
    radius = half_w_px + half_feather_px
    r = int(math.ceil(radius))
    yy, xx = np.ogrid[-r:r + 1, -r:r + 1]
    disk = (yy * yy + xx * xx) <= radius * radius
    border = binary_dilation(edge, structure=disk)
    # Чёрный НИКОГДА не кладётся на воду (прозрачный пиксель) — граница на
    # берегу рисуется только внутрь суши. Иначе на узкой воде (гавань у́же
    # толщины линии) "полутолщины" с двух берегов смыкаются в сплошную кляксу
    # и запечатывают залив (см. docstring файла, пункт 2).
    border &= opaque
    arr[border] = BORDER_COLOR

    img.paste(Image.fromarray(arr, mode="RGBA"), (x0, y0))
    return img


def _godot_string_hash(s: str) -> int:
    """Повторяет String::hash() в Godot 4 (djb2: h=5381, h=h*33+c)."""
    h = 5381
    for ch in s:
        h = ((h << 5) + h + ord(ch)) & 0xFFFFFFFF
    return h


def _cell_color(idx: int, color_key: str) -> tuple:
    if color_key:
        hue = math.fmod(float(_godot_string_hash(color_key)) * 0.61803398875, 1.0)
    else:
        hue = math.fmod(float(idx) * 0.61803398875, 1.0)
    r, g, b = colorsys.hsv_to_rgb(hue, SATURATION, VALUE)
    return (round(r * 255), round(g * 255), round(b * 255), round(FILL_ALPHA * 255))


def _explode_rings(geom) -> list:
    """Polygon -> [[ext_ring, hole_ring, ...]], MultiPolygon -> несколько таких списков."""
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        rings = [list(geom.exterior.coords)]
        rings += [list(h.coords) for h in geom.interiors]
        return [rings]
    if geom.geom_type == "MultiPolygon":
        out = []
        for g in geom.geoms:
            out.extend(_explode_rings(g))
        return out
    return []


def main() -> None:
    t0 = time.time()
    full_world = "--full" in sys.argv
    data = json.load(open(SRC, encoding="utf-8"))
    raw_cells = data["cells"]
    print(f"[{time.time()-t0:.1f}s] cells (весь мир): {len(raw_cells)}", flush=True)

    rx0, ry0, rx1, ry1 = region_bbox_world_px()
    print(f"[{time.time()-t0:.1f}s] РЕГИОН {REGION_LONLAT} -> world px "
          f"[{rx0:.0f},{ry0:.0f},{rx1:.0f},{ry1:.0f}]", flush=True)

    # Океан для среза буфера щелей (см. docstring, пункт 1). Обрезаем по bbox
    # региона (в --full — не обрезаем), чтобы difference() не работал с
    # гигантским мировым полигоном на каждой провинции.
    ocean_polys = []
    for oc in json.load(open(OCEAN_SRC, encoding="utf-8"))["cells"]:
        orings = oc.get("rings", [])
        if orings and len(orings[0]) >= 3:
            p = Polygon(orings[0], orings[1:])
            if not p.is_valid:
                p = p.buffer(0)
            ocean_polys.append(p)
    ocean = unary_union(ocean_polys)
    if not full_world:
        clip_pad = 5.0 + GAP_FIX_PX * 2.0
        ocean = ocean.intersection(box(rx0 - clip_pad, ry0 - clip_pad,
                                        rx1 + clip_pad, ry1 + clip_pad))
    print(f"[{time.time()-t0:.1f}s] океан загружен и обрезан по региону", flush=True)

    # idx — ТОЧНО как в IrregularCellProvider._load_data: считается по ВСЕМ
    # записям исходного массива по порядку (включая невалидные), не по
    # отфильтрованному подмножеству — иначе цвета разойдутся с тем, что
    # показал бы живой слой "8" для тех же клеток.
    # Заливка — по РАЗДУТОМУ контуру (GAP_FIX_PX, закрывает щели между
    # соседями) — граница потом ищется по самой этой заливке, см.
    # _draw_borders_from_fill.
    cells = []
    pad = 5.0  # запас в world px вокруг региона, чтобы не грузить/буферить весь мир
    for idx, c in enumerate(raw_cells):
        rings = c.get("rings", [])
        if not rings or len(rings[0]) < 3:
            continue
        bb = c.get("bbox")
        if not full_world and bb and (bb[2] < rx0 - pad or bb[0] > rx1 + pad
                                       or bb[3] < ry0 - pad or bb[1] > ry1 + pad):
            continue
        color = _cell_color(idx, str(c.get("color_key", "")))
        try:
            poly = Polygon(rings[0], rings[1:])
            if not poly.is_valid:
                poly = poly.buffer(0)
            # Раздув закрывает щели между соседями, но НЕ должен вылезать в
            # море (съедал узкие гавани) — срезаем обратно точным океаном.
            buffered = poly.buffer(GAP_FIX_PX).difference(ocean)
        except Exception:
            continue
        for ring_set in _explode_rings(buffered):
            bbx = [p[0] for p in ring_set[0]]
            bby = [p[1] for p in ring_set[0]]
            cells.append({
                "rings": ring_set,
                "bbox": [min(bbx), min(bby), max(bbx), max(bby)],
                "color": color,
            })
    print(f"[{time.time()-t0:.1f}s] валидных клеток (в регионе, раздутых): {len(cells)}", flush=True)

    # Океан больше не нужен — освобождаем ДО цикла тайлов: холст дальнего
    # зума огромный (render_px до ~16К), каждая сотня лишних МБ на счету.
    del ocean, ocean_polys, raw_cells, data
    import gc
    gc.collect()

    os.makedirs(OUT_DIR, exist_ok=True)

    written = 0
    skipped_empty = 0
    for z in range(BAKE_MAX_Z + 1):
        n = 1 << z
        tile_world = WORLD_PX / n
        supersample = max(SUPERSAMPLE, math.ceil(MIN_SCALE * tile_world / TILE_PX))
        render_px = TILE_PX * supersample
        scale = render_px / tile_world
        margin_render_px = MARGIN_PX * supersample
        margin_world = margin_render_px / scale
        pad_tile = GAP_FIX_PX * 2.0 + BORDER_WIDTH * 2.0 + margin_world
        # half_w — как в _render/_draw_segment живого слоя: border_width (мировые
        # px) * scale, с "полом" min_half_w (уже в native px, без scale) и
        # потолком MAX_BORDER_PX (в финальных px тайла -> native через supersample).
        half_w_px = max(BORDER_MIN_HALF_W, BORDER_WIDTH * scale * 0.5)
        half_w_px = min(half_w_px, MAX_BORDER_PX * supersample * 0.5)
        half_feather_px = BORDER_FEATHER * 0.5

        if full_world:
            tx_range = range(n)
            ty_range = range(n)
        else:
            tx_range = range(max(0, int(rx0 / tile_world) - 1), min(n, int(rx1 / tile_world) + 2))
            ty_range = range(max(0, int(ry0 / tile_world) - 1), min(n, int(ry1 / tile_world) + 2))

        for ty in ty_range:
            t0y = ty * tile_world
            t1y = t0y + tile_world
            for tx in tx_range:
                t0x = tx * tile_world
                t1x = t0x + tile_world

                hits = []
                for c in cells:
                    bx0, by0, bx1, by1 = c["bbox"]
                    if bx1 < t0x - pad_tile or bx0 > t1x + pad_tile or by1 < t0y - pad_tile or by0 > t1y + pad_tile:
                        continue
                    hits.append(c)
                if not hits:
                    skipped_empty += 1
                    continue

                # ЭКОНОМИЯ ПАМЯТИ: на дальнем зуме полный холст гигантский
                # (render_px до ~16K, ~1 ГБ RGBA), а реальный контент (регион
                # Галисии) — крошечный уголок. Работаем только в прямоугольнике
                # контента, ВЫРОВНЕННОМ по сетке supersample (тогда LANCZOS-
                # ресайз куска попадает в ту же сетку выборки, что и ресайз
                # всего холста, — картинка та же с точностью до прозрачных
                # краёв за пределами запаса reach).
                canvas_px = render_px + 2 * margin_render_px
                out_canvas_px = TILE_PX + 2 * MARGIN_PX
                ss = supersample
                # запас: толщина границы + феатер + опора LANCZOS-ядра (~3 px
                # итогового растра = 3*ss native px, берём 4 для верности)
                reach = int(math.ceil(half_w_px + BORDER_FEATHER)) + 4 * ss
                minx = min(c["bbox"][0] for c in hits)
                miny = min(c["bbox"][1] for c in hits)
                maxx = max(c["bbox"][2] for c in hits)
                maxy = max(c["bbox"][3] for c in hits)
                px0 = int((minx - t0x) * scale + margin_render_px) - reach
                py0 = int((miny - t0y) * scale + margin_render_px) - reach
                px1 = int(math.ceil((maxx - t0x) * scale + margin_render_px)) + reach
                py1 = int(math.ceil((maxy - t0y) * scale + margin_render_px)) + reach
                px0 = max(0, (px0 // ss) * ss)
                py0 = max(0, (py0 // ss) * ss)
                px1 = min(canvas_px, ((px1 + ss - 1) // ss) * ss)
                py1 = min(canvas_px, ((py1 + ss - 1) // ss) * ss)

                img = Image.new("RGBA", (px1 - px0, py1 - py0), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img, "RGBA")

                def to_px(ring):
                    return [((x - t0x) * scale + margin_render_px - px0,
                             (y - t0y) * scale + margin_render_px - py0) for x, y in ring]

                for c in hits:
                    pts = to_px(c["rings"][0])
                    if len(pts) >= 3:
                        draw.polygon(pts, fill=c["color"])
                    for hole in c["rings"][1:]:
                        hpts = to_px(hole)
                        if len(hpts) >= 3:
                            draw.polygon(hpts, fill=(0, 0, 0, 0))

                if BORDER_COLOR[3] > 0:
                    img = _draw_borders_from_fill(img, half_w_px, half_feather_px, BORDER_FEATHER)

                img = _resize_premultiplied(img, ((px1 - px0) // ss, (py1 - py0) // ss))
                out_img = Image.new("RGBA", (out_canvas_px, out_canvas_px), (0, 0, 0, 0))
                out_img.paste(img, (px0 // ss, py0 // ss))
                out_img = out_img.crop((MARGIN_PX, MARGIN_PX, MARGIN_PX + TILE_PX, MARGIN_PX + TILE_PX))
                out_img.save(f"{OUT_DIR}/{z}_{tx}_{ty}.png", optimize=True)
                written += 1

        print(f"[{time.time()-t0:.1f}s] z={z}: готово", flush=True)

    print(f"[{time.time()-t0:.1f}s] записано {written} тайлов, пропущено пустых {skipped_empty}", flush=True)

    total_bytes = sum(os.path.getsize(f"{OUT_DIR}/{f}") for f in os.listdir(OUT_DIR))
    print(f"[{time.time()-t0:.1f}s] размер на диске: {total_bytes/1024/1024:.2f} МБ ({written} файлов)", flush=True)


if __name__ == "__main__":
    main()
