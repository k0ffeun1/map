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
import rasterio
from rasterio.warp import reproject, Resampling
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
# Отключено 2026-07-12 по просьбе пользователя: полосу мелководья теперь
# рисует ТОЛЬКО живой оверлей (_ocean_shallow_sprite в TileMapViewer.gd,
# distance-field shallow_water_band.gdshader) — раньше он дублировался и
# здесь, в PNG, с ДРУГИМИ константами (SEA_MARGIN_KM/цвет), что при
# одновременном показе давало двойную полосу разной ширины/цвета. Флаг
# оставлен (не удалён код) для быстрого отката, если вернётся старый баг
# рассинхрона береговой линии у живого distance-field слоя (см. докстринг
# файла выше — исходная причина, почему мелководье вообще перенесли в бейк).
BAKE_SHALLOW_BAND = False
SHALLOW_COLOR = (0x8A, 0xC6, 0xDA, 255)
LAND_MARGIN_KM = 0.5  # решение пользователя 2026-07-11 (было 0.0)
SEA_MARGIN_KM = 20.0

# Плавное затухание мелководья к открытому морю (2026-07-12) — та же идея,
# что была у живого shallow_water_band.gdshader (edge_transition_km), но без
# растрового distance-field (тот подход уже один раз давал рассинхрон
# береговой линии из-за другого supersample, см. докстринг файла и done.md).
# Вместо этого — N концентрических колец с растущей альфой ближе к берегу;
# края со стороны суши НЕ трогаем (там резкий обрез, как решил пользователь
# для живой версии).
EDGE_TRANSITION_KM = 12.1  # то же число, что OCEAN_SHALLOW_DEFAULT_EDGE_TRANSITION_KM в TileMapViewer.gd
FADE_RING_STEPS = 24  # после LANCZOS-сжатия тайла ступени сглаживаются, визуально гладко

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

# Вся Иберия (материк Испания/Португалия + Балеары, тот же bbox, что у
# build_provinces_iberia.py/build_coast_distance_field.py: (-9.9, 35.95, 4.4,
# 44.0)) + ~200км буфер от берега в море во все стороны — решение пользователя
# 2026-07-12, расширение прежнего теста (был только СЗ Испании/Галисия,
# (-10.5, 41.0, -6.0, 44.5)). Буфер посчитан в градусах на средней широте
# Иберии (~40°, cos40°=0.766): 200км/111.32км = 1.80° по широте,
# 200км/(111.32*0.766) = 2.35° по долготе — приближение, не точный geodesic
# buffer (для отбора тайлов точность не нужна, лишние пустые тайлы просто
# пропускаются, см. skipped_empty ниже).
REGION_LONLAT = (-12.25, 34.15, 6.75, 45.80)

# --- Реальная глубина моря из ГЛОБАЛЬНОГО GEBCO_2024 (2026-07-11/12) ---
# Заменяет старую регионально-ограниченную батиметрию (_load_depth_raster/
# _draw_depth_zones ниже, GMRT/один регион, оставлены неиспользуемыми как
# историческая справка) — GEBCO покрывает весь мир, поэтому цвет заливки
# больше не плоский OCEAN_COLOR, а непрерывный градиент по РЕАЛЬНОЙ глубине,
# ТОЧНО тот же (цвета/gradient_gamma/mid_point), что зафиксирован пользователем
# 2026-07-11 для живой панели "Мелководье (слой 2)" в TileMapViewer.gd
# (OCEAN_DEPTH_DEFAULT_*). Раз это теперь запекается статично, кодирование
# глубины как 16 бит в текстуру (нужное только живому шейдеру) не требуется —
# цвет считается прямо в Python и рисуется как обычный RGBA.
GEBCO_DIR = "scripts/tools/_work/gebco_2024_world"
GEBCO_QUADRANTS = [
    (lon0, lat0, lon0 + 90.0, lat0 + 90.0)
    for lon0 in (-180.0, -90.0, 0.0, 90.0)
    for lat0 in (-90.0, 0.0)
]
EARTH_R = 6378137.0  # тот же сферический радиус, что подразумевает наша Web Mercator формула project()/unproject()


# ВАЖНО: это НЕ "реальный максимум глубины в мире" (Марианская впадина
# ~10935м) — это именно та точка отсчёта, под которую пользователь подобрал
# gradient_gamma/mid_point на живой панели (регион был max_depth_m=6000).
# С 11000 тёмный "глубинный" цвет почти не проявлялся нигде в Атлантике —
# обычная глубина 4000-5600м это лишь ~40-50% кривой, а mid_point=0.7
# требует близости к САМОМУ максимуму диапазона. Настоящие желоба (реже,
# глубже 6000м) просто обрезаются в максимально тёмный цвет клампом ниже,
# а не растягивают кривую под редкое исключение.
DEPTH_MAX_DEPTH_M = 6000.0
DEPTH_COLOR_SHELF = (0x00, 0x9a, 0xcd)   # #009acd — решение пользователя 2026-07-11
DEPTH_COLOR_MID = (0x04, 0x58, 0x8c)     # #04588c
DEPTH_COLOR_DEEP = (0x06, 0x29, 0x62)    # #062962
DEPTH_GRADIENT_GAMMA = 0.8
DEPTH_MID_POINT = 0.7

