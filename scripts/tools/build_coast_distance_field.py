# -*- coding: utf-8 -*-
"""
Растровое поле "расстояние до берега со знаком" (км) для региона Западная
Европа + Средиземноморье (REGION_LONLAT, расширено 2026-07-12 по прямой
просьбе пользователя — было только Пиренейский п-ов + Балеары, тот же bbox,
что у "слоя 4"). Море — положительное расстояние, суша — ОТРИЦАТЕЛЬНОЕ
(нужно, чтобы полоса "мелководье" могла заходить на 1 км вглубь суши, не
только в море — решение пользователя 2026-07-10, второй заход: 3 уровня
моря — мелководье (фикс. полоса -1..+10 км от берега)/шельф/глубины моря,
см. scripts/SeaZonesLayer.gd).

Источник геометрии — assets/world_ocean.json (НЕ сырой provinces.json
напрямую!): найден реальный баг (2026-07-10, третий заход) — сырые
провинции местами не сшиты идеально (микро-щели на стыках соседних
областей), растеризация помечала эти щели "морем", и вокруг каждой рисовался
ложный ореол мелководья прямо посреди сплошной суши. world_ocean.json уже
решает ровно эту проблему (замыкание щель, см. build_world_ocean.py) и
заодно осознанно вырезает мелкие острова (MIN_HOLE_AREA_PX2, решение
пользователя) — попутно убирает и "конфетти" мелководья вокруг мелких
островков в открытом море.

Метод:
1. Суша = bbox региона МИНУС world_ocean (а не union провинций напрямую).
   Растеризуем в булеву маску на сетке region_world_px * SUPERSAMPLE
   (8x — по просьбе пользователя).
2. scipy distance_transform_edt ДВАЖДЫ: расстояние от каждого МОРСКОГО
   пикселя до ближайшей суши (как раньше), и расстояние от каждого
   пикселя СУШИ до ближайшего моря (новое) — знак определяется маской.
3. Растровые px -> мировые px (/SUPERSAMPLE) -> км: Web Mercator ЛОКАЛЬНО
   конформна (масштаб одинаков по x/y в любой точке), реальный км на
   мировой px в точке с широтой φ = (экваториальная окружность Земли /
   WORLD_PX) * cos(φ) — считается ПОСТРОЧНО (широта меняется по Y).

Кодирование в PNG — 16 бит на пиксель (R/G) поверх сдвинутого диапазона
[ENCODE_MIN_KM, ENCODE_MAX_KM] (не только 0..max, т.к. значения теперь
бывают отрицательными). Альфа не используется для маски моря/суши (сама
подписанная дистанция уже говорит, суша это или море) — везде 255.
Декодируется шейдером scripts/shaders/shallow_water_band.gdshader.
"""

import json
import math

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import Affine
from scipy.ndimage import distance_transform_edt
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

WORLD_PX = 8192.0
EARTH_CIRCUMFERENCE_KM = 40075.017

# Западная Европа + Средиземноморье — расширено 2026-07-12 по прямой просьбе
# пользователя (было REGION_LONLAT = (-9.9, 35.95, 4.4, 44.0), тот же bbox,
# что "слой 4"/Иберия). Тот же bbox, что у build_sea_depth_west_europe.py —
# оба живых оверлея слоя 2 должны покрывать одинаковую площадь.
REGION_LONLAT = (-10.0, 34.0, 30.0, 60.0)

SUPERSAMPLE = 8  # по просьбе пользователя (2026-07-10)

# Диапазон кодирования (км) — суша отрицательная (нужно немного, полоса
# заходит всего на 1 км), море положительное (запас на будущее).
ENCODE_MIN_KM = -20.0
ENCODE_MAX_KM = 1000.0

OCEAN_SRC = "assets/world_ocean.json"
OUT_PNG = "assets/generated/coast_distance_field_west_europe.png"


def project(lon: float, lat: float) -> tuple:
    lat = max(-85.05112878, min(85.05112878, lat))
    x = (lon + 180.0) / 360.0 * WORLD_PX
    lat_rad = math.radians(lat)
    y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
    return x, y


def unproject_y(y: float) -> float:
    n = 0.5 - y / WORLD_PX
    lat_rad = 2.0 * math.atan(math.exp(2.0 * math.pi * n)) - math.pi / 2.0
    return math.degrees(lat_rad)


