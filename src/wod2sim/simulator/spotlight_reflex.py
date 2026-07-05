from __future__ import annotations

from dataclasses import dataclass, field
import math

from .environment import DEFAULT_EGO_RADIUS_M, SIM_TICK_DT_S, Actor, Obstacle, Scenario, actor_to_obstacle_at_time, min_segment_clearance, min_time_swept_clearance, static_obstacles_at_time
from .perception import ScenePerception, perceived_obstacle_axis_extent
from .planner import PlannedAction
from .trajectory_selector import TrajectoryCandidate, TrajectoryReference, TrajectorySelectorScore, TrajectorySelectorConfig, Trajectory, score_candidate
from .world_model import WorldState


@dataclass(frozen=True)
class ManeuverSpec:
    name: str
    min_speed_mps: float
    speed_scale: float
    lateral_offset_m: float
    lateral_profile: str = "smooth"


@dataclass(frozen=True)
class ReferenceRuleConfig:
    clear_obstacle_pressure_max: float = 0.25
    clear_uncertainty_max: float = 0.45
    clear_corridor_ratio_min: float = 0.35
    obstacle_pressure_min: float = 0.20
    high_pressure_evasive_min: float = 0.35  # above this, prefer evasive over nudge
    high_uncertainty_min: float = 0.55
    low_corridor_ratio_max: float = 0.25
    clear_maintain_score: float = 92.0
    clear_center_score: float = 88.0
    obstacle_slow_yield_score: float = 86.0
    obstacle_nudge_score: float = 91.0   # preferred at moderate pressure only
    obstacle_evasive_score: float = 94.0  # preferred at high pressure
    uncertainty_crawl_score: float = 90.0
    uncertainty_stop_score: float = 82.0
    lane_recover_score: float = 93.0
    default_maintain_score: float = 80.0
    default_slow_yield_score: float = 76.0
    lane_center_min_speed_mps: float = 0.75
    lane_recover_min_speed_mps: float = 0.5
    lane_recover_speed_scale: float = 0.65


@dataclass(frozen=True)
class SimulatorBackedScoreConfig:
    use_privileged_actor_forecast: bool = False
    min_action_clearance_m: float = 0.55
    unsafe_action_penalty: float = 1_000.0
    avoid_unnecessary_stop_penalty: float = 250.0
    progress_bonus_min: float = -20.0
    progress_bonus_max: float = 40.0
    goal_progress_weight: float = 2.5
    target_progress_weight: float = 4.0
    moving_speed_bonus_cap: float = 12.0
    moving_speed_bonus_weight: float = 6.0
    near_clearance_target_m: float = 2.0
    near_clearance_penalty_weight: float = 55.0
    horizon_clearance_target_m: float = 0.75
    horizon_clearance_penalty_weight: float = 12.0
    avoidance_side_clearance_delta_m: float = 0.25
    obstacle_ignore_behind_m: float = -1.0
    obstacle_weight_epsilon_m: float = 0.1
    obstacle_pressure_distance_m: float = 10.0


@dataclass(frozen=True)
class TrajectoryGenerationConfig:
    point_count: int = 20
    horizon_seconds: float = 5.0
    action_index: int = 3
    smoothstep_a: float = 3.0
    smoothstep_b: float = 2.0
    goal_heading_distance_m: float = 25.0


@dataclass(frozen=True)
class SpotlightReflexConfig:
    selector: TrajectorySelectorConfig = field(default_factory=TrajectorySelectorConfig)
    references: ReferenceRuleConfig = field(default_factory=ReferenceRuleConfig)
    scoring: SimulatorBackedScoreConfig = field(default_factory=SimulatorBackedScoreConfig)
    trajectory: TrajectoryGenerationConfig = field(default_factory=TrajectoryGenerationConfig)
    maneuvers: tuple[ManeuverSpec, ...] = (
        ManeuverSpec("stop", 0.0, 0.0, 0.0),
        ManeuverSpec("crawl", 0.35, 0.25, 0.0),
        ManeuverSpec("maintain", 0.75, 1.0, 0.0),
        ManeuverSpec("slow_yield", 0.45, 0.55, 0.0),
        ManeuverSpec("nudge_left", 0.65, 0.85, 2.0),
        ManeuverSpec("nudge_right", 0.65, 0.85, -2.0),
        ManeuverSpec("evasive_left", 0.55, 0.70, 8.0, "early"),
        ManeuverSpec("evasive_right", 0.55, 0.70, -8.0, "early"),
        ManeuverSpec("lane_recover", 0.50, 0.65, 0.0),
    )