# 4-й уровень — "бездна" (океанские желоба), решение пользователя 2026-07-12:
# НЕ часть 3-цветной кривой (та настроена под max_depth_m=6000, желоба глубже
# него уже просто клампятся в DEPTH_COLOR_DEEP) — отдельный сплошной цвет
# поверх готового градиента, там где РЕАЛЬНАЯ (некламп нутая) глубина
# превышает порог.
DEPTH_ABYSS_THRESHOLD_M = 9000.0
DEPTH_COLOR_ABYSS = (0x00, 0x12, 0x30)  # #001230

# Глубина — гладкие данные без резких границ (сама береговая линия берётся из
# альфы уже нарисованного полигона-маски, не отсюда), в отличие от векторных
# линий ей не нужен supersample канвы тайла целиком — на z=0/1 канва (из-за
# MIN_SCALE) раздувается до ~16500px, семплирование/градиент на этом размере
# упал по памяти (ArrayMemoryError, ~1ГБ на один float32-массив, несколько
# штук одновременно). Считаем на этом капе, потом обычный bilinear upscale
# до фактического canvas_px перед композитингом с маской.
DEPTH_SAMPLE_MAX_PX = 1024


def _gebco_path(lon0: float, lat0: float, lon1: float, lat1: float) -> str:
    return f"{GEBCO_DIR}/gebco_2024_sub_ice_n{lat1:.1f}_s{lat0:.1f}_w{lon0:.1f}_e{lon1:.1f}.tif"


def open_gebco_sources() -> list:
    """Открывает 8 глобальных GeoTIFF-квадрантов GEBCO_2024 (см.
    _preview_sea_depth.py/done.md — скачаны разово вручную, ~7.1ГБ,
    scripts/tools/_work/ не в git). Возвращает [] и печатает предупреждение,
    если данных нет — вызывающий код должен упасть обратно на плоский
    OCEAN_COLOR, не падать с исключением."""
    out = []
    for (lon0, lat0, lon1, lat1) in GEBCO_QUADRANTS:
        path = _gebco_path(lon0, lat0, lon1, lat1)
        if not os.path.exists(path):
            print(f"GEBCO не найден: {path} — глубина не запекается, плоский OCEAN_COLOR", flush=True)
            for src in out:
                src.close()
            return []
        out.append(rasterio.open(path))
    return out


def _tile_dst_transform(t0x: float, t0y: float, canvas_span_wpx: float, canvas_px: int) -> rasterio.Affine:
    """Аффинное преобразование "пиксель канвы тайла -> метры EPSG:3857",
    БЕЗ обращения к rasterio.warp.calculate_default_transform (та функция
    выводит трансформ из bounds ИСТОЧНИКА — нам нужен трансформ, заданный
    НАШИМ выходным тайлом). Наша project()/unproject() — обычная сферическая
    Web Mercator, отмасштабированная на WORLD_PX, поэтому пересчёт в метры
    EPSG:3857 — точная линейная формула (проверено: R*pi совпадает со
    стандартным пределом Web Mercator ~20037508.34м на lat=85.05113°)."""
    k = 2.0 * math.pi * EARTH_R / WORLD_PX  # метров на единицу "мирового px"
    origin_x = k * t0x - math.pi * EARTH_R
    origin_y = math.pi * EARTH_R - k * t0y
    a = k * canvas_span_wpx / canvas_px       # м/px по x
    e = -k * canvas_span_wpx / canvas_px      # м/px по y (отрицательный — строки идут на юг)
    return rasterio.Affine(a, 0.0, origin_x, 0.0, e, origin_y)


