from __future__ import annotations

from dataclasses import dataclass
import math

from .environment import DEFAULT_EGO_RADIUS_M, Scenario, min_time_swept_clearance, nearest_lane_point, route_centerline, scenario_at_state
from .perception import perceive_scene
from .policy import EgoState, Rollout, RolloutConfig, StepRecord, advance_ego_state
from .world_model import update_world_state


@dataclass(frozen=True)
class OracleConfig:
    speed_scales: tuple[float, ...] = (1.0, 0.65, 0.35, 0.0)
    steering_angles_rad: tuple[float, ...] = (-1.1, -0.55, 0.0, 0.55, 1.1)
    horizon_steps: int = 5
    lane_samples_per_segment: int = 12
    lookahead_samples: int = 24
    max_steps: int = 220
    step_size: float = 1.35
    goal_tolerance_m: float = 3.0
    stall_goal_distance_m: float = 3.0
    solvable_min_clearance_m: float = 0.25
    yield_speed_scale_max: float = 0.5
    avoidance_angle_threshold_rad: float = 0.2
    collision_penalty: float = 1_000_000.0
    collision_penalty_slope: float = 10_000.0
    lane_error_fraction: float = 0.75
    clearance_score_cap_m: float = 5.0
    clearance_score_weight: float = 22.0
    progress_score_weight: float = 18.0
    lane_penalty_weight: float = 12.0
    stopped_penalty: float = 0.15


DEFAULT_ORACLE_CONFIG = OracleConfig()


@dataclass(frozen=True)
class OracleCertificate:
    solvable: bool
    reasoning_trace: str
    rollout: Rollout
    min_clearance: float
    intervention_free: bool


def run_oracle_policy(
    scenario: Scenario,
    max_steps: int = 220,
    step_size: float = 1.35,
    config: OracleConfig | None = None,
) -> OracleCertificate:
    """Run a privileged receding-horizon oracle over full simulator state.

    The oracle is not a submitted driving policy. It sees future actor positions
    over a short horizon and exists to check that a generated scenario has a
    feasible route through the current abstract simulator.
    """
    config = _oracle_config(config, max_steps, step_size)
    dynamics = _oracle_rollout_config(config)
    ego_state = EgoState(
        x=scenario.start[0],
        y=scenario.start[1],
        heading_rad=_initial_heading(scenario),
        speed_mps=0.0,
        steering_rad=0.0,
    )
    dense_lane = route_centerline(scenario, samples_per_segment=config.lane_samples_per_segment)
    steps: list[StepRecord] = []
    collision = False
    reached_goal = False
    runtime_state: dict[str, object] = {}

    for tick in range(config.max_steps):
        position = (ego_state.x, ego_state.y)
        previous_position = position
        active_scenario, runtime_state = scenario_at_state(scenario, tick, position, runtime_state)
        direction, target_step_distance, mode = _choose_privileged_action(scenario, position, tick, dense_lane, config, ego_state)
        ego_state = advance_ego_state(ego_state, direction, target_step_distance, dynamics)
        position = (ego_state.x, ego_state.y)

        perception = perceive_scene(active_scenario, position)
        world_state = update_world_state(active_scenario, position, perception)
        min_clearance = min_time_swept_clearance(
            scenario,
            previous_position,
            position,
            tick,
            tick + 1,
            ego_radius=DEFAULT_EGO_RADIUS_M,
        )
        collision = min_clearance <= 0.0
        previous_goal_distance = math.dist(previous_position, scenario.goal)
        goal_distance = math.dist(position, scenario.goal)
        steps.append(
            StepRecord(
                t=tick,
                x=position[0],
                y=position[1],
                lane_error=perception.lane_error,
                min_obstacle_distance=min_clearance,
                uncertainty=world_state.uncertainty,
                collision_risk=world_state.collision_risk,
                action_mode=f"oracle:{mode}",
                speed=ego_state.speed_mps * dynamics.dt_s,
                intervention=False,
                goal_distance=goal_distance,
                progress=previous_goal_distance - goal_distance,
                comfort_cost=0.0 if not steps else abs(ego_state.speed_mps * dynamics.dt_s - steps[-1].speed),
                active_actor_count=len(active_scenario.actors),
                stall=ego_state.speed_mps * dynamics.dt_s == 0.0 and goal_distance >= config.stall_goal_distance_m,
            )
        )

        if collision:
            break
        if goal_distance < config.goal_tolerance_m:
            reached_goal = True
            break

    rollout = Rollout(success=reached_goal and not collision, collision=collision, reached_goal=reached_goal, steps=steps)
    min_clearance = min((step.min_obstacle_distance for step in steps), default=math.inf)
    trace = oracle_reasoning_trace(scenario, rollout)
    return OracleCertificate(
        solvable=rollout.success and min_clearance > config.solvable_min_clearance_m,
        reasoning_trace=trace,
        rollout=rollout,
        min_clearance=min_clearance,
        intervention_free=True,
    )


def _oracle_config(config: OracleConfig | None, max_steps: int, step_size: float) -> OracleConfig:
    if config is not None:
        return config
    if max_steps == DEFAULT_ORACLE_CONFIG.max_steps and step_size == DEFAULT_ORACLE_CONFIG.step_size:
        return DEFAULT_ORACLE_CONFIG
    return OracleConfig(max_steps=max_steps, step_size=step_size)


