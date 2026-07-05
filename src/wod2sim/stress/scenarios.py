from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Iterable

from wod2sim.simulator.environment import Actor, Obstacle, Scenario
from wod2sim.simulator.wod_scenarios import WOD_E2E_CLUSTERS, generate_wod_scenario

SIM_TICK_DT_S = 0.25
NOMINAL_EGO_APPROACH_MPS = 4.4


@dataclass(frozen=True)
class StressLevel:
    name: str
    trigger_offset_ticks: int
    actor_speed_scale: float
    lateral_tightening: float
    obstacle_pressure_scale: float


STRESS_LEVELS: dict[str, StressLevel] = {
    "debug": StressLevel("debug", trigger_offset_ticks=4, actor_speed_scale=0.92, lateral_tightening=0.82, obstacle_pressure_scale=0.85),
    "stress": StressLevel("stress", trigger_offset_ticks=0, actor_speed_scale=1.0, lateral_tightening=1.0, obstacle_pressure_scale=1.0),
    "audit": StressLevel("audit", trigger_offset_ticks=-3, actor_speed_scale=1.12, lateral_tightening=1.18, obstacle_pressure_scale=1.18),
}


def generate_internal_stress_scenario(
    cluster: str,
    seed: int,
    level: str = "audit",
    width: float = 120.0,
    height: float = 80.0,
) -> Scenario:
    if cluster not in WOD_E2E_CLUSTERS:
        valid = ", ".join(WOD_E2E_CLUSTERS)
        raise ValueError(f"unknown WOD cluster {cluster!r}; expected one of: {valid}")
    if level not in STRESS_LEVELS:
        valid = ", ".join(sorted(STRESS_LEVELS))
        raise ValueError(f"unknown stress level {level!r}; expected one of: {valid}")

    scenario = generate_wod_scenario(cluster, seed, width=width, height=height)
    stress_level = STRESS_LEVELS[level]
    conflict_point = _cluster_conflict_point(scenario)
    ego_arrival_tick = _estimate_ego_arrival_tick(scenario, conflict_point)
    actors = _retime_actors(scenario, stress_level, ego_arrival_tick, conflict_point)
    obstacles = _tighten_obstacles(scenario, stress_level, conflict_point)
    tags = {
        **scenario.tags,
        "stress_level": stress_level.name,
        "stress_conflict_point": [round(conflict_point[0], 3), round(conflict_point[1], 3)],
        "ego_relative_trigger_tick": ego_arrival_tick,
        "generator": "internal_stress_v1",
        "source_generator": scenario.tags.get("generator", "wod_e2e_procedural_v1"),
    }
    return replace(scenario, actors=actors, obstacles=obstacles, tags=tags)


def _cluster_conflict_point(scenario: Scenario) -> tuple[float, float]:
    if scenario.cluster in {"intersection", "pedestrian", "cyclist", "spotlight", "foreign object debris", "cut-in"}:
        return scenario.lane_center[3]
    if scenario.cluster in {"construction", "single-lane maneuver", "special vehicle"}:
        return scenario.lane_center[4]
    return scenario.lane_center[min(4, len(scenario.lane_center) - 1)]


def _estimate_ego_arrival_tick(scenario: Scenario, conflict_point: tuple[float, float]) -> int:
    lane = scenario.lane_center
    start = scenario.start
    lane_distance_m = max(0.0, conflict_point[0] - start[0])
    curvature_penalty = sum(abs(b[1] - a[1]) for a, b in zip(lane, lane[1:])) * 0.08
    trigger_time_s = max(0.0, (lane_distance_m + curvature_penalty - 7.5) / NOMINAL_EGO_APPROACH_MPS)
    return max(0, int(round(trigger_time_s / SIM_TICK_DT_S)))


