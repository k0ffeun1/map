#!/usr/bin/env python3
"""Export an Admin-1 outline PNG for Province Map Builder.

Province Map Builder uses opaque pixels as a landmass.  This exporter keeps
the original game geometry as source data and creates a compact editable
canvas for a single Admin-1; it never replaces the world-map geometry.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
GEOMETRY = ROOT / "assets" / "map_geometry" / "provinces.json"
IDENTITY = ROOT / "assets" / "game_data" / "provinces.json"
OUT_DIR = ROOT / "assets" / "province_map_builder"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--province-id", default="province:2848")
    parser.add_argument("--size", type=int, default=1024)
    args = parser.parse_args()
    identities = {item["id"]: item for item in json.loads(IDENTITY.read_text(encoding="utf-8"))["provinces"]}
    province = identities[args.province_id]
    geometries = {item["legacy_id"]: item for item in json.loads(GEOMETRY.read_text(encoding="utf-8"))["provinces"]}
    rings = geometries[province["legacy_id"]]["rings"]
    all_points = [point for ring in rings for point in ring]
    x0, y0 = (min(point[index] for point in all_points) for index in (0, 1))
    x1, y1 = (max(point[index] for point in all_points) for index in (0, 1))
    padding = 32
    usable = max(1, args.size - padding * 2)
    scale = usable / max(x1 - x0, y1 - y0)
    canvas_w = int(round((x1 - x0) * scale)) + padding * 2
    canvas_h = int(round((y1 - y0) * scale)) + padding * 2

    def transform(point: list[float]) -> tuple[int, int]:
        return round((point[0] - x0) * scale) + padding, round((point[1] - y0) * scale) + padding

    image = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.polygon([transform(point) for point in rings[0]], fill=(255, 255, 255, 255))
    for hole in rings[1:]:
        draw.polygon([transform(point) for point in hole], fill=(0, 0, 0, 0))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{args.province_id.replace(':', '_')}_outline"
    image.save(OUT_DIR / f"{stem}.png")
    (OUT_DIR / f"{stem}.json").write_text(json.dumps({
        "province_id": args.province_id,
        "name": province.get("name", args.province_id),
        "source_bounds_world_px": [x0, y0, x1, y1],
        "canvas_px": [canvas_w, canvas_h],
        "padding_px": padding,
        "world_to_canvas_scale": scale,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_DIR / f'{stem}.png'}")


if __name__ == "__main__":
    main()