def region_bbox_world_px() -> tuple:
    lon0, lat0, lon1, lat1 = REGION_LONLAT
    x0, y0 = project(lon0, lat1)
    x1, y1 = project(lon1, lat0)
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _load_region_polys(path: str, rx0: float, ry0: float, rx1: float, ry1: float, pad: float) -> list:
    polys = []
    for c in json.load(open(path, encoding="utf-8"))["cells"]:
        rings = c.get("rings", [])
        if not rings or len(rings[0]) < 3:
            continue
        bb = c.get("bbox")
        if bb and (bb[2] < rx0 - pad or bb[0] > rx1 + pad or bb[3] < ry0 - pad or bb[1] > ry1 + pad):
            continue
        p = Polygon(rings[0], rings[1:])
        if not p.is_valid:
            p = p.buffer(0)
        polys.append(p)
    return polys


def main() -> None:
    rx0, ry0, rx1, ry1 = region_bbox_world_px()
    pad = 20.0
    print(f"регион {REGION_LONLAT} -> world px [{rx0:.0f},{ry0:.0f},{rx1:.0f},{ry1:.0f}]")

    ocean_polys = _load_region_polys(OCEAN_SRC, rx0, ry0, rx1, ry1, pad)
    ocean_union = unary_union(ocean_polys)
    ocean_clipped = ocean_union.intersection(box(rx0 - pad, ry0 - pad, rx1 + pad, ry1 + pad))
    land_union = box(rx0 - pad, ry0 - pad, rx1 + pad, ry1 + pad).difference(ocean_clipped)
    print(f"море (world_ocean.json): {len(ocean_polys)} кусков в регионе")

    out_w = int(round((rx1 - rx0) * SUPERSAMPLE))
    out_h = int(round((ry1 - ry0) * SUPERSAMPLE))
    print(f"растр: {out_w}x{out_h} (x{SUPERSAMPLE})")

    px_size = 1.0 / SUPERSAMPLE
    transform = Affine(px_size, 0.0, rx0, 0.0, px_size, ry0)

    shapes = []
    geoms = land_union.geoms if land_union.geom_type == "MultiPolygon" else [land_union]
    for g in geoms:
        if not g.is_empty:
            shapes.append((g, 1))

    land_mask = rasterize(shapes, out_shape=(out_h, out_w), transform=transform,
                           fill=0, dtype=np.uint8)
    print(f"суша растеризована: {int(land_mask.sum())} px из {land_mask.size}")

    # Море -> расстояние до ближайшей суши; суша -> расстояние до ближайшего
    # моря (ОТДЕЛЬНЫЙ EDT, знак учитываем при объединении).
    dt_sea_raster_px = distance_transform_edt(1 - land_mask)
    dt_land_raster_px = distance_transform_edt(land_mask)
    is_sea = land_mask == 0
    signed_raster_px = np.where(is_sea, dt_sea_raster_px, -dt_land_raster_px)
    signed_world_px = signed_raster_px / SUPERSAMPLE

    # Локальный км/мировой-px по широте — ПОСТРОЧНО (широта зависит от y).
    row_y = ry0 + (np.arange(out_h) + 0.5) * px_size
    row_lat = np.array([unproject_y(float(y)) for y in row_y])
    km_per_world_px_row = (EARTH_CIRCUMFERENCE_KM / WORLD_PX) * np.cos(np.radians(row_lat))
    signed_km = signed_world_px * km_per_world_px_row[:, None]

    signed_km_clamped = np.clip(signed_km, ENCODE_MIN_KM, ENCODE_MAX_KM)
    norm16 = np.round((signed_km_clamped - ENCODE_MIN_KM) / (ENCODE_MAX_KM - ENCODE_MIN_KM) * 65535.0).astype(np.uint32)
    r = (norm16 // 256).astype(np.uint8)
    g = (norm16 % 256).astype(np.uint8)
    b = np.zeros_like(r)
    a = np.full_like(r, 255)
    rgba = np.stack([r, g, b, a], axis=-1)

    from PIL import Image
    Image.fromarray(rgba, mode="RGBA").save(OUT_PNG)

    print(f"расстояние (со знаком): min={signed_km.min():.1f}км max={signed_km.max():.1f}км "
          f"(суша<0, море>0)")
    print(f"сохранено -> {OUT_PNG} ({out_w}x{out_h}), диапазон кодирования [{ENCODE_MIN_KM:.0f}, {ENCODE_MAX_KM:.0f}] км")

    bbox_path = OUT_PNG.rsplit(".", 1)[0] + "_bbox.json"
    with open(bbox_path, "w", encoding="utf-8") as f:
        json.dump({"x0": rx0, "y0": ry0, "x1": rx1, "y1": ry1, "world_px": WORLD_PX,
                    "encode_min_km": ENCODE_MIN_KM, "encode_max_km": ENCODE_MAX_KM}, f)
    print(f"сохранено -> {bbox_path}")


if __name__ == "__main__":
    main()
