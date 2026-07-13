# -*- coding: utf-8 -*-
"""
Офлайн-запекание "нижней" (под провинциями) части нового слоя 2 — точная
копия внешнего вида живого слоя V (см. assets/config/ocean_v_bake_profile.json
и аудит в CLAUDE.md/задаче 2026-07-13): базовая плоская заливка на ВЕСЬ мир
(БЕЗ вырезания геометрии provinces.json/world_ocean.json — как и у живого
SolidColorTileProvider слоя V, острова не дырявятся) + непрерывный градиент
реальной глубины GEBCO_2024 поверх, только там, где есть данные (два
региона профиля: west_europe, mariana_trench).

НЕ печёт мелководье — та часть рисуется ВЫШЕ провинций, отдельный скрипт
bake_ocean_v_shallow_tiles.py (см. докстринг там же).

Источник маски море/суша для наложения глубины — ВЕКТОРНЫЙ
assets/world_ocean.json (не знак высоты GEBCO — тот же баг с польдерами
Нидерландов, что уже исправлен в build_sea_depth_west_europe.py).

Использование:
    python scripts/tools/bake_ocean_v_base_depth_tiles.py \
        --region=-12.25,34.15,6.75,45.80 --max-z=7 --force

    python scripts/tools/bake_ocean_v_base_depth_tiles.py --full --max-z=7 --resume
"""
import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from PIL import Image, ImageDraw
from shapely.geometry import Polygon
from shapely.ops import unary_union

WORLD_PX = 8192.0
EARTH_R = 6378137.0

PROFILE_PATH = "assets/config/ocean_v_bake_profile.json"
OCEAN_SRC = "assets/world_ocean.json"
GEBCO_DIR = "scripts/tools/_work/gebco_2024_world"
GEBCO_QUADRANTS = [
    (lon0, lat0, lon0 + 90.0, lat0 + 90.0)
    for lon0 in (-180.0, -90.0, 0.0, 90.0)
    for lat0 in (-90.0, 0.0)
]

OUT_DIR = "build_artifacts/ocean_v_final/base_depth"
MANIFEST_PATH = "build_artifacts/ocean_v_final/manifests/base_depth_manifest.json"

# Береговая маска (для смешения глубины с базовой заливкой) рендерится в
# повышенном разрешении supersample, но сама глубина семплируется не выше
# этого предела — иначе на z0/z1 (гигантская канва) отдельные float32-массивы
# на тайл переваливают за ГБ памяти (см. п.6 задачи/докстринг
# bake_world_ocean_tiles.py::DEPTH_SAMPLE_MAX_PX). Итоговый тайл всё равно
# 1024x1024 (см. profile.render.tile_px).
DEPTH_SAMPLE_MAX_PX = 1024


def load_profile() -> dict:
    return json.load(open(PROFILE_PATH, encoding="utf-8"))


