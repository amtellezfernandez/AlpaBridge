from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
import math
import random
from pathlib import Path
from typing import Any


SIM_TICK_DT_S = 0.25
DEFAULT_TIME_SWEEP_MAX_DEPTH = 3
DEFAULT_TIME_SWEEP_CURVATURE_TOLERANCE_M = 0.1
DEFAULT_EGO_RADIUS_M = 0.35


@dataclass
class Obstacle:
    x: float
    y: float
    radius: float
    kind: str = "obstacle"
    label: str = "obstacle"
    length: float | None = None
    heading: float = 0.0


@dataclass
class Actor:
    actor_id: str
    kind: str
    x: float
    y: float
    width: float
    length: float
    heading: float
    speed: float
    vx: float
    vy: float
    behavior: str
    role: str
    active_from: int = 0
    active_until: int = 10_000

    @property
    def radius(self) -> float:
        return max(self.width, self.length) * 0.5


@dataclass
class Scenario:
    width: float
    height: float
    lane_center: list[tuple[float, float]]
    lane_half_width: float
    obstacles: list[Obstacle]
    start: tuple[float, float]
    goal: tuple[float, float]
    seed: int
    cluster: str = "baseline"
    tags: dict[str, Any] = field(default_factory=dict)
    actors: list[Actor] = field(default_factory=list)
    map_features: list[dict[str, Any]] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)


def generate_scenario(seed: int, width: float = 120.0, height: float = 80.0) -> Scenario:
    rng = random.Random(seed)
    lane_half_width = rng.uniform(7.0, 10.0)
    control_points = 8
    lane_center: list[tuple[float, float]] = []

    for index in range(control_points):
        x = 10 + index * (width - 20) / (control_points - 1)
        y = height * 0.5 + rng.uniform(-height * 0.22, height * 0.22)
        lane_center.append((x, y))

    obstacles: list[Obstacle] = []
    for _ in range(rng.randint(7, 12)):
        segment_index = rng.randint(1, control_points - 2)
        anchor_x, anchor_y = lane_center[segment_index]
        lateral_offset = rng.choice((-1.0, 1.0)) * rng.uniform(lane_half_width * 0.45, lane_half_width * 0.95)
        forward_offset = rng.uniform(-5.0, 5.0)
        obstacles.append(
            Obstacle(
                x=anchor_x + forward_offset,
                y=anchor_y + lateral_offset,
                radius=rng.uniform(1.2, 2.8),
                kind="background_obstacle",
                label="baseline_texture",
            )
        )

    start = (lane_center[0][0] - 4.0, lane_center[0][1])
    goal = (lane_center[-1][0] + 4.0, lane_center[-1][1])
    return Scenario(width, height, lane_center, lane_half_width, obstacles, start, goal, seed)


def actor_at_time_index(
    actor: Actor,
    time_index: float,
    dt: float = SIM_TICK_DT_S,
    active_from: float | None = None,
) -> Actor:
    effective_active_from = float(actor.active_from if active_from is None else active_from)
    if time_index < effective_active_from:
        return actor
    elapsed = max(0.0, time_index - effective_active_from) * dt
    if actor.behavior in {"cut_in", "swerve"}:
        longitudinal = actor.speed * elapsed
        lateral = min(4.5, 0.38 * elapsed * elapsed)
        lateral *= -1.0 if actor.vy < 0.0 else 1.0
        return replace(
            actor,
            x=actor.x + math.cos(actor.heading) * longitudinal,
            y=actor.y + math.sin(actor.heading) * longitudinal + lateral,
        )
    if actor.behavior in {"darting", "erratic_pedestrian"}:
        pause = 0.4 if int(elapsed * 2.0) % 3 == 0 else 1.0
        wobble = math.sin(elapsed * 3.7) * 0.55
        return replace(actor, x=actor.x + actor.vx * elapsed * pause, y=actor.y + actor.vy * elapsed * pause + wobble)
    if actor.behavior in {"sudden_brake", "hesitating"}:
        moving_time = min(elapsed, 1.2)
        creep_time = max(0.0, elapsed - 1.2)
        distance = actor.speed * moving_time + actor.speed * 0.15 * creep_time
        return replace(actor, x=actor.x + math.cos(actor.heading) * distance, y=actor.y + math.sin(actor.heading) * distance)
    if actor.behavior == "wrong_way":
        return replace(actor, x=actor.x - abs(actor.vx) * elapsed, y=actor.y + actor.vy * elapsed)
    return replace(actor, x=actor.x + actor.vx * elapsed, y=actor.y + actor.vy * elapsed)