DEFAULT_SPOTLIGHT_CONFIG = SpotlightReflexConfig()


@dataclass(frozen=True)
class SpotlightSelection:
    candidate: TrajectoryCandidate
    score: TrajectorySelectorScore
    candidate_count: int
    reference_count: int
    effective_score: float
    decision_reasons: tuple[str, ...]
    top_candidate_summaries: tuple[dict[str, object], ...]
    extra_metadata: dict[str, object] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, object]:
        metadata = {
            "candidate_count": self.candidate_count,
            "reference_count": self.reference_count,
            "selected_maneuver": self.candidate.name,
            "selector_score": self.score.combined_score,
            "selector_effective_score": self.effective_score,
            "selector_3s_score": self.score.score_3s,
            "selector_5s_score": self.score.score_5s,
            "selector_3s_reference": self.score.reference_3s_label,
            "selector_5s_reference": self.score.reference_5s_label,
            "selector_3s_inside_region": self.score.inside_3s_region,
            "selector_5s_inside_region": self.score.inside_5s_region,
            "decision_reason": "; ".join(self.decision_reasons[:6]),
            "decision_reasons": list(self.decision_reasons),
            "top_candidate_summaries": list(self.top_candidate_summaries),
        }
        metadata.update(self.extra_metadata)
        return metadata


@dataclass(frozen=True)
class CandidateScoreExplanation:
    candidate_name: str
    selector_score: float
    effective_score: float
    action_clearance_m: float
    horizon_clearance_m: float
    progress_bonus: float
    near_clearance_penalty: float
    horizon_clearance_penalty: float
    safety_penalty: float
    stop_penalty: float
    reference_3s_label: str
    reference_5s_label: str
    inside_3s_region: bool
    inside_5s_region: bool
    reasons: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        return {
            "candidate": self.candidate_name,
            "selector_score": _round_float(self.selector_score),
            "effective_score": _round_float(self.effective_score),
            "action_clearance_m": _round_float(self.action_clearance_m),
            "horizon_clearance_m": _round_float(self.horizon_clearance_m),
            "progress_bonus": _round_float(self.progress_bonus),
            "near_clearance_penalty": _round_float(self.near_clearance_penalty),
            "horizon_clearance_penalty": _round_float(self.horizon_clearance_penalty),
            "safety_penalty": _round_float(self.safety_penalty),
            "stop_penalty": _round_float(self.stop_penalty),
            "reference_3s": self.reference_3s_label,
            "reference_5s": self.reference_5s_label,
            "inside_3s_region": self.inside_3s_region,
            "inside_5s_region": self.inside_5s_region,
            "reasons": list(self.reasons[:8]),
        }


@dataclass(frozen=True)
class SpotlightCandidateEvaluation:
    candidate: TrajectoryCandidate
    score: TrajectorySelectorScore
    explanation: CandidateScoreExplanation


def generate_maneuver_candidates(
    position: tuple[float, float],
    heading: tuple[float, float],
    speed_mps: float,
    config: SpotlightReflexConfig | None = None,
) -> list[TrajectoryCandidate]:
    config = config or DEFAULT_SPOTLIGHT_CONFIG
    forward = _normalize(heading)
    if forward == (0.0, 0.0):
        forward = (1.0, 0.0)
    left = (-forward[1], forward[0])
    base_speed = max(0.0, speed_mps)

    candidates: list[TrajectoryCandidate] = []
    for spec in config.maneuvers:
        maneuver_speed = max(spec.min_speed_mps, base_speed * spec.speed_scale)
        trajectory = _trajectory(
            position,
            forward,
            left,
            maneuver_speed,
            spec.lateral_offset_m,
            lateral_profile=spec.lateral_profile,
            config=config.trajectory,
        )
        candidates.append(
            TrajectoryCandidate(
                name=spec.name,
                trajectory=trajectory,
                confidence=1.0,
                metadata={"speed_mps": maneuver_speed, "lateral_offset_m": spec.lateral_offset_m},
            )
        )
    return candidates


