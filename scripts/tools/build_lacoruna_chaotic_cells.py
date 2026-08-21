#!/usr/bin/env python3
"""Offline build of four validated chaotic cells for layer 3 (La Coruña).

Pipeline: deterministic seed points -> Voronoi -> province clipping -> shared
edges -> recursive midpoint displacement -> polygon rebuild -> validation ->
JSON, debug PNGs and lossless ID map. Godot only consumes the JSON.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, Point, Polygon, box
from shapely.ops import polygonize, unary_union, voronoi_diagram


ROOT = Path(__file__).resolve().parents[2]
GEOMETRY_PATH = ROOT / "assets/map_geometry/provinces.json"
OCEAN_PATH = ROOT / "assets/world_ocean.json"
OUT_PATH = ROOT / "assets/generated/provinces/la_coruna_cells.json"
VALIDATION_PATH = ROOT / "assets/generated/provinces/la_coruna_validation.json"
DEBUG_DIR = ROOT / "assets/debug/la_coruna"
WORLD_PX = 8192.0
WORLD_SEED = 12345
PROVINCE_ID = "province:2848"
TARGET_AREA_KM2 = 2100.0
COAST_CLEARANCE_KM = 2.0

# City seed is fixed; the rest stay inside their intended zones but use a
# deterministic, small offset derived from WORLD_SEED.
SEED_ZONES = (
    ("Ла-Корунья — городская клетка", (3904.66, 2998.56), 0.0),
    ("Ла-Корунья — западное побережье", (3893.8, 3008.8), 1.0),
    ("Ла-Корунья — южная часть", (3900.6, 3016.9), 1.0),
    ("Ла-Корунья — восточная внутренняя", (3912.2, 3009.3), 1.0),
)

# Keep source encoding independent of the editor/terminal code page.
SEED_ZONES = (
    ("\u041b\u0430-\u041a\u043e\u0440\u0443\u043d\u044c\u044f \u2014 \u0433\u043e\u0440\u043e\u0434\u0441\u043a\u0430\u044f \u043a\u043b\u0435\u0442\u043a\u0430", (3904.66, 2998.56), 0.0),
    ("\u041b\u0430-\u041a\u043e\u0440\u0443\u043d\u044c\u044f \u2014 \u0437\u0430\u043f\u0430\u0434\u043d\u043e\u0435 \u043f\u043e\u0431\u0435\u0440\u0435\u0436\u044c\u0435", (3893.8, 3008.8), 1.0),
    ("\u041b\u0430-\u041a\u043e\u0440\u0443\u043d\u044c\u044f \u2014 \u044e\u0436\u043d\u0430\u044f \u0447\u0430\u0441\u0442\u044c", (3900.6, 3016.9), 1.0),
    ("\u041b\u0430-\u041a\u043e\u0440\u0443\u043d\u044c\u044f \u2014 \u0432\u043e\u0441\u0442\u043e\u0447\u043d\u0430\u044f \u0432\u043d\u0443\u0442\u0440\u0435\u043d\u043d\u044f\u044f", (3912.2, 3009.3), 1.0),
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def line_parts(geometry) -> list[LineString]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry] if geometry.length > 1e-7 else []
    if isinstance(geometry, MultiLineString):
        return [part for part in geometry.geoms if part.length > 1e-7]
    if isinstance(geometry, GeometryCollection):
        result: list[LineString] = []
        for part in geometry.geoms:
            result.extend(line_parts(part))
        return result
    return []


def polygon_from_rings(rings: list) -> Polygon:
    polygon = Polygon(rings[0], rings[1:])
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.geom_type == "MultiPolygon":
        polygon = max(polygon.geoms, key=lambda item: item.area)
    if polygon.is_empty or polygon.geom_type != "Polygon":
        raise RuntimeError("La Coruña contour is not a usable polygon")
    return polygon


def km_to_world_px(poly: Polygon, km: float) -> float:
    y = poly.representative_point().y
    latitude = math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / WORLD_PX)))
    return km * WORLD_PX / 40075.016686 / max(math.cos(latitude), 1e-6)


def deterministic_seeds(province: Polygon) -> list[Point]:
    seeds: list[Point] = []
    for index, (_name, position, movable) in enumerate(SEED_ZONES):
        point = Point(position)
        if movable > 0.0:
            rng = random.Random(WORLD_SEED + index * 97)
            point = Point(point.x + rng.uniform(-0.42, 0.42), point.y + rng.uniform(-0.42, 0.42))
        if not province.covers(point):
            point = province.boundary.interpolate(province.boundary.project(point)).interpolate(0.0)
            point = province.representative_point()
        seeds.append(point)
    return seeds


def raw_voronoi_cells(province: Polygon, seeds: list[Point]) -> list[Polygon]:
    diagram = voronoi_diagram(MultiPoint(seeds), envelope=province.envelope.buffer(100.0), edges=False)
    result: list[Polygon] = []
    for seed in seeds:
        source = next((poly for poly in diagram.geoms if poly.covers(seed)), None)
        if source is None:
            raise RuntimeError("Voronoi cell for a seed was not found")
        clipped = source.intersection(province)
        if clipped.geom_type == "MultiPolygon":
            clipped = max(clipped.geoms, key=lambda item: item.area)
        if clipped.is_empty or clipped.geom_type != "Polygon":
            raise RuntimeError("Voronoi clipping produced an invalid cell")
        result.append(clipped)
    return result


def edge_rng(edge_id: str, level: int) -> random.Random:
    digest = hashlib.sha256(f"{WORLD_SEED}:{edge_id}:{level}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def displaced_segment(a: tuple[float, float], b: tuple[float, float], edge_id: str,
                      depth: int, amplitude: float, level: int = 0) -> list[tuple[float, float]]:
    if depth <= 0:
        return [a, b]
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 0.25:
        return [a, b]
    nx, ny = -dy / length, dx / length
    rng = edge_rng(edge_id, level)
    offset = rng.uniform(-amplitude, amplitude)
    midpoint = ((ax + bx) * 0.5 + nx * offset, (ay + by) * 0.5 + ny * offset)
    left = displaced_segment(a, midpoint, edge_id + "L", depth - 1, amplitude * 0.5, level + 1)
    right = displaced_segment(midpoint, b, edge_id + "R", depth - 1, amplitude * 0.5, level + 1)
    return left[:-1] + right


def wavy_line(line: LineString, edge_id: str) -> LineString:
    coords = list(line.simplify(0.08, preserve_topology=True).coords)
    points: list[tuple[float, float]] = []
    for index, (a, b) in enumerate(zip(coords, coords[1:])):
        length = Point(a).distance(Point(b))
        # First bend is at most 5% of an average cell span; each recursive
        # level halves it. This keeps narrow parts and triple nodes safe.
        # Короткие рёбра у тройных узлов почти не искажаем: иначе волна
        # пересечёт соседнюю границу. На длинных границах остаётся заметный
        # крупный изгиб, соответствующий 5–8% размера клетки.
        amplitude = min(0.42, length * 0.035)
        segment = displaced_segment(a, b, f"{edge_id}:{index}", 3, amplitude)
        points.extend(segment if not points else segment[1:])
    return LineString(points)


def shared_edges(cells: list[Polygon]) -> list[tuple[int, int, LineString]]:
    edges: list[tuple[int, int, LineString]] = []
    for first in range(len(cells)):
        for second in range(first + 1, len(cells)):
            for line in line_parts(cells[first].boundary.intersection(cells[second].boundary)):
                if line.length > 0.20:
                    edges.append((first, second, line))
    return edges


def rebuild_with_wavy_edges(province: Polygon, seeds: list[Point], raw_cells: list[Polygon]) -> tuple[list[Polygon], list[LineString]]:
    # Берём топологически связанный граф из ВСЕХ контуров Voronoi-клеток.
    # Прямое pairwise intersection иногда даёт у тройного узла два конца,
    # различающихся на машинную погрешность; такой набор не полигонализуется.
    # Unary union уже нодировал этот граф, поэтому заменяем только внутренние
    # его сегменты, оставляя точные внешние части контура провинции.
    graph = line_parts(unary_union([cell.boundary for cell in raw_cells]))
    outer_lines = [line for line in graph if province.boundary.distance(line.interpolate(0.5, normalized=True)) <= 0.04]
    inner_lines = [line for line in graph if province.boundary.distance(line.interpolate(0.5, normalized=True)) > 0.04]
    wavy_edges = [wavy_line(line, f"edge:{index}") for index, line in enumerate(inner_lines)]
    network = unary_union([*outer_lines, *wavy_edges])
    faces = [face for face in polygonize(network) if province.covers(face.representative_point()) and face.area > 1e-5]
    assigned: list[Polygon] = []
    for seed in seeds:
        matches = [face for face in faces if face.covers(seed)]
        if len(matches) != 1:
            raise RuntimeError("Wavy edge rebuild lost a seed or produced an extra face")
        assigned.append(matches[0])
    # The authoritative province ring is much denser than the clipped Voronoi
    # graph. Polygonization can leave a microscopic seam at an outer node;
    # attach it to the nearest cell before validation rather than exporting a
    # gap in coverage.
    missing = province.difference(unary_union(assigned))
    missing_parts = [missing] if missing.geom_type == "Polygon" else list(getattr(missing, "geoms", []))
    for part in missing_parts:
        if part.is_empty or part.area <= 1e-9:
            continue
        target = min(range(len(assigned)), key=lambda index: assigned[index].distance(part.representative_point()))
        merged = assigned[target].union(part)
        if merged.geom_type != "Polygon":
            raise RuntimeError("Microscopic seam could not be attached to one cell")
        assigned[target] = merged
    return assigned, wavy_edges


def local_coast_guard(province: Polygon):
    if not OCEAN_PATH.exists():
        return GeometryCollection()
    margin = km_to_world_px(province, COAST_CLEARANCE_KM)
    clip = box(*province.bounds).buffer(margin + 3.0)
    lines: list[LineString] = []
    for cell in load_json(OCEAN_PATH).get("cells", []):
        bbox_data = cell.get("bbox", [])
        if len(bbox_data) != 4 or bbox_data[2] < clip.bounds[0] or bbox_data[0] > clip.bounds[2] or bbox_data[3] < clip.bounds[1] or bbox_data[1] > clip.bounds[3]:
            continue
        for ring in cell.get("rings", []):
            if len(ring) >= 2:
                lines.extend(line_parts(LineString(ring).intersection(clip)))
    return unary_union(lines).buffer(margin) if lines else GeometryCollection()


def split_open_chains(coords: list[tuple[float, float]], boundary) -> tuple[list[list[list[float]]], list[list[list[float]]]]:
    n = len(coords) - 1
    flags = [boundary.distance(Point((coords[i][0] + coords[i + 1][0]) * 0.5, (coords[i][1] + coords[i + 1][1]) * 0.5)) > 0.04 for i in range(n)]

    def collect(wanted: bool) -> list[list[list[float]]]:
        if not any(flag == wanted for flag in flags):
            return []
        if all(flag == wanted for flag in flags):
            return [[[round(x, 6), round(y, 6)] for x, y in coords]]
        start = next(index for index in range(n) if flags[index] == wanted and flags[index - 1] != wanted)
        result, chain = [], []
        for offset in range(n):
            index = (start + offset) % n
            if flags[index] == wanted:
                if not chain:
                    chain = [coords[index]]
                chain.append(coords[(index + 1) % n])
            elif len(chain) >= 2:
                result.append([[round(x, 6), round(y, 6)] for x, y in chain])
                chain = []
        if len(chain) >= 2:
            result.append([[round(x, 6), round(y, 6)] for x, y in chain])
        return result

    return collect(True), collect(False)


def clipped_internal_chains(chains: list[list[list[float]]], coast_guard) -> list[list[list[float]]]:
    if coast_guard.is_empty:
        return chains
    output: list[list[list[float]]] = []
    for chain in chains:
        for line in line_parts(LineString(chain).difference(coast_guard)):
            if line.length > 0.15:
                output.append([[round(x, 6), round(y, 6)] for x, y in line.coords])
    return output


def rings(poly: Polygon) -> list[list[list[float]]]:
    return [[[round(x, 6), round(y, 6)] for x, y in poly.exterior.coords]] + [
        [[round(x, 6), round(y, 6)] for x, y in ring.coords] for ring in poly.interiors
    ]


def validate(province: Polygon, cells: list[Polygon], seeds: list[Point], source_area_km2: float) -> dict:
    coverage = unary_union(cells)
    overlap = sum(cell.area for cell in cells) - coverage.area
    neighbours = []
    for index, cell in enumerate(cells):
        neighbours.append([other for other, value in enumerate(cells) if other != index and cell.boundary.intersection(value.boundary).length > 0.20])
    areas = [source_area_km2 * cell.area / province.area for cell in cells]
    report = {
        "coverage_ok": province.symmetric_difference(coverage).area < 1e-5,
        "missing_world_px2": round(province.difference(coverage).area, 9),
        "extra_world_px2": round(coverage.difference(province).area, 9),
        "overlap_world_px2": round(overlap, 9),
        "valid_polygons": all(cell.is_valid and cell.geom_type == "Polygon" for cell in cells),
        "seed_inside": [cell.covers(seed) for cell, seed in zip(cells, seeds)],
        "areas_km2": [round(value, 2) for value in areas],
        "neighbours": neighbours,
    }
    if not report["coverage_ok"] or abs(overlap) > 1e-5 or not report["valid_polygons"] or not all(report["seed_inside"]):
        raise RuntimeError(f"Geometry validation failed: {report}")
    return report


def make_debug_images(province: Polygon, seeds: list[Point], raw: list[Polygon], final: list[Polygon], wavy: list[LineString], validation: dict) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    width, height, pad = 1000, 760, 30
    min_x, min_y, max_x, max_y = province.bounds
    scale = min((width - pad * 2) / (max_x - min_x), (height - pad * 2) / (max_y - min_y))
    def xy(point): return (pad + (point[0] - min_x) * scale, pad + (point[1] - min_y) * scale)
    def canvas(): return Image.new("RGB", (width, height), "#15253a")
    def draw_poly(draw, poly, fill=None, outline="#e8edf4", line_width=2):
        draw.polygon([xy(item) for item in poly.exterior.coords], fill=fill, outline=outline, width=line_width)
    colors = ("#67b7dc", "#8fcf9f", "#e6b76f", "#bd90d7")
    def save_step(number, title, cells=None, edges=None, id_map=False):
        image = Image.new("RGB", (width, height), (0, 0, 0)) if id_map else canvas()
        draw = ImageDraw.Draw(image)
        if not id_map:
            draw.text((20, 10), title, fill="#ffffff")
        if cells:
            for index, cell in enumerate(cells):
                fill = ((index + 1, 0, 0) if id_map else colors[index % len(colors)])
                if id_map:
                    # Pure ID raster: background is RGB(0,0,0), cell N is
                    # RGB(N,0,0). No label, antialiasing or outline may alter
                    # an identifier pixel.
                    draw.polygon([xy(item) for item in cell.exterior.coords], fill=fill)
                else:
                    draw_poly(draw, cell, fill=fill)
        else:
            draw_poly(draw, province, fill="#406b80", outline="#ffffff", line_width=3)
        if edges:
            for edge in edges:
                draw.line([xy(item) for item in edge.coords], fill="#171717", width=3)
        if not id_map:
            for index, seed in enumerate(seeds, start=1):
                sx, sy = xy((seed.x, seed.y)); draw.ellipse((sx - 5, sy - 5, sx + 5, sy + 5), fill="#ffd94f")
                draw.text((sx + 7, sy - 7), str(index), fill="#ffffff")
        image.save(DEBUG_DIR / f"{number}.png")
    save_step("01_province_outline", "La Coruna: province outline")
    save_step("02_seed_points", "La Coruna: deterministic seeds")
    save_step("03_raw_voronoi", "La Coruna: raw Voronoi", raw)
    save_step("04_clipped_cells", "La Coruna: clipped Voronoi", raw)
    save_step("05_wavy_edges", "La Coruna: shared wavy edges", raw, wavy)
    save_step("06_final_cells", "La Coruna: final rebuilt cells", final)
    save_step("07_id_map", "La Coruna: lossless ID map", final, id_map=True)
    image = canvas(); draw = ImageDraw.Draw(image)
    draw.text((20, 20), "Validation: " + ("OK" if validation["coverage_ok"] else "FAILED"), fill="#66e38b" if validation["coverage_ok"] else "#ff6666")
    draw.text((20, 50), json.dumps(validation, ensure_ascii=False), fill="#ffffff")
    image.save(DEBUG_DIR / "08_validation_errors.png")


def main() -> None:
    geometry = load_json(GEOMETRY_PATH)
    entry = next(item for item in geometry["provinces"] if item["id"] == PROVINCE_ID)
    province = polygon_from_rings(entry["rings"])
    seeds = deterministic_seeds(province)
    raw = raw_voronoi_cells(province, seeds)
    final, wavy = rebuild_with_wavy_edges(province, seeds, raw)
    validation = validate(province, final, seeds, float(entry["area_km2"]))
    coast_guard = local_coast_guard(province)
    cells = []
    for index, cell in enumerate(final):
        open_chains, boundary_chains = split_open_chains(list(cell.exterior.coords), province.boundary)
        label = cell.representative_point()
        cells.append({
            "id": f"lacoruna_cell_{index + 1:02d}", "name": SEED_ZONES[index][0],
            "province_id": PROVINCE_ID, "cell_role": "city" if index == 0 else "territory",
            "rings": rings(cell), "brd_open": clipped_internal_chains(open_chains, coast_guard),
            "brd_boundary": boundary_chains, "bbox": [round(value, 4) for value in cell.bounds],
            "center": [round(cell.centroid.x, 4), round(cell.centroid.y, 4)],
            "label_point": [round(label.x, 4), round(label.y, 4)],
            "area_km2": validation["areas_km2"][index],
            "neighbor_cell_ids": [f"lacoruna_cell_{item + 1:02d}" for item in validation["neighbours"][index]],
            "color": [0.16, 0.74, 0.96, 0.0],
        })
    payload = {"schema_version": 1, "kind": "lacoruna_chaotic_cells", "world_px": WORLD_PX,
        "source": {"province": "assets/map_geometry/provinces.json", "world_seed": WORLD_SEED,
                   "method": "voronoi_then_shared_recursive_midpoint_displacement", "coast_clearance_km": COAST_CLEARANCE_KM},
        "id_map": {
            "path": "assets/debug/la_coruna/07_id_map.png",
            "encoding": "RGB red channel: 0=outside, 1..4=cell_ids order",
            "cell_ids": [cell["id"] for cell in cells],
        },
        "validation": validation, "cells": cells}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    VALIDATION_PATH.write_text(json.dumps({
        "province_id": PROVINCE_ID,
        "world_seed": WORLD_SEED,
        "cell_ids": [cell["id"] for cell in cells],
        "validation": validation,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    make_debug_images(province, seeds, raw, final, wavy, validation)
    print(f"wrote {OUT_PATH.relative_to(ROOT)}: {len(cells)} cells; validation={validation['coverage_ok']}")


if __name__ == "__main__":
    main()
