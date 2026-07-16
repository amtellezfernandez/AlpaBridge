from __future__ import annotations

import json
import math
import os
import zlib
from pathlib import Path
from threading import Lock
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
        def __init__(self, trajectory_xy: np.ndarray, headings: np.ndarray, reasoning_text: str | None = None) -> None:
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
                raise ValueError(f"{self.__class__.__name__} expects cameras {expected}, got {received}")

    ModelConfig = Any
    PredictionInput = Any

from .alpasim_signal import extract_alpasim_signal, scenario_from_command
from .environment import Scenario, nearest_lane_point, route_centerline, scenario_at_tick
from .perception import perceive_scene
from .spotlight_reflex import SpotlightSelection, evaluate_maneuver_candidates
from .world_model import update_world_state


class SpotlightReflexAlpaSimModel(BaseTrajectoryModel):
    """AlpaSim trajectory-model adapter for the Spotlight Reflex policy.

    AlpaSim calls model plugins with camera tensors, route command, speed, acceleration,
    and ego history. This adapter stays dependency-light but uses the available
    simulator signal: route command, dynamics, camera exposure/visibility, and any
    optional structured hazards attached by an upstream AlpaSim/AlpaSignal layer.
    """

    _DEFAULT_CAMERA_IDS = ["camera_front_wide_120fov"]
    _HORIZON_SECONDS = 5.0
    _LEGAL_TOKENS = frozenset({"stop", "crawl", "maintain", "slow_yield", "lane_recover"})
    _ROUTE_MARGIN_BUFFER_M = 0.45
    _MAX_ROUTE_DEVIATION_M = 0.75

    @classmethod
    def from_config(
        cls,
        model_cfg: ModelConfig,
        device: Any,
        camera_ids: list[str],
        context_length: int | None,
        output_frequency_hz: int,
    ) -> "SpotlightReflexAlpaSimModel":
        log_path = os.getenv("WOD2SIM_SPOTLIGHT_LOG_PATH", str(_model_cfg_value(model_cfg, "log_path", "") or "")).strip()
        return cls(
            camera_ids=camera_ids,
            context_length=context_length or 1,
            output_frequency_hz=output_frequency_hz,
            log_path=Path(log_path) if log_path else None,
        )

    def __init__(
        self,
        camera_ids: list[str] | None = None,
        context_length: int = 1,
        output_frequency_hz: int = 4,
        log_path: Path | None = None,
    ) -> None:
        self._camera_ids = camera_ids or list(self._DEFAULT_CAMERA_IDS)
        self._context_length = context_length
        self._output_frequency_hz = output_frequency_hz
        self._log_path = log_path
        self._log_lock = Lock()
        self._prediction_counter = 0
        self._sensor_freshness_guard = _SensorFreshnessGuard(self.__class__.__name__)

    @property
    def camera_ids(self) -> list[str]:
        return self._camera_ids

    @property
    def context_length(self) -> int:
        return self._context_length

    @property
    def output_frequency_hz(self) -> int:
        return self._output_frequency_hz

    def _encode_command(self, command: DriveCommand) -> str:
        return {
            DriveCommand.LEFT: "left",
            DriveCommand.STRAIGHT: "straight",
            DriveCommand.RIGHT: "right",
            DriveCommand.UNKNOWN: "straight",
        }[command]

    def predict(self, prediction_input: PredictionInput) -> ModelPrediction:
        self._validate_cameras(prediction_input.camera_images)
        for camera_id, frames in prediction_input.camera_images.items():
            if len(frames) != self._context_length:
                raise ValueError(
                    f"SpotlightReflexAlpaSimModel expects {self._context_length} "
                    f"frame(s) for {camera_id}, got {len(frames)}"
                )
        command = self._encode_command(prediction_input.command)
        speed_mps = max(0.25, float(prediction_input.speed))
        try:
            sensor_freshness = self._sensor_freshness_guard.validate(prediction_input)
        except RuntimeError as exc:
            self._append_prediction_log(
                prediction_input=prediction_input,
                payload={
                    "command": command,
                    "speed_mps": round(float(speed_mps), 4),
                    "result": "sensor_failure",
                    "sensor_error": str(exc),
                    "sensor_freshness": self._sensor_freshness_guard.last_diagnostics(),
                },
            )
            raise

        alpasim_signal = extract_alpasim_signal(prediction_input)
        scenario = scenario_from_command(command, alpasim_signal)
        active_scenario = scenario_at_tick(scenario, 0)
        position = active_scenario.start
        perception = perceive_scene(active_scenario, position)
        world_state = update_world_state(active_scenario, position, perception)
        selection = _select_legal_transfer_maneuver(
            active_scenario,
            position,
            world_state,
            perception,
            speed_mps=speed_mps,
        )

        trajectory_xy = _resample_to_frequency(
            np.asarray(selection.candidate.trajectory, dtype=np.float32),
            output_frequency_hz=self._output_frequency_hz,
            horizon_seconds=self._HORIZON_SECONDS,
        )
        headings = self._compute_headings_from_trajectory(trajectory_xy)
        selection_metadata = selection.to_metadata()
        reasoning_text = json.dumps(
            {
                "adapter": "wod2sim.simulator.spotlight_reflex",
                "command": command,
                "selected_maneuver": selection.candidate.name,
                "candidate_count": selection.candidate_count,
                "reference_count": selection.reference_count,
                "selector_score": selection.score.combined_score,
                "selector_effective_score": selection_metadata["selector_effective_score"],
                "selector_3s_score": selection.score.score_3s,
                "selector_5s_score": selection.score.score_5s,
                "selector_3s_reference": selection.score.reference_3s_label,
                "selector_5s_reference": selection.score.reference_5s_label,
                "decision_reason": selection_metadata["decision_reason"],
                "decision_reasons": selection_metadata["decision_reasons"],
                "transfer_legality_gate_applied": selection_metadata["transfer_legality_gate_applied"],
                "transfer_legality_previous_maneuver": selection_metadata["transfer_legality_previous_maneuver"],
                "transfer_legality_reason": selection_metadata["transfer_legality_reason"],
                "transfer_legality_vetoed_tokens": selection_metadata["transfer_legality_vetoed_tokens"],
                "top_candidate_summaries": selection_metadata["top_candidate_summaries"],
                "obstacle_pressure": world_state.obstacle_pressure,
                "route_blockage": world_state.route_blockage,
                "corridor_blocked": world_state.corridor_blocked,
                "left_clearance": world_state.left_clearance,
                "right_clearance": world_state.right_clearance,
                "preferred_escape_side": world_state.preferred_escape_side,
                "alpasim_signal": alpasim_signal,
                "sensor_freshness": sensor_freshness,
            },
            sort_keys=True,
        )
        self._append_prediction_log(
            prediction_input=prediction_input,
            payload={
                "command": command,
                "speed_mps": round(float(speed_mps), 4),
                "selected_maneuver": selection.candidate.name,
                "decision_reason": selection_metadata["decision_reason"],
                "candidate_count": selection.candidate_count,
                "reference_count": selection.reference_count,
                "top_candidate_summaries": selection_metadata["top_candidate_summaries"],
                "alpasim_signal": alpasim_signal,
                "sensor_freshness": sensor_freshness,
                "result": "ok",
            },
        )
        return ModelPrediction(
            trajectory_xy=trajectory_xy,
            headings=headings,
            reasoning_text=reasoning_text,
        )

    def _append_prediction_log(self, *, prediction_input: PredictionInput, payload: dict[str, Any]) -> None:
        if self._log_path is None:
            return
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._prediction_counter += 1
        record = {
            "frame_index": self._prediction_counter,
            "scene_id": _prediction_scene_id(prediction_input),
            **payload,
        }
        with self._log_lock:
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")


