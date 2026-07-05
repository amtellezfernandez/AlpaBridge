from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
from threading import Lock
import time
from typing import Any

import numpy as np

from .alpasim_signal import extract_alpasim_signal, scenario_from_command
from .alpasim_spotlight import (
    BaseTrajectoryModel,
    DriveCommand,
    ModelPrediction,
    PredictionInput,
    _SensorFreshnessGuard,
    _prediction_scene_id,
    _resample_to_frequency,
)
from .alpasim_token_bc import (
    _cfg_value,
    _load_oracle_actor_proxy,
    _nearest_oracle_actor_proxy_frame,
    _oracle_frame_to_current_hazards,
    _prediction_timestamp_us,
)
from .environment import (
    DEFAULT_EGO_RADIUS_M,
    SIM_TICK_DT_S,
    Scenario,
    min_time_swept_clearance,
    nearest_lane_point,
    route_centerline,
    scenario_at_tick,
)


@dataclass(frozen=True)
class DirectPlannerConfig:
    selection_objective: str = "cost"
    horizon_seconds: float = 5.0
    point_count: int = 20
    clearance_target_m: float = 1.25
    lane_margin_buffer_m: float = 0.75
    max_lateral_offset_m: float = 1.5
    max_accel_speed_scale: float = 1.25
    speed_scales: tuple[float, ...] = (0.0, 0.35, 0.55, 0.75, 0.9, 1.05, 1.2)
    lateral_offsets_m: tuple[float, ...] = (-1.5, 0.0, 1.5)
    clearance_samples: int = 1
    clearance_max_depth: int = 0
    clearance_weight: float = 850.0
    collision_weight: float = 15_000.0
    lane_weight: float = 1200.0
    route_weight: float = 12.0
    smoothness_weight: float = 18.0
    lateral_weight: float = 1.5
    progress_weight: float = 1.15
    speed_preference_weight: float = 8.0
    rear_flow_weight: float = 2400.0
    rear_flow_ttc_threshold_s: float = 3.0
    rear_flow_max_gap_m: float = 18.0
    rear_flow_min_closing_mps: float = 0.5
    rear_flow_min_ego_speed_mps: float = 2.0
    rear_flow_lateral_gate_m: float = 3.0


@dataclass(frozen=True)
class DirectPlan:
    trajectory: np.ndarray
    cost: float
    metrics: dict[str, Any]


