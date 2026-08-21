#!/usr/bin/env python3
from __future__ import annotations

import json, math, sys, copy
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
from shapely.geometry import Polygon, MultiPolygon, Point, LineString, MultiLineString
from shapely.ops import unary_union, linemerge

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / 'scripts' / 'tools'))
import build_land_cells_universal_v2 as v2  # noqa: E402

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
except Exception as exc:  # pragma: no cover
    raise RuntimeError(f'matplotlib required: {exc}')

FIXED_DIR = ROOT / 'manual_land_cell_iterations' / 'fixed_test_geometry'
DEFAULT_OUT_ROOT = ROOT / 'manual_land_cell_iterations' / 'output'


# manual expanded candidate overrides removed



@dataclass
class ManualConfig:
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
    # extra manual tuning / post-processing
    post_smooth_radius_world: float = 0.0
    post_smooth_rounds: int = 0
    post_simplify_world: float = 0.0
    boundary_min_shared_len: float = 1.0

    def to_base(self) -> v2.GeneratorConfig:
        return v2.GeneratorConfig(
            grid_size=self.grid_size,
            grid_padding=self.grid_padding,
            city_area_ratio=self.city_area_ratio,
            city_protection_ratio=self.city_protection_ratio,
            opponent_seed_count=self.opponent_seed_count,
            neck_strength=self.neck_strength,
            noise_strength=self.noise_strength,
            noise_scale_ratio=self.noise_scale_ratio,
            split_search_steps=self.split_search_steps,
            min_component_ratio=self.min_component_ratio,
            min_neck_lobe_ratio=self.min_neck_lobe_ratio,
            max_area_ratio_normal=self.max_area_ratio_normal,
            coverage_tolerance=self.coverage_tolerance,
            simplify_pixels=self.simplify_pixels,
            random_seed=self.random_seed,
        )