def generate_pseudo_references(
    scenario: Scenario,
    position: tuple[float, float],
    world_state: WorldState,
    perception: ScenePerception,
    speed_mps: float,
    heading: tuple[float, float] | None = None,
    config: SpotlightReflexConfig | None = None,
) -> list[TrajectoryReference]:
    config = config or DEFAULT_SPOTLIGHT_CONFIG
    rules = config.references
    reference_heading = heading if heading is not None else perception.lane_heading
    candidates = {
        candidate.name: candidate
        for candidate in generate_maneuver_candidates(position, reference_heading, speed_mps, config)
    }
    obstacle_pressure = _obstacle_pressure(perception, config.scoring)
    corridor_ratio = perception.corridor_margin / max(scenario.lane_half_width, 1e-6)
    uncertainty = max(world_state.uncertainty, perception.uncertainty)

    def _ref(name: str, token: str, score: float) -> TrajectoryReference | None:
        c = candidates.get(token)
        return TrajectoryReference(name, c.trajectory, score) if c is not None else None

    references: list[TrajectoryReference] = []
    if (
        obstacle_pressure < rules.clear_obstacle_pressure_max
        and uncertainty < rules.clear_uncertainty_max
        and corridor_ratio > rules.clear_corridor_ratio_min
    ):
        r = _ref("clear_corridor_maintain", "maintain", rules.clear_maintain_score)
        if r:
            references.append(r)
        references.append(
            TrajectoryReference(
                "clear_corridor_center_progress",
                _lane_center_reference(position, world_state, speed_mps, config),
                rules.clear_center_score,
            )
        )

    if obstacle_pressure >= rules.obstacle_pressure_min:
        side = _avoidance_side(position, perception, candidates, scenario, config)
        r = _ref("obstacle_pressure_slow_yield", "slow_yield", rules.obstacle_slow_yield_score)
        if r:
            references.append(r)
        if obstacle_pressure >= rules.high_pressure_evasive_min:
            # High pressure: prefer evasive (large lateral displacement); skip nudge reference
            # so nudge does not win over evasive via score alone
            r = _ref(f"obstacle_pressure_evasive_{side}", f"evasive_{side}", rules.obstacle_evasive_score)
            if r:
                references.append(r)
        else:
            # Moderate pressure: nudge is preferred (small correction), evasive as backup
            r = _ref(f"obstacle_pressure_nudge_{side}", f"nudge_{side}", rules.obstacle_nudge_score)
            if r:
                references.append(r)
            r = _ref(f"obstacle_pressure_evasive_{side}", f"evasive_{side}", rules.obstacle_evasive_score)
            if r:
                references.append(r)

    if uncertainty >= rules.high_uncertainty_min:
        for token, rname, score in [
            ("crawl", "high_uncertainty_crawl", rules.uncertainty_crawl_score),
            ("stop", "high_uncertainty_stop", rules.uncertainty_stop_score),
        ]:
            r = _ref(rname, token, score)
            if r:
                references.append(r)

    if corridor_ratio < rules.low_corridor_ratio_max:
        references.append(
            TrajectoryReference(
                "low_corridor_margin_lane_recover",
                _lane_recover_reference(position, perception, speed_mps, reference_heading, config),
                rules.lane_recover_score,
            )
        )

    if not references:
        for token, rname, score in [
            ("maintain", "default_maintain", rules.default_maintain_score),
            ("slow_yield", "default_slow_yield", rules.default_slow_yield_score),
            ("stop", "default_stop", rules.uncertainty_stop_score),
        ]:
            r = _ref(rname, token, score)
            if r:
                references.append(r)

    return references