def sample_depth_gradient_rgba(gebco_sources: list, t0x: float, t0y: float,
                                canvas_span_wpx: float, canvas_px: int) -> np.ndarray:
    """Семплирует реальную глубину GEBCO для квадратной канвы тайла
    (t0x..t0x+canvas_span_wpx в мировых px по обеим осям) и красит тем же
    непрерывным 3-цветным градиентом, что и живая панель слоя 2/5. Каждый
    источник-квадрант реджепроецируется НАПРЯМУЮ в EPSG:3857-трансформ этой
    канвы (rasterio сам читает из файла только нужное окно, не весь квадрант) —
    квадранты не пересекаются, поэтому просто берём первое непустое значение
    на каждый пиксель. Возвращает RGBA uint8 (canvas_px, canvas_px, 4)."""
    sample_px = min(canvas_px, DEPTH_SAMPLE_MAX_PX)
    dst_transform = _tile_dst_transform(t0x, t0y, canvas_span_wpx, sample_px)
    combined = np.full((sample_px, sample_px), np.nan, dtype=np.float32)

    # Тайл почти всегда лежит только в 1 (реже 2-4, на границе квадрантов)
    # из 8 квадрантов — пропускаем остальные ДО reproject(), иначе на
    # маленьких тайлах (высокий z, тысячи штук) 7 из 8 вызовов тратятся
    # впустую (не находят данных, но всё равно читают/warp-ят файл).
    lon_left, lat_top = unproject(t0x, t0y)
    lon_right, lat_bottom = unproject(t0x + canvas_span_wpx, t0y + canvas_span_wpx)

    for src in gebco_sources:
        sb = src.bounds
        if sb.right < lon_left or sb.left > lon_right or sb.top < lat_bottom or sb.bottom > lat_top:
            continue
        part = np.full((sample_px, sample_px), np.nan, dtype=np.float32)
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
        gap = np.isnan(combined) & ~np.isnan(part)
        if gap.any():
            combined[gap] = part[gap]

    elevation = np.nan_to_num(combined, nan=1.0)  # NaN (за пределами всех квадрантов, полюса) -> суша/прозрачно
    is_sea = elevation <= 0.0
    depth_m_real = -elevation  # НЕ клампнутая, для порога "бездны" ниже
    depth_m = np.clip(depth_m_real, 0.0, DEPTH_MAX_DEPTH_M)

    t = depth_m / DEPTH_MAX_DEPTH_M
    t_curved = np.power(t, DEPTH_GRADIENT_GAMMA)
    frac_low = np.clip(t_curved / DEPTH_MID_POINT, 0.0, 1.0)
    frac_high = np.clip((t_curved - DEPTH_MID_POINT) / (1.0 - DEPTH_MID_POINT), 0.0, 1.0)
    below = t_curved < DEPTH_MID_POINT

    rgb = np.empty((sample_px, sample_px, 3), dtype=np.float32)
    for ch in range(3):
        low_val = DEPTH_COLOR_SHELF[ch] + (DEPTH_COLOR_MID[ch] - DEPTH_COLOR_SHELF[ch]) * frac_low
        high_val = DEPTH_COLOR_MID[ch] + (DEPTH_COLOR_DEEP[ch] - DEPTH_COLOR_MID[ch]) * frac_high
        rgb[:, :, ch] = np.where(below, low_val, high_val)

    abyss = depth_m_real >= DEPTH_ABYSS_THRESHOLD_M
    for ch in range(3):
        rgb[:, :, ch] = np.where(abyss, DEPTH_COLOR_ABYSS[ch], rgb[:, :, ch])

    alpha = np.where(is_sea, 255, 0).astype(np.uint8)
    rgba = np.dstack([np.clip(rgb, 0, 255).astype(np.uint8), alpha])
    if sample_px != canvas_px:
        rgba = np.array(Image.fromarray(rgba, mode="RGBA").resize((canvas_px, canvas_px), Image.BILINEAR))
    return rgba


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
    inner_aeqd = land_aeqd.buffer(-LAND_MARGIN_KM * 1000.0, quad_segs=16)

    # Сплошная часть (alpha=255) — от берега до начала зоны затухания;
    # дальше N узких колец с растущей к морю прозрачностью (EDGE_TRANSITION_KM,
    # см. константу) — приближение непрерывного градиента, край со стороны
    # суши (inner_aeqd) остаётся резким, как решено для живой версии.
    solid_outer_km = max(LAND_MARGIN_KM, SEA_MARGIN_KM - EDGE_TRANSITION_KM)
    solid_aeqd = land_aeqd.buffer(solid_outer_km * 1000.0, quad_segs=16).difference(inner_aeqd)
    pieces_aeqd = [(solid_aeqd, 255)]

    fade_km_span = SEA_MARGIN_KM - solid_outer_km
    if fade_km_span > 0:
        for i in range(FADE_RING_STEPS):
            d_inner = solid_outer_km + fade_km_span * i / FADE_RING_STEPS
            d_outer = solid_outer_km + fade_km_span * (i + 1) / FADE_RING_STEPS
            ring_aeqd = land_aeqd.buffer(d_outer * 1000.0, quad_segs=16).difference(
                land_aeqd.buffer(d_inner * 1000.0, quad_segs=16))
            frac = 1.0 - (i + 0.5) / FADE_RING_STEPS  # ближе к берегу -> непрозрачнее
            alpha = max(0, min(255, round(255 * frac)))
            pieces_aeqd.append((ring_aeqd, alpha))

    out = []
    for geom_aeqd, alpha in pieces_aeqd:
        if geom_aeqd.is_empty:
            continue
        geom_lonlat = shapely_transform(to_wgs84, geom_aeqd)
        geom_wpx = shapely_transform(lonlat_to_wpx, geom_lonlat)
        if not geom_wpx.is_valid:
            geom_wpx = geom_wpx.buffer(0)
        geom_wpx = geom_wpx.intersection(region_box)
        for ring_set in _explode_rings(geom_wpx):
            ext = ring_set[0]
            xs = [p[0] for p in ext]
            ys = [p[1] for p in ext]
            out.append({"rings": ring_set, "bbox": [min(xs), min(ys), max(xs), max(ys)], "alpha": alpha})
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


