from __future__ import annotations

import json
import platform
from collections import OrderedDict
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import numpy as np

try:
    import torch
except ImportError:  # pragma: no cover - exercised in dependency-light installs.
    torch = None

from .alpasim_contract import (
    BaseTrajectoryModel,
    DriveCommand,
    ModelPrediction,
    resample_trajectory,
)
from .image_ops import resize_and_center_crop
from .inference_rate_cache import PoseReanchoredInferenceCache

VAVAM_SOURCE_REPOSITORY = "https://github.com/valeoai/VideoActionModel"
VAVAM_SOURCE_TAG = "v1.0.0"
VAVAM_CODE_LICENSE = "MIT"
VAVAM_WEIGHTS_LICENSE = "VideoActionModel License (research-only, per upstream repo)"
VAVAM_EXPECTED_HEIGHT = 900
VAVAM_EXPECTED_WIDTH = 1600
VAVAM_NATIVE_FREQUENCY_HZ = 2.0  # native waypoint spacing, independent of serving cadence
VAVAM_NATIVE_PERIOD_S = 1.0 / VAVAM_NATIVE_FREQUENCY_HZ


_COMMAND_TO_VAVAM_ID = {
    int(DriveCommand.RIGHT): 0,
    int(DriveCommand.LEFT): 1,
    int(DriveCommand.STRAIGHT): 2,
    int(DriveCommand.UNKNOWN): 2,
}


def vavam_command_id(command: Any) -> int:
    value = getattr(command, "value", command)
    try:
        index = int(value)
    except (TypeError, ValueError):
        index = int(DriveCommand.UNKNOWN)
    return _COMMAND_TO_VAVAM_ID.get(index, _COMMAND_TO_VAVAM_ID[int(DriveCommand.UNKNOWN)])


def latest_camera_image(camera_images: dict[str, list[Any]], camera_id: str) -> np.ndarray:
    frames = camera_images.get(camera_id) or []
    if not frames:
        raise ValueError(f"no camera frames available for {camera_id!r}")
    return np.asarray(frames[-1].image)