def actor_at_tick(actor: Actor, tick: int, dt: float = SIM_TICK_DT_S) -> Actor:
    return actor_at_time_index(actor, float(tick), dt)


def actor_to_obstacle_at_time(
    actor: Actor,
    time_index: float,
    dt: float = SIM_TICK_DT_S,
    active_from: float | None = None,
    active_until: float | None = None,
) -> Obstacle | None:
    effective_active_from = float(actor.active_from if active_from is None else active_from)
    effective_active_until = float(actor.active_until if active_until is None else active_until)
    if time_index < effective_active_from or time_index > effective_active_until:
        return None
    projected = actor_at_time_index(actor, time_index, dt, active_from=effective_active_from)
    return Obstacle(
        projected.x,
        projected.y,
        projected.width * 0.5,
        kind=projected.kind,
        label=projected.role,
        length=projected.length,
        heading=projected.heading,
    )


def actor_to_obstacle(actor: Actor, tick: int = 0, dt: float = SIM_TICK_DT_S) -> Obstacle | None:
    return actor_to_obstacle_at_time(actor, float(tick), dt)


def _same_obstacle(first: Obstacle, second: Obstacle) -> bool:
    return (
        first.kind == second.kind
        and first.label == second.label
        and math.isclose(first.x, second.x, abs_tol=1e-9)
        and math.isclose(first.y, second.y, abs_tol=1e-9)
        and math.isclose(first.radius, second.radius, abs_tol=1e-9)
    )


def static_obstacles_at_time(scenario: Scenario, time_index: float, dt: float = SIM_TICK_DT_S) -> list[Obstacle]:
    obstacles = [obstacle for obstacle in scenario.obstacles if obstacle.kind != "ambient"]
    if not scenario.actors:
        return obstacles
    actor_obstacles = [
        obstacle
        for actor in scenario.actors
        if (obstacle := actor_to_obstacle_at_time(actor, time_index, dt)) is not None
    ]
    if not actor_obstacles:
        return obstacles
    return [
        obstacle
        for obstacle in obstacles
        if not any(_same_obstacle(obstacle, actor_obstacle) for actor_obstacle in actor_obstacles)
    ]


def obstacles_at_time(scenario: Scenario, time_index: float, dt: float = SIM_TICK_DT_S) -> list[Obstacle]:
    obstacles = static_obstacles_at_time(scenario, time_index, dt)
    for actor in scenario.actors:
        obstacle = actor_to_obstacle_at_time(actor, time_index, dt)
        if obstacle is not None:
            obstacles.append(obstacle)
    return obstacles


def obstacles_at_tick(scenario: Scenario, tick: int, dt: float = SIM_TICK_DT_S) -> list[Obstacle]:
    return obstacles_at_time(scenario, float(tick), dt)


def scenario_at_tick(scenario: Scenario, tick: int, dt: float = SIM_TICK_DT_S) -> Scenario:
    return replace(scenario, obstacles=obstacles_at_time(scenario, float(tick), dt), environment={**scenario.environment, "tick": tick})


