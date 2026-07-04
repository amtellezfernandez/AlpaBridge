from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Callable

from .environment import DEFAULT_EGO_RADIUS_M, Scenario, min_segment_clearance, min_time_swept_clearance, obstacle_axis_extent, route_centerline, scenario_at_state
from .perception import ScenePerception, perceive_scene
from .planner import PlannedAction, plan_action
from .safety import SafeAction, apply_safety_filter
from .spotlight_reflex import SpotlightReflexConfig, plan_spotlight_reflex_action
from .world_model import WorldState, update_world_state


@dataclass
class StepRecord:
    t: int
    x: float
    y: float
    lane_error: float
    min_obstacle_distance: float
    uncertainty: float
    collision_risk: float
    action_mode: str
    speed: float
    intervention: bool
    obstacle_pressure: float | None = None
    route_blockage: float | None = None
    corridor_blocked: bool | None = None
    left_clearance: float | None = None
    right_clearance: float | None = None
    preferred_escape_side: str | None = None
    world_model_summary: str | None = None
    goal_distance: float | None = None
    progress: float | None = None
    comfort_cost: float | None = None
    active_actor_count: int | None = None
    stall: bool | None = None
    candidate_count: int | None = None
    reference_count: int | None = None
    selected_maneuver: str | None = None
    selector_score: float | None = None
    selector_effective_score: float | None = None
    selector_3s_score: float | None = None
    selector_5s_score: float | None = None
    selector_3s_reference: str | None = None
    selector_5s_reference: str | None = None
    selector_3s_inside_region: bool | None = None
    selector_5s_inside_region: bool | None = None
    decision_reason: str | None = None
    decision_reasons: list[str] | None = None
    top_candidate_summaries: list[dict[str, Any]] | None = None


@dataclass
class Rollout:
    success: bool
    collision: bool
    reached_goal: bool
    steps: list[StepRecord]


@dataclass(frozen=True)
class EgoState:
    x: float
    y: float
    heading_rad: float
    speed_mps: float
    steering_rad: float


PolicyPlanner = Callable[
    [Scenario, tuple[float, float], WorldState, ScenePerception, "RolloutConfig"],
    tuple[PlannedAction, dict[str, Any]],
]


@dataclass(frozen=True)
class RolloutConfig:
    max_steps: int = 220
    step_size: float = 1.25
    dt_s: float = 1.0
    goal_tolerance_m: float = 3.0
    stall_goal_distance_m: float = 3.0
    max_accel_mps2: float = 3.0
    max_decel_mps2: float = 4.0
    max_abs_steering_rad: float = 0.95
    max_steering_rate_rad_s: float = 2.2
    wheelbase_m: float = 2.8
    preserve_planned_direction: bool = False
    spotlight: SpotlightReflexConfig = field(default_factory=SpotlightReflexConfig)


DEFAULT_BASELINE_ROLLOUT_CONFIG = RolloutConfig()
DEFAULT_SPOTLIGHT_ROLLOUT_CONFIG = RolloutConfig(max_steps=225, preserve_planned_direction=True)


def run_policy(
    scenario: Scenario,
    max_steps: int = 220,
    step_size: float = 1.25,
    config: RolloutConfig | None = None,
) -> Rollout:
    config = _rollout_config(config, max_steps, step_size, DEFAULT_BASELINE_ROLLOUT_CONFIG)
    return _run_rollout(scenario, _baseline_planner, config)


def run_spotlight_reflex_policy(
    scenario: Scenario,
    max_steps: int = 225,
    step_size: float = 1.25,
    config: RolloutConfig | None = None,
) -> Rollout:
    config = _rollout_config(config, max_steps, step_size, DEFAULT_SPOTLIGHT_ROLLOUT_CONFIG)
    return _run_rollout(
        scenario,
        _spotlight_reflex_planner,
        config,
    )


