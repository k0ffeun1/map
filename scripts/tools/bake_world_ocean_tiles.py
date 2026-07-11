"""Офлайн-запекание слоя "Мировой океан" (клавиша `2`) в PNG-тайлы — тот же
повод, что и у bake_land_sea_tiles.py/bake_continents_tiles.py: живой
scan-line рендер IrregularCellProvider.gd на GDScript тормозит на
гигантском полигоне (у мирового океана один кусок — 34155 точек контура,
bbox почти во весь мир, каждый тайл пересчитывает их все).

ТЕСТОВЫЙ прогон — печёт ТОЛЬКО регион (по умолчанию северо-запад Иберии,
см. REGION_LONLAT), не весь мир: чтобы быстро проверить, решает ли
запекание пиксельность берега, не дожидаясь полного мирового прогона.
Вне запечённого региона BakedTileProvider будет показывать пусто (см. его
комментарий "нет файла -> нечего рисовать") — это ожидаемо для теста,
полный мир — отдельным прогоном с --full, когда результат устроит.

Цвета/border ТОЧНО повторяют вызов IrregularCellProvider.new(...) для
океана в TileMapViewer.gd (border_color=(0.10,0.35,0.60,0.85),
ocean_color=(0.20,0.55,0.85,0.55), border_width=1.0) — если один поменяется,
поменяй и другой.

МЕЛКОВОДЬЕ (SHALLOW_COLOR, -LAND_MARGIN_KM..+SEA_MARGIN_KM от берега) ЗАПЕКАЕТСЯ
ПРЯМО В ЭТИ ЖЕ ТАЙЛЫ (решение пользователя 2026-07-10, третий заход) — раньше
было отдельным растровым слоем (scripts/SeaZonesLayer.gd,
build_coast_distance_field.py), но растеризация с ДРУГИМ supersample давала
видимый рассинхрон береговой линии с этим (векторным) слоем. Тут же
геометрия ТА ЖЕ (world_ocean.json), буфер строится shapely+pyproj (см.
_build_shallow_band) и рисуется в той же tile-функции — граница по
построению совпадает пиксель в пиксель.
"""
import json
import math
import os
import sys
import time

import numpy as np
import pyproj
from PIL import Image, ImageDraw
from shapely.geometry import Polygon, box
from shapely.ops import unary_union, transform as shapely_transform

WORLD_PX = 8192.0
# 1024/8 — как у слоя 4 (bake_provinces_iberia_tiles.py), по просьбе
# пользователя 2026-07-10: чётче берег, был заметно смазан на 256/4 рядом
# с новым векторно-точным слоем мелководья (клавиша 5).
TILE_PX = 1024
SUPERSAMPLE = 8
BAKE_MAX_Z = 7
OUT_DIR = "assets/tiles_bundle/world_ocean_baked"
SRC = "assets/world_ocean.json"

MIN_SCALE = 2.0
MARGIN_PX = 4

BORDER_WIDTH = 1.0  # мировые px — как border_width в вызове IrregularCellProvider.new() для океана.
BORDER_COLOR = (26, 89, 153, 217)   # Color(0.10, 0.35, 0.60, 0.85) -> 0..255
MAX_BORDER_PX = 2

OCEAN_COLOR = (51, 140, 217, 140)   # Color(0.20, 0.55, 0.85, 0.55) -> 0..255

# #8ac6da, непрозрачно — тот же цвет, что был у DEFAULT_SHELF_COLOR в
# SeaZonesLayer.gd. Рисуется ПОВЕРХ обычной заливки океана в полосе
# -LAND_MARGIN_KM..+SEA_MARGIN_KM от берега (решение пользователя, см.
# докстринг файла).
SHALLOW_COLOR = (0x8A, 0xC6, 0xDA, 255)
LAND_MARGIN_KM = 0.5  # решение пользователя 2026-07-11 (было 0.0)
SEA_MARGIN_KM = 20.0

