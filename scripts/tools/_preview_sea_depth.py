# -*- coding: utf-8 -*-
"""
ЧЕРНОВОЙ превью-скрипт (не часть игрового пайплайна, см. правило именования
в CLAUDE.md — префикс "_preview" как у _preview_admin1.py).

Экспортирует СЫРУЮ батиметрию (GMRT, синтез GEBCO+доп. съёмок) как текстуру
глубины в метрах — не готовые цвета зон. Раскраска по 4 зонам (мелководье/
склон/глубина/бездна) теперь делается ШЕЙДЕРОМ в реальном времени в Godot
(пороги и цвета крутятся слайдерами по клавише 5, см.
scripts/SeaZonesLayer.gd и scripts/shaders/sea_depth_zones.gdshader) —
это позволяет пользователю подбирать пороги на глаз без перезапуска скрипта.

Кодирование: глубина (метры, 0..MAX_DEPTH_M) записывается как 16 бит на
пиксель — R = старший байт, G = младший байт нормированного 0..65535
значения; альфа = маска море(255)/суша(0). Декодируется шейдером обратно
в метры.

РЕГИОН — REGION_LONLAT, Северо-Запад Иберии/Галисия, тот же bbox, что у
РЕАЛЬНОГО тестового запечённого слоя "Мировой океан"
(scripts/tools/bake_world_ocean_tiles.py, REGION_LONLAT), с западной
границей, раздвинутой в Атлантику (было -10.5, стало -16.0) по прямой
просьбе пользователя 2026-07-11 — сравнить градиент/изобаты на бОльших
глубинах открытого океана, а не только на узком шельфе у берега. ПРОБОВАЛИ
расширять до "весь Пиренейский п-ов + Балеары + буфер 450км во все стороны"
(REGION_LONLAT_FULL_IBERIA) — ОТКАЧЕНО обратно тем же днём: слишком тяжёлые
данные (417МБ GMRT), результат почти целиком заливал экран без пользы для
подбора порогов, а НЕ большой бокс generate_sea_cells.py (TEST_REGION_LONLAT
— Иберия+Франция+Бискай+Ла-Манш, другая форма/назначение).

Исходные данные скачаны вручную (не автоматизировано в этом скрипте, разово):
    curl "https://www.gmrt.org/services/GridServer?minlongitude=-16.0&maxlongitude=-6.0&minlatitude=41.0&maxlatitude=44.5&format=geotiff&resolution=max&layer=topo" \
      -o scripts/tools/_work/gmrt_galicia_atlantic.tif

ТОЛЬКО референс для пользователя (подобрать пороги/цвета глазами прямо в
игре) — не игровые данные.
"""

import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
from scipy.ndimage import distance_transform_edt
from PIL import Image
import math

WORLD_PX = 8192.0  # как у generate_sea_cells.py / build_world_ocean.py

# Западная граница РАСШИРЕНА относительно REGION_LONLAT в
# bake_world_ocean_tiles.py (было -10.5, стало -16.0) — только у этого
# debug-слоя глубины, не у запечённого слоя "Мировой океан" (там расширять
# смысла нет, суша/шельф не меняются, а перезапекать тайлы дорого).
# Пробовали "весь Пиренейский п-ов + Балеары + буфер 450км" — откачено, см.
# докстринг файла. Исходник того прогона (gmrt_iberia_450km_buffer.tif) НЕ
# удалён по прямой просьбе пользователя 2026-07-11 — пригодится, когда
# вернёмся к этому региону (поменять REGION_LONLAT обратно на
# (-15.2, 31.9, 9.7, 48.0) и SRC_TIF на этот файл).
REGION_LONLAT = (-16.0, 41.0, -6.0, 44.5)  # (lon0, lat0, lon1, lat1)

SRC_TIF = "scripts/tools/_work/gmrt_galicia_atlantic.tif"
# В assets/generated/ (не _work) — грузится в игру как debug-слой,
# см. SeaZonesLayer.gd / TileMapViewer.gd (клавиша 5).
OUT_PNG = "assets/generated/sea_depth_raw_test_region.png"

# ПРАВИЛО ПРОЕКТА (решение пользователя 2026-07-11): SUPERSAMPLE=8 на ВСЕХ
# запеканиях, КРОМЕ континентов/суши-моря (bake_continents_tiles.py,
# bake_land_sea_tiles.py — там гигантские слитые полигоны, x8 ощутимо дороже,
# оставлены на x4). Раньше здесь стояло 4 — поднято до общего правила.
SUPERSAMPLE = 8

# Максимум диапазона кодирования (метры) — запас над реальной макс. глубиной
# региона, чтобы 16-битное кодирование не срезало дно впадин.
MAX_DEPTH_M = 6000.0


