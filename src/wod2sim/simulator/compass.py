from __future__ import annotations

from dataclasses import asdict, dataclass, field
import argparse
import json
from pathlib import Path
from typing import Callable

from .compositional_scenarios import (
    COMPOSITIONAL_SUITES,
    CompositionalScenarioProfile,
    CorridorClearanceConfig,
    DEFAULT_COMPOSITIONAL_PROFILE,
    DifficultyConfig,
    AmbientGeometryConfig,
    EnvironmentConfig,
    HazardGeometryConfig,
    TopologyGeometryConfig,
    generate_compositional_scenario,
)
from .environment import Obstacle, Scenario
from .oracle import DEFAULT_ORACLE_CONFIG, OracleCertificate, OracleConfig, run_oracle_policy
from .policy import Rollout, run_policy, run_spotlight_reflex_policy
from .wod_scenarios import WOD_E2E_CLUSTERS, generate_wod_scenario


PolicyFn = Callable[..., Rollout]

REASONING_SCORE_SOURCE = "diagnostic_rollout_trace_overlap_v0_not_official"


@dataclass(frozen=True)
class CompassLevel:
    level: int
    name: str
    suite: str
    description: str
    official: bool


@dataclass(frozen=True)
class CompassScoreWeights:
    safety: float = 0.30
    route_quality: float = 0.25
    comfort: float = 0.15
    recovery: float = 0.15
    generalization: float = 0.15


@dataclass(frozen=True)
class DrivingQualityConfig:
    success_score: float = 10.0
    failure_score: float = 2.0
    collision_penalty: float = 10.0
    clearance_target_m: float = 2.0
    clearance_zero_m: float = 0.0
    progress_target_m_per_step: float = 1.0
    route_lane_error_target_m: float = 0.35
    route_lane_error_zero_m: float = 4.0
    intervention_rate_target: float = 0.10
    intervention_rate_zero: float = 0.70
    comfort_cost_target: float = 0.10
    comfort_cost_zero: float = 1.20
    stall_rate_target: float = 0.00
    stall_rate_zero: float = 0.25


@dataclass(frozen=True)
class SuitePenaltyConfig:
    min_clearance_threshold: float | None = None
    min_clearance_penalty: float = 0.0
    intervention_rate_threshold: float | None = None
    intervention_penalty_cap: float = 0.0
    intervention_penalty_scale: float = 0.0
    progress_threshold: float | None = None
    progress_penalty: float = 0.0


@dataclass(frozen=True)
class CompassProfile:
    name: str
    levels: tuple[CompassLevel, ...]
    official_level_weights: dict[int, float]
    score_weights: CompassScoreWeights = field(default_factory=CompassScoreWeights)
    driving_quality: DrivingQualityConfig = field(default_factory=DrivingQualityConfig)
    scenario_generation: CompositionalScenarioProfile = field(default_factory=lambda: DEFAULT_COMPOSITIONAL_PROFILE)
    oracle: OracleConfig = field(default_factory=lambda: DEFAULT_ORACLE_CONFIG)
    min_official_coverage_weight: float = 0.85
    min_runs_per_official_level: int = 3
    suite_penalties: dict[str, SuitePenaltyConfig] = field(default_factory=dict)


DEFAULT_COMPASS_LEVELS = (
    CompassLevel(0, "sanity", "sanity", "single hazard, good visibility, slow speed", True),
    CompassLevel(1, "wod_aligned", "wod", "WOD-style long-tail clusters", True),
    CompassLevel(2, "compositional", "compositional", "independent axes combined", True),
    CompassLevel(3, "adversarial", "adversarial", "two or three hazards plus actor-behavior stress", True),
    CompassLevel(4, "frontier_probe", "gauntlet", "four synchronized threats, reported outside official score", False),
)


DEFAULT_COMPASS_PROFILE = CompassProfile(
    name="compass-v0",
    levels=DEFAULT_COMPASS_LEVELS,
    official_level_weights={0: 0.10, 1: 0.25, 2: 0.40, 3: 0.25},
    suite_penalties={
        "gauntlet": SuitePenaltyConfig(
            min_clearance_threshold=1.0,
            min_clearance_penalty=2.0,
            intervention_rate_threshold=0.28,
            intervention_penalty_cap=3.0,
            intervention_penalty_scale=8.0,
            progress_threshold=0.55,
            progress_penalty=2.0,
        ),
        "adversarial": SuitePenaltyConfig(
            min_clearance_threshold=0.7,
            min_clearance_penalty=1.0,
            intervention_rate_threshold=0.55,
            intervention_penalty_cap=1.5,
            intervention_penalty_scale=4.0,
        ),
    },
)

