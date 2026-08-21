#!/usr/bin/env python3
"""Safe entry point for rebuilding the real Natural Earth Admin-1 layer.

IMPORTANT PROJECT CONTRACT
--------------------------
Real Admin-1 outer boundaries are source geometry and must not be changed just
because an administrative unit is small, locally unusual, or has a fine-looking
`type_en` label.  The legacy `build_provinces.py` contains an old heuristic
`_merge_small_pieces()` stage that can absorb genuine cantons/municipalities/
small regions into arbitrary neighbours while preserving the neighbour name.
That behavior produced semantically corrupted identities such as a very large
"Appenzell Innerrhoden" / "Jekabpils" geometry.

This entry point deliberately disables ONLY that heuristic adjacency merge.
Explicit named source-level corrections in `MERGE_GROUPS` (currently Greater
London) still run inside `build_provinces.main()`.  Existing island filtering,
projection, simplification and overlap cleanup are otherwise unchanged so this
can be used as a minimal migration step rather than a full map-pipeline rewrite.

The Natural Earth source GeoJSON is intentionally offline and is not currently
stored in the repository, so running this script requires the same local source
file as the legacy builder:
  scripts/tools/_work/ne_10m_admin_1_states_provinces.geojson
"""
from __future__ import annotations

import build_provinces as legacy


def _preserve_real_admin1_boundaries(pieces: list) -> list:
    """Do not merge source Admin-1 polygons by size/type/neighbour heuristics."""
    print(
        "  SAFE ADMIN1 MODE: heuristic _merge_small_pieces disabled; "
        f"preserving {len(pieces)} source polygon pieces"
    )
    return pieces


def main() -> None:
    legacy._merge_small_pieces = _preserve_real_admin1_boundaries
    legacy.main()


if __name__ == "__main__":
    main()
