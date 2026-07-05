from __future__ import annotations

from dataclasses import dataclass
import math

from .perception import ScenePerception, perceived_obstacle_signed_distance
from .planner import PlannedAction
from .world_model import WorldState


@dataclass
class SafeAction:
    direction: tuple[float, float]
    speed: float
    mode: str
    intervention: bool


def apply_safety_filter(action: PlannedAction, world_state: WorldState, perception: ScenePerception) -> SafeAction:
    if world_state.collision_risk > 0.985:
        if perception.visible_obstacles:
            return SafeAction(
                direction=_risk_escape_direction(world_state, perception, action),
                speed=min(max(action.speed, 1.15), 1.15),
                mode="emergency_escape",
                intervention=True,
            )
        return SafeAction(direction=(0.0, 0.0), speed=0.0, mode="emergency_stop", intervention=True)

    if world_state.collision_risk > 0.80 and perception.uncertainty > 0.55:
        return SafeAction(
            direction=_risk_escape_direction(world_state, perception, action),
            speed=min(max(action.speed, 0.70), 0.70),
            mode="risk_escape",
            intervention=True,
        )

    if world_state.collision_risk > 0.55 and perception.uncertainty > 0.48 and perception.visible_obstacles:
        return SafeAction(
            direction=_risk_escape_direction(world_state, perception, action),
            speed=min(max(action.speed, 0.45), 0.45),
            mode="risk_nudge",
            intervention=True,
        )

    if "evasive" in action.mode and perception.visible_obstacles and (
        world_state.collision_risk > 0.10 or perception.uncertainty > 0.35
    ):
        return SafeAction(
            direction=action.direction,
            speed=min(action.speed, 0.85),
            mode="guarded_evasive",
            intervention=True,
        )

    if world_state.collision_risk > 0.65 and perception.uncertainty > 0.65:
        risk_span = max(1e-6, 0.80 - 0.65)
        risk_fraction = max(0.0, min(1.0, (world_state.collision_risk - 0.65) / risk_span))
        creep_speed = 0.45 - risk_fraction * 0.30
        return SafeAction(
            direction=action.direction,
            speed=min(action.speed, max(0.15, creep_speed)),
            mode="risk_creep",
            intervention=True,
        )

    if perception.uncertainty > 0.78:
        return SafeAction(
            direction=action.direction,
            speed=min(action.speed, 0.5),
            mode="cautious_follow",
            intervention=True,
        )

    if perception.corridor_margin < 0.45:
        return SafeAction(
            direction=_recovery_direction(world_state, perception),
            speed=min(max(action.speed, 1.15), 1.15),
            mode="lane_recovery",
            intervention=True,
        )

    return SafeAction(direction=action.direction, speed=action.speed, mode=action.mode, intervention=False)


def _recovery_direction(world_state: WorldState, perception: ScenePerception) -> tuple[float, float]:
    target_vector = (
        world_state.target_point[0] - world_state.position[0],
        world_state.target_point[1] - world_state.position[1],
    )
    target_direction = _normalize(target_vector)
    if target_direction != (0.0, 0.0):
        return target_direction
    return perception.lane_heading


def _risk_escape_direction(
    world_state: WorldState,
    perception: ScenePerception,
    action: PlannedAction,
) -> tuple[float, float]:
    if not perception.visible_obstacles:
        return _recovery_direction(world_state, perception)
    nearest = min(perception.visible_obstacles, key=lambda obstacle: obstacle.signed_distance)
    away = _normalize((world_state.position[0] - nearest.x, world_state.position[1] - nearest.y))
    if away == (0.0, 0.0):
        return _recovery_direction(world_state, perception)
    recovery = _recovery_direction(world_state, perception)
    target_direction = _target_direction(world_state)
    candidates = [
        away,
        _normalize((away[1], -away[0])),
        _normalize((-away[1], away[0])),
        recovery,
        action.direction,
        perception.lane_heading,
        (-target_direction[0], -target_direction[1]),
    ]
    return max(
        (candidate for candidate in candidates if candidate != (0.0, 0.0)),
        key=lambda candidate: (
            _predicted_visible_clearance(world_state, perception, candidate, 0.70),
            _target_progress(world_state, candidate),
        ),
        default=away,
    )


def _predicted_visible_clearance(
    world_state: WorldState,
    perception: ScenePerception,
    direction: tuple[float, float],
    speed: float,
) -> float:
    next_position = (
        world_state.position[0] + direction[0] * speed,
        world_state.position[1] + direction[1] * speed,
    )
    return min(
        perceived_obstacle_signed_distance(next_position, obstacle)
        for obstacle in perception.visible_obstacles
    )


def _target_progress(world_state: WorldState, direction: tuple[float, float]) -> float:
    target_direction = _target_direction(world_state)
    return direction[0] * target_direction[0] + direction[1] * target_direction[1]


def _target_direction(world_state: WorldState) -> tuple[float, float]:
    target_direction = _normalize(
        (
            world_state.target_point[0] - world_state.position[0],
            world_state.target_point[1] - world_state.position[1],
        )
    )
    return target_direction


def _normalize(vector: tuple[float, float]) -> tuple[float, float]:
    norm = math.hypot(vector[0], vector[1])
    if norm == 0.0:
        return (0.0, 0.0)
    return (vector[0] / norm, vector[1] / norm)
