from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np

from .alpasim_contract import (
    BaseTrajectoryModel,
    DriveCommand,
    ModelPrediction,
    PredictionInput,
    SensorFreshnessGuard,
    corrected_speed_mps,
    make_model_prediction,
    prediction_runtime_metadata,
    prediction_scene_id,
    resample_trajectory,
)
from .alpasim_signal import (
    extract_alpasim_signal,
    filtered_route_points,
    route_waypoints_from_input,
)


@dataclass(frozen=True)
class BaselineDriverConfig:
    horizon_seconds: float = 5.0
    point_count: int = 20


_ROUTE_CONTRACT_MODE_ENV = "ALPABRIDGE_ROUTE_CONTRACT_MODE"


class _BaselineDriverModel(BaseTrajectoryModel):
    _DEFAULT_CAMERA_IDS = ["camera_front_wide_120fov"]
    _BASELINE_NAME = "baseline"

    @classmethod
    def from_config(
        cls,
        model_cfg: Any,
        device: Any,
        camera_ids: list[str],
        context_length: int | None,
        output_frequency_hz: int,
    ) -> "_BaselineDriverModel":
        config = BaselineDriverConfig(
            horizon_seconds=_cfg_float(model_cfg, "horizon_seconds", 5.0),
            point_count=_cfg_int(model_cfg, "point_count", int(round(output_frequency_hz * 5.0))),
        )
        log_path = os.getenv(
            "ALPABRIDGE_BASELINE_LOG_PATH",
            str(_cfg_value(model_cfg, "selection_log_path", "") or ""),
        ).strip()
        return cls(
            camera_ids=camera_ids,
            context_length=context_length or 1,
            output_frequency_hz=output_frequency_hz,
            config=config,
            log_path=Path(log_path) if log_path else None,
        )

    def __init__(
        self,
        *,
        camera_ids: list[str] | None = None,
        context_length: int = 1,
        output_frequency_hz: int = 4,
        config: BaselineDriverConfig | None = None,
        log_path: Path | None = None,
    ) -> None:
        self._camera_ids = camera_ids or list(self._DEFAULT_CAMERA_IDS)
        self._context_length = int(context_length)
        self._output_frequency_hz = int(output_frequency_hz)
        self._config = config or BaselineDriverConfig()
        self._log_path = log_path
        self._log_lock = Lock()
        self._prediction_counter = 0
        self._sensor_freshness_guard = SensorFreshnessGuard(self.__class__.__name__)

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
        return _encode_command(command)

    def predict(self, prediction_input: PredictionInput) -> ModelPrediction:
        self._validate_cameras(prediction_input.camera_images)
        for camera_id, frames in prediction_input.camera_images.items():
            if len(frames) != self._context_length:
                raise ValueError(
                    f"{self.__class__.__name__} expects {self._context_length} frame(s) "
                    f"for {camera_id}, got {len(frames)}"
                )
        self._prediction_counter += 1
        speed_mps = _input_speed_mps(prediction_input)
        try:
            sensor_freshness = self._sensor_freshness_guard.validate(prediction_input)
        except RuntimeError as exc:
            self._append_log(
                {
                    "scene_id": prediction_scene_id(prediction_input),
                    **prediction_runtime_metadata(prediction_input),
                    "baseline": self._BASELINE_NAME,
                    "command": _input_command(prediction_input),
                    "speed_mps": round(speed_mps, 4),
            "reported_speed_mps": round(_reported_speed_mps(prediction_input), 4),
                    "result": "sensor_failure",
                    "sensor_error": str(exc),
                    "sensor_freshness": self._sensor_freshness_guard.last_diagnostics(),
                }
            )
            raise
        route_contract_mode = _route_contract_mode()
        contract_input = _prediction_input_for_route_contract(prediction_input, route_contract_mode)
        alpasim_signal = extract_alpasim_signal(contract_input)
        trajectory = self._trajectory(contract_input)
        headings = self._compute_headings_from_trajectory(trajectory)
        payload = {
            "scene_id": prediction_scene_id(prediction_input),
            **prediction_runtime_metadata(prediction_input),
            "adapter": "alpabridge.simulator.baseline_drivers",
            "baseline": self._BASELINE_NAME,
            "route_contract_mode": route_contract_mode,
            "command": _input_command(prediction_input),
            "speed_mps": round(speed_mps, 4),
            "reported_speed_mps": round(_reported_speed_mps(prediction_input), 4),
            "alpasim_signal": alpasim_signal,
            "route_source": alpasim_signal.get("route_source"),
            "route_waypoint_count": alpasim_signal.get("route_waypoint_count"),
            "sensor_freshness": sensor_freshness,
            "result": "ok",
        }
        self._append_log(payload)
        return make_model_prediction(
            trajectory_xy=trajectory,
            headings=headings,
            reasoning_text=json.dumps(payload, sort_keys=True),
        )

    def _trajectory(self, prediction_input: PredictionInput) -> np.ndarray:
        raise NotImplementedError

    def _point_count(self) -> int:
        return max(1, int(self._config.point_count))

    def _horizon_seconds(self) -> float:
        return max(0.1, float(self._config.horizon_seconds))

    def _append_log(self, payload: dict[str, Any]) -> None:
        if self._log_path is None:
            return
        record = {
            "frame_index": self._prediction_counter,
            **payload,
        }
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_lock:
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")