COMPASS_PROFILES = {
    "compass-v0": DEFAULT_COMPASS_PROFILE,
    "smoke": CompassProfile(
        name="smoke",
        levels=DEFAULT_COMPASS_LEVELS,
        official_level_weights={0: 0.25, 1: 0.25, 2: 0.25, 3: 0.25},
        min_official_coverage_weight=0.50,
        min_runs_per_official_level=1,
        suite_penalties=DEFAULT_COMPASS_PROFILE.suite_penalties,
    ),
}


@dataclass(frozen=True)
class CompassRun:
    level: int
    level_name: str
    suite: str
    cluster: str
    seed: int
    policy: str
    solvable: bool
    success: bool
    collision: bool
    safety_score: float
    route_quality_score: float
    comfort_score: float
    reasoning_quality: float
    reasoning_score_source: str
    recovery_rate: float
    generalization_score: float
    compass_score: float
    oracle_trace: str
    policy_trace: str
    failure_axes: str
    oracle_failed_policy_succeeded: bool
    oracle_failed_policy_failed: bool


def evaluate_compass(policy_name: str, suite: str, seeds: range, profile: CompassProfile | None = None) -> dict:
    profile = profile or DEFAULT_COMPASS_PROFILE
    policy = _policy(policy_name)
    runs = _evaluate_level(policy_name, policy, _level_for_suite(suite, profile), seeds, profile)
    return {"runs": [asdict(run) for run in runs], "summary": _summary(runs, profile)}


def evaluate_ladder(policy_name: str, seeds: range, profile: CompassProfile | None = None) -> dict:
    profile = profile or DEFAULT_COMPASS_PROFILE
    policy = _policy(policy_name)
    runs: list[CompassRun] = []
    for level in profile.levels:
        runs.extend(_evaluate_level(policy_name, policy, level, seeds, profile))
    return {"runs": [asdict(run) for run in runs], "summary": _ladder_summary(runs, profile)}


def _evaluate_level(
    policy_name: str,
    policy: PolicyFn,
    level: CompassLevel,
    seeds: range,
    profile: CompassProfile,
) -> list[CompassRun]:
    runs: list[CompassRun] = []
    for seed in seeds:
        paired_in_dist = policy(_paired_in_distribution_scenario(level, seed, profile))
        for scenario in _scenarios_for_level(level, seed, profile):
            oracle = run_oracle_policy(scenario, config=profile.oracle)
            rollout = policy(scenario)
            runs.append(_score_run(policy_name, level, seed, rollout, paired_in_dist, oracle, scenario, profile))
    return runs


def _score_run(
    policy_name: str,
    level: CompassLevel,
    seed: int,
    rollout: Rollout,
    paired_in_dist: Rollout,
    oracle: OracleCertificate,
    scenario: Scenario,
    profile: CompassProfile,
) -> CompassRun:
    policy_trace = _policy_trace(rollout)
    quality = _driving_quality_scores(rollout, level.suite, profile)
    reasoning = _reasoning_quality(policy_trace, oracle.reasoning_trace)
    recovery = _recovery_rate(rollout)
    generalization = _generalization_score(paired_in_dist, rollout, level.suite, profile)
    compass = _weighted_compass_score(
        profile.score_weights,
        {
            "safety": quality["safety_score"],
            "route_quality": quality["route_quality_score"],
            "comfort": quality["comfort_score"],
            "recovery": recovery,
            "generalization": generalization,
        },
    )
    failure_axes = "" if rollout.success else str(scenario.tags.get("ood_axes", ""))
    return CompassRun(
        level=level.level,
        level_name=level.name,
        suite=level.suite,
        cluster=scenario.cluster,
        seed=seed,
        policy=policy_name,
        solvable=oracle.solvable,
        success=rollout.success,
        collision=rollout.collision,
        safety_score=round(quality["safety_score"], 3),
        route_quality_score=round(quality["route_quality_score"], 3),
        comfort_score=round(quality["comfort_score"], 3),
        reasoning_quality=round(reasoning, 3),
        reasoning_score_source=REASONING_SCORE_SOURCE,
        recovery_rate=round(recovery, 3),
        generalization_score=round(generalization, 3),
        compass_score=round(compass, 3),
        oracle_trace=oracle.reasoning_trace,
        policy_trace=policy_trace,
        failure_axes=failure_axes,
        oracle_failed_policy_succeeded=(not oracle.solvable) and rollout.success,
        oracle_failed_policy_failed=(not oracle.solvable) and (not rollout.success),
    )


