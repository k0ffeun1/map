"""Офлайн-запекание слоя "Клетки (тест: Ла-Корунья)" (клавиша C) — та же
идея, что у bake_provinces_iberia_tiles.py, но сильно проще: одна маленькая
провинция (assets/cells_test.json, ~37x39 мировых px, 4 клетки), никаких
щелей между соседями (клетки нарезаны intersection() из ОДНОГО контура,
build_cells_test.py) и БЕЗ границы между клетками (alpha=0, решение
пользователя 2026-07-11, см. BORDER_STYLE["cell"] в TileMapViewer.gd) —
поэтому здесь нет ни GAP_FIX_PX, ни _draw_borders_from_fill, только заливка.

Регион запекания — bbox самих данных (вся провинция целиком), с небольшим
запасом, а не общий REGION_LONLAT — слой самодостаточный, не привязан к
общему тестовому региону Иберии/Галисии.

Цвет клетки — ТОТ ЖЕ хэш по золотому сечению от индекса, что и
IrregularCellProvider._load_data (idx * 0.61803398875), с ТЕМИ ЖЕ
saturation/value/alpha, что передаются в TileMapViewer.gd для живого слоя
"C" (0.55, 0.55, 0.95) — если один поменяется, поменяй и другой.

SUPERSAMPLE=8 — по общему правилу проекта (см. _preview_sea_depth.py).
"""
import colorsys
import json
import math
import os
import time

import numpy as np
from PIL import Image, ImageChops, ImageDraw
from shapely.geometry import Polygon

WORLD_PX = 8192.0
TILE_PX = 1024  # как raster_px у живого слоя "C" (IrregularCellProvider.new(..., raster_px=1024))
SUPERSAMPLE = 8
BAKE_MAX_Z = 7
OUT_DIR = "assets/tiles_bundle/cells_test_baked"
SRC = "assets/cells_test.json"

MIN_SCALE = 2.0
MARGIN_PX = 4
PAD_WORLD_PX = 2.0  # запас вокруг bbox данных, мировые px

FILL_ALPHA = 0.55
SATURATION = 0.55
VALUE = 0.95


def _resize_premultiplied(img: Image.Image, size: tuple) -> Image.Image:
	"""См. bake_provinces_iberia_tiles.py — премультипликация альфы перед
	LANCZOS-ресайзом, иначе тёмный ободок на границе заливка<->прозрачность."""
	r, g, b, a = img.split()
	premult_img = Image.merge("RGB", tuple(ImageChops.multiply(ch, a) for ch in (r, g, b)))
	premult_resized = premult_img.resize(size, Image.LANCZOS)
	alpha_resized = a.resize(size, Image.LANCZOS)

	p = np.asarray(premult_resized).astype(np.float32)
	a2 = np.asarray(alpha_resized).astype(np.float32)
	safe_a = np.where(a2 > 0, a2, 1.0)
	rgb_out = np.clip(p / (safe_a[..., None] / 255.0), 0, 255)
	rgb_out = np.where(a2[..., None] > 0, rgb_out, 0)
	out = np.dstack([rgb_out, a2]).astype(np.uint8)
	return Image.fromarray(out, mode="RGBA")


def _cell_color(idx: int) -> tuple:
	hue = math.fmod(float(idx) * 0.61803398875, 1.0)
	r, g, b = colorsys.hsv_to_rgb(hue, SATURATION, VALUE)
	return (round(r * 255), round(g * 255), round(b * 255), round(FILL_ALPHA * 255))


