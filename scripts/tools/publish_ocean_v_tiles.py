# -*- coding: utf-8 -*-
"""
Публикация проверенного результата запекания нового слоя 2 (см.
bake_ocean_v_base_depth_tiles.py/bake_ocean_v_shallow_tiles.py) из черновой
папки build_artifacts/ocean_v_final/ (вне res://, в .gitignore) в рабочую
runtime-папку assets/tiles_bundle/ocean_v_final/, которую грузит
TileMapViewer.gd.

Копирует ТОЛЬКО после проверки целостности — не трогает build_artifacts/ и
не трогает живой V/старый слой 2 (assets/tiles_bundle/world_ocean_baked).

Проверки:
  - оба manifest.json (base_depth/shallow) существуют и валидный JSON;
  - profile_hash в manifest совпадает с ТЕКУЩИМ assets/config/ocean_v_bake_profile.json
    (иначе публикуем тайлы, запечённые под другие параметры, чем сейчас
    зафиксированы — расхождение молча разъедет визуал);
  - каждый PNG открывается (PIL.Image.verify()) без ошибок.

Использование:
    python scripts/tools/publish_ocean_v_tiles.py
    python scripts/tools/publish_ocean_v_tiles.py --force   # публиковать, даже если profile_hash разошёлся
"""
import hashlib
import json
import os
import shutil
import sys

from PIL import Image

PROFILE_PATH = "assets/config/ocean_v_bake_profile.json"
SRC_ROOT = "build_artifacts/ocean_v_final"
DST_ROOT = "assets/tiles_bundle/ocean_v_final"

BUNDLES = ["base_depth", "shallow"]


def profile_hash(profile: dict) -> str:
    raw = json.dumps(profile, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def verify_pngs(src_dir: str) -> list:
    """Возвращает список повреждённых файлов (пустой — всё ок)."""
    bad = []
    for name in os.listdir(src_dir):
        if not name.endswith(".png"):
            continue
        path = f"{src_dir}/{name}"
        try:
            with Image.open(path) as img:
                img.verify()
        except Exception as e:
            bad.append((path, str(e)))
    return bad


def main() -> None:
    force = "--force" in sys.argv
    current_profile = json.load(open(PROFILE_PATH, encoding="utf-8"))
    current_hash = profile_hash(current_profile)

    ok = True
    for bundle in BUNDLES:
        src_dir = f"{SRC_ROOT}/{bundle}"
        manifest_path = f"{SRC_ROOT}/manifests/{bundle}_manifest.json"

        if not os.path.isdir(src_dir):
            print(f"[{bundle}] нет папки {src_dir} — пропущен", file=sys.stderr)
            ok = False
            continue
        if not os.path.exists(manifest_path):
            print(f"[{bundle}] нет manifest {manifest_path} — публикация запрещена", file=sys.stderr)
            ok = False
            continue

        manifest = json.load(open(manifest_path, encoding="utf-8"))
        if manifest.get("profile_hash") != current_hash and not force:
            print(f"[{bundle}] profile_hash в manifest ({manifest.get('profile_hash')}) "
                  f"не совпадает с текущим профилем ({current_hash}) — тайлы запечены под "
                  f"другие параметры. Перезапеки или используй --force.", file=sys.stderr)
            ok = False
            continue

        print(f"[{bundle}] проверка PNG в {src_dir}...", flush=True)
        bad = verify_pngs(src_dir)
        if bad:
            print(f"[{bundle}] найдены повреждённые PNG:", file=sys.stderr)
            for path, err in bad:
                print(f"    {path}: {err}", file=sys.stderr)
            ok = False
            continue

        print(f"[{bundle}] OK, копирую -> {DST_ROOT}/{bundle}", flush=True)

    if not ok:
        print("Публикация ОТМЕНЕНА — есть непройденные проверки (см. выше).", file=sys.stderr)
        sys.exit(1)

    os.makedirs(DST_ROOT, exist_ok=True)
    for bundle in BUNDLES:
        src_dir = f"{SRC_ROOT}/{bundle}"
        dst_dir = f"{DST_ROOT}/{bundle}"
        if os.path.isdir(dst_dir):
            shutil.rmtree(dst_dir)
        shutil.copytree(src_dir, dst_dir)

        manifest_path = f"{SRC_ROOT}/manifests/{bundle}_manifest.json"
        shutil.copy(manifest_path, f"{dst_dir}/manifest.json")

    print("Публикация завершена.", flush=True)


if __name__ == "__main__":
    main()