def _driving_quality_scores(
    rollout: Rollout,
    suite: str = "compositional",
    profile: CompassProfile | None = None,
) -> dict[str, float]:
    profile = profile or DEFAULT_COMPASS_PROFILE
    config = profile.driving_quality
    if not rollout.steps:
        return {"safety_score": 0.0, "route_quality_score": 0.0, "comfort_score": 0.0}

    count = len(rollout.steps)
    min_clearance = min(step.min_obstacle_distance for step in rollout.steps)
    avg_progress = sum((step.progress or 0.0) for step in rollout.steps) / count
    avg_lane_error = sum(abs(step.lane_error) for step in rollout.steps) / count
    intervention_rate = sum(1 for step in rollout.steps if step.intervention) / count
    avg_comfort_cost = sum((step.comfort_cost or 0.0) for step in rollout.steps) / count
    stall_rate = sum(1 for step in rollout.steps if step.stall) / count

    safety_score = config.success_score if rollout.success else config.failure_score
    if rollout.collision:
        safety_score -= config.collision_penalty
    safety_score = min(safety_score, _scale_higher_is_better(min_clearance, config.clearance_zero_m, config.clearance_target_m))

    progress_score = _scale_higher_is_better(avg_progress, 0.0, config.progress_target_m_per_step)
    lane_score = _scale_lower_is_better(avg_lane_error, config.route_lane_error_target_m, config.route_lane_error_zero_m)
    route_quality_score = (progress_score + lane_score) * 0.5

    intervention_score = _scale_lower_is_better(
        intervention_rate,
        config.intervention_rate_target,
        config.intervention_rate_zero,
    )
    comfort_score = _scale_lower_is_better(avg_comfort_cost, config.comfort_cost_target, config.comfort_cost_zero)
    stall_score = _scale_lower_is_better(stall_rate, config.stall_rate_target, config.stall_rate_zero)
    comfort_score = (intervention_score + comfort_score + stall_score) / 3.0

    penalties = profile.suite_penalties.get(suite)
    if penalties is not None:
        if penalties.min_clearance_threshold is not None and min_clearance < penalties.min_clearance_threshold:
            safety_score -= penalties.min_clearance_penalty
        if penalties.intervention_rate_threshold is not None and intervention_rate > penalties.intervention_rate_threshold:
            comfort_score -= min(
                penalties.intervention_penalty_cap,
                (intervention_rate - penalties.intervention_rate_threshold) * penalties.intervention_penalty_scale,
            )
        if penalties.progress_threshold is not None and avg_progress < penalties.progress_threshold:
            route_quality_score -= penalties.progress_penalty

    return {
        "safety_score": max(0.0, min(10.0, safety_score)),
        "route_quality_score": max(0.0, min(10.0, route_quality_score)),
        "comfort_score": max(0.0, min(10.0, comfort_score)),
    }


def _scale_higher_is_better(value: float, zero: float, target: float) -> float:
    if target <= zero:
        raise ValueError("target must be greater than zero for higher-is-better scaling")
    return max(0.0, min(10.0, 10.0 * (value - zero) / (target - zero)))


def _scale_lower_is_better(value: float, target: float, zero: float) -> float:
    if zero <= target:
        raise ValueError("zero must be greater than target for lower-is-better scaling")
    if value <= target:
        return 10.0
    return max(0.0, min(10.0, 10.0 * (zero - value) / (zero - target)))


def _reasoning_quality(policy_trace: str, oracle_trace: str) -> float:
    policy_terms = _terms(policy_trace)
    oracle_terms = _terms(oracle_trace)
    if not oracle_terms:
        return 0.0
    overlap = len(policy_terms & oracle_terms) / len(oracle_terms)
    return max(0.0, min(10.0, overlap * 10.0))


