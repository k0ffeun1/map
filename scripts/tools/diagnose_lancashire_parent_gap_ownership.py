#!/usr/bin/env python3
"""Classify the two Lancashire cell-boundary gap arcs against macro neighbours.

Consumes the v4 cell-boundary diagnostic.  Each short ring arc is already known
to lie on the Lancashire/Manchester parent boundary; this script determines
whether that parent arc is shared with another gameplay province or belongs to
the outer union of the Britain/North-Atlantic land mask.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
MACRO_PATH = ROOT / "assets" / "game_data" / "britain_north_atlantic_gameplay_provinces.json"
DIAGNOSTIC_PATH = ROOT / "reports" / "britain_lancashire_cell_boundary_diagnostic.json"
OUT_PATH = ROOT / "reports" / "britain_lancashire_parent_gap_ownership.json"
PARENT_ID = "gb_england_lancashire_manchester"
PAIR_SUFFIX = (":cell:01", ":cell:02")
TOL = 1.0e-5
EPS = 1.0e-9


def polygon_parts(geometry: Any) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [item for item in geometry.geoms if isinstance(item, Polygon) and not item.is_empty]
    return []


def parts_geometry(parts_payload: Any) -> Any:
    parts = []
    for part in parts_payload if isinstance(parts_payload, list) else []:
        rings = part.get("rings", []) if isinstance(part, dict) else []
        if not rings or len(rings[0]) < 3:
            continue
        geometry: Any = Polygon(rings[0], rings[1:])
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        parts.extend(polygon_parts(geometry))
    result = unary_union(parts) if parts else Polygon()
    return result if result.is_valid else result.buffer(0)


def covered_length(line: LineString, boundary: Any) -> float:
    if line.is_empty or boundary is None or boundary.is_empty:
        return 0.0
    return float(line.intersection(boundary.buffer(TOL)).length)


def classify_arc(line: LineString, macro_geometries: dict[str, Any], land_boundary: Any) -> dict[str, Any]:
    length = float(line.length)
    neighbours = []
    for province_id, geometry in sorted(macro_geometries.items()):
        if province_id == PARENT_ID:
            continue
        hit = covered_length(line, geometry.boundary)
        share = hit / max(length, EPS)
        if share >= 0.02:
            neighbours.append({
                "province_id": province_id,
                "length_world_px": round(hit, 9),
                "share": round(min(1.0, share), 6),
            })
    neighbours.sort(key=lambda item: item["share"], reverse=True)

    outer_length = covered_length(line, land_boundary)
    outer_share = min(1.0, outer_length / max(length, EPS))
    neighbour_share = max((float(item["share"]) for item in neighbours), default=0.0)
    if neighbour_share >= 0.95 and outer_share < 0.05:
        classification = "shared_gameplay_province_boundary"
    elif outer_share >= 0.95 and neighbour_share < 0.05:
        classification = "outer_land_mask_boundary"
    elif neighbour_share >= 0.80:
        classification = "mostly_shared_gameplay_province_boundary"
    elif outer_share >= 0.80:
        classification = "mostly_outer_land_mask_boundary"
    else:
        classification = "mixed_or_unresolved"

    return {
        "length_world_px": round(length, 9),
        "outer_land_boundary_length_world_px": round(outer_length, 9),
        "outer_land_boundary_share": round(outer_share, 6),
        "macro_neighbours": neighbours,
        "classification": classification,
    }


def main() -> None:
    diagnostic = json.loads(DIAGNOSTIC_PATH.read_text(encoding="utf-8"))
    if diagnostic.get("format") != "britain_lancashire_cell_boundary_diagnostic/v4":
        raise RuntimeError("v4 Lancashire cell diagnostic is required")

    macro = json.loads(MACRO_PATH.read_text(encoding="utf-8"))
    macro_geometries = {
        str(item["id"]): parts_geometry(item.get("parts", []))
        for item in macro.get("provinces", [])
        if isinstance(item, dict) and item.get("id")
    }
    if PARENT_ID not in macro_geometries:
        raise RuntimeError("Lancashire/Manchester macro province missing")
    land = unary_union(list(macro_geometries.values()))
    if not land.is_valid:
        land = land.buffer(0)
    land_boundary = land.boundary

    target_pair = next(
        (
            pair for pair in diagnostic.get("pairs", [])
            if str(pair.get("left", "")).endswith(PAIR_SUFFIX[0])
            and str(pair.get("right", "")).endswith(PAIR_SUFFIX[1])
        ),
        None,
    )
    if target_pair is None:
        raise RuntimeError("cell:01/cell:02 pair missing from diagnostic")

    gaps = []
    for gap_index, gap in enumerate(target_pair.get("component_gaps", [])):
        row = {
            "gap_index": gap_index,
            "gap_world_px": gap.get("gap_world_px"),
            "a_endpoint": gap.get("a_endpoint"),
            "b_endpoint": gap.get("b_endpoint"),
            "cell_arcs": [],
        }
        for side_key in ("left_cell_ring_arcs", "right_cell_ring_arcs"):
            arcs = gap.get(side_key)
            short = arcs.get("shorter_arc") if isinstance(arcs, dict) else None
            coords = short.get("coordinates", []) if isinstance(short, dict) else []
            if len(coords) < 2:
                continue
            line = LineString([(float(point[0]), float(point[1])) for point in coords])
            row["cell_arcs"].append({
                "side": side_key,
                "coordinates": coords,
                **classify_arc(line, macro_geometries, land_boundary),
            })
        gaps.append(row)

    payload = {
        "format": "britain_lancashire_parent_gap_ownership/v1",
        "parent_id": PARENT_ID,
        "gap_count": len(gaps),
        "gaps": gaps,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("LANCASHIRE_PARENT_GAP_OWNERSHIP=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
