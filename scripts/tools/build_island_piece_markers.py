"""Диагностический слой поверх слоя "8" (assets/provinces.json): точки на
КАЖДОМ отдельном куске провинции, у которой таких кусков >= 2 (реальные
острова/анклавы вроде Northwest Territories/Qaasuitsup Kommunia — см. сессию
2026-07-12: у них по 10+ отдельных записей с одним именем) — чекбокс
"Островные куски" в панели слоя 8 (TileMapViewer.gd,
IslandPieceMarkersLayer/IslandPieceMarkerNode). Группировка по ПОЛЮ "name" —
единственный способ связать разрозненные записи одной провинции, т.к.
отдельного "group_id" в provinces.json нет (см. build_provinces.py:
color_key группирует только явно перечисленные MERGE_GROUPS, не все
многокусочные провинции).

Точка маркера — representative_point() (shapely), гарантированно внутри
куска (см. build_small_provinces_markers.py — тот же приём и та же причина).
"""
import json

from shapely.geometry import Polygon

SRC = "assets/provinces.json"
OUT = "assets/island_piece_markers.json"


def main() -> None:
    cells = json.load(open(SRC, encoding="utf-8"))["cells"]

    by_name: dict = {}
    for idx, c in enumerate(cells):
        name = c.get("name", "")
        if not name:
            continue
        by_name.setdefault(name, []).append((idx, c))

    markers = []
    for name, entries in by_name.items():
        if len(entries) < 2:
            continue
        for idx, c in entries:
            rings = c.get("rings", [])
            if not rings or len(rings[0]) < 3:
                continue
            cell_id = str(c.get("id", "") or f"province_{idx:04d}")
            try:
                poly = Polygon(rings[0], rings[1:])
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if poly.is_empty:
                    continue
                rp = poly.representative_point()
            except Exception:
                continue
            markers.append({
                "id": cell_id,
                "name": name,
                "pos": [round(rp.x, 1), round(rp.y, 1)],
                "piece_count": len(entries),
            })

    json.dump({"markers": markers}, open(OUT, "w", encoding="utf-8"),
               ensure_ascii=False, separators=(",", ":"))
    print(f"провинций с >=2 кусками: {sum(1 for v in by_name.values() if len(v) >= 2)}, "
          f"кусков всего: {len(markers)}, записано {OUT}")


if __name__ == "__main__":
    main()