def select_maneuver(
    scenario: Scenario,
    position: tuple[float, float],
    world_state: WorldState,
    perception: ScenePerception,
    speed_mps: float,
    config: SpotlightReflexConfig | None = None,
) -> SpotlightSelection:
    config = config or DEFAULT_SPOTLIGHT_CONFIG
    evaluations, reference_count = evaluate_maneuver_candidates(
        scenario,
        position,
        world_state,
        perception,
        speed_mps,
        config,
    )
    best_evaluation = evaluations[0]
    for evaluation in evaluations[1:]:
        if (
            evaluation.explanation.effective_score,
            evaluation.candidate.confidence,
        ) > (
            best_evaluation.explanation.effective_score,
            best_evaluation.candidate.confidence,
        ):
            best_evaluation = evaluation

    top_candidate_summaries = tuple(
        evaluation.explanation.to_summary()
        for evaluation in sorted(evaluations, key=lambda item: item.explanation.effective_score, reverse=True)[:3]
    )
    return SpotlightSelection(
        best_evaluation.candidate,
        best_evaluation.score,
        len(evaluations),
        reference_count,
        best_evaluation.explanation.effective_score,
        best_evaluation.explanation.reasons,
        top_candidate_summaries,
    )


def evaluate_maneuver_candidates(
    scenario: Scenario,
    position: tuple[float, float],
    world_state: WorldState,
    perception: ScenePerception,
    speed_mps: float,
    config: SpotlightReflexConfig | None = None,
) -> tuple[list[SpotlightCandidateEvaluation], int]:
    config = config or DEFAULT_SPOTLIGHT_CONFIG
    heading = _planning_heading(position, world_state, perception, scenario, config)
    candidates = generate_maneuver_candidates(position, heading, speed_mps, config)
    references = generate_pseudo_references(scenario, position, world_state, perception, speed_mps, heading, config)
    moving_candidate_is_safe = any(
        candidate.name != "stop" and _action_clearance(candidate.trajectory, scenario, config) >= config.scoring.min_action_clearance_m
        for candidate in candidates
    )
    evaluations: list[SpotlightCandidateEvaluation] = []
    for candidate in candidates:
        candidate_score = score_candidate(candidate, references, speed_mps, config.selector)
        explanation = _explain_simulator_backed_score(
            candidate_score,
            candidate,
            scenario,
            position,
            world_state,
            moving_candidate_is_safe,
            config,
        )
        evaluations.append(
            SpotlightCandidateEvaluation(
                candidate=candidate,
                score=candidate_score,
                explanation=explanation,
            )
        )
    return evaluations, len(references)


def plan_spotlight_reflex_action(
    scenario: Scenario,
    position: tuple[float, float],
    world_state: WorldState,
    perception: ScenePerception,
    nominal_step_size: float = 1.25,
    config: SpotlightReflexConfig | None = None,
) -> tuple[PlannedAction, SpotlightSelection]:
    config = config or DEFAULT_SPOTLIGHT_CONFIG
    speed_mps = max(0.0, nominal_step_size)
    selection = select_maneuver(scenario, position, world_state, perception, speed_mps, config)
    next_point = selection.candidate.trajectory[config.trajectory.action_index]
    step_vector = (next_point[0] - position[0], next_point[1] - position[1])
    step_distance = math.hypot(step_vector[0], step_vector[1])
    direction = _normalize(step_vector)
    action = PlannedAction(
        direction=direction,
        speed=step_distance,
        mode=f"spotlight_reflex:{selection.candidate.name}",
        score=selection.score.combined_score,
    )
    return action, selection


def _simulator_backed_score(
    score: TrajectorySelectorScore,
    candidate: TrajectoryCandidate,
    scenario: Scenario,
    position: tuple[float, float],
    world_state: WorldState,
    moving_candidate_is_safe: bool,
    config: SpotlightReflexConfig,
) -> float:
    return _explain_simulator_backed_score(
        score,
        candidate,
        scenario,
        position,
        world_state,
        moving_candidate_is_safe,
        config,
    ).effective_score


