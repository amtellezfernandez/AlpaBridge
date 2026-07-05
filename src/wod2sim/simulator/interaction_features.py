from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .environment import DEFAULT_EGO_RADIUS_M, SIM_TICK_DT_S, Scenario, actor_to_obstacle_at_time, point_clearance


INTERACTION_FEATURE_NAMES = (
    "min_dynamic_clearance_m",
    "time_to_closest_approach_s",
    "closest_longitudinal_m",
    "closest_lateral_m",
    "relative_speed_mps",
    "crossing_relation",
    "dynamic_actor_present",
)


@dataclass(frozen=True)
class CandidateInteractionSummary:
    min_dynamic_clearance_m: float
    time_to_closest_approach_s: float
    closest_longitudinal_m: float
    closest_lateral_m: float
    relative_speed_mps: float
    crossing_relation: float
    dynamic_actor_present: float

    def as_array(self) -> np.ndarray:
        return np.array(
            [
                self.min_dynamic_clearance_m,
                self.time_to_closest_approach_s,
                self.closest_longitudinal_m,
                self.closest_lateral_m,
                self.relative_speed_mps,
                self.crossing_relation,
                self.dynamic_actor_present,
            ],
            dtype=np.float32,
        )


def candidate_interaction_features(
    scenario: Scenario,
    position: tuple[float, float],
    trajectory: list[tuple[float, float]],
    *,
    point_limit: int,
    horizon_seconds: float,
    ego_radius: float = DEFAULT_EGO_RADIUS_M,
) -> np.ndarray:
    return summarize_candidate_interaction(
        scenario,
        position,
        trajectory,
        point_limit=point_limit,
        horizon_seconds=horizon_seconds,
        ego_radius=ego_radius,
    ).as_array()


def summarize_candidate_interaction(
    scenario: Scenario,
    position: tuple[float, float],
    trajectory: list[tuple[float, float]],
    *,
    point_limit: int,
    horizon_seconds: float,
    ego_radius: float = DEFAULT_EGO_RADIUS_M,
) -> CandidateInteractionSummary:
    if not scenario.actors:
        return CandidateInteractionSummary(20.0, horizon_seconds, 0.0, 0.0, 0.0, 0.0, 0.0)

    points = _capped_points(position, trajectory, point_limit=point_limit)
    if len(points) <= 1:
        return CandidateInteractionSummary(20.0, horizon_seconds, 0.0, 0.0, 0.0, 0.0, 0.0)

    dt_s = max(horizon_seconds / max(point_limit, 1), 1e-3)
    best_clearance = math.inf
    best_time_s = horizon_seconds
    best_longitudinal = 0.0
    best_lateral = 0.0
    best_rel_speed = 0.0
    best_crossing_relation = 0.0
    actor_present = False

    for idx, point in enumerate(points[1:], start=1):
        prev = points[idx - 1]
        elapsed_s = idx * dt_s
        time_index = elapsed_s / SIM_TICK_DT_S
        seg = (point[0] - prev[0], point[1] - prev[1])
        seg_norm = math.hypot(*seg)
        if seg_norm > 1e-6:
            forward = (seg[0] / seg_norm, seg[1] / seg_norm)
        else:
            forward = (1.0, 0.0)
        left = (-forward[1], forward[0])
        ego_speed = seg_norm / dt_s

        for actor in scenario.actors:
            obstacle = actor_to_obstacle_at_time(actor, time_index)
            if obstacle is None:
                continue
            actor_present = True
            clearance = point_clearance(point, obstacle) - ego_radius
            if clearance >= best_clearance:
                continue
            offset = (obstacle.x - point[0], obstacle.y - point[1])
            best_clearance = clearance
            best_time_s = elapsed_s
            best_longitudinal = offset[0] * forward[0] + offset[1] * forward[1]
            best_lateral = offset[0] * left[0] + offset[1] * left[1]
            actor_speed = math.hypot(actor.vx, actor.vy)
            actor_vel = _normalized_velocity(actor)
            rel_vx = ego_speed * forward[0] - actor_speed * actor_vel[0]
            rel_vy = ego_speed * forward[1] - actor_speed * actor_vel[1]
            best_rel_speed = math.hypot(rel_vx, rel_vy)
            if abs(best_lateral) <= max(1.5, obstacle.radius * 1.2):
                best_crossing_relation = 1.0 if best_longitudinal >= 0.0 else -1.0
            else:
                best_crossing_relation = 0.0

    if not actor_present:
        return CandidateInteractionSummary(20.0, horizon_seconds, 0.0, 0.0, 0.0, 0.0, 0.0)

    return CandidateInteractionSummary(
        min_dynamic_clearance_m=float(best_clearance),
        time_to_closest_approach_s=float(best_time_s),
        closest_longitudinal_m=float(best_longitudinal),
        closest_lateral_m=float(best_lateral),
        relative_speed_mps=float(best_rel_speed),
        crossing_relation=float(best_crossing_relation),
        dynamic_actor_present=1.0,
    )


def _capped_points(
    position: tuple[float, float],
    trajectory: list[tuple[float, float]],
    *,
    point_limit: int,
) -> list[tuple[float, float]]:
    if point_limit <= 0:
        return [position]
    points = [position]
    capped = list(trajectory[:point_limit])
    if not capped:
        points.append(position)
        return points
    points.extend(capped)
    if len(capped) < point_limit:
        points.extend([capped[-1]] * (point_limit - len(capped)))
    return points


def _normalized_velocity(actor) -> tuple[float, float]:
    speed = math.hypot(actor.vx, actor.vy)
    if speed > 1e-6:
        return (actor.vx / speed, actor.vy / speed)
    return (math.cos(actor.heading), math.sin(actor.heading))
