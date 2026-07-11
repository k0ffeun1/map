"""Обрезка assets/provinces.json до региона Пиренейский п-ов + Балеары —
ЖИВОЙ (векторный) эквивалент того же региона, что уже фильтрует
bake_provinces_iberia_tiles.py (REGION_LONLAT, тот же bbox-фильтр по
запасу PAD_WORLD_PX). Результат — assets/provinces_iberia.json, тот же
формат rings/bbox/name, что и полный provinces.json.

Повод: слой "4" (клавиша 4) временно живой (IrregularCellProvider, см.
TileMapViewer.gd, PROVINCES_IBERIA_FORCE_LIVE, решение сессии 2026-07-11) —
пока не зафиксирована граница provinces.json и не перезапечено начисто.
Если грузить в слой "4" ПОЛНЫЙ provinces.json — слой рисует ВЕСЬ мир и
становится дубликатом слоя "8" (найдено пользователем в сессии). Этот
скрипт даёт слою "4" собственный, ограниченный регионом набор данных, как и
задумано изначально.

world_px клеток НЕ пересчитывается (уже спроецированы build_provinces.py) —
просто фильтр по bbox, дешёвая операция.
"""
import json, math

SRC = "assets/provinces.json"
OUT = "assets/provinces_iberia.json"
WORLD_PX = 8192.0

# ТОТ ЖЕ регион, что REGION_LONLAT в bake_provinces_iberia_tiles.py — не
# рассинхронизировать (баг-ловушка: другой регион на слое "4" live vs
# baked-версия, к которой вернёмся позже).
REGION_LONLAT = (-9.9, 35.95, 4.4, 44.0)
PAD_WORLD_PX = 5.0  # тот же запас, что "pad" в bake_provinces_iberia_tiles.py


def project(lon: float, lat: float) -> tuple:
	lat = max(-85.05112878, min(85.05112878, lat))
	x = (lon + 180.0) / 360.0 * WORLD_PX
	lat_rad = math.radians(lat)
	y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
	return x, y


def region_bbox_world_px() -> tuple:
	lon0, lat0, lon1, lat1 = REGION_LONLAT
	x0, y0 = project(lon0, lat1)
	x1, y1 = project(lon1, lat0)
	return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def main() -> None:
	data = json.load(open(SRC, encoding="utf-8"))
	rx0, ry0, rx1, ry1 = region_bbox_world_px()
	print(f"регион {REGION_LONLAT} -> world px [{rx0:.0f},{ry0:.0f},{rx1:.0f},{ry1:.0f}]")

	out_cells = []
	for c in data["cells"]:
		bb = c.get("bbox")
		if not bb:
			continue
		if bb[2] < rx0 - PAD_WORLD_PX or bb[0] > rx1 + PAD_WORLD_PX \
				or bb[3] < ry0 - PAD_WORLD_PX or bb[1] > ry1 + PAD_WORLD_PX:
			continue
		out_cells.append(c)

	print(f"клеток в регионе: {len(out_cells)} из {len(data['cells'])}")
	json.dump({"world_px": data["world_px"], "cells": out_cells},
			   open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
	print(f"wrote {OUT}")


if __name__ == "__main__":
	main()