def _explain_simulator_backed_score(
    score: TrajectorySelectorScore,
    candidate: TrajectoryCandidate,
    scenario: Scenario,
    position: tuple[float, float],
    world_state: WorldState,
    moving_candidate_is_safe: bool,
    config: SpotlightReflexConfig,
) -> CandidateScoreExplanation:
    scoring = config.scoring
    action_clearance = _action_clearance(candidate.trajectory, scenario, config, origin=position)
    full_clearance = _min_obstacle_clearance_with_config(candidate.trajectory, scenario, config, origin=position)
    progress_bonus = 0.0
    near_penalty = 0.0
    horizon_penalty = 0.0
    safety_penalty = 0.0
    stop_penalty = 0.0
    reasons = [
        f"3s_reference={score.reference_3s_label}",
        f"5s_reference={score.reference_5s_label}",
        "inside_3s_region" if score.inside_3s_region else "outside_3s_region",
        "inside_5s_region" if score.inside_5s_region else "outside_5s_region",
        f"action_clearance={action_clearance:.2f}m",
        f"horizon_clearance={full_clearance:.2f}m",
    ]

    if action_clearance < scoring.min_action_clearance_m:
        safety_penalty = scoring.unsafe_action_penalty
        reasons.append(f"unsafe_action_penalty={safety_penalty:.1f}")
        return CandidateScoreExplanation(
            candidate_name=candidate.name,
            selector_score=score.combined_score,
            effective_score=score.combined_score - safety_penalty,
            action_clearance_m=action_clearance,
            horizon_clearance_m=full_clearance,
            progress_bonus=progress_bonus,
            near_clearance_penalty=near_penalty,
            horizon_clearance_penalty=horizon_penalty,
            safety_penalty=safety_penalty,
            stop_penalty=stop_penalty,
            reference_3s_label=score.reference_3s_label,
            reference_5s_label=score.reference_5s_label,
            inside_3s_region=score.inside_3s_region,
            inside_5s_region=score.inside_5s_region,
            reasons=tuple(reasons),
        )

    if candidate.name == "stop" and moving_candidate_is_safe:
        stop_penalty = scoring.avoid_unnecessary_stop_penalty
        reasons.append(f"moving_candidate_available_stop_penalty={stop_penalty:.1f}")
        return CandidateScoreExplanation(
            candidate_name=candidate.name,
            selector_score=score.combined_score,
            effective_score=score.combined_score - stop_penalty,
            action_clearance_m=action_clearance,
            horizon_clearance_m=full_clearance,
            progress_bonus=progress_bonus,
            near_clearance_penalty=near_penalty,
            horizon_clearance_penalty=horizon_penalty,
            safety_penalty=safety_penalty,
            stop_penalty=stop_penalty,
            reference_3s_label=score.reference_3s_label,
            reference_5s_label=score.reference_5s_label,
            inside_3s_region=score.inside_3s_region,
            inside_5s_region=score.inside_5s_region,
            reasons=tuple(reasons),
        )

    action_point = candidate.trajectory[min(config.trajectory.action_index, len(candidate.trajectory) - 1)]
    final_point = candidate.trajectory[-1]
    goal_progress = math.dist(position, scenario.goal) - math.dist(final_point, scenario.goal)
    target_progress = math.dist(position, world_state.target_point) - math.dist(action_point, world_state.target_point)
    progress_bonus = max(
        scoring.progress_bonus_min,
        min(
            scoring.progress_bonus_max,
            goal_progress * scoring.goal_progress_weight + target_progress * scoring.target_progress_weight,
        ),
    )
    if candidate.name != "stop":
        speed_bonus = min(
            scoring.moving_speed_bonus_cap,
            float(candidate.metadata.get("speed_mps", 0.0)) * scoring.moving_speed_bonus_weight,
        )
        progress_bonus += speed_bonus
        reasons.append(f"moving_speed_bonus={speed_bonus:.2f}")
    near_penalty = max(0.0, scoring.near_clearance_target_m - action_clearance) * scoring.near_clearance_penalty_weight
    horizon_penalty = max(0.0, scoring.horizon_clearance_target_m - full_clearance) * scoring.horizon_clearance_penalty_weight
    reasons.append(f"progress_bonus={progress_bonus:.2f}")
    if near_penalty > 0.0:
        reasons.append(f"near_clearance_penalty={near_penalty:.2f}")
    if horizon_penalty > 0.0:
        reasons.append(f"horizon_clearance_penalty={horizon_penalty:.2f}")
    effective_score = score.combined_score + progress_bonus - near_penalty - horizon_penalty
    return CandidateScoreExplanation(
        candidate_name=candidate.name,
        selector_score=score.combined_score,
        effective_score=effective_score,
        action_clearance_m=action_clearance,
        horizon_clearance_m=full_clearance,
        progress_bonus=progress_bonus,
        near_clearance_penalty=near_penalty,
        horizon_clearance_penalty=horizon_penalty,
        safety_penalty=safety_penalty,
        stop_penalty=stop_penalty,
        reference_3s_label=score.reference_3s_label,
        reference_5s_label=score.reference_5s_label,
        inside_3s_region=score.inside_3s_region,
        inside_5s_region=score.inside_5s_region,
        reasons=tuple(reasons),
    )


