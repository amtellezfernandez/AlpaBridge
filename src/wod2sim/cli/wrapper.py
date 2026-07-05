from __future__ import annotations

from importlib import import_module
import runpy
from typing import Any


def export_command_namespace(namespace: dict[str, Any], module: str) -> Any:
    target_module = f"wod2sim.cli.commands.{module}"
    target = import_module(target_module)
    namespace["_TARGET_MODULE"] = target_module
    namespace["_target"] = target
    for name, value in vars(target).items():
        if name.startswith("_") and name[1:].isupper():
            continue
        if name not in {"__name__", "__package__", "__loader__", "__spec__"}:
            namespace[name] = value
    return target


def run_command_module(target_module: str, target: Any) -> None:
    if hasattr(target, "main"):
        raise SystemExit(target.main())
    runpy.run_module(target_module, run_name="__main__")