def _retime_actors(
    scenario: Scenario,
    stress_level: StressLevel,
    ego_arrival_tick: int,
    conflict_point: tuple[float, float],
) -> list[Actor]:
    actors: list[Actor] = []
    half_width = scenario.lane_half_width
    for actor in scenario.actors:
        active_from = actor.active_from
        active_until = actor.active_until
        speed = actor.speed
        x = actor.x
        y = actor.y
        heading = actor.heading
        role = actor.role

        if scenario.cluster == "intersection" and role == "conflicting_vehicle":
            speed = actor.speed * stress_level.actor_speed_scale
            active_from = max(0, ego_arrival_tick + stress_level.trigger_offset_ticks)
            active_until = active_from + 18
            x = conflict_point[0] + math.copysign(0.7, actor.x - conflict_point[0] if actor.x != conflict_point[0] else 1.0)
            y = conflict_point[1] + math.copysign(half_width * 0.94 / stress_level.lateral_tightening, actor.y - conflict_point[1])
        elif scenario.cluster == "intersection" and role == "occluded_vehicle":
            active_from = max(active_from, ego_arrival_tick + stress_level.trigger_offset_ticks + 6)
            active_until = active_from + 16
            x = min(actor.x, conflict_point[0] + 7.5)
            y = conflict_point[1] + math.copysign(half_width * 1.18 / stress_level.lateral_tightening, actor.y - conflict_point[1])
        elif scenario.cluster in {"spotlight", "foreign object debris"} and role == "spotlight_hazard":
            active_from = max(0, ego_arrival_tick + stress_level.trigger_offset_ticks + 1)
            active_until = max(active_from + 12, actor.active_until)
            y = conflict_point[1] + (actor.y - conflict_point[1]) / stress_level.lateral_tightening
            speed = actor.speed * stress_level.actor_speed_scale
        elif scenario.cluster == "cut-in" and role == "cut_in_vehicle":
            active_from = max(0, ego_arrival_tick + stress_level.trigger_offset_ticks - 1)
            active_until = active_from + 20
            y = conflict_point[1] + (actor.y - conflict_point[1]) / stress_level.lateral_tightening
            speed = actor.speed * stress_level.actor_speed_scale
        elif scenario.cluster == "construction" and role == "flagger":
            y = conflict_point[1] + (actor.y - conflict_point[1]) / stress_level.lateral_tightening

        vx = math.cos(heading) * speed
        vy = math.sin(heading) * speed
        actors.append(
            replace(
                actor,
                x=x,
                y=y,
                speed=speed,
                vx=vx,
                vy=vy,
                active_from=active_from,
                active_until=active_until,
            )
        )
    return actors


def _tighten_obstacles(
    scenario: Scenario,
    stress_level: StressLevel,
    conflict_point: tuple[float, float],
) -> list[Obstacle]:
    if scenario.cluster not in {"construction", "foreign object debris", "spotlight"}:
        return list(scenario.obstacles)

    tightened: list[Obstacle] = []
    half_width = scenario.lane_half_width
    for obstacle in scenario.obstacles:
        x = obstacle.x
        y = obstacle.y
        radius = obstacle.radius
        if scenario.cluster == "construction" and obstacle.kind == "cone":
            y = conflict_point[1] + (obstacle.y - conflict_point[1]) / stress_level.lateral_tightening
        elif scenario.cluster == "foreign object debris" and obstacle.label == "ambient_texture":
            if abs(obstacle.x - conflict_point[0]) < 8.0:
                y = conflict_point[1] + math.copysign(half_width * 0.72, obstacle.y - conflict_point[1] if obstacle.y != conflict_point[1] else 1.0)
                radius = obstacle.radius * min(1.35, stress_level.obstacle_pressure_scale)
        elif scenario.cluster == "spotlight" and obstacle.label == "spotlight_occluder":
            y = conflict_point[1] + (obstacle.y - conflict_point[1]) / stress_level.lateral_tightening
            x = min(obstacle.x, conflict_point[0] + 5.8)
        tightened.append(replace(obstacle, x=x, y=y, radius=radius))
    return tightened


def iter_internal_stress_cases(
    clusters: Iterable[str],
    seeds: Iterable[int],
    levels: Iterable[str],
) -> Iterable[tuple[str, int, str, Scenario]]:
    for cluster in clusters:
        for seed in seeds:
            for level in levels:
                yield cluster, seed, level, generate_internal_stress_scenario(cluster, seed, level=level)