def _round_float(value: float) -> float | str:
    if math.isinf(value):
        return "inf" if value > 0.0 else "-inf"
    if math.isnan(value):
        return "nan"
    return round(float(value), 3)


def _action_clearance(
    trajectory: Trajectory,
    scenario: Scenario,
    config: SpotlightReflexConfig | None = None,
    origin: tuple[float, float] | None = None,
) -> float:
    config = config or DEFAULT_SPOTLIGHT_CONFIG
    return _min_obstacle_clearance_with_config(trajectory[: config.trajectory.action_index + 1], scenario, config, origin=origin)


def _min_obstacle_clearance(
    trajectory: Trajectory,
    scenario: Scenario,
    origin: tuple[float, float] | None = None,
) -> float:
    return _min_obstacle_clearance_with_config(trajectory, scenario, DEFAULT_SPOTLIGHT_CONFIG, origin=origin)


def _min_obstacle_clearance_with_config(
    trajectory: Trajectory,
    scenario: Scenario,
    config: SpotlightReflexConfig,
    origin: tuple[float, float] | None = None,
) -> float:
    min_clearance = math.inf
    previous_point = origin
    for point_index, point in enumerate(trajectory):
        start = point if previous_point is None else previous_point
        clearance = _trajectory_segment_clearance(start, point, scenario, point_index, config)
        if clearance < min_clearance:
            min_clearance = clearance
        previous_point = point
    return min_clearance


def _trajectory_segment_clearance(
    start: tuple[float, float],
    end: tuple[float, float],
    scenario: Scenario,
    point_index: int,
    config: SpotlightReflexConfig,
) -> float:
    if not config.scoring.use_privileged_actor_forecast or not scenario.actors:
        return min_segment_clearance(start, end, scenario.obstacles, ego_radius=DEFAULT_EGO_RADIUS_M)

    current_tick = float(scenario.environment.get("tick", 0))
    segment_start_seconds = (point_index / config.trajectory.point_count) * config.trajectory.horizon_seconds
    segment_end_seconds = ((point_index + 1) / config.trajectory.point_count) * config.trajectory.horizon_seconds
    return min_time_swept_clearance(
        scenario,
        start,
        end,
        current_tick + segment_start_seconds / SIM_TICK_DT_S,
        current_tick + segment_end_seconds / SIM_TICK_DT_S,
        ego_radius=DEFAULT_EGO_RADIUS_M,
    )