def _rollout_config(
    config: RolloutConfig | None,
    max_steps: int,
    step_size: float,
    default: RolloutConfig,
) -> RolloutConfig:
    if config is not None:
        return config
    if max_steps == default.max_steps and step_size == default.step_size:
        return default
    return RolloutConfig(
        max_steps=max_steps,
        step_size=step_size,
        dt_s=default.dt_s,
        goal_tolerance_m=default.goal_tolerance_m,
        stall_goal_distance_m=default.stall_goal_distance_m,
        max_accel_mps2=default.max_accel_mps2,
        max_decel_mps2=default.max_decel_mps2,
        max_abs_steering_rad=default.max_abs_steering_rad,
        max_steering_rate_rad_s=default.max_steering_rate_rad_s,
        wheelbase_m=default.wheelbase_m,
        preserve_planned_direction=default.preserve_planned_direction,
        spotlight=default.spotlight,
    )


def _baseline_planner(
    scenario: Scenario,
    position: tuple[float, float],
    world_state: WorldState,
    perception: ScenePerception,
    config: RolloutConfig,
) -> tuple[PlannedAction, dict[str, Any]]:
    del scenario
    return plan_action(position, world_state, perception, nominal_step_size=config.step_size), {}


def _spotlight_reflex_planner(
    scenario: Scenario,
    position: tuple[float, float],
    world_state: WorldState,
    perception: ScenePerception,
    config: RolloutConfig,
) -> tuple[PlannedAction, dict[str, Any]]:
    planned_action, selection = plan_spotlight_reflex_action(
        scenario,
        position,
        world_state,
        perception,
        nominal_step_size=config.step_size,
        config=config.spotlight,
    )
    return planned_action, selection.to_metadata()


def _run_rollout(
    scenario: Scenario,
    planner: PolicyPlanner,
    config: RolloutConfig,
) -> Rollout:
    initial_heading = _initial_heading(scenario)
    ego_state = EgoState(
        x=scenario.start[0],
        y=scenario.start[1],
        heading_rad=initial_heading,
        speed_mps=0.0,
        steering_rad=0.0,
    )
    steps: list[StepRecord] = []
    collision = False
    reached_goal = False
    runtime_state: dict[str, object] = {}

    for tick in range(config.max_steps):
        position = (ego_state.x, ego_state.y)
        previous_position = position
        active_scenario, runtime_state = scenario_at_state(scenario, tick, position, runtime_state)
        perception = perceive_scene(active_scenario, position)
        world_state = update_world_state(active_scenario, position, perception)
        planned_action, metadata = planner(active_scenario, position, world_state, perception, config)
        safe_action = apply_safety_filter(planned_action, world_state, perception)
        safe_action = _recenter_route_drift(active_scenario, safe_action, world_state, perception)
        safe_action = _recover_stalled_spotlight_progress(safe_action, planned_action, world_state, perception, steps)
        safe_action = _commit_wod_intersection_crossing(active_scenario, safe_action, world_state, perception, steps)
        if (
            config.preserve_planned_direction
            and safe_action.direction == (0.0, 0.0)
            and safe_action.speed > 0.0
            and planned_action.direction != (0.0, 0.0)
        ):
            safe_action.direction = planned_action.direction

        ego_state = advance_ego_state(ego_state, safe_action.direction, safe_action.speed, config)
        position = (ego_state.x, ego_state.y)

        min_obstacle_distance = min_time_swept_clearance(
            scenario,
            previous_position,
            position,
            tick,
            tick + 1,
            ego_radius=DEFAULT_EGO_RADIUS_M,
        )
        collision = min_obstacle_distance <= 0.0
        previous_goal_distance = math.dist(previous_position, scenario.goal)
        goal_distance = math.dist(position, scenario.goal)
        steps.append(
            _step_record(
                tick,
                position,
                perception,
                world_state,
                safe_action,
                goal_distance,
                previous_goal_distance,
                min_obstacle_distance,
                len(active_scenario.actors),
                steps[-1].speed if steps else None,
                metadata,
                config,
                ego_state,
            )
        )

        if collision:
            break

        if math.dist(position, scenario.goal) < config.goal_tolerance_m:
            reached_goal = True
            break

    success = reached_goal and not collision
    return Rollout(success=success, collision=collision, reached_goal=reached_goal, steps=steps)


