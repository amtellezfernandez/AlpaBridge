from __future__ import annotations

import math
from typing import Any

import numpy as np

try:  # Optional: available only inside a NAVSIM devkit environment.
    from navsim.agents.abstract_agent import AbstractAgent
    from navsim.common.dataclasses import AgentInput, SensorConfig, Trajectory
    from nuplan.planning.simulation.trajectory.trajectory_sampling import TrajectorySampling
except ModuleNotFoundError:  # pragma: no cover - exercised only when NAVSIM is installed.
    AbstractAgent = object  # type: ignore[assignment,misc]
    AgentInput = Any  # type: ignore[misc,assignment]
    SensorConfig = None  # type: ignore[assignment]
    Trajectory = None  # type: ignore[assignment]
    TrajectorySampling = None  # type: ignore[assignment]


NAVSIM_AGENT_VARIANTS = ("raw", "clamped", "hard_veto", "source_decay")


class ManeuverTokenNavsimAgent(AbstractAgent):  # type: ignore[misc,valid-type]
    """NAVSIM adapter for the deterministic ManeuverToken intervention matrix.

    This agent deliberately uses only ego status and route command so it can run on
    NAVSIM's public non-reactive metric surface without privileged scene access.
    """

    requires_scene = False

    def __init__(
        self,
        variant: str = "raw",
        trajectory_sampling: Any = None,
    ) -> None:
        if variant not in NAVSIM_AGENT_VARIANTS:
            valid = ", ".join(NAVSIM_AGENT_VARIANTS)
            raise ValueError(f"unknown NAVSIM ManeuverToken variant {variant!r}; expected one of: {valid}")
        if TrajectorySampling is None:
            self._trajectory_sampling = _FallbackSampling()
        else:
            self._trajectory_sampling = trajectory_sampling or TrajectorySampling(time_horizon=4, interval_length=0.5)
            super().__init__(self._trajectory_sampling)
        self.variant = variant

    def name(self) -> str:
        return f"ManeuverTokenNavsimAgent_{self.variant}"

    def initialize(self) -> None:
        return None

    def get_sensor_config(self) -> Any:
        if SensorConfig is None:
            raise RuntimeError("NAVSIM is not installed; SensorConfig is unavailable")
        return SensorConfig.build_no_sensors()

    def compute_trajectory(self, agent_input: AgentInput) -> Any:
        if Trajectory is None:
            raise RuntimeError("NAVSIM is not installed; cannot construct navsim Trajectory")
        ego_status = agent_input.ego_statuses[-1]
        speed_mps = _ego_speed_mps(ego_status)
        command = _command_from_status(ego_status)
        poses = navsim_maneuver_token_poses(
            speed_mps=speed_mps,
            command=command,
            variant=self.variant,
            num_poses=int(self._trajectory_sampling.num_poses),
            interval_length_s=float(self._trajectory_sampling.interval_length),
        )
        return Trajectory(poses, self._trajectory_sampling)


def navsim_maneuver_token_poses(
    *,
    speed_mps: float,
    command: str,
    variant: str,
    num_poses: int,
    interval_length_s: float,
) -> np.ndarray:
    """Generate local NAVSIM `(x, y, heading)` poses for one intervention variant."""

    if variant not in NAVSIM_AGENT_VARIANTS:
        valid = ", ".join(NAVSIM_AGENT_VARIANTS)
        raise ValueError(f"unknown NAVSIM ManeuverToken variant {variant!r}; expected one of: {valid}")
    speed_scale, lateral_goal = _variant_controls(speed_mps=speed_mps, command=command, variant=variant)
    forward_speed = max(0.0, speed_mps * speed_scale)
    poses = []
    previous_x = 0.0
    previous_y = 0.0
    for index in range(num_poses):
        t = (index + 1) * interval_length_s
        horizon_ratio = (index + 1) / max(1, num_poses)
        x = forward_speed * t
        y = lateral_goal * _smoothstep(horizon_ratio)
        heading = math.atan2(y - previous_y, max(1e-6, x - previous_x))
        poses.append((x, y, heading))
        previous_x = x
        previous_y = y
    return np.asarray(poses, dtype=np.float32)


def _variant_controls(*, speed_mps: float, command: str, variant: str) -> tuple[float, float]:
    route_lateral = {"left": 2.2, "straight": 0.0, "right": -2.2, "unknown": 0.0}[command]
    if variant == "raw":
        return 1.0, route_lateral
    if variant == "clamped":
        return 0.95, max(-1.2, min(1.2, route_lateral))
    if variant == "hard_veto":
        if speed_mps < 0.8:
            return 0.0, 0.0
        return 0.65, max(-0.9, min(0.9, route_lateral))
    if variant == "source_decay":
        return 0.82, route_lateral * 0.55
    raise AssertionError(variant)


def _ego_speed_mps(ego_status: Any) -> float:
    velocity = np.asarray(getattr(ego_status, "ego_velocity", [0.0, 0.0]), dtype=np.float32)
    if velocity.size < 2:
        return 0.0
    return float(np.linalg.norm(velocity[:2]))


def _command_from_status(ego_status: Any) -> str:
    command = np.asarray(getattr(ego_status, "driving_command", []))
    if command.size < 3:
        return "straight"
    index = int(np.argmax(command))
    return {0: "left", 1: "straight", 2: "right"}.get(index, "unknown")


def _smoothstep(value: float) -> float:
    x = max(0.0, min(1.0, value))
    return x * x * (3.0 - 2.0 * x)


class _FallbackSampling:
    num_poses = 8
    interval_length = 0.5
