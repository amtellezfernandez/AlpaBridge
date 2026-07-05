from __future__ import annotations

import math

from wod2sim.simulator.policy import Rollout, run_policy, run_spotlight_reflex_policy
from wod2sim.stress.metrics import classify_internal_stress, compute_internal_stress_metrics
from wod2sim.stress.scenarios import iter_internal_stress_cases


def summarize_internal_stress_run(
    cluster: str,
    seed: int,
    level: str,
    policy: str,
    scenario,
    rollout: Rollout,
) -> dict[str, float | int | str | bool]:
    metrics = compute_internal_stress_metrics(scenario, rollout)
    verdict = classify_internal_stress(metrics, rollout)
    return {
        "cluster": cluster,
        "seed": seed,
        "stress_level": level,
        "policy": policy,
        "success": rollout.success,
        "collision": rollout.collision,
        "reached_goal": rollout.reached_goal,
        "stress_verdict": verdict,
        "min_clearance_m": round(metrics.min_clearance_m, 3),
        "peak_collision_risk": round(metrics.peak_collision_risk, 4),
        "min_ttc_s": round(metrics.min_ttc_s, 3) if math.isfinite(metrics.min_ttc_s) else "inf",
        "exposure_steps": metrics.exposure_steps,
        "intervention_rate": round(metrics.intervention_rate, 4),
        "avg_progress_m": round(metrics.avg_progress_m, 4),
        "max_lane_error_m": round(metrics.max_lane_error_m, 3),
        "decision_modes": metrics.decision_modes,
        "hard_response": metrics.hard_response,
        "ego_relative_trigger_tick": int(scenario.tags.get("ego_relative_trigger_tick", 0)),
    }


def evaluate_internal_stress(
    clusters: tuple[str, ...],
    seed_start: int,
    seed_end: int,
    levels: tuple[str, ...],
    policy: str,
) -> list[dict[str, float | int | str | bool]]:
    if policy == "baseline":
        policies = (("baseline", run_policy),)
    elif policy == "spotlight-reflex":
        policies = (("spotlight-reflex", run_spotlight_reflex_policy),)
    else:
        policies = (("baseline", run_policy), ("spotlight-reflex", run_spotlight_reflex_policy))

    rows: list[dict[str, float | int | str | bool]] = []
    for cluster, seed, level, scenario in iter_internal_stress_cases(clusters, range(seed_start, seed_end + 1), levels):
        for policy_name, policy_fn in policies:
            rollout = policy_fn(scenario)
            rows.append(summarize_internal_stress_run(cluster, seed, level, policy_name, scenario, rollout))
    return rows


def aggregate_internal_stress(rows: list[dict[str, float | int | str | bool]]) -> list[dict[str, float | int | str]]:
    groups: dict[tuple[str, str, str], list[dict[str, float | int | str | bool]]] = {}
    for row in rows:
        groups.setdefault((str(row["policy"]), str(row["cluster"]), str(row["stress_level"])), []).append(row)

    summary: list[dict[str, float | int | str]] = []
    for (policy, cluster, level), scoped in sorted(groups.items()):
        count = len(scoped)
        summary.append(
            {
                "policy": policy,
                "cluster": cluster,
                "stress_level": level,
                "runs": count,
                "success_rate": round(sum(1 for row in scoped if row["success"]) / count, 3),
                "collision_rate": round(sum(1 for row in scoped if row["collision"]) / count, 3),
                "stressed_pass_rate": round(sum(1 for row in scoped if row["stress_verdict"] == "pass:stressed") / count, 3),
                "understressed_rate": round(sum(1 for row in scoped if row["stress_verdict"] == "weak:understressed") / count, 3),
                "edge_rate": round(sum(1 for row in scoped if row["stress_verdict"] == "edge:near_limit") / count, 3),
                "avg_min_clearance_m": round(sum(float(row["min_clearance_m"]) for row in scoped) / count, 3),
                "avg_peak_collision_risk": round(sum(float(row["peak_collision_risk"]) for row in scoped) / count, 4),
                "avg_exposure_steps": round(sum(int(row["exposure_steps"]) for row in scoped) / count, 3),
                "avg_intervention_rate": round(sum(float(row["intervention_rate"]) for row in scoped) / count, 4),
            }
        )
    return summary
