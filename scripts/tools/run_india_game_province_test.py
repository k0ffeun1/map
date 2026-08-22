#!/usr/bin/env python3
"""One-command India architecture test."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(script: str) -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "tools" / script)], cwd=ROOT, check=True)


if __name__ == "__main__":
    run("build_india_stage6_test.py")
    run("build_india_game_provinces_test.py")
    print("India game-province test complete")
