#!/usr/bin/env python3
"""Build the La Coruna layer through the regional-table Political Claims pipeline.

The implementation itself lives in ``build_regional_political_claims_cells``.
This small entry point fixes the scope to the guide's first milestone: only
La Coruna, its P3 Galicia profile, its capital anchor, and exactly four cells.
"""
from __future__ import annotations

import json
from pathlib import Path

import build_regional_political_claims_cells as claims


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "assets" / "cells_lacoruna_political_claims.json"
REPORT = ROOT / "assets" / "cell_topology" / "lacoruna_political_claims_validation.json"


def main() -> None:
    payload, report = claims.build(all_provinces=False)
    if not report["ok"] or report["cell_count"] != 4 or report["province_count"] != 1:
        raise ValueError(f"Political Claims milestone failed: {report}")
    payload["provenance"]["output_scope"] = "La Coruna guide milestone only"
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}: 4 cells")


if __name__ == "__main__":
    main()
