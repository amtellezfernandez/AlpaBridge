"""Model-predictive-style planner: forward-simulates several candidate
control sequences through a simple ego dynamics model and selects the
lowest-cost rollout, using only real-time signal already available to every
other model here - no privileged/oracle actor state, no learned checkpoint.

This is a genuinely different "how does the action get decided" shape than
the other built-ins:

- ``constant_velocity``/``route_following`` are closed-form kinematics with
  no search at all;
- ``direct_actor_planner`` blends a small family of preset geometric paths
  (speed-scale x lateral-offset) and checks them against ground-truth actor
  state it is given out of band;
- ``token_dagger_bc``/``vavam`` are a single reactive forward pass through a
  learned checkpoint.

This one instead forward-simulates its own short-horizon dynamics model for
each candidate (yaw_rate, acceleration) pair - an "imagined future" per
candidate, not a static geometric blend - scores each rollout against a
route/hazard/speed/smoothness cost computed from the same real-time
``alpasignal`` every other model here already receives, and returns the
lowest-cost rollout. That "propagate a dynamics model forward, score the
imagined futures, act on the best one" pattern is the same one MPC and
model-based planning share, without needing a learned world model or
privileged data to demonstrate it.
"""

from __future__ import annotations

import json
import math
import os
import time
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
    prediction_runtime_metadata,
    prediction_scene_id,
    resample_trajectory,
)
from .alpasim_signal import (
    extract_alpasim_signal,
    filtered_route_points,
    signal_actors,
    signal_obstacles,
)
from .baseline_drivers import _cfg_float, _cfg_int, _cfg_value, _encode_command
from .environment import Actor, Obstacle, segment_point_distance


@dataclass(frozen=True)
class MPCPlannerConfig:
    horizon_seconds: float = 5.0
    point_count: int = 20
    max_speed_mps: float = 12.0
    target_cruise_speed_mps: float = 8.0
    command_lateral_goal_m: float = 16.0
    ego_radius_m: float = 1.1
    min_clearance_m: float = 2.0
    yaw_rates_rps: tuple[float, ...] = (-0.35, -0.18, 0.0, 0.18, 0.35)
    accels_mps2: tuple[float, ...] = (-2.5, -1.0, 0.0, 1.0, 1.5)
    route_weight: float = 6.0
    clearance_weight: float = 60.0
    collision_weight: float = 4000.0
    speed_weight: float = 3.0
    smoothness_weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.yaw_rates_rps or not self.accels_mps2:
            raise ValueError(
                "MPCPlannerConfig.yaw_rates_rps and accels_mps2 must each have at "
                "least one candidate - an empty set leaves _select_candidate with "
                "no rollout to choose from."
            )


