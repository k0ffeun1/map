#!/usr/bin/env python3
"""Stable Stage 6 runner with stress-case selection policy.

Kept separate while the universal generator is under CI tuning.  It patches
only which automatic control provinces are selected; generation, 2 km coast,
Q/K/U/Y geometry and validation remain untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import build_stage6_universal_subdivisions as core


def _is_inland(sources: core.Sources, polygon) -> bool:
    distance = core.COAST_RULE_KM / max(core.km_per_world_px(polygon.representative_point().y), 1.0e-9)
    return not sources.coast_neighbours(polygon, distance)


def select_controls_fixed(sources: core.Sources) -> dict[str, str]:
    lacoruna = "province:2848"

    london = core.find_named(sources, ["greater london", "london"], ("united_kingdom__", "england__"))
    if london is None:
        london = core.nearest_named_fallback(sources, -0.12, 51.51, ("united_kingdom__", "england__"))

    sicily = core.find_named(sources, ["sicily", "sicilia"], ("italy__",))
    if sicily is None:
        sicily = core.nearest_named_fallback(sources, 14.0, 37.6, ("italy__",))

    brittany = core.find_named(sources, ["bretagne", "brittany"], ("france__",))
    if brittany is None:
        brittany = core.nearest_named_fallback(sources, -3.0, 48.2, ("france__",))

    used = {lacoruna, london, sicily, brittany}
    europe = []
    for pid, geometry in sources.geometry.items():
        if pid in used:
            continue
        parts = core.polygon_parts(geometry)
        if len(parts) != 1:
            continue
        polygon = parts[0]
        center = polygon.representative_point()
        if not (3500.0 <= center.x <= 5200.0 and 1550.0 <= center.y <= 3350.0):
            continue
        area = core.area_km2(polygon)
        if area < 45.0:
            continue
        europe.append((pid, polygon, area, core.aspect_ratio(polygon)))

    long_narrow_candidates = [item for item in europe if 500.0 <= item[2] <= 30000.0]
    long_narrow = max(long_narrow_candidates or europe, key=lambda item: (item[3], item[2]))[0]
    used.add(long_narrow)

    inland_candidates = [
        item for item in europe
        if item[0] not in used and item[2] >= 5000.0 and _is_inland(sources, item[1])
    ]
    if not inland_candidates:
        inland_candidates = [item for item in europe if item[0] not in used and _is_inland(sources, item[1])]
    large_inland = max(inland_candidates, key=lambda item: item[2])[0]
    used.add(large_inland)

    # This control is explicitly about lack of space.  Do not accidentally
    # turn it into a coast/archipelago test: require an inland polygon first.
    small_candidates = [
        item for item in europe
        if item[0] not in used and 45.0 <= item[2] <= 1500.0 and _is_inland(sources, item[1])
    ]
    if not small_candidates:
        small_candidates = [
            item for item in europe
            if item[0] not in used and _is_inland(sources, item[1])
        ]
    if not small_candidates:
        raise RuntimeError("could not select a small inland Stage 6 stress province")
    small = min(small_candidates, key=lambda item: item[2])[0]

    return {
        "ordinary_coastal": lacoruna,
        "dense_complex_london": london,
        "island_sicily": sicily,
        "complex_coast_brittany": brittany,
        "long_narrow_stress": long_narrow,
        "large_inland_stress": large_inland,
        "small_space_stress": small,
    }


core.select_controls = select_controls_fixed

if __name__ == "__main__":
    core.main()