def _recover_stalled_spotlight_progress(
    safe_action: SafeAction,
    planned_action: PlannedAction,
    world_state: WorldState,
    perception: ScenePerception,
    steps: list[StepRecord],
) -> SafeAction:
    if world_state.collision_risk > 0.75 or world_state.goal_distance < 8.0:
        return safe_action
    if len(steps) < 12:
        return safe_action
    if (
        planned_action.mode.startswith("spotlight_reflex:")
        and any(step.action_mode == "deadlock_breakout" for step in steps[-4:])
        and world_state.collision_risk < 0.72
        and steps[-1].min_obstacle_distance > 1.15
    ):
        direction = _direction_to_target(world_state)
        speed = max(safe_action.speed, 0.75)
        if direction != (0.0, 0.0) and _visible_clearance_after_step(world_state, perception, direction, speed) > 1.05:
            return SafeAction(direction=direction, speed=speed, mode="deadlock_breakout", intervention=True)
    if not _stalled_spotlight_recovery_candidate(safe_action, planned_action, world_state):
        return safe_action
    if any(step.action_mode == "intersection_crossing" for step in steps[-8:]):
        return safe_action
    if world_state.collision_risk > 0.65 and any(step.action_mode == "progress_recovery" for step in steps[-3:]):
        return safe_action

    if len(steps) >= 48:
        long_recent = steps[-48:]
        long_progress = sum(step.progress or 0.0 for step in long_recent)
        long_min_clearance = min(step.min_obstacle_distance for step in long_recent)
        long_recovery_modes = sum(
            1
            for step in long_recent
            if step.action_mode in {"risk_nudge", "progress_recovery", "cautious_follow"} or step.action_mode.endswith(":crawl")
        )
        lane_stall = abs(perception.lane_error) > 4.0 and long_progress < 4.0 and long_min_clearance > 1.1
        oscillation_stall = long_progress < 8.0 and long_recovery_modes >= 30 and long_min_clearance > 1.30
        if lane_stall or oscillation_stall:
            direction = _direction_to_target(world_state)
            speed = max(safe_action.speed, 1.15)
            if direction != (0.0, 0.0) and _visible_clearance_after_step(world_state, perception, direction, speed) > 1.05:
                return SafeAction(direction=direction, speed=speed, mode="deadlock_breakout", intervention=True)

    recent = steps[-12:]
    recent_progress = sum(step.progress or 0.0 for step in recent)
    recent_crawl_or_nudge = sum(
        1
        for step in recent
        if step.action_mode in {"risk_nudge", "cautious_follow"} or step.action_mode.endswith(":crawl")
    )
    min_recent_clearance = min(step.min_obstacle_distance for step in recent)
    if recent_progress > 1.0 or recent_crawl_or_nudge < 8 or min_recent_clearance < 1.2:
        return safe_action

    direction = _progress_recovery_direction(world_state, perception, planned_action)
    if direction == (0.0, 0.0):
        return safe_action
    recovery_speed = 0.85 if abs(perception.lane_error) > 5.0 and min_recent_clearance > 1.45 else 0.6
    return SafeAction(direction=direction, speed=max(safe_action.speed, recovery_speed), mode="progress_recovery", intervention=True)