class VAVAMAlpaSimModel(BaseTrajectoryModel):
    """Inference-only adapter for the public Valeo VideoActionModel (VAVAM).

    This wraps the same public ``vam`` package
    (``git+https://github.com/valeoai/VideoActionModel@v1.0.0``, MIT-licensed
    code, research-only weights license) that AlpaSim's own official e2e
    challenge sample submission uses. It is unrelated to AlpaSim's internal
    ``VAMModel`` (``alpasim_driver.models.vam_model``), which depends on a
    differently-provisioned, non-public checkpoint even though both import
    from a Python package literally named ``vam``.
    """

    @classmethod
    def from_config(
        cls,
        model_cfg: Any,
        device: Any,
        camera_ids: list[str],
        context_length: int | None,
        output_frequency_hz: int,
    ) -> "VAVAMAlpaSimModel":
        checkpoint_path = getattr(model_cfg, "checkpoint_path", None)
        tokenizer_checkpoint_path = getattr(model_cfg, "tokenizer_checkpoint_path", None)
        if not checkpoint_path:
            raise ValueError("VAVAMAlpaSimModel requires model.checkpoint_path")
        if not tokenizer_checkpoint_path:
            raise ValueError("VAVAMAlpaSimModel requires model.tokenizer_checkpoint_path")
        if context_length not in (None, 1):
            raise ValueError("VAVAMAlpaSimModel uses a single current camera frame")
        horizon_seconds = float(getattr(model_cfg, "horizon_seconds", 5.0))
        return cls(
            checkpoint_path=checkpoint_path,
            tokenizer_checkpoint_path=tokenizer_checkpoint_path,
            device=str(device),
            camera_ids=camera_ids,
            output_frequency_hz=int(output_frequency_hz),
            horizon_seconds=horizon_seconds,
        )

    def __init__(
        self,
        checkpoint_path: str | Path,
        tokenizer_checkpoint_path: str | Path,
        *,
        device: str = "cpu",
        camera_ids: list[str] | None = None,
        output_frequency_hz: int = 10,
        horizon_seconds: float = 5.0,
    ) -> None:
        if torch is None:
            raise ImportError("VAVAMAlpaSimModel requires torch; install with the alpasim extra.")
        self._camera_ids = camera_ids or ["front"]
        self._device = _resolve_device(device)
        self._checkpoint_path = Path(checkpoint_path).expanduser().resolve()
        self._tokenizer_checkpoint_path = Path(tokenizer_checkpoint_path).expanduser().resolve()
        self._output_frequency_hz = int(output_frequency_hz)
        self._horizon_seconds = float(horizon_seconds)
        self._use_autocast = self._device.type == "cuda" and platform.machine() != "aarch64"
        self._dtype = torch.float16 if self._use_autocast else torch.float32
        self._vam, self._tokenizer, self._transform = self._load()
        self._inference_cache = PoseReanchoredInferenceCache(min_interval_s=VAVAM_NATIVE_PERIOD_S)

    @property
    def camera_ids(self) -> list[str]:
        return self._camera_ids

    @property
    def context_length(self) -> int:
        return 1

    @property
    def output_frequency_hz(self) -> int:
        return self._output_frequency_hz

    def _load(self) -> tuple[Any, Any, Any]:
        from vam.action_expert import VideoActionModelInference
        from vam.datalib.transforms import NeuroNCAPTransform

        if not self._checkpoint_path.is_file():
            raise FileNotFoundError(f"VAVAM checkpoint not found: {self._checkpoint_path}")
        if not self._tokenizer_checkpoint_path.is_file():
            raise FileNotFoundError(
                f"VAVAM VQ tokenizer not found: {self._tokenizer_checkpoint_path}"
            )

        checkpoint = torch.load(self._checkpoint_path, map_location="cpu", weights_only=False)
        config = checkpoint["hyper_parameters"]["vam_conf"].copy()
        config.pop("_target_", None)
        config.pop("_recursive_", None)
        config["gpt_checkpoint_path"] = None
        config["action_checkpoint_path"] = None
        config["gpt_mup_base_shapes"] = None
        config["action_mup_base_shapes"] = None

        vam = VideoActionModelInference(**config)
        state_dict = OrderedDict()
        for key, value in checkpoint["state_dict"].items():
            state_dict[key.replace("vam.", "")] = value
        vam.load_state_dict(state_dict, strict=True)
        vam = vam.eval().to(self._device)

        tokenizer = torch.jit.load(self._tokenizer_checkpoint_path, map_location=self._device)
        tokenizer = tokenizer.to(self._device).eval()

        return vam, tokenizer, NeuroNCAPTransform()

    def _encode_command(self, command: Any) -> int:
        return vavam_command_id(command)

    def predict(self, prediction_input: Any) -> ModelPrediction:
        self._validate_cameras(prediction_input.camera_images)

        def _infer() -> np.ndarray:
            command_id = self._encode_command(prediction_input.command)
            image = latest_camera_image(prediction_input.camera_images, self.camera_ids[0])
            return self._run_inference(image, command_id)

        native_trajectory_xy, reused_cache = self._inference_cache.get(prediction_input, _infer)
        native_point_count = native_trajectory_xy.shape[0]

        if not np.isfinite(native_trajectory_xy).all():
            raise ValueError("VAVAM produced a non-finite trajectory")
        fitted_trajectory_xy, fitted_timestamps_s, extrapolated = _fit_to_horizon(
            native_trajectory_xy,
            native_frequency_hz=VAVAM_NATIVE_FREQUENCY_HZ,
            horizon_seconds=self._horizon_seconds,
        )
        trajectory_xy = resample_trajectory(
            fitted_trajectory_xy,
            output_frequency_hz=self._output_frequency_hz,
            horizon_seconds=self._horizon_seconds,
            source_timestamps=fitted_timestamps_s,
        )
        headings = self._compute_headings_from_trajectory(trajectory_xy)
        metadata = {
            "adapter": "alpabridge.simulator.vavam_model",
            "source_repository": VAVAM_SOURCE_REPOSITORY,
            "source_tag": VAVAM_SOURCE_TAG,
            "code_license": VAVAM_CODE_LICENSE,
            "weights_license": VAVAM_WEIGHTS_LICENSE,
            "input_contract": "single_camera_frame+discrete_command",
            "route_geometry_consumed": False,
            "native_points": int(native_point_count),
            "horizon_extrapolated": extrapolated,
            "reused_cached_inference": reused_cache,
        }
        return ModelPrediction(
            trajectory_xy=trajectory_xy,
            headings=headings,
            reasoning_text=json.dumps(metadata, sort_keys=True),
        )

    def _run_inference(self, image: np.ndarray, command_id: int) -> np.ndarray:
        cropped = resize_and_center_crop(image, VAVAM_EXPECTED_HEIGHT, VAVAM_EXPECTED_WIDTH)
        tensor = self._transform(cropped).unsqueeze(0).to(self._device)
        autocast_ctx = (
            torch.amp.autocast(self._device.type, dtype=self._dtype)
            if self._use_autocast
            else nullcontext()
        )

        with torch.no_grad():
            with autocast_ctx:
                tokens = self._tokenizer(tensor)
                batched_tokens = tokens.unsqueeze(1)
                batched_command = torch.tensor(
                    [[command_id]], device=self._device, dtype=torch.long
                )
                raw_trajectory = self._vam(batched_tokens, batched_command, self._dtype)

        return _format_trajectory(raw_trajectory)


def _fit_to_horizon(
    native_trajectory_xy: np.ndarray,
    *,
    native_frequency_hz: float,
    horizon_seconds: float,
) -> tuple[np.ndarray, np.ndarray, bool]:
    """Truncate or hold-position-extrapolate a native-cadence trajectory to
    span exactly ``horizon_seconds``, so its timestamps satisfy
    ``resample_trajectory``'s ``(0, horizon]`` requirement regardless of how
    many points the model actually predicted.
    """
    target_count = max(1, int(round(horizon_seconds * native_frequency_hz)))
    native_count = native_trajectory_xy.shape[0]
    if native_count >= target_count:
        fitted = native_trajectory_xy[:target_count]
        extrapolated = False
    else:
        pad = np.repeat(native_trajectory_xy[-1:], target_count - native_count, axis=0)
        fitted = np.concatenate([native_trajectory_xy, pad], axis=0)
        extrapolated = True
    timestamps_s = np.arange(1, target_count + 1, dtype=np.float64) / native_frequency_hz
    timestamps_s = np.minimum(timestamps_s, horizon_seconds)
    return fitted, timestamps_s, extrapolated


def _format_trajectory(trajectory: Any) -> np.ndarray:
    array = trajectory.detach().float().cpu().numpy()
    while array.ndim > 2 and array.shape[0] == 1:
        array = array.squeeze(0)
    if array.ndim != 2 or array.shape[1] != 2:
        raise ValueError(f"unexpected VAVAM trajectory shape {array.shape}")
    return array.astype(np.float32)


def _resolve_device(device: str) -> Any:
    requested = str(device).strip().lower()
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested for VAVAM but is unavailable")
    if requested not in {"cpu", "cuda"}:
        raise ValueError("VAVAM device must be cpu or cuda")
    return torch.device(requested)