class DirectActorPlannerAlpaSimModel(BaseTrajectoryModel):
    """Selector-free AlpaSim planner.

    This model bypasses token logits entirely. It samples a small continuous trajectory
    family and minimizes an actor/route/lane/smoothness objective. The intent is an
    experimental bottleneck test: if this reduces the collision surface where the token
    selector did not, the bounded token interface is likely limiting the previous method.
    """

    _DEFAULT_CAMERA_IDS = ["camera_front_wide_120fov"]

    @classmethod
    def from_config(
        cls,
        model_cfg: Any,
        device: Any,
        camera_ids: list[str],
        context_length: int | None,
        output_frequency_hz: int,
    ) -> "DirectActorPlannerAlpaSimModel":
        defaults = DirectPlannerConfig()
        oracle_path = os.getenv(
            "WAYSPAN_DIRECT_PLANNER_ORACLE_ACTOR_PROXY_PATH",
            str(_cfg_value(model_cfg, "oracle_actor_proxy_path", "") or ""),
        ).strip()
        log_path = os.getenv(
            "WAYSPAN_DIRECT_PLANNER_LOG_PATH",
            str(_cfg_value(model_cfg, "selection_log_path", "") or ""),
        ).strip()
        config = DirectPlannerConfig(
            selection_objective=_env_str(
                "WAYSPAN_DIRECT_PLANNER_SELECTION_OBJECTIVE",
                model_cfg,
                "selection_objective",
                defaults.selection_objective,
            ),
            horizon_seconds=_env_float(
                "WAYSPAN_DIRECT_PLANNER_HORIZON_SECONDS",
                model_cfg,
                "horizon_seconds",
                defaults.horizon_seconds,
            ),
            point_count=_env_int("WAYSPAN_DIRECT_PLANNER_POINT_COUNT", model_cfg, "point_count", defaults.point_count),
            clearance_target_m=_env_float(
                "WAYSPAN_DIRECT_PLANNER_CLEARANCE_TARGET_M",
                model_cfg,
                "clearance_target_m",
                defaults.clearance_target_m,
            ),
            lane_margin_buffer_m=_env_float(
                "WAYSPAN_DIRECT_PLANNER_LANE_MARGIN_BUFFER_M",
                model_cfg,
                "lane_margin_buffer_m",
                defaults.lane_margin_buffer_m,
            ),
            max_lateral_offset_m=_env_float(
                "WAYSPAN_DIRECT_PLANNER_MAX_LATERAL_OFFSET_M",
                model_cfg,
                "max_lateral_offset_m",
                defaults.max_lateral_offset_m,
            ),
            max_accel_speed_scale=_env_float(
                "WAYSPAN_DIRECT_PLANNER_MAX_ACCEL_SPEED_SCALE",
                model_cfg,
                "max_accel_speed_scale",
                defaults.max_accel_speed_scale,
            ),
            speed_scales=_float_tuple(
                os.getenv("WAYSPAN_DIRECT_PLANNER_SPEED_SCALES"),
                _cfg_value(model_cfg, "speed_scales", defaults.speed_scales),
            ),
            lateral_offsets_m=_float_tuple(
                os.getenv("WAYSPAN_DIRECT_PLANNER_LATERAL_OFFSETS_M"),
                _cfg_value(model_cfg, "lateral_offsets_m", defaults.lateral_offsets_m),
            ),
            clearance_samples=_env_int(
                "WAYSPAN_DIRECT_PLANNER_CLEARANCE_SAMPLES",
                model_cfg,
                "clearance_samples",
                defaults.clearance_samples,
            ),
            clearance_max_depth=_env_int(
                "WAYSPAN_DIRECT_PLANNER_CLEARANCE_MAX_DEPTH",
                model_cfg,
                "clearance_max_depth",
                defaults.clearance_max_depth,
            ),
            progress_weight=_env_float(
                "WAYSPAN_DIRECT_PLANNER_PROGRESS_WEIGHT",
                model_cfg,
                "progress_weight",
                defaults.progress_weight,
            ),
            speed_preference_weight=_env_float(
                "WAYSPAN_DIRECT_PLANNER_SPEED_PREFERENCE_WEIGHT",
                model_cfg,
                "speed_preference_weight",
                defaults.speed_preference_weight,
            ),
            rear_flow_weight=_env_float(
                "WAYSPAN_DIRECT_PLANNER_REAR_FLOW_WEIGHT",
                model_cfg,
                "rear_flow_weight",
                defaults.rear_flow_weight,
            ),
        )
        _validate_selection_objective(config.selection_objective)
        return cls(
            camera_ids=camera_ids,
            context_length=context_length or 1,
            output_frequency_hz=output_frequency_hz,
            planner_config=config,
            oracle_actor_proxy_path=Path(oracle_path) if oracle_path else None,
            oracle_actor_proxy_tolerance_us=int(
                os.getenv(
                    "WAYSPAN_DIRECT_PLANNER_ORACLE_ACTOR_PROXY_TOLERANCE_US",
                    str(_cfg_value(model_cfg, "oracle_actor_proxy_tolerance_us", 50_000)),
                )
            ),
            log_path=Path(log_path) if log_path else None,
        )

    def __init__(
        self,
        camera_ids: list[str] | None = None,
        context_length: int = 1,
        output_frequency_hz: int = 4,
        planner_config: DirectPlannerConfig | None = None,
        oracle_actor_proxy_path: Path | None = None,
        oracle_actor_proxy_tolerance_us: int = 50_000,
        log_path: Path | None = None,
    ) -> None:
        self._camera_ids = camera_ids or list(self._DEFAULT_CAMERA_IDS)
        self._context_length = int(context_length)
        self._output_frequency_hz = int(output_frequency_hz)
        self._config = planner_config or DirectPlannerConfig()
        self._oracle_actor_proxy_path = oracle_actor_proxy_path
        self._oracle_actor_proxy_frames, self._oracle_actor_proxy_timestamps = _load_oracle_actor_proxy(
            oracle_actor_proxy_path
        )
        self._oracle_actor_proxy_tolerance_us = max(0, int(oracle_actor_proxy_tolerance_us))
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
                    f"DirectActorPlannerAlpaSimModel expects {self._context_length} frame(s) "
                    f"for {camera_id}, got {len(frames)}"
                )
        self._prediction_counter += 1
        command = self._encode_command(prediction_input.command)
        speed_mps = max(0.0, float(prediction_input.speed))
        try:
            sensor_freshness = self._sensor_freshness_guard.validate(prediction_input)
        except RuntimeError as exc:
            self._append_log(
                {
                    "scene_id": _prediction_scene_id(prediction_input),
                    "command": command,
                    "speed_mps": round(float(speed_mps), 4),
                    "result": "sensor_failure",
                    "sensor_error": str(exc),
                    "sensor_freshness": self._sensor_freshness_guard.last_diagnostics(),
                }
            )
            raise
        sensor_signal = extract_alpasim_signal(prediction_input)
        alpasim_signal = self._inject_oracle_actor_proxy(prediction_input, sensor_signal)
        scenario = scenario_at_tick(scenario_from_command(command, alpasim_signal), 0)
        plan_start = time.perf_counter()
        plan = plan_direct_actor_trajectory(scenario, speed_mps=speed_mps, config=self._config)
        planner_latency_ms = (time.perf_counter() - plan_start) * 1000.0
        trajectory_xy = _resample_to_frequency(
            plan.trajectory.astype(np.float32),
            output_frequency_hz=self._output_frequency_hz,
            horizon_seconds=self._config.horizon_seconds,
        )
        headings = self._compute_headings_from_trajectory(trajectory_xy)
        reasoning_payload = {
            "scene_id": _prediction_scene_id(prediction_input),
            "adapter": "wod2sim.simulator.alpasim_direct_actor_planner",
            "command": command,
            "planner": "selector_free_actor_aware_grid",
            "speed_mps": round(speed_mps, 4),
            "oracle_actor_proxy_enabled": self._oracle_actor_proxy_path is not None,
            "oracle_actor_proxy_path": str(self._oracle_actor_proxy_path) if self._oracle_actor_proxy_path else None,
            "alpasim_signal": _compact_signal(alpasim_signal),
            "sensor_freshness": sensor_freshness,
            "planner_latency_ms": round(planner_latency_ms, 3),
            "plan": plan.metrics,
            "result": "ok",
        }
        self._append_log(reasoning_payload)
        return ModelPrediction(
            trajectory_xy=trajectory_xy,
            headings=headings,
            reasoning_text=json.dumps(reasoning_payload, sort_keys=True),
        )

    def _inject_oracle_actor_proxy(
        self,
        prediction_input: PredictionInput,
        alpasim_signal: dict[str, Any],
    ) -> dict[str, Any]:
        if self._oracle_actor_proxy_path is None:
            return alpasim_signal
        requested_timestamp = _prediction_timestamp_us(prediction_input)
        merged = dict(alpasim_signal)
        merged["oracle_actor_proxy_enabled"] = True
        merged["oracle_actor_proxy_path"] = str(self._oracle_actor_proxy_path)
        merged["oracle_actor_proxy_timestamp_us"] = requested_timestamp
        merged["oracle_actor_proxy_hit"] = False
        merged["oracle_actor_proxy_count"] = 0
        merged["oracle_actor_proxy_delta_us"] = None
        merged["oracle_actor_proxy_matched_timestamp_us"] = None
        if requested_timestamp is None:
            merged["oracle_actor_proxy_miss_reason"] = "missing_prediction_timestamp"
            return merged
        frame = _nearest_oracle_actor_proxy_frame(
            self._oracle_actor_proxy_frames,
            self._oracle_actor_proxy_timestamps,
            requested_timestamp,
            tolerance_us=self._oracle_actor_proxy_tolerance_us,
        )
        if frame is None:
            merged["oracle_actor_proxy_miss_reason"] = "timestamp_not_found"
            return merged
        hazards, transform_info = _oracle_frame_to_current_hazards(frame, prediction_input)
        if hazards is None:
            merged["oracle_actor_proxy_miss_reason"] = transform_info["miss_reason"]
            merged["oracle_actor_proxy_frame_space"] = transform_info["frame_space"]
            return merged
        matched_timestamp = int(frame.get("timestamp_us", requested_timestamp))
        merged["structured_hazards"] = list(alpasim_signal.get("structured_hazards", [])) + hazards
        merged["oracle_actor_proxy_hit"] = True
        merged["oracle_actor_proxy_count"] = len(hazards)
        merged["oracle_actor_proxy_world_actor_count"] = int(transform_info.get("world_actor_count", 0))
        merged["oracle_actor_proxy_delta_us"] = abs(matched_timestamp - requested_timestamp)
        merged["oracle_actor_proxy_matched_timestamp_us"] = matched_timestamp
        merged["oracle_actor_proxy_scene_id"] = frame.get("scene_id")
        merged["oracle_actor_proxy_frame_space"] = transform_info["frame_space"]
        merged["oracle_actor_proxy_current_ego_pose"] = transform_info.get("current_ego_pose")
        return merged

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


