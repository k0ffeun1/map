# -*- coding: utf-8 -*-
"""
Растровое поле СЫРОЙ глубины моря (метры, 16 бит на пиксель, тот же формат,
что у build_sea_depth_west_europe.py) на регион Марианской впадины — по
прямой просьбе пользователя 2026-07-13: самая глубокая точка Мирового
океана, Бездна Челленджера (11.3733° с.ш., 142.5917° в.д., ~10 924-10 935 м,
экспедиция Five Deeps 2019), +500 км во все стороны от неё.

Источник — тот же ГЛОБАЛЬНЫЙ GEBCO_2024 (8 GeoTIFF-квадрантов, уже скачаны
в scripts/tools/_work/gebco_2024_world/), что и у build_sea_depth_west_europe.py
— он покрывает весь мир, включая Тихий океан, докачивать отдельный tif не
нужно.

MAX_DEPTH_M поднят до 11000 м (в отличие от 6000 м у Западной Европы) —
специально, чтобы вместить реальную глубину Бездны Челленджера и оставить
запас для 4-го уровня градиента "бездна" (>9000 м, см. sea_depth_zones.gdshader
и OCEAN_DEPTH_DEFAULT_ABYSS_* в TileMapViewer.gd).

Раскраска по-прежнему живым шейдером в Godot (sea_depth_zones.gdshader) —
этот скрипт экспортирует только сырые метры, не готовые цвета.

Кодирование — идентично build_sea_depth_west_europe.py: R = старший байт,
G = младший байт нормированной 0..65535 глубины (0..MAX_DEPTH_M), альфа =
маска море(255)/суша(0), взятая из ВЕКТОРНОГО assets/world_ocean.json (не из
знака высоты GEBCO — та же причина, что в build_sea_depth_west_europe.py:
не полагаться на GEBCO для решения "суша или море").
"""

import json
import math
import os

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.warp import reproject, Resampling
from shapely.geometry import Polygon
from PIL import Image

WORLD_PX = 8192.0

# Бездна Челленджера (11.3733, 142.5917) +500 км во всех направлениях
# (см. докстринг файла — расчёт через 111.32 км/градус широты и поправку
# на cos(широта) для долготы).
REGION_LONLAT = (138.0102, 6.8817, 147.1732, 15.8649)  # (lon0, lat0, lon1, lat1)

GEBCO_DIR = "scripts/tools/_work/gebco_2024_world"
GEBCO_QUADRANTS = [
    (lon0, lat0, lon0 + 90.0, lat0 + 90.0)
    for lon0 in (-180.0, -90.0, 0.0, 90.0)
    for lat0 in (-90.0, 0.0)
]

OCEAN_SRC = "assets/world_ocean.json"  # источник истины море/суша (не GEBCO, см. докстринг выше)
OUT_PNG = "assets/generated/sea_depth_mariana_trench.png"

# Тот же приём x8 + нарезка на тайлы, что у build_sea_depth_west_europe.py —
# регион здесь маленький (500 км), скорее всего влезет одним файлом, но
# нарезка не мешает, если вдруг не влезет.
SUPERSAMPLE = 8
TILE_MAX_PX = 8000

MAX_DEPTH_M = 11000.0  # вмещает реальную глубину Бездны Челленджера (~10935м) + запас под 4-й уровень градиента


def project(lon: float, lat: float) -> tuple:
    lat = max(-85.05112878, min(85.05112878, lat))
    x = (lon + 180.0) / 360.0 * WORLD_PX
    lat_rad = math.radians(lat)
    y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
    return x, y


def _gebco_path(lon0: float, lat0: float, lon1: float, lat1: float) -> str:
    return f"{GEBCO_DIR}/gebco_2024_sub_ice_n{lat1:.1f}_s{lat0:.1f}_w{lon0:.1f}_e{lon1:.1f}.tif"


