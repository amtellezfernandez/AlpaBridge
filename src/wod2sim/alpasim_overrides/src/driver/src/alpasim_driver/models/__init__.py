# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 NVIDIA Corporation

"""Model abstraction layer for trajectory prediction models.

This override keeps the base abstractions importable in minimal local-driver
environments where heavyweight built-in backends (VAM/Alpamayo) are not
installed. Those backends remain available through their entry points when
their optional dependencies are present.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .base import (
    BaseTrajectoryModel,
    CameraFrame,
    CameraImages,
    DriveCommand,
    ModelPrediction,
    PredictionInput,
)
from .manual_model import ManualModel

_LAZY_IMPORTS = {
    "Alpamayo15Model": ".alpamayo1_5_model",
    "Alpamayo1Model": ".alpamayo1_model",
    "VAMModel": ".vam_model",
}

__all__ = [
    "Alpamayo15Model",
    "Alpamayo1Model",
    "BaseTrajectoryModel",
    "CameraFrame",
    "CameraImages",
    "DriveCommand",
    "ManualModel",
    "ModelPrediction",
    "PredictionInput",
    "VAMModel",
]


def __getattr__(name: str) -> Any:
    module_name = _LAZY_IMPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