def plan_direct_actor_trajectory(
    scenario: Scenario,
    *,
    speed_mps: float,
    config: DirectPlannerConfig | None = None,
) -> DirectPlan:
    config = config or DirectPlannerConfig()
    _validate_selection_objective(config.selection_objective)
    best: DirectPlan | None = None
    best_key: tuple[float, ...] | None = None
    candidate_count = 0
    speed_scales = tuple(
        scale for scale in config.speed_scales if 0.0 <= scale <= max(0.0, config.max_accel_speed_scale)
    )
    lateral_offsets = tuple(
        max(-config.max_lateral_offset_m, min(config.max_lateral_offset_m, offset))
        for offset in config.lateral_offsets_m
    )
    for speed_scale in speed_scales:
        for lateral_offset in lateral_offsets:
            candidate_count += 1
            trajectory = _candidate_trajectory(
                scenario,
                speed_mps=speed_mps,
                speed_scale=speed_scale,
                lateral_offset_m=lateral_offset,
                config=config,
            )
            cost, metrics = _trajectory_cost(
                trajectory,
                scenario=scenario,
                speed_mps=speed_mps,
                speed_scale=speed_scale,
                lateral_offset_m=lateral_offset,
                config=config,
            )
            plan = DirectPlan(trajectory=trajectory, cost=cost, metrics=metrics)
            key = _plan_rank_key(plan, config=config)
            if best is None or best_key is None or key > best_key:
                best = plan
                best_key = key
    if best is None:
        candidate_count += 1
        trajectory = _candidate_trajectory(
            scenario,
            speed_mps=speed_mps,
            speed_scale=0.0,
            lateral_offset_m=0.0,
            config=config,
        )
        cost, metrics = _trajectory_cost(
            trajectory,
            scenario=scenario,
            speed_mps=speed_mps,
            speed_scale=0.0,
            lateral_offset_m=0.0,
            config=config,
        )
        best = DirectPlan(trajectory=trajectory, cost=cost, metrics=metrics)
    best.metrics["candidate_count"] = candidate_count
    best.metrics["selection_objective"] = config.selection_objective
    return best


