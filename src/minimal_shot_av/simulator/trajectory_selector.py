from __future__ import annotations

from dataclasses import dataclass, field
import math


Trajectory = list[tuple[float, float]]


@dataclass(frozen=True)
class TrajectorySelectorConfig:
    index_3s: int = 11
    index_5s: int = 19
    lateral_3s_m: float = 1.0
    longitudinal_3s_m: float = 4.0
    lateral_5s_m: float = 1.8
    longitudinal_5s_m: float = 7.2
    score_floor: float = 4.0
    outside_region_decay_base: float = 0.1
    score_3s_weight: float = 0.5
    score_5s_weight: float = 0.5
    speed_scale_min_speed_mps: float = 1.4
    speed_scale_max_speed_mps: float = 11.0
    speed_scale_min_value: float = 0.5
    speed_scale_max_value: float = 1.0


DEFAULT_TRAJECTORY_SELECTOR_CONFIG = TrajectorySelectorConfig()


@dataclass(frozen=True)
class TrajectoryCandidate:
    name: str
    trajectory: Trajectory
    confidence: float = 1.0
    source: str = "deterministic_maneuver_library"
    metadata: dict[str, float | str] = field(default_factory=dict)


@dataclass(frozen=True)
class TrajectoryReference:
    label: str
    trajectory: Trajectory
    score: float


@dataclass(frozen=True)
class TrajectorySelectorScore:
    combined_score: float
    score_3s: float
    score_5s: float
    reference_3s_label: str
    reference_5s_label: str
    inside_3s_region: bool
    inside_5s_region: bool


def speed_scale(speed_mps: float, config: TrajectorySelectorConfig | None = None) -> float:
    config = config or DEFAULT_TRAJECTORY_SELECTOR_CONFIG
    if speed_mps <= config.speed_scale_min_speed_mps:
        return config.speed_scale_min_value
    if speed_mps >= config.speed_scale_max_speed_mps:
        return config.speed_scale_max_value
    ratio = (speed_mps - config.speed_scale_min_speed_mps) / (
        config.speed_scale_max_speed_mps - config.speed_scale_min_speed_mps
    )
    return config.speed_scale_min_value + (config.speed_scale_max_value - config.speed_scale_min_value) * ratio


def trajectory_region_score(
    candidate: Trajectory,
    reference: Trajectory,
    reference_score: float,
    speed_mps: float,
    index: int,
    config: TrajectorySelectorConfig | None = None,
) -> tuple[float, bool]:
    config = config or DEFAULT_TRAJECTORY_SELECTOR_CONFIG
    if index == config.index_3s:
        lateral_threshold = config.lateral_3s_m
        longitudinal_threshold = config.longitudinal_3s_m
    elif index == config.index_5s:
        lateral_threshold = config.lateral_5s_m
        longitudinal_threshold = config.longitudinal_5s_m
    else:
        raise ValueError(f"unsupported trajectory selector index: {index}")

    if len(candidate) <= index or len(reference) <= index:
        raise ValueError("candidate and reference trajectories must contain the requested selector index")

    scale = speed_scale(speed_mps, config)
    lateral_threshold *= scale
    longitudinal_threshold *= scale

    tangent = _reference_tangent(reference, index)
    normal = (-tangent[1], tangent[0])
    dx = candidate[index][0] - reference[index][0]
    dy = candidate[index][1] - reference[index][1]
    longitudinal_error = abs(dx * tangent[0] + dy * tangent[1])
    lateral_error = abs(dx * normal[0] + dy * normal[1])

    longitudinal_overshoot = max(0.0, longitudinal_error / longitudinal_threshold - 1.0)
    lateral_overshoot = max(0.0, lateral_error / lateral_threshold - 1.0)
    overshoot = max(longitudinal_overshoot, lateral_overshoot)
    inside = overshoot == 0.0
    if inside:
        return reference_score, True
    return max(reference_score * (config.outside_region_decay_base**overshoot), config.score_floor), False


def score_candidate(
    candidate: TrajectoryCandidate,
    references: list[TrajectoryReference],
    speed_mps: float,
    config: TrajectorySelectorConfig | None = None,
) -> TrajectorySelectorScore:
    config = config or DEFAULT_TRAJECTORY_SELECTOR_CONFIG
    if not references:
        raise ValueError("at least one RFS reference is required")

    best_3s = _best_reference_score(candidate.trajectory, references, speed_mps, config.index_3s, config)
    best_5s = _best_reference_score(candidate.trajectory, references, speed_mps, config.index_5s, config)
    combined = config.score_3s_weight * best_3s[0] + config.score_5s_weight * best_5s[0]
    return TrajectorySelectorScore(
        combined_score=combined,
        score_3s=best_3s[0],
        score_5s=best_5s[0],
        reference_3s_label=best_3s[1].label,
        reference_5s_label=best_5s[1].label,
        inside_3s_region=best_3s[2],
        inside_5s_region=best_5s[2],
    )


def _best_reference_score(
    candidate: Trajectory,
    references: list[TrajectoryReference],
    speed_mps: float,
    index: int,
    config: TrajectorySelectorConfig,
) -> tuple[float, TrajectoryReference, bool]:
    best_score = -math.inf
    best_reference = references[0]
    best_inside = False
    for reference in references:
        score, inside = trajectory_region_score(candidate, reference.trajectory, reference.score, speed_mps, index, config)
        if score > best_score:
            best_score = score
            best_reference = reference
            best_inside = inside
    return best_score, best_reference, best_inside


def _reference_tangent(reference: Trajectory, index: int) -> tuple[float, float]:
    if index > 0:
        tangent = (reference[index][0] - reference[index - 1][0], reference[index][1] - reference[index - 1][1])
    else:
        tangent = (reference[1][0] - reference[0][0], reference[1][1] - reference[0][1])
    normalized = _normalize(tangent)
    if normalized == (0.0, 0.0):
        return (1.0, 0.0)
    return normalized


def _normalize(vector: tuple[float, float]) -> tuple[float, float]:
    norm = math.hypot(vector[0], vector[1])
    if norm == 0.0:
        return (0.0, 0.0)
    return (vector[0] / norm, vector[1] / norm)
