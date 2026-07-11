"""Офлайн-препроцессинг: озёра (Natural Earth ne_10m_lakes) с делением на
БОЛЬШИЕ/МАЛЫЕ — ТОЛЬКО данные для будущих механик (см. TODO.md), никакого
нового видимого слоя это не создаёт (озёра уже вырезаны дырками в
continents.json/land_sea.json, см. build_continents.py/build_land_sea.py, —
это НЕ трогаем).

Задумка (см. обсуждение с пользователем): большие озёра — по ним могут
ходить речные суда (переправа с одного берега на другой), у них есть
рыболовный промысел; малые озёра — просто вода, без таких механик.

Порог БОЛЬШОЕ/МАЛОЕ — LARGE_LAKE_AREA_KM2 = 500 км². Ориентир на реальные
озёра с историческими паромными линиями/промыслом (Женевское озеро ~533,
Чад ~1293, Чудское ~2772), а не только на "великие" озёра уровня Байкала/
Виктории/Онтарио. Список крупных получается узнаваемый: Великие озёра
Северной Америки, Байкал, Виктория, Танганьика, Ньяса/Малави, Ладога,
Онега, Балхаш, Титикака, Иссык-Куль, Венерн, Женевское, Чад, Чудское и т.п.
(357 озёр из 1293 показываемых, порог настраиваемый).

Не запускается в Godot — отдельный шаг подготовки данных. Результат:
assets/lakes.json — {"world_px":...,"lakes":[{"rings":[[[x,y],...]],"bbox":[...],
"tier":0|1,"name":str,"area_km2":float}]} (0 — большое, 1 — малое).
"""
import json, math, time

SRC = "scripts/tools/_work/ne_10m_lakes.geojson"
OUT = "assets/lakes.json"
WORLD_PX = 8192.0
R_KM = 6371.0

# Тот же порог, что и у build_land_sea.py/build_continents.py/build_land_cells.py
# — совсем мелкие пруды не нужны нигде в проекте.
MIN_LAKE_AREA_KM2 = 15.0
LARGE_LAKE_AREA_KM2 = 500.0

LAKE_LARGE, LAKE_SMALL = 0, 1


def project(lon, lat):
    lat = max(-85.05112878, min(85.05112878, lat))
    x = (lon + 180.0) / 360.0 * WORLD_PX
    lat_rad = math.radians(lat)
    y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
    return (x, y)


def ring_area_km2_lonlat(ring):
    lats = [p[1] for p in ring]
    lat0 = math.radians(sum(lats) / len(lats))
    pts = []
    for lon, lat in ring:
        x = math.radians(lon) * math.cos(lat0) * R_KM
        y = math.radians(lat) * R_KM
        pts.append((x, y))
    a = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return abs(a) * 0.5


def main():
    t0 = time.time()
    data = json.load(open(SRC, encoding="utf-8"))

    out_lakes = []
    n_large = 0
    n_small = 0
    n_skipped = 0
    for f in data["features"]:
        props = f["properties"]
        name = props.get("name") or props.get("name_en") or ""
        geom = f["geometry"]
        parts = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]

        # Считаем площадь ВСЕГО озера (сумма кусков, как делает
        # _build_lakes_index в build_land_cells.py) ДО решения large/small —
        # некоторые озёра (напр. водохранилища с рукавами) распадаются на
        # несколько полигонов, но это одно и то же озеро для механик.
        total_area = sum(ring_area_km2_lonlat(part[0]) for part in parts)
        if total_area < MIN_LAKE_AREA_KM2:
            n_skipped += 1
            continue
        tier = LAKE_LARGE if total_area >= LARGE_LAKE_AREA_KM2 else LAKE_SMALL
        if tier == LAKE_LARGE:
            n_large += 1
        else:
            n_small += 1

        # ТОЛЬКО внешний контур (part[0]) — дырки-острова внутри озера
        # (part[1:], напр. Ольхон на Байкале, Манитулин на Гуроне, острова
        # Виктории) НАМЕРЕННО отбрасываются по просьбе пользователя: острова
        # внутри озёр для механик (паром/промысел) не нужны, озеро — сплошная
        # вода целиком, без "дырок" под них.
        for part in parts:
            ext_ll = part[0]
            if len(ext_ll) < 3:
                continue
            ext = [project(lon, lat) for lon, lat in ext_ll]
            ext = [(round(x, 2), round(y, 2)) for x, y in ext]
            xs = [q[0] for q in ext]
            ys = [q[1] for q in ext]
            out_lakes.append({
                "rings": [[[x, y] for x, y in ext]],
                "bbox": [min(xs), min(ys), max(xs), max(ys)],
                "tier": tier,
                "name": name,
                "area_km2": round(total_area, 1),
            })

    print(f"[{time.time()-t0:.1f}s] lakes: large={n_large}, small={n_small}, "
          f"skipped (< {MIN_LAKE_AREA_KM2:.0f}km2): {n_skipped}, polygons written: {len(out_lakes)}")

    json.dump({"world_px": WORLD_PX, "lakes": out_lakes},
              open(OUT, "w", encoding="utf-8"), separators=(",", ":"))
    print(f"[{time.time()-t0:.1f}s] wrote {OUT}")


if __name__ == "__main__":
    main()
