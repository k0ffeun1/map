"""Build a compact review index for the world province layer (old hotkey 8).

This does NOT change gameplay data. It joins the stable province passports with
assets/provinces.json and writes one line per province with a geographic centre.
The index is intentionally text/line-oriented so world-region assignments can be
reviewed in chunks before the final dissolve into regions.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

WORLD_PX = 8192.0
GEOMETRY = Path("assets/provinces.json")
PASSPORTS = Path("assets/game_data/provinces.json")
OUT = Path("reports/world_province_index.txt")


def world_to_lonlat(x: float, y: float) -> tuple[float, float]:
    lon = (x / WORLD_PX) * 360.0 - 180.0
    merc_y = math.pi * (1.0 - 2.0 * y / WORLD_PX)
    lat = math.degrees(math.atan(math.sinh(merc_y)))
    return lon, lat


def main() -> None:
    geom_data = json.loads(GEOMETRY.read_text(encoding="utf-8"))
    passport_data = json.loads(PASSPORTS.read_text(encoding="utf-8"))

    geom_by_id = {}
    geom_by_name: dict[str, list[dict]] = {}
    for cell in geom_data.get("cells", []):
        cid = str(cell.get("id", ""))
        if cid:
            geom_by_id[cid] = cell
        geom_by_name.setdefault(str(cell.get("name", "")), []).append(cell)

    rows = []
    missing = []
    country_counts: dict[str, int] = {}

    for province in passport_data.get("provinces", []):
        legacy_id = str(province.get("legacy_id", ""))
        name = str(province.get("name", ""))
        country = legacy_id.split("__", 1)[0] if "__" in legacy_id else "unknown"
        cell = geom_by_id.get(legacy_id)
        match = "id"
        if cell is None:
            same_name = geom_by_name.get(name, [])
            if len(same_name) == 1:
                cell = same_name[0]
                match = "unique_name"
        if cell is None:
            missing.append((province.get("id", ""), legacy_id, name))
            continue

        bbox = cell.get("bbox", [])
        if not isinstance(bbox, list) or len(bbox) != 4:
            missing.append((province.get("id", ""), legacy_id, name))
            continue
        x = (float(bbox[0]) + float(bbox[2])) * 0.5
        y = (float(bbox[1]) + float(bbox[3])) * 0.5
        lon, lat = world_to_lonlat(x, y)
        country_counts[country] = country_counts.get(country, 0) + 1
        rows.append((country, int(province.get("numeric_id", -1)), str(province.get("id", "")), legacy_id, name, lon, lat, match))

    rows.sort(key=lambda r: (r[0], r[1], r[4]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# world province index v1 | source=assets/provinces.json | old layer 8\n")
        f.write(f"# passports={len(passport_data.get('provinces', []))} matched={len(rows)} missing={len(missing)} countries={len(country_counts)}\n")
        f.write("# country_slug|numeric_id|province_id|legacy_id|name|lon|lat|match\n")
        for country, numeric_id, pid, legacy_id, name, lon, lat, match in rows:
            safe_name = name.replace("|", "/").replace("\n", " ")
            f.write(f"{country}|{numeric_id}|{pid}|{legacy_id}|{safe_name}|{lon:.5f}|{lat:.5f}|{match}\n")
        if missing:
            f.write("# MISSING\n")
            for pid, legacy_id, name in missing:
                f.write(f"# missing|{pid}|{legacy_id}|{name}\n")

    print(f"WORLD_PROVINCE_INDEX passports={len(passport_data.get('provinces', []))} matched={len(rows)} missing={len(missing)} countries={len(country_counts)}")
    print("COUNTRIES=" + ",".join(sorted(country_counts)))
    if missing:
        raise SystemExit("province geometry join is incomplete; see report")


if __name__ == "__main__":
    main()