def _recovery_rate(rollout: Rollout) -> float:
    if not rollout.steps:
        return 0.0
    near_miss_ticks = [index for index, step in enumerate(rollout.steps) if step.min_obstacle_distance < 1.0]
    if not near_miss_ticks:
        return 10.0 if rollout.success else 4.0
    recovered = 0
    for index in near_miss_ticks:
        future = rollout.steps[index : min(len(rollout.steps), index + 12)]
        if future and max(step.min_obstacle_distance for step in future) > 1.4:
            recovered += 1
    return max(0.0, min(10.0, 10.0 * recovered / len(near_miss_ticks)))


def _generalization_score(
    in_dist: Rollout,
    ood: Rollout,
    suite: str = "compositional",
    profile: CompassProfile | None = None,
) -> float:
    profile = profile or DEFAULT_COMPASS_PROFILE
    in_score = _official_rollout_score(in_dist, "compositional", profile)
    ood_score = _official_rollout_score(ood, suite, profile)
    gap = max(0.0, in_score - ood_score)
    return max(0.0, min(10.0, 10.0 - gap))


def _official_rollout_score(rollout: Rollout, suite: str, profile: CompassProfile) -> float:
    quality = _driving_quality_scores(rollout, suite, profile)
    recovery = _recovery_rate(rollout)
    return _weighted_compass_score(
        profile.score_weights,
        {
            "safety": quality["safety_score"],
            "route_quality": quality["route_quality_score"],
            "comfort": quality["comfort_score"],
            "recovery": recovery,
            "generalization": 10.0,
        },
    )


def _policy_trace(rollout: Rollout) -> str:
    recent_steps = rollout.steps[-20:]
    modes = ",".join(sorted({step.action_mode for step in recent_steps})) if recent_steps else "none"
    maneuvers = ",".join(
        sorted({str(step.selected_maneuver) for step in recent_steps if step.selected_maneuver})
    )
    references = ",".join(
        sorted(
            {
                str(reference)
                for step in recent_steps
                for reference in (step.selector_3s_reference, step.selector_5s_reference)
                if reference
            }
        )
    )
    return f"policy_modes={modes}; selected_maneuvers={maneuvers}; selected_references={references}"


def _terms(text: str) -> set[str]:
    return {
        token.strip(" .,;:=()[]{}").lower()
        for token in text.replace("+", " ").replace("_", " ").split()
        if len(token.strip(" .,;:=()[]{}")) > 3
    }


def _summary(runs: list[CompassRun], profile: CompassProfile | None = None) -> dict:
    profile = profile or DEFAULT_COMPASS_PROFILE
    count = max(1, len(runs))
    return {
        "runs": len(runs),
        "benchmark_profile": profile.name,
        "official_score_formula": _score_formula(profile.score_weights),
        "driving_quality_config": asdict(profile.driving_quality),
        "scenario_generation_profile": asdict(profile.scenario_generation),
        "oracle_config": asdict(profile.oracle),
        "reasoning_score_source": REASONING_SCORE_SOURCE,
        "solvability_rate": round(sum(run.solvable for run in runs) / count, 3),
        "success_rate": round(sum(run.success for run in runs) / count, 3),
        "collision_rate": round(sum(run.collision for run in runs) / count, 3),
        "avg_safety_score": round(sum(run.safety_score for run in runs) / count, 3),
        "avg_route_quality_score": round(sum(run.route_quality_score for run in runs) / count, 3),
        "avg_comfort_score": round(sum(run.comfort_score for run in runs) / count, 3),
        "avg_reasoning_quality": round(sum(run.reasoning_quality for run in runs) / count, 3),
        "avg_recovery_rate": round(sum(run.recovery_rate for run in runs) / count, 3),
        "avg_generalization_score": round(sum(run.generalization_score for run in runs) / count, 3),
        "compass_score": round(sum(run.compass_score for run in runs) / count, 3),
        "oracle_failed_policy_succeeded": sum(1 for run in runs if run.oracle_failed_policy_succeeded),
        "oracle_failed_policy_failed": sum(1 for run in runs if run.oracle_failed_policy_failed),
    }


