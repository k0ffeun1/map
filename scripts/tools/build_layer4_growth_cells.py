#!/usr/bin/env python3
"""Build four noisy-growth cells inside every province from map layer 4."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from shapely.geometry import Point, Polygon

import build_lacoruna_growth_cells as core


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "assets" / "provinces_iberia.json"
OUTPUT = ROOT / "assets" / "cells_layer4_growth.json"
REPORT = ROOT / "assets" / "cell_topology" / "layer4_growth_validation.json"
SEED_COUNT = 4
GRID_STEP = 0.75


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def choose_seeds(cells: list[tuple[float, float]], polygon: Polygon, count: int) -> list[tuple[float, float]]:
    centroid = polygon.representative_point()
    first = min(cells, key=lambda item: Point(item).distance(centroid))
    result = [first]
    while len(result) < count:
        candidate = max(
            cells,
            key=lambda item: min(
                (item[0] - seed[0]) ** 2 + (item[1] - seed[1]) ** 2
                for seed in result
            ),
        )
        if candidate in result:
            break
        result.append(candidate)
    return result


def build(noise_scale: float, noise_strength: float) -> tuple[dict[str, Any], dict[str, Any]]:
    source = load_json(SOURCE)
    core.GRID_STEP = GRID_STEP
    core.NOISE_SCALE = noise_scale
    core.NOISE_STRENGTH = noise_strength
    output_cells: list[dict[str, Any]] = []
    skipped: list[str] = []

    for province in source.get("cells", []):
        province_id = str(province.get("id", ""))
        province_name = str(province.get("name", province_id))
        try:
            polygon = core.as_polygon(province)
            cells, index_by_grid, _origin = core.grid_mask(polygon)
            if not cells:
                skipped.append(province_id)
                continue
            seeds = choose_seeds(cells, polygon, min(SEED_COUNT, len(cells)))
            core.SEEDS = [
                (f"growth:{province_id}:{index + 1:02d}", f"{province_name} {index + 1}", seed)
                for index, seed in enumerate(seeds)
            ]
            owners = core.grow_regions(polygon, cells, index_by_grid)
            polygons = core.region_polygons(polygon, cells, owners)
            borders, neighbours = core.grid_shared_borders(index_by_grid, owners)
            for index, cell_polygon in enumerate(polygons):
                cell_id, cell_name, seed = core.SEEDS[index]
                label = cell_polygon.representative_point()
                area = cell_polygon.area * core.km_per_world_px(label.y) ** 2
                output_cells.append({
                    "id": cell_id,
                    "name": cell_name,
                    "parent_province_id": province_id,
                    "parent_province_name": province_name,
                    "profile_id": "P4-layer4-growth",
                    "area_km2": round(area, 2),
                    "rings": core.rings_from_polygon(cell_polygon),
                    "bbox": [round(value, 4) for value in cell_polygon.bounds],
                    "center": [round(cell_polygon.centroid.x, 4), round(cell_polygon.centroid.y, 4)],
                    "label_point": [round(label.x, 4), round(label.y, 4)],
                    "seed": [round(seed[0], 4), round(seed[1], 4)],
                    "brd_open": borders[index],
                    "neighbours": neighbours[cell_id],
                    "color": [0.42, 0.82, 0.95, 0.0],
                })
        except (ValueError, IndexError) as error:
            skipped.append(f"{province_id}: {error}")

    payload = {
        "world_px": float(source.get("world_px", core.WORLD_PX)),
        "cells": output_cells,
        "provenance": {
            "method": "layer4_mask_multi_source_dijkstra",
            "source": "assets/provinces_iberia.json",
            "province_count": len(source.get("cells", [])),
            "cells_per_province": SEED_COUNT,
            "grid_step_px": GRID_STEP,
            "noise_scale_px": noise_scale,
            "noise_strength": noise_strength,
        },
    }
    report = {
        "ok": not skipped,
        "source_provinces": len(source.get("cells", [])),
        "generated_cells": len(output_cells),
        "skipped": skipped,
    }
    return payload, report


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--noise-scale", type=float, default=3.2)
    parser.add_argument("--noise-strength", type=float, default=0.85)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload, report = build(max(0.5, args.noise_scale), max(0.0, args.noise_strength))
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    write_json(output_path, payload)
    write_json(REPORT, report)
    print(f"wrote {output_path.relative_to(ROOT)}: {len(payload['cells'])} cells")
    if report["skipped"]:
        print(f"skipped: {len(report['skipped'])}")


if __name__ == "__main__":
    main()
