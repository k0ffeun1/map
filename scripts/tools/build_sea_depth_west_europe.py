# -*- coding: utf-8 -*-
"""
Растровое поле СЫРОЙ глубины моря (метры, 16 бит на пиксель, тот же формат,
что у _preview_sea_depth.py) на регион Западная Европа + Средиземноморье —
по прямой просьбе пользователя 2026-07-12 ("хочу увидеть всю Европу в живом
рендере"), расширяет прежний тестовый бокс Галисии (_preview_sea_depth.py,
REGION_LONLAT=(-16,41,-6,44.5)) на гораздо больший регион.

Источник — ГЛОБАЛЬНЫЙ GEBCO_2024 (8 GeoTIFF-квадрантов, ~7.1ГБ, уже скачаны
разово вручную в scripts/tools/_work/gebco_2024_world/, см.
bake_world_ocean_tiles.py/open_gebco_sources), НЕ отдельный GMRT-докачанный
файл, как у _preview_sea_depth.py — регион слишком большой, докачивать под
него отдельный tif не нужно, GEBCO уже покрывает весь мир.

Раскраска (шельф/склон/глубины/бездна) по-прежнему делается ЖИВЫМ шейдером
в Godot (sea_depth_zones.gdshader, слайдеры под клавишей "2") — этот скрипт
экспортирует только сырые метры, не готовые цвета (в отличие от
sample_depth_gradient_rgba в bake_world_ocean_tiles.py, которая печёт готовый
цвет прямо в тайлы "Мирового океана" — это ДРУГОЙ, статичный слой).

Кодирование — идентично _preview_sea_depth.py: R = старший байт, G = младший
байт нормированной 0..65535 глубины (0..MAX_DEPTH_M), альфа = маска
море(255)/суша(0).
"""

import json
import math
import os

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from PIL import Image

WORLD_PX = 8192.0

# Западная Европа + Средиземноморье — решение пользователя 2026-07-12
# (вариант "Только Западная Европа+Средиземноморье" из предложенных двух).
REGION_LONLAT = (-10.0, 34.0, 30.0, 60.0)  # (lon0, lat0, lon1, lat1)

GEBCO_DIR = "scripts/tools/_work/gebco_2024_world"
GEBCO_QUADRANTS = [
    (lon0, lat0, lon0 + 90.0, lat0 + 90.0)
    for lon0 in (-180.0, -90.0, 0.0, 90.0)
    for lat0 in (-90.0, 0.0)
]

OUT_PNG = "assets/generated/sea_depth_west_europe.png"

# То же правило проекта, что и у соседних скриптов (SUPERSAMPLE=8 везде,
# кроме континентов/суши-моря) — но регион здесь В РАЗЫ больше Галисии,
# поэтому супersample снижен, иначе итоговый растр (2-3к px в Галисии при x8)
# разрастётся до multiple-ГБ картинки на весь регион. x2 достаточно для
# гладкого глубинного градиента (в отличие от векторных линий берега, глубина
# — плавное поле без резких границ).
SUPERSAMPLE = 2

MAX_DEPTH_M = 6000.0  # то же значение, что уже подобрано в панели (OCEAN_DEPTH_DEFAULT_*), см. TileMapViewer.gd


def project(lon: float, lat: float) -> tuple:
    lat = max(-85.05112878, min(85.05112878, lat))
    x = (lon + 180.0) / 360.0 * WORLD_PX
    lat_rad = math.radians(lat)
    y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
    return x, y


def _gebco_path(lon0: float, lat0: float, lon1: float, lat1: float) -> str:
    return f"{GEBCO_DIR}/gebco_2024_sub_ice_n{lat1:.1f}_s{lat0:.1f}_w{lon0:.1f}_e{lon1:.1f}.tif"


def open_gebco_sources_for_region(lon_left: float, lat_bottom: float, lon_right: float, lat_top: float) -> list:
    out = []
    for (qlon0, qlat0, qlon1, qlat1) in GEBCO_QUADRANTS:
        if qlon1 < lon_left or qlon0 > lon_right or qlat1 < lat_bottom or qlat0 > lat_top:
            continue
        path = _gebco_path(qlon0, qlat0, qlon1, qlat1)
        if not os.path.exists(path):
            print(f"GEBCO не найден: {path} — пропускаю квадрант")
            continue
        out.append(rasterio.open(path))
    return out


def main() -> None:
    lon0, lat0, lon1, lat1 = REGION_LONLAT
    x0, y1 = project(lon0, lat0)  # южная граница -> больший y
    x1, y0 = project(lon1, lat1)  # северная граница -> меньший y
    out_w = int(round((x1 - x0) * SUPERSAMPLE))
    out_h = int(round((y1 - y0) * SUPERSAMPLE))
    print(f"регион {REGION_LONLAT} -> world px [{x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f}], "
          f"растр {out_w}x{out_h} (x{SUPERSAMPLE})")

    sources = open_gebco_sources_for_region(lon0, lat0, lon1, lat1)
    if not sources:
        print("GEBCO квадранты не найдены — нечего запекать, выхожу")
        return
    print(f"открыто {len(sources)} квадрантов GEBCO")

    k = 2.0 * math.pi * 6378137.0 / WORLD_PX  # метров на "мировой px" (сферическая Web Mercator)
    origin_x = k * x0 - math.pi * 6378137.0
    origin_y = math.pi * 6378137.0 - k * y0
    a = k * (x1 - x0) / out_w
    e = -k * (y1 - y0) / out_h
    dst_transform = rasterio.Affine(a, 0.0, origin_x, 0.0, e, origin_y)

    combined = np.full((out_h, out_w), np.nan, dtype=np.float32)
    for src in sources:
        part = np.full((out_h, out_w), np.nan, dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=part,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=float(src.nodata) if src.nodata is not None else None,
            dst_transform=dst_transform,
            dst_crs="EPSG:3857",
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
        src.close()
        gap = np.isnan(combined) & ~np.isnan(part)
        if gap.any():
            combined[gap] = part[gap]

    elevation = np.nan_to_num(combined, nan=1.0)  # NaN (вне всех квадрантов) -> суша/прозрачно
    is_sea = elevation <= 0.0
    depth = -elevation
    depth_clamped = np.clip(depth, 0.0, MAX_DEPTH_M)
    depth_clamped[~is_sea] = 0.0

    norm16 = np.round(depth_clamped / MAX_DEPTH_M * 65535.0).astype(np.uint32)
    r = (norm16 // 256).astype(np.uint8)
    g = (norm16 % 256).astype(np.uint8)
    b = np.zeros_like(r)
    a_ch = np.where(is_sea, 255, 0).astype(np.uint8)
    rgba = np.stack([r, g, b, a_ch], axis=-1)

    os.makedirs(os.path.dirname(OUT_PNG), exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(OUT_PNG)

    total_sea = int(is_sea.sum())
    if total_sea:
        sea_depths = depth_clamped[is_sea]
        print(f"depth range over sea: min={sea_depths.min():.0f}м max={sea_depths.max():.0f}м mean={sea_depths.mean():.0f}м")
    print(f"сохранено -> {OUT_PNG} ({out_w}x{out_h}), max_depth_m={MAX_DEPTH_M:.0f}")

    bbox_path = OUT_PNG.rsplit(".", 1)[0] + "_bbox.json"
    with open(bbox_path, "w", encoding="utf-8") as f:
        json.dump({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "world_px": WORLD_PX, "max_depth_m": MAX_DEPTH_M}, f)
    print(f"сохранено -> {bbox_path}")


if __name__ == "__main__":
    main()
