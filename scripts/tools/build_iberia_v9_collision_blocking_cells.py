#!/usr/bin/env python3
"""Build selectable Iberian land cells with the v9 radial collision algorithm.

The input is the Layer 4 province selection geometry already clipped by the
shared 2 km ocean overlap.  This keeps generated land cells out of the water
strip while leaving the visible Layer 4 province geometry unchanged.
"""
from __future__ import annotations

import argparse
import json
import math
import zlib
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import rasterio.features
from affine import Affine
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Polygon, mapping, shape
from shapely.ops import linemerge, unary_union


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "assets" / "provinces_iberia_selection_2km.json"
OUTPUT = ROOT / "assets" / "cells_iberia_v9_collision_blocking.json"
REPORT = ROOT / "assets" / "cell_topology" / "iberia_v9_collision_blocking_validation.json"

WORLD_PX = 8192.0
EARTH_RADIUS_KM = 6371.0088
COAST_MARGIN_KM = 2.0

# Параметры v9 из гайда. raster_step уменьшен для карты мира: 3 world-px
# здесь даёт слишком грубую границу провинции (примерно 12–15 км на широте
# Иберии), поэтому используется один world-px.
CIRCLE_COUNT = 4
START_RADIUS = 18.0
RAY_COUNT = 8700
BASE_SPEED = 65.0
SPEED_VARIATION = 0.29
SPEED_ARC_COUNT = 44
ANGULAR_SMOOTHNESS = 1.0
MICRO_VARIATION = 0.99
CIRCLE_SPEED_VARIATION = 0.46
AREA_PROFILE_STRENGTH = 0.45
COLLISION_PASSES = 8
CLEANUP_PASSES = 4
RASTER_STEP = 1.0


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def unproject_lat(y: float) -> float:
    n = math.pi - 2.0 * math.pi * y / WORLD_PX
    return math.degrees(math.atan(math.sinh(n)))


def km_per_world_px(y: float) -> float:
    return (2.0 * math.pi * EARTH_RADIUS_KM / WORLD_PX) * math.cos(math.radians(unproject_lat(y)))


def polygon_parts(geometry: Any) -> list[Polygon]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return [part for part in geometry.geoms if not part.is_empty]
    if isinstance(geometry, GeometryCollection):
        return [part for part in geometry.geoms if isinstance(part, Polygon) and not part.is_empty]
    return []


def line_parts(geometry: Any) -> list[LineString]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return [part for part in geometry.geoms if not part.is_empty]
    if isinstance(geometry, GeometryCollection):
        return [part for part in geometry.geoms if isinstance(part, LineString) and not part.is_empty]
    return []


def entry_geometry(entry: dict[str, Any]) -> Any:
    rings = entry.get("rings", [])
    if not rings:
        raise ValueError("у провинции нет rings")
    geometry = Polygon(rings[0], rings[1:])
    if not geometry.is_valid:
        geometry = geometry.buffer(0)
    if geometry.is_empty:
        raise ValueError("пустая геометрия после исправления")
    return geometry


def rings_from_polygon(poly: Polygon) -> list[list[list[float]]]:
    def coords(raw: Any) -> list[list[float]]:
        return [[round(float(x), 5), round(float(y), 5)] for x, y in raw]
    return [coords(poly.exterior.coords)] + [coords(ring.coords) for ring in poly.interiors]


def line_coordinates(line: LineString) -> list[list[float]]:
    return [[round(float(x), 5), round(float(y), 5)] for x, y in line.coords]


def build_raster_mask(geometry: Any, step: float) -> tuple[np.ndarray, Affine, float, float]:
    min_x, min_y, max_x, max_y = geometry.bounds
    width = max(1, int(math.ceil((max_x - min_x) / step)))
    height = max(1, int(math.ceil((max_y - min_y) / step)))
    transform = Affine(step, 0.0, min_x, 0.0, step, min_y)
    mask = rasterio.features.rasterize(
        [(mapping(geometry), 1)],
        out_shape=(height, width),
        transform=transform,
        fill=0,
        default_value=1,
        all_touched=False,
        dtype=np.uint8,
    ).astype(bool)
    return mask, transform, min_x, min_y


