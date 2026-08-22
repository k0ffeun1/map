#!/usr/bin/env python3
"""Ultra-conservative coastal-spike configuration for Britain/North Atlantic.

The first coastal pass proved too permissive and started selecting legitimate
small capes.  This wrapper keeps the v2 topology/safety machinery but narrows the
coastal detector to almost line-width source artifacts only.
"""
from __future__ import annotations

import run_britain_north_atlantic_regional_test_v2 as v2


def main() -> None:
    # Roughly <150-200 m effective ribbon width at Britain latitudes.
    v2.COAST_MAX_EFFECTIVE_WIDTH = 0.06
    # Require a very obvious out-and-back needle rather than an ordinary cape.
    v2.COAST_MIN_STRETCH = 3.0
    v2.COAST_MIN_EXCESS = 1.0
    # A single edit must be tiny in both absolute and relative terms.
    v2.COAST_MAX_SINGLE_REMOVAL_KM2 = 8.0
    v2.COAST_MAX_SINGLE_REMOVAL_FRACTION = 8.0e-4
    # Across the whole regional test, at most 0.002% of land may be removed.
    v2.COAST_MAX_TOTAL_REMOVAL_RATIO = 2.0e-5
    v2.COAST_OWNER_SHARE = 0.96
    v2.COAST_MAX_PASSES_PER_PART = 6
    v2.main()


if __name__ == "__main__":
    main()