def _validate_selection_objective(selection_objective: str) -> None:
    if selection_objective not in {"cost", "max_clearance"}:
        raise ValueError("selection_objective must be one of: cost, max_clearance")


def _plan_rank_key(plan: DirectPlan, *, config: DirectPlannerConfig) -> tuple[float, ...]:
    min_clearance = _metric_float(plan.metrics.get("min_clearance_m"))
    progress = _metric_float(plan.metrics.get("progress_m"))
    lane_violation = _metric_float(plan.metrics.get("lane_violation_mean_sq"))
    route_deviation = _metric_float(plan.metrics.get("max_route_deviation_m"))
    if config.selection_objective == "max_clearance":
        return (
            min_clearance,
            progress,
            -lane_violation,
            -route_deviation,
            -float(plan.cost),
        )
    return (-float(plan.cost), min_clearance, progress)


def _candidate_trajectory(
    scenario: Scenario,
    *,
    speed_mps: float,
    speed_scale: float,
    lateral_offset_m: float,
    config: DirectPlannerConfig,
) -> np.ndarray:
    point_count = max(2, int(config.point_count))
    horizon = max(0.5, float(config.horizon_seconds))
    if speed_scale <= 1e-6:
        final_x = max(0.5, min(2.0, speed_mps * 0.15))
    else:
        final_x = max(2.0, speed_mps * horizon * speed_scale)
    points: list[tuple[float, float]] = []
    for index in range(1, point_count + 1):
        t = index / point_count
        x = final_x * _smoothstep(t)
        route_y = _route_y_at_x(route_centerline(scenario, samples_per_segment=8), x)
        lateral_profile = _smoothstep(t)
        y = route_y + lateral_offset_m * lateral_profile
        points.append((x, y))
    return np.asarray(points, dtype=np.float32)


