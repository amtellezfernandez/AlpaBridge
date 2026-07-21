#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alpabridge.cli.commands.build_alpasim_local_usdz_cache import main

if __name__ == "__main__":
    raise SystemExit(main())