def profile_hash(profile: dict) -> str:
    raw = json.dumps(profile, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


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


def lonlat_bbox_to_world_px(bbox_lonlat: list) -> tuple:
    lon0, lat0, lon1, lat1 = bbox_lonlat
    x0, y0 = project(lon0, lat1)
    x1, y1 = project(lon1, lat0)
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _gebco_path(lon0: float, lat0: float, lon1: float, lat1: float) -> str:
    return f"{GEBCO_DIR}/gebco_2024_sub_ice_n{lat1:.1f}_s{lat0:.1f}_w{lon0:.1f}_e{lon1:.1f}.tif"


def open_gebco_sources() -> list:
    out = []
    for (lon0, lat0, lon1, lat1) in GEBCO_QUADRANTS:
        path = _gebco_path(lon0, lat0, lon1, lat1)
        if not os.path.exists(path):
            print(f"GEBCO не найден: {path} — глубина не запекается для затронутых тайлов", flush=True)
            for src in out:
                src.close()
            return []
        out.append(rasterio.open(path))
    return out


def _tile_dst_transform(t0x: float, t0y: float, canvas_span_wpx: float, canvas_px: int) -> rasterio.Affine:
    k = 2.0 * math.pi * EARTH_R / WORLD_PX
    origin_x = k * t0x - math.pi * EARTH_R
    origin_y = math.pi * EARTH_R - k * t0y
    a = k * canvas_span_wpx / canvas_px
    e = -k * canvas_span_wpx / canvas_px
    return rasterio.Affine(a, 0.0, origin_x, 0.0, e, origin_y)


def sample_gebco_depth_m(gebco_sources: list, t0x: float, t0y: float,
                          canvas_span_wpx: float, sample_px: int) -> np.ndarray:
    """Сырая (некламп нутая) глубина в метрах, NaN там, где нет данных ни в
    одном квадранте (суша по высоте не считается — маска моря берётся
    отдельно из world_ocean.json, см. sea_mask_for_tile)."""
    dst_transform = _tile_dst_transform(t0x, t0y, canvas_span_wpx, sample_px)
    combined = np.full((sample_px, sample_px), np.nan, dtype=np.float32)

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
    return -combined  # elevation -> глубина (положительная под водой)


def depth_m_to_rgb(depth_m: np.ndarray, region: dict, depth_profile: dict) -> np.ndarray:
    max_depth_m = float(region["max_depth_m"])
    depth_clamped = np.clip(np.nan_to_num(depth_m, nan=0.0), 0.0, max_depth_m)

    shelf = hex_to_rgb(depth_profile["shelf_color"])
    mid = hex_to_rgb(depth_profile["mid_color"])
    deep = hex_to_rgb(depth_profile["deep_color"])
    abyss = hex_to_rgb(depth_profile["abyss_color"])
    gamma = float(depth_profile["gradient_gamma"])
    mid_point = float(depth_profile["mid_point"])
    abyss_threshold_m = float(depth_profile["abyss_threshold_m"])

    t = depth_clamped / max_depth_m
    t_curved = np.power(t, gamma)
    frac_low = np.clip(t_curved / mid_point, 0.0, 1.0)
    frac_high = np.clip((t_curved - mid_point) / (1.0 - mid_point), 0.0, 1.0)
    below = t_curved < mid_point

    rgb = np.empty(depth_m.shape + (3,), dtype=np.float32)
    for ch in range(3):
        low_val = shelf[ch] + (mid[ch] - shelf[ch]) * frac_low
        high_val = mid[ch] + (deep[ch] - mid[ch]) * frac_high
        rgb[:, :, ch] = np.where(below, low_val, high_val)

    depth_real = np.nan_to_num(depth_m, nan=-1.0)  # некламп нутая, для порога бездны
    is_abyss = depth_real >= abyss_threshold_m
    for ch in range(3):
        rgb[:, :, ch] = np.where(is_abyss, abyss[ch], rgb[:, :, ch])

    return np.clip(rgb, 0, 255).astype(np.uint8)


def build_ocean_union():
    data = json.load(open(OCEAN_SRC, encoding="utf-8"))
    polys = []
    for c in data["cells"]:
        rings = c.get("rings", [])
        if not rings or len(rings[0]) < 3:
            continue
        p = Polygon(rings[0], rings[1:])
        if not p.is_valid:
            p = p.buffer(0)
        polys.append(p)
    return unary_union(polys), data["cells"]


def sea_mask_for_tile(ocean_cells: list, t0x: float, t0y: float, tile_world: float,
                       canvas_px: int, supersample: int) -> np.ndarray:
    """Растеризует world_ocean.json (векторная маска суша/море) в супер-
    сэмплированное разрешение, потом сжимает LANCZOS до canvas_px — гладкий
    берег без зубцов, как у живого V (см. п.6 задачи)."""
    render_px = canvas_px * supersample
    scale = render_px / tile_world
    img = Image.new("L", (render_px, render_px), 0)
    draw = ImageDraw.Draw(img)
    pad = tile_world * 0.02
    for c in ocean_cells:
        bx0, by0, bx1, by1 = c["bbox"]
        if bx1 < t0x - pad or bx0 > t0x + tile_world + pad or by1 < t0y - pad or by0 > t0y + tile_world + pad:
            continue
        rings = c["rings"]
        pts = [((x - t0x) * scale, (y - t0y) * scale) for x, y in rings[0]]
        if len(pts) >= 3:
            draw.polygon(pts, fill=255)
        for hole in rings[1:]:
            hpts = [((x - t0x) * scale, (y - t0y) * scale) for x, y in hole]
            if len(hpts) >= 3:
                draw.polygon(hpts, fill=0)
    small = img.resize((canvas_px, canvas_px), Image.LANCZOS)
    return np.array(small)


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", type=str, default=None, help="lon0,lat0,lon1,lat1")
    ap.add_argument("--max-z", type=int, default=None)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--force", action="store_true")
    return ap.parse_args()


def main() -> None:
    t0 = time.time()
    args = parse_args()
    profile = load_profile()
    tile_px = int(profile["render"]["tile_px"])
    supersample = int(profile["render"]["supersample"])
    max_z = args.max_z if args.max_z is not None else int(profile["render"]["max_z"])
    base_rgb = hex_to_rgb(profile["base_color"])
    depth_profile = profile["depth"]
    regions = profile["depth_regions"]

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)

    if not args.full and not args.region:
        print("Нужно указать --region=lon0,lat0,lon1,lat1 или --full", file=sys.stderr)
        sys.exit(1)

    print(f"[{time.time()-t0:.1f}s] загрузка world_ocean.json (маска моря)...", flush=True)
    _, ocean_cells = build_ocean_union()

    gebco_sources = open_gebco_sources()
    print(f"[{time.time()-t0:.1f}s] GEBCO квадрантов открыто: {len(gebco_sources)}", flush=True)

    region_px_list = []
    for r in regions:
        region_px_list.append((r, lonlat_bbox_to_world_px(r["region_lonlat"])))

    written = 0
    skipped_existing = 0
    skipped_flat = 0
    tile_count_by_z: dict = {}

    for z in range(max_z + 1):
        n = 1 << z
        tile_world = WORLD_PX / n

        if args.full:
            tx_range = range(n)
            ty_range = range(n)
        else:
            lon0, lat0, lon1, lat1 = [float(v) for v in args.region.split(",")]
            rx0, ry0, rx1, ry1 = lonlat_bbox_to_world_px([lon0, lat0, lon1, lat1])
            tx_range = range(max(0, int(rx0 / tile_world) - 1), min(n, int(rx1 / tile_world) + 2))
            ty_range = range(max(0, int(ry0 / tile_world) - 1), min(n, int(ry1 / tile_world) + 2))

        z_count = 0
        for ty in ty_range:
            t0y = ty * tile_world
            for tx in tx_range:
                t0x = tx * tile_world
                out_path = f"{OUT_DIR}/{z}_{tx}_{ty}.png"
                if args.resume and not args.force and os.path.exists(out_path):
                    skipped_existing += 1
                    z_count += 1
                    continue

                # Базовая заливка — ВЕСЬ тайл, без вырезания геометрии (как
                # живой SolidColorTileProvider слоя V).
                canvas = np.empty((tile_px, tile_px, 4), dtype=np.uint8)
                canvas[:, :, 0] = base_rgb[0]
                canvas[:, :, 1] = base_rgb[1]
                canvas[:, :, 2] = base_rgb[2]
                canvas[:, :, 3] = 255

                # Накладываем глубину только там, где тайл пересекает один
                # из регионов профиля.
                for region, (rx0, ry0, rx1, ry1) in region_px_list:
                    if rx1 < t0x or rx0 > t0x + tile_world or ry1 < t0y or ry0 > t0y + tile_world:
                        continue
                    if not gebco_sources:
                        continue
                    sea_mask = sea_mask_for_tile(ocean_cells, t0x, t0y, tile_world, tile_px, supersample)
                    if not sea_mask.any():
                        continue
                    sample_px = min(tile_px, DEPTH_SAMPLE_MAX_PX)
                    depth_m = sample_gebco_depth_m(gebco_sources, t0x, t0y, tile_world, sample_px)
                    rgb = depth_m_to_rgb(depth_m, region, depth_profile)
                    if sample_px != tile_px:
                        rgb = np.array(Image.fromarray(rgb, mode="RGB").resize((tile_px, tile_px), Image.BILINEAR))
                    mask_bool = sea_mask > 127
                    canvas[mask_bool, 0:3] = rgb[mask_bool]

                # Тайл вне обоих регионов профиля (или GEBCO не задел ни
                # одного пикселя) — ОДНОТОННАЯ заливка base_color, побайтово
                # идентичная НА ЛЮБОМ z/x/y с тем же свойством (проверено:
                # 91% тайлов полного мира именно такие). Не сохраняем файл
                # вовсе — StreamedBakedTileProvider.gd подставляет base_color
                # сплошной заливкой сам, когда файла нет (fallback_color в
                # конструкторе), это визуально ТОЧНО то же самое, что
                # сохранённый однотонный PNG, но без лишних тысяч дублей на
                # диске (см. задачу оптимизации 2026-07-13).
                is_flat = (canvas[:, :, 0].min() == canvas[:, :, 0].max() == base_rgb[0]
                           and canvas[:, :, 1].min() == canvas[:, :, 1].max() == base_rgb[1]
                           and canvas[:, :, 2].min() == canvas[:, :, 2].max() == base_rgb[2])
                if is_flat:
                    if os.path.exists(out_path):
                        os.remove(out_path)  # мог остаться от предыдущего прогона до оптимизации
                    skipped_flat += 1
                    z_count += 1
                    continue

                Image.fromarray(canvas, mode="RGBA").save(out_path, optimize=True)
                written += 1
                z_count += 1

        tile_count_by_z[str(z)] = z_count
        print(f"[{time.time()-t0:.1f}s] z={z}: {z_count} тайлов ({skipped_flat} однотонных не сохранено)", flush=True)

    for src in gebco_sources:
        src.close()

    git_commit = ""
    try:
        git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=".", text=True).strip()
    except Exception:
        pass

    manifest = {
        "schema_version": 1,
        "tile_px": tile_px,
        "max_z": max_z,
        "supersample": supersample,
        "source": "GEBCO_2024 + world_ocean.json",
        "profile": profile,
        "profile_hash": profile_hash(profile),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "command": " ".join(sys.argv),
        "mode": "full" if args.full else "region",
        "region_lonlat": None if args.full else args.region,
        "tile_count_by_z": tile_count_by_z,
        "total_tile_count": sum(tile_count_by_z.values()),
        "flat_tiles_not_saved": skipped_flat,
        "fallback_color": profile["base_color"],
        "git_commit": git_commit,
    }
    json.dump(manifest, open(MANIFEST_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"[{time.time()-t0:.1f}s] записано {written} тайлов, пропущено (resume) {skipped_existing}, "
          f"однотонных не сохранено {skipped_flat}", flush=True)
    print(f"manifest -> {MANIFEST_PATH}", flush=True)


if __name__ == "__main__":
    main()
