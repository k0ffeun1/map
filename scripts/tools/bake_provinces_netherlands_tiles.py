"""Bake the small "N" layer into offline PNG tiles.

Source: assets/provinces_netherlands.json
Output: assets/tiles_bundle/provinces_netherlands_baked/{z}_{x}_{y}.png

The JSON remains the source for clicks. These PNGs are only the visual layer.
"""

import colorsys
import json
import math
import os
import time

from PIL import Image, ImageChops, ImageDraw


WORLD_PX = 8192.0
SRC = "assets/provinces_netherlands.json"
OUT_DIR = "assets/tiles_bundle/provinces_netherlands_baked"
TILE_PX = 1024
SUPERSAMPLE = 4
BAKE_MAX_Z = 7
FILL_ALPHA = 1.0
SATURATION = 0.22
VALUE = 0.78
BORDER_COLOR = (156, 156, 156, 255)
BORDER_WIDTH_WORLD_PX = 0.30


def _godot_string_hash(s: str) -> int:
    h = 5381
    for ch in s:
        h = ((h << 5) + h + ord(ch)) & 0xFFFFFFFF
    return h


def _cell_color(idx: int, color_key: str) -> tuple:
    if color_key:
        hue = math.fmod(float(_godot_string_hash(color_key)) * 0.61803398875, 1.0)
    else:
        hue = math.fmod(float(idx) * 0.61803398875, 1.0)
    r, g, b = colorsys.hsv_to_rgb(hue, SATURATION, VALUE)
    return (round(r * 255), round(g * 255), round(b * 255), round(FILL_ALPHA * 255))


def _resize_premultiplied(img: Image.Image, size: tuple) -> Image.Image:
    r, g, b, a = img.split()
    premult_img = Image.merge("RGB", tuple(ImageChops.multiply(ch, a) for ch in (r, g, b)))
    premult_resized = premult_img.resize(size, Image.LANCZOS)
    alpha_resized = a.resize(size, Image.LANCZOS)
    return Image.merge("RGBA", (*premult_resized.split(), alpha_resized))


def _all_bbox(cells: list) -> tuple:
    x0 = min(c["bbox"][0] for c in cells)
    y0 = min(c["bbox"][1] for c in cells)
    x1 = max(c["bbox"][2] for c in cells)
    y1 = max(c["bbox"][3] for c in cells)
    return x0, y0, x1, y1


def main() -> None:
    t0 = time.time()
    data = json.load(open(SRC, encoding="utf-8"))
    cells = []
    for idx, cell in enumerate(data.get("cells", [])):
        rings = cell.get("rings", [])
        if not rings or len(rings[0]) < 3:
            continue
        cells.append({
            "rings": rings,
            "bbox": cell["bbox"],
            "color": _cell_color(idx, str(cell.get("color_key", ""))),
        })
    if not cells:
        raise RuntimeError(f"no cells in {SRC}")

    rx0, ry0, rx1, ry1 = _all_bbox(cells)
    pad = 6.0
    rx0 -= pad
    ry0 -= pad
    rx1 += pad
    ry1 += pad
    os.makedirs(OUT_DIR, exist_ok=True)
    for name in os.listdir(OUT_DIR):
        if name.endswith(".png"):
            os.unlink(os.path.join(OUT_DIR, name))

    written = 0
    skipped = 0
    for z in range(BAKE_MAX_Z + 1):
        n = 1 << z
        tile_world = WORLD_PX / n
        render_px = TILE_PX * SUPERSAMPLE
        scale = render_px / tile_world
        border_width = max(1, int(round(BORDER_WIDTH_WORLD_PX * scale)))
        tx0 = max(0, int(math.floor(rx0 / tile_world)))
        ty0 = max(0, int(math.floor(ry0 / tile_world)))
        tx1 = min(n - 1, int(math.floor(rx1 / tile_world)))
        ty1 = min(n - 1, int(math.floor(ry1 / tile_world)))

        for ty in range(ty0, ty1 + 1):
            t0y = ty * tile_world
            t1y = t0y + tile_world
            for tx in range(tx0, tx1 + 1):
                t0x = tx * tile_world
                t1x = t0x + tile_world
                hits = [
                    c for c in cells
                    if not (c["bbox"][2] < t0x or c["bbox"][0] > t1x
                            or c["bbox"][3] < t0y or c["bbox"][1] > t1y)
                ]
                if not hits:
                    skipped += 1
                    continue

                img = Image.new("RGBA", (render_px, render_px), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img, "RGBA")
                for c in hits:
                    local_rings = []
                    for ring in c["rings"]:
                        pts = [((p[0] - t0x) * scale, (p[1] - t0y) * scale) for p in ring]
                        if len(pts) >= 3:
                            local_rings.append(pts)
                    if not local_rings:
                        continue
                    draw.polygon(local_rings[0], fill=c["color"])
                    for hole in local_rings[1:]:
                        draw.polygon(hole, fill=(0, 0, 0, 0))

                for c in hits:
                    for ring in c["rings"]:
                        pts = [((p[0] - t0x) * scale, (p[1] - t0y) * scale) for p in ring]
                        if len(pts) >= 3:
                            draw.line(pts + [pts[0]], fill=BORDER_COLOR, width=border_width)

                out = _resize_premultiplied(img, (TILE_PX, TILE_PX))
                if out.getbbox() is None:
                    skipped += 1
                    continue
                path = os.path.join(OUT_DIR, f"{z}_{tx}_{ty}.png")
                out.save(path)
                written += 1
        print(f"z{z}: written so far {written}", flush=True)

    print(f"[{time.time() - t0:.1f}s] wrote {written} tiles, skipped {skipped} empty")


if __name__ == "__main__":
    main()
