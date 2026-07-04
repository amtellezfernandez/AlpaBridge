from __future__ import annotations

from dataclasses import dataclass
import math

from .environment import Scenario, route_centerline
from .perception import ScenePerception, perceived_obstacle_axis_extent


@dataclass
class WorldState:
    position: tuple[float, float]
    target_point: tuple[float, float]
    progress_fraction: float
    collision_risk: float
    goal_distance: float
    uncertainty: float
    nearest_obstacle_distance: float = math.inf
    obstacle_pressure: float = 0.0
    route_blockage: float = 0.0
    corridor_blocked: bool = False
    left_clearance: float = math.inf
    right_clearance: float = math.inf
    preferred_escape_side: str = "balanced"


def update_world_state(
    scenario: Scenario,
    position: tuple[float, float],
    perception: ScenePerception,
    lookahead: int = 12,
) -> WorldState:
    lane_points = route_centerline(scenario)
    target_index = min(len(lane_points) - 1, perception.lane_index + lookahead)
    target_point = lane_points[target_index]
    progress_fraction = target_index / max(1, len(lane_points) - 1)
    goal_distance = math.dist(position, scenario.goal)

    nearest_signed_distance = min(
        (obstacle.signed_distance for obstacle in perception.visible_obstacles),
        default=20.0,
    )
    collision_risk = max(0.0, min(1.0, (5.0 - nearest_signed_distance) / 5.0))
    geometry = _label_free_geometry_summary(scenario, position, perception)

    return WorldState(
        position=position,
        target_point=target_point,
        progress_fraction=progress_fraction,
        collision_risk=collision_risk,
        goal_distance=goal_distance,
        uncertainty=perception.uncertainty,
        nearest_obstacle_distance=nearest_signed_distance,
        obstacle_pressure=geometry["obstacle_pressure"],
        route_blockage=geometry["route_blockage"],
        corridor_blocked=bool(geometry["corridor_blocked"]),
        left_clearance=geometry["left_clearance"],
        right_clearance=geometry["right_clearance"],
        preferred_escape_side=str(geometry["preferred_escape_side"]),
    )


def _label_free_geometry_summary(
    scenario: Scenario,
    position: tuple[float, float],
    perception: ScenePerception,
) -> dict[str, float | str | bool]:
    """Summarize local occupancy from geometry only, ignoring scenario labels."""

    heading = _normalize(perception.lane_heading)
    if heading == (0.0, 0.0):
        target = (scenario.goal[0] - position[0], scenario.goal[1] - position[1])
        heading = _normalize(target)
    if heading == (0.0, 0.0):
        heading = (1.0, 0.0)
    left = (-heading[1], heading[0])

    left_clearance = math.inf
    right_clearance = math.inf
    route_blockage = 0.0
    nearest_signed_distance = min(
        (obstacle.signed_distance for obstacle in perception.visible_obstacles),
        default=20.0,
    )
    obstacle_pressure = max(0.0, min(1.0, (10.0 - nearest_signed_distance) / 10.0))

    for obstacle in perception.visible_obstacles:
        dx = obstacle.x - position[0]
        dy = obstacle.y - position[1]
        forward_distance = dx * heading[0] + dy * heading[1]
        lateral_distance = dx * left[0] + dy * left[1]
        clearance = obstacle.signed_distance
        forward_extent = perceived_obstacle_axis_extent(obstacle, heading)
        lateral_extent = perceived_obstacle_axis_extent(obstacle, left)
        if lateral_distance >= 0.0:
            left_clearance = min(left_clearance, clearance)
        else:
            right_clearance = min(right_clearance, clearance)
        if forward_distance >= -forward_extent and abs(lateral_distance) <= scenario.lane_half_width + lateral_extent:
            forward_pressure = max(0.0, min(1.0, (12.0 - forward_distance) / 12.0))
            lateral_intrusion = max(
                0.0,
                min(
                    1.0,
                    (scenario.lane_half_width + lateral_extent - abs(lateral_distance)) / scenario.lane_half_width,
                ),
            )
            route_blockage = max(route_blockage, forward_pressure * lateral_intrusion)

    if math.isinf(left_clearance) and math.isinf(right_clearance):
        preferred_escape_side = "balanced"
    elif left_clearance > right_clearance + 0.25:
        preferred_escape_side = "left"
    elif right_clearance > left_clearance + 0.25:
        preferred_escape_side = "right"
    else:
        preferred_escape_side = "balanced"

    visibility_horizon_m = 20.0

    return {
        "nearest_obstacle_distance": nearest_signed_distance,
        "obstacle_pressure": obstacle_pressure,
        "route_blockage": route_blockage,
        "corridor_blocked": route_blockage >= 0.45,
        "left_clearance": visibility_horizon_m if math.isinf(left_clearance) else left_clearance,
        "right_clearance": visibility_horizon_m if math.isinf(right_clearance) else right_clearance,
        "preferred_escape_side": preferred_escape_side,
    }


def _normalize(vector: tuple[float, float]) -> tuple[float, float]:
    norm = math.hypot(vector[0], vector[1])
    if norm == 0.0:
        return (0.0, 0.0)
    return (vector[0] / norm, vector[1] / norm)
