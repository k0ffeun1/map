"""Build the real global Admin-2 overlay from geoBoundaries CGAZ.

Input: scripts/tools/_work/geoBoundariesCGAZ_ADM2/ (the extracted official
       geoBoundaries CGAZ ADM2 archive).
Output: assets/admin2_geoboundaries.json, rendered by TileMapViewer as a
        translucent overlay over the existing Natural Earth Admin-1 layer.

CGAZ is geoBoundaries' world composite.  It is deliberately pre-simplified
for global visualisation; source, vintage and licence are retained per cell.
https://www.geoboundaries.org/api.html
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box, shape


ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT / "scripts" / "tools" / "_work" / "geoBoundariesCGAZ_ADM2"
OUT = ROOT / "assets" / "admin2_geoboundaries.json"
WORLD_PX = 8192.0
LAT_NORTH = 76.0
LAT_SOUTH = -58.0
# CGAZ itself is simplified.  This extra light pass keeps the game layer
# responsive without changing its administrative topology.
SIMPLIFY_TOLERANCE_DEG = 0.003
MIN_PIECE_AREA_KM2 = 1.0
EARTH_RADIUS_KM = 6371.0088


def project(lon: float, lat: float) -> tuple[float, float]:
	lat = max(-85.05112878, min(85.05112878, lat))
	x = (lon + 180.0) / 360.0 * WORLD_PX
	lat_rad = math.radians(lat)
	y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
	return x, y


def explode(geom):
	if geom.is_empty:
		return []
	if isinstance(geom, Polygon):
		return [geom]
	if isinstance(geom, (MultiPolygon, GeometryCollection)):
		out = []
		for child in geom.geoms:
			out.extend(explode(child))
		return out
	return []


def ring_area_km2(ring) -> float:
	points = list(ring)
	if len(points) < 3:
		return 0.0
	lat0 = math.radians(sum(lat for _lon, lat in points) / len(points))
	flat = [
		(math.radians(lon) * math.cos(lat0) * EARTH_RADIUS_KM,
		 math.radians(lat) * EARTH_RADIUS_KM)
		for lon, lat in points
	]
	return abs(sum(
		flat[i][0] * flat[(i + 1) % len(flat)][1] - flat[(i + 1) % len(flat)][0] * flat[i][1]
		for i in range(len(flat))
	)) * 0.5


def slug(value: str) -> str:
	chars = []
	for char in value.lower().strip():
		chars.append(char if char.isalnum() else "_")
	return "".join(chars).strip("_") or "unnamed"


def source_dataset() -> Path:
	# The current CGAZ ADM2 archive ships as a Shapefile.  GeoJSON is accepted
	# too, so the builder remains usable if geoBoundaries change that packaging.
	for suffix in ("*.shp", "*.geojson"):
		files = sorted(SRC_DIR.rglob(suffix))
		if files:
			return files[0]
	raise FileNotFoundError(f"No CGAZ dataset found under {SRC_DIR}. Extract the ADM2 archive first.")


def iter_features(source: Path):
	if source.suffix.lower() == ".geojson":
		with source.open(encoding="utf-8") as handle:
			yield from json.load(handle)["features"]
		return
	import shapefile
	# CGAZ's DBF includes legacy Latin-1 names (for example Albanian ë), while
	# its packaging does not include a .cpg sidecar declaring that encoding.
	reader = shapefile.Reader(str(source), encoding="latin1")
	for item in reader.iterShapeRecords():
		yield {"properties": item.record.as_dict(), "geometry": item.shape.__geo_interface__}


def feature_properties(properties: dict) -> tuple[str, str, str, str]:
	iso = str(properties.get("shapeISO") or properties.get("boundaryISO") or properties.get("ISO") or properties.get("shapeGroup") or "UNK")
	name = str(properties.get("shapeName") or properties.get("boundaryName") or properties.get("NAME_2") or "Unnamed Admin-2")
	admin1 = str(properties.get("ADM1_NAME") or properties.get("shapeParent") or "")
	boundary_id = str(properties.get("shapeID") or properties.get("boundaryID") or f"{iso}-{name}")
	return iso, name, admin1, boundary_id


def main() -> None:
	source = source_dataset()
	print(f"Reading {source}")

	crop = box(-180.0, LAT_SOUTH, 180.0, LAT_NORTH)
	cells = []
	id_counts: dict[str, int] = {}
	for index, feature in enumerate(iter_features(source), start=1):
		geom = shape(feature["geometry"])
		if not geom.is_valid:
			geom = geom.buffer(0)
		if geom.is_empty:
			continue
		geom = geom.intersection(crop).simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
		iso, name, admin1, boundary_id = feature_properties(feature.get("properties", {}))
		base_id = slug(f"{iso}__{boundary_id}")
		for piece in explode(geom):
			ext_ll = list(piece.exterior.coords)
			if len(ext_ll) < 3 or ring_area_km2(ext_ll) < MIN_PIECE_AREA_KM2:
				continue
			ext = [[round(x, 2), round(y, 2)] for x, y in (project(lon, lat) for lon, lat in ext_ll)]
			holes = []
			for interior in piece.interiors:
				hole = list(interior.coords)
				if len(hole) >= 3:
					holes.append([[round(x, 2), round(y, 2)] for x, y in (project(lon, lat) for lon, lat in hole)])
			count = id_counts.get(base_id, 0) + 1
			id_counts[base_id] = count
			cell_id = base_id if count == 1 else f"{base_id}_{count}"
			xs = [point[0] for point in ext]
			ys = [point[1] for point in ext]
			cells.append({
				"id": cell_id,
				"name": name,
				"admin1": admin1,
				"iso3": iso,
				"source": "geoBoundaries CGAZ ADM2",
				"rings": [ext, *holes],
				"bbox": [min(xs), min(ys), max(xs), max(ys)],
			})
		if index % 5000 == 0:
			print(f"Processed {index} source features; emitted {len(cells)} pieces")

	OUT.parent.mkdir(parents=True, exist_ok=True)
	with OUT.open("w", encoding="utf-8") as handle:
		json.dump({
			"world_px": WORLD_PX,
			"source": "geoBoundaries CGAZ ADM2",
			"license_note": "See geoBoundaries source metadata and attribution requirements.",
			"cells": cells,
		}, handle, ensure_ascii=False, separators=(",", ":"))
	print(f"Wrote {len(cells)} Admin-2 pieces to {OUT}")


if __name__ == "__main__":
	main()