def _recenter_route_drift(
    scenario: Scenario,
    safe_action: SafeAction,
    world_state: WorldState,
    perception: ScenePerception,
) -> SafeAction:
    if abs(perception.lane_error) < 4.0:
        return safe_action
    if world_state.collision_risk > 0.30 or perception.uncertainty > 0.75:
        return safe_action
    if safe_action.mode in {"risk_nudge", "risk_escape", "emergency_escape", "emergency_stop"}:
        return safe_action
    if "evasive" in safe_action.mode:
        return safe_action
    nearest_clearance = min((obstacle.signed_distance for obstacle in perception.visible_obstacles), default=math.inf)
    if nearest_clearance < 1.2:
        return safe_action

    lane_return = _normalize(
        (
            perception.lane_point[0] - world_state.position[0],
            perception.lane_point[1] - world_state.position[1],
        )
    )
    target_direction = _direction_to_target(world_state)
    if lane_return == (0.0, 0.0):
        return safe_action
    direction = lane_return
    if target_direction != (0.0, 0.0):
        direction = _normalize(
            (
                lane_return[0] * 0.85 + target_direction[0] * 0.65,
                lane_return[1] * 0.85 + target_direction[1] * 0.65,
            )
        )
    if direction == (0.0, 0.0):
        return safe_action
    return SafeAction(
        direction=direction,
        speed=min(max(safe_action.speed, 1.05), 1.15),
        mode="route_recenter",
        intervention=True,
    )


def _stalled_spotlight_recovery_candidate(
    safe_action: SafeAction,
    planned_action: PlannedAction,
    world_state: WorldState,
) -> bool:
    if not planned_action.mode.startswith("spotlight_reflex:"):
        return False
    maneuver = planned_action.mode.rsplit(":", maxsplit=1)[-1]
    if maneuver == "crawl":
        return True
    if safe_action.mode != "risk_nudge" or maneuver not in {"nudge_left", "nudge_right", "evasive_left", "evasive_right", "lane_recover"}:
        return False
    if world_state.collision_risk > 0.70:
        return False

    target_direction = _direction_to_target(world_state)
    planned_progress = planned_action.direction[0] * target_direction[0] + planned_action.direction[1] * target_direction[1]
    return planned_progress > 0.25


def _commit_wod_intersection_crossing(
    scenario: Scenario,
    safe_action: SafeAction,
    world_state: WorldState,
    perception: ScenePerception,
    steps: list[StepRecord],
) -> SafeAction:
    if len(steps) < 36 or world_state.goal_distance < 8.0 or world_state.collision_risk > 0.96:
        return safe_action

    row = _blocking_obstacle_row(scenario)
    if row is None:
        return safe_action
    row_x, target_y = row
    if world_state.position[0] < row_x - 9.0 or world_state.position[0] > row_x + 4.0:
        return safe_action

    recent = steps[-24:]
    recent_crossing = any(step.action_mode == "intersection_crossing" for step in steps[-8:])
    recent_progress = sum(step.progress or 0.0 for step in recent)
    recent_interventions = sum(1 for step in recent if step.intervention)
    recent_recovery_modes = sum(
        1
        for step in recent
        if step.action_mode in {"risk_nudge", "risk_escape", "cautious_follow", "progress_recovery", "deadlock_breakout", "guarded_evasive"}
        or step.action_mode.endswith(":crawl")
    )
    if not recent_crossing and (recent_progress > 8.0 or recent_interventions < 10 or recent_recovery_modes < 12):
        return safe_action

    current_y = world_state.position[1]
    local_row_clearance = _static_clearance_at(scenario, (row_x, current_y))
    local_exit_clearance = _static_clearance_at(scenario, (row_x + 5.0, current_y))
    if (
        (abs(current_y - target_y) > 2.5 or safe_action.mode in {"risk_escape", "risk_nudge"})
        and _lane_band_contains(scenario, (row_x, current_y), margin_scale=0.95)
        and local_row_clearance > 1.05
        and local_exit_clearance > 1.5
    ):
        target_y = current_y

    if world_state.position[0] < row_x - 2.0 and abs(current_y - target_y) > 0.75:
        target = (row_x - 3.5, target_y)
        speed = 0.95
    else:
        target = (row_x + 8.0, target_y)
        speed = 1.15
    direction = _normalize((target[0] - world_state.position[0], target[1] - world_state.position[1]))
    if direction == (0.0, 0.0):
        return safe_action

    next_clearance = _static_clearance_at(
        scenario,
        (
            world_state.position[0] + direction[0] * speed,
            world_state.position[1] + direction[1] * speed,
        ),
    )
    current_clearance = _static_clearance_at(scenario, world_state.position)
    if next_clearance < 1.05 and next_clearance < current_clearance + 0.10:
        return safe_action
    return SafeAction(direction=direction, speed=max(safe_action.speed, speed), mode="intersection_crossing", intervention=True)


