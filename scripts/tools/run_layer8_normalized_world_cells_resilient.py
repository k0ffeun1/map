#!/usr/bin/env python3
"""Resilient CLI for normalized Layer-8 cell generation.

The underlying Stage-6 political-cell generator is deterministic, but a very
small number of polygons can hit a numerical topology edge case for one seed
(e.g. polygonize returns N-1 faces for N requested zones). This wrapper keeps
all normal output identical and retries only failed micro-partitions with a
small deterministic sequence of alternate seeds.

This is not random fallback: parent ID, requested seed and retry order fully
determine the result, so generation remains reproducible across machines/shards.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import build_layer8_normalized_world_cells as world

ORIGINAL_MICRO_PARTITION = world.stage6.micro_partition
MAX_ATTEMPTS = 8
RETRY_SEED_STEP = 104729  # prime, deterministic


def resilient_micro_partition(
    land: Any,
    zone_count: int,
    city: Any,
    seed: int,
    zone_offset: int = 0,
):
    errors: list[str] = []
    for attempt in range(MAX_ATTEMPTS):
        effective_seed = int(seed) + attempt * RETRY_SEED_STEP
        try:
            final, stats = ORIGINAL_MICRO_PARTITION(
                land,
                zone_count,
                city,
                effective_seed,
                zone_offset,
            )
            stats = dict(stats)
            stats["topology_retry_attempt"] = attempt
            stats["requested_seed"] = int(seed)
            stats["effective_seed"] = effective_seed
            if attempt:
                stats["topology_retry_recovered"] = True
                stats["topology_retry_prior_errors"] = errors
            else:
                stats["topology_retry_recovered"] = False
            return final, stats
        except RuntimeError as error:
            errors.append(f"attempt={attempt} seed={effective_seed}: {error}")

    raise RuntimeError(
        "deterministic topology retries exhausted: " + " | ".join(errors)
    )


def main() -> None:
    world.stage6.micro_partition = resilient_micro_partition
    world.main()


if __name__ == "__main__":
    main()