def _trajectory_cost(
    trajectory: np.ndarray,
    *,
    scenario: Scenario,
    speed_mps: float,
    speed_scale: float,
    lateral_offset_m: float,
    config: DirectPlannerConfig,
) -> tuple[float, dict[str, Any]]:
    lane_points = route_centerline(scenario)
    min_clearance = math.inf
    route_sq = 0.0
    lane_violation_sq = 0.0
    max_route_deviation = 0.0
    previous = scenario.start
    point_count = len(trajectory)
    horizon_ticks = config.horizon_seconds / SIM_TICK_DT_S
    for index, point_array in enumerate(trajectory):
        point = (float(point_array[0]), float(point_array[1]))
        start_tick = (index / point_count) * horizon_ticks
        end_tick = ((index + 1) / point_count) * horizon_ticks
        clearance = min_time_swept_clearance(
            scenario,
            previous,
            point,
            start_tick,
            end_tick,
            samples=max(1, int(config.clearance_samples)),
            max_depth=max(0, int(config.clearance_max_depth)),
            ego_radius=DEFAULT_EGO_RADIUS_M,
        )
        min_clearance = min(min_clearance, clearance)
        _, _, route_deviation = nearest_lane_point(point, lane_points)
        max_route_deviation = max(max_route_deviation, route_deviation)
        route_sq += route_deviation * route_deviation
        lane_over = max(
            0.0,
            route_deviation - max(0.1, scenario.lane_half_width - config.lane_margin_buffer_m),
        )
        lane_violation_sq += lane_over * lane_over
        previous = point

    clearance_shortfall = max(0.0, config.clearance_target_m - min_clearance)
    collision_shortfall = max(0.0, -min_clearance)
    smoothness = _smoothness_cost(trajectory)
    lateral_cost = float(np.mean(np.square(trajectory[:, 1]))) if len(trajectory) else 0.0
    progress = float(trajectory[-1, 0]) if len(trajectory) else 0.0
    candidate_mean_speed_mps = progress / max(0.1, float(config.horizon_seconds))
    speed_preference = max(0.0, 1.0 - float(speed_scale)) ** 2
    rear_flow = _rear_flow_metrics(
        scenario,
        lane_points=lane_points,
        speed_mps=speed_mps,
        candidate_mean_speed_mps=candidate_mean_speed_mps,
        config=config,
    )
    route_mean_sq = route_sq / max(1, point_count)
    lane_mean_sq = lane_violation_sq / max(1, point_count)
    cost = (
        config.clearance_weight * clearance_shortfall * clearance_shortfall
        + config.collision_weight * collision_shortfall * collision_shortfall
        + config.lane_weight * lane_mean_sq
        + config.route_weight * route_mean_sq
        + config.smoothness_weight * smoothness
        + config.lateral_weight * lateral_cost
        + config.speed_preference_weight * speed_preference
        + config.rear_flow_weight * float(rear_flow["rear_flow_penalty"])
        - config.progress_weight * progress
    )
    metrics = {
        "cost": round(float(cost), 4),
        "speed_scale": round(float(speed_scale), 4),
        "lateral_offset_m": round(float(lateral_offset_m), 4),
        "min_clearance_m": _round_metric(min_clearance),
        "clearance_target_m": round(float(config.clearance_target_m), 4),
        "max_route_deviation_m": round(float(max_route_deviation), 4),
        "route_mean_sq": round(float(route_mean_sq), 4),
        "lane_violation_mean_sq": round(float(lane_mean_sq), 4),
        "smoothness_cost": round(float(smoothness), 4),
        "progress_m": round(float(progress), 4),
        "candidate_mean_speed_mps": round(float(candidate_mean_speed_mps), 4),
        "speed_preference_cost": round(float(speed_preference), 4),
        "rear_actor_count": rear_flow["rear_actor_count"],
        "rear_closing_actor_count": rear_flow["rear_closing_actor_count"],
        "rear_flow_gap_m": _round_metric(float(rear_flow["rear_flow_gap_m"])),
        "rear_flow_ttc_s": _round_metric(float(rear_flow["rear_flow_ttc_s"])),
        "rear_flow_penalty": round(float(rear_flow["rear_flow_penalty"]), 4),
        "actor_count": len(scenario.actors),
        "obstacle_count": len(scenario.obstacles),
        "lane_half_width_m": round(float(scenario.lane_half_width), 4),
    }
    return float(cost), metrics


