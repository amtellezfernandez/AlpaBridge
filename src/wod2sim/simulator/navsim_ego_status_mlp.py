from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

try:
    import torch
    import torch.nn as nn
except ImportError:  # pragma: no cover - exercised in dependency-light installs.
    torch = None
    nn = None

from .alpasim_contract import BaseTrajectoryModel, DriveCommand, ModelPrediction

NAVSIM_SOURCE_COMMIT = "0811876c274e8b058ab2be9b3dcd4d37bd23f177"
NAVSIM_CHECKPOINT_REPOSITORY = "autonomousvision/navsim_baselines"
NAVSIM_CHECKPOINT_REVISION = "32d89c0ae6e7c13c311f4a034002006c250afab0"
NAVSIM_EGO_STATUS_FEATURES = 8
NAVSIM_EGO_STATUS_HIDDEN = 512
NAVSIM_EGO_STATUS_POSES = 8
NAVSIM_EGO_STATUS_HORIZON_SECONDS = 4.0
NAVSIM_EGO_STATUS_OUTPUT_FREQUENCY_HZ = 2


class NavsimEgoStatusMLPModel(BaseTrajectoryModel):
    """Inference-only adapter for NAVSIM v1.1's published EgoStatusMLP baseline."""

    @classmethod
    def from_config(
        cls,
        model_cfg: Any,
        device: Any,
        camera_ids: list[str],
        context_length: int | None,
        output_frequency_hz: int,
    ) -> "NavsimEgoStatusMLPModel":
        checkpoint_path = getattr(model_cfg, "checkpoint_path", None)
        if not checkpoint_path:
            raise ValueError(
                "NavsimEgoStatusMLPModel requires model.checkpoint_path"
            )
        if context_length not in (None, 1):
            raise ValueError("NAVSIM EgoStatusMLP uses a single current state")
        if output_frequency_hz != NAVSIM_EGO_STATUS_OUTPUT_FREQUENCY_HZ:
            raise ValueError(
                "NAVSIM EgoStatusMLP must retain its published 2 Hz output cadence"
            )
        return cls(
            checkpoint_path=checkpoint_path,
            device=str(device),
            camera_ids=camera_ids,
        )

    def __init__(
        self,
        checkpoint_path: str | Path,
        *,
        device: str = "cpu",
        camera_ids: list[str] | None = None,
    ) -> None:
        if torch is None or nn is None:
            raise ImportError(
                "NavsimEgoStatusMLPModel requires torch in the learned-policy runtime."
            )
        self._camera_ids = camera_ids or ["front"]
        self._device = _resolve_device(device)
        self._checkpoint_path = Path(checkpoint_path).expanduser().resolve()
        self._mlp = nn.Sequential(
            nn.Linear(NAVSIM_EGO_STATUS_FEATURES, NAVSIM_EGO_STATUS_HIDDEN),
            nn.ReLU(),
            nn.Linear(NAVSIM_EGO_STATUS_HIDDEN, NAVSIM_EGO_STATUS_HIDDEN),
            nn.ReLU(),
            nn.Linear(NAVSIM_EGO_STATUS_HIDDEN, NAVSIM_EGO_STATUS_HIDDEN),
            nn.ReLU(),
            nn.Linear(
                NAVSIM_EGO_STATUS_HIDDEN,
                NAVSIM_EGO_STATUS_POSES * 3,
            ),
        )
        self._load_checkpoint()
        self._mlp.to(self._device)
        self._mlp.eval()

    @property
    def camera_ids(self) -> list[str]:
        return self._camera_ids

    @property
    def context_length(self) -> int:
        return 1

    @property
    def output_frequency_hz(self) -> int:
        return NAVSIM_EGO_STATUS_OUTPUT_FREQUENCY_HZ

    def _encode_command(self, command: Any) -> np.ndarray:
        return _command_one_hot(command)

    def predict(self, prediction_input: Any) -> ModelPrediction:
        feature = navsim_ego_status_feature(prediction_input)
        feature_tensor = torch.from_numpy(feature).to(self._device).unsqueeze(0)
        with torch.no_grad():
            raw_trajectory = self._mlp(feature_tensor)
        poses = (
            raw_trajectory.reshape(NAVSIM_EGO_STATUS_POSES, 3)
            .detach()
            .to("cpu")
            .numpy()
            .astype(np.float32)
        )
        if not np.isfinite(poses).all():
            raise ValueError("NAVSIM EgoStatusMLP produced a non-finite trajectory")
        metadata = {
            "adapter": "wod2sim.simulator.navsim_ego_status_mlp",
            "checkpoint_repository": NAVSIM_CHECKPOINT_REPOSITORY,
            "checkpoint_revision": NAVSIM_CHECKPOINT_REVISION,
            "input_contract": "velocity_xy+acceleration_xy+discrete_command",
            "route_geometry_consumed": False,
            "source_commit": NAVSIM_SOURCE_COMMIT,
        }
        return ModelPrediction(
            trajectory_xy=poses[:, :2],
            headings=poses[:, 2],
            reasoning_text=json.dumps(metadata, sort_keys=True),
        )

    def _load_checkpoint(self) -> None:
        if not self._checkpoint_path.is_file():
            raise FileNotFoundError(
                f"NAVSIM EgoStatusMLP checkpoint not found: {self._checkpoint_path}"
            )
        checkpoint = torch.load(
            self._checkpoint_path,
            map_location="cpu",
            weights_only=True,
        )
        if not isinstance(checkpoint, dict) or not isinstance(
            checkpoint.get("state_dict"), dict
        ):
            raise ValueError(
                "NAVSIM EgoStatusMLP checkpoint must contain a state_dict mapping"
            )
        prefix = "agent._mlp."
        state_dict = {
            key.removeprefix(prefix): value
            for key, value in checkpoint["state_dict"].items()
            if isinstance(key, str) and key.startswith(prefix)
        }
        expected = self._mlp.state_dict()
        if set(state_dict) != set(expected):
            raise ValueError(
                "NAVSIM EgoStatusMLP checkpoint parameters do not match the "
                "published v1.1 architecture"
            )
        mismatched = [
            key
            for key in expected
            if tuple(state_dict[key].shape) != tuple(expected[key].shape)
        ]
        if mismatched:
            raise ValueError(
                "NAVSIM EgoStatusMLP checkpoint tensor shapes do not match the "
                f"published v1.1 architecture: {', '.join(mismatched)}"
            )
        self._mlp.load_state_dict(state_dict, strict=True)