def project(lon: float, lat: float) -> tuple:
    lat = max(-85.05112878, min(85.05112878, lat))
    x = (lon + 180.0) / 360.0 * WORLD_PX
    lat_rad = math.radians(lat)
    y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
    return x, y


def main():
    lon0, lat0, lon1, lat1 = REGION_LONLAT
    x0, y1 = project(lon0, lat0)  # lat0 (южная граница) -> больший y
    x1, y0 = project(lon1, lat1)  # lat1 (северная граница) -> меньший y
    out_w = int(round((x1 - x0) * SUPERSAMPLE))
    out_h = int(round((y1 - y0) * SUPERSAMPLE))
    print(f"target Web Mercator window: {out_w}x{out_h} px (x{SUPERSAMPLE}, world px {x0:.1f},{y0:.1f} .. {x1:.1f},{y1:.1f})")

    with rasterio.open(SRC_TIF) as src:
        dst_crs = "EPSG:3857"
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        # Источник (GMRT, склейка GEBCO+доп. съёмок) содержит настоящие
        # пропуски данных (NaN, ~0.09% сетки — дыры на стыках съёмок). Без
        # src_nodata/dst_nodata reproject() либо портит соседние пиксели
        # мусорными значениями от билинейного смешивания с NaN, либо (раз
        # dst изначально нулевой) оставляет там elevation=0 — то и другое
        # ошибочно классифицируется как "мелководье"/"бездна" (белые/чёрные
        # крапинки на картинке, замечено пользователем 2026-07-10).
        dst = np.full((height, width), np.nan, dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=np.nan,
            dst_transform=transform,
            dst_crs=dst_crs,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
        elevation = dst

        # Пропуски после репроекции — заполняем ближайшим валидным соседом
        # (дыры единичные и редкие, nearest-fill незаметен на глаз), а не
        # оставляем NaN/0 — иначе они не проходят через is_sea/depth
        # классификацию честно.
        invalid = np.isnan(elevation)
        if invalid.any():
            _, idx = distance_transform_edt(invalid, return_distances=True, return_indices=True)
            elevation = elevation[tuple(idx)]
            print(f"filled {int(invalid.sum())} nodata px ({100.0 * invalid.sum() / invalid.size:.3f}%) via nearest-neighbor")

    # elevation: метры, суша положительная, море отрицательное (стандарт GMRT/GEBCO)
    depth = -elevation  # глубина в метрах, положительная под водой
    is_sea = elevation <= 0.0
    depth_clamped = np.clip(depth, 0.0, MAX_DEPTH_M)
    depth_clamped[~is_sea] = 0.0

    # Ресайзим СЫРУЮ глубину (float) и маску моря NEAREST — категориальная
    # маска и слабо меняющееся поле метров не должны сглаживаться (иначе на
    # границе суша/море появятся выдуманные промежуточные значения глубины).
    # Кодирование в 16-битные R/G-байты делаем ПОСЛЕ ресайза.
    depth_img = Image.fromarray(depth_clamped.astype(np.float32), mode="F")
    depth_img = depth_img.resize((out_w, out_h), Image.NEAREST)
    depth_resized = np.array(depth_img)

    sea_img = Image.fromarray((is_sea.astype(np.uint8) * 255), mode="L")
    sea_img = sea_img.resize((out_w, out_h), Image.NEAREST)
    sea_resized = np.array(sea_img) > 127

    norm16 = np.round(np.clip(depth_resized, 0.0, MAX_DEPTH_M) / MAX_DEPTH_M * 65535.0).astype(np.uint32)
    r = (norm16 // 256).astype(np.uint8)
    g = (norm16 % 256).astype(np.uint8)
    b = np.zeros_like(r)
    a = np.where(sea_resized, 255, 0).astype(np.uint8)
    rgba = np.stack([r, g, b, a], axis=-1)

    img = Image.fromarray(rgba, mode="RGBA")
    img.save(OUT_PNG)

    total_sea = int(sea_resized.sum())
    sea_depths = depth_resized[sea_resized]
    if total_sea:
        print(f"depth range over sea: min={sea_depths.min():.0f}м max={sea_depths.max():.0f}м mean={sea_depths.mean():.0f}м")
    print(f"saved -> {OUT_PNG} ({out_w}x{out_h}), max_depth_m={MAX_DEPTH_M:.0f}")

    # Мировой bbox + max_depth_m рядом с картинкой — чтобы GDScript-слой
    # (SeaZonesLayer.gd) декодировал текстуру и позиционировал спрайт
    # ТЕМИ ЖЕ числами, без дублирования вручную.
    import json
    bbox_path = OUT_PNG.rsplit(".", 1)[0] + "_bbox.json"
    with open(bbox_path, "w", encoding="utf-8") as f:
        json.dump({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "world_px": WORLD_PX, "max_depth_m": MAX_DEPTH_M}, f)
    print(f"saved -> {bbox_path}")


if __name__ == "__main__":
    main()