def _ladder_summary(runs: list[CompassRun], profile: CompassProfile | None = None) -> dict:
    profile = profile or DEFAULT_COMPASS_PROFILE
    by_level: dict[int, list[CompassRun]] = {}
    for run in runs:
        by_level.setdefault(run.level, []).append(run)

    level_summaries: list[dict] = []
    official_score = 0.0
    official_weight = 0.0
    sample_size_valid = True
    for level in profile.levels:
        group = by_level.get(level.level, [])
        summary = _summary(group, profile)
        ranked_runs = [run for run in group if _rankable_run(run)]
        oracle_gap_runs = [run for run in group if run.oracle_failed_policy_succeeded]
        excluded_runs = [run for run in group if _excluded_unsolved_run(run)]
        ranked_summary = _summary(ranked_runs, profile)
        level_payload = {
            "level": level.level,
            "name": level.name,
            "suite": level.suite,
            "official": level.official,
            "description": level.description,
            "all_runs": summary,
            "oracle_solved_runs": ranked_summary,
            "ranked_runs": ranked_summary,
            "oracle_gap_runs": len(oracle_gap_runs),
            "excluded_unsolvable": len(excluded_runs),
            "sample_size_valid": (not level.official) or len(ranked_runs) >= profile.min_runs_per_official_level,
        }
        if level.official and len(ranked_runs) < profile.min_runs_per_official_level:
            sample_size_valid = False
        level_summaries.append(level_payload)
        if level.official:
            weight = profile.official_level_weights[level.level]
            if ranked_runs:
                official_score += ranked_summary["compass_score"] * weight
                official_weight += weight

    frontier = next((item for item in level_summaries if item["level"] == 4), None)
    return {
        "official_compass_score": round(official_score / official_weight, 3) if official_weight else 0.0,
        "benchmark_profile": profile.name,
        "official_weights": profile.official_level_weights,
        "official_coverage_weight": round(official_weight, 3),
        "official_missing_weight": round(sum(profile.official_level_weights.values()) - official_weight, 3),
        "minimum_required_coverage_weight": profile.min_official_coverage_weight,
        "minimum_runs_per_official_level": profile.min_runs_per_official_level,
        "sample_size_valid": sample_size_valid,
        "score_valid": official_weight >= profile.min_official_coverage_weight and sample_size_valid,
        "official_score_formula": _score_formula(profile.score_weights),
        "driving_quality_config": asdict(profile.driving_quality),
        "scenario_generation_profile": asdict(profile.scenario_generation),
        "oracle_config": asdict(profile.oracle),
        "reasoning_score_source": REASONING_SCORE_SOURCE,
        "frontier_probe": frontier,
        "levels": level_summaries,
    }


def _rankable_run(run: CompassRun) -> bool:
    return run.solvable or run.oracle_failed_policy_succeeded


def _excluded_unsolved_run(run: CompassRun) -> bool:
    return (not run.solvable) and (not run.success)


def _scenarios_for_level(level: CompassLevel, seed: int, profile: CompassProfile) -> list[Scenario]:
    if level.suite == "wod":
        return [generate_wod_scenario(cluster, seed) for cluster in WOD_E2E_CLUSTERS]
    return [_scenario(level.suite, seed, profile)]


def _paired_in_distribution_scenario(level: CompassLevel, seed: int, profile: CompassProfile) -> Scenario:
    if level.level == 0:
        return _sanity_scenario(seed)
    if level.level == 1:
        return _sanity_scenario(seed)
    if level.level == 2:
        return generate_wod_scenario(WOD_E2E_CLUSTERS[(seed - 1) % len(WOD_E2E_CLUSTERS)], seed)
    return generate_compositional_scenario(seed, "compositional", profile=profile.scenario_generation)


def _scenario(suite: str, seed: int, profile: CompassProfile | None = None) -> Scenario:
    profile = profile or DEFAULT_COMPASS_PROFILE
    if suite == "sanity":
        return _sanity_scenario(seed)
    if suite == "wod":
        return generate_wod_scenario(WOD_E2E_CLUSTERS[(seed - 1) % len(WOD_E2E_CLUSTERS)], seed)
    if suite in COMPOSITIONAL_SUITES:
        return generate_compositional_scenario(seed, suite, profile=profile.scenario_generation)
    raise ValueError(f"unknown suite {suite!r}")