def scenario_at_state(
    scenario: Scenario,
    tick: int,
    position: tuple[float, float],
    runtime_state: dict[str, object] | None = None,
    dt: float = SIM_TICK_DT_S,
) -> tuple[Scenario, dict[str, object]]:
    state = dict(runtime_state or {})
    actor_trigger_ticks = dict(state.get("actor_trigger_ticks", {}))
    actor_windows = _runtime_actor_windows(scenario, float(tick), position, actor_trigger_ticks)
    triggered_actor_ids = _trigger_region_actor_ids(scenario)
    state["actor_trigger_ticks"] = actor_trigger_ticks
    obstacles = [obstacle for obstacle in scenario.obstacles if obstacle.kind != "ambient"]
    for actor in scenario.actors:
        if actor.actor_id in triggered_actor_ids and actor.actor_id not in actor_windows:
            continue
        active_from, active_until = actor_windows.get(actor.actor_id, (actor.active_from, actor.active_until))
        obstacle = actor_to_obstacle_at_time(actor, float(tick), dt, active_from=active_from, active_until=active_until)
        if obstacle is not None:
            obstacles.append(obstacle)
    return (
        replace(scenario, obstacles=obstacles, environment={**scenario.environment, "tick": tick, "runtime_actor_windows": actor_windows}),
        state,
    )


def _runtime_actor_windows(
    scenario: Scenario,
    time_index: float,
    position: tuple[float, float],
    actor_trigger_ticks: dict[str, float],
) -> dict[str, tuple[float, float]]:
    trigger_regions = scenario.environment.get("trigger_regions")
    if isinstance(trigger_regions, list) and trigger_regions:
        windows = _runtime_windows_from_regions(scenario, time_index, position, actor_trigger_ticks, trigger_regions)
        if windows:
            return windows

    if scenario.cluster != "intersection":
        return {}
    trigger_x = float(scenario.environment.get("intersection_trigger_x", scenario.lane_center[3][0] - 8.0))
    if position[0] < trigger_x:
        return {}

    actors = [actor for actor in scenario.actors if actor.role in {"conflicting_vehicle", "occluded_vehicle"}]
    return _activate_actor_group(time_index, actor_trigger_ticks, actors)


def _runtime_windows_from_regions(
    scenario: Scenario,
    time_index: float,
    position: tuple[float, float],
    actor_trigger_ticks: dict[str, float],
    trigger_regions: list[object],
) -> dict[str, tuple[float, float]]:
    windows: dict[str, tuple[float, float]] = {}
    for raw_region in trigger_regions:
        if not isinstance(raw_region, dict):
            continue
        actor_roles = tuple(str(role) for role in raw_region.get("actor_roles", ()))
        actors = [actor for actor in scenario.actors if actor.role in actor_roles]
        if not actors or not _position_matches_trigger(position, raw_region):
            continue
        delay_ticks = float(raw_region.get("delay_ticks", 0.0))
        scoped = _activate_actor_group(time_index + delay_ticks, actor_trigger_ticks, actors)
        windows.update(scoped)
    return windows


def _trigger_region_actor_ids(scenario: Scenario) -> set[str]:
    trigger_regions = scenario.environment.get("trigger_regions")
    if not isinstance(trigger_regions, list):
        return set()
    actor_ids: set[str] = set()
    for raw_region in trigger_regions:
        if not isinstance(raw_region, dict):
            continue
        actor_roles = {str(role) for role in raw_region.get("actor_roles", ())}
        actor_ids.update(actor.actor_id for actor in scenario.actors if actor.role in actor_roles)
    return actor_ids


def _position_matches_trigger(position: tuple[float, float], region: dict[str, object]) -> bool:
    x_min = float(region.get("x_min", -math.inf))
    x_max = float(region.get("x_max", math.inf))
    y_min = float(region.get("y_min", -math.inf))
    y_max = float(region.get("y_max", math.inf))
    return x_min <= position[0] <= x_max and y_min <= position[1] <= y_max