def choose_centres(xs: np.ndarray, ys: np.ndarray, geometry: Any, count: int, rng: np.random.Generator) -> np.ndarray:
    """Farthest-point sampling, with values scaled to each small province."""
    if xs.size <= count:
        return np.arange(xs.size, dtype=np.int64)
    # The guide's fixed 205 px is appropriate to its large demo canvas, but
    # impossible inside ordinary map provinces. Farthest-point sampling uses
    # the local province extent directly and still keeps all centres apart.
    # Берег уже сдвинут внутрь на 2 км входным слоем. Не вызываем distance()
    # для каждого raster-пикселя: на всей Иберии это превратило бы офлайн-
    # сборку в миллионы дорогих геометрических запросов. Farthest-point
    # sampling сам оттягивает центры от тесных краёв, а безопасная береговая
    # полоса остаётся частью исходной геометрии.
    candidates = np.arange(xs.size, dtype=np.int64)
    selected = [int(candidates[rng.integers(candidates.size)])]
    nearest_sq = (xs[candidates] - xs[selected[0]]) ** 2 + (ys[candidates] - ys[selected[0]]) ** 2
    while len(selected) < count:
        # A tiny random choice among the best candidates preserves the v9
        # centre_spread behaviour while remaining deterministic for a seed.
        top_count = min(12, candidates.size)
        best = np.argpartition(nearest_sq, -top_count)[-top_count:]
        choice = int(best[rng.integers(best.size)])
        selected.append(int(candidates[choice]))
        distance_sq = (xs[candidates] - xs[selected[-1]]) ** 2 + (ys[candidates] - ys[selected[-1]]) ** 2
        nearest_sq = np.minimum(nearest_sq, distance_sq)
    return np.asarray(selected, dtype=np.int64)


def build_speed_profile(circle_index: int, multiplier: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed + circle_index * 7919)
    knots = rng.uniform(-1.0, 1.0, SPEED_ARC_COUNT)
    rays = np.arange(RAY_COUNT, dtype=np.float64)
    u = rays / float(RAY_COUNT) * float(SPEED_ARC_COUNT)
    k0 = np.floor(u).astype(np.int32) % SPEED_ARC_COUNT
    k1 = (k0 + 1) % SPEED_ARC_COUNT
    t = u - np.floor(u)
    smooth_t = t * t * (3.0 - 2.0 * t)
    t = t * (1.0 - ANGULAR_SMOOTHNESS) + smooth_t * ANGULAR_SMOOTHNESS
    z = knots[k0] * (1.0 - t) + knots[k1] * t
    z += rng.uniform(-1.0, 1.0, RAY_COUNT) * MICRO_VARIATION * 0.12
    speed = BASE_SPEED * multiplier * (1.0 + z * SPEED_VARIATION * 0.62)
    return np.maximum(BASE_SPEED * 0.2, speed)


def ray_indices(dx: np.ndarray, dy: np.ndarray) -> np.ndarray:
    angles = np.mod(np.arctan2(dy, dx), math.tau)
    return (np.floor(angles / math.tau * RAY_COUNT).astype(np.int32) % RAY_COUNT)


def collision_blocking(owner: np.ndarray, distances: list[np.ndarray], rays: list[np.ndarray]) -> np.ndarray:
    current = owner.copy()
    tolerance = RASTER_STEP * 1.75
    for _pass in range(COLLISION_PASSES):
        source = current.copy()
        next_owner = source.copy()
        changes = 0
        for circle_id in range(len(distances)):
            enemy = source != circle_id
            if not np.any(enemy):
                continue
            enemy_indices = np.flatnonzero(enemy)
            ordered = enemy_indices[np.argsort(distances[circle_id][enemy_indices], kind="stable")]
            ordered_rays = rays[circle_id][ordered]
            _, first = np.unique(ordered_rays, return_index=True)
            nearest = ordered[first]
            cut_distance = np.full(RAY_COUNT, np.inf, dtype=np.float64)
            blocker = np.full(RAY_COUNT, -1, dtype=np.int16)
            cut_distance[rays[circle_id][nearest]] = distances[circle_id][nearest]
            blocker[rays[circle_id][nearest]] = source[nearest]
            own = np.flatnonzero(source == circle_id)
            if own.size == 0:
                continue
            own_rays = rays[circle_id][own]
            replace = own[distances[circle_id][own] > cut_distance[own_rays] + tolerance]
            replacement_owner = blocker[rays[circle_id][replace]]
            valid = replacement_owner >= 0
            if np.any(valid):
                target = replace[valid]
                next_owner[target] = replacement_owner[valid]
                changes += int(target.size)
        current = next_owner
        if changes == 0:
            break
    return current


