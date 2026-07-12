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

ИСПРАВЛЕНО (2026-07-12): маска море/суша (альфа) раньше бралась НАПРЯМУЮ из
знака высоты GEBCO (`elevation <= 0.0`) — найден реальный баг на слое "V":
Нидерланды (польдеры, часть страны физически НИЖЕ уровня моря, реальная
высота отрицательная) ошибочно помечались морем — тёмные пятна-острова прямо
посреди суши на скриншоте пользователя. Теперь маска берётся из ВЕКТОРНОГО
`assets/world_ocean.json` (тот же источник, что уже использует
build_coast_distance_field.py для полосы мелководья) — GEBCO используется
ТОЛЬКО для цвета/значения глубины ТАМ, где уже по вектору известно, что это
море, а не для самого решения "это суша или море". Заодно устраняет
рассинхрон береговой линии между этим файлом и мелководьем (оба теперь от
одного источника).
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

# Регион расширен ЕЩЁ РАЗ 2026-07-12 (та же сессия) по прямой просьбе
# пользователя — от Западной Европы до побережья Америки (Северной и Южной),
# Карибский бассейн захвачен целиком. Тот же bbox и то же обоснование
# границ, что в build_coast_distance_field.py — см. комментарий там.
REGION_LONLAT = (-90.0, -35.0, 30.0, 60.0)  # (lon0, lat0, lon1, lat1)

GEBCO_DIR = "scripts/tools/_work/gebco_2024_world"
GEBCO_QUADRANTS = [
    (lon0, lat0, lon0 + 90.0, lat0 + 90.0)
    for lon0 in (-180.0, -90.0, 0.0, 90.0)
    for lat0 in (-90.0, 0.0)
]

OCEAN_SRC = "assets/world_ocean.json"  # источник истины море/суша (не GEBCO, см. докстринг выше)
OUT_PNG = "assets/generated/sea_depth_west_europe.png"

# x8 — по прямой просьбе пользователя 2026-07-12 ("сделай то же самое для
# глубин, x8"), тот же способ, что уже применили к мелководью
# (build_coast_distance_field.py): нарезка на тайлы вместо одного файла,
# см. TILE_MAX_PX и код сохранения в main().
SUPERSAMPLE = 8

# Тайлы НЕ пересжимаются (те же соображения, что у coast_distance_field.py —
# это не картинка, а числа глубины в R/G, LANCZOS испортил бы кодирование).
TILE_MAX_PX = 8000

MAX_DEPTH_M = 6000.0  # то же значение, что уже подобрано в панели (OCEAN_DEPTH_DEFAULT_*), см. TileMapViewer.gd


def project(lon: float, lat: float) -> tuple:
    lat = max(-85.05112878, min(85.05112878, lat))
    x = (lon + 180.0) / 360.0 * WORLD_PX
    lat_rad = math.radians(lat)
    y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
    return x, y


def _gebco_path(lon0: float, lat0: float, lon1: float, lat1: float) -> str:
    return f"{GEBCO_DIR}/gebco_2024_sub_ice_n{lat1:.1f}_s{lat0:.1f}_w{lon0:.1f}_e{lon1:.1f}.tif"


def _rasterize_ocean_mask(x0: float, y0: float, out_w: int, out_h: int) -> np.ndarray:
    """Векторная маска моря из OCEAN_SRC на ту же сетку (WORLD_PX-координаты,
    пиксель = 1/SUPERSAMPLE), что и GEBCO-растр глубины — см. докстринг файла
    про то, почему это не берётся из знака высоты GEBCO напрямую."""
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

    # Маска море/суша — из ВЕКТОРА (world_ocean.json), НЕ из знака высоты
    # GEBCO (см. докстринг файла про баг с польдерами Нидерландов). GEBCO
    # используется только для значения глубины там, где вектор уже сказал
    # "это море".
    is_sea = _rasterize_ocean_mask(x0, y0, out_w, out_h)

    # in-place на x8 (450 Mpx) — та же проблема и тот же фикс, что уже
    # применили в build_coast_distance_field.py: каждая "обычная" операция
    # (nan_to_num/clip/copy) на массиве такого размера без in-place создаёт
    # СВОЙ временный 1.7-ГБ буфер, штук 5-6 таких буферов разом валят
    # MemoryError. Переиспользуем ОДИН буфер `combined` на всех шагах.
    np.nan_to_num(combined, nan=1.0, copy=False)  # NaN (вне квадрантов GEBCO) -> считаем сушей по высоте
    np.negative(combined, out=combined)  # combined: elevation -> -elevation (depth, суша теперь отрицательная)
    np.clip(combined, 0.0, MAX_DEPTH_M, out=combined)  # клип снизу защищает от суши с "морской" GEBCO-высотой (польдеры)
    combined[~is_sea] = 0.0  # там, где вектор говорит "суша" — глубина принудительно 0, что бы ни думал GEBCO
    # combined теперь и есть depth_clamped (метры) — считаем статистику ДО
    # дальнейшего перевода в 16-битный код.
    total_sea = int(is_sea.sum())
    if total_sea:
        sea_depths = combined[is_sea]
        print(f"depth range over sea: min={sea_depths.min():.0f}м max={sea_depths.max():.0f}м mean={sea_depths.mean():.0f}м")
        del sea_depths

    combined *= 65535.0 / MAX_DEPTH_M
    np.round(combined, out=combined)
    # uint16 (не uint32) — значения 0..65535 влезают, лишний uint32 стоил бы
    # ещё ~1.8 ГБ впустую на этом размере.
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

    # Годотовский Image не грузит текстуру больше 268 435 456 px ("Too many
    # pixels for Image") — на этом bbox x8 даёт ~449 млн px, одним файлом не
    # влезает (см. done.md, тот же фикс, что у build_coast_distance_field.py).
    # ВАЖНО: тайлы НЕ сжимаются — это НЕ картинка, а число (метры),
    # закодированное в R/G, LANCZOS/любое сглаживание испортило бы значение.
    # Просто РЕЖЕМ уже посчитанный растр на куски.
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
