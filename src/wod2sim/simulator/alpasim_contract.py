from __future__ import annotations

import math
import zlib
from typing import Any

import numpy as np

try:
    from alpasim_driver.models.base import (
        BaseTrajectoryModel,
        DriveCommand,
        ModelPrediction,
        PredictionInput,
    )
    from alpasim_driver.schema import ModelConfig
except ImportError:
    class DriveCommand:
        LEFT = 0
        STRAIGHT = 1
        RIGHT = 2
        UNKNOWN = 3

    class ModelPrediction:
        def __init__(
            self,
            trajectory_xy: np.ndarray,
            headings: np.ndarray,
            reasoning_text: str | None = None,
        ) -> None:
            self.trajectory_xy = trajectory_xy
            self.headings = headings
            self.reasoning_text = reasoning_text

    class BaseTrajectoryModel:
        @staticmethod
        def _compute_headings_from_trajectory(trajectory_xy: np.ndarray) -> np.ndarray:
            previous = np.zeros_like(trajectory_xy)
            previous[1:, :] = trajectory_xy[:-1, :]
            deltas = trajectory_xy - previous
            return np.arctan2(deltas[:, 1], deltas[:, 0])

        def _validate_cameras(self, camera_images: dict[str, list[Any]]) -> None:
            received = set(camera_images)
            expected = set(self.camera_ids)
            if received != expected:
                raise ValueError(
                    f"{self.__class__.__name__} expects cameras {expected}, got {received}"
                )

    ModelConfig = Any
    PredictionInput = Any


class SensorFreshnessGuard:
    """Reject camera streams that stop advancing while the ego pose changes."""

    _MAX_POSE_CAMERA_LAG_US = 50_000

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._last_camera_timestamp_us: int | None = None
        self._last_camera_fingerprint: int | None = None
        self._last_pose_signature: tuple[float, float, float] | None = None
        self._last_diagnostics: dict[str, Any] | None = None

    def validate(self, prediction_input: Any) -> dict[str, Any]:
        camera_timestamp_us = _latest_camera_timestamp_us(prediction_input)
        camera_fingerprint = _latest_camera_fingerprint(prediction_input)
        pose_signature = _current_pose_signature(prediction_input)
        pose_timestamp_us = _current_pose_timestamp_us(prediction_input)
        previous_pose = self._last_pose_signature
        previous_camera_timestamp = self._last_camera_timestamp_us
        previous_camera_fingerprint = self._last_camera_fingerprint
        diagnostics = {
            "status": "ok",
            "camera_timestamp_us": camera_timestamp_us,
            "camera_fingerprint": camera_fingerprint,
            "pose_timestamp_us": pose_timestamp_us,
            "pose_signature": _jsonable_pose_signature(pose_signature),
            "previous_pose_signature": _jsonable_pose_signature(previous_pose),
            "previous_camera_timestamp_us": previous_camera_timestamp,
            "previous_camera_fingerprint": previous_camera_fingerprint,
            "pose_camera_lag_us": None
            if pose_timestamp_us is None or camera_timestamp_us is None
            else int(pose_timestamp_us) - int(camera_timestamp_us),
        }
        self._last_diagnostics = diagnostics
        if camera_timestamp_us is None or pose_signature is None:
            diagnostics["status"] = "insufficient_signal"
            return diagnostics
        if (
            pose_timestamp_us is not None
            and pose_timestamp_us - camera_timestamp_us > self._MAX_POSE_CAMERA_LAG_US
        ):
            lag_us = pose_timestamp_us - camera_timestamp_us
            diagnostics["status"] = "stale_pose_leads_camera"
            raise RuntimeError(
                f"{self._model_name} detected a stale camera stream: latest ego pose timestamp "
                f"{pose_timestamp_us} leads the newest camera frame {camera_timestamp_us} by "
                f"{lag_us} us. The vehicle is moving while camera frames are not updating; "
                "check the upstream AlpaSim/sensorsim camera pipeline."
            )

        if previous_pose is None or previous_camera_timestamp is None:
            diagnostics["status"] = "ok_initial"
            self._commit_observation(pose_signature, camera_timestamp_us, camera_fingerprint)
            return diagnostics
        if not _pose_changed(previous_pose, pose_signature):
            diagnostics["status"] = "ok_pose_static"
            self._commit_observation(pose_signature, camera_timestamp_us, camera_fingerprint)
            return diagnostics
        if (
            camera_timestamp_us > previous_camera_timestamp
            and camera_fingerprint is not None
            and previous_camera_fingerprint is not None
            and camera_fingerprint == previous_camera_fingerprint
        ):
            diagnostics["status"] = "frozen_camera_content"
            raise RuntimeError(
                f"{self._model_name} detected a frozen camera stream: ego pose changed from "
                f"{previous_pose} to {pose_signature}, and the latest camera timestamp advanced "
                f"from {previous_camera_timestamp} to {camera_timestamp_us}, but the newest camera "
                "frame content did not change. The vehicle is moving while camera imagery is "
                "effectively frozen; check the upstream AlpaSim/sensorsim camera pipeline."
            )
        if camera_timestamp_us > previous_camera_timestamp:
            diagnostics["status"] = "ok_camera_advanced"
            self._commit_observation(pose_signature, camera_timestamp_us, camera_fingerprint)
            return diagnostics

        diagnostics["status"] = "stale_camera_timestamp"
        raise RuntimeError(
            f"{self._model_name} detected a stale camera stream: ego pose changed from "
            f"{previous_pose} to {pose_signature}, but the latest camera timestamp stayed at "
            f"{camera_timestamp_us}. The vehicle is moving while camera frames are not updating; "
            "check the upstream AlpaSim/sensorsim camera pipeline."
        )

    def last_diagnostics(self) -> dict[str, Any] | None:
        if self._last_diagnostics is None:
            return None
        return dict(self._last_diagnostics)

    def _commit_observation(
        self,
        pose_signature: tuple[float, float, float],
        camera_timestamp_us: int | None,
        camera_fingerprint: int | None,
    ) -> None:
        self._last_pose_signature = pose_signature
        self._last_camera_timestamp_us = camera_timestamp_us
        self._last_camera_fingerprint = camera_fingerprint