class ConstantVelocityAlpaSimModel(_BaselineDriverModel):
    """Straight-line constant-velocity baseline for closed-loop sanity checks."""

    _BASELINE_NAME = "constant_velocity"

    def _trajectory(self, prediction_input: PredictionInput) -> np.ndarray:
        trajectory = _straight_trajectory(
            speed_mps=_input_speed_mps(prediction_input),
            horizon_seconds=self._horizon_seconds(),
            point_count=self._point_count(),
        )
        return resample_trajectory(trajectory, self._output_frequency_hz, self._horizon_seconds())


class RouteFollowingAlpaSimModel(_BaselineDriverModel):
    """Follow supplied route waypoints without learned policy logits."""

    _BASELINE_NAME = "route_following"

    def _trajectory(self, prediction_input: PredictionInput) -> np.ndarray:
        speed_mps = _input_speed_mps(prediction_input)
        route_points = _route_points(prediction_input)
        if len(route_points) < 2:
            trajectory = _straight_trajectory(
                speed_mps=speed_mps,
                horizon_seconds=self._horizon_seconds(),
                point_count=self._point_count(),
            )
        else:
            env_target, _ = _ramp_settings()
            trajectory = _sample_route(
                route_points,
                speed_mps=speed_mps,
                horizon_seconds=self._horizon_seconds(),
                point_count=self._point_count(),
                target_speed_override_mps=_ramp_up_only(
                    effective_ramp_target_mps(
                        getattr(prediction_input, "reference_speed_mps", None),
                        target_speed_mps=env_target,
                        scale=_ramp_scale(),
                    ),
                    current_speed_mps=speed_mps,
                ),
            )
        return resample_trajectory(trajectory, self._output_frequency_hz, self._horizon_seconds())


def _route_points(prediction_input: PredictionInput) -> list[tuple[float, float]]:
    return filtered_route_points(route_waypoints_from_input(prediction_input))


class _CommandOnlyRoutePredictionInput:
    _ROUTE_ATTRS = {"route_waypoints", "route_path", "navigation_waypoints", "route"}

    def __init__(self, source: PredictionInput) -> None:
        self._source = source

    def __getattr__(self, name: str) -> Any:
        if name in self._ROUTE_ATTRS:
            return []
        return getattr(self._source, name)


def _prediction_input_for_route_contract(
    prediction_input: PredictionInput, route_contract_mode: str
) -> PredictionInput:
    if route_contract_mode == "command_only_route":
        return _CommandOnlyRoutePredictionInput(prediction_input)  # type: ignore[return-value]
    return prediction_input


def _route_contract_mode() -> str:
    raw_value = os.getenv(_ROUTE_CONTRACT_MODE_ENV, "full_contract").strip().lower()
    if raw_value in {"", "full", "full_contract"}:
        return "full_contract"
    if raw_value in {"command_only", "command_only_route"}:
        return "command_only_route"
    raise ValueError(
        f"{_ROUTE_CONTRACT_MODE_ENV} must be full_contract or command_only_route; "
        f"got {raw_value!r}"
    )