def cleanup_owner_map(owner: np.ndarray, mask: np.ndarray, circle_count: int) -> np.ndarray:
    """Weak 3×3 majority cleanup from the guide, without touching the sea."""
    current = np.full(mask.shape, -1, dtype=np.int16)
    current[mask] = owner
    for _pass in range(CLEANUP_PASSES):
        padded = np.pad(current, 1, constant_values=-1)
        candidate = current.copy()
        strongest = np.zeros(current.shape, dtype=np.int8)
        for circle_id in range(circle_count):
            votes = np.zeros(current.shape, dtype=np.int8)
            for dy in range(3):
                for dx in range(3):
                    votes += (padded[dy:dy + current.shape[0], dx:dx + current.shape[1]] == circle_id)
            replace = mask & (current != circle_id) & (votes >= 6) & (votes > strongest)
            candidate[replace] = circle_id
            strongest[replace] = votes[replace]
        if np.array_equal(candidate, current):
            break
        current = candidate
    return current[mask]


def owner_geometries(owner_grid: np.ndarray, mask: np.ndarray, transform: Affine, province: Any, circle_count: int) -> list[list[Polygon]]:
    result: list[list[Polygon]] = []
    values = np.zeros(mask.shape, dtype=np.int16)
    values[mask] = owner_grid.astype(np.int16) + 1
    for circle_id in range(circle_count):
        source_mask = mask & (values == circle_id + 1)
        raw = []
        for geojson, value in rasterio.features.shapes(values, mask=source_mask, transform=transform):
            if int(value) == circle_id + 1:
                raw.append(shape(geojson))
        geometry = unary_union(raw).intersection(province) if raw else GeometryCollection()
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        result.append(sorted(polygon_parts(geometry), key=lambda item: item.area, reverse=True))
    return result


def add_internal_borders(records: list[dict[str, Any]]) -> None:
    for record in records:
        record["brd_open"] = []
        record["neighbours"] = []
    for left in range(len(records)):
        for right in range(left + 1, len(records)):
            shared = records[left]["_geometry"].boundary.intersection(records[right]["_geometry"].boundary)
            parts = [part for part in line_parts(shared) if part.length > RASTER_STEP * 0.7]
            if not parts:
                continue
            merged = parts[0] if len(parts) == 1 else linemerge(unary_union(parts))
            chains = [line_coordinates(part.simplify(RASTER_STEP * 0.15, preserve_topology=False))
                      for part in line_parts(merged) if part.length > RASTER_STEP * 0.7]
            if not chains:
                continue
            records[left]["brd_open"].extend(chains)
            records[right]["brd_open"].extend(chains)
            records[left]["neighbours"].append(records[right]["id"])
            records[right]["neighbours"].append(records[left]["id"])
    for record in records:
        record["neighbours"].sort()