def prediction_scene_id(prediction_input: Any) -> str | None:
    value = getattr(prediction_input, "scene_id", None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def resample_trajectory(
    trajectory_xy: np.ndarray,
    output_frequency_hz: int,
    horizon_seconds: float,
    source_timestamps: np.ndarray | None = None,
) -> np.ndarray:
    try:
        output_frequency = float(output_frequency_hz)
        horizon = float(horizon_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("output_frequency_hz and horizon_seconds must be numeric") from exc
    if not math.isfinite(output_frequency) or output_frequency <= 0.0:
        raise ValueError("output_frequency_hz must be positive and finite")
    if not math.isfinite(horizon) or horizon <= 0.0:
        raise ValueError("horizon_seconds must be positive and finite")

    trajectory = np.asarray(trajectory_xy, dtype=np.float32)
    if trajectory.ndim != 2 or trajectory.shape[1] != 2 or trajectory.shape[0] < 1:
        raise ValueError("trajectory_xy must have shape (N, 2) with N >= 1")
    if not np.isfinite(trajectory).all():
        raise ValueError("trajectory_xy must contain only finite values")

    expected_points = max(1, int(round(output_frequency * horizon)))
    target_t = np.linspace(
        horizon / expected_points,
        horizon,
        expected_points,
        dtype=np.float64,
    )

    if source_timestamps is None:
        source_t = np.linspace(0.0, horizon, trajectory.shape[0] + 1, dtype=np.float64)
        target_grid_matches_source = expected_points == trajectory.shape[0]
    else:
        timestamps = np.asarray(source_timestamps, dtype=np.float64)
        if timestamps.shape != (trajectory.shape[0],):
            raise ValueError("source_timestamps must have shape (N,) matching trajectory_xy")
        if not np.isfinite(timestamps).all():
            raise ValueError("source_timestamps must contain only finite values")
        if np.any(timestamps <= 0.0) or np.any(timestamps > horizon):
            raise ValueError("source_timestamps must lie within (0, horizon_seconds]")
        if np.any(np.diff(timestamps) <= 0.0):
            raise ValueError("source_timestamps must be strictly increasing")
        source_t = np.concatenate((np.asarray([0.0], dtype=np.float64), timestamps))
        target_grid_matches_source = (
            expected_points == trajectory.shape[0]
            and np.allclose(timestamps, target_t, rtol=0.0, atol=1e-7)
        )

    if target_grid_matches_source:
        return trajectory

    # The current ego pose is the implicit origin for future ego-relative points.
    source_xy = np.vstack((np.zeros((1, 2), dtype=np.float32), trajectory))
    x = np.interp(target_t, source_t, source_xy[:, 0])
    y = np.interp(target_t, source_t, source_xy[:, 1])
    return np.stack((x, y), axis=1).astype(np.float32)


def _latest_camera_timestamp_us(prediction_input: Any) -> int | None:
    camera_images = getattr(prediction_input, "camera_images", {}) or {}
    latest_timestamp: int | None = None
    for frames in camera_images.values():
        if not frames:
            continue
        frame = frames[-1]
        timestamp = getattr(frame, "timestamp_us", None)
        if timestamp is None and isinstance(frame, (tuple, list)) and frame:
            timestamp = frame[0]
        if timestamp is None:
            continue
        timestamp_int = int(timestamp)
        if latest_timestamp is None or timestamp_int > latest_timestamp:
            latest_timestamp = timestamp_int
    return latest_timestamp


def _latest_camera_fingerprint(prediction_input: Any) -> int | None:
    camera_images = getattr(prediction_input, "camera_images", {}) or {}
    fingerprint: int | None = None
    for camera_id in sorted(camera_images):
        frames = camera_images.get(camera_id) or []
        if not frames:
            continue
        frame = frames[-1]
        image = getattr(frame, "image", None)
        if image is None and isinstance(frame, (tuple, list)) and len(frame) >= 2:
            image = frame[1]
        if image is None:
            continue
        try:
            image_array = np.ascontiguousarray(np.asarray(image))
        except Exception:
            continue
        fingerprint_value = zlib.crc32(camera_id.encode("utf-8"))
        fingerprint_value = zlib.crc32(
            str(image_array.shape).encode("utf-8"), fingerprint_value
        )
        fingerprint_value = zlib.crc32(
            str(image_array.dtype).encode("utf-8"), fingerprint_value
        )
        fingerprint_value = zlib.crc32(
            memoryview(image_array).cast("B"), fingerprint_value
        )
        fingerprint = (
            fingerprint_value
            if fingerprint is None
            else zlib.crc32(
                fingerprint_value.to_bytes(4, "little", signed=False),
                fingerprint,
            )
        )
    return fingerprint


def _current_pose_signature(prediction_input: Any) -> tuple[float, float, float] | None:
    ego_pose_history = getattr(prediction_input, "ego_pose_history", []) or []
    for pose in reversed(list(ego_pose_history)):
        parsed = _pose_like_to_signature(pose)
        if parsed is not None:
            return parsed
    ego_pose = getattr(prediction_input, "ego_pose", None)
    if ego_pose is not None:
        return _pose_like_to_signature(ego_pose)
    return None


def _current_pose_timestamp_us(prediction_input: Any) -> int | None:
    ego_pose_history = getattr(prediction_input, "ego_pose_history", []) or []
    for pose in reversed(list(ego_pose_history)):
        timestamp = getattr(pose, "timestamp_us", None)
        if timestamp is not None:
            try:
                return int(timestamp)
            except (TypeError, ValueError):
                continue
    ego_pose = getattr(prediction_input, "ego_pose", None)
    if ego_pose is not None:
        timestamp = getattr(ego_pose, "timestamp_us", None)
        if timestamp is not None:
            try:
                return int(timestamp)
            except (TypeError, ValueError):
                return None
    return None


def _pose_like_to_signature(pose: Any) -> tuple[float, float, float] | None:
    raw_pose = getattr(pose, "pose", None)
    if raw_pose is not None:
        pose = raw_pose

    x = _first_float_attr(pose, ("x", "world_x"))
    y = _first_float_attr(pose, ("y", "world_y"))
    vec = getattr(pose, "vec", None)
    if x is None and vec is not None:
        x = _first_float_attr(vec, ("x",))
    if y is None and vec is not None:
        y = _first_float_attr(vec, ("y",))
    position = getattr(pose, "position", None)
    if x is None and position is not None:
        x = _first_float_attr(position, ("x",))
    if y is None and position is not None:
        y = _first_float_attr(position, ("y",))
    translation = getattr(pose, "translation", None)
    if x is None and translation is not None:
        x = _first_float_attr(translation, ("x",))
    if y is None and translation is not None:
        y = _first_float_attr(translation, ("y",))
    if x is None or y is None:
        return None

    yaw = _first_float_attr(pose, ("yaw", "heading", "heading_rad", "world_heading"))
    if yaw is None:
        quat = getattr(pose, "quat", getattr(pose, "quaternion", None))
        yaw = _yaw_from_quat_like(quat) if quat is not None else 0.0
    return (round(float(x), 4), round(float(y), 4), round(float(yaw), 6))


def _first_float_attr(obj: Any, names: tuple[str, ...]) -> float | None:
    for name in names:
        value = getattr(obj, name, None)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _jsonable_pose_signature(
    pose: tuple[float, float, float] | None,
) -> list[float] | None:
    if pose is None:
        return None
    return [float(pose[0]), float(pose[1]), float(pose[2])]


def _yaw_from_quat_like(quat: Any) -> float | None:
    if quat is None:
        return None
    z = _first_float_attr(quat, ("z",))
    w = _first_float_attr(quat, ("w",))
    if z is None or w is None:
        return None
    return math.atan2(2.0 * w * z, 1.0 - 2.0 * z * z)


def _pose_changed(
    previous_pose: tuple[float, float, float],
    current_pose: tuple[float, float, float],
) -> bool:
    dx = abs(current_pose[0] - previous_pose[0])
    dy = abs(current_pose[1] - previous_pose[1])
    dheading = abs(current_pose[2] - previous_pose[2])
    return dx > 0.05 or dy > 0.05 or dheading > 0.01
