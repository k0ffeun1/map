#!/usr/bin/env python3
"""Refresh visual open borders without altering existing cell geometry.

The source asset may contain hand-tuned cells. This tool replaces only
``brd_open``: dividers meet provincial borders on land and retain a 2 km
setback only where that border meets the ocean.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from shapely.geometry import LineString, MultiLineString, Polygon, box
from shapely.ops import unary_union

import build_cells_test as cell_tools


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ASSET = ROOT / "assets/land_cells_universal_v2_iberia_all.json"
GEOMETRY_ASSET = ROOT / "assets/map_geometry/provinces.json"
OCEAN_POLYGONS = cell_tools.load_world_ocean()


def polygon_from_rings(rings: list) -> Polygon:
    polygon = Polygon(rings[0], rings[1:])
    return polygon if polygon.is_valid else polygon.buffer(0)


def coast_safe_mask(province: Polygon) -> object:
    margin_px = cell_tools._ocean_margin_px(province)
    clip_box = box(*province.bounds).buffer(margin_px + 3.0)
    ocean_parts = []
    for ocean in OCEAN_POLYGONS:
        if ocean.intersects(clip_box):
            part = ocean.intersection(clip_box)
            if not part.is_empty:
                ocean_parts.append(part)
    if not ocean_parts:
        return province
    return province.difference(unary_union(ocean_parts).buffer(margin_px, quad_segs=8))


def clip_chains_to_mask(chains: list, mask: object) -> list:
    output = []
    for chain in chains:
        if len(chain) < 2:
            continue
        clipped = LineString(chain).intersection(mask)
        if clipped.is_empty:
            continue
        if isinstance(clipped, LineString):
            parts = [clipped]
        elif isinstance(clipped, MultiLineString):
            parts = list(clipped.geoms)
        else:
            parts = [item for item in getattr(clipped, "geoms", []) if isinstance(item, LineString)]
        for part in parts:
            coords = [[round(x, 2), round(y, 2)] for x, y in part.coords]
            if len(coords) >= 2:
                output.append(coords)
    return output


def refresh(asset_path: Path) -> None:
    payload = json.loads(asset_path.read_text(encoding="utf-8"))
    geometry_doc = json.loads(GEOMETRY_ASSET.read_text(encoding="utf-8"))
    provinces = {
        item["id"]: polygon_from_rings(item["rings"])
        for item in geometry_doc["provinces"]
    }
    masks: dict[str, object] = {}
    refreshed = 0
    for cell in payload.get("cells", []):
        province_id = cell.get("province_id", "")
        province = provinces.get(province_id)
        rings = cell.get("rings", [])
        if province is None or not rings or len(rings[0]) < 3:
            continue
        internal, _boundary = cell_tools._split_border_chains(rings[0], province.boundary)
        if province_id not in masks:
            masks[province_id] = coast_safe_mask(province)
        cell["brd_open"] = clip_chains_to_mask(internal, masks[province_id])
        refreshed += 1
    asset_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"refreshed brd_open for {refreshed} cells in {asset_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", type=Path, default=DEFAULT_ASSET)
    refresh(parser.parse_args().asset)


if __name__ == "__main__":
    main()
