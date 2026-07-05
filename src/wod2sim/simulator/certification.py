from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from .compass import CompassProfile, compass_profile_by_name, evaluate_ladder, load_compass_profile
from .compositional_scenarios import COMPOSITIONAL_CONDITIONS, COMPOSITIONAL_HAZARDS, COMPOSITIONAL_TOPOLOGIES
from .wod_scenarios import WOD_E2E_CLUSTERS


CONFIDENCE_LEVEL = 0.95
WILSON_Z_95 = 1.959963984540054
DEFAULT_COLLISION_THRESHOLD = 0.01
DEFAULT_SUCCESS_THRESHOLD = 0.90
DEFAULT_MIN_RANKED_RUNS_PER_LEVEL = 30


@dataclass(frozen=True)
class OddSpec:
    name: str = "COMPASS abstract urban/highway ODD v0"
    road_topologies: tuple[str, ...] = COMPOSITIONAL_TOPOLOGIES
    wod_aligned_clusters: tuple[str, ...] = WOD_E2E_CLUSTERS
    speed_range_kph: tuple[int, int] = (0, 120)
    weather_conditions: tuple[str, ...] = COMPOSITIONAL_CONDITIONS
    actor_and_hazard_types: tuple[str, ...] = COMPOSITIONAL_HAZARDS
    hazard_combination_depth: tuple[int, ...] = (1, 2, 3)
    simulator_tier: str = "abstract_2d"
    exclusions: tuple[str, ...] = (
        "no legal certification claim",
        "no public-road deployment approval",
        "oracle is an independent feasibility check, not a proof-grade solver",
        "sensor-realistic evidence requires the AlpaSim tier",
    )


@dataclass(frozen=True)
class EvidenceThresholds:
    min_success_rate_lower_bound: float = DEFAULT_SUCCESS_THRESHOLD
    max_collision_rate_upper_bound: float = DEFAULT_COLLISION_THRESHOLD
    min_compass_score: float = 7.0
    min_safety_score: float = 8.0
    min_route_quality_score: float = 6.5
    min_comfort_score: float = 6.0
    min_worst_compass_score: float = 4.0
    min_worst_safety_score: float = 5.0
    min_worst_route_quality_score: float = 3.0
    min_worst_comfort_score: float = 3.0
    min_ranked_runs_per_official_level: int = DEFAULT_MIN_RANKED_RUNS_PER_LEVEL
    confidence_level: float = CONFIDENCE_LEVEL


@dataclass(frozen=True)
class EvidenceProfile:
    name: str
    odd_spec: OddSpec
    thresholds: EvidenceThresholds
    description: str
    compass_profile: str = "compass-v0"


@dataclass(frozen=True)
class ConfidenceInterval:
    estimate: float
    lower: float
    upper: float
    confidence: float
    method: str = "wilson_score"


def generate_evidence_report(
    policy_name: str,
    seeds: range,
    odd_spec: OddSpec | None = None,
    thresholds: EvidenceThresholds | None = None,
    profile_name: str = "custom",
    compass_profile: CompassProfile | None = None,
) -> dict[str, Any]:
    odd = odd_spec or OddSpec()
    limits = thresholds or EvidenceThresholds()
    compass_profile = compass_profile or compass_profile_by_name("compass-v0")
    compass_report = evaluate_ladder(policy_name, seeds, compass_profile)
    official_runs = _official_ranked_runs(compass_report)
    level_evidence = _official_level_evidence(compass_report, limits)
    run_count = len(official_runs)
    success_count = sum(1 for run in official_runs if run["success"])
    collision_count = sum(1 for run in official_runs if run["collision"])
    quality_summary = _quality_summary(official_runs)

    success_ci = _proportion_interval(success_count, run_count, limits.confidence_level)
    collision_ci = _proportion_interval(collision_count, run_count, limits.confidence_level)
    failures = _evidence_failures(compass_report["summary"], success_ci, collision_ci, level_evidence, limits)
    status = "compass_evidence_threshold_met" if not failures else failures[0]["code"]

    return {
        "schema": "compass_sotif_evidence_package_v0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": policy_name,
        "claim_type": "simulation_evidence_package_not_legal_certification",
        "evidence_profile": profile_name,
        "compass_profile": compass_profile.name,
        "odd_specification": asdict(odd),
        "thresholds": asdict(limits),
        "compass_summary": compass_report["summary"],
        "statistical_evidence": {
            "official_ranked_runs": run_count,
            "success_count": success_count,
            "collision_count": collision_count,
            "success_rate": asdict(success_ci),
            "collision_rate": asdict(collision_ci),
            "quality_summary": quality_summary,
            "official_level_evidence": level_evidence,
        },
        "sotif_alignment": _sotif_alignment(compass_report["summary"], status),
        "evidence_status": status,
        "evidence_failures": failures,
        "remaining_gaps": _remaining_gaps(compass_report["summary"], failures),
    }