def load_test_geometry(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def polygon_from_rings(rings: list) -> Polygon | MultiPolygon:
    poly = Polygon(rings[0], rings[1:])
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly


def largest_polygon(geom):
    if geom.geom_type == 'Polygon':
        return geom
    if geom.geom_type == 'MultiPolygon':
        return max(geom.geoms, key=lambda p: p.area)
    return geom


def boundary_chains_from_geom(geom) -> list[list[tuple[float, float]]]:
    if geom.is_empty:
        return []
    try:
        merged = linemerge(geom)
    except Exception:
        merged = geom
    chains = []
    if isinstance(merged, LineString):
        chains.append(list(merged.coords))
    elif isinstance(merged, MultiLineString):
        for part in merged.geoms:
            chains.append(list(part.coords))
    else:
        try:
            for part in merged.geoms:
                chains.extend(boundary_chains_from_geom(part))
        except Exception:
            pass
    return [chain for chain in chains if len(chain) >= 2]


def chain_orientation_deg(chain: list[tuple[float, float]]) -> float:
    x0, y0 = chain[0]
    x1, y1 = chain[-1]
    ang = math.degrees(math.atan2(y1 - y0, x1 - x0))
    ang = abs((ang + 180.0) % 180.0)
    return ang


def chain_sinuosity(chain: list[tuple[float, float]]) -> float:
    if len(chain) < 2:
        return 1.0
    length = 0.0
    for a, b in zip(chain, chain[1:]):
        length += math.dist(a, b)
    direct = math.dist(chain[0], chain[-1])
    if direct <= 1e-9:
        return 1.0
    return length / direct


def sharp_turn_ratio(chain: list[tuple[float, float]], threshold_deg: float = 125.0) -> float:
    if len(chain) < 3:
        return 0.0
    sharp = 0
    total = 0
    for p0, p1, p2 in zip(chain, chain[1:], chain[2:]):
        v1 = (p0[0] - p1[0], p0[1] - p1[1])
        v2 = (p2[0] - p1[0], p2[1] - p1[1])
        n1 = math.hypot(*v1)
        n2 = math.hypot(*v2)
        if n1 < 1e-9 or n2 < 1e-9:
            continue
        dot = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
        angle = math.degrees(math.acos(dot))
        total += 1
        if angle < threshold_deg:
            sharp += 1
    return sharp / total if total else 0.0


def count_long_straight_sections(chain: list[tuple[float, float]], min_len: float = 10.0, max_dev_deg: float = 8.0) -> int:
    if len(chain) < 3:
        return 0
    count = 0
    run_len = 0.0
    prev_ang = None
    for a, b in zip(chain, chain[1:]):
        seg_len = math.dist(a, b)
        ang = chain_orientation_deg([a, b])
        if prev_ang is None or abs(((ang - prev_ang + 90) % 180) - 90) <= max_dev_deg:
            run_len += seg_len
        else:
            if run_len >= min_len:
                count += 1
            run_len = seg_len
        prev_ang = ang
    if run_len >= min_len:
        count += 1
    return count


def minimum_width(poly: Polygon) -> float:
    try:
        return float(poly.minimum_clearance)
    except Exception:
        return 0.0


def smooth_polygons(polygons: list[Polygon], province_poly: Polygon, cfg: ManualConfig) -> list[Polygon]:
    result = [poly for poly in polygons]
    if cfg.post_smooth_rounds <= 0 and cfg.post_simplify_world <= 0:
        return result
    for _ in range(max(cfg.post_smooth_rounds, 1) if cfg.post_simplify_world > 0 else cfg.post_smooth_rounds):
        if cfg.post_smooth_rounds > 0 and cfg.post_smooth_radius_world > 0:
            smoothed = []
            for poly in result:
                p = poly.buffer(cfg.post_smooth_radius_world, join_style=1).buffer(-cfg.post_smooth_radius_world, join_style=1)
                if p.is_empty:
                    p = poly
                if p.geom_type != 'Polygon':
                    p = largest_polygon(p)
                smoothed.append(p)
            result = v2.repair_polygon_coverage(smoothed, province_poly)
        if cfg.post_simplify_world > 0:
            simp = []
            for poly in result:
                p = poly.simplify(cfg.post_simplify_world, preserve_topology=True)
                if p.geom_type != 'Polygon':
                    p = largest_polygon(p)
                simp.append(p)
            result = v2.repair_polygon_coverage(simp, province_poly)
    return result


class FixedGeometryGenerator:
    def __init__(self, cfg: ManualConfig):
        self.cfg = cfg
        self.base_cfg = cfg.to_base()
        self.helper = v2.UniversalLandCellGenerator(self.base_cfg)

    def generate_one(self, territory: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], list[Polygon], Polygon]:
        province_poly = polygon_from_rings(territory['rings'])
        if province_poly.geom_type != 'Polygon':
            province_poly = largest_polygon(province_poly)
        area_km2 = float(territory['area_km2'])
        province = {
            'id': territory['id'],
            'numeric_id': territory['numeric_id'],
            'name': territory['name'],
            'display_name_ru': territory.get('display_name_ru', territory['name']),
            'legacy_id': territory['id'],
            'region_id': territory.get('region_id', 'manual_tests'),
        }
        geometry = {
            'id': territory['id'],
            'numeric_id': territory['numeric_id'],
            'name': territory['name'],
            'rings': territory['rings'],
            'area_km2': area_km2,
        }
        city = territory['city']
        city_xy = tuple(city['pos'])
        ctx = v2.build_raster_context(province_poly, area_km2, self.base_cfg)
        city_rc = ctx.world_to_rc(*city_xy)
        traversal_cost, shape_debug = v2.build_traversal_cost(ctx.mask, territory['id'], self.base_cfg)
        labels = np.zeros_like(ctx.mask, dtype=np.int32)
        leaf_masks, split_debug = v2.recursive_partition_city_first(
            ctx.mask,
            int(territory['cell_count']),
            traversal_cost,
            city_rc,
            self.base_cfg,
            territory['id'],
            depth=0,
            target_leaf_pixels=max(1, int(round(ctx.mask.sum() / int(territory['cell_count'])))),
        )
        for next_label, leaf in enumerate(leaf_masks, start=1):
            labels[leaf] = next_label
        labels = v2.repair_unlabelled_pixels(labels, ctx.mask)
        labels = v2.compact_label_ids(labels)
        polygons = v2.polygonize_labels(labels, ctx, province_poly, self.base_cfg)
        polygons = v2.repair_polygon_coverage(polygons, province_poly)
        polygons = smooth_polygons(polygons, province_poly, self.cfg)
        target_area = area_km2 / int(territory['cell_count'])
        cell_records, validation = self.helper._make_cells(province, geometry, polygons, city_xy, target_area, 'manual_test')
        debug = {
            'province_id': territory['id'],
            'province_name': territory['display_name_ru'],
            'province_name_en': territory['name'],
            'target_area_km2': round(target_area, 3),
            'source_area_km2': round(area_km2, 3),
            'requested_cell_count': int(territory['cell_count']),
            'city': city,
            'shape_analysis': shape_debug,
            'splits': split_debug,
            'validation': validation,
        }
        return cell_records, debug, polygons, province_poly


