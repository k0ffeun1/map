"""Офлайн-препроцессинг: реки трёх уровней значимости (Natural Earth
ne_10m_rivers_lake_centerlines, поле scalerank — 0 самое значимое) — важно
для будущих механик (см. TODO.md: границы/торговые пути/движение вдоль
рек и т.п.), поэтому отдельный слой линий, а не часть суши/континентов.

Источник — официальный шейпфайл Natural Earth, скачан один раз:
  curl -L -o scripts/tools/_work/ne_10m_rivers.zip \
    https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_rivers_lake_centerlines.zip
  (unzip, затем shp -> geojson через pyshp: scripts/tools/_work/ne_10m_rivers.geojson,
  поля name/scalerank/geometry).

Три уровня (TIER_RANKS) по scalerank датасета:
  0 крупные  (0..2)  — Нил, Амазонка, Янцзы, Дунай, Миссисипи, Конго, Обь...
  1 средние  (3..5)  — Рейн, Сена, Тигр, Волга, Днепр, Эбро, Тахо/Tagus...
  2 мелкие   (6..8)  — Гвадалквивир, Дуэро и т.п. (без них, напр., у Испании
                       на карте вообще нет рек — только Эбро/Тахо уровня 1).
Дальше (9+) — не берём: это уже мелкие притоки, не нужны для масштаба игры.

Не запускается в Godot — отдельный шаг подготовки данных. Результат:
assets/rivers.json — {"world_px":...,"rivers":[{"points":[[x,y],...],"bbox":[...],"tier":0|1|2}]}
(полилинии, НЕ полигоны — рендерится RiverTileProvider.gd, не IrregularCellProvider;
tier решает толщину/цвет на стороне рендера).
"""
import json, math, time

SRC = "scripts/tools/_work/ne_10m_rivers.geojson"
OUT = "assets/rivers.json"
WORLD_PX = 8192.0

LAT_NORTH = 76.0
LAT_SOUTH = -58.0

# (макс. scalerank включительно) для каждого уровня, по возрастанию.
TIER_MAX_RANK = [2, 5, 8]
SIMPLIFY_TOLERANCE_DEG = 0.01


def project(lon, lat):
    lat = max(-85.05112878, min(85.05112878, lat))
    x = (lon + 180.0) / 360.0 * WORLD_PX
    lat_rad = math.radians(lat)
    y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
    return (x, y)


def _tier_of(rank: int):
    for tier, max_rank in enumerate(TIER_MAX_RANK):
        if rank <= max_rank:
            return tier
    return None


def main():
    from shapely.geometry import LineString
    from shapely.ops import clip_by_rect

    t0 = time.time()
    data = json.load(open(SRC, encoding="utf-8"))

    out_rivers = []
    skipped_rank = 0
    tier_counts = [0, 0, 0]
    for f in data["features"]:
        props = f["properties"]
        rank = props.get("scalerank")
        tier = _tier_of(rank) if rank is not None else None
        if tier is None:
            skipped_rank += 1
            continue
        geom = f["geometry"]
        lines = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
        for line in lines:
            if len(line) < 2:
                continue
            try:
                ls = LineString(line)
                # Обрезаем по той же широтной полосе, что и остальные слои
                # (реки в Арктике/Антарктике всё равно нигде не отображаются).
                ls = clip_by_rect(ls, -180.0, LAT_SOUTH, 180.0, LAT_NORTH)
                if ls.is_empty:
                    continue
                ls = ls.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=False)
            except Exception:
                continue

            segments = [ls] if ls.geom_type == "LineString" else list(ls.geoms)
            for seg in segments:
                coords = list(seg.coords)
                if len(coords) < 2:
                    continue
                pts = [project(lon, lat) for lon, lat in coords]
                pts = [(round(x, 2), round(y, 2)) for x, y in pts]
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                out_rivers.append({
                    "points": [[x, y] for x, y in pts],
                    "bbox": [min(xs), min(ys), max(xs), max(ys)],
                    "tier": tier,
                })
                tier_counts[tier] += 1

    print(f"[{time.time()-t0:.1f}s] rivers written: {len(out_rivers)} "
          f"(large={tier_counts[0]}, medium={tier_counts[1]}, small={tier_counts[2]}), "
          f"skipped (scalerank > {TIER_MAX_RANK[-1]}): {skipped_rank}")

    json.dump({"world_px": WORLD_PX, "rivers": out_rivers},
              open(OUT, "w", encoding="utf-8"), separators=(",", ":"))
    print(f"[{time.time()-t0:.1f}s] wrote {OUT}")


if __name__ == "__main__":
    main()