def navsim_ego_status_feature(prediction_input: Any) -> np.ndarray:
    velocity_xy = _finite_xy(
        getattr(prediction_input, "velocity_xy", None),
        fallback=(float(getattr(prediction_input, "speed", 0.0) or 0.0), 0.0),
    )
    acceleration_xy = _finite_xy(
        getattr(prediction_input, "acceleration_xy", None),
        fallback=(
            float(getattr(prediction_input, "acceleration", 0.0) or 0.0),
            0.0,
        ),
    )
    return np.concatenate(
        (
            np.asarray(velocity_xy, dtype=np.float32),
            np.asarray(acceleration_xy, dtype=np.float32),
            _command_one_hot(getattr(prediction_input, "command", None)),
        )
    ).astype(np.float32)


def _command_one_hot(command: Any) -> np.ndarray:
    value = getattr(command, "value", command)
    try:
        index = int(value)
    except (TypeError, ValueError):
        index = int(DriveCommand.UNKNOWN)
    if index not in (0, 1, 2, 3):
        index = int(DriveCommand.UNKNOWN)
    encoded = np.zeros(4, dtype=np.float32)
    encoded[index] = 1.0
    return encoded


def _finite_xy(
    value: Any,
    *,
    fallback: tuple[float, float],
) -> tuple[float, float]:
    try:
        x, y = value
        parsed = (float(x), float(y))
    except (TypeError, ValueError):
        parsed = (float(fallback[0]), float(fallback[1]))
    if not all(math.isfinite(item) for item in parsed):
        return (0.0, 0.0)
    return parsed


def _resolve_device(device: str) -> Any:
    requested = str(device).strip().lower()
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested for NAVSIM EgoStatusMLP but is unavailable")
    if requested not in {"cpu", "cuda"}:
        raise ValueError("NAVSIM EgoStatusMLP device must be cpu or cuda")
    return torch.device(requested)