EVIDENCE_PROFILES = {
    "sotif-v0": EvidenceProfile(
        name="sotif-v0",
        odd_spec=OddSpec(),
        thresholds=EvidenceThresholds(),
        description="Conservative abstract-simulator evidence profile; not a legal certification.",
    ),
    "smoke": EvidenceProfile(
        name="smoke",
        odd_spec=OddSpec(name="COMPASS smoke-test ODD v0"),
        thresholds=EvidenceThresholds(
            min_success_rate_lower_bound=0.50,
            max_collision_rate_upper_bound=0.50,
            min_compass_score=0.0,
            min_safety_score=0.0,
            min_route_quality_score=0.0,
            min_comfort_score=0.0,
            min_worst_compass_score=0.0,
            min_worst_safety_score=0.0,
            min_worst_route_quality_score=0.0,
            min_worst_comfort_score=0.0,
            min_ranked_runs_per_official_level=1,
            confidence_level=CONFIDENCE_LEVEL,
        ),
        description="Development-only profile for checking report plumbing; not evidence for safety claims.",
        compass_profile="smoke",
    ),
}


def profile_by_name(name: str) -> EvidenceProfile:
    try:
        return EVIDENCE_PROFILES[name]
    except KeyError as exc:
        valid = ", ".join(sorted(EVIDENCE_PROFILES))
        raise ValueError(f"unknown evidence profile {name!r}; expected one of: {valid}") from exc


def load_odd_spec(path: Path) -> OddSpec:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _dataclass_from_dict(OddSpec, payload)


def load_thresholds(path: Path) -> EvidenceThresholds:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _dataclass_from_dict(EvidenceThresholds, payload)


def _dataclass_from_dict(cls, payload: dict[str, Any]):
    allowed = cls.__dataclass_fields__
    unknown = sorted(set(payload) - set(allowed))
    if unknown:
        raise ValueError(f"unknown {cls.__name__} field(s): {', '.join(unknown)}")
    normalized = {}
    for key, value in payload.items():
        if isinstance(getattr(cls(), key), tuple):
            normalized[key] = tuple(value)
        else:
            normalized[key] = value
    return cls(**normalized)


def _official_ranked_runs(compass_report: dict[str, Any]) -> list[dict[str, Any]]:
    official_levels = {
        level["level"]
        for level in compass_report["summary"]["levels"]
        if level["official"]
    }
    return [
        run
        for run in compass_report["runs"]
        if run["level"] in official_levels and (run["solvable"] or run["oracle_failed_policy_succeeded"])
    ]


def _official_level_evidence(compass_report: dict[str, Any], thresholds: EvidenceThresholds) -> list[dict[str, Any]]:
    runs_by_level: dict[int, list[dict[str, Any]]] = {}
    for run in _official_ranked_runs(compass_report):
        runs_by_level.setdefault(int(run["level"]), []).append(run)

    evidence: list[dict[str, Any]] = []
    minimum_runs = _effective_minimum_ranked_runs(thresholds)
    for level in compass_report["summary"]["levels"]:
        if not level["official"]:
            continue
        level_runs = runs_by_level.get(int(level["level"]), [])
        run_count = len(level_runs)
        success_count = sum(1 for run in level_runs if run["success"])
        collision_count = sum(1 for run in level_runs if run["collision"])
        quality = _quality_summary(level_runs)
        success_ci = _proportion_interval(success_count, run_count, thresholds.confidence_level)
        collision_ci = _proportion_interval(collision_count, run_count, thresholds.confidence_level)
        evidence.append(
            {
                "level": level["level"],
                "name": level["name"],
                "suite": level["suite"],
                "ranked_runs": run_count,
                "success_count": success_count,
                "collision_count": collision_count,
                "success_rate": asdict(success_ci),
                "collision_rate": asdict(collision_ci),
                "quality": quality,
                "minimum_ranked_runs": minimum_runs,
                "sample_size_valid": run_count >= minimum_runs,
                "success_threshold_met": success_ci.lower >= thresholds.min_success_rate_lower_bound,
                "collision_threshold_met": collision_ci.upper <= thresholds.max_collision_rate_upper_bound,
                "quality_thresholds_met": _quality_thresholds_met(quality, thresholds),
            }
        )
    return evidence