def _smoothness_cost(trajectory: np.ndarray) -> float:
    if len(trajectory) < 3:
        return 0.0
    second = trajectory[2:] - 2.0 * trajectory[1:-1] + trajectory[:-2]
    return float(np.mean(np.sum(np.square(second), axis=1)))


def _rear_flow_metrics(
    scenario: Scenario,
    *,
    lane_points: list[tuple[float, float]],
    speed_mps: float,
    candidate_mean_speed_mps: float,
    config: DirectPlannerConfig,
) -> dict[str, float | int]:
    route_tangent = _route_tangent_at_point(scenario.start, lane_points)
    route_left = (-route_tangent[1], route_tangent[0])
    lateral_gate = min(
        max(1.5, float(scenario.lane_half_width) + 0.25),
        float(config.rear_flow_lateral_gate_m),
    )
    rear_actor_count = 0
    rear_closing_actor_count = 0
    min_gap = math.inf
    min_ttc = math.inf
    for actor in scenario.actors:
        dx = float(actor.x) - float(scenario.start[0])
        dy = float(actor.y) - float(scenario.start[1])
        longitudinal = dx * route_tangent[0] + dy * route_tangent[1]
        lateral = dx * route_left[0] + dy * route_left[1]
        if longitudinal >= -0.5 or abs(lateral) > lateral_gate:
            continue
        gap = max(0.0, -longitudinal - float(actor.length) * 0.5 - DEFAULT_EGO_RADIUS_M)
        if gap > float(config.rear_flow_max_gap_m):
            continue
        rear_actor_count += 1
        min_gap = min(min_gap, gap)
        rel_forward_speed = float(actor.vx) * route_tangent[0] + float(actor.vy) * route_tangent[1]
        candidate_closing_speed = float(speed_mps) + rel_forward_speed - float(candidate_mean_speed_mps)
        if candidate_closing_speed < float(config.rear_flow_min_closing_mps):
            continue
        rear_closing_actor_count += 1
        min_ttc = min(min_ttc, gap / max(candidate_closing_speed, 1e-6))
    active = (
        float(speed_mps) >= float(config.rear_flow_min_ego_speed_mps)
        and rear_closing_actor_count > 0
        and min_ttc <= float(config.rear_flow_ttc_threshold_s)
    )
    shortfall = 0.0
    if active:
        shortfall = max(0.0, float(config.rear_flow_ttc_threshold_s) - min_ttc) / max(
            1e-6,
            float(config.rear_flow_ttc_threshold_s),
        )
    return {
        "rear_actor_count": rear_actor_count,
        "rear_closing_actor_count": rear_closing_actor_count,
        "rear_flow_gap_m": min_gap,
        "rear_flow_ttc_s": min_ttc,
        "rear_flow_penalty": shortfall * shortfall,
    }