def compute_metrics(cells: list[dict[str, Any]], province_poly: Polygon, territory_name: str, cfg: ManualConfig) -> dict[str, Any]:
    polys = [polygon_from_rings(cell['rings']) for cell in cells]
    city_poly = polys[0]
    city_point = Point(cells[0]['label_point'])  # will replace below
    # use real city from record name? no fixed city in record, use centroid placeholder? corrected later in caller if needed.
    union = unary_union(polys)
    coverage_missing = float(province_poly.difference(union).area)
    coverage_extra = float(union.difference(province_poly).area)
    overlap = float(sum(p.area for p in polys) - union.area)
    shared_chains = []
    parallel_pairs = 0
    point_touches = 0
    touch_pairs = 0
    orientations = []
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            inter = polys[i].boundary.intersection(polys[j].boundary)
            shared_len = float(inter.length)
            if shared_len > cfg.boundary_min_shared_len:
                for chain in boundary_chains_from_geom(inter):
                    if len(chain) >= 2:
                        shared_chains.append(chain)
                        orientations.append(chain_orientation_deg(chain))
            else:
                if polys[i].touches(polys[j]):
                    point_touches += 1
            if polys[i].touches(polys[j]):
                touch_pairs += 1
    for i in range(len(orientations)):
        for j in range(i + 1, len(orientations)):
            diff = abs(((orientations[i] - orientations[j] + 90.0) % 180.0) - 90.0)
            if diff <= 10.0:
                parallel_pairs += 1
    sinuosity = [chain_sinuosity(c) for c in shared_chains] or [1.0]
    sharp = [sharp_turn_ratio(c) for c in shared_chains] or [0.0]
    straight_counts = [count_long_straight_sections(c) for c in shared_chains] or [0]
    widths = [minimum_width(p) for p in polys]
    tail_count = sum(1 for w in widths if w < 2.5)
    compacts = [float(c['compactness']) for c in cells]
    area_vals = [float(c['area_km2']) for c in cells]
    metrics = {
        'territory': territory_name,
        'coverage_ok': coverage_missing < 1e-6 and coverage_extra < 1e-6 and abs(overlap) < 1e-6,
        'overlap_ok': abs(overlap) < 1e-6,
        'connected': all(p.geom_type == 'Polygon' for p in polys),
        'adjacency_ok': all(sorted(a['neighbor_land_cell_ids']) == sorted(set(a['neighbor_land_cell_ids'])) for a in cells),
        'city_inside': True,
        'city_clearance_ratio': None,
        'area_ratio': round(max(area_vals) / max(min(area_vals), 1e-9), 4),
        'min_compactness': round(min(compacts), 4),
        'mean_compactness': round(float(np.mean(compacts)), 4),
        'mean_sinuosity': round(float(np.mean(sinuosity)), 4),
        'max_sinuosity': round(float(np.max(sinuosity)), 4),
        'sharp_turn_ratio': round(float(np.mean(sharp)), 4),
        'parallel_penalty': int(parallel_pairs),
        'internal_boundary_vertex_count': int(sum(len(c) for c in shared_chains)),
        'internal_boundary_total_length': round(float(sum(sum(math.dist(a,b) for a,b in zip(c,c[1:])) for c in shared_chains)), 4),
        'minimum_width': round(float(min(widths)), 4),
        'thin_tail_count': int(tail_count),
        'long_straight_sections': int(sum(straight_counts)),
        'same_direction_pairs': int(parallel_pairs),
        'point_touch_pairs': int(point_touches),
        'technical_errors': [],
    }
    return metrics


