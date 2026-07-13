# -*- coding: utf-8 -*-
"""
Офлайн-запекание "верхней" (над провинциями) части нового слоя 2 — полоса
мелководья, точная копия живого shallow_water_band.gdshader слоя V (см.
assets/config/ocean_v_bake_profile.json и bake_ocean_v_base_depth_tiles.py,
тот же комплект). Прозрачный фон, только полоса мелководья.

Источник — то же закодированное поле расстояний до берега (16 бит на пиксель,
R = старший байт, G = младший байт), что уже использует живой V:
assets/generated/coast_distance_field_west_europe_tiles/ (manifest.json с
координатами каждого куска в МИРОВЫХ px). Регион ограничен покрытием этого
поля (Иберия + буфер Атлантики) — вне него у живого V мелководья тоже нет.

NEAREST при сэмплировании (не LANCZOS/LINEAR) — глубина/расстояние закодированы
как 2 независимых 8-битных канала, линейная интерполяция канала по отдельности
даёт мусорные промежуточные значения (та же ловушка, что в
bake_world_ocean_tiles.py::_draw_depth_zones).

Использование:
    python scripts/tools/bake_ocean_v_shallow_tiles.py \
        --region=-12.25,34.15,6.75,45.80 --max-z=7 --force
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
from PIL import Image

WORLD_PX = 8192.0

PROFILE_PATH = "assets/config/ocean_v_bake_profile.json"
DISTANCE_FIELD_MANIFEST = "assets/generated/coast_distance_field_west_europe_tiles/manifest.json"
DISTANCE_FIELD_DIR = "assets/generated/coast_distance_field_west_europe_tiles"

OUT_DIR = "build_artifacts/ocean_v_final/shallow"
MANIFEST_PATH = "build_artifacts/ocean_v_final/manifests/shallow_manifest.json"


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


def lonlat_bbox_to_world_px(bbox_lonlat: list) -> tuple:
    lon0, lat0, lon1, lat1 = bbox_lonlat
    x0, y0 = project(lon0, lat1)
    x1, y1 = project(lon1, lat0)
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def smoothstep(edge0: np.ndarray, edge1: np.ndarray, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


_DF_CACHE_MAX = 2  # держим максимум 2 полных декодированных исходных тайла разом (~512МБ на 8000x8000 RGBA)
_df_array_cache: dict = {}
_df_array_order: list = []


def _get_df_array(path: str) -> np.ndarray:
    """LRU (макс. _DF_CACHE_MAX) декодированных исходных тайлов поля
    расстояний — без кэша соседние выходные тайлы одного z заново
    распаковывали бы один и тот же 8000x8000 PNG на каждый вызов (см.
    load_distance_field/MemoryError, из-за которого кэш всех тайлов разом
    убрали, а не заменили на неограниченный по счёту)."""
    if path in _df_array_cache:
        _df_array_order.remove(path)
        _df_array_order.append(path)
        return _df_array_cache[path]
    with Image.open(path) as img:
        arr = np.array(img.convert("RGBA"))
    _df_array_cache[path] = arr
    _df_array_order.append(path)
    while len(_df_array_order) > _DF_CACHE_MAX:
        oldest = _df_array_order.pop(0)
        del _df_array_cache[oldest]
    return arr


def load_distance_field():
    """НЕ декодирует пиксели заранее — каждый исходный тайл поля расстояний
    может быть до 8000x8000 (TILE_MAX_PX в build_coast_distance_field.py),
    т.е. ~192-256МБ на тайл декодированным; держать все 9 (или больше на
    полном мире) в памяти разом валило процесс в MemoryError. Только размер
    (Image.open БЕЗ .load()/.convert() не декодирует пиксели, только читает
    заголовок) — сам файл открывается/декодируется лениво по требованию в
    sample_signed_km_for_tile, максимум один источник в памяти одновременно."""
    manifest = json.load(open(DISTANCE_FIELD_MANIFEST, encoding="utf-8"))
    tiles = []
    for t in manifest["tiles"]:
        path = f"{DISTANCE_FIELD_DIR}/{t['file']}"
        with Image.open(path) as probe:
            size = probe.size
        tiles.append({**t, "path": path, "size": size})
    return manifest, tiles


def sample_signed_km_for_tile(df_tiles: list, encode_min_km: float, encode_max_km: float,
                               t0x: float, t0y: float, tile_world: float, out_px: int) -> np.ndarray:
    """Собирает NEAREST-мозаику куска поля расстояний, попадающего в выходной
    тайл, и декодирует в км со знаком. NaN там, где данных нет вообще (вне
    покрытия coast_distance_field). Каждый исходный тайл открывается и
    декодируется по требованию, не держится в памяти между вызовами (см.
    load_distance_field)."""
    signed_km = np.full((out_px, out_px), np.nan, dtype=np.float32)
    tile_x1, tile_y1 = t0x + tile_world, t0y + tile_world

    for t in df_tiles:
        sx0, sy0, sx1, sy1 = t["x0"], t["y0"], t["x1"], t["y1"]
        ox0, oy0 = max(t0x, sx0), max(t0y, sy0)
        ox1, oy1 = min(tile_x1, sx1), min(tile_y1, sy1)
        if ox1 <= ox0 or oy1 <= oy0:
            continue

        dw, dh = t["size"]
        src_px0 = (ox0 - sx0) / (sx1 - sx0) * dw
        src_py0 = (oy0 - sy0) / (sy1 - sy0) * dh
        src_px1 = (ox1 - sx0) / (sx1 - sx0) * dw
        src_py1 = (oy1 - sy0) / (sy1 - sy0) * dh
        cx0, cy0 = round(src_px0), round(src_py0)
        cx1 = max(cx0 + 1, round(src_px1))
        cy1 = max(cy0 + 1, round(src_py1))
        src_arr = _get_df_array(t["path"])
        crop = Image.fromarray(src_arr[cy0:cy1, cx0:cx1], mode="RGBA")

        tgt_x0 = round((ox0 - t0x) / tile_world * out_px)
        tgt_y0 = round((oy0 - t0y) / tile_world * out_px)
        tgt_x1 = round((ox1 - t0x) / tile_world * out_px)
        tgt_y1 = round((oy1 - t0y) / tile_world * out_px)
        tgt_w, tgt_h = tgt_x1 - tgt_x0, tgt_y1 - tgt_y0
        if tgt_w < 1 or tgt_h < 1:
            continue

        resized = crop.resize((tgt_w, tgt_h), Image.NEAREST)
        arr = np.array(resized)
        combined = arr[:, :, 0].astype(np.uint32) * 256 + arr[:, :, 1].astype(np.uint32)
        km = combined.astype(np.float32) / 65535.0 * (encode_max_km - encode_min_km) + encode_min_km
        signed_km[tgt_y0:tgt_y0 + tgt_h, tgt_x0:tgt_x0 + tgt_w] = km

    return signed_km


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", type=str, default=None, help="lon0,lat0,lon1,lat1")
    ap.add_argument("--max-z", type=int, default=None)
    ap.add_argument("--full", action="store_true",
                     help="Полный мир — но полоса всё равно ограничена покрытием coast_distance_field (Иберия/Атлантика), вне него тайлы просто не пишутся")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--force", action="store_true")
    return ap.parse_args()


def main() -> None:
    t0 = time.time()
    args = parse_args()
    profile = load_profile()
    tile_px = int(profile["render"]["tile_px"])
    max_z = args.max_z if args.max_z is not None else int(profile["render"]["max_z"])
    shallow = profile["shallow"]
    band_rgb = hex_to_rgb(shallow["color"])
    land_margin_km = float(shallow["land_margin_km"])
    sea_margin_km = float(shallow["sea_margin_km"])
    edge_transition_km = float(shallow["edge_transition_km"])

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)

    if not os.path.exists(DISTANCE_FIELD_MANIFEST):
        print(f"Не найден {DISTANCE_FIELD_MANIFEST} — сначала build_coast_distance_field.py", file=sys.stderr)
        sys.exit(1)

    print(f"[{time.time()-t0:.1f}s] загрузка поля расстояний до берега...", flush=True)
    df_manifest, df_tiles = load_distance_field()
    encode_min_km = float(df_manifest["encode_min_km"])
    encode_max_km = float(df_manifest["encode_max_km"])
    cov_x0, cov_y0, cov_x1, cov_y1 = df_manifest["x0"], df_manifest["y0"], df_manifest["x1"], df_manifest["y1"]

    written = 0
    skipped_existing = 0
    skipped_no_coverage = 0
    tile_count_by_z: dict = {}

    for z in range(max_z + 1):
        n = 1 << z
        tile_world = WORLD_PX / n

        if args.region:
            lon0, lat0, lon1, lat1 = [float(v) for v in args.region.split(",")]
            rx0, ry0, rx1, ry1 = lonlat_bbox_to_world_px([lon0, lat0, lon1, lat1])
        else:
            rx0, ry0, rx1, ry1 = cov_x0, cov_y0, cov_x1, cov_y1

        # Полоса физически ограничена покрытием coast_distance_field —
        # пересекаем с ним в любом режиме, чтобы не перебирать тайлы, где
        # заведомо нечего рисовать.
        rx0, ry0 = max(rx0, cov_x0), max(ry0, cov_y0)
        rx1, ry1 = min(rx1, cov_x1), min(ry1, cov_y1)
        if rx1 <= rx0 or ry1 <= ry0:
            tile_count_by_z[str(z)] = 0
            continue

        tx_range = range(max(0, int(rx0 / tile_world) - 1), min(n, int(rx1 / tile_world) + 2))
        ty_range = range(max(0, int(ry0 / tile_world) - 1), min(n, int(ry1 / tile_world) + 2))

        z_count = 0
        for ty in ty_range:
            t0y = ty * tile_world
            for tx in tx_range:
                t0x = tx * tile_world
                if t0x + tile_world < cov_x0 or t0x > cov_x1 or t0y + tile_world < cov_y0 or t0y > cov_y1:
                    skipped_no_coverage += 1
                    continue

                out_path = f"{OUT_DIR}/{z}_{tx}_{ty}.png"
                if args.resume and not args.force and os.path.exists(out_path):
                    skipped_existing += 1
                    z_count += 1
                    continue

                signed_km = sample_signed_km_for_tile(df_tiles, encode_min_km, encode_max_km,
                                                       t0x, t0y, tile_world, tile_px)
                valid = ~np.isnan(signed_km)
                if not valid.any():
                    skipped_no_coverage += 1
                    continue

                km = np.nan_to_num(signed_km, nan=-1e9)
                alpha_land = (km >= -land_margin_km).astype(np.float32)
                alpha_sea = 1.0 - smoothstep(
                    np.float32(sea_margin_km - edge_transition_km),
                    np.float32(sea_margin_km + edge_transition_km), km)
                in_band = alpha_land * alpha_sea * valid.astype(np.float32)

                if not (in_band > 0.001).any():
                    # Не сохраняем полностью прозрачные тайлы.
                    z_count += 1
                    continue

                canvas = np.zeros((tile_px, tile_px, 4), dtype=np.uint8)
                canvas[:, :, 0] = band_rgb[0]
                canvas[:, :, 1] = band_rgb[1]
                canvas[:, :, 2] = band_rgb[2]
                canvas[:, :, 3] = np.clip(in_band * 255.0, 0, 255).astype(np.uint8)

                Image.fromarray(canvas, mode="RGBA").save(out_path, optimize=True)
                written += 1
                z_count += 1

        tile_count_by_z[str(z)] = z_count
        print(f"[{time.time()-t0:.1f}s] z={z}: {z_count} тайлов", flush=True)

    git_commit = ""
    try:
        git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=".", text=True).strip()
    except Exception:
        pass

    manifest = {
        "schema_version": 1,
        "tile_px": tile_px,
        "max_z": max_z,
        "source": "coast_distance_field_west_europe",
        "profile": profile,
        "profile_hash": profile_hash(profile),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "command": " ".join(sys.argv),
        "mode": "full" if args.full else ("region" if args.region else "coverage-only"),
        "region_lonlat": args.region,
        "tile_count_by_z": tile_count_by_z,
        "total_tile_count": sum(tile_count_by_z.values()),
        "git_commit": git_commit,
    }
    json.dump(manifest, open(MANIFEST_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"[{time.time()-t0:.1f}s] записано {written} тайлов, пропущено (пусто/вне покрытия) {skipped_no_coverage}, "
          f"пропущено (resume) {skipped_existing}", flush=True)
    print(f"manifest -> {MANIFEST_PATH}", flush=True)


if __name__ == "__main__":
    main()
