#!/usr/bin/env python3
"""Audit canonical layer-8 geometry against the numeric map_geometry mirror.

Layer 8 is rendered from assets/provinces.json (stable legacy ids).  Some newer
region/cell tooling historically used assets/map_geometry/provinces.json
(numeric ids).  This audit proves whether the mirror is still geometrically in
sync with the passport mapping and surfaces the exact suspicious ids seen in
manual editing.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "assets" / "provinces.json"
MIRROR = ROOT / "assets" / "map_geometry" / "provinces.json"
IDENTITIES = ROOT / "assets" / "game_data" / "provinces.json"
REPORT = ROOT / "reports" / "layer8_region_geometry_source_audit.json"
EXPECTED = 4027
SUSPICIOUS = {"province:1719", "province:2310", "province:3484"}


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def bbox(entry: dict[str, Any]) -> list[float]:
    raw = entry.get("bbox", [])
    if isinstance(raw, list) and len(raw) >= 4:
        return [round(float(x), 2) for x in raw[:4]]
    rings = entry.get("rings", [])
    pts = [p for ring in rings for p in ring if isinstance(p, list) and len(p) >= 2]
    if not pts:
        return []
    xs = [float(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    return [round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)]


def geometry_hash(entry: dict[str, Any]) -> str:
    payload = json.dumps(entry.get("rings", []), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def main() -> None:
    canonical_doc = read(CANONICAL)
    mirror_doc = read(MIRROR)
    identity_doc = read(IDENTITIES)

    canonical = {str(x.get("id", "")): x for x in canonical_doc.get("cells", []) if str(x.get("id", ""))}
    mirror = {str(x.get("id", "")): x for x in mirror_doc.get("provinces", []) if str(x.get("id", ""))}
    identities = {str(x.get("id", "")): x for x in identity_doc.get("provinces", []) if str(x.get("id", ""))}

    missing_canonical = []
    missing_mirror = []
    bbox_mismatch = []
    hash_mismatch = []
    suspicious = []

    for pid, identity in identities.items():
        legacy = str(identity.get("legacy_id", ""))
        c = canonical.get(legacy)
        m = mirror.get(pid)
        if c is None:
            missing_canonical.append({"province_id": pid, "legacy_id": legacy, "name": identity.get("name", "")})
            continue
        if m is None:
            missing_mirror.append({"province_id": pid, "legacy_id": legacy, "name": identity.get("name", "")})
            continue
        cb = bbox(c)
        mb = bbox(m)
        ch = geometry_hash(c)
        mh = geometry_hash(m)
        if cb != mb:
            bbox_mismatch.append({"province_id": pid, "legacy_id": legacy, "name": identity.get("name", ""), "canonical_bbox": cb, "mirror_bbox": mb})
        if ch != mh:
            hash_mismatch.append({"province_id": pid, "legacy_id": legacy, "name": identity.get("name", ""), "canonical_hash": ch, "mirror_hash": mh, "canonical_bbox": cb, "mirror_bbox": mb})
        if pid in SUSPICIOUS:
            suspicious.append({
                "province_id": pid,
                "legacy_id": legacy,
                "name": identity.get("name", ""),
                "canonical_bbox": cb,
                "mirror_bbox": mb,
                "bbox_equal": cb == mb,
                "geometry_hash_equal": ch == mh,
            })

    report = {
        "schema_version": 1,
        "format": "layer8_region_geometry_source_audit/v1",
        "canonical_source": str(CANONICAL),
        "mirror_source": str(MIRROR),
        "identity_source": str(IDENTITIES),
        "canonical_count": len(canonical),
        "mirror_count": len(mirror),
        "identity_count": len(identities),
        "missing_canonical_count": len(missing_canonical),
        "missing_mirror_count": len(missing_mirror),
        "bbox_mismatch_count": len(bbox_mismatch),
        "geometry_hash_mismatch_count": len(hash_mismatch),
        "missing_canonical": missing_canonical[:100],
        "missing_mirror": missing_mirror[:100],
        "bbox_mismatch_examples": bbox_mismatch[:100],
        "geometry_hash_mismatch_examples": hash_mismatch[:100],
        "suspicious_manual_edit_ids": suspicious,
        "canonical_layer8_required_for_editor_and_region_geometry": True,
    }

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        "LAYER8_REGION_GEOMETRY_AUDIT",
        f"canonical={len(canonical)}",
        f"mirror={len(mirror)}",
        f"identities={len(identities)}",
        f"missing_canonical={len(missing_canonical)}",
        f"missing_mirror={len(missing_mirror)}",
        f"bbox_mismatch={len(bbox_mismatch)}",
        f"hash_mismatch={len(hash_mismatch)}",
    )
    for item in suspicious:
        print("SUSPICIOUS", item)

    if len(canonical) != EXPECTED or len(identities) != EXPECTED:
        raise SystemExit(2)
    if missing_canonical or missing_mirror:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
