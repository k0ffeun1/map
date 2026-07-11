"""Офлайн-запекание ГЛАВНОГО слоя "Суша/Море" (клавиша `-`) в готовые PNG-тайлы.

Тот же повод, что и у bake_continents_tiles.py: слой строится живым
scan-line рендером в IrregularCellProvider.gd, а тут ОДНА клетка суши
(слитая Евразия) — 27830 точек контура, вторая (Америки) — 22406, суммарно
по всем клеткам 125026 точек (см. assets/land_sea.json) — заметно тяжелее
даже континентов. Печём так же — по одному разу офлайн, а не на лету.

assets/land_sea.json остаётся источником правды для игровой ЛОГИКИ (клик
"суша или море" и т.п., см. TODO.md) — картинки этого не заменяют.

Цвета/border ТОЧНО повторяют вызов IrregularCellProvider.new(...) для
суши/моря в TileMapViewer.gd (border_color=(0.10,0.08,0.06,0.8),
land_color=(0.55,0.50,0.35,0.6)) и BORDER_WIDTH=1.4 из самого
IrregularCellProvider.gd — если один поменяется, поменяй и другой.
"""
import json
import math
import os
import time

from PIL import Image, ImageDraw

WORLD_PX = 8192.0
TILE_PX = 256
# ИСКЛЮЧЕНИЕ из общего правила "SUPERSAMPLE=8 на всех запеканиях" (решение
# пользователя 2026-07-11), см. bake_continents_tiles.py — весь мир целиком.
SUPERSAMPLE = 4  # рендерим в TILE_PX*SUPERSAMPLE, потом сжимаем LANCZOS.
BAKE_MAX_Z = 7
OUT_DIR = "assets/tiles_bundle/land_sea_baked"
SRC = "assets/land_sea.json"

# См. bake_continents_tiles.py — на низком зуме (мало пикселей на мировую
# единицу) тонкие детали контура (проливы и т.п.) у гигантских полигонов
# (Евразия — 27830 точек) могут схлопнуться в под-пиксельную полосу и дать
# ложную сплошную линию через тайл. Держим минимум px/мировая-единица.
MIN_SCALE = 2.0

# Тот же приём стыковки тайлов, что и в bake_continents_tiles.py — рендерим
# с запасом, сжимаем LANCZOS ВМЕСТЕ с запасом, обрезаем ровно до тайла.
MARGIN_PX = 4

BORDER_WIDTH = 1.4  # мировые px — как BORDER_WIDTH в IrregularCellProvider.gd.
BORDER_COLOR = (26, 20, 15, 204)   # Color(0.10, 0.08, 0.06, 0.8) -> 0..255
MAX_BORDER_PX = 2  # потолок толщины в пикселях тайла — иначе на z7 "плывёт" (см. continents).

LAND_COLOR = (140, 127, 89, 153)   # Color(0.55, 0.50, 0.35, 0.6) -> 0..255


def main() -> None:
	t0 = time.time()
	data = json.load(open(SRC, encoding="utf-8"))
	cells = data["cells"]
	print(f"[{time.time()-t0:.1f}s] cells: {len(cells)}")

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
		margin_world = margin_render_px / scale
		pad = BORDER_WIDTH * 2.0 + margin_world
		border_w_px = max(1, min(MAX_BORDER_PX * supersample, round(BORDER_WIDTH * scale)))

		for ty in range(n):
			t0y = ty * tile_world
			t1y = t0y + tile_world
			for tx in range(n):
				t0x = tx * tile_world
				t1x = t0x + tile_world

				hits = []
				for c in cells:
					bx0, by0, bx1, by1 = c["bbox"]
					if bx1 < t0x - pad or bx0 > t1x + pad or by1 < t0y - pad or by0 > t1y + pad:
						continue
					hits.append(c)
				if not hits:
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
						draw.polygon(pts, fill=LAND_COLOR)
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

		print(f"[{time.time()-t0:.1f}s] z={z}: готово ({n}x{n} тайлов)")

	print(f"[{time.time()-t0:.1f}s] записано {written} тайлов, пропущено пустых {skipped_empty}")

	total_bytes = sum(os.path.getsize(f"{OUT_DIR}/{f}") for f in os.listdir(OUT_DIR))
	print(f"[{time.time()-t0:.1f}s] размер на диске: {total_bytes/1024/1024:.2f} МБ ({written} файлов)")


if __name__ == "__main__":
	main()
