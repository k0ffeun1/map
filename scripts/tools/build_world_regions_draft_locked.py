"""Small lock/fix wrapper around build_world_regions_draft.py.

The base generator intentionally stays readable. This wrapper fixes named
world exceptions by deriving their IDs through the exact same slugify()
function as the 273-region seed catalog, preventing duplicate IDs caused by
hand-written transliteration variants.
"""
from __future__ import annotations

import runpy
from pathlib import Path

CORE_PATH = Path(__file__).with_name("build_world_regions_draft.py")
CORE = runpy.run_path(str(CORE_PATH))

# Keep only target names here. IDs are always derived by core.slugify().
TARGET_BY_PROVINCE_NAME = {
    "Greenland": "Арктическая Канада",
    "Iceland": "Северная Скандинавия",
    "Faroe Islands": "Северная Скандинавия",
    "Falkland Islands": "Патагония",
}

slugify = CORE["slugify"]
core_globals = CORE["main"].__globals__
core_globals["NAME_FORCED_REGION"] = {
    province_name: (f"region:world:{slugify(region_name)}", region_name)
    for province_name, region_name in TARGET_BY_PROVINCE_NAME.items()
}

if __name__ == "__main__":
    CORE["main"]()