class MPCPlannerAlpaSimModel(BaseTrajectoryModel):
    """Selects an action by forward-simulating and scoring candidate
    control sequences - a small, real MPC-style planner, not a learned
    policy and not a privileged one."""

    _DEFAULT_CAMERA_IDS = ["camera_front_wide_120fov"]

    @classmethod
    def from_config(
        cls,
        model_cfg: Any,
        device: Any,
        camera_ids: list[str],
        context_length: int | None,
        output_frequency_hz: int,
    ) -> "MPCPlannerAlpaSimModel":
        defaults = MPCPlannerConfig()
        config = MPCPlannerConfig(
            horizon_seconds=_cfg_float(model_cfg, "horizon_seconds", defaults.horizon_seconds),
            point_count=_cfg_int(
                model_cfg, "point_count", int(round(output_frequency_hz * defaults.horizon_seconds))
            ),
            max_speed_mps=_cfg_float(model_cfg, "max_speed_mps", defaults.max_speed_mps),
            target_cruise_speed_mps=_cfg_float(
                model_cfg, "target_cruise_speed_mps", defaults.target_cruise_speed_mps
            ),
        )
        log_path = os.getenv(
            "ALPABRIDGE_MPC_PLANNER_LOG_PATH",
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
        config: MPCPlannerConfig | None = None,
        log_path: Path | None = None,
    ) -> None:
        self._camera_ids = camera_ids or list(self._DEFAULT_CAMERA_IDS)
        self._context_length = int(context_length)
        self._output_frequency_hz = int(output_frequency_hz)
        self._config = config or MPCPlannerConfig()
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
        command = self._encode_command(prediction_input.command)
        speed_mps = corrected_speed_mps(prediction_input)
        try:
            sensor_freshness = self._sensor_freshness_guard.validate(prediction_input)
        except RuntimeError as exc:
            self._append_log(
                {
                    "scene_id": prediction_scene_id(prediction_input),
                    **prediction_runtime_metadata(prediction_input),
                    "adapter": "alpabridge.simulator.mpc_planner",
                    "command": command,
                    "speed_mps": round(float(speed_mps), 4),
                    "result": "sensor_failure",
                    "sensor_error": str(exc),
                    "sensor_freshness": self._sensor_freshness_guard.last_diagnostics(),
                }
            )
            raise

        signal = extract_alpasim_signal(prediction_input)
        route_points = filtered_route_points(signal["route_waypoints"])
        obstacles = signal_obstacles(signal)
        actors = signal_actors(signal)

        plan_start = time.perf_counter()
        best_points, best_yaw_rate, best_accel, best_cost = _select_candidate(
            speed_mps=speed_mps,
            command=command,
            route_points=route_points,
            obstacles=obstacles,
            actors=actors,
            config=self._config,
        )
        planner_latency_ms = (time.perf_counter() - plan_start) * 1000.0

        trajectory_xy = resample_trajectory(
            np.asarray(best_points, dtype=np.float32),
            output_frequency_hz=self._output_frequency_hz,
            horizon_seconds=self._config.horizon_seconds,
        )
        headings = self._compute_headings_from_trajectory(trajectory_xy)
        payload = {
            "scene_id": prediction_scene_id(prediction_input),
            **prediction_runtime_metadata(prediction_input),
            "adapter": "alpabridge.simulator.mpc_planner",
            "planner": "candidate_rollout_mpc",
            "command": command,
            "speed_mps": round(speed_mps, 4),
            "route_source": signal.get("route_source"),
            "route_waypoint_count": signal.get("route_waypoint_count"),
            "obstacle_count": len(obstacles),
            "actor_count": len(actors),
            "chosen_yaw_rate_rps": round(best_yaw_rate, 4),
            "chosen_accel_mps2": round(best_accel, 4),
            "chosen_cost": round(best_cost, 4),
            "planner_latency_ms": round(planner_latency_ms, 3),
            "sensor_freshness": sensor_freshness,
            "result": "ok",
        }
        self._append_log(payload)
        return ModelPrediction(
            trajectory_xy=trajectory_xy,
            headings=headings,
            reasoning_text=json.dumps(payload, sort_keys=True),
        )

    def _append_log(self, payload: dict[str, Any]) -> None:
        if self._log_path is None:
            return
        record = {"frame_index": self._prediction_counter, **payload}
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_lock:
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")


def _select_candidate(
    *,
    speed_mps: float,
    command: str,
    route_points: list[tuple[float, float]],
    obstacles: list[Obstacle],
    actors: list[Actor],
    config: MPCPlannerConfig,
) -> tuple[list[tuple[float, float]], float, float, float]:
    dt = config.horizon_seconds / max(1, config.point_count)
    lateral_goal_m = {
        "left": config.command_lateral_goal_m,
        "straight": 0.0,
        "right": -config.command_lateral_goal_m,
    }[command]

    best: tuple[float, list[tuple[float, float]], float, float] | None = None
    for yaw_rate in config.yaw_rates_rps:
        for accel in config.accels_mps2:
            points, speeds = _rollout_candidate(
                yaw_rate=yaw_rate,
                accel=accel,
                speed0=speed_mps,
                dt=dt,
                point_count=config.point_count,
                max_speed_mps=config.max_speed_mps,
            )
            cost = _candidate_cost(
                points=points,
                speeds=speeds,
                dt=dt,
                yaw_rate=yaw_rate,
                accel=accel,
                route_points=route_points,
                lateral_goal_m=lateral_goal_m,
                obstacles=obstacles,
                actors=actors,
                config=config,
            )
            if best is None or cost < best[0]:
                best = (cost, points, yaw_rate, accel)

    assert best is not None
    cost, points, yaw_rate, accel = best
    return points, yaw_rate, accel, cost