def combine_metrics(debug_validation: dict[str, Any], derived: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(derived)
    out['coverage_ok'] = bool(debug_validation.get('coverage_ok', out['coverage_ok']))
    out['connected'] = bool(debug_validation.get('all_cells_connected', out['connected']))
    out['adjacency_ok'] = bool(debug_validation.get('adjacency_is_symmetric', out['adjacency_ok']))
    out['city_inside'] = bool(debug_validation.get('city_inside_city_cell', out['city_inside']))
    out['city_clearance_ratio'] = float(debug_validation.get('city_clearance_ratio', 0.0))
    out['min_compactness'] = round(min(out['min_compactness'], float(debug_validation.get('min_compactness', out['min_compactness']))), 4)
    out['mean_compactness'] = round(float(debug_validation.get('mean_compactness', out['mean_compactness'])), 4)
    out['area_ratio'] = round(float(debug_validation.get('max_to_min_area_ratio', out['area_ratio'])), 4)
    if not out['coverage_ok']:
        out['technical_errors'].append('coverage_failed')
    if not out['connected']:
        out['technical_errors'].append('disconnected_cell')
    if not out['adjacency_ok']:
        out['technical_errors'].append('adjacency_asymmetry')
    if not out['city_inside']:
        out['technical_errors'].append('city_outside_city_cell')
    if out['point_touch_pairs'] > 0:
        out['technical_errors'].append('point_touch_pairs')
    return out


def score_metrics(all_metrics: list[dict[str, Any]]) -> float:
    penalty = 0.0
    for m in all_metrics:
        if not m['coverage_ok']:
            penalty += 80.0
        if not m['connected']:
            penalty += 80.0
        if not m['adjacency_ok']:
            penalty += 35.0
        if not m['city_inside']:
            penalty += 80.0
        if m['city_clearance_ratio'] is None or m['city_clearance_ratio'] < 0.28:
            penalty += 18.0
        penalty += max(0.0, m['area_ratio'] - 1.18) * 25.0
        penalty += abs(m['mean_sinuosity'] - 1.08) * 75.0
        penalty += m['sharp_turn_ratio'] * 35.0
        penalty += m['parallel_penalty'] * 2.4
        penalty += m['long_straight_sections'] * 2.5
        penalty += max(0.0, 0.22 - m['min_compactness']) * 30.0
        penalty += len(m['technical_errors']) * 25.0
    return round(max(0.0, 100.0 - penalty), 3)


def render_single(path: Path, title: str, province_poly: Polygon, polygons: list[Polygon], city_xy: tuple[float, float], metrics: dict[str, Any]) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 7.2), dpi=160)
    for idx, poly in enumerate(polygons, start=1):
        x, y = poly.exterior.xy
        ax.fill(x, y, alpha=0.55)
        ax.plot(x, y, linewidth=1.2)
        rp = poly.representative_point()
        ax.text(rp.x, rp.y, str(idx), ha='center', va='center', fontsize=10)
    x, y = province_poly.exterior.xy
    ax.plot(x, y, color='black', linewidth=1.8)
    ax.scatter([city_xy[0]], [city_xy[1]], marker='o', s=40, zorder=10)
    ax.set_title(
        f"{title}\n"
        f"cells={len(polygons)} area_ratio={metrics['area_ratio']} clearance={metrics['city_clearance_ratio']}\n"
        f"sinuosity={metrics['mean_sinuosity']} straight={metrics['long_straight_sections']} parallel={metrics['parallel_penalty']}",
        fontsize=10,
    )
    ax.set_aspect('equal')
    ax.invert_yaxis()
    ax.axis('off')
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)


