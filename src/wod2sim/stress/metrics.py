from __future__ import annotations

from dataclasses import dataclass
import math

from wod2sim.simulator.environment import Scenario
from wod2sim.simulator.policy import Rollout


@dataclass(frozen=True)
class InternalStressMetrics:
    min_clearance_m: float
    exposure_steps: int
    peak_collision_risk: float
    min_ttc_s: float
    intervention_rate: float
    avg_progress_m: float
    max_lane_error_m: float
    decision_modes: int
    hard_response: bool


def compute_internal_stress_metrics(scenario: Scenario, rollout: Rollout) -> InternalStressMetrics:
    if not rollout.steps:
        return InternalStressMetrics(
            min_clearance_m=math.inf,
            exposure_steps=0,
            peak_collision_risk=0.0,
            min_ttc_s=math.inf,
            intervention_rate=0.0,
            avg_progress_m=0.0,
            max_lane_error_m=0.0,
            decision_modes=0,
            hard_response=False,
        )

    clearances = [step.min_obstacle_distance for step in rollout.steps]
    risks = [step.collision_risk for step in rollout.steps]
    lane_errors = [abs(step.lane_error) for step in rollout.steps]
    progresses = [(step.progress or 0.0) for step in rollout.steps]
    interventions = [bool(step.intervention) for step in rollout.steps]
    action_modes = {step.action_mode for step in rollout.steps if step.action_mode}
    exposure_threshold = max(1.5, scenario.lane_half_width * 0.22)
    exposure_steps = sum(1 for clearance in clearances if clearance <= exposure_threshold)
    hard_response = any(
        step.action_mode in {"risk_nudge", "risk_escape", "guarded_evasive"}
        or step.action_mode.endswith(":slow_yield")
        for step in rollout.steps
        if step.action_mode
    )
    return InternalStressMetrics(
        min_clearance_m=min(clearances),
        exposure_steps=exposure_steps,
        peak_collision_risk=max(risks),
        min_ttc_s=_surrogate_min_ttc(rollout),
        intervention_rate=sum(1 for flag in interventions if flag) / len(interventions),
        avg_progress_m=sum(progresses) / len(progresses),
        max_lane_error_m=max(lane_errors),
        decision_modes=len(action_modes),
        hard_response=hard_response,
    )


def classify_internal_stress(metrics: InternalStressMetrics, rollout: Rollout) -> str:
    if rollout.collision:
        return "failure:collision"
    if not rollout.reached_goal:
        return "failure:goal"
    if metrics.min_clearance_m > 4.0 and metrics.peak_collision_risk < 0.2 and not metrics.hard_response:
        return "weak:understressed"
    if metrics.min_clearance_m < 0.75 or metrics.min_ttc_s < 0.6:
        return "edge:near_limit"
    if metrics.hard_response or metrics.exposure_steps >= 2 or metrics.peak_collision_risk >= 0.45:
        return "pass:stressed"
    return "pass:mild"


def _surrogate_min_ttc(rollout: Rollout, dt_s: float = 1.0) -> float:
    if len(rollout.steps) < 2:
        return math.inf
    min_ttc = math.inf
    previous = rollout.steps[0]
    for current in rollout.steps[1:]:
        closing_speed = max(0.0, (previous.min_obstacle_distance - current.min_obstacle_distance) / dt_s)
        if closing_speed > 1e-6:
            min_ttc = min(min_ttc, max(0.0, current.min_obstacle_distance) / closing_speed)
        previous = current
    return min_ttc
