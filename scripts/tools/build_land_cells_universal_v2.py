#!/usr/bin/env python3
"""Universal city-first land-cell generator.

The generator is deliberately NOT a final multi-seed Voronoi partition.
It performs the following pipeline for every province:

1. Rasterize the final province polygon in a local high-resolution workspace.
2. Build a traversal-cost field. Narrow corridors and isthmuses are expensive,
   so competing regions tend to meet at natural necks.
3. Keep the city in the protected branch of every early split until it
   becomes one final leaf, so the city cell is produced first without carving
   an artificial oval bubble.
4. Detect medial-axis bottlenecks / peninsula necks.
5. Evaluate several deterministic split orientations and recursively split
   only one remaining region at a time (binary partition).
6. Polygonize the labels and simplify the whole coverage at once, preserving
   shared edges and the original province boundary.
7. Validate coverage, connectivity, cell areas, city clearance and adjacency.

The script can generate one province for debugging or a configured batch.
It uses the final province polygon as the source of truth and never clips land
through the ocean mask.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import rasterio.features
import shapely
from affine import Affine
from scipy.ndimage import distance_transform_edt, gaussian_filter, minimum_filter
from shapely.geometry import MultiPolygon, Point, Polygon, shape
from shapely.ops import nearest_points, unary_union
from skimage.graph import MCP_Geometric
from skimage.measure import label as cc_label
from skimage.morphology import medial_axis

import build_cells_test as cell_tools

try:
    import matplotlib.pyplot as plt
except ModuleNotFoundError:
    plt = None


ROOT = Path(__file__).resolve().parents[2]
GEOMETRY_PATH = ROOT / "assets/map_geometry/provinces.json"
PROVINCES_PATH = ROOT / "assets/game_data/provinces.json"
CITIES_PATH = ROOT / "assets/province_cities_iberia.json"
PROFILE_PATH = ROOT / "assets/game_data/land_cell_generation_profiles.json"
DEFAULT_OUT = ROOT / "assets/land_cells_universal_v2_preview.json"
DEFAULT_DEBUG_DIR = ROOT / "reports/land_cells_debug_v2"


@dataclass
class GeneratorConfig:
    grid_size: int = 320
    grid_padding: int = 4
    city_area_ratio: float = 1.00
    city_protection_ratio: float = 0.38
    opponent_seed_count: int = 7
    neck_strength: float = 2.8
    noise_strength: float = 0.22
    noise_scale_ratio: float = 0.055
    split_search_steps: int = 22
    min_component_ratio: float = 0.055
    min_neck_lobe_ratio: float = 0.12
    max_area_ratio_normal: float = 1.75
    coverage_tolerance: float = 1e-6
    simplify_pixels: float = 3.25
    random_seed: int = 20260714


@dataclass
class RasterContext:
    polygon: Polygon
    mask: np.ndarray
    transform: Affine
    inv_transform: Affine
    width: int
    height: int
    pixel_world_x: float
    pixel_world_y: float
    pixel_area_km2: float

    def world_to_rc(self, x: float, y: float) -> tuple[int, int]:
        col_f, row_f = self.inv_transform * (x, y)
        row = int(np.clip(round(row_f), 0, self.height - 1))
        col = int(np.clip(round(col_f), 0, self.width - 1))
        if self.mask[row, col]:
            return row, col
        # Snap to the nearest inside pixel.
        outside = ~self.mask
        _dist, indices = distance_transform_edt(outside, return_indices=True)
        return int(indices[0, row, col]), int(indices[1, row, col])

    def rc_to_world(self, row: int, col: int) -> tuple[float, float]:
        x, y = self.transform * (col + 0.5, row + 0.5)
        return float(x), float(y)


@dataclass
class NeckCandidate:
    row: int
    col: int
    radius_px: float
    component_ratio: float
    balance_error: float
    score: float
    seed_a: tuple[int, int]
    seed_b: tuple[int, int]


@dataclass
class GeneratedProvince:
    province: dict[str, Any]
    geometry: dict[str, Any]
    cells: list[dict[str, Any]]
    debug: dict[str, Any]


class UniversalLandCellGenerator:
    def __init__(self, config: GeneratorConfig):
        self.config = config
        self.geometry_doc = load_json(GEOMETRY_PATH)
        self.province_doc = load_json(PROVINCES_PATH)
        self.world_px = float(self.geometry_doc.get("world_px", 8192.0))
        self.geometry_by_id = {item["id"]: item for item in self.geometry_doc["provinces"]}
        self.province_by_id = {item["id"]: item for item in self.province_doc["provinces"]}
        self.province_by_name = {
            normalize_name(item.get("name", "")): item
            for item in self.province_doc["provinces"]
        }
        self.cities = load_cities()
        self.city_by_province_name = {
            normalize_name(item.get("province", "")): item for item in self.cities
        }
        self.profile_doc = load_json(PROFILE_PATH) if PROFILE_PATH.exists() else {"profiles": {}, "regions": {}}

    def generate(
        self,
        province_id: str,
        *,
        forced_cell_count: int | None = None,
        forced_target_area_km2: float | None = None,
        debug_dir: Path | None = None,
    ) -> GeneratedProvince:
        province = self.province_by_id[province_id]
        geometry = self.geometry_by_id[province_id]
        province_poly = polygon_from_rings(geometry["rings"])
        if province_poly.geom_type != "Polygon":
            province_poly = largest_polygon(province_poly)
        if province_poly is None or province_poly.is_empty:
            raise RuntimeError(f"{province_id}: empty province polygon")

        target_area, min_cells, max_cells, profile_id = self._resolve_profile(
            province,
            geometry,
            forced_target_area_km2,
        )
        area_km2 = float(geometry.get("area_km2") or polygon_area_km2(geometry["rings"]))
        cell_count = forced_cell_count or int(round(area_km2 / target_area))
        cell_count = max(min_cells, min(max_cells, max(1, cell_count)))

        city = self._resolve_city(province, province_poly)
        city_point = tuple(city["pos"])
        ctx = build_raster_context(province_poly, area_km2, self.config)
        city_rc = ctx.world_to_rc(*city_point)
        traversal_cost, shape_debug = build_traversal_cost(
            ctx.mask,
            province_id,
            self.config,
        )

        labels = np.zeros_like(ctx.mask, dtype=np.int32)
        debug_info: dict[str, Any] = {
            "province_id": province_id,
            "province_name": province.get("name", ""),
            "profile_id": profile_id,
            "target_area_km2": round(target_area, 3),
            "source_area_km2": round(area_km2, 3),
            "requested_cell_count": cell_count,
            "city": city,
            "city_source": city.get("source", "unknown"),
            "grid": {
                "width": ctx.width,
                "height": ctx.height,
                "pixel_area_km2": round(ctx.pixel_area_km2, 6),
            },
            "shape_analysis": shape_debug,
            "splits": [],
        }

        if cell_count == 1:
            labels[ctx.mask] = 1
        else:
            # The whole province is recursively partitioned. The branch that
            # contains the city is always processed first, until the city ends
            # up in one leaf. This gives the city cell two or more meaningful
            # open cuts instead of carving a closed circular bubble.
            leaf_masks, split_debug = recursive_partition_city_first(
                ctx.mask,
                cell_count,
                traversal_cost,
                city_rc,
                self.config,
                province_id,
                depth=0,
                target_leaf_pixels=max(1, int(round(ctx.mask.sum() / cell_count))),
            )
            for next_label, leaf in enumerate(leaf_masks, start=1):
                labels[leaf] = next_label
            debug_info["city_partition"] = {
                "method": "recursive_city_branch",
                "city_rc": list(city_rc),
                "city_leaf_pixels": int(leaf_masks[0].sum()),
                "target_pixels": round(int(ctx.mask.sum()) / cell_count),
            }
            debug_info["splits"].extend(split_debug)
            labels = repair_unlabelled_pixels(labels, ctx.mask)
            labels = compact_label_ids(labels)

        polygons = polygonize_labels(labels, ctx, province_poly, self.config)
        polygons = repair_polygon_coverage(polygons, province_poly)
        cell_records, validation = self._make_cells(
            province,
            geometry,
            polygons,
            city_point,
            target_area,
            profile_id,
        )
        debug_info["validation"] = validation
        debug_info["result_cell_count"] = len(cell_records)

        if debug_dir is not None:
            debug_dir.mkdir(parents=True, exist_ok=True)
            stem = safe_slug(province.get("name") or province_id)
            debug_root = debug_dir if debug_dir.is_absolute() else ROOT / debug_dir
            debug_path = debug_root / f"{stem}_{province_id.replace(':', '_')}.png"
            render_debug_preview(
                debug_path,
                province_poly,
                polygons,
                city_point,
                debug_info,
            )
            debug_info["preview_path"] = str(debug_path.relative_to(ROOT)).replace("\\", "/")

        return GeneratedProvince(province, geometry, cell_records, debug_info)

    def _resolve_profile(
        self,
        province: dict[str, Any],
        geometry: dict[str, Any],
        forced_target: float | None,
    ) -> tuple[float, int, int, str]:
        if forced_target is not None:
            return float(forced_target), 1, 24, "forced"

        region_id = province.get("region_id", "")
        region_rule = self.profile_doc.get("regions", {}).get(region_id, {})
        profile_id = region_rule.get("profile_id", "")
        profile = self.profile_doc.get("profiles", {}).get(profile_id, {})

        target = region_rule.get("target_cell_area_km2", profile.get("target_cell_area_km2"))
        if not target:
            # Safe fallback for an unconfigured province. This does not pretend
            # that the region is already classified; it merely keeps the CLI
            # usable for geometry tests.
            target = 4000.0
            profile_id = profile_id or "fallback_unconfigured"
        min_cells = int(region_rule.get("min_cells_per_province", profile.get("min_cells_per_province", 1)))
        max_cells = int(region_rule.get("max_cells_per_province", profile.get("max_cells_per_province", 16)))
        return float(target), min_cells, max_cells, profile_id

    def _resolve_city(self, province: dict[str, Any], polygon: Polygon) -> dict[str, Any]:
        name_key = normalize_name(province.get("name", ""))
        city = self.city_by_province_name.get(name_key)
        if city:
            point = Point(city["pos"])
            if polygon.buffer(1e-9).contains(point):
                return {**city, "source": "province_city_dataset"}
            if polygon.buffer(0.25).contains(point):
                # Some source city markers sit a few pixels offshore or just
                # across an imperfect administrative boundary. Preserve the
                # real coastal location but move it a tiny distance inside the
                # final province polygon so the city-cell invariant is exact.
                nearest = nearest_points(polygon, point)[0]
                interior = polygon.representative_point()
                snapped = Point(
                    nearest.x * 0.985 + interior.x * 0.015,
                    nearest.y * 0.985 + interior.y * 0.015,
                )
                if not polygon.buffer(1e-9).contains(snapped):
                    snapped = interior
                return {
                    **city,
                    "pos": [round(snapped.x, 4), round(snapped.y, 4)],
                    "source": "province_city_dataset_snapped_inside",
                    "original_pos": city["pos"],
                }

        representative = polygon.representative_point()
        return {
            "name": province.get("display_name_ru") or province.get("name") or province["id"],
            "province": province.get("name", ""),
            "pos": [round(representative.x, 4), round(representative.y, 4)],
            "source": "representative_point_fallback",
        }

    def _make_cells(
        self,
        province: dict[str, Any],
        geometry: dict[str, Any],
        polygons: list[Polygon],
        city_point_xy: tuple[float, float],
        target_area: float,
        profile_id: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        city_point = Point(city_point_xy)
        city_index = next(
            (i for i, poly in enumerate(polygons) if poly.buffer(1e-7).contains(city_point)),
            0,
        )

        # Put the city cell first, then order remaining cells clockwise around
        # the province centre for deterministic IDs.
        centre = unary_union(polygons).centroid
        remaining = [i for i in range(len(polygons)) if i != city_index]
        remaining.sort(key=lambda i: math.atan2(
            polygons[i].representative_point().y - centre.y,
            polygons[i].representative_point().x - centre.x,
        ))
        order = [city_index] + remaining
        ordered = [polygons[i] for i in order]

        ids = [f"land_cell:{province['numeric_id']}:{idx + 1:02d}" for idx in range(len(ordered))]
        neighbours: list[list[str]] = [[] for _ in ordered]
        shared_lengths = np.zeros((len(ordered), len(ordered)), dtype=float)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                shared = ordered[i].boundary.intersection(ordered[j].boundary)
                length = float(shared.length)
                if length > 1e-5:
                    neighbours[i].append(ids[j])
                    neighbours[j].append(ids[i])
                    shared_lengths[i, j] = shared_lengths[j, i] = length

        records: list[dict[str, Any]] = []
        areas: list[float] = []
        compactness_values: list[float] = []
        for idx, (cell_id, poly) in enumerate(zip(ids, ordered)):
            rings = rings_from_polygon(poly)
            area = polygon_area_km2(rings)
            areas.append(area)
            perimeter = max(float(poly.length), 1e-9)
            compactness = float(4.0 * math.pi * poly.area / (perimeter * perimeter))
            compactness_values.append(compactness)
            representative = poly.representative_point()
            centroid = poly.centroid
            brd_open, brd_boundary = cell_tools._split_border_chains(rings[0], unary_union(ordered).boundary)
            brd_open = cell_tools._trim_open_chains_to_land(brd_open, unary_union(ordered), unary_union(ordered))
            role = "city" if idx == 0 else "territory"
            records.append({
                "id": cell_id,
                "name": f"{province.get('display_name_ru') or province.get('name')} — {'городская клетка' if role == 'city' else f'клетка {idx + 1}'}",
                "province_id": province["id"],
                "legacy_province_id": province.get("legacy_id", ""),
                "region_id": province.get("region_id", ""),
                "profile_id": profile_id,
                "cell_role": role,
                "rings": rings,
                "brd_open": brd_open,
                "brd_boundary": brd_boundary,
                "bbox": bbox_from_rings(rings),
                "center": [round(centroid.x, 2), round(centroid.y, 2)],
                "label_point": [round(representative.x, 2), round(representative.y, 2)],
                "area_km2": round(area, 2),
                "target_area_km2": round(target_area, 2),
                "compactness": round(compactness, 4),
                "neighbor_land_cell_ids": sorted(neighbours[idx]),
            })

        province_poly = polygon_from_rings(geometry["rings"])
        coverage_union = unary_union(ordered)
        missing = float(province_poly.difference(coverage_union).area)
        extra = float(coverage_union.difference(province_poly).area)
        overlap = float(sum(poly.area for poly in ordered) - coverage_union.area)
        city_poly = ordered[0]
        internal_border = unary_union([
            city_poly.boundary.intersection(other.boundary)
            for other in ordered[1:]
        ])
        city_internal_clearance_world = float(internal_border.distance(city_point)) if not internal_border.is_empty else 0.0
        city_area = max(areas[0], 1e-9)
        city_equivalent_radius_km = math.sqrt(city_area / math.pi)
        # Convert world-pixel distance to km locally by comparing geometry area.
        world_area = max(province_poly.area, 1e-9)
        local_km_per_world = math.sqrt(float(geometry.get("area_km2", sum(areas))) / world_area)
        city_internal_clearance_km = city_internal_clearance_world * local_km_per_world

        validation = {
            "coverage_ok": missing < self.config.coverage_tolerance and extra < self.config.coverage_tolerance and abs(overlap) < self.config.coverage_tolerance,
            "missing_world_px2": round(missing, 9),
            "extra_world_px2": round(extra, 9),
            "overlap_world_px2": round(overlap, 9),
            "city_inside_city_cell": city_poly.buffer(1e-7).contains(city_point),
            "city_internal_clearance_km": round(city_internal_clearance_km, 3),
            "city_clearance_ratio": round(city_internal_clearance_km / max(city_equivalent_radius_km, 1e-9), 3),
            "cell_areas_km2": [round(v, 2) for v in areas],
            "min_area_km2": round(min(areas), 2),
            "max_area_km2": round(max(areas), 2),
            "max_to_min_area_ratio": round(max(areas) / max(min(areas), 1e-9), 3),
            "min_compactness": round(min(compactness_values), 4),
            "mean_compactness": round(float(np.mean(compactness_values)), 4),
            "all_cells_connected": all(poly.geom_type == "Polygon" for poly in ordered),
            "adjacency_is_symmetric": all(
                ids[i] in neighbours[j]
                for i in range(len(ids))
                for j in range(len(ids))
                if ids[j] in neighbours[i]
            ),
        }
        return records, validation


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_cities() -> list[dict[str, Any]]:
    if not CITIES_PATH.exists():
        return []
    return load_json(CITIES_PATH).get("cities", [])


def normalize_name(value: str) -> str:
    value = value.casefold().strip()
    value = re.sub(r"\s+", " ", value)
    return value


def safe_slug(value: str) -> str:
    value = value.casefold()
    value = re.sub(r"[^a-z0-9а-яё]+", "_", value, flags=re.IGNORECASE)
    return value.strip("_") or "province"


def polygon_from_rings(rings: list) -> Polygon | MultiPolygon:
    poly = Polygon(rings[0], rings[1:])
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly


def largest_polygon(geom) -> Polygon | None:
    if geom.is_empty:
        return None
    if geom.geom_type == "Polygon":
        return geom
    if geom.geom_type == "MultiPolygon":
        return max(geom.geoms, key=lambda part: part.area)
    return None


def rings_from_polygon(poly: Polygon) -> list[list[list[float]]]:
    rings = [[[round(x, 3), round(y, 3)] for x, y in poly.exterior.coords]]
    for hole in poly.interiors:
        rings.append([[round(x, 3), round(y, 3)] for x, y in hole.coords])
    return rings


def bbox_from_rings(rings: list) -> list[float]:
    xs = [point[0] for ring in rings for point in ring]
    ys = [point[1] for ring in rings for point in ring]
    return [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)]


def polygon_area_km2(rings: list) -> float:
    area = cell_tools.ring_area_km2_world_px(rings[0])
    for hole in rings[1:]:
        area -= cell_tools.ring_area_km2_world_px(hole)
    return max(float(area), 0.0)


def build_raster_context(poly: Polygon, area_km2: float, config: GeneratorConfig) -> RasterContext:
    minx, miny, maxx, maxy = poly.bounds
    width_world = maxx - minx
    height_world = maxy - miny
    longest = max(width_world, height_world, 1e-9)
    inner_size = max(96, config.grid_size - config.grid_padding * 2)
    scale = inner_size / longest
    width = max(64, int(math.ceil(width_world * scale)) + config.grid_padding * 2)
    height = max(64, int(math.ceil(height_world * scale)) + config.grid_padding * 2)

    pad_x = config.grid_padding / scale
    pad_y = config.grid_padding / scale
    bounds = (minx - pad_x, miny - pad_y, maxx + pad_x, maxy + pad_y)
    transform = rasterio.transform.from_bounds(*bounds, width=width, height=height)
    mask = rasterio.features.rasterize(
        [(poly, 1)],
        out_shape=(height, width),
        transform=transform,
        fill=0,
        all_touched=True,
        dtype="uint8",
    ).astype(bool)
    pixel_count = max(int(mask.sum()), 1)
    pixel_area_km2 = area_km2 / pixel_count
    inv = ~transform
    return RasterContext(
        polygon=poly,
        mask=mask,
        transform=transform,
        inv_transform=inv,
        width=width,
        height=height,
        pixel_world_x=abs(float(transform.a)),
        pixel_world_y=abs(float(transform.e)),
        pixel_area_km2=pixel_area_km2,
    )


def deterministic_rng(key: str, base_seed: int) -> np.random.Generator:
    digest = hashlib.sha256(f"{base_seed}:{key}".encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "little", signed=False)
    return np.random.default_rng(seed)


def build_traversal_cost(mask: np.ndarray, key: str, config: GeneratorConfig) -> tuple[np.ndarray, dict[str, Any]]:
    boundary_distance = distance_transform_edt(mask)
    max_distance = max(float(boundary_distance.max()), 1.0)

    # Narrow corridors have a low distance to both sides. Increasing their
    # traversal cost makes recursive regions meet at the neck instead of
    # cutting through broad lobes.
    neck_term = 1.0 / np.maximum(boundary_distance, 0.75)
    neck_term /= max(float(neck_term[mask].mean()), 1e-9)

    rng = deterministic_rng(key, config.random_seed)
    noise = rng.normal(0.0, 1.0, size=mask.shape)
    sigma = max(2.0, min(mask.shape) * config.noise_scale_ratio)
    noise = gaussian_filter(noise, sigma=sigma, mode="nearest")
    inside_noise = noise[mask]
    noise = (noise - float(inside_noise.mean())) / max(float(inside_noise.std()), 1e-9)
    noise = np.clip(noise, -2.0, 2.0) / 2.0

    cost = 1.0 + config.neck_strength * neck_term + config.noise_strength * noise
    cost = np.clip(cost, 0.35, 12.0)
    cost[~mask] = np.inf

    skeleton, skeleton_distance = medial_axis(mask, return_distance=True)
    neck_pixels = skeleton & (skeleton_distance <= np.percentile(skeleton_distance[skeleton], 35) if skeleton.any() else False)
    return cost, {
        "max_boundary_distance_px": round(max_distance, 3),
        "skeleton_pixel_count": int(skeleton.sum()),
        "low_radius_skeleton_pixels": int(neck_pixels.sum()),
        "noise_sigma_px": round(sigma, 3),
    }


def weighted_distance(mask: np.ndarray, cost: np.ndarray, starts: Iterable[tuple[int, int]]) -> np.ndarray:
    starts_list = [(int(r), int(c)) for r, c in starts if mask[int(r), int(c)]]
    if not starts_list:
        raise RuntimeError("weighted_distance: no valid starts")
    local_cost = np.where(mask, cost, np.inf)
    mcp = MCP_Geometric(local_cost, fully_connected=True)
    distances, _traceback = mcp.find_costs(starts=starts_list)
    distances[~mask] = np.inf
    return distances


def component_containing(mask: np.ndarray, seed: tuple[int, int]) -> np.ndarray:
    labelled = cc_label(mask, connectivity=2)
    component_id = int(labelled[seed])
    if component_id == 0:
        return np.zeros_like(mask, dtype=bool)
    return labelled == component_id


def connected_components(mask: np.ndarray) -> list[np.ndarray]:
    labelled = cc_label(mask, connectivity=2)
    components: list[np.ndarray] = []
    for component_id in range(1, int(labelled.max()) + 1):
        component = labelled == component_id
        if component.any():
            components.append(component)
    components.sort(key=lambda item: int(item.sum()), reverse=True)
    return components


def peak_pixel(mask: np.ndarray, score: np.ndarray | None = None) -> tuple[int, int]:
    if not mask.any():
        raise RuntimeError("peak_pixel on empty mask")
    if score is None:
        score = distance_transform_edt(mask)
    values = np.where(mask, score, -np.inf)
    flat = int(np.argmax(values))
    return tuple(int(v) for v in np.unravel_index(flat, mask.shape))


def tune_threshold_component(
    region: np.ndarray,
    diff: np.ndarray,
    seed: tuple[int, int],
    target_pixels: int,
    steps: int,
) -> tuple[np.ndarray, float, int]:
    finite = diff[region & np.isfinite(diff)]
    if finite.size == 0:
        raise RuntimeError("no finite distance difference")
    low = float(np.min(finite))
    high = float(np.max(finite))
    best_mask = np.zeros_like(region, dtype=bool)
    best_bias = 0.0
    best_error = float("inf")
    for _ in range(steps):
        bias = (low + high) * 0.5
        candidate = region & (diff <= bias)
        candidate = component_containing(candidate, seed)
        size = int(candidate.sum())
        error = abs(size - target_pixels)
        if error < best_error and size > 0:
            best_error = error
            best_mask = candidate
            best_bias = bias
        if size < target_pixels:
            low = bias
        else:
            high = bias
    return best_mask, best_bias, int(best_mask.sum())


def internal_border_distance_px(cell_mask: np.ndarray, province_mask: np.ndarray, seed: tuple[int, int]) -> float:
    # Only the border against another land cell counts. The coastline / outer
    # province boundary must not penalize a coastal city.
    neighbour_outside = province_mask & ~cell_mask
    if not neighbour_outside.any():
        return 0.0
    internal_border = cell_mask & binary_neighbour(neighbour_outside)
    if not internal_border.any():
        return 0.0
    points = np.argwhere(internal_border)
    return float(np.min(np.hypot(points[:, 0] - seed[0], points[:, 1] - seed[1])))


def binary_neighbour(mask: np.ndarray) -> np.ndarray:
    out = np.zeros_like(mask, dtype=bool)
    out[1:, :] |= mask[:-1, :]
    out[:-1, :] |= mask[1:, :]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    out[1:, 1:] |= mask[:-1, :-1]
    out[:-1, :-1] |= mask[1:, 1:]
    out[1:, :-1] |= mask[:-1, 1:]
    out[:-1, 1:] |= mask[1:, :-1]
    return out


def detect_best_neck(
    region: np.ndarray,
    desired_fraction: float,
    config: GeneratorConfig,
) -> NeckCandidate | None:
    if int(region.sum()) < 250:
        return None
    skeleton, dist = medial_axis(region, return_distance=True)
    if not skeleton.any():
        return None
    local_min = minimum_filter(dist, size=7, mode="nearest")
    candidates_mask = skeleton & (dist <= local_min + 0.35) & (dist >= 1.25)
    candidates = np.argwhere(candidates_mask)
    if len(candidates) == 0:
        return None

    # Keep at most 80 deterministic candidates, prioritizing small radii.
    candidates = sorted(candidates.tolist(), key=lambda rc: (dist[rc[0], rc[1]], rc[0], rc[1]))[:80]
    rr, cc = np.ogrid[:region.shape[0], :region.shape[1]]
    total = int(region.sum())
    best: NeckCandidate | None = None
    for row, col in candidates:
        radius = float(dist[row, col])
        cut_radius = max(2.0, radius * 1.15)
        removed = (rr - row) ** 2 + (cc - col) ** 2 <= cut_radius ** 2
        cut_region = region & ~removed
        components = connected_components(cut_region)
        if len(components) < 2:
            continue
        first, second = components[:2]
        a = int(first.sum())
        b = int(second.sum())
        if min(a, b) / total < config.min_neck_lobe_ratio:
            continue
        fraction = a / max(a + b, 1)
        fraction = min(fraction, 1.0 - fraction)
        desired_small = min(desired_fraction, 1.0 - desired_fraction)
        balance_error = abs(fraction - desired_small)
        radius_score = radius / max(float(dist[skeleton].max()), 1.0)
        leftover = max(0, total - a - b) / total
        score = balance_error * 3.0 + radius_score * 0.8 + leftover * 2.0
        seed_a = peak_pixel(first)
        seed_b = peak_pixel(second)
        candidate = NeckCandidate(
            row=row,
            col=col,
            radius_px=radius,
            component_ratio=fraction,
            balance_error=balance_error,
            score=score,
            seed_a=seed_a,
            seed_b=seed_b,
        )
        if best is None or candidate.score < best.score:
            best = candidate
    return best


def fallback_split_seeds(region: np.ndarray, cost: np.ndarray) -> tuple[tuple[int, int], tuple[int, int]]:
    boundary_distance = distance_transform_edt(region)
    seed_a = peak_pixel(region, boundary_distance)
    d_a = weighted_distance(region, cost, [seed_a])
    score = d_a * (0.40 + boundary_distance / max(float(boundary_distance.max()), 1.0))
    seed_b = peak_pixel(region, score)
    return seed_a, seed_b



def mask_compactness(mask: np.ndarray) -> float:
    """Raster compactness in [0, 1]; 1 is a circle-like compact region."""
    area = int(mask.sum())
    if area <= 0:
        return 0.0
    boundary = mask & binary_neighbour(~mask)
    perimeter = max(int(boundary.sum()), 1)
    value = 4.0 * math.pi * area / float(perimeter * perimeter)
    return float(np.clip(value, 0.0, 1.0))


def partition_quality(
    region: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    desired_fraction: float,
) -> dict[str, float]:
    total = max(int(region.sum()), 1)
    a_size = int(a.sum())
    b_size = int(b.sum())
    fraction = a_size / total
    balance_error = abs(fraction - desired_fraction)
    internal_border = a & binary_neighbour(b)
    border_norm = int(internal_border.sum()) / max(math.sqrt(total), 1.0)
    compact_a = mask_compactness(a)
    compact_b = mask_compactness(b)
    radius_a = float(distance_transform_edt(a).max()) if a.any() else 0.0
    radius_b = float(distance_transform_edt(b).max()) if b.any() else 0.0
    thickness_a = radius_a / max(math.sqrt(max(a_size, 1)), 1.0)
    thickness_b = radius_b / max(math.sqrt(max(b_size, 1)), 1.0)
    thin_penalty = max(0.0, 0.12 - thickness_a) + max(0.0, 0.12 - thickness_b)
    compact_penalty = (1.0 - compact_a) + (1.0 - compact_b)
    score = (
        balance_error * 6.0
        + border_norm * 0.42
        + compact_penalty * 0.70
        + thin_penalty * 10.0
    )
    return {
        "score": float(score),
        "balance_error": float(balance_error),
        "border_norm": float(border_norm),
        "compact_a": float(compact_a),
        "compact_b": float(compact_b),
        "thickness_a": float(thickness_a),
        "thickness_b": float(thickness_b),
    }


def interior_extreme_seed(region: np.ndarray, direction: np.ndarray) -> tuple[int, int]:
    coords = np.argwhere(region)
    if len(coords) == 0:
        raise RuntimeError("interior_extreme_seed on empty mask")
    center = coords.mean(axis=0)
    direction = np.asarray(direction, dtype=float)
    norm = float(np.linalg.norm(direction))
    if norm <= 1e-9:
        return peak_pixel(region)
    direction /= norm
    projections = (coords - center) @ direction
    boundary_distance = distance_transform_edt(region)
    bd = boundary_distance[coords[:, 0], coords[:, 1]]
    proj_span = max(float(np.ptp(projections)), 1.0)
    bd_span = max(float(bd.max()), 1.0)
    score = projections / proj_span + 0.34 * bd / bd_span
    index = int(np.argmax(score))
    return int(coords[index, 0]), int(coords[index, 1])


def candidate_seed_pairs(
    region: np.ndarray,
    cost: np.ndarray,
    neck: NeckCandidate | None,
) -> list[tuple[str, tuple[int, int], tuple[int, int]]]:
    pairs: list[tuple[str, tuple[int, int], tuple[int, int]]] = []
    if neck is not None:
        pairs.append(("medial_axis_neck", neck.seed_a, neck.seed_b))

    fallback_a, fallback_b = fallback_split_seeds(region, cost)
    pairs.append(("weighted_farthest", fallback_a, fallback_b))

    coords = np.argwhere(region)
    if len(coords) >= 8:
        centered = coords - coords.mean(axis=0)
        covariance = np.cov(centered.T)
        values, vectors = np.linalg.eigh(covariance)
        order = np.argsort(values)[::-1]
        axes = [vectors[:, order[0]], vectors[:, order[1]]]
        principal = axes[0]
        # Principal, secondary and two broad rotated alternatives. These are
        # candidate seed axes; the actual border remains a weighted geodesic
        # bisector and therefore follows necks/noise rather than a straight line.
        angle = math.atan2(float(principal[0]), float(principal[1]))
        for name, delta in [
            ("pca_primary", 0.0),
            ("pca_secondary", math.pi / 2.0),
            ("pca_rotated_plus", math.pi / 5.0),
            ("pca_rotated_minus", -math.pi / 5.0),
        ]:
            direction = np.array([math.sin(angle + delta), math.cos(angle + delta)])
            seed_a = interior_extreme_seed(region, direction)
            seed_b = interior_extreme_seed(region, -direction)
            pairs.append((name, seed_a, seed_b))

    unique: list[tuple[str, tuple[int, int], tuple[int, int]]] = []
    seen: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for name, a, b in pairs:
        if a == b:
            continue
        key = tuple(sorted((a, b)))
        if key in seen:
            continue
        seen.add(key)
        unique.append((name, a, b))
    return unique


def candidate_city_opponents(
    region: np.ndarray,
    cost: np.ndarray,
    city_rc: tuple[int, int],
) -> list[tuple[str, tuple[int, int]]]:
    city_distance = weighted_distance(region, cost, [city_rc])
    boundary_distance = distance_transform_edt(region)
    score = city_distance * (0.45 + boundary_distance / max(float(boundary_distance.max()), 1.0))
    candidates: list[tuple[str, tuple[int, int]]] = [
        ("weighted_farthest", peak_pixel(region, score)),
        ("pure_geodesic_farthest", peak_pixel(region, city_distance)),
    ]
    coords = np.argwhere(region)
    if len(coords) >= 8:
        centered = coords - coords.mean(axis=0)
        covariance = np.cov(centered.T)
        values, vectors = np.linalg.eigh(covariance)
        order = np.argsort(values)[::-1]
        for idx, axis_name in [(order[0], "pca_primary"), (order[1], "pca_secondary")]:
            axis = vectors[:, idx]
            first = interior_extreme_seed(region, axis)
            second = interior_extreme_seed(region, -axis)
            chosen = first if math.dist(first, city_rc) >= math.dist(second, city_rc) else second
            candidates.append((axis_name, chosen))
    unique: list[tuple[str, tuple[int, int]]] = []
    seen: set[tuple[int, int]] = set()
    for name, seed in candidates:
        if seed == city_rc or seed in seen:
            continue
        seen.add(seed)
        unique.append((name, seed))
    return unique


def repair_binary_partition(
    region: np.ndarray,
    a_mask: np.ndarray,
    seed_a: tuple[int, int],
    seed_b: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray]:
    a = component_containing(a_mask, seed_a)
    b = component_containing(region & ~a, seed_b)
    assigned = a | b
    leftovers = connected_components(region & ~assigned)
    for component in leftovers:
        touches_a = int((component & binary_neighbour(a)).sum())
        touches_b = int((component & binary_neighbour(b)).sum())
        if touches_a >= touches_b:
            a |= component
        else:
            b |= component
    a = component_containing(a, seed_a)
    b = region & ~a
    b = component_containing(b, seed_b)
    if not a.any() or not b.any() or int((a | b).sum()) != int(region.sum()):
        # Last-resort deterministic assignment preserving the region.
        b = region & ~a
        if not b.any():
            raise RuntimeError("binary partition collapsed")
    return a, b


def split_region_binary(
    region: np.ndarray,
    left_count: int,
    total_count: int,
    cost: np.ndarray,
    config: GeneratorConfig,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    desired_fraction = left_count / total_count
    neck = detect_best_neck(region, desired_fraction, config)
    candidates: list[tuple[float, np.ndarray, np.ndarray, dict[str, Any]]] = []

    for method, seed_a, seed_b in candidate_seed_pairs(region, cost, neck):
        try:
            d_a = weighted_distance(region, cost, [seed_a])
            d_b = weighted_distance(region, cost, [seed_b])
            diff = np.full_like(d_a, np.inf, dtype=float)
            valid = region & np.isfinite(d_a) & np.isfinite(d_b)
            diff[valid] = d_a[valid] - d_b[valid]
            target_pixels = int(round(int(region.sum()) * desired_fraction))
            a, bias, _actual = tune_threshold_component(
                region,
                diff,
                seed_a,
                target_pixels,
                config.split_search_steps,
            )
            a, b = repair_binary_partition(region, a, seed_a, seed_b)
        except (RuntimeError, ValueError):
            continue

        min_fraction = min(int(a.sum()), int(b.sum())) / max(int(region.sum()), 1)
        if min_fraction < config.min_component_ratio:
            continue
        quality = partition_quality(region, a, b, desired_fraction)
        # A confirmed skeleton neck is a real shape signal, not merely another
        # seed pair. Give it a restrained bonus while still allowing a much
        # cleaner compact fallback to win.
        neck_bonus = -0.26 if method == "medial_axis_neck" else 0.0
        total_score = quality["score"] + neck_bonus
        detail = {
            "method": method,
            "region_pixels": int(region.sum()),
            "left_count": left_count,
            "right_count": total_count - left_count,
            "target_fraction": round(desired_fraction, 4),
            "actual_fraction": round(int(a.sum()) / max(int(region.sum()), 1), 4),
            "seed_a_rc": list(seed_a),
            "seed_b_rc": list(seed_b),
            "bias": round(float(bias), 5),
            "candidate_score": round(float(total_score), 5),
            "quality": {key: round(value, 5) for key, value in quality.items()},
        }
        if neck is not None and method == "medial_axis_neck":
            detail["neck"] = {
                "rc": [neck.row, neck.col],
                "radius_px": round(neck.radius_px, 3),
                "component_ratio": round(neck.component_ratio, 4),
                "balance_error": round(neck.balance_error, 4),
                "score": round(neck.score, 4),
            }
        candidates.append((total_score, a, b, detail))

    if not candidates:
        seed_a, seed_b = fallback_split_seeds(region, cost)
        d_a = weighted_distance(region, cost, [seed_a])
        d_b = weighted_distance(region, cost, [seed_b])
        diff = np.full_like(d_a, np.inf, dtype=float)
        valid = region & np.isfinite(d_a) & np.isfinite(d_b)
        diff[valid] = d_a[valid] - d_b[valid]
        target_pixels = int(round(int(region.sum()) * desired_fraction))
        a, bias, _actual = tune_threshold_component(region, diff, seed_a, target_pixels, config.split_search_steps)
        a, b = repair_binary_partition(region, a, seed_a, seed_b)
        quality = partition_quality(region, a, b, desired_fraction)
        debug = {
            "method": "emergency_weighted_farthest",
            "region_pixels": int(region.sum()),
            "left_count": left_count,
            "right_count": total_count - left_count,
            "target_fraction": round(desired_fraction, 4),
            "actual_fraction": round(int(a.sum()) / max(int(region.sum()), 1), 4),
            "seed_a_rc": list(seed_a),
            "seed_b_rc": list(seed_b),
            "bias": round(float(bias), 5),
            "quality": {key: round(value, 5) for key, value in quality.items()},
        }
        return a, b, debug

    candidates.sort(key=lambda item: item[0])
    _score, best_a, best_b, best_debug = candidates[0]
    best_debug["candidate_count"] = len(candidates)
    best_debug["runner_up_scores"] = [round(float(item[0]), 5) for item in candidates[1:4]]
    return best_a, best_b, best_debug


def split_region_with_city(
    region: np.ndarray,
    city_rc: tuple[int, int],
    city_side_count: int,
    total_count: int,
    cost: np.ndarray,
    config: GeneratorConfig,
    target_leaf_pixels: int,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if not region[city_rc]:
        raise RuntimeError("city seed is outside the current city branch")

    city_distance = weighted_distance(region, cost, [city_rc])
    desired_fraction = city_side_count / total_count
    target_pixels = int(round(int(region.sum()) * desired_fraction))
    equivalent_radius_px = math.sqrt(max(target_leaf_pixels, 1) / math.pi)
    required_clearance = config.city_protection_ratio * equivalent_radius_px
    rr, cc = np.indices(region.shape)
    protected = region & ((rr - city_rc[0]) ** 2 + (cc - city_rc[1]) ** 2 <= required_clearance ** 2)

    candidates: list[tuple[float, np.ndarray, np.ndarray, dict[str, Any]]] = []
    for method, seed_b in candidate_city_opponents(region, cost, city_rc):
        try:
            other_distance = weighted_distance(region, cost, [seed_b])
            diff = np.full_like(city_distance, np.inf, dtype=float)
            valid = region & np.isfinite(city_distance) & np.isfinite(other_distance)
            diff[valid] = city_distance[valid] - other_distance[valid]
            city_side, bias, _actual = tune_threshold_component(
                region,
                diff,
                city_rc,
                target_pixels,
                config.split_search_steps,
            )
            # Hard city protection: all land within the protected radius belongs
            # to the city branch. This acts only against INTERNAL borders; the
            # province coast/outer edge is naturally allowed to be close.
            city_side |= protected
            city_side, other_side = repair_binary_partition(region, city_side, city_rc, seed_b)
        except (RuntimeError, ValueError):
            continue

        other_fraction = int(other_side.sum()) / max(int(region.sum()), 1)
        if other_fraction < config.min_component_ratio:
            continue
        clearance = internal_border_distance_px(city_side, region, city_rc)
        quality = partition_quality(region, city_side, other_side, desired_fraction)
        clearance_deficit = max(0.0, required_clearance - clearance) / max(required_clearance, 1e-9)
        oversize = max(0.0, int(city_side.sum()) / max(int(region.sum()), 1) - min(0.88, desired_fraction + 0.18))
        total_score = quality["score"] + clearance_deficit * 12.0 + oversize * 8.0
        detail = {
            "method": f"city_branch_{method}",
            "region_pixels": int(region.sum()),
            "city_side_count": city_side_count,
            "other_side_count": total_count - city_side_count,
            "target_fraction": round(desired_fraction, 4),
            "actual_fraction": round(int(city_side.sum()) / max(int(region.sum()), 1), 4),
            "city_rc": list(city_rc),
            "opponent_seed_rc": list(seed_b),
            "bias": round(float(bias), 5),
            "city_clearance_px": round(float(clearance), 3),
            "required_clearance_px": round(float(required_clearance), 3),
            "candidate_score": round(float(total_score), 5),
            "quality": {key: round(value, 5) for key, value in quality.items()},
        }
        candidates.append((total_score, city_side, other_side, detail))

    if not candidates:
        raise RuntimeError("no valid city split candidates")
    candidates.sort(key=lambda item: item[0])
    _score, best_city, best_other, best_debug = candidates[0]
    best_debug["candidate_count"] = len(candidates)
    best_debug["runner_up_scores"] = [round(float(item[0]), 5) for item in candidates[1:4]]
    return best_city, best_other, best_debug


def recursive_partition_city_first(
    region: np.ndarray,
    cell_count: int,
    cost: np.ndarray,
    city_rc: tuple[int, int],
    config: GeneratorConfig,
    key: str,
    depth: int,
    target_leaf_pixels: int,
) -> tuple[list[np.ndarray], list[dict[str, Any]]]:
    if cell_count <= 1:
        return [region], []

    # Keep the city in the slightly larger branch for odd counts. Repeating
    # this process surrounds an inland city with several sequential cuts and
    # gives a coastal city a natural coast-facing leaf.
    city_side_count = (cell_count + 1) // 2
    other_side_count = cell_count - city_side_count
    city_side, other_side, debug = split_region_with_city(
        region,
        city_rc,
        city_side_count,
        cell_count,
        cost,
        config,
        target_leaf_pixels,
    )
    debug["depth"] = depth

    city_leaves, city_debug = recursive_partition_city_first(
        city_side,
        city_side_count,
        cost,
        city_rc,
        config,
        key + "C",
        depth + 1,
        target_leaf_pixels,
    )
    other_leaves, other_debug = recursive_partition(
        other_side,
        other_side_count,
        cost,
        config,
        key + "O",
        depth + 1,
    )
    # City leaf stays first for deterministic ID ...:01.
    return city_leaves + other_leaves, [debug] + city_debug + other_debug


def recursive_partition(
    region: np.ndarray,
    cell_count: int,
    cost: np.ndarray,
    config: GeneratorConfig,
    key: str,
    depth: int,
) -> tuple[list[np.ndarray], list[dict[str, Any]]]:
    if cell_count <= 1:
        return [region], []
    left_count = cell_count // 2
    right_count = cell_count - left_count
    left, right, debug = split_region_binary(
        region,
        left_count,
        cell_count,
        cost,
        config,
    )
    debug["depth"] = depth
    left_leaves, left_debug = recursive_partition(
        left,
        left_count,
        cost,
        config,
        key + "L",
        depth + 1,
    )
    right_leaves, right_debug = recursive_partition(
        right,
        right_count,
        cost,
        config,
        key + "R",
        depth + 1,
    )
    return left_leaves + right_leaves, [debug] + left_debug + right_debug


def repair_unlabelled_pixels(labels: np.ndarray, province_mask: np.ndarray) -> np.ndarray:
    out = labels.copy()
    missing = province_mask & (out == 0)
    if not missing.any():
        return out
    # Multi-source nearest-label propagation.
    labelled_mask = out > 0
    _dist, indices = distance_transform_edt(~labelled_mask, return_indices=True)
    out[missing] = out[indices[0, missing], indices[1, missing]]
    return out


def compact_label_ids(labels: np.ndarray) -> np.ndarray:
    out = np.zeros_like(labels, dtype=np.int32)
    values = sorted(int(value) for value in np.unique(labels) if value > 0)
    for new_value, old_value in enumerate(values, start=1):
        out[labels == old_value] = new_value
    return out


def polygonize_labels(
    labels: np.ndarray,
    ctx: RasterContext,
    province_poly: Polygon,
    config: GeneratorConfig,
) -> list[Polygon]:
    grouped: dict[int, list[Polygon]] = {}
    for geom_mapping, value in rasterio.features.shapes(
        labels.astype(np.int32),
        mask=labels > 0,
        transform=ctx.transform,
        connectivity=8,
    ):
        label_value = int(value)
        geom = shape(geom_mapping).intersection(province_poly)
        if geom.is_empty:
            continue
        if geom.geom_type == "Polygon":
            grouped.setdefault(label_value, []).append(geom)
        elif geom.geom_type == "MultiPolygon":
            grouped.setdefault(label_value, []).extend(list(geom.geoms))

    # Raster clipping can leave a label with a one-pixel disconnected shard
    # (usually inside a deep coastal concavity). Keep the largest component for
    # that label and transfer every tiny shard to a cell that shares a real edge
    # with it. Final game cells must remain connected Polygons.
    label_values = sorted(grouped)
    main_by_label: dict[int, Polygon] = {}
    extras: list[tuple[Polygon, int]] = []
    for label_value in label_values:
        geom = unary_union(grouped[label_value]).buffer(0)
        if geom.geom_type == "MultiPolygon":
            parts = sorted(list(geom.geoms), key=lambda part: part.area, reverse=True)
            main_by_label[label_value] = parts[0]
            extras.extend((part, label_value) for part in parts[1:])
        else:
            main_by_label[label_value] = geom

    for extra, original_label in sorted(extras, key=lambda item: item[0].area, reverse=True):
        best_label: int | None = None
        best_score = -1.0
        for label_value, main in main_by_label.items():
            merged = main.union(extra).buffer(0)
            if merged.geom_type != "Polygon":
                continue
            shared = float(main.boundary.intersection(extra.boundary).length)
            # Prefer a genuine shared edge; area is only a deterministic tie-break.
            score = shared * 1_000_000.0 + float(main.area)
            if score > best_score:
                best_score = score
                best_label = label_value
        if best_label is None:
            # Extremely rare point-touch artifact: attach to the closest cell
            # through a microscopic bridge smaller than one raster pixel.
            best_label = min(
                main_by_label,
                key=lambda label_value: main_by_label[label_value].distance(extra),
            )
            bridge = main_by_label[best_label].buffer(max(ctx.pixel_world_x, ctx.pixel_world_y) * 0.08)
            main_by_label[best_label] = bridge.union(extra).intersection(province_poly).buffer(0)
        else:
            main_by_label[best_label] = main_by_label[best_label].union(extra).buffer(0)

    polygons: list[Polygon] = [main_by_label[label_value] for label_value in label_values]

    # Simplify the complete coverage in one operation. Shared edges remain
    # exactly identical, and the external province boundary is untouched.
    tolerance = max(ctx.pixel_world_x, ctx.pixel_world_y) * config.simplify_pixels
    simplified = shapely.coverage_simplify(
        np.array(polygons, dtype=object),
        tolerance=tolerance,
        simplify_boundary=False,
    )
    return [geom.buffer(0) for geom in simplified]


def repair_polygon_coverage(polygons: list[Polygon], province_poly: Polygon) -> list[Polygon]:
    # Clip strictly to the final province and assign any numeric residue to the
    # cell sharing the longest border with it.
    result = [poly.intersection(province_poly).buffer(0) for poly in polygons]
    union = unary_union(result)
    missing = province_poly.difference(union)
    if not missing.is_empty and missing.area > 1e-10:
        pieces = [missing] if missing.geom_type == "Polygon" else list(missing.geoms)
        for piece in pieces:
            index = max(
                range(len(result)),
                key=lambda i: float(result[i].boundary.intersection(piece.boundary).length),
            )
            result[index] = result[index].union(piece).buffer(0)

    # Remove any possible overlap deterministically in list order.
    occupied = Polygon()
    cleaned: list[Polygon] = []
    for poly in result:
        current = poly.difference(occupied).buffer(0)
        if current.geom_type == "MultiPolygon":
            current = largest_polygon(current) or current
        cleaned.append(current)
        occupied = occupied.union(current)

    final_missing = province_poly.difference(unary_union(cleaned))
    if not final_missing.is_empty and final_missing.area > 1e-10:
        index = max(
            range(len(cleaned)),
            key=lambda i: float(cleaned[i].boundary.intersection(final_missing.boundary).length),
        )
        cleaned[index] = cleaned[index].union(final_missing).buffer(0)
    return cleaned


def render_debug_preview(
    path: Path,
    province_poly: Polygon,
    cells: list[Polygon],
    city_xy: tuple[float, float],
    debug: dict[str, Any],
) -> None:
    if plt is None:
        raise RuntimeError("matplotlib is required for debug images; run with --no-debug-images or install requirements_land_cells_v2.txt")
    fig, ax = plt.subplots(figsize=(9, 9), dpi=160)
    for index, poly in enumerate(cells):
        geoms = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)
        for geom in geoms:
            x, y = geom.exterior.xy
            ax.fill(x, y, alpha=0.55, label=f"Клетка {index + 1}" if geom is geoms[0] else None)
            ax.plot(x, y, linewidth=1.25)
    x, y = province_poly.exterior.xy
    ax.plot(x, y, linewidth=2.0)
    ax.scatter([city_xy[0]], [city_xy[1]], s=55, marker="o", zorder=20)
    ax.annotate("Город", city_xy, xytext=(5, 5), textcoords="offset points")
    validation = debug.get("validation", {})
    ax.set_title(
        f"{debug.get('province_name')} — {len(cells)} клеток\n"
        f"coverage={validation.get('coverage_ok')}, "
        f"area ratio={validation.get('max_to_min_area_ratio')}, "
        f"city clearance={validation.get('city_clearance_ratio')}"
    )
    ax.set_aspect("equal")
    ax.invert_yaxis()
    ax.axis("off")
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def find_province_id(generator: UniversalLandCellGenerator, value: str) -> str:
    if value in generator.province_by_id:
        return value
    normalized = normalize_name(value)
    exact = generator.province_by_name.get(normalized)
    if exact:
        return exact["id"]
    candidates = [
        item for item in generator.province_doc["provinces"]
        if normalized in normalize_name(item.get("name", ""))
    ]
    if len(candidates) == 1:
        return candidates[0]["id"]
    raise KeyError(f"Province not found or ambiguous: {value}")


def write_payload(path: Path, generated: list[GeneratedProvince], world_px: float) -> None:
    payload = {
        "schema_version": 1,
        "kind": "universal_city_first_land_cells",
        "world_px": world_px,
        "method": "city_first_recursive_binary_multi_candidate_v2",
        "source": {
            "geometry": str(GEOMETRY_PATH.relative_to(ROOT)).replace("\\", "/"),
            "provinces": str(PROVINCES_PATH.relative_to(ROOT)).replace("\\", "/"),
            "cities": str(CITIES_PATH.relative_to(ROOT)).replace("\\", "/"),
            "profiles": str(PROFILE_PATH.relative_to(ROOT)).replace("\\", "/") if PROFILE_PATH.exists() else None,
        },
        "provinces": [item.debug for item in generated],
        "cells": [cell for item in generated for cell in item.cells],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--province", action="append", default=[], help="province ID or exact name; repeatable")
    parser.add_argument("--cell-count", type=int, help="forced cell count; only for a single province")
    parser.add_argument("--target-area-km2", type=float, help="forced target cell area")
    parser.add_argument("--grid-size", type=int, default=320)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--debug-dir", type=Path, default=DEFAULT_DEBUG_DIR)
    parser.add_argument("--no-debug-images", action="store_true")
    parser.add_argument("--all-configured", action="store_true", help="generate all provinces with configured region profiles")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.no_debug_images and plt is None:
        raise SystemExit(
            "matplotlib is required for debug images; run with --no-debug-images "
            "or install requirements_land_cells_v2.txt"
        )
    config = GeneratorConfig(grid_size=max(128, args.grid_size))
    generator = UniversalLandCellGenerator(config)

    province_ids: list[str] = []
    for value in args.province:
        province_ids.append(find_province_id(generator, value))
    if args.all_configured:
        configured_regions = set(generator.profile_doc.get("regions", {}))
        province_ids.extend(
            item["id"] for item in generator.province_doc["provinces"]
            if item.get("region_id") in configured_regions
        )
    if not province_ids:
        province_ids = [find_province_id(generator, "La Coruña")]
    province_ids = list(dict.fromkeys(province_ids))

    if args.cell_count is not None and len(province_ids) != 1:
        raise SystemExit("--cell-count can only be used with one province")

    generated: list[GeneratedProvince] = []
    debug_dir = None if args.no_debug_images else args.debug_dir
    for index, province_id in enumerate(province_ids, start=1):
        print(f"[{index}/{len(province_ids)}] {province_id} ...", flush=True)
        item = generator.generate(
            province_id,
            forced_cell_count=args.cell_count,
            forced_target_area_km2=args.target_area_km2,
            debug_dir=debug_dir,
        )
        generated.append(item)
        validation = item.debug["validation"]
        print(
            f"  cells={len(item.cells)} coverage={validation['coverage_ok']} "
            f"area_ratio={validation['max_to_min_area_ratio']} "
            f"city_clearance={validation['city_clearance_ratio']}",
            flush=True,
        )

    write_payload(args.output, generated, generator.world_px)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