class _SensorFreshnessGuard:
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
        fingerprint_value = zlib.crc32(str(image_array.shape).encode("utf-8"), fingerprint_value)
        fingerprint_value = zlib.crc32(str(image_array.dtype).encode("utf-8"), fingerprint_value)
        fingerprint_value = zlib.crc32(memoryview(image_array).cast("B"), fingerprint_value)
        fingerprint = fingerprint_value if fingerprint is None else zlib.crc32(
            fingerprint_value.to_bytes(4, "little", signed=False),
            fingerprint,
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


def _model_cfg_value(model_cfg: Any, key: str, default: Any = None) -> Any:
    if isinstance(model_cfg, dict):
        return model_cfg.get(key, default)
    return getattr(model_cfg, key, default)


def _jsonable_pose_signature(pose: tuple[float, float, float] | None) -> list[float] | None:
    if pose is None:
        return None
    return [float(pose[0]), float(pose[1]), float(pose[2])]


def _prediction_scene_id(prediction_input: Any) -> str | None:
    value = getattr(prediction_input, "scene_id", None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _yaw_from_quat_like(quat: Any) -> float | None:
    if quat is None:
        return None
    z = _first_float_attr(quat, ("z",))
    w = _first_float_attr(quat, ("w",))
    if z is None or w is None:
        return None
    return math.atan2(2.0 * w * z, 1.0 - 2.0 * z * z)


def _pose_changed(previous_pose: tuple[float, float, float], current_pose: tuple[float, float, float]) -> bool:
    dx = abs(current_pose[0] - previous_pose[0])
    dy = abs(current_pose[1] - previous_pose[1])
    dheading = abs(current_pose[2] - previous_pose[2])
    return dx > 0.05 or dy > 0.05 or dheading > 0.01


def _resample_to_frequency(
    trajectory_xy: np.ndarray,
    output_frequency_hz: int,
    horizon_seconds: float,
) -> np.ndarray:
    expected_points = max(1, int(round(output_frequency_hz * horizon_seconds)))
    if expected_points == trajectory_xy.shape[0]:
        return trajectory_xy

    source_t = np.linspace(1.0 / trajectory_xy.shape[0], 1.0, trajectory_xy.shape[0])
    target_t = np.linspace(1.0 / expected_points, 1.0, expected_points)
    x = np.interp(target_t, source_t, trajectory_xy[:, 0])
    y = np.interp(target_t, source_t, trajectory_xy[:, 1])
    return np.stack((x, y), axis=1).astype(np.float32)


def _select_legal_transfer_maneuver(
    scenario: Scenario,
    position: tuple[float, float],
    world_state: Any,
    perception: Any,
    *,
    speed_mps: float,
) -> SpotlightSelection:
    evaluations, reference_count = evaluate_maneuver_candidates(
        scenario,
        position,
        world_state,
        perception,
        speed_mps,
    )
    best = max(
        evaluations,
        key=lambda item: (item.explanation.effective_score, item.candidate.confidence),
    )
    vetoes: list[dict[str, str]] = []
    safe_evaluations = []
    for evaluation in evaluations:
        violation = _transfer_legality_violation(scenario, evaluation)
        if violation is None:
            safe_evaluations.append(evaluation)
        else:
            vetoes.append({"token": evaluation.candidate.name, "reason": violation})

    chosen = best
    legality_applied = False
    legality_reason = "not_required"
    previous_maneuver = best.candidate.name
    if _transfer_legality_violation(scenario, best) is not None:
        legality_applied = True
        legality_reason = "prefer_route_stable_candidate"
        safe_pool = safe_evaluations or [
            evaluation
            for evaluation in evaluations
            if evaluation.candidate.name in SpotlightReflexAlpaSimModel._LEGAL_TOKENS
        ]
        chosen = max(
            safe_pool if safe_pool else evaluations,
            key=_transfer_legality_key,
        )
        if not safe_evaluations:
            legality_reason = "no_route_stable_candidate"

    top_candidate_summaries = tuple(
        {
            **evaluation.explanation.to_summary(),
            "transfer_legal": _transfer_legality_violation(scenario, evaluation) is None,
        }
        for evaluation in sorted(evaluations, key=lambda item: item.explanation.effective_score, reverse=True)[:3]
    )
    metadata = {
        "transfer_legality_gate_applied": legality_applied,
        "transfer_legality_previous_maneuver": previous_maneuver,
        "transfer_legality_reason": legality_reason,
        "transfer_legality_vetoed_tokens": vetoes,
    }
    return SpotlightSelection(
        chosen.candidate,
        chosen.score,
        len(evaluations),
        reference_count,
        chosen.explanation.effective_score,
        chosen.explanation.reasons,
        top_candidate_summaries,
        metadata,
    )


def _transfer_legality_violation(scenario: Scenario, evaluation: Any) -> str | None:
    token = evaluation.candidate.name
    if token not in SpotlightReflexAlpaSimModel._LEGAL_TOKENS:
        return "forbidden_lateral_maneuver"
    if evaluation.explanation.safety_penalty > 0.0:
        return "unsafe_action"
    if not evaluation.score.inside_5s_region:
        return "outside_route_region"
    lane_points = route_centerline(scenario)
    max_allowed = max(0.35, scenario.lane_half_width - SpotlightReflexAlpaSimModel._ROUTE_MARGIN_BUFFER_M)
    start_dev = _route_deviation(scenario.start, lane_points)
    final_dev = _route_deviation(evaluation.candidate.trajectory[-1], lane_points)
    if final_dev > max_allowed:
        return "lane_boundary_cross"
    if final_dev > start_dev + SpotlightReflexAlpaSimModel._MAX_ROUTE_DEVIATION_M:
        return "route_deviation_growth"
    for point in evaluation.candidate.trajectory:
        if _route_deviation(point, lane_points) > max_allowed:
            return "lane_boundary_cross"
    return None


def _route_deviation(point: tuple[float, float], lane_points: list[tuple[float, float]]) -> float:
    _, _, deviation = nearest_lane_point(point, lane_points)
    return float(deviation)


def _transfer_legality_key(evaluation: Any) -> tuple[float, ...]:
    return (
        1.0 if evaluation.score.inside_5s_region else 0.0,
        1.0 if evaluation.score.inside_3s_region else 0.0,
        1.0 if evaluation.candidate.name in SpotlightReflexAlpaSimModel._LEGAL_TOKENS else 0.0,
        -float(evaluation.explanation.near_clearance_penalty),
        float(evaluation.explanation.progress_bonus),
        float(evaluation.explanation.effective_score),
        float(evaluation.candidate.confidence),
    )