def _oracle_rollout_config(config: OracleConfig) -> RolloutConfig:
    return RolloutConfig(
        max_steps=config.max_steps,
        step_size=config.step_size,
        dt_s=1.0,
        goal_tolerance_m=config.goal_tolerance_m,
        stall_goal_distance_m=config.stall_goal_distance_m,
    )


def oracle_reasoning_trace(scenario: Scenario, rollout: Rollout | None = None) -> str:
    hazard = scenario.tags.get("primary_hazard_type", "unknown_hazard")
    composition = scenario.tags.get("hazard_composition", hazard)
    topology = scenario.tags.get("topology", scenario.cluster)
    condition = scenario.tags.get("condition", scenario.environment.get("weather", "unknown_condition"))
    decision = scenario.tags.get("intended_decision", "maintain_safe_progress")
    status = "feasibility_check_passed" if rollout is None or rollout.success else "feasibility_check_failed"
    return (
        f"{status}: topology={topology}; condition={condition}; hazards={composition}; "
        f"primary={hazard}; required_decision={decision}; response=preserve clearance, "
        "yield to dynamic conflicts, avoid static blockers, then recover to route."
    )


def _choose_privileged_action(
    scenario: Scenario,
    position: tuple[float, float],
    tick: int,
    dense_lane: list[tuple[float, float]],
    config: OracleConfig,
    ego_state: EgoState,
) -> tuple[tuple[float, float], float, str]:
    target = _lookahead_target(scenario, position, dense_lane, config)
    base = _normalize((target[0] - position[0], target[1] - position[1]))
    if base == (0.0, 0.0):
        base = _normalize((scenario.goal[0] - position[0], scenario.goal[1] - position[1]))
    candidates: list[tuple[float, tuple[float, float], float, str]] = []
    for speed_scale in config.speed_scales:
        for angle in config.steering_angles_rad:
            direction = _normalize(_rotate(base, angle))
            speed = config.step_size * speed_scale
            score = _horizon_score(scenario, ego_state, direction, speed, tick, config)
            mode = _candidate_mode(speed_scale, angle, config)
            candidates.append((score, direction, speed, mode))
    _, direction, speed, mode = max(candidates, key=lambda item: item[0])
    return direction, speed, mode


def _candidate_mode(speed_scale: float, angle: float, config: OracleConfig) -> str:
    if speed_scale <= config.yield_speed_scale_max:
        return "yield"
    if angle > config.avoidance_angle_threshold_rad:
        return "avoid_left"
    if angle < -config.avoidance_angle_threshold_rad:
        return "avoid_right"
    return "progress"


def _horizon_score(
    scenario: Scenario,
    ego_state: EgoState,
    direction: tuple[float, float],
    target_step_distance: float,
    tick: int,
    config: OracleConfig,
) -> float:
    dynamics = _oracle_rollout_config(config)
    simulated = ego_state
    min_clearance = math.inf
    progress = 0.0
    lane_penalty = 0.0
    for horizon_offset in range(config.horizon_steps):
        active = scenario_at_tick(scenario, tick + horizon_offset)
        current_position = (simulated.x, simulated.y)
        previous_goal = math.dist(current_position, scenario.goal)
        next_state = advance_ego_state(simulated, direction, target_step_distance, dynamics)
        next_position = (next_state.x, next_state.y)
        step_clearance = min_time_swept_clearance(
            scenario,
            current_position,
            next_position,
            tick + horizon_offset,
            tick + horizon_offset + 1,
            ego_radius=DEFAULT_EGO_RADIUS_M,
        )
        simulated = next_state
        progress += previous_goal - math.dist(next_position, scenario.goal)
        min_clearance = min(min_clearance, step_clearance)
        if step_clearance < 0.0:
            return -config.collision_penalty + step_clearance * config.collision_penalty_slope
        perception = perceive_scene(active, next_position)
        lane_penalty += max(0.0, perception.lane_error - active.lane_half_width * config.lane_error_fraction)
    clearance_score = min(config.clearance_score_cap_m, min_clearance) * config.clearance_score_weight
    return (
        progress * config.progress_score_weight
        + clearance_score
        - lane_penalty * config.lane_penalty_weight
        - (config.stopped_penalty if speed == 0.0 else 0.0)
    )


def _lookahead_target(
    scenario: Scenario,
    position: tuple[float, float],
    dense_lane: list[tuple[float, float]],
    config: OracleConfig,
) -> tuple[float, float]:
    best_index, _, _ = nearest_lane_point(position, dense_lane)
    if best_index >= len(dense_lane) - config.lookahead_samples:
        return scenario.goal
    return dense_lane[min(len(dense_lane) - 1, best_index + config.lookahead_samples)]


def _normalize(vector: tuple[float, float]) -> tuple[float, float]:
    norm = math.hypot(vector[0], vector[1])
    if norm == 0.0:
        return (0.0, 0.0)
    return (vector[0] / norm, vector[1] / norm)


def _rotate(vector: tuple[float, float], angle: float) -> tuple[float, float]:
    c = math.cos(angle)
    s = math.sin(angle)
    return (vector[0] * c - vector[1] * s, vector[0] * s + vector[1] * c)


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