# Шельф/глубины моря (реальная батиметрия GMRT) НЕ запекаются сюда — откат
# 2026-07-10 (попытка привязать клавиши 2/5 друг к другу запутала UX,
# пользователь попросил откатить до состояния "слой 2 = океан+мелководье,
# слой 5 = отдельная живая панель шельф/глубины с ползунком"). Код
# _load_depth_raster/_draw_depth_zones НИЖЕ оставлен неиспользуемым в
# main() — можно вернуть вызовом при следующей явной просьбе.
DEPTH_IMG_PATH = "assets/generated/sea_depth_raw_test_region.png"
DEPTH_BBOX_PATH = "assets/generated/sea_depth_raw_test_region_bbox.json"
THRESHOLD_SHELF_M = 300.0
SHELF_COLOR = SHALLOW_COLOR  # тот же цвет, что у мелководья — общий, см. SeaZonesLayer.gd
DEEP_COLOR = (30, 80, 160, 255)   # Color(0.117, 0.313, 0.627) -> 0..255

# Северо-запад Иберии (Галисия + вход в Бискайский залив) — тестовый регион.
REGION_LONLAT = (-10.5, 41.0, -6.0, 44.5)


def project(lon: float, lat: float) -> tuple:
    lat = max(-85.05112878, min(85.05112878, lat))
    x = (lon + 180.0) / 360.0 * WORLD_PX
    lat_rad = math.radians(lat)
    y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
    return x, y


def unproject(x: float, y: float) -> tuple:
    lon = x / WORLD_PX * 360.0 - 180.0
    n = 0.5 - y / WORLD_PX
    lat_rad = 2.0 * math.atan(math.exp(2.0 * math.pi * n)) - math.pi / 2.0
    return lon, math.degrees(lat_rad)


def region_bbox_world_px() -> tuple:
    lon0, lat0, lon1, lat1 = REGION_LONLAT
    x0, y0 = project(lon0, lat1)
    x1, y1 = project(lon1, lat0)
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _explode_rings(geom) -> list:
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


def _build_shallow_band(ocean_union, bbox: tuple) -> list:
    """Полоса мелководья (-LAND_MARGIN_KM..+SEA_MARGIN_KM от берега) — ТА ЖЕ
    геометрия world_ocean.json, что и сама заливка океана в этом файле,
    буфер в честных км через azimuthal equidistant (см. обсуждение с
    пользователем 2026-07-10 — растровый вариант давал рассинхрон береговой
    линии). Возвращает список {"bbox":..., "rings":[[...]]} — тот же формат,
    что и cells, для переиспользования в tile-цикле."""
    rx0, ry0, rx1, ry1 = bbox
    region_box = box(rx0, ry0, rx1, ry1)
    land = region_box.difference(ocean_union)
    if land.is_empty:
        return []

    center_lon, center_lat = unproject((rx0 + rx1) / 2.0, (ry0 + ry1) / 2.0)
    wgs84 = pyproj.CRS.from_epsg(4326)
    aeqd = pyproj.CRS.from_proj4(f"+proj=aeqd +lat_0={center_lat} +lon_0={center_lon} +datum=WGS84 +units=m")
    to_aeqd = pyproj.Transformer.from_crs(wgs84, aeqd, always_xy=True).transform
    to_wgs84 = pyproj.Transformer.from_crs(aeqd, wgs84, always_xy=True).transform

    def wpx_to_lonlat(x, y, z=None):
        return unproject(x, y)

    def lonlat_to_wpx(lon, lat, z=None):
        return project(lon, lat)

    land_lonlat = shapely_transform(wpx_to_lonlat, land)
    land_aeqd = shapely_transform(to_aeqd, land_lonlat)
    outer_aeqd = land_aeqd.buffer(SEA_MARGIN_KM * 1000.0, quad_segs=16)
    inner_aeqd = land_aeqd.buffer(-LAND_MARGIN_KM * 1000.0, quad_segs=16)
    band_aeqd = outer_aeqd.difference(inner_aeqd)
    band_lonlat = shapely_transform(to_wgs84, band_aeqd)
    band_wpx = shapely_transform(lonlat_to_wpx, band_lonlat)
    if not band_wpx.is_valid:
        band_wpx = band_wpx.buffer(0)
    band_wpx = band_wpx.intersection(region_box)

    out = []
    for ring_set in _explode_rings(band_wpx):
        ext = ring_set[0]
        xs = [p[0] for p in ext]
        ys = [p[1] for p in ext]
        out.append({"rings": ring_set, "bbox": [min(xs), min(ys), max(xs), max(ys)]})
    return out


