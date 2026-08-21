"""Robust topology-lock wrapper for La Coruna Stage 5.

The Stage 4 visual chains are already clipped to the authoritative layer-4
2 km gameplay coastline. GEOS, however, does not always consider a line whose
endpoint merely touches a curved boundary to be a cutter in a planar graph.

For polygonization only, this wrapper:
1. projects coastal endpoints to the exact gameplay boundary;
2. extends each such cutter 0.02 world-px beyond that boundary;
3. polygons the noded graph;
4. clips every resulting face back to the authoritative gameplay land.

The extension is therefore never present in exported game geometry. It only
makes the topological cut unambiguous. All other Stage 5 logic/validation is
kept in build_lacoruna_final_subdivision.py.
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
        # Degenerate last segment: exact weld is still better than the old
        # near-touch. A valid Stage 4 chain normally never reaches this branch.
        points[index] = anchor
        return True

    points[index] = (
        anchor[0] + dx / length * CUTTER_EXTENSION_WORLD_PX,
        anchor[1] + dy / length * CUTTER_EXTENSION_WORLD_PX,
    )
    return True


def build_faces_locked(land, components: list[dict]):
    """Polygonize Stage 4 lines as guaranteed cutters of the 2 km land."""
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

    # unary_union performs the actual planar noding: coastline/cutter crossing
    # points and the exact shared internal junction become common graph nodes.
    network = unary_union([land.boundary, *cutters])
    result = []
    for face in polygonize(network):
        clipped = face.intersection(land)
        for part in CORE["polygons"](clipped):
            if part.area <= MIN_FACE_AREA:
                continue
            if land.covers(part.representative_point()):
                result.append(part)

    if not result:
        raise RuntimeError("Stage 5 topology lock polygonized zero gameplay faces")

    # Expose diagnostics to the core build result without changing exported
    # coordinates. build() reads build_faces through its runpy globals.
    CORE["_stage5_locked_welded_endpoint_count"] = welded_endpoint_count
    CORE["_stage5_locked_face_count"] = len(result)
    return result


def build() -> dict:
    # Functions loaded by runpy resolve globals through the returned dict, so
    # replacing build_faces here safely upgrades the core pipeline while
    # retaining its strict coverage/seed/capital/adjacency validation.
    CORE["build_faces"] = build_faces_locked
    result = CORE["build"]()
    result.setdefault("generation", {})["topology_lock_method"] = "exact_coast_weld_plus_external_cutter"
    result["generation"]["coast_contact_epsilon_world_px"] = COAST_CONTACT_EPSILON
    result["generation"]["cutter_extension_world_px"] = CUTTER_EXTENSION_WORLD_PX
    result["generation"]["welded_coast_endpoint_count"] = int(
        CORE.get("_stage5_locked_welded_endpoint_count", 0)
    )
    result["generation"]["locked_polygonized_face_count"] = int(
        CORE.get("_stage5_locked_face_count", 0)
    )
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
