"""Build a small standalone Netherlands provinces layer from assets/provinces.json.

The source Natural Earth-derived layer currently has generated fallback ids in
Godot. This tool bakes those same long ids into JSON explicitly, so clicks on
the standalone layer show/search by ids such as province_0400.
"""

import json
from pathlib import Path


SRC = Path("assets/provinces.json")
OUT = Path("assets/provinces_netherlands.json")

FRISIAN_ISLAND_SOURCE_INDEXES = [
    2885,  # west Friesland island piece
    2886,  # middle Friesland island piece
    2887,  # east Friesland island piece
    2888,  # far east Friesland island piece
]

COLOGNE_HAMBURG_SOURCE_INDEXES = [
    274,  # Schleswig-Holstein
    401,  # Niedersachsen
    402,  # Niedersachsen island piece
    403,  # Niedersachsen island piece
    404,  # Niedersachsen island piece
    405,  # Niedersachsen island piece
    406,  # Niedersachsen island piece
    407,  # Niedersachsen island piece
    408,  # Niedersachsen island piece
    411,  # Nordrhein-Westfalen
]

MERGED_GROUPS_BY_SOURCE_INDEX = {
    675: {
        "id": "province_0677",
        "name": "Noord-Brabant",
        "color_key": "province_0677",
    },
    677: {
        "id": "province_0677",
        "name": "Noord-Brabant",
        "color_key": "province_0677",
    },
    2880: {
        "id": "province_2881",
        "name": "Zuid-Holland",
        "color_key": "province_2881",
    },
    2881: {
        "id": "province_2881",
        "name": "Zuid-Holland",
        "color_key": "province_2881",
    },
    2883: {
        "id": "province_2883_2885_2886_2887_2888",
        "name": "Noord-Holland + Friesland islands",
        "color_key": "province_2883_2885_2886_2887_2888",
    },
    2885: {
        "id": "province_2883_2885_2886_2887_2888",
        "name": "Noord-Holland + Friesland islands",
        "color_key": "province_2883_2885_2886_2887_2888",
    },
    2886: {
        "id": "province_2883_2885_2886_2887_2888",
        "name": "Noord-Holland + Friesland islands",
        "color_key": "province_2883_2885_2886_2887_2888",
    },
    2887: {
        "id": "province_2883_2885_2886_2887_2888",
        "name": "Noord-Holland + Friesland islands",
        "color_key": "province_2883_2885_2886_2887_2888",
    },
    2888: {
        "id": "province_2883_2885_2886_2887_2888",
        "name": "Noord-Holland + Friesland islands",
        "color_key": "province_2883_2885_2886_2887_2888",
    },
    402: {
        "id": "province_0402_0403_0404_0405_0406_0407_0408",
        "name": "Niedersachsen islands",
        "color_key": "province_0402_0403_0404_0405_0406_0407_0408",
    },
    403: {
        "id": "province_0402_0403_0404_0405_0406_0407_0408",
        "name": "Niedersachsen islands",
        "color_key": "province_0402_0403_0404_0405_0406_0407_0408",
    },
    404: {
        "id": "province_0402_0403_0404_0405_0406_0407_0408",
        "name": "Niedersachsen islands",
        "color_key": "province_0402_0403_0404_0405_0406_0407_0408",
    },
    405: {
        "id": "province_0402_0403_0404_0405_0406_0407_0408",
        "name": "Niedersachsen islands",
        "color_key": "province_0402_0403_0404_0405_0406_0407_0408",
    },
    406: {
        "id": "province_0402_0403_0404_0405_0406_0407_0408",
        "name": "Niedersachsen islands",
        "color_key": "province_0402_0403_0404_0405_0406_0407_0408",
    },
    407: {
        "id": "province_0402_0403_0404_0405_0406_0407_0408",
        "name": "Niedersachsen islands",
        "color_key": "province_0402_0403_0404_0405_0406_0407_0408",
    },
    408: {
        "id": "province_0402_0403_0404_0405_0406_0407_0408",
        "name": "Niedersachsen islands",
        "color_key": "province_0402_0403_0404_0405_0406_0407_0408",
    },
}

# Source cell indexes in assets/provinces.json. 2884 is intentionally excluded:
# the user removed that Friesland piece from both layer 8 and this layer.
NETHERLANDS_SOURCE_INDEXES = [
    *COLOGNE_HAMBURG_SOURCE_INDEXES,
    400,   # Groningen
    409,   # Drenthe
    410,   # Overijssel
    412,   # Gelderland
    413,   # Limburg (NL)
    675,   # Zeeland
    677,   # Noord-Brabant
    2880,  # Zuid-Holland island piece
    2881,  # Zuid-Holland
    2882,  # Noord-Holland
    2883,  # Noord-Holland island piece
    *FRISIAN_ISLAND_SOURCE_INDEXES,
    3498,  # Flevoland
]


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    cells = data.get("cells", [])
    out_cells = []

    for source_index in NETHERLANDS_SOURCE_INDEXES:
        if source_index >= len(cells):
            raise IndexError(f"source index {source_index} is outside {SRC}")
        cell = dict(cells[source_index])
        merged_group = MERGED_GROUPS_BY_SOURCE_INDEX.get(source_index)
        if merged_group:
            cell["id"] = merged_group["id"]
            cell["name"] = merged_group["name"]
            cell["color_key"] = merged_group["color_key"]
        else:
            cell["id"] = f"province_{source_index:04d}"
        cell["source_index"] = source_index
        cell.pop("brd", None)
        out_cells.append(cell)

    OUT.write_text(
        json.dumps(
            {
                "world_px": data.get("world_px", 8192),
                "source": str(SRC).replace("\\", "/"),
                "cells": out_cells,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"wrote {OUT} ({len(out_cells)} cells)")


if __name__ == "__main__":
    main()
