from __future__ import annotations

from dataclasses import dataclass
import math

from .perception import ScenePerception, perceived_obstacle_signed_distance
from .world_model import WorldState


@dataclass
class PlannedAction:
    direction: tuple[float, float]
    speed: float
    mode: str
    score: float


def _normalize(vector: tuple[float, float]) -> tuple[float, float]:
    norm = math.hypot(vector[0], vector[1])
    if norm == 0:
        return (0.0, 0.0)
    return (vector[0] / norm, vector[1] / norm)


def _rotate(vector: tuple[float, float], angle_radians: float) -> tuple[float, float]:
    c = math.cos(angle_radians)
    s = math.sin(angle_radians)
    return (vector[0] * c - vector[1] * s, vector[0] * s + vector[1] * c)


def _repulsion_vector(position: tuple[float, float], perception: ScenePerception) -> tuple[float, float]:
    total_x = 0.0
    total_y = 0.0
    for obstacle in perception.visible_obstacles:
        dx = position[0] - obstacle.x
        dy = position[1] - obstacle.y
        direction = _normalize((dx, dy))
        strength = max(0.0, min(1.0, (9.0 - obstacle.signed_distance) / 9.0))
        total_x += direction[0] * strength
        total_y += direction[1] * strength
    return total_x, total_y


def _score_direction(
    position: tuple[float, float],
    direction: tuple[float, float],
    step_size: float,
    target_point: tuple[float, float],
    perception: ScenePerception,
) -> float:
    proposed = (position[0] + direction[0] * step_size, position[1] + direction[1] * step_size)
    progress_term = -math.dist(proposed, target_point)
    lane_term = -math.dist(proposed, perception.lane_point) * 0.35
    obstacle_term = 0.0

    for obstacle in perception.visible_obstacles:
        signed_distance = perceived_obstacle_signed_distance(proposed, obstacle)
        if signed_distance < 0.0:
            return -1e9
        obstacle_term += min(4.0, signed_distance) * 0.25

    return progress_term + lane_term + obstacle_term


def plan_action(
    position: tuple[float, float],
    world_state: WorldState,
    perception: ScenePerception,
    nominal_step_size: float = 1.25,
) -> PlannedAction:
    target_direction = _normalize(
        (
            world_state.target_point[0] - position[0],
            world_state.target_point[1] - position[1],
        )
    )
    if target_direction == (0.0, 0.0):
        target_direction = perception.lane_heading

    repulse_x, repulse_y = _repulsion_vector(position, perception)
    guided_direction = _normalize(
        (
            target_direction[0] + repulse_x * 1.35 + perception.lane_heading[0] * 0.2,
            target_direction[1] + repulse_y * 1.35 + perception.lane_heading[1] * 0.2,
        )
    )
    if guided_direction == (0.0, 0.0):
        guided_direction = target_direction

    candidate_angles = (-1.15, -0.7, -0.35, -0.15, 0.0, 0.15, 0.35, 0.7, 1.15)
    best_direction = target_direction
    best_score = -1e18
    for angle in candidate_angles:
        direction = _normalize(_rotate(guided_direction, angle))
        score = _score_direction(position, direction, nominal_step_size, world_state.target_point, perception)
        if score > best_score:
            best_score = score
            best_direction = direction

    speed = nominal_step_size * max(0.4, 1.0 - world_state.collision_risk * 0.45 - world_state.uncertainty * 0.25)
    return PlannedAction(direction=best_direction, speed=speed, mode="planned", score=best_score)