def _quality_summary(runs: list[dict[str, Any]]) -> dict[str, float]:
    if not runs:
        return {
            "compass_score": 0.0,
            "safety_score": 0.0,
            "route_quality_score": 0.0,
            "comfort_score": 0.0,
            "worst_compass_score": 0.0,
            "worst_safety_score": 0.0,
            "worst_route_quality_score": 0.0,
            "worst_comfort_score": 0.0,
            "p10_compass_score": 0.0,
            "p10_safety_score": 0.0,
            "p10_route_quality_score": 0.0,
            "p10_comfort_score": 0.0,
        }
    compass_values = [float(run["compass_score"]) for run in runs]
    safety_values = [float(run["safety_score"]) for run in runs]
    route_values = [float(run["route_quality_score"]) for run in runs]
    comfort_values = [float(run["comfort_score"]) for run in runs]
    return {
        "compass_score": round(sum(compass_values) / len(runs), 6),
        "safety_score": round(sum(safety_values) / len(runs), 6),
        "route_quality_score": round(sum(route_values) / len(runs), 6),
        "comfort_score": round(sum(comfort_values) / len(runs), 6),
        "worst_compass_score": round(min(compass_values), 6),
        "worst_safety_score": round(min(safety_values), 6),
        "worst_route_quality_score": round(min(route_values), 6),
        "worst_comfort_score": round(min(comfort_values), 6),
        "p10_compass_score": round(_nearest_rank_percentile(compass_values, 0.10), 6),
        "p10_safety_score": round(_nearest_rank_percentile(safety_values, 0.10), 6),
        "p10_route_quality_score": round(_nearest_rank_percentile(route_values, 0.10), 6),
        "p10_comfort_score": round(_nearest_rank_percentile(comfort_values, 0.10), 6),
    }


def _nearest_rank_percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _quality_thresholds_met(quality: dict[str, float], thresholds: EvidenceThresholds) -> bool:
    return (
        quality["compass_score"] >= thresholds.min_compass_score
        and quality["safety_score"] >= thresholds.min_safety_score
        and quality["route_quality_score"] >= thresholds.min_route_quality_score
        and quality["comfort_score"] >= thresholds.min_comfort_score
        and quality["worst_compass_score"] >= thresholds.min_worst_compass_score
        and quality["worst_safety_score"] >= thresholds.min_worst_safety_score
        and quality["worst_route_quality_score"] >= thresholds.min_worst_route_quality_score
        and quality["worst_comfort_score"] >= thresholds.min_worst_comfort_score
    )


def _effective_minimum_ranked_runs(thresholds: EvidenceThresholds) -> int:
    zero_collision_runs = _minimum_zero_event_trials(
        thresholds.max_collision_rate_upper_bound,
        thresholds.confidence_level,
    )
    return max(thresholds.min_ranked_runs_per_official_level, zero_collision_runs)


def _minimum_zero_event_trials(max_upper_bound: float, confidence: float) -> int:
    if not 0.0 < max_upper_bound < 1.0:
        raise ValueError("max_upper_bound must be inside (0, 1)")
    z = WILSON_Z_95 if confidence == CONFIDENCE_LEVEL else _normal_quantile_approx(1.0 - (1.0 - confidence) / 2.0)
    return math.ceil((z * z) * (1.0 - max_upper_bound) / max_upper_bound)


def _proportion_interval(successes: int, trials: int, confidence: float) -> ConfidenceInterval:
    if trials <= 0:
        return ConfidenceInterval(estimate=0.0, lower=0.0, upper=1.0, confidence=confidence)

    z = WILSON_Z_95 if confidence == CONFIDENCE_LEVEL else _normal_quantile_approx(1.0 - (1.0 - confidence) / 2.0)
    p_hat = successes / trials
    denominator = 1.0 + z * z / trials
    center = (p_hat + z * z / (2.0 * trials)) / denominator
    margin = z * math.sqrt((p_hat * (1.0 - p_hat) + z * z / (4.0 * trials)) / trials) / denominator
    return ConfidenceInterval(
        estimate=round(p_hat, 6),
        lower=round(max(0.0, center - margin), 6),
        upper=round(min(1.0, center + margin), 6),
        confidence=confidence,
    )