def _load_depth_raster() -> tuple:
    """Реальная батиметрия GMRT (тестовый бокс Галисии) — та же PNG, что
    грузит scripts/SeaZonesLayer.gd для живого шейдера. Возвращает
    (PIL.Image, dx0, dy0, dx1, dy1, max_depth_m) или None, если файлов нет."""
    if not (os.path.exists(DEPTH_IMG_PATH) and os.path.exists(DEPTH_BBOX_PATH)):
        return None
    bbox = json.load(open(DEPTH_BBOX_PATH, encoding="utf-8"))
    img = Image.open(DEPTH_IMG_PATH).convert("RGBA")
    return img, bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"], bbox["max_depth_m"]


def _draw_depth_zones(canvas: Image.Image, depth: tuple, t0x: float, t0y: float,
                       scale: float, margin_render_px: float, margin_world: float,
                       tile_world: float) -> None:
    """Сэмплирует растр батиметрии в область канвы тайла и красит
    шельф/глубины моря — NEAREST (не LANCZOS/LINEAR!), т.к. глубина
    закодирована как 16 бит в 2 отдельных 8-битных канала (R/G), линейная
    интерполяция каналов НЕЗАВИСИМО даёт мусорные значения (та же ловушка,
    что была у мелководья на клавише 5, см. SeaZonesLayer.gd)."""
    depth_img, dx0, dy0, dx1, dy1, max_depth_m = depth
    tile_wx0, tile_wy0 = t0x - margin_world, t0y - margin_world
    tile_wx1, tile_wy1 = t0x + tile_world + margin_world, t0y + tile_world + margin_world

    ox0, oy0 = max(tile_wx0, dx0), max(tile_wy0, dy0)
    ox1, oy1 = min(tile_wx1, dx1), min(tile_wy1, dy1)
    if ox1 <= ox0 or oy1 <= oy0:
        return

    dw, dh = depth_img.size
    src_px0 = (ox0 - dx0) / (dx1 - dx0) * dw
    src_py0 = (oy0 - dy0) / (dy1 - dy0) * dh
    src_px1 = (ox1 - dx0) / (dx1 - dx0) * dw
    src_py1 = (oy1 - dy0) / (dy1 - dy0) * dh
    crop = depth_img.crop((round(src_px0), round(src_py0), round(src_px1), round(src_py1)))

    tgt_x0 = (ox0 - t0x) * scale + margin_render_px
    tgt_y0 = (oy0 - t0y) * scale + margin_render_px
    tgt_x1 = (ox1 - t0x) * scale + margin_render_px
    tgt_y1 = (oy1 - t0y) * scale + margin_render_px
    tgt_w, tgt_h = round(tgt_x1 - tgt_x0), round(tgt_y1 - tgt_y0)
    if tgt_w < 1 or tgt_h < 1:
        return

    resized = crop.resize((tgt_w, tgt_h), Image.NEAREST)
    arr = np.array(resized)
    combined = arr[:, :, 0].astype(np.uint32) * 256 + arr[:, :, 1].astype(np.uint32)
    depth_m = combined.astype(np.float32) / 65535.0 * max_depth_m
    sea_mask = arr[:, :, 3] > 0

    out = np.zeros((tgt_h, tgt_w, 4), dtype=np.uint8)
    out[sea_mask & (depth_m < THRESHOLD_SHELF_M)] = SHELF_COLOR
    out[sea_mask & (depth_m >= THRESHOLD_SHELF_M)] = DEEP_COLOR

    depth_layer = Image.fromarray(out, mode="RGBA")
    canvas.paste(depth_layer, (round(tgt_x0), round(tgt_y0)), depth_layer)