def _step_record(
    tick: int,
    position: tuple[float, float],
    perception: ScenePerception,
    world_state: WorldState,
    safe_action: SafeAction,
    goal_distance: float,
    previous_goal_distance: float,
    min_obstacle_distance: float,
    active_actor_count: int,
    previous_speed: float | None,
    metadata: dict[str, Any],
    config: RolloutConfig,
    ego_state: EgoState,
) -> StepRecord:
    return StepRecord(
        t=tick,
        x=position[0],
        y=position[1],
        lane_error=perception.lane_error,
        min_obstacle_distance=min_obstacle_distance,
        uncertainty=world_state.uncertainty,
        collision_risk=world_state.collision_risk,
        obstacle_pressure=world_state.obstacle_pressure,
        route_blockage=world_state.route_blockage,
        corridor_blocked=world_state.corridor_blocked,
        left_clearance=world_state.left_clearance,
        right_clearance=world_state.right_clearance,
        preferred_escape_side=world_state.preferred_escape_side,
        world_model_summary=_world_model_summary(world_state),
        action_mode=safe_action.mode,
        speed=ego_state.speed_mps * config.dt_s,
        intervention=safe_action.intervention,
        goal_distance=goal_distance,
        progress=previous_goal_distance - goal_distance,
        comfort_cost=0.0 if previous_speed is None else abs(safe_action.speed - previous_speed),
        active_actor_count=active_actor_count,
        stall=safe_action.speed == 0.0 and goal_distance >= config.stall_goal_distance_m,
        **_spotlight_step_fields(metadata),
    )


def _spotlight_step_fields(metadata: dict[str, Any]) -> dict[str, Any]:
    if not metadata:
        return {}
    return {
        "candidate_count": int(metadata["candidate_count"]),
        "reference_count": int(metadata["reference_count"]),
        "selected_maneuver": str(metadata["selected_maneuver"]),
        "selector_score": float(metadata["selector_score"]),
        "selector_effective_score": float(metadata["selector_effective_score"]),
        "selector_3s_score": float(metadata["selector_3s_score"]),
        "selector_5s_score": float(metadata["selector_5s_score"]),
        "selector_3s_reference": str(metadata["selector_3s_reference"]),
        "selector_5s_reference": str(metadata["selector_5s_reference"]),
        "selector_3s_inside_region": bool(metadata["selector_3s_inside_region"]),
        "selector_5s_inside_region": bool(metadata["selector_5s_inside_region"]),
        "decision_reason": str(metadata["decision_reason"]),
        "decision_reasons": [str(reason) for reason in metadata["decision_reasons"]],
        "top_candidate_summaries": [dict(summary) for summary in metadata["top_candidate_summaries"]],
    }


def _world_model_summary(world_state: WorldState) -> str:
    return (
        f"pressure={world_state.obstacle_pressure:.2f}; "
        f"route_blockage={world_state.route_blockage:.2f}; "
        f"corridor_blocked={world_state.corridor_blocked}; "
        f"escape={world_state.preferred_escape_side}"
    )


def _direction_to_target(world_state: WorldState) -> tuple[float, float]:
    vector = (
        world_state.target_point[0] - world_state.position[0],
        world_state.target_point[1] - world_state.position[1],
    )
    norm = math.hypot(vector[0], vector[1])
    if norm == 0.0:
        return (0.0, 0.0)
    return (vector[0] / norm, vector[1] / norm)