def _rasterize_ocean_mask(x0: float, y0: float, out_w: int, out_h: int) -> np.ndarray:
    """Векторная маска моря из OCEAN_SRC на ту же сетку, что и GEBCO-растр
    глубины — см. докстринг файла про то, почему это не берётся из знака
    высоты GEBCO напрямую."""
    px_size = 1.0 / SUPERSAMPLE
    transform = rasterio.Affine(px_size, 0.0, x0, 0.0, px_size, y0)
    rx1 = x0 + out_w * px_size
    ry1 = y0 + out_h * px_size
    pad = 5.0
    shapes = []
    for c in json.load(open(OCEAN_SRC, encoding="utf-8"))["cells"]:
        bb = c.get("bbox")
        if bb and (bb[2] < x0 - pad or bb[0] > rx1 + pad or bb[3] < y0 - pad or bb[1] > ry1 + pad):
            continue
        rings = c.get("rings", [])
        if not rings or len(rings[0]) < 3:
            continue
        shapes.append((Polygon(rings[0], rings[1:]), 1))
    if not shapes:
        return np.zeros((out_h, out_w), dtype=bool)
    mask = rasterize(shapes, out_shape=(out_h, out_w), transform=transform, fill=0, dtype=np.uint8)
    return mask.astype(bool)


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

    is_sea = _rasterize_ocean_mask(x0, y0, out_w, out_h)

    np.nan_to_num(combined, nan=1.0, copy=False)
    np.negative(combined, out=combined)
    np.clip(combined, 0.0, MAX_DEPTH_M, out=combined)
    combined[~is_sea] = 0.0
    total_sea = int(is_sea.sum())
    if total_sea:
        sea_depths = combined[is_sea]
        print(f"depth range over sea: min={sea_depths.min():.0f}м max={sea_depths.max():.0f}м mean={sea_depths.mean():.0f}м")
        del sea_depths

    combined *= 65535.0 / MAX_DEPTH_M
    np.round(combined, out=combined)
    norm16 = combined.astype(np.uint16)
    del combined
    r = (norm16 // 256).astype(np.uint8)
    g = (norm16 % 256).astype(np.uint8)
    del norm16
    b = np.zeros_like(r)
    a_ch = np.where(is_sea, 255, 0).astype(np.uint8)
    del is_sea
    rgba = np.stack([r, g, b, a_ch], axis=-1)
    del r, g, b, a_ch
    import gc
    gc.collect()

    os.makedirs(os.path.dirname(OUT_PNG), exist_ok=True)

    if out_w * out_h > TILE_MAX_PX * TILE_MAX_PX:
        tiles_dir = OUT_PNG.rsplit(".", 1)[0] + "_tiles"
        os.makedirs(tiles_dir, exist_ok=True)
        cols = math.ceil(out_w / TILE_MAX_PX)
        rows = math.ceil(out_h / TILE_MAX_PX)
        manifest_tiles = []
        for row in range(rows):
            for col in range(cols):
                tx0 = col * TILE_MAX_PX
                ty0 = row * TILE_MAX_PX
                tx1 = min(tx0 + TILE_MAX_PX, out_w)
                ty1 = min(ty0 + TILE_MAX_PX, out_h)
                tile_name = f"tile_{row}_{col}.png"
                tile_arr = np.ascontiguousarray(rgba[ty0:ty1, tx0:tx1])
                Image.fromarray(tile_arr, mode="RGBA").save(f"{tiles_dir}/{tile_name}")
                del tile_arr
                px_size = 1.0 / SUPERSAMPLE
                manifest_tiles.append({
                    "file": tile_name, "row": row, "col": col,
                    "x0": x0 + tx0 * px_size, "y0": y0 + ty0 * px_size,
                    "x1": x0 + tx1 * px_size, "y1": y0 + ty1 * px_size,
                })
        manifest_path = f"{tiles_dir}/manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"world_px": WORLD_PX, "max_depth_m": MAX_DEPTH_M, "rows": rows, "cols": cols,
                        "x0": x0, "y0": y0, "x1": x1, "y1": y1, "tiles": manifest_tiles}, f)
        print(f"растр {out_w}x{out_h} превышает лимит Godot Image ({TILE_MAX_PX*TILE_MAX_PX} px на тайл) "
              f"-> нарезан на {rows}x{cols}={len(manifest_tiles)} тайлов")
        print(f"сохранено -> {tiles_dir}/ (манифест {manifest_path})")
    else:
        Image.fromarray(rgba, mode="RGBA").save(OUT_PNG)
        bbox_path = OUT_PNG.rsplit(".", 1)[0] + "_bbox.json"
        with open(bbox_path, "w", encoding="utf-8") as f:
            json.dump({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "world_px": WORLD_PX, "max_depth_m": MAX_DEPTH_M}, f)
        print(f"сохранено -> {bbox_path}")


if __name__ == "__main__":
    main()
