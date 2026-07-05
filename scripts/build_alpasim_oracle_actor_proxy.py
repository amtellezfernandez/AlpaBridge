from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wod2sim.cli.wrapper import export_command_namespace, run_command_module

_TARGET_MODULE = ""
_target = export_command_namespace(globals(), "build_alpasim_oracle_actor_proxy")

if __name__ == "__main__":
    run_command_module(_TARGET_MODULE, _target)