def _blocking_obstacle_row(scenario: Scenario) -> tuple[float, float] | None:
    x_axis = (1.0, 0.0)
    y_axis = (0.0, 1.0)
    candidates = [
        obstacle
        for obstacle in scenario.obstacles
        if obstacle.kind != "ambient" and _lane_band_contains(scenario, (obstacle.x, obstacle.y), margin_scale=1.35)
    ]
    if len(candidates) < 3:
        return None

    row_obstacles = max(
        (_near_x_band(candidates, anchor.x, half_width=2.4) for anchor in candidates),
        key=len,
    )
    if len(row_obstacles) < 3:
        return None

    row_x = sum(obstacle.x for obstacle in row_obstacles) / len(row_obstacles)
    lane_y = min(scenario.lane_center, key=lambda point: abs(point[0] - row_x))[1]
    lower = lane_y - scenario.lane_half_width * 0.95
    upper = lane_y + scenario.lane_half_width * 0.95
    intervals = sorted(
        (
            max(lower, obstacle.y - obstacle_axis_extent(obstacle, y_axis) - 0.95),
            min(upper, obstacle.y + obstacle_axis_extent(obstacle, y_axis) + 0.95),
        )
        for obstacle in row_obstacles
        if lower <= obstacle.y + obstacle_axis_extent(obstacle, y_axis) and obstacle.y - obstacle_axis_extent(obstacle, y_axis) <= upper
    )

    gaps: list[tuple[float, float]] = []
    cursor = lower
    for start, end in intervals:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < upper:
        gaps.append((cursor, upper))
    if not gaps:
        return None

    usable = [gap for gap in gaps if gap[1] - gap[0] >= 1.2]
    if not usable:
        usable = gaps
    best = min(usable, key=lambda gap: (abs(((gap[0] + gap[1]) * 0.5) - lane_y), -(gap[1] - gap[0])))
    return row_x, (best[0] + best[1]) * 0.5


def _near_x_band(obstacles: list[Any], anchor_x: float, half_width: float) -> list[Any]:
    x_axis = (1.0, 0.0)
    return [
        obstacle
        for obstacle in obstacles
        if obstacle.x - obstacle_axis_extent(obstacle, x_axis) <= anchor_x + half_width
        and obstacle.x + obstacle_axis_extent(obstacle, x_axis) >= anchor_x - half_width
    ]


def _lane_band_contains(
    scenario: Scenario,
    point: tuple[float, float],
    margin_scale: float = 1.0,
) -> bool:
    lane_point = min(scenario.lane_center, key=lambda lane: math.dist(point, lane))
    return math.dist(point, lane_point) <= scenario.lane_half_width * margin_scale


def _static_clearance_at(scenario: Scenario, position: tuple[float, float]) -> float:
    return min_segment_clearance(position, position, scenario.obstacles, ego_radius=DEFAULT_EGO_RADIUS_M)


def _visible_clearance_after_step(
    world_state: WorldState,
    perception: ScenePerception,
    direction: tuple[float, float],
    speed: float,
) -> float:
    if not perception.visible_obstacles:
        return math.inf
    next_position = (
        world_state.position[0] + direction[0] * speed,
        world_state.position[1] + direction[1] * speed,
    )
    return min_segment_clearance(
        world_state.position,
        next_position,
        perception.visible_obstacles,
        ego_radius=DEFAULT_EGO_RADIUS_M,
    )