def _activate_actor_group(
    time_index: float,
    actor_trigger_ticks: dict[str, float],
    actors: list[Actor],
) -> dict[str, tuple[float, float]]:
    if not actors:
        return {}
    base_active_from = min(actor.active_from for actor in actors)
    windows: dict[str, tuple[float, float]] = {}
    for actor in actors:
        if actor.actor_id not in actor_trigger_ticks:
            actor_trigger_ticks[actor.actor_id] = time_index + max(0.0, actor.active_from - base_active_from)
        effective_active_from = float(actor_trigger_ticks[actor.actor_id])
        duration = max(1.0, float(actor.active_until - actor.active_from))
        windows[actor.actor_id] = (effective_active_from, effective_active_from + duration)
    return windows


def point_clearance(point: tuple[float, float], obstacle: Obstacle) -> float:
    start, end = obstacle_spine(obstacle)
    return segment_point_distance(start, end, point) - obstacle.radius


def segment_point_distance(
    start: tuple[float, float],
    end: tuple[float, float],
    point: tuple[float, float],
) -> float:
    segment = (end[0] - start[0], end[1] - start[1])
    length_sq = segment[0] * segment[0] + segment[1] * segment[1]
    if length_sq == 0.0:
        return math.dist(start, point)
    offset = (point[0] - start[0], point[1] - start[1])
    projection = (offset[0] * segment[0] + offset[1] * segment[1]) / length_sq
    projection = min(1.0, max(0.0, projection))
    nearest = (
        start[0] + segment[0] * projection,
        start[1] + segment[1] * projection,
    )
    return math.dist(nearest, point)


def obstacle_spine(obstacle: Obstacle) -> tuple[tuple[float, float], tuple[float, float]]:
    length = obstacle.length if obstacle.length is not None else obstacle.radius * 2.0
    half_spine = max(0.0, length * 0.5 - obstacle.radius)
    dx = math.cos(obstacle.heading) * half_spine
    dy = math.sin(obstacle.heading) * half_spine
    return ((obstacle.x - dx, obstacle.y - dy), (obstacle.x + dx, obstacle.y + dy))


def obstacle_local_spine(obstacle: Obstacle) -> tuple[tuple[float, float], tuple[float, float]]:
    length = obstacle.length if obstacle.length is not None else obstacle.radius * 2.0
    half_spine = max(0.0, length * 0.5 - obstacle.radius)
    dx = math.cos(obstacle.heading) * half_spine
    dy = math.sin(obstacle.heading) * half_spine
    return ((-dx, -dy), (dx, dy))


def obstacle_axis_extent(
    obstacle: Obstacle,
    axis: tuple[float, float],
) -> float:
    local_start, local_end = obstacle_local_spine(obstacle)
    return max(abs(local_start[0] * axis[0] + local_start[1] * axis[1]), abs(local_end[0] * axis[0] + local_end[1] * axis[1])) + obstacle.radius


def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
    return (
        min(a[0], c[0]) - 1e-9 <= b[0] <= max(a[0], c[0]) + 1e-9
        and min(a[1], c[1]) - 1e-9 <= b[1] <= max(a[1], c[1]) + 1e-9
    )


