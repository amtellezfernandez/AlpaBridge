from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wod2sim.cli.wrapper import export_command_namespace, run_command_module

_TARGET_MODULE = ""
_target = export_command_namespace(globals(), "benchmark_operator_matrix")

if __name__ == "__main__":
    run_command_module(_TARGET_MODULE, _target)