def _rollout_candidate(
    *,
    yaw_rate: float,
    accel: float,
    speed0: float,
    dt: float,
    point_count: int,
    max_speed_mps: float,
) -> tuple[list[tuple[float, float]], list[float]]:
    """Forward-simulate a unicycle model under a held-constant control - the
    "imagined future" for this candidate, not a static geometric shape."""
    x = y = heading = 0.0
    speed = speed0
    points: list[tuple[float, float]] = []
    speeds: list[float] = []
    for _ in range(max(1, point_count)):
        speed = min(max_speed_mps, max(0.0, speed + accel * dt))
        heading = heading + yaw_rate * dt
        x = x + speed * math.cos(heading) * dt
        y = y + speed * math.sin(heading) * dt
        points.append((x, y))
        speeds.append(speed)
    return points, speeds


def _distance_to_polyline(
    point: tuple[float, float], polyline: list[tuple[float, float]]
) -> float:
    """Perpendicular (segment-clamped) distance from ``point`` to the
    nearest segment of ``polyline`` - not the nearest discrete vertex, which
    would overstate the distance for any point between two sparse
    waypoints."""
    return min(
        segment_point_distance(polyline[index], polyline[index + 1], point)
        for index in range(len(polyline) - 1)
    )


def _candidate_cost(
    *,
    points: list[tuple[float, float]],
    speeds: list[float],
    dt: float,
    yaw_rate: float,
    accel: float,
    route_points: list[tuple[float, float]],
    lateral_goal_m: float,
    obstacles: list[Obstacle],
    actors: list[Actor],
    config: MPCPlannerConfig,
) -> float:
    if len(route_points) >= 2:
        tracking_cost = sum(
            _distance_to_polyline(point, route_points) ** 2 for point in points
        ) / len(points)
    else:
        tracking_cost = (points[-1][1] - lateral_goal_m) ** 2

    hazard_soft = 0.0
    hazard_violations = 0.0
    for step_index, point in enumerate(points):
        elapsed_s = (step_index + 1) * dt
        for obstacle in obstacles:
            clearance = (
                math.hypot(point[0] - obstacle.x, point[1] - obstacle.y)
                - obstacle.radius
                - config.ego_radius_m
            )
            if clearance < config.min_clearance_m:
                hazard_soft += config.min_clearance_m - clearance
            if clearance < 0.0:
                hazard_violations += 1.0
        for actor in actors:
            actor_x = actor.x + actor.vx * elapsed_s
            actor_y = actor.y + actor.vy * elapsed_s
            clearance = (
                math.hypot(point[0] - actor_x, point[1] - actor_y)
                - actor.radius
                - config.ego_radius_m
            )
            if clearance < config.min_clearance_m:
                hazard_soft += config.min_clearance_m - clearance
            if clearance < 0.0:
                hazard_violations += 1.0
    hazard_cost = config.clearance_weight * hazard_soft + config.collision_weight * hazard_violations

    speed_cost = sum((speed - config.target_cruise_speed_mps) ** 2 for speed in speeds) / len(speeds)
    smoothness_cost = (yaw_rate**2) * 4.0 + (accel / 3.0) ** 2

    return (
        config.route_weight * tracking_cost
        + hazard_cost
        + config.speed_weight * speed_cost
        + config.smoothness_weight * smoothness_cost
    )