def segments_intersect(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> bool:
    o1 = _orientation(first_start, first_end, second_start)
    o2 = _orientation(first_start, first_end, second_end)
    o3 = _orientation(second_start, second_end, first_start)
    o4 = _orientation(second_start, second_end, first_end)
    if (o1 > 0.0) != (o2 > 0.0) and (o3 > 0.0) != (o4 > 0.0):
        return True
    if math.isclose(o1, 0.0, abs_tol=1e-9) and _on_segment(first_start, second_start, first_end):
        return True
    if math.isclose(o2, 0.0, abs_tol=1e-9) and _on_segment(first_start, second_end, first_end):
        return True
    if math.isclose(o3, 0.0, abs_tol=1e-9) and _on_segment(second_start, first_start, second_end):
        return True
    if math.isclose(o4, 0.0, abs_tol=1e-9) and _on_segment(second_start, first_end, second_end):
        return True
    return False


def segment_distance(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> float:
    if segments_intersect(first_start, first_end, second_start, second_end):
        return 0.0
    return min(
        segment_point_distance(first_start, first_end, second_start),
        segment_point_distance(first_start, first_end, second_end),
        segment_point_distance(second_start, second_end, first_start),
        segment_point_distance(second_start, second_end, first_end),
    )


def obstacle_signed_distance(point: tuple[float, float], obstacle: Obstacle) -> float:
    return point_clearance(point, obstacle)


def segment_clearance(
    start: tuple[float, float],
    end: tuple[float, float],
    obstacle: Obstacle,
    ego_radius: float = 0.0,
) -> float:
    obstacle_start, obstacle_end = obstacle_spine(obstacle)
    return segment_distance(start, end, obstacle_start, obstacle_end) - obstacle.radius - ego_radius


def min_segment_clearance(
    start: tuple[float, float],
    end: tuple[float, float],
    obstacles: list[Obstacle],
    ego_radius: float = 0.0,
) -> float:
    return min((segment_clearance(start, end, obstacle, ego_radius=ego_radius) for obstacle in obstacles), default=math.inf)


def moving_obstacle_segment_clearance(
    ego_start: tuple[float, float],
    ego_end: tuple[float, float],
    obstacle_start: tuple[float, float],
    obstacle_end: tuple[float, float],
    obstacle_radius: float,
    ego_radius: float = 0.0,
    obstacle_spine_start: tuple[float, float] | None = None,
    obstacle_spine_end: tuple[float, float] | None = None,
) -> float:
    relative_start = (
        ego_start[0] - obstacle_start[0],
        ego_start[1] - obstacle_start[1],
    )
    relative_end = (
        ego_end[0] - obstacle_end[0],
        ego_end[1] - obstacle_end[1],
    )
    local_spine_start = obstacle_spine_start if obstacle_spine_start is not None else (0.0, 0.0)
    local_spine_end = obstacle_spine_end if obstacle_spine_end is not None else (0.0, 0.0)
    return segment_distance(relative_start, relative_end, local_spine_start, local_spine_end) - obstacle_radius - ego_radius


def _actor_motion_curvature(
    actor: Actor,
    start_time_index: float,
    end_time_index: float,
    dt: float,
) -> float:
    midpoint_time_index = (start_time_index + end_time_index) * 0.5
    start_obstacle = actor_to_obstacle_at_time(actor, start_time_index, dt)
    midpoint_obstacle = actor_to_obstacle_at_time(actor, midpoint_time_index, dt)
    end_obstacle = actor_to_obstacle_at_time(actor, end_time_index, dt)
    if start_obstacle is None or midpoint_obstacle is None or end_obstacle is None:
        return 0.0
    interpolated_midpoint = (
        (start_obstacle.x + end_obstacle.x) * 0.5,
        (start_obstacle.y + end_obstacle.y) * 0.5,
    )
    return math.dist((midpoint_obstacle.x, midpoint_obstacle.y), interpolated_midpoint)


def _moving_actor_segment_clearance(
    actor: Actor,
    ego_start: tuple[float, float],
    ego_end: tuple[float, float],
    start_time_index: float,
    end_time_index: float,
    dt: float,
    max_depth: int,
    curvature_tolerance_m: float,
    ego_radius: float,
) -> float:
    start_obstacle = actor_to_obstacle_at_time(actor, start_time_index, dt)
    end_obstacle = actor_to_obstacle_at_time(actor, end_time_index, dt)
    if start_obstacle is None and end_obstacle is None:
        return math.inf
    if start_obstacle is None:
        start_obstacle = end_obstacle
    if end_obstacle is None:
        end_obstacle = start_obstacle
    assert start_obstacle is not None
    assert end_obstacle is not None
    clearance = moving_obstacle_segment_clearance(
        ego_start,
        ego_end,
        (start_obstacle.x, start_obstacle.y),
        (end_obstacle.x, end_obstacle.y),
        max(start_obstacle.radius, end_obstacle.radius),
        ego_radius=ego_radius,
        obstacle_spine_start=obstacle_local_spine(start_obstacle)[0],
        obstacle_spine_end=obstacle_local_spine(start_obstacle)[1],
    )
    if max_depth <= 0:
        return clearance
    curvature = _actor_motion_curvature(actor, start_time_index, end_time_index, dt)
    if curvature <= curvature_tolerance_m:
        return clearance
    midpoint_fraction = 0.5
    midpoint_time_index = (start_time_index + end_time_index) * midpoint_fraction
    midpoint = interpolate_point(ego_start, ego_end, midpoint_fraction)
    return min(
        clearance,
        _moving_actor_segment_clearance(
            actor,
            ego_start,
            midpoint,
            start_time_index,
            midpoint_time_index,
            dt,
            max_depth - 1,
            curvature_tolerance_m,
            ego_radius,
        ),
        _moving_actor_segment_clearance(
            actor,
            midpoint,
            ego_end,
            midpoint_time_index,
            end_time_index,
            dt,
            max_depth - 1,
            curvature_tolerance_m,
            ego_radius,
        ),
    )


def interpolate_point(
    start: tuple[float, float],
    end: tuple[float, float],
    fraction: float,
) -> tuple[float, float]:
    return (
        start[0] + (end[0] - start[0]) * fraction,
        start[1] + (end[1] - start[1]) * fraction,
    )


def min_time_swept_clearance(
    scenario: Scenario,
    start: tuple[float, float],
    end: tuple[float, float],
    start_time_index: float,
    end_time_index: float,
    samples: int = 5,
    dt: float = SIM_TICK_DT_S,
    max_depth: int = DEFAULT_TIME_SWEEP_MAX_DEPTH,
    curvature_tolerance_m: float = DEFAULT_TIME_SWEEP_CURVATURE_TOLERANCE_M,
    ego_radius: float = 0.0,
) -> float:
    samples = max(1, samples)
    static_clearance = min_segment_clearance(
        start,
        end,
        static_obstacles_at_time(scenario, start_time_index, dt),
        ego_radius=ego_radius,
    )
    min_clearance = static_clearance
    for sample in range(samples):
        first_fraction = sample / samples
        second_fraction = (sample + 1) / samples
        segment_start = interpolate_point(start, end, first_fraction)
        segment_end = interpolate_point(start, end, second_fraction)
        first_time_index = start_time_index + (end_time_index - start_time_index) * first_fraction
        second_time_index = start_time_index + (end_time_index - start_time_index) * second_fraction
        for actor in scenario.actors:
            min_clearance = min(
                min_clearance,
                _moving_actor_segment_clearance(
                    actor,
                    segment_start,
                    segment_end,
                    first_time_index,
                    second_time_index,
                    dt,
                    max_depth,
                    curvature_tolerance_m,
                    ego_radius,
                ),
            )
    return min_clearance


def interpolate_lane(centerline: list[tuple[float, float]], samples_per_segment: int = 16) -> list[tuple[float, float]]:
    if len(centerline) < 3:
        return list(centerline)

    def catmull_rom(
        p0: tuple[float, float],
        p1: tuple[float, float],
        p2: tuple[float, float],
        p3: tuple[float, float],
        t: float,
    ) -> tuple[float, float]:
        t2 = t * t
        t3 = t2 * t
        x = 0.5 * (
            (2.0 * p1[0])
            + (-p0[0] + p2[0]) * t
            + (2.0 * p0[0] - 5.0 * p1[0] + 4.0 * p2[0] - p3[0]) * t2
            + (-p0[0] + 3.0 * p1[0] - 3.0 * p2[0] + p3[0]) * t3
        )
        y = 0.5 * (
            (2.0 * p1[1])
            + (-p0[1] + p2[1]) * t
            + (2.0 * p0[1] - 5.0 * p1[1] + 4.0 * p2[1] - p3[1]) * t2
            + (-p0[1] + 3.0 * p1[1] - 3.0 * p2[1] + p3[1]) * t3
        )
        return (x, y)

    points: list[tuple[float, float]] = []
    for index in range(len(centerline) - 1):
        first = centerline[index]
        second = centerline[index + 1]
        p0 = centerline[index - 1] if index > 0 else first
        p1 = first
        p2 = second
        p3 = centerline[index + 2] if index + 2 < len(centerline) else second
        for sample in range(samples_per_segment):
            t = sample / samples_per_segment
            points.append(catmull_rom(p0, p1, p2, p3, t))
    points.append(centerline[-1])
    return points


def scenario_lane_count(scenario: Scenario) -> int:
    for feature in scenario.map_features:
        if str(feature.get("kind", "")) == "route_corridor":
            try:
                return max(1, int(feature.get("lane_count", 1)))
            except (TypeError, ValueError):
                return 1
    return 1


def scenario_travel_lane_index(scenario: Scenario) -> int:
    lane_count = scenario_lane_count(scenario)
    for feature in scenario.map_features:
        if str(feature.get("kind", "")) == "route_corridor" and "travel_lane_index" in feature:
            try:
                return min(max(0, int(feature["travel_lane_index"])), lane_count - 1)
            except (TypeError, ValueError):
                return 0 if lane_count > 1 else 0
    return 0 if lane_count > 1 else 0


def route_lane_offset_m(scenario: Scenario) -> float:
    lane_count = scenario_lane_count(scenario)
    if lane_count <= 1:
        return 0.0
    lane_width = (scenario.lane_half_width * 2.0) / lane_count
    lane_index = scenario_travel_lane_index(scenario)
    return -scenario.lane_half_width + lane_width * (lane_index + 0.5)


def offset_centerline(centerline: list[tuple[float, float]], offset_m: float) -> list[tuple[float, float]]:
    if not centerline or abs(offset_m) <= 1e-9:
        return list(centerline)
    if len(centerline) == 1:
        return list(centerline)
    offset_points: list[tuple[float, float]] = []
    for index, point in enumerate(centerline):
        prev_point = centerline[index - 1] if index > 0 else point
        next_point = centerline[index + 1] if index < len(centerline) - 1 else point
        dx = next_point[0] - prev_point[0]
        dy = next_point[1] - prev_point[1]
        norm = math.hypot(dx, dy)
        if norm <= 1e-9:
            nx, ny = 0.0, 1.0
        else:
            nx, ny = -dy / norm, dx / norm
        offset_points.append((point[0] + nx * offset_m, point[1] + ny * offset_m))
    return offset_points


def route_centerline(scenario: Scenario, samples_per_segment: int = 16) -> list[tuple[float, float]]:
    points = interpolate_lane(offset_centerline(scenario.lane_center, route_lane_offset_m(scenario)), samples_per_segment=samples_per_segment)
    if not points:
        return [scenario.start, scenario.goal]
    if math.dist(points[0], scenario.start) > 1e-6:
        points = [scenario.start, *points]
    if math.dist(points[-1], scenario.goal) > 1e-6:
        points = [*points, scenario.goal]
    return points


def nearest_lane_point(point: tuple[float, float], lane_points: list[tuple[float, float]]) -> tuple[int, tuple[float, float], float]:
    best_index = 0
    best_point = lane_points[0]
    best_distance = math.inf

    for index, lane_point in enumerate(lane_points):
        distance = math.dist(point, lane_point)
        if distance < best_distance:
            best_index = index
            best_point = lane_point
            best_distance = distance

    return best_index, best_point, best_distance


def write_rollout(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def scenario_to_dict(scenario: Scenario) -> dict:
    return {
        "width": scenario.width,
        "height": scenario.height,
        "lane_center": scenario.lane_center,
        "lane_half_width": scenario.lane_half_width,
        "obstacles": [asdict(obstacle) for obstacle in scenario.obstacles],
        "start": scenario.start,
        "goal": scenario.goal,
        "seed": scenario.seed,
        "cluster": scenario.cluster,
        "tags": scenario.tags,
        "actors": [asdict(actor) for actor in scenario.actors],
        "map_features": scenario.map_features,
        "environment": scenario.environment,
    }