def _ramped_distances(
    times_s: np.ndarray,
    *,
    speed_mps: float,
    target_speed_mps: float,
    accel_mps2: float,
) -> np.ndarray:
    """Distance along the path at each time under a capped linear speed ramp.

    With the ramp disabled (target <= 0) this is exactly ``t * v0``, the
    historical constant-speed profile. Otherwise speed moves from ``v0`` toward
    the target at ``accel_mps2`` (either direction) and holds there:
    closed-form integration of a trapezoidal speed profile.
    """
    v0 = max(0.0, speed_mps)
    if target_speed_mps <= 0.0 or accel_mps2 <= 0.0 or abs(target_speed_mps - v0) < 1e-9:
        return times_s * v0
    vt = max(0.0, target_speed_mps)
    a = accel_mps2 if vt > v0 else -accel_mps2
    t_ramp = (vt - v0) / a
    ramp = times_s <= t_ramp
    distances = np.empty_like(times_s)
    distances[ramp] = v0 * times_s[ramp] + 0.5 * a * times_s[ramp] ** 2
    d_ramp_end = v0 * t_ramp + 0.5 * a * t_ramp**2
    distances[~ramp] = d_ramp_end + vt * (times_s[~ramp] - t_ramp)
    return distances


def _ramp_settings() -> tuple[float, float]:
    """Target speed and acceleration for the route follower's speed ramp.

    Disabled by default (target 0), which reproduces the historical
    constant-speed behaviour byte for byte. The environment is the only
    configuration surface the standalone gRPC driver has.
    """
    try:
        target = float(os.environ.get("ALPABRIDGE_RF_TARGET_SPEED_MPS", "0") or 0.0)
    except ValueError:
        target = 0.0
    try:
        accel = float(os.environ.get("ALPABRIDGE_RF_ACCEL_MPS2", "1.5") or 1.5)
    except ValueError:
        accel = 1.5
    if not (math.isfinite(target) and math.isfinite(accel)):
        return 0.0, 1.5
    return max(0.0, target), max(0.0, accel)


def _ramp_scale() -> float:
    """Multiplier on the session's warmup reference speed, 0 = disabled.

    An absolute target ramps a scene the human drove at 3.7 m/s to the same
    9 m/s as one driven at 8.5, and the slow scene is slow for a reason. The
    scale anchors the target to the human's own warmup pace instead; when both
    the scale and the absolute target are set, the tighter one wins.
    """
    try:
        scale = float(os.environ.get("ALPABRIDGE_RF_TARGET_SPEED_SCALE", "0") or 0.0)
    except ValueError:
        return 0.0
    if not math.isfinite(scale) or scale <= 0.0:
        return 0.0
    return scale


def effective_ramp_target_mps(
    reference_speed_mps: float | None,
    *,
    target_speed_mps: float,
    scale: float,
) -> float:
    """Combine the absolute target with the scaled per-scene reference.

    Returns the absolute target untouched when the scale is unusable, so
    behaviour without the scale is unchanged. With only the scale, the target
    is scale x reference. With both, the tighter bound wins - the scale exists
    to stop the absolute target from tripling the pace of a slow scene.
    """
    scaled = 0.0
    if scale > 0.0 and reference_speed_mps and math.isfinite(reference_speed_mps):
        scaled = scale * max(0.0, reference_speed_mps)
    if scaled <= 0.0:
        return target_speed_mps
    if target_speed_mps <= 0.0:
        return scaled
    return min(target_speed_mps, scaled)


def _ramp_up_only(target_speed_mps: float, *, current_speed_mps: float) -> float:
    """Disable the ramp instead of letting it brake.

    Measured: a scene launched at ~20 m/s scored a perfect 1.0 with the stock
    constant-speed sampler, and 0.5692 when a 9 m/s target dragged it down -
    braking pushed it 4 m off the reference and the record truncated. The ramp
    exists to lift a speed-locked launch, so a target at or below the current
    speed reverts to the historical behaviour rather than becoming a brake.
    """
    if 0.0 < target_speed_mps <= max(0.0, current_speed_mps):
        return 0.0
    return target_speed_mps


def _sample_route(
    points: list[tuple[float, float]],
    *,
    speed_mps: float,
    horizon_seconds: float,
    point_count: int,
    target_speed_override_mps: float | None = None,
) -> np.ndarray:
    segment_lengths = [
        math.dist(points[index], points[index + 1]) for index in range(len(points) - 1)
    ]
    total_length = sum(segment_lengths)
    if total_length <= 1e-6:
        return _straight_trajectory(
            speed_mps=speed_mps,
            horizon_seconds=horizon_seconds,
            point_count=point_count,
        )

    cumulative = [0.0]
    for length in segment_lengths:
        cumulative.append(cumulative[-1] + length)
    times_s = np.linspace(
        horizon_seconds / point_count,
        horizon_seconds,
        point_count,
        dtype=np.float64,
    )
    # The historical sampler multiplied this grid by the current speed, which
    # locks the launch speed in for the whole rollout. The ramp (opt-in)
    # accelerates toward a target speed instead.
    target_speed_mps, accel_mps2 = _ramp_settings()
    if target_speed_override_mps is not None:
        target_speed_mps = target_speed_override_mps
    target_distances = _ramped_distances(
        times_s,
        speed_mps=speed_mps,
        target_speed_mps=target_speed_mps,
        accel_mps2=accel_mps2,
    ).astype(np.float32)
    samples = [_point_at_distance(points, cumulative, float(distance)) for distance in target_distances]
    return np.asarray(samples, dtype=np.float32)


