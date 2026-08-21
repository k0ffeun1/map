"""Robust topology-lock wrapper for La Coruna Stage 5.

Stage 4 visual chains are clipped to the authoritative layer-4 2 km gameplay
coastline. For strict planar polygonization a coastal endpoint is welded to the
exact boundary and the cutter is extended only 0.02 world-px beyond it. Every
face is then clipped back to gameplay land, so the extension never appears in
exported game geometry.
"""
from __future__ import annotations

import argparse
import json
import math
import runpy
from pathlib import Path

from shapely.geometry import LineString, Point
from shapely.ops import nearest_points, polygonize, unary_union

ROOT = Path(__file__).resolve().parents[2]
CORE_PATH = Path(__file__).with_name("build_lacoruna_final_subdivision.py")
CORE = runpy.run_path(str(CORE_PATH))

COAST_CONTACT_EPSILON = 0.001
CUTTER_EXTENSION_WORLD_PX = 0.02
MIN_FACE_AREA = 1.0e-7

_LAST_WELDED_ENDPOINT_COUNT = 0
_LAST_FACE_COUNT = 0


def _extend_coastal_endpoint(points: list[tuple[float, float]], index: int, neighbor_index: int, land) -> bool:
    point = Point(points[index])
    if point.distance(land.boundary) > COAST_CONTACT_EPSILON:
        return False

    boundary_point = nearest_points(point, land.boundary)[1]
    anchor = (float(boundary_point.x), float(boundary_point.y))
    neighbor = points[neighbor_index]
    dx = anchor[0] - neighbor[0]
    dy = anchor[1] - neighbor[1]
    length = math.hypot(dx, dy)
    if length <= 1.0e-12:
        points[index] = anchor
        return True

    points[index] = (
        anchor[0] + dx / length * CUTTER_EXTENSION_WORLD_PX,
        anchor[1] + dy / length * CUTTER_EXTENSION_WORLD_PX,
    )
    return True


def build_faces_locked(land, components: list[dict]):
    """Turn Stage 4 shared lines into unambiguous planar cutters."""
    global _LAST_WELDED_ENDPOINT_COUNT, _LAST_FACE_COUNT
    cutters: list[LineString] = []
    welded_endpoint_count = 0

    for component in components:
        points = list(component["clean"])
        if len(points) < 2:
            continue
        if _extend_coastal_endpoint(points, 0, 1, land):
            welded_endpoint_count += 1
        if _extend_coastal_endpoint(points, -1, -2, land):
            welded_endpoint_count += 1
        cutters.append(LineString(points))

    if not cutters:
        raise RuntimeError("Stage 5 topology lock received no political cutters")

    network = unary_union([land.boundary, *cutters])
    result = []
    for face in polygonize(network):
        clipped = face.intersection(land)
        for part in CORE["polygons"](clipped):
            if part.area > MIN_FACE_AREA and land.covers(part.representative_point()):
                result.append(part)

    if not result:
        raise RuntimeError("Stage 5 topology lock polygonized zero gameplay faces")

    _LAST_WELDED_ENDPOINT_COUNT = welded_endpoint_count
    _LAST_FACE_COUNT = len(result)
    return result


def build() -> dict:
    # runpy returns a mapping, while function name lookup uses the function's
    # actual __globals__ dictionary. Patch that dictionary directly.
    core_globals = CORE["build"].__globals__
    core_globals["build_faces"] = build_faces_locked

    result = CORE["build"]()
    generation = result.setdefault("generation", {})
    generation["topology_lock_method"] = "exact_coast_weld_plus_external_cutter"
    generation["coast_contact_epsilon_world_px"] = COAST_CONTACT_EPSILON
    generation["cutter_extension_world_px"] = CUTTER_EXTENSION_WORLD_PX
    generation["welded_coast_endpoint_count"] = _LAST_WELDED_ENDPOINT_COUNT
    generation["locked_polygonized_face_count"] = _LAST_FACE_COUNT
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    result = build()
    out_path: Path = CORE["OUT_PATH"]
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"

    if args.check:
        if not out_path.exists() or out_path.read_text(encoding="utf-8") != encoded:
            raise SystemExit("Stage 5 locked asset missing or stale")
        print("Stage 5 locked check OK")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(encoded, encoding="utf-8")
    validation = result["validation"]
    generation = result["generation"]
    print(
        "Stage 5 locked built: "
        f"zones={validation['zone_count']}, "
        f"faces={generation['locked_polygonized_face_count']}, "
        f"welded_coast_endpoints={generation['welded_coast_endpoint_count']}, "
        f"missing={validation['coverage_missing_world_px2']}, "
        f"extra={validation['coverage_extra_world_px2']}, "
        f"overlap={validation['max_pair_overlap_world_px2']}, "
        "coast=2.0km"
    )
    print(out_path.relative_to(ROOT))


if __name__ == "__main__":
    main()