def render_overview(path: Path, entries: list[tuple[str, Polygon, list[Polygon], tuple[float,float], dict[str,Any]]], iteration_label: str, score: float) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(12, 12), dpi=160)
    axes = axes.ravel()
    for ax, (title, province_poly, polygons, city_xy, metrics) in zip(axes, entries):
        for idx, poly in enumerate(polygons, start=1):
            x, y = poly.exterior.xy
            ax.fill(x, y, alpha=0.55)
            ax.plot(x, y, linewidth=1.0)
            rp = poly.representative_point()
            ax.text(rp.x, rp.y, str(idx), ha='center', va='center', fontsize=8)
        x, y = province_poly.exterior.xy
        ax.plot(x, y, color='black', linewidth=1.6)
        ax.scatter([city_xy[0]], [city_xy[1]], marker='o', s=28, zorder=10)
        ax.set_title(
            f"{title}\nAR {metrics['area_ratio']} | CLR {metrics['city_clearance_ratio']} | SIN {metrics['mean_sinuosity']}\n"
            f"STR {metrics['long_straight_sections']} | PAR {metrics['parallel_penalty']} | SHRP {metrics['sharp_turn_ratio']}",
            fontsize=8,
        )
        ax.set_aspect('equal')
        ax.invert_yaxis()
        ax.axis('off')
    fig.suptitle(f"{iteration_label} | score={score}", fontsize=14)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)


def run_iteration(cfg: ManualConfig, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generator = FixedGeometryGenerator(cfg)
    test_files = ['la_coruna.json', 'london.json', 'brittany.json', 'sicily.json']
    territories = [load_test_geometry(FIXED_DIR / name) for name in test_files]
    cells_payload = []
    per_territory = {}
    render_entries = []
    for terr in territories:
        cells, debug, polygons, province_poly = generator.generate_one(terr)
        derived = compute_metrics(cells, province_poly, terr['id'], cfg)
        metrics = combine_metrics(debug['validation'], derived)
        per_territory[terr['id']] = {
            'debug': debug,
            'metrics': metrics,
        }
        city_xy = tuple(terr['city']['pos'])
        title = terr.get('display_name_ru', terr['name'])
        png_name = {
            'province:2848': 'la_coruna.png',
            'province:4026': 'london.png',
            'test_brittany': 'brittany.png',
            'test_sicily': 'sicily.png',
        }[terr['id']]
        render_single(output_dir / png_name, title, province_poly, polygons, city_xy, metrics)
        render_entries.append((title, province_poly, polygons, city_xy, metrics))
        cells_payload.append({
            'territory': terr['id'],
            'name': title,
            'cells': cells,
            'metrics': metrics,
        })
    score = score_metrics([v['metrics'] for v in per_territory.values()])
    render_overview(output_dir / 'overview.png', render_entries, output_dir.name, score)
    aggregate = {
        'coverage_ok_all': all(v['metrics']['coverage_ok'] for v in per_territory.values()),
        'connected_all': all(v['metrics']['connected'] for v in per_territory.values()),
        'adjacency_ok_all': all(v['metrics']['adjacency_ok'] for v in per_territory.values()),
        'city_inside_all': all(v['metrics']['city_inside'] for v in per_territory.values()),
        'mean_area_ratio': round(float(np.mean([v['metrics']['area_ratio'] for v in per_territory.values()])), 4),
        'mean_sinuosity': round(float(np.mean([v['metrics']['mean_sinuosity'] for v in per_territory.values()])), 4),
        'mean_sharp_turn_ratio': round(float(np.mean([v['metrics']['sharp_turn_ratio'] for v in per_territory.values()])), 4),
        'parallel_penalty_total': int(sum(v['metrics']['parallel_penalty'] for v in per_territory.values())),
        'thin_tail_total': int(sum(v['metrics']['thin_tail_count'] for v in per_territory.values())),
        'long_straight_total': int(sum(v['metrics']['long_straight_sections'] for v in per_territory.values())),
        'technical_error_count': int(sum(len(v['metrics']['technical_errors']) for v in per_territory.values())),
    }
    (output_dir / 'cells.json').write_text(json.dumps(cells_payload, ensure_ascii=False, indent=2), encoding='utf-8')
    (output_dir / 'metrics.json').write_text(json.dumps({'territories': {k: v['metrics'] for k,v in per_territory.items()}, 'aggregate': aggregate, 'score': score}, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'territories': per_territory, 'aggregate': aggregate, 'score': score}


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--config-json', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    cfg = ManualConfig(**json.loads(args.config_json.read_text(encoding='utf-8')))
    run_iteration(cfg, args.output_dir)


if __name__ == '__main__':
    main()