def build_province(entry: dict[str, Any], source_part: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    province = entry_geometry(entry)
    # Несколько очень маленьких островных частей переживают честную 2-км
    # отсечку лишь тонким участком. Для них повышаем разрешение локально,
    # вместо того чтобы молча потерять будущую выделяемую клетку.
    local_step = RASTER_STEP
    mask, transform, min_x, min_y = build_raster_mask(province, local_step)
    rows, cols = np.nonzero(mask)
    while rows.size == 0 and local_step > 0.0625:
        local_step *= 0.5
        mask, transform, min_x, min_y = build_raster_mask(province, local_step)
        rows, cols = np.nonzero(mask)
    if rows.size == 0:
        raise ValueError("после береговой отсечки не осталось raster-пикселей")
    circle_count = min(CIRCLE_COUNT, int(rows.size))
    xs = min_x + (cols.astype(np.float64) + 0.5) * local_step
    ys = min_y + (rows.astype(np.float64) + 0.5) * local_step
    province_id = str(entry.get("id", "province"))
    seed = zlib.crc32(f"v9:{province_id}:{source_part}".encode("utf-8"))
    rng = np.random.default_rng(seed)
    centre_indices = choose_centres(xs, ys, province, circle_count, rng)
    centres = np.column_stack((xs[centre_indices], ys[centre_indices]))
    size_multipliers = np.array([1.15, 1.06, 0.98, 0.88], dtype=np.float64)[:circle_count]
    rng.shuffle(size_multipliers)
    distances: list[np.ndarray] = []
    rays: list[np.ndarray] = []
    arrival = []
    for circle_id, centre in enumerate(centres):
        area_multiplier = 1.0 + (size_multipliers[circle_id] - 1.0) * AREA_PROFILE_STRENGTH
        area_multiplier *= 1.0 + rng.uniform(-1.0, 1.0) * CIRCLE_SPEED_VARIATION * 0.18
        profile = build_speed_profile(circle_id, area_multiplier, seed)
        dx, dy = xs - centre[0], ys - centre[1]
        distance = np.hypot(dx, dy)
        ray = ray_indices(dx, dy)
        ray_float = np.mod(np.arctan2(dy, dx), math.tau) / math.tau * RAY_COUNT
        ray0 = np.floor(ray_float).astype(np.int32) % RAY_COUNT
        ray1 = (ray0 + 1) % RAY_COUNT
        fraction = ray_float - np.floor(ray_float)
        local_speed = profile[ray0] * (1.0 - fraction) + profile[ray1] * fraction
        distances.append(distance)
        rays.append(ray)
        arrival.append(np.maximum(0.0, distance - START_RADIUS) / local_speed)
    owner = np.argmin(np.vstack(arrival), axis=0).astype(np.int16)
    owner = collision_blocking(owner, distances, rays)
    owner = cleanup_owner_map(owner, mask, circle_count)
    owner = collision_blocking(owner, distances, rays)
    polygons = owner_geometries(owner, mask, transform, province, circle_count)

    records: list[dict[str, Any]] = []
    source_name = str(entry.get("name", province_id))
    for circle_id, parts in enumerate(polygons):
        for part_index, poly in enumerate(parts, start=1):
            suffix = f":{part_index:02d}" if len(parts) > 1 else ""
            cell_id = f"v9:{province_id}:{source_part:02d}:{circle_id + 1:02d}{suffix}"
            label = poly.representative_point()
            records.append({
                "id": cell_id,
                "name": f"{source_name} — {circle_id + 1}" + (f" ({part_index})" if len(parts) > 1 else ""),
                "parent_province_id": province_id,
                "parent_province_name": source_name,
                "source_part": source_part,
                "profile_id": "land_profile:v9_collision_blocking",
                "area_km2": round(poly.area * km_per_world_px(label.y) ** 2, 2),
                "rings": rings_from_polygon(poly),
                "bbox": [round(value, 5) for value in poly.bounds],
                "center": [round(poly.centroid.x, 5), round(poly.centroid.y, 5)],
                "label_point": [round(label.x, 5), round(label.y, 5)],
                "growth_center": [round(float(centres[circle_id, 0]), 5), round(float(centres[circle_id, 1]), 5)],
                "color": [0.91, 0.65, 0.20, 0.0],
                "_geometry": poly,
            })
    add_internal_borders(records)
    for record in records:
        del record["_geometry"]
    return records, {
        "province_id": province_id,
        "source_part": source_part,
        "raster_cells": int(rows.size),
        "raster_step_world_px": local_step,
        "circle_count": circle_count,
        "generated_cells": len(records),
        "centres": [[round(float(x), 4), round(float(y), 4)] for x, y in centres],
    }


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    source = load_json(SOURCE)
    cells: list[dict[str, Any]] = []
    validations: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    ids_seen: Counter[str] = Counter()
    for entry in source.get("cells", []):
        province_id = str(entry.get("id", "province"))
        ids_seen[province_id] += 1
        try:
            generated, validation = build_province(entry, ids_seen[province_id])
            cells.extend(generated)
            validations.append(validation)
        except (ValueError, IndexError, TypeError) as error:
            skipped.append({"province_id": province_id, "reason": str(error)})
    payload = {
        "world_px": float(source.get("world_px", WORLD_PX)),
        "cells": cells,
        "provenance": {
            "method": "v9_radial_arrival_time_collision_blocking",
            "source": "assets/provinces_iberia_selection_2km.json",
            "coast_margin_km": COAST_MARGIN_KM,
            "circle_count": CIRCLE_COUNT,
            "ray_count": RAY_COUNT,
            "speed_arc_count": SPEED_ARC_COUNT,
            "collision_passes": COLLISION_PASSES,
            "cleanup_passes": CLEANUP_PASSES,
            "raster_step_world_px": RASTER_STEP,
        },
    }
    report = {
        "ok": not skipped,
        "source_parts": len(source.get("cells", [])),
        "generated_cells": len(cells),
        "skipped": skipped,
        "provinces": validations,
    }
    return payload, report


def main() -> None:
    parser = argparse.ArgumentParser(description="Строит клетки Иберии по алгоритму V9 Collision Blocking.")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload, report = build()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    write_json(output, payload)
    write_json(REPORT, report)
    print(f"wrote {output.relative_to(ROOT)}: {len(payload['cells'])} cells")
    if report["skipped"]:
        print(f"skipped source parts: {len(report['skipped'])}")


if __name__ == "__main__":
    main()