def _normal_quantile_approx(probability: float) -> float:
    # Abramowitz-Stegun-style approximation; enough for dependency-free CI reporting.
    if not 0.0 < probability < 1.0:
        raise ValueError("probability must be inside (0, 1)")
    if probability < 0.5:
        return -_normal_quantile_approx(1.0 - probability)
    t = math.sqrt(-2.0 * math.log(1.0 - probability))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    return t - (c0 + c1 * t + c2 * t * t) / (1.0 + d1 * t + d2 * t * t + d3 * t * t * t)


def _evidence_failures(
    summary: dict[str, Any],
    success_ci: ConfidenceInterval,
    collision_ci: ConfidenceInterval,
    level_evidence: list[dict[str, Any]],
    thresholds: EvidenceThresholds,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    if not summary["score_valid"]:
        failures.append({"code": "insufficient_sample_or_coverage", "scope": "compass"})
    for level in level_evidence:
        if not level["sample_size_valid"]:
            failures.append(
                {
                    "code": "insufficient_evidence_level_sample_size",
                    "scope": level["name"],
                    "ranked_runs": level["ranked_runs"],
                    "minimum_ranked_runs": level["minimum_ranked_runs"],
                }
            )
        if not level["success_threshold_met"]:
            failures.append(
                {
                    "code": "insufficient_per_level_success_confidence",
                    "scope": level["name"],
                    "lower_bound": level["success_rate"]["lower"],
                    "threshold": thresholds.min_success_rate_lower_bound,
                }
            )
        if not level["collision_threshold_met"]:
            failures.append(
                {
                    "code": "insufficient_per_level_collision_confidence",
                    "scope": level["name"],
                    "upper_bound": level["collision_rate"]["upper"],
                    "threshold": thresholds.max_collision_rate_upper_bound,
                }
            )
        if not level["quality_thresholds_met"]:
            failures.append(
                {
                    "code": "insufficient_per_level_driving_quality",
                    "scope": level["name"],
                    "quality": level["quality"],
                    "thresholds": _quality_threshold_payload(thresholds),
                }
            )
    if success_ci.lower < thresholds.min_success_rate_lower_bound:
        failures.append(
            {
                "code": "insufficient_success_confidence",
                "scope": "pooled_official",
                "lower_bound": success_ci.lower,
                "threshold": thresholds.min_success_rate_lower_bound,
            }
        )
    if collision_ci.upper > thresholds.max_collision_rate_upper_bound:
        failures.append(
            {
                "code": "insufficient_collision_confidence",
                "scope": "pooled_official",
                "upper_bound": collision_ci.upper,
                "threshold": thresholds.max_collision_rate_upper_bound,
            }
        )
    return failures


def _quality_threshold_payload(thresholds: EvidenceThresholds) -> dict[str, float]:
    return {
        "min_compass_score": thresholds.min_compass_score,
        "min_safety_score": thresholds.min_safety_score,
        "min_route_quality_score": thresholds.min_route_quality_score,
        "min_comfort_score": thresholds.min_comfort_score,
        "min_worst_compass_score": thresholds.min_worst_compass_score,
        "min_worst_safety_score": thresholds.min_worst_safety_score,
        "min_worst_route_quality_score": thresholds.min_worst_route_quality_score,
        "min_worst_comfort_score": thresholds.min_worst_comfort_score,
    }


def _sotif_alignment(summary: dict[str, Any], status: str) -> dict[str, str]:
    verification = "simulation_evidence_available" if summary["score_valid"] else "partial"
    validation = "partial_simulation_only"
    if status == "compass_evidence_threshold_met":
        validation = "simulation_evidence_partial_real_world_validation_required"
    return {
        "iso_21448_section_8_verification": verification,
        "iso_21448_section_9_validation": validation,
        "regulatory_position": "supporting evidence only; regulator or safety authority still decides approval",
    }


def _remaining_gaps(summary: dict[str, Any], failures: list[dict[str, Any]]) -> list[str]:
    gaps: list[str] = []
    failure_codes = {str(failure["code"]) for failure in failures}
    if not summary["sample_size_valid"]:
        gaps.append("increase official-level seed count")
    if "insufficient_evidence_level_sample_size" in failure_codes:
        gaps.append("increase ranked runs per official evidence level")
    if summary["official_missing_weight"] > 0.0:
        gaps.append("restore missing official coverage weight")
    if {"insufficient_success_confidence", "insufficient_per_level_success_confidence"} & failure_codes:
        gaps.append("improve lower confidence bound on success rate")
    if {"insufficient_collision_confidence", "insufficient_per_level_collision_confidence"} & failure_codes:
        gaps.append("improve upper confidence bound on collision rate")
    if "insufficient_per_level_driving_quality" in failure_codes:
        gaps.append("improve driving quality: safety margin, route discipline, comfort, and intervention burden")
    gaps.append("validate abstract-sim findings in sensor-realistic AlpaSim tier")
    gaps.append("document real-world ODD mismatch before any deployment claim")
    return gaps


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a COMPASS SOTIF-aligned evidence package.")
    parser.add_argument("--policy", default="spotlight-reflex", choices=("baseline", "spotlight-reflex"))
    parser.add_argument("--profile", default="sotif-v0", choices=tuple(sorted(EVIDENCE_PROFILES)))
    parser.add_argument("--odd-spec", type=Path, help="Optional JSON file overriding the selected profile ODD.")
    parser.add_argument("--thresholds", type=Path, help="Optional JSON file overriding the selected profile thresholds.")
    parser.add_argument(
        "--compass-profile-json",
        type=Path,
        help="Optional JSON file overriding the benchmark scoring profile used by the evidence report.",
    )
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seed-end", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("artifacts/compass_evidence_report.json"))
    args = parser.parse_args()

    profile = profile_by_name(args.profile)
    odd_spec = load_odd_spec(args.odd_spec) if args.odd_spec else profile.odd_spec
    thresholds = load_thresholds(args.thresholds) if args.thresholds else profile.thresholds
    compass_profile = (
        load_compass_profile(args.compass_profile_json)
        if args.compass_profile_json
        else compass_profile_by_name(profile.compass_profile)
    )
    report = generate_evidence_report(
        args.policy,
        range(args.seed_start, args.seed_end + 1),
        odd_spec=odd_spec,
        thresholds=thresholds,
        profile_name=profile.name,
        compass_profile=compass_profile,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    stats = report["statistical_evidence"]
    print(f"Evidence profile: {report['evidence_profile']}")
    print(f"Evidence status: {report['evidence_status']}")
    print(
        "success={success:.3f} [{low:.3f}, {high:.3f}] collision={collision:.3f} [{clow:.3f}, {chigh:.3f}]".format(
            success=stats["success_rate"]["estimate"],
            low=stats["success_rate"]["lower"],
            high=stats["success_rate"]["upper"],
            collision=stats["collision_rate"]["estimate"],
            clow=stats["collision_rate"]["lower"],
            chigh=stats["collision_rate"]["upper"],
        )
    )
    _print_level_evidence(stats["official_level_evidence"])
    print(f"Wrote {args.output}")


def _print_level_evidence(level_evidence: list[dict[str, Any]]) -> None:
    for level in level_evidence:
        print(
            "L{level} {name:14s} runs={runs:4d} sample={sample} "
            "success_lb={success_lb:.3f} collision_ub={collision_ub:.3f} "
            "score={score:.2f} safe={safe:.2f} route={route:.2f} comfort={comfort:.2f} "
            "worst={worst:.2f}/{worst_safe:.2f}/{worst_route:.2f}/{worst_comfort:.2f}".format(
                level=level["level"],
                name=level["name"],
                runs=level["ranked_runs"],
                sample=level["sample_size_valid"],
                success_lb=level["success_rate"]["lower"],
                collision_ub=level["collision_rate"]["upper"],
                score=level["quality"]["compass_score"],
                safe=level["quality"]["safety_score"],
                route=level["quality"]["route_quality_score"],
                comfort=level["quality"]["comfort_score"],
                worst=level["quality"]["worst_compass_score"],
                worst_safe=level["quality"]["worst_safety_score"],
                worst_route=level["quality"]["worst_route_quality_score"],
                worst_comfort=level["quality"]["worst_comfort_score"],
            )
        )


if __name__ == "__main__":
    main()