def _progress_recovery_direction(
    world_state: WorldState,
    perception: ScenePerception,
    planned_action: PlannedAction,
) -> tuple[float, float]:
    target_direction = _direction_to_target(world_state)
    if target_direction == (0.0, 0.0):
        target_direction = planned_action.direction
    if abs(perception.lane_error) > 3.0:
        lane_return = _normalize(
            (
                perception.lane_point[0] - world_state.position[0],
                perception.lane_point[1] - world_state.position[1],
            )
        )
        if lane_return != (0.0, 0.0):
            target_weight = 0.90 if abs(perception.lane_error) > 5.0 else 0.70
            lane_weight = 0.30 if abs(perception.lane_error) > 5.0 else 0.70
            target_direction = _normalize(
                (
                    target_direction[0] * target_weight + lane_return[0] * lane_weight,
                    target_direction[1] * target_weight + lane_return[1] * lane_weight,
                )
            )
    if target_direction == (0.0, 0.0) or not perception.visible_obstacles:
        return target_direction

    nearest = min(perception.visible_obstacles, key=lambda obstacle: obstacle.signed_distance)
    away = _normalize(
        (
            world_state.position[0] - nearest.x,
            world_state.position[1] - nearest.y,
        )
    )
    forward_component = away[0] * target_direction[0] + away[1] * target_direction[1]
    lateral = _normalize(
        (
            away[0] - forward_component * target_direction[0],
            away[1] - forward_component * target_direction[1],
        )
    )
    if lateral == (0.0, 0.0):
        lateral = (-target_direction[1], target_direction[0])
    return _normalize(
        (
            target_direction[0] * 0.78 + lateral[0] * 0.62,
            target_direction[1] * 0.78 + lateral[1] * 0.62,
        )
    )


def _normalize(vector: tuple[float, float]) -> tuple[float, float]:
    norm = math.hypot(vector[0], vector[1])
    if norm == 0.0:
        return (0.0, 0.0)
    return (vector[0] / norm, vector[1] / norm)


def advance_ego_state(
    ego_state: EgoState,
    target_direction: tuple[float, float],
    target_step_distance: float,
    config: RolloutConfig,
) -> EgoState:
    dt_s = max(config.dt_s, 1e-6)
    target_speed_mps = max(0.0, target_step_distance / dt_s)
    speed_delta = target_speed_mps - ego_state.speed_mps
    accel_limit = config.max_accel_mps2 if speed_delta >= 0.0 else config.max_decel_mps2
    speed_delta = _clamp(speed_delta, -accel_limit * dt_s, accel_limit * dt_s)
    speed_mps = max(0.0, ego_state.speed_mps + speed_delta)

    target_heading = ego_state.heading_rad if target_direction == (0.0, 0.0) else math.atan2(target_direction[1], target_direction[0])
    desired_steering = _clamp(_wrap_angle(target_heading - ego_state.heading_rad), -config.max_abs_steering_rad, config.max_abs_steering_rad)
    steering_delta = _clamp(
        desired_steering - ego_state.steering_rad,
        -config.max_steering_rate_rad_s * dt_s,
        config.max_steering_rate_rad_s * dt_s,
    )
    steering_rad = _clamp(
        ego_state.steering_rad + steering_delta,
        -config.max_abs_steering_rad,
        config.max_abs_steering_rad,
    )

    heading_rate = 0.0 if config.wheelbase_m <= 1e-6 else speed_mps / config.wheelbase_m * math.tan(steering_rad)
    heading_rad = _wrap_angle(ego_state.heading_rad + heading_rate * dt_s)
    step_distance = speed_mps * dt_s
    x = ego_state.x + math.cos(heading_rad) * step_distance
    y = ego_state.y + math.sin(heading_rad) * step_distance
    return EgoState(x=x, y=y, heading_rad=heading_rad, speed_mps=speed_mps, steering_rad=steering_rad)


def _initial_heading(scenario: Scenario) -> float:
    lane_points = route_centerline(scenario, samples_per_segment=4)
    if len(lane_points) >= 2:
        dx = lane_points[1][0] - scenario.start[0]
        dy = lane_points[1][1] - scenario.start[1]
        if not math.isclose(dx, 0.0, abs_tol=1e-9) or not math.isclose(dy, 0.0, abs_tol=1e-9):
            return math.atan2(dy, dx)
    dx = scenario.goal[0] - scenario.start[0]
    dy = scenario.goal[1] - scenario.start[1]
    return math.atan2(dy, dx) if not (math.isclose(dx, 0.0, abs_tol=1e-9) and math.isclose(dy, 0.0, abs_tol=1e-9)) else 0.0


def _wrap_angle(angle_rad: float) -> float:
    return math.atan2(math.sin(angle_rad), math.cos(angle_rad))


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