def _max_z_arg() -> int:
    """--max-z=N ограничивает верхний уровень запекания (по умолчанию
    BAKE_MAX_Z) — для быстрого превью всего мира на низких zoom-уровнях
    перед дорогим полным прогоном до BAKE_MAX_Z."""
    for arg in sys.argv:
        if arg.startswith("--max-z="):
            return int(arg.split("=", 1)[1])
    return BAKE_MAX_Z


def main() -> None:
    t0 = time.time()
    full_world = "--full" in sys.argv
    max_z = _max_z_arg()
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
        if BAKE_SHALLOW_BAND:
            shallow_cells = _build_shallow_band(ocean_union, (rx0, ry0, rx1, ry1))
            print(f"[{time.time()-t0:.1f}s] полоса мелководья: {len(shallow_cells)} кусков "
                  f"(-{LAND_MARGIN_KM:.0f}км/+{SEA_MARGIN_KM:.0f}км)", flush=True)
        else:
            print(f"[{time.time()-t0:.1f}s] BAKE_SHALLOW_BAND=False — полоса мелководья не "
                  f"печётся, её рисует живой оверлей поверх (см. TileMapViewer.gd)", flush=True)
    else:
        print("--full: полоса мелководья пока не считается (нужен другой метод буфера "
              "для всего мира, не единый AEQD-центр) — только заливка океана.", flush=True)

    depth = None  # старая регионально-ограниченная батиметрия (GMRT) — не используется, см. комментарий у THRESHOLD_SHELF_M

    gebco_sources = open_gebco_sources()
    if gebco_sources:
        print(f"[{time.time()-t0:.1f}s] GEBCO: {len(gebco_sources)} квадрантов открыто, "
              f"реальная глубина будет запечена вместо плоского OCEAN_COLOR", flush=True)

    written = 0
    skipped_empty = 0
    for z in range(max_z + 1):
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

                # Реальная глубина GEBCO (весь мир) заменяет плоский OCEAN_COLOR
                # — та же форма моря (маска = альфа уже нарисованного полигона
                # выше, дырки/берег остаются от world_ocean.json), но цвет
                # берётся из непрерывного градиента по метрам глубины (см.
                # sample_depth_gradient_rgba). Если GEBCO не скачан —
                # gebco_sources пуст, заливка остаётся плоской, как раньше.
                if gebco_sources:
                    sea_mask_arr = np.array(img.split()[3])
                    sea_mask_img = Image.fromarray(
                        np.where(sea_mask_arr > 0, 255, 0).astype(np.uint8), mode="L")
                    canvas_span_wpx = tile_world + 2.0 * margin_world
                    depth_rgba = sample_depth_gradient_rgba(
                        gebco_sources, t0x - margin_world, t0y - margin_world,
                        canvas_span_wpx, canvas_px)
                    depth_img = Image.fromarray(depth_rgba, mode="RGBA")
                    img = Image.composite(depth_img, img, sea_mask_img)
                    draw = ImageDraw.Draw(img, "RGBA")

                # Мелководье — ПОВЕРХ заливки океана, той же геометрией
                # (world_ocean.json), никакого отдельного растра — см.
                # докстринг файла.
                for c in shallow_hits:
                    pts = to_px(c["rings"][0])
                    piece_color = (SHALLOW_COLOR[0], SHALLOW_COLOR[1], SHALLOW_COLOR[2],
                                   c.get("alpha", SHALLOW_COLOR[3]))
                    if len(pts) >= 3:
                        draw.polygon(pts, fill=piece_color)
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

    for src in gebco_sources:
        src.close()

    print(f"[{time.time()-t0:.1f}s] записано {written} тайлов, пропущено пустых {skipped_empty}", flush=True)


if __name__ == "__main__":
    main()