def _trajectory_step_obstacles(
    scenario: Scenario,
    point_index: int,
    config: SpotlightReflexConfig,
) -> list[Obstacle]:
    if not config.scoring.use_privileged_actor_forecast or not scenario.actors:
        return scenario.obstacles

    cache = scenario.environment.setdefault("_forecast_obstacles_by_point_index", {})
    if point_index in cache:
        return cache[point_index]

    static_obstacles, moving_actors = _forecast_static_and_moving_obstacles(scenario)
    current_tick = float(scenario.environment.get("tick", 0))
    point_seconds = ((point_index + 1) / config.trajectory.point_count) * config.trajectory.horizon_seconds
    actor_obstacles = [
        obstacle
        for actor in moving_actors
        if (obstacle := actor_to_obstacle_at_time(actor, current_tick + point_seconds / SIM_TICK_DT_S)) is not None
    ]
    obstacles = static_obstacles + actor_obstacles
    cache[point_index] = obstacles
    return obstacles


def _forecast_static_and_moving_obstacles(scenario: Scenario) -> tuple[list[Obstacle], list[Actor]]:
    cache_key = "_forecast_static_and_moving_obstacles"
    if cache_key in scenario.environment:
        return scenario.environment[cache_key]

    moving_actors = [actor for actor in scenario.actors if _actor_is_moving(actor)]
    if not moving_actors:
        result = (scenario.obstacles, [])
        scenario.environment[cache_key] = result
        return result

    current_tick = float(scenario.environment.get("tick", 0))
    static_obstacles = static_obstacles_at_time(scenario, current_tick)
    result = (static_obstacles, moving_actors)
    scenario.environment[cache_key] = result
    return result


def _actor_is_moving(actor: Actor) -> bool:
    return any(abs(float(getattr(actor, field_name))) > 1e-9 for field_name in ("speed", "vx", "vy"))


def _trajectory(
    position: tuple[float, float],
    forward: tuple[float, float],
    left: tuple[float, float],
    speed_mps: float,
    final_lateral_offset: float,
    lateral_profile: str = "smooth",
    config: TrajectoryGenerationConfig | None = None,
) -> Trajectory:
    config = config or DEFAULT_SPOTLIGHT_CONFIG.trajectory
    points: Trajectory = []
    for step in range(1, config.point_count + 1):
        t = step / config.point_count
        seconds = t * config.horizon_seconds
        lateral_t = _lateral_interpolation(t, lateral_profile, config)
        forward_distance = speed_mps * seconds
        lateral_distance = final_lateral_offset * lateral_t
        points.append(
            (
                position[0] + forward[0] * forward_distance + left[0] * lateral_distance,
                position[1] + forward[1] * forward_distance + left[1] * lateral_distance,
            )
        )
    return points


def _lateral_interpolation(t: float, profile: str, config: TrajectoryGenerationConfig | None = None) -> float:
    config = config or DEFAULT_SPOTLIGHT_CONFIG.trajectory
    if profile == "smooth":
        return t * t * (config.smoothstep_a - config.smoothstep_b * t)
    if profile == "early":
        return math.sqrt(t)
    raise ValueError(f"unknown lateral trajectory profile: {profile}")


def _lane_center_reference(
    position: tuple[float, float],
    world_state: WorldState,
    speed_mps: float,
    config: SpotlightReflexConfig | None = None,
) -> Trajectory:
    config = config or DEFAULT_SPOTLIGHT_CONFIG
    forward = _normalize((world_state.target_point[0] - position[0], world_state.target_point[1] - position[1]))
    if forward == (0.0, 0.0):
        forward = (1.0, 0.0)
    left = (-forward[1], forward[0])
    return _trajectory(
        position,
        forward,
        left,
        max(config.references.lane_center_min_speed_mps, speed_mps),
        0.0,
        config=config.trajectory,
    )