def _sanity_scenario(seed: int) -> Scenario:
    lane = [(10.0, 40.0), (35.0, 40.0), (65.0, 40.0), (95.0, 40.0), (120.0, 40.0)]
    side = -1.0 if seed % 2 else 1.0
    return Scenario(
        width=140.0,
        height=80.0,
        lane_center=lane,
        lane_half_width=9.0,
        obstacles=[
            Obstacle(62.0, 40.0 + side * 2.6, 1.0, "debris", "hazard_0_sanity_debris"),
            Obstacle(82.0, 40.0 - side * 7.0, 1.0, "ambient", "ambient_texture"),
        ],
        start=(6.0, 40.0),
        goal=(126.0, 40.0),
        seed=seed,
        cluster="sanity:single_hazard",
        tags={
            "generator": "compass_sanity_v1",
            "scenario_suite": "sanity",
            "topology": "straight",
            "condition": "clear",
            "primary_hazard_id": "hazard_0_sanity_debris",
            "primary_hazard_type": "debris_object",
            "intended_decision": "lateral_avoidance_with_progress",
            "allowed_maneuvers": "maintain,nudge_left,nudge_right",
            "difficulty": 0.1,
            "ood_axes": "",
            "ambient_objects": 1,
            "blocking_hazards": 1,
            "hazard_composition": "debris_object",
        },
        environment={"weather": "clear", "visibility": 1.0, "time_of_day": "midday", "road_surface": "dry"},
    )


def _score_formula(weights: CompassScoreWeights) -> str:
    total_weight = _score_weight_sum(weights)
    return (
        f"{weights.safety:.2f}*safety + "
        f"{weights.route_quality:.2f}*route_quality + "
        f"{weights.comfort:.2f}*comfort + "
        f"{weights.recovery:.2f}*recovery + "
        f"{weights.generalization:.2f}*generalization"
        f" normalized_by {total_weight:.2f}"
    )


def _weighted_compass_score(weights: CompassScoreWeights, components: dict[str, float]) -> float:
    total_weight = _score_weight_sum(weights)
    weighted_sum = sum(float(weight) * float(components[name]) for name, weight in asdict(weights).items())
    return weighted_sum / total_weight


def _score_weight_sum(weights: CompassScoreWeights) -> float:
    return sum(float(value) for value in asdict(weights).values())


def compass_profile_by_name(name: str) -> CompassProfile:
    try:
        return COMPASS_PROFILES[name]
    except KeyError as exc:
        valid = ", ".join(sorted(COMPASS_PROFILES))
        raise ValueError(f"unknown COMPASS profile {name!r}; expected one of: {valid}") from exc