def main() -> None:
	t0 = time.time()
	data = json.load(open(SRC, encoding="utf-8"))
	raw_cells = data["cells"]
	print(f"[{time.time()-t0:.1f}s] клеток: {len(raw_cells)}")

	cells = []
	for idx, c in enumerate(raw_cells):
		rings = c.get("rings", [])
		if not rings or len(rings[0]) < 3:
			continue
		color = _cell_color(idx)
		try:
			poly = Polygon(rings[0], rings[1:])
			if not poly.is_valid:
				poly = poly.buffer(0)
		except Exception:
			continue
		if poly.is_empty:
			continue
		ext = list(poly.exterior.coords)
		holes = [list(h.coords) for h in poly.interiors]
		bbx = [p[0] for p in ext]
		bby = [p[1] for p in ext]
		cells.append({
			"rings": [ext] + holes,
			"bbox": [min(bbx), min(bby), max(bbx), max(bby)],
			"color": color,
		})

	rx0 = min(c["bbox"][0] for c in cells) - PAD_WORLD_PX
	ry0 = min(c["bbox"][1] for c in cells) - PAD_WORLD_PX
	rx1 = max(c["bbox"][2] for c in cells) + PAD_WORLD_PX
	ry1 = max(c["bbox"][3] for c in cells) + PAD_WORLD_PX
	print(f"[{time.time()-t0:.1f}s] регион данных (мировые px): [{rx0:.1f},{ry0:.1f},{rx1:.1f},{ry1:.1f}]")

	os.makedirs(OUT_DIR, exist_ok=True)

	written = 0
	skipped_empty = 0
	for z in range(BAKE_MAX_Z + 1):
		n = 1 << z
		tile_world = WORLD_PX / n
		supersample = max(SUPERSAMPLE, math.ceil(MIN_SCALE * tile_world / TILE_PX))
		render_px = TILE_PX * supersample
		scale = render_px / tile_world
		margin_render_px = MARGIN_PX * supersample

		tx_range = range(max(0, int(rx0 / tile_world) - 1), min(n, int(rx1 / tile_world) + 2))
		ty_range = range(max(0, int(ry0 / tile_world) - 1), min(n, int(ry1 / tile_world) + 2))

		for ty in ty_range:
			t0y = ty * tile_world
			t1y = t0y + tile_world
			for tx in tx_range:
				t0x = tx * tile_world
				t1x = t0x + tile_world

				hits = [c for c in cells
						if not (c["bbox"][2] < t0x or c["bbox"][0] > t1x
								or c["bbox"][3] < t0y or c["bbox"][1] > t1y)]
				if not hits:
					skipped_empty += 1
					continue

				canvas_px = render_px + 2 * margin_render_px
				out_canvas_px = TILE_PX + 2 * MARGIN_PX
				ss = supersample
				reach = 4 * ss
				minx = min(c["bbox"][0] for c in hits)
				miny = min(c["bbox"][1] for c in hits)
				maxx = max(c["bbox"][2] for c in hits)
				maxy = max(c["bbox"][3] for c in hits)
				px0 = int((minx - t0x) * scale + margin_render_px) - reach
				py0 = int((miny - t0y) * scale + margin_render_px) - reach
				px1 = int(math.ceil((maxx - t0x) * scale + margin_render_px)) + reach
				py1 = int(math.ceil((maxy - t0y) * scale + margin_render_px)) + reach
				px0 = max(0, (px0 // ss) * ss)
				py0 = max(0, (py0 // ss) * ss)
				px1 = min(canvas_px, ((px1 + ss - 1) // ss) * ss)
				py1 = min(canvas_px, ((py1 + ss - 1) // ss) * ss)

				img = Image.new("RGBA", (px1 - px0, py1 - py0), (0, 0, 0, 0))
				draw = ImageDraw.Draw(img, "RGBA")

				def to_px(ring):
					return [((x - t0x) * scale + margin_render_px - px0,
							 (y - t0y) * scale + margin_render_px - py0) for x, y in ring]

				for c in hits:
					pts = to_px(c["rings"][0])
					if len(pts) >= 3:
						draw.polygon(pts, fill=c["color"])
					for hole in c["rings"][1:]:
						hpts = to_px(hole)
						if len(hpts) >= 3:
							draw.polygon(hpts, fill=(0, 0, 0, 0))

				img = _resize_premultiplied(img, ((px1 - px0) // ss, (py1 - py0) // ss))
				out_img = Image.new("RGBA", (out_canvas_px, out_canvas_px), (0, 0, 0, 0))
				out_img.paste(img, (px0 // ss, py0 // ss))
				out_img = out_img.crop((MARGIN_PX, MARGIN_PX, MARGIN_PX + TILE_PX, MARGIN_PX + TILE_PX))
				out_img.save(f"{OUT_DIR}/{z}_{tx}_{ty}.png", optimize=True)
				written += 1

		print(f"[{time.time()-t0:.1f}s] z={z}: готово", flush=True)

	print(f"[{time.time()-t0:.1f}s] записано {written} тайлов, пропущено пустых {skipped_empty}")


if __name__ == "__main__":
	main()
