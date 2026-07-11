"""Офлайн-запекание слоя "Континенты" (клавиша 0) в готовые PNG-тайлы.

Слой строился живым скан-line рендером в IrregularCellProvider.gd — для
нескольких гигантских полигонов (Евразия, Африка, Америки — до ~5900 точек
контура каждый) это заметно тормозило: рендерер проверяет КАЖДОЕ ребро
полигона на КАЖДОЙ из 256 строк тайла, при десятках тысяч точек это
миллионы проверок на один тайл (см. обсуждение в TODO.md/сессии).

Это не игровые данные — просто картинка. Источник правды для игровой логики
("эта клетка принадлежит континенту X") остаётся assets/continents.json,
как и раньше; здесь лишь один раз рисуются PNG того же самого контура для
показа на экране, вместо того чтобы считать его заново при каждом кадре.

Печём до BAKE_MAX_Z=7 (совпадает с интерактивным MAX_Z в TileMapViewer.gd) —
изначально пробовали ограничиться z6 ради экономии места, но это создавало
несостыковку уровней (BakedTileProvider.gd честно говорил "ещё гружусь" за
пределами запечённого, только когда фикс уже был внедрён; ДО фикса —
"тут просто пусто" — из-за чего движок раньше времени выбрасывал подложку
предыдущего уровня зума, и был виден шов/пропажа цвета при переходе через
z7). Проще всего испечь везде одинаково, до самого глубокого уровня.

Цвета/border ТОЧНО повторяют вызов IrregularCellProvider.new(...) для
континентов в TileMapViewer.gd — если один поменяется, поменяй и другой.
"""
import json
import math
import os
import time

from PIL import Image, ImageDraw

WORLD_PX = 8192.0
TILE_PX = 256
# ИСКЛЮЧЕНИЕ из общего правила "SUPERSAMPLE=8 на всех запеканиях" (решение
# пользователя 2026-07-11) — весь мир, гигантские слитые полигоны, x8 здесь
# ощутимо дороже по времени печи, оставлено на x4.
SUPERSAMPLE = 4  # рендерим в TILE_PX*SUPERSAMPLE, потом сжимаем LANCZOS -> сглаженные чёткие края.
# x4 = в 16 раз больше пикселей на тайл при отрисовке (было x2=4x). Число
# тайлов не меняется (по-прежнему до z7, 16384 шт.) — растёт только время
# печи на тайл, зато края контуров/границ ещё чище после LANCZOS-сжатия.
BAKE_MAX_Z = 7
OUT_DIR = "assets/tiles_bundle/continents_baked"
SRC = "assets/continents.json"

# render_px = TILE_PX*SUPERSAMPLE не зависит от z, а tile_world (мировых px на
# тайл) удваивается на каждом уровне К НИЗКОМУ зуму — значит "разрешающая
# способность" рендера (px на мировую единицу) падает вдвое на каждом шаге к
# z0. На z1-z3 её не хватает, чтобы разрешить тонкие детали контура (Босфор,
# пролив Эресунн между Данией/Швецией и т.п. — там, где Европа/Азия после
# Chaikin-сглаживания превратились в гигантские полигоны с 17-23 тыс. точек):
# под-пиксельная перемычка контура заставляет PIL scanline-заливку протянуть
# сплошную горизонтальную полосу через весь тайл. Фикс — держать МИНИМУМ
# px/мировая-единица не ниже MIN_SCALE на всех уровнях, поднимая supersample
# только для низких z (там тайлов мало: z0..z3 = 85 шт. суммарно, дешёво).
MIN_SCALE = 2.0  # px супersampled-рендера на 1 мировую единицу, минимум (= scale на z4 по умолчанию)

# Каждый тайл раньше сжимался LANCZOS НЕЗАВИСИМО от соседей — у фильтра не было
# реальных пикселей ЗА краем тайла, и на верхнем/нижнем ряду получался едва
# другой оттенок, чем в соседнем тайле того же ряда. На сплошном фоне (океан)
# незаметно, а на любом внутреннем крае (озеро, изгиб берега) — тонкая полоса
# через весь ряд тайлов, "плавающая" по широте от зума к зуму (своя тайловая
# сетка на каждом z). Рендерим с запасом MARGIN_PX (в готовых, НЕ супersampled
# px) за каждым краем, сжимаем ВМЕСТЕ с запасом, потом обрезаем ровно до тайла —
# так LANCZOS видит настоящих соседей, и края двух тайлов совпадают.
MARGIN_PX = 4

BORDER_WIDTH = 0.45  # мировые px — ещё тоньше и чётче (было 0.7, до этого 1.4), по просьбе пользователя
BORDER_COLOR = (10, 10, 10, 255)  # почти чёрный, полностью непрозрачный (было тёмно-коричневый 0.75 альфы — мутно)
MAX_BORDER_PX = 2  # потолок толщины в пикселях тайла — на глубоком зуме (z7) иначе разрастается и "плывёт"

# ТОЧНО как continent_colors в TileMapViewer.gd (порядок = "cont" индекс).
CONTINENT_COLORS = [
	(89, 140, 217, 140),   # Европа            Color(0.35,0.55,0.85,0.55)
	(217, 140, 77, 140),   # Азия              Color(0.85,0.55,0.30,0.55)
	(115, 191, 102, 140),  # Африка            Color(0.45,0.75,0.40,0.55)
	(217, 77, 89, 140),    # Северная Америка  Color(0.85,0.30,0.35,0.55)
	(204, 191, 77, 140),   # Южная Америка     Color(0.80,0.75,0.30,0.55)
	(153, 102, 204, 140),  # Океания           Color(0.60,0.40,0.80,0.55)
]


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
		margin_render_px = MARGIN_PX * supersample  # запас в супersampled px
		margin_world = margin_render_px / scale
		pad = BORDER_WIDTH * 2.0 + margin_world
		border_w_px = max(1, min(MAX_BORDER_PX * supersample, round(BORDER_WIDTH * scale)))

		# Индекс клеток по бакетам тайлов через bbox — иначе на z6 (4096 тайлов)
		# перебор всех ~1800 клеток на каждый тайл был бы 4096*1800 ~ 7.4M
		# проверок, не критично, но проще и быстрее сразу отобрать кандидатов.
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
					color = CONTINENT_COLORS[int(c.get("cont", 0)) % len(CONTINENT_COLORS)]
					pts = to_px(c["rings"][0])
					if len(pts) >= 3:
						draw.polygon(pts, fill=color)
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