def load_compass_profile(path: Path) -> CompassProfile:
    payload = json.loads(path.read_text(encoding="utf-8"))
    allowed = {
        "name",
        "levels",
        "official_level_weights",
        "score_weights",
        "driving_quality",
        "scenario_generation",
        "oracle",
        "min_official_coverage_weight",
        "min_runs_per_official_level",
        "suite_penalties",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown CompassProfile field(s): {', '.join(unknown)}")

    raw_levels = payload.get("levels")
    levels = DEFAULT_COMPASS_LEVELS if raw_levels is None else tuple(CompassLevel(**level) for level in raw_levels)
    score_weights = CompassScoreWeights(**payload.get("score_weights", {}))
    driving_quality = DrivingQualityConfig(**payload.get("driving_quality", {}))
    scenario_generation = _load_scenario_generation_profile(payload.get("scenario_generation"))
    oracle = OracleConfig(**payload.get("oracle", {}))
    if "suite_penalties" in payload:
        suite_penalties = {
            suite: SuitePenaltyConfig(**config)
            for suite, config in payload["suite_penalties"].items()
        }
    else:
        suite_penalties = DEFAULT_COMPASS_PROFILE.suite_penalties
    official_weights = {
        int(level): float(weight)
        for level, weight in payload.get("official_level_weights", DEFAULT_COMPASS_PROFILE.official_level_weights).items()
    }
    profile = CompassProfile(
        name=str(payload["name"]),
        levels=levels,
        official_level_weights=official_weights,
        score_weights=score_weights,
        driving_quality=driving_quality,
        scenario_generation=scenario_generation,
        oracle=oracle,
        min_official_coverage_weight=float(
            payload.get("min_official_coverage_weight", DEFAULT_COMPASS_PROFILE.min_official_coverage_weight)
        ),
        min_runs_per_official_level=int(
            payload.get("min_runs_per_official_level", DEFAULT_COMPASS_PROFILE.min_runs_per_official_level)
        ),
        suite_penalties=suite_penalties,
    )
    _validate_compass_profile(profile)
    return profile


def _load_scenario_generation_profile(payload: dict | None) -> CompositionalScenarioProfile:
    if payload is None:
        return DEFAULT_COMPOSITIONAL_PROFILE
    allowed = {
        "name",
        "suite_seed_offsets",
        "suite_pressure",
        "hazard_counts",
        "ambient_base_count",
        "gauntlet_lane_half_width_cap",
        "corridor_clearance",
        "difficulty",
        "topology",
        "hazards",
        "ambient",
        "environment",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown CompositionalScenarioProfile field(s): {', '.join(unknown)}")
    hazard_counts = {
        suite: tuple(int(value) for value in values)
        for suite, values in payload.get("hazard_counts", DEFAULT_COMPOSITIONAL_PROFILE.hazard_counts).items()
    }
    return CompositionalScenarioProfile(
        name=str(payload.get("name", DEFAULT_COMPOSITIONAL_PROFILE.name)),
        suite_seed_offsets={
            suite: int(offset)
            for suite, offset in payload.get(
                "suite_seed_offsets",
                DEFAULT_COMPOSITIONAL_PROFILE.suite_seed_offsets,
            ).items()
        },
        suite_pressure={
            suite: float(pressure)
            for suite, pressure in payload.get("suite_pressure", DEFAULT_COMPOSITIONAL_PROFILE.suite_pressure).items()
        },
        hazard_counts=hazard_counts,
        ambient_base_count=int(payload.get("ambient_base_count", DEFAULT_COMPOSITIONAL_PROFILE.ambient_base_count)),
        gauntlet_lane_half_width_cap=tuple(
            float(value)
            for value in payload.get(
                "gauntlet_lane_half_width_cap",
                DEFAULT_COMPOSITIONAL_PROFILE.gauntlet_lane_half_width_cap,
            )
        ),
        corridor_clearance=CorridorClearanceConfig(**payload.get("corridor_clearance", {})),
        difficulty=DifficultyConfig(**payload.get("difficulty", {})),
        topology=TopologyGeometryConfig(**payload.get("topology", {})),
        hazards=HazardGeometryConfig(**payload.get("hazards", {})),
        ambient=AmbientGeometryConfig(**payload.get("ambient", {})),
        environment=EnvironmentConfig(**payload.get("environment", {})),
    )


def _validate_compass_profile(profile: CompassProfile) -> None:
    official_levels = {level.level for level in profile.levels if level.official}
    missing_weights = sorted(official_levels - set(profile.official_level_weights))
    if missing_weights:
        raise ValueError(f"official_level_weights missing official level(s): {missing_weights}")
    negative_weights = sorted(level for level, weight in profile.official_level_weights.items() if weight < 0.0)
    if negative_weights:
        raise ValueError(f"official_level_weights has negative weight for level(s): {negative_weights}")
    total_weight = sum(profile.official_level_weights[level] for level in official_levels)
    if total_weight <= 0.0:
        raise ValueError("official_level_weights must assign positive total weight to official levels")
    if profile.min_runs_per_official_level < 1:
        raise ValueError("min_runs_per_official_level must be at least 1")
    if not 0.0 <= profile.min_official_coverage_weight <= total_weight:
        raise ValueError("min_official_coverage_weight must be between 0 and total official weight")
    _validate_score_weights(profile.score_weights)
    _validate_driving_quality(profile.driving_quality)
    _validate_scenario_generation_profile(profile.scenario_generation)


def _validate_score_weights(weights: CompassScoreWeights) -> None:
    values = asdict(weights)
    negative = sorted(name for name, value in values.items() if value < 0.0)
    if negative:
        raise ValueError(f"score_weights has negative weight(s): {negative}")
    if _score_weight_sum(weights) <= 0.0:
        raise ValueError("score_weights must have positive total weight")


def _validate_driving_quality(config: DrivingQualityConfig) -> None:
    _scale_higher_is_better(config.clearance_target_m, config.clearance_zero_m, config.clearance_target_m)
    _scale_higher_is_better(config.progress_target_m_per_step, 0.0, config.progress_target_m_per_step)
    _scale_lower_is_better(config.route_lane_error_target_m, config.route_lane_error_target_m, config.route_lane_error_zero_m)
    _scale_lower_is_better(config.intervention_rate_target, config.intervention_rate_target, config.intervention_rate_zero)
    _scale_lower_is_better(config.comfort_cost_target, config.comfort_cost_target, config.comfort_cost_zero)
    _scale_lower_is_better(config.stall_rate_target, config.stall_rate_target, config.stall_rate_zero)


def _validate_scenario_generation_profile(profile: CompositionalScenarioProfile) -> None:
    required_suites = set(COMPOSITIONAL_SUITES)
    for field_name, mapping in (
        ("suite_seed_offsets", profile.suite_seed_offsets),
        ("suite_pressure", profile.suite_pressure),
        ("hazard_counts", profile.hazard_counts),
    ):
        missing = sorted(required_suites - set(mapping))
        if missing:
            raise ValueError(f"scenario_generation.{field_name} missing suite(s): {missing}")
    invalid_counts = {
        suite: counts
        for suite, counts in profile.hazard_counts.items()
        if not counts or any(count < 1 for count in counts)
    }
    if invalid_counts:
        raise ValueError(f"scenario_generation.hazard_counts must contain positive counts: {invalid_counts}")
    if profile.ambient_base_count < 0:
        raise ValueError("scenario_generation.ambient_base_count must be non-negative")
    if len(profile.gauntlet_lane_half_width_cap) != 2 or profile.gauntlet_lane_half_width_cap[0] > profile.gauntlet_lane_half_width_cap[1]:
        raise ValueError("scenario_generation.gauntlet_lane_half_width_cap must be [min, max]")


def _level_for_suite(suite: str, profile: CompassProfile | None = None) -> CompassLevel:
    profile = profile or DEFAULT_COMPASS_PROFILE
    if suite == "ladder":
        raise ValueError("ladder is an evaluation mode, not a single suite")
    for level in profile.levels:
        if level.suite == suite:
            return level
    raise ValueError(f"unknown suite {suite!r}")


def _policy(name: str) -> PolicyFn:
    if name == "baseline":
        return run_policy
    if name == "spotlight-reflex":
        return run_spotlight_reflex_policy
    raise ValueError(f"unknown policy {name!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the COMPASS internal simulator benchmark.")
    parser.add_argument("command", choices=("run", "benchmark", "ladder"))
    parser.add_argument("--policy", default="spotlight-reflex", choices=("baseline", "spotlight-reflex"))
    parser.add_argument("--profile", default="compass-v0", choices=tuple(sorted(COMPASS_PROFILES)))
    parser.add_argument("--profile-json", type=Path, help="Optional JSON file overriding the selected COMPASS profile.")
    parser.add_argument("--suite", default="gauntlet", choices=("sanity", "wod") + COMPOSITIONAL_SUITES)
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seed-end", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("artifacts/compass_report.json"))
    args = parser.parse_args()
    profile = load_compass_profile(args.profile_json) if args.profile_json else compass_profile_by_name(args.profile)

    if args.command in {"ladder", "benchmark"}:
        report = evaluate_ladder(args.policy, range(args.seed_start, args.seed_end + 1), profile)
        score_label = "official_compass_score"
    else:
        report = evaluate_compass(args.policy, args.suite, range(args.seed_start, args.seed_end + 1), profile)
        score_label = "compass_score"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    print(f"COMPASS Score: {report['summary'][score_label]:.2f} ({args.policy}, {args.command})")
    _print_summary(report["summary"])
    print(f"Wrote {args.output}")


def _print_summary(summary: dict) -> None:
    if "levels" not in summary:
        print(json.dumps(summary, indent=2))
        return
    print(
        "valid={valid} coverage={coverage:.2f} missing={missing:.2f} "
        "sample_size_valid={sample}".format(
            valid=summary["score_valid"],
            coverage=summary["official_coverage_weight"],
            missing=summary["official_missing_weight"],
            sample=summary["sample_size_valid"],
        )
    )
    for level in summary["levels"]:
        solved = level["oracle_solved_runs"]
        all_runs = level["all_runs"]
        marker = "official" if level["official"] else "frontier"
        print(
            "L{level} {name:14s} {marker:8s} score={score:5.2f} "
            "safe={safe:5.2f} route={route:5.2f} comfort={comfort:5.2f} "
            "recovery={recovery:5.2f} gen={gen:5.2f} success={success:4.2f} "
            "solvable={solvable:4.2f} excluded={excluded}".format(
                level=level["level"],
                name=level["name"],
                marker=marker,
                score=solved["compass_score"],
                safe=solved["avg_safety_score"],
                route=solved["avg_route_quality_score"],
                comfort=solved["avg_comfort_score"],
                recovery=solved["avg_recovery_rate"],
                gen=solved["avg_generalization_score"],
                success=all_runs["success_rate"],
                solvable=all_runs["solvability_rate"],
                excluded=level["excluded_unsolvable"],
            )
        )


if __name__ == "__main__":
    main()