def main() -> None:
    t0 = time.time()
    full_world = "--full" in sys.argv
    data = json.load(open(SRC, encoding="utf-8"))
    cells = data["cells"]
    print(f"[{time.time()-t0:.1f}s] cells: {len(cells)}", flush=True)

    os.makedirs(OUT_DIR, exist_ok=True)

    shallow_cells: list = []
    if not full_world:
        rx0, ry0, rx1, ry1 = region_bbox_world_px()
        print(f"[{time.time()-t0:.1f}s] РЕГИОН {REGION_LONLAT} -> world px "
              f"[{rx0:.0f},{ry0:.0f},{rx1:.0f},{ry1:.0f}]", flush=True)

        ocean_polys = []
        for c in cells:
            rings = c.get("rings", [])
            if not rings or len(rings[0]) < 3:
                continue
            p = Polygon(rings[0], rings[1:])
            if not p.is_valid:
                p = p.buffer(0)
            ocean_polys.append(p)
        ocean_union = unary_union(ocean_polys)
        shallow_cells = _build_shallow_band(ocean_union, (rx0, ry0, rx1, ry1))
        print(f"[{time.time()-t0:.1f}s] полоса мелководья: {len(shallow_cells)} кусков "
              f"(-{LAND_MARGIN_KM:.0f}км/+{SEA_MARGIN_KM:.0f}км)", flush=True)
    else:
        print("--full: полоса мелководья пока не считается (нужен другой метод буфера "
              "для всего мира, не единый AEQD-центр) — только заливка океана.", flush=True)

    depth = None  # шельф/глубины НЕ запекаются сюда, см. комментарий у THRESHOLD_SHELF_M

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
        pad = BORDER_WIDTH * 2.0 + margin_world
        border_w_px = max(1, min(MAX_BORDER_PX * supersample, round(BORDER_WIDTH * scale)))

        if full_world:
            tx_range = range(n)
            ty_range = range(n)
        else:
            rx0, ry0, rx1, ry1 = region_bbox_world_px()
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
                    if bx1 < t0x - pad or bx0 > t1x + pad or by1 < t0y - pad or by0 > t1y + pad:
                        continue
                    hits.append(c)
                shallow_hits = []
                for c in shallow_cells:
                    bx0, by0, bx1, by1 = c["bbox"]
                    if bx1 < t0x - pad or bx0 > t1x + pad or by1 < t0y - pad or by0 > t1y + pad:
                        continue
                    shallow_hits.append(c)
                if not hits and not shallow_hits:
                    skipped_empty += 1
                    continue

                canvas_px = render_px + 2 * margin_render_px
                img = Image.new("RGBA", (canvas_px, canvas_px), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img, "RGBA")

                def to_px(ring):
                    return [((x - t0x) * scale + margin_render_px,
                             (y - t0y) * scale + margin_render_px) for x, y in ring]

                for c in hits:
                    pts = to_px(c["rings"][0])
                    if len(pts) >= 3:
                        draw.polygon(pts, fill=OCEAN_COLOR)
                    for hole in c["rings"][1:]:
                        hpts = to_px(hole)
                        if len(hpts) >= 3:
                            draw.polygon(hpts, fill=(0, 0, 0, 0))

                # Шельф/глубины моря — ПОВЕРХ заливки океана, ПОД мелководьем
                # (см. _draw_depth_zones и докстринг файла).
                if depth:
                    _draw_depth_zones(img, depth, t0x, t0y, scale, margin_render_px,
                                       margin_world, tile_world)

                # Мелководье — ПОВЕРХ заливки океана, той же геометрией
                # (world_ocean.json), никакого отдельного растра — см.
                # докстринг файла.
                for c in shallow_hits:
                    pts = to_px(c["rings"][0])
                    if len(pts) >= 3:
                        draw.polygon(pts, fill=SHALLOW_COLOR)
                    for hole in c["rings"][1:]:
                        hpts = to_px(hole)
                        if len(hpts) >= 3:
                            draw.polygon(hpts, fill=(0, 0, 0, 0))

                for c in hits:
                    pts = to_px(c["rings"][0])
                    if len(pts) >= 2:
                        draw.line(pts + [pts[0]], fill=BORDER_COLOR, width=border_w_px, joint="curve")

                out_canvas_px = TILE_PX + 2 * MARGIN_PX
                img = img.resize((out_canvas_px, out_canvas_px), Image.LANCZOS)
                img = img.crop((MARGIN_PX, MARGIN_PX, MARGIN_PX + TILE_PX, MARGIN_PX + TILE_PX))
                img.save(f"{OUT_DIR}/{z}_{tx}_{ty}.png", optimize=True)
                written += 1

        print(f"[{time.time()-t0:.1f}s] z={z}: готово", flush=True)

    print(f"[{time.time()-t0:.1f}s] записано {written} тайлов, пропущено пустых {skipped_empty}", flush=True)


if __name__ == "__main__":
    main()
