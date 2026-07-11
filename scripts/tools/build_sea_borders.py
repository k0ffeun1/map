import json, math, sys

SRC = "marine_polys.geojson"
OUT = "sea_borders.json"
WORLD_PX = 8192.0
SIMPLIFY_TOL = 0.6  # world-px tolerance (out of 8192) for Douglas-Peucker

KEEP_CLASSES = {"sea", "gulf", "bay", "strait", "sound", "channel", "lagoon",
                "fjord", "ocean", "inlet", "generic"}


def project(lon, lat):
    lat = max(-85.05112878, min(85.05112878, lat))
    x = (lon + 180.0) / 360.0 * WORLD_PX
    lat_rad = math.radians(lat)
    y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
    return [round(x, 2), round(y, 2)]


def rdp(points, tol):
    if len(points) < 3:
        return points
    (x1, y1), (x2, y2) = points[0], points[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy)
    idx, dmax = -1, 0.0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        if norm == 0:
            d = math.hypot(px - x1, py - y1)
        else:
            d = abs(dy * px - dx * py + x2 * y1 - y2 * x1) / norm
        if d > dmax:
            idx, dmax = i, d
    if dmax > tol:
        left = rdp(points[:idx + 1], tol)
        right = rdp(points[idx:], tol)
        return left[:-1] + right
    return [points[0], points[-1]]


def rings_of(geom):
    if geom["type"] == "Polygon":
        return geom["coordinates"]
    if geom["type"] == "MultiPolygon":
        out = []
        for poly in geom["coordinates"]:
            out.extend(poly)
        return out
    return []


def main():
    data = json.load(open(SRC, encoding="utf-8"))
    out_features = []
    total_pts_in, total_pts_out = 0, 0

    for f in data["features"]:
        props = f["properties"]
        cla = props.get("featurecla")
        if cla not in KEEP_CLASSES:
            continue
        name = props.get("name_ru") or props.get("name") or ""
        rings_out = []
        for ring in rings_of(f["geometry"]):
            total_pts_in += len(ring)
            proj = [project(lon, lat) for lon, lat in ring]
            simplified = rdp(proj, SIMPLIFY_TOL)
            if len(simplified) < 2:
                continue
            total_pts_out += len(simplified)
            rings_out.append(simplified)
        if not rings_out:
            continue
        xs = [p[0] for r in rings_out for p in r]
        ys = [p[1] for r in rings_out for p in r]
        out_features.append({
            "name": name,
            "cla": cla,
            "bbox": [min(xs), min(ys), max(xs), max(ys)],
            "rings": rings_out,
        })

    json.dump({"world_px": WORLD_PX, "features": out_features},
              open(OUT, "w", encoding="utf-8"), separators=(",", ":"))
    print("features kept:", len(out_features))
    print("points in/out:", total_pts_in, total_pts_out)


if __name__ == "__main__":
    main()
