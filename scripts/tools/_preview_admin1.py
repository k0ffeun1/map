"""Быстрый ОДНОРАЗОВЫЙ превью-рендер ne_10m_admin_1_states_provinces (штаты/
области/республики) — просто посмотреть, как выглядят реальные админ-границы
на карте, БЕЗ какой-либо нарезки/обработки. Не часть пайплайна, удалить после
просмотра."""
import json, math, time
from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None
WORLD_PX = 16384.0  # превью покрупнее для детализации регионов


def project(lon, lat):
    lat = max(-85.05112878, min(85.05112878, lat))
    x = (lon + 180.0) / 360.0 * WORLD_PX
    lat_rad = math.radians(lat)
    y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
    return (x, y)


def main():
    t0 = time.time()
    data = json.load(open("scripts/tools/_work/ne_10m_admin_1_states_provinces.geojson", encoding="utf-8"))
    img = Image.new("RGB", (int(WORLD_PX), int(WORLD_PX)), (10, 20, 40))
    draw = ImageDraw.Draw(img)

    colors = [
        (217, 140, 140), (140, 217, 160), (140, 170, 217), (217, 200, 120),
        (190, 140, 217), (120, 200, 200), (217, 160, 100), (160, 190, 120),
    ]

    n = 0
    for i, f in enumerate(data["features"]):
        geom = f["geometry"]
        parts = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        color = colors[i % len(colors)]
        for part in parts:
            ext = [project(lon, lat) for lon, lat in part[0]]
            if len(ext) >= 3:
                draw.polygon(ext, fill=color, outline=(20, 20, 20))
                n += 1

    img.save("scripts/tools/_work/_preview_admin1_world.png")
    print(f"[{time.time()-t0:.1f}s] wrote preview, {n} pieces")

    # Отдельные зумы на интересные регионы, чтобы оценить детализацию.
    crops = {
        "spain": (-9.5, 3.5, 36.0, 43.8),
        "russia_west": (30.0, 55.0, 45.0, 62.0),
        "usa": (-125.0, -66.0, 24.0, 49.0),
    }
    for name, (lon0, lon1, lat0, lat1) in crops.items():
        x0, y0 = project(lon0, lat1)
        x1, y1 = project(lon1, lat0)
        crop = img.crop((max(0, int(x0)), max(0, int(y0)), min(int(WORLD_PX), int(x1)), min(int(WORLD_PX), int(y1))))
        crop.save(f"scripts/tools/_work/_preview_admin1_{name}.png")
    print(f"[{time.time()-t0:.1f}s] wrote crops: {list(crops)}")


if __name__ == "__main__":
    main()