def _lane_recover_reference(
    position: tuple[float, float],
    perception: ScenePerception,
    speed_mps: float,
    heading: tuple[float, float] | None = None,
    config: SpotlightReflexConfig | None = None,
) -> Trajectory:
    config = config or DEFAULT_SPOTLIGHT_CONFIG
    forward = _normalize(heading if heading is not None else perception.lane_heading)
    if forward == (0.0, 0.0):
        forward = (1.0, 0.0)
    left = (-forward[1], forward[0])
    dx = perception.lane_point[0] - position[0]
    dy = perception.lane_point[1] - position[1]
    lateral_offset = dx * left[0] + dy * left[1]
    return _trajectory(
        position,
        forward,
        left,
        max(config.references.lane_recover_min_speed_mps, speed_mps * config.references.lane_recover_speed_scale),
        lateral_offset,
        config=config.trajectory,
    )


def _planning_heading(
    position: tuple[float, float],
    world_state: WorldState,
    perception: ScenePerception,
    scenario: Scenario,
    config: SpotlightReflexConfig | None = None,
) -> tuple[float, float]:
    config = config or DEFAULT_SPOTLIGHT_CONFIG
    goal_vector = (scenario.goal[0] - position[0], scenario.goal[1] - position[1])
    goal_heading = _normalize(goal_vector)
    lane_heading = _normalize(perception.lane_heading)
    if lane_heading == (0.0, 0.0) or math.dist(position, scenario.goal) < config.trajectory.goal_heading_distance_m:
        return goal_heading
    return lane_heading


def _normalize(vector: tuple[float, float]) -> tuple[float, float]:
    norm = math.hypot(vector[0], vector[1])
    if norm == 0.0:
        return (0.0, 0.0)
    return (vector[0] / norm, vector[1] / norm)


def _obstacle_pressure(
    perception: ScenePerception,
    config: SimulatorBackedScoreConfig | None = None,
) -> float:
    config = config or DEFAULT_SPOTLIGHT_CONFIG.scoring
    nearest_signed_distance = min(
        (obstacle.signed_distance for obstacle in perception.visible_obstacles),
        default=config.obstacle_pressure_distance_m * 2.0,
    )
    return max(0.0, min(1.0, (config.obstacle_pressure_distance_m - nearest_signed_distance) / config.obstacle_pressure_distance_m))


def _avoidance_side(
    position: tuple[float, float],
    perception: ScenePerception,
    candidates: dict[str, TrajectoryCandidate],
    scenario: Scenario,
    config: SpotlightReflexConfig | None = None,
) -> str:
    config = config or DEFAULT_SPOTLIGHT_CONFIG
    scoring = config.scoring

    def _side_clearance(side: str) -> float:
        vals = [
            _min_obstacle_clearance_with_config(c.trajectory, scenario, config)
            for name in (f"nudge_{side}", f"evasive_{side}")
            if (c := candidates.get(name)) is not None
        ]
        return max(vals) if vals else 0.0

    left_clearance = _side_clearance("left")
    right_clearance = _side_clearance("right")
    if abs(left_clearance - right_clearance) > scoring.avoidance_side_clearance_delta_m:
        return "left" if left_clearance > right_clearance else "right"

    forward = _normalize(perception.lane_heading)
    if forward == (0.0, 0.0):
        forward = (1.0, 0.0)
    left = (-forward[1], forward[0])
    weighted_lateral = 0.0
    total_weight = 0.0
    for obstacle in perception.visible_obstacles:
        dx = obstacle.x - position[0]
        dy = obstacle.y - position[1]
        forward_distance = dx * forward[0] + dy * forward[1]
        if forward_distance < scoring.obstacle_ignore_behind_m:
            continue
        lateral = dx * left[0] + dy * left[1]
        lateral_extent = perceived_obstacle_axis_extent(obstacle, left)
        weight = 1.0 / max(
            obstacle.signed_distance + obstacle.radius + scoring.obstacle_weight_epsilon_m,
            scoring.obstacle_weight_epsilon_m,
        )
        weighted_lateral += (lateral + math.copysign(lateral_extent, lateral if lateral != 0.0 else 1.0)) * weight
        total_weight += weight
    if total_weight == 0.0:
        return "left"
    return "right" if weighted_lateral > 0.0 else "left"