def _point_at_distance(
    points: list[tuple[float, float]],
    cumulative: list[float],
    distance_m: float,
) -> tuple[float, float]:
    if distance_m <= 0.0:
        return points[0]
    total_length = cumulative[-1]
    if distance_m >= total_length:
        start = points[-2]
        end = points[-1]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = max(1e-6, math.hypot(dx, dy))
        extra = distance_m - total_length
        return (end[0] + extra * dx / length, end[1] + extra * dy / length)
    for index in range(len(cumulative) - 1):
        if cumulative[index + 1] < distance_m:
            continue
        start = points[index]
        end = points[index + 1]
        length = max(1e-6, cumulative[index + 1] - cumulative[index])
        alpha = (distance_m - cumulative[index]) / length
        return (start[0] + alpha * (end[0] - start[0]), start[1] + alpha * (end[1] - start[1]))
    return points[-1]


def _straight_trajectory(
    *,
    speed_mps: float,
    horizon_seconds: float,
    point_count: int,
) -> np.ndarray:
    times = np.linspace(horizon_seconds / point_count, horizon_seconds, point_count, dtype=np.float32)
    x = times * max(0.0, speed_mps)
    y = np.zeros_like(x)
    return np.stack((x, y), axis=1).astype(np.float32)


def _reported_speed_mps(prediction_input: PredictionInput) -> float:
    """The speed AlpaSim reported, before any pose-derived correction.

    Logged next to the corrected value so it is visible whether the fallback in
    `corrected_speed_mps` actually fired on a given frame. Without this the two are
    indistinguishable in telemetry, so an upstream fix to the reported value -- or a
    regression in it -- looks identical to the fallback quietly compensating.
    """
    return max(0.0, float(getattr(prediction_input, "speed", 0.0) or 0.0))


def _input_speed_mps(prediction_input: PredictionInput) -> float:
    # Uses corrected_speed_mps rather than prediction_input.speed directly:
    # AlpaSim's own EgoDriverService._get_speed_and_acceleration can report a
    # stale/lagging DynamicState as a dead stop for the first ~1s of a real
    # rollout even while ego_pose_history shows genuine motion (confirmed
    # directly against real telemetry: ~10 m/s of real pose displacement
    # reading as speed_mps=0.0 for the first several frames of a session).
    # Without this, constant_velocity/route_following would forward-simulate
    # standing still during exactly that window.
    try:
        speed = corrected_speed_mps(prediction_input)
    except (TypeError, ValueError):
        return 0.0
    return speed if math.isfinite(speed) and speed > 0.0 else 0.0


def _input_command(prediction_input: PredictionInput) -> str:
    return _encode_command(getattr(prediction_input, "command", None))


def _encode_command(command: Any) -> str:
    command_map = {
        DriveCommand.LEFT: "left",
        DriveCommand.STRAIGHT: "straight",
        DriveCommand.RIGHT: "right",
        DriveCommand.UNKNOWN: "straight",
        0: "left",
        1: "straight",
        2: "right",
        3: "straight",
    }
    if command in command_map:
        return command_map[command]
    name = getattr(command, "name", None)
    if isinstance(name, str):
        value = name.lower()
        return "straight" if value == "unknown" else value
    return str(command) if command not in (None, "") else "unknown"


def _cfg_float(model_cfg: Any, key: str, default: float) -> float:
    value = _cfg_value(model_cfg, key, default)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _cfg_int(model_cfg: Any, key: str, default: int) -> int:
    value = _cfg_value(model_cfg, key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _cfg_value(model_cfg: Any, key: str, default: Any) -> Any:
    if isinstance(model_cfg, dict):
        return model_cfg.get(key, default)
    return getattr(model_cfg, key, default)