def _route_tangent_at_point(
    point: tuple[float, float],
    lane_points: list[tuple[float, float]],
) -> tuple[float, float]:
    if len(lane_points) < 2:
        return (1.0, 0.0)
    index, _, _ = nearest_lane_point(point, lane_points)
    if index <= 0:
        start, end = lane_points[0], lane_points[1]
    elif index >= len(lane_points) - 1:
        start, end = lane_points[-2], lane_points[-1]
    else:
        start, end = lane_points[index - 1], lane_points[index + 1]
    return _normalize_pair((end[0] - start[0], end[1] - start[1]))


def _normalize_pair(vector: tuple[float, float]) -> tuple[float, float]:
    norm = math.hypot(float(vector[0]), float(vector[1]))
    if norm <= 1e-9:
        return (1.0, 0.0)
    return (float(vector[0]) / norm, float(vector[1]) / norm)


def _route_y_at_x(lane_center: list[tuple[float, float]], x: float) -> float:
    if not lane_center:
        return 0.0
    points = sorted(lane_center, key=lambda item: item[0])
    if x <= points[0][0]:
        return float(points[0][1])
    for first, second in zip(points, points[1:]):
        if first[0] <= x <= second[0]:
            dx = second[0] - first[0]
            if abs(dx) < 1e-6:
                return float(second[1])
            t = (x - first[0]) / dx
            return float(first[1] + (second[1] - first[1]) * t)
    return float(points[-1][1])


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, float(t)))
    return t * t * (3.0 - 2.0 * t)


def _float_tuple(raw: Any, default: Any) -> tuple[float, ...]:
    if raw is None or raw == "":
        raw = default
    if isinstance(raw, str):
        values = [item.strip() for item in raw.split(",") if item.strip()]
    else:
        values = list(raw)
    parsed = tuple(float(value) for value in values)
    if not parsed:
        return tuple(float(value) for value in default)
    return parsed


def _env_float(env_name: str, model_cfg: Any, key: str, default: float) -> float:
    raw = os.getenv(env_name)
    if raw is None:
        raw = _cfg_value(model_cfg, key, default)
    return float(raw)


def _env_int(env_name: str, model_cfg: Any, key: str, default: int) -> int:
    raw = os.getenv(env_name)
    if raw is None:
        raw = _cfg_value(model_cfg, key, default)
    return int(raw)


def _env_str(env_name: str, model_cfg: Any, key: str, default: str) -> str:
    raw = os.getenv(env_name)
    if raw is None:
        raw = _cfg_value(model_cfg, key, default)
    return str(raw)


def _metric_float(value: Any) -> float:
    if value == "inf":
        return math.inf
    if value == "-inf":
        return -math.inf
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _compact_signal(signal: dict[str, Any]) -> dict[str, Any]:
    return {
        "structured_hazard_count": len(signal.get("structured_hazards", []) or []),
        "route_waypoint_count": len(signal.get("route_waypoints", []) or []),
        "visibility_risk": signal.get("visibility_risk"),
        "dynamics_risk": signal.get("dynamics_risk"),
        "oracle_actor_proxy_enabled": signal.get("oracle_actor_proxy_enabled", False),
        "oracle_actor_proxy_hit": signal.get("oracle_actor_proxy_hit", False),
        "oracle_actor_proxy_count": signal.get("oracle_actor_proxy_count", 0),
        "oracle_actor_proxy_delta_us": signal.get("oracle_actor_proxy_delta_us"),
        "oracle_actor_proxy_scene_id": signal.get("oracle_actor_proxy_scene_id"),
    }


def _round_metric(value: float) -> float | str:
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return round(float(value), 4)
