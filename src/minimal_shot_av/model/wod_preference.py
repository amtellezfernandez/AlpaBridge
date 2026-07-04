from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

from .rfs_metric import Trajectory
from .wod_e2e import WodE2EPreferenceFrame


@dataclass(frozen=True)
class PreferenceCandidate:
    name: str
    trajectory: Trajectory
    features: dict[str, float | int | str]


def generate_preference_candidates(frame: WodE2EPreferenceFrame) -> list[PreferenceCandidate]:
    """Generate simple verifier candidates for one WOD-E2E validation frame."""

    heading = (1.0, 0.0)
    speed = max(0.0, frame.init_speed_mps)
    logged_future = frame.future_trajectory
    turn_bias = _intent_turn_bias(frame.intent)

    specs = [
        ("logged_future", logged_future),
        ("constant_velocity", _constant_velocity(heading, speed)),
        ("stop", _constant_velocity(heading, 0.0)),
        ("crawl", _constant_velocity(heading, max(0.35, speed * 0.25))),
        ("maintain", _constant_velocity(heading, max(0.75, speed))),
        ("accelerate", _constant_accel(heading, speed, accel_mps2=0.8)),
        ("slow_yield", _constant_velocity(heading, max(0.45, speed * 0.55))),
        ("decel_soft", _constant_accel(heading, speed, accel_mps2=-0.8)),
        ("decel_hard", _constant_accel(heading, speed, accel_mps2=-1.8)),
        ("stop_by_3s", _decelerate_to_stop(heading, speed, stop_time_s=3.0)),
        ("stop_by_5s", _decelerate_to_stop(heading, speed, stop_time_s=5.0)),
    ]
    for offset in (0.5, 1.0, 2.0, 3.5):
        specs.append((f"offset_left_{offset:g}m", _offset_trajectory(heading, max(0.65, speed * 0.85), offset)))
        specs.append((f"offset_right_{offset:g}m", _offset_trajectory(heading, max(0.65, speed * 0.85), -offset)))
    for lateral_accel in (0.35, 0.7, 1.1):
        specs.append((f"arc_left_{lateral_accel:g}", _arc_trajectory(speed, abs(lateral_accel))))
        specs.append((f"arc_right_{lateral_accel:g}", _arc_trajectory(speed, -abs(lateral_accel))))
    if turn_bias != 0.0:
        side = "left" if turn_bias > 0.0 else "right"
        specs.append((f"intent_{side}_arc", _arc_trajectory(max(speed, 2.0), turn_bias * 1.4)))
        specs.append((f"intent_{side}_wide", _offset_trajectory(heading, max(0.65, speed * 0.75), turn_bias * 3.5)))

    candidates: list[PreferenceCandidate] = []
    for name, trajectory in specs:
        aligned = _ensure_twenty_points(trajectory)
        candidates.append(
            PreferenceCandidate(
                name=name,
                trajectory=aligned,
                features=trajectory_features(
                    aligned,
                    candidate_name=name,
                    intent=frame.intent,
                    init_speed_mps=frame.init_speed_mps,
                ),
            )
        )
    return candidates


def trajectory_features(
    trajectory: Trajectory,
    *,
    candidate_name: str,
    intent: int,
    init_speed_mps: float,
) -> dict[str, float | int | str]:
    if len(trajectory) != 20:
        raise ValueError("trajectory features expect exactly 20 points")

    x_values = [point[0] for point in trajectory]
    y_values = [point[1] for point in trajectory]
    step_distances = [
        math.dist((0.0, 0.0), trajectory[0]),
        *[
            math.dist(trajectory[index - 1], trajectory[index])
            for index in range(1, len(trajectory))
        ],
    ]
    total_distance = sum(step_distances)
    endpoint = trajectory[-1]
    point_3s = trajectory[11]
    point_5s = trajectory[19]
    mean_step = total_distance / len(step_distances)
    max_step = max(step_distances)
    min_step = min(step_distances)
    lateral_range = max(y_values) - min(y_values)
    speeds = [distance * 4.0 for distance in step_distances]
    accels = [(speeds[index] - speeds[index - 1]) * 4.0 for index in range(1, len(speeds))]
    lateral_steps = [
        trajectory[0][1],
        *[trajectory[index][1] - trajectory[index - 1][1] for index in range(1, len(trajectory))],
    ]
    heading_changes = _heading_changes(trajectory)
    expected_5s_progress = max(0.0, float(init_speed_mps)) * 5.0
    forward_deltas = [
        trajectory[0][0],
        *[trajectory[index][0] - trajectory[index - 1][0] for index in range(1, len(trajectory))],
    ]
    reverse_distance = sum(max(0.0, -delta) for delta in forward_deltas)
    monotonic_forward_rate = sum(1.0 for delta in forward_deltas if delta >= -1e-6) / len(forward_deltas)
    signed_lateral_3s = float(point_3s[1])
    signed_lateral_5s = float(endpoint[1])
    lateral_to_progress_ratio = abs(signed_lateral_5s) / max(1.0, float(point_5s[0]))
    curvature_per_meter = (
        sum(abs(value) for value in heading_changes) / max(1.0, total_distance)
        if heading_changes
        else 0.0
    )
    final_speed_ratio = speeds[-1] / max(1.0, float(init_speed_mps))
    progress_ratio_5s = float(point_5s[0]) / max(1.0, expected_5s_progress)
    progress_error_5s = float(point_5s[0]) - expected_5s_progress
    stop_distance_error = abs(float(point_5s[0])) if init_speed_mps < 1.4 else abs(progress_error_5s)
    turn_direction = _intent_turn_bias(intent)
    turn_lateral_alignment_3s = turn_direction * signed_lateral_3s
    turn_lateral_alignment_5s = turn_direction * signed_lateral_5s

    features: dict[str, float | int | str] = {
        "candidate_name": candidate_name,
        "candidate_family": _candidate_family(candidate_name),
        "intent": int(intent),
        "init_speed_mps": float(init_speed_mps),
        "x_3s": float(point_3s[0]),
        "y_3s": float(point_3s[1]),
        "x_5s": float(point_5s[0]),
        "y_5s": float(point_5s[1]),
        "endpoint_distance": float(math.hypot(endpoint[0], endpoint[1])),
        "total_distance": float(total_distance),
        "mean_step_distance": float(mean_step),
        "max_step_distance": float(max_step),
        "min_step_distance": float(min_step),
        "final_lateral_abs": float(abs(endpoint[1])),
        "max_lateral_abs": float(max(abs(value) for value in y_values)),
        "lateral_range": float(lateral_range),
        "forward_progress": float(max(x_values) - min(0.0, min(x_values))),
        "mean_speed_mps": float(sum(speeds) / len(speeds)),
        "max_speed_mps": float(max(speeds)),
        "final_speed_mps": float(speeds[-1]),
        "mean_abs_accel_mps2": float(sum(abs(value) for value in accels) / len(accels)) if accels else 0.0,
        "max_abs_accel_mps2": float(max(abs(value) for value in accels)) if accels else 0.0,
        "mean_abs_lateral_step": float(sum(abs(value) for value in lateral_steps) / len(lateral_steps)),
        "max_abs_lateral_step": float(max(abs(value) for value in lateral_steps)),
        "signed_lateral_3s": signed_lateral_3s,
        "signed_lateral_5s": signed_lateral_5s,
        "intent_turn_alignment": float(turn_lateral_alignment_5s),
        "turn_lateral_alignment_3s": float(turn_lateral_alignment_3s),
        "turn_lateral_alignment_5s": float(turn_lateral_alignment_5s),
        "expected_progress_5s": float(expected_5s_progress),
        "progress_ratio_5s": float(progress_ratio_5s),
        "progress_error_5s": float(progress_error_5s),
        "progress_error_abs_5s": float(abs(progress_error_5s)),
        "stop_distance_error": float(stop_distance_error),
        "reverse_distance": float(reverse_distance),
        "monotonic_forward_rate": float(monotonic_forward_rate),
        "lateral_to_progress_ratio": float(lateral_to_progress_ratio),
        "curvature_per_meter": float(curvature_per_meter),
        "final_speed_ratio": float(final_speed_ratio),
        "mean_abs_heading_change": (
            float(sum(abs(value) for value in heading_changes) / len(heading_changes))
            if heading_changes
            else 0.0
        ),
        "max_abs_heading_change": float(max(abs(value) for value in heading_changes)) if heading_changes else 0.0,
    }
    for second in range(1, 6):
        point = trajectory[second * 4 - 1]
        features[f"x_{second}s"] = float(point[0])
        features[f"y_{second}s"] = float(point[1])
    return features


def _constant_velocity(heading: tuple[float, float], speed_mps: float) -> Trajectory:
    return [
        (
            heading[0] * speed_mps * (step / 4.0),
            heading[1] * speed_mps * (step / 4.0),
        )
        for step in range(1, 21)
    ]


def _constant_accel(
    heading: tuple[float, float],
    initial_speed_mps: float,
    *,
    accel_mps2: float,
) -> Trajectory:
    trajectory: Trajectory = []
    for step in range(1, 21):
        seconds = step / 4.0
        distance = max(0.0, initial_speed_mps * seconds + 0.5 * accel_mps2 * seconds * seconds)
        trajectory.append((heading[0] * distance, heading[1] * distance))
    return trajectory


def _decelerate_to_stop(
    heading: tuple[float, float],
    initial_speed_mps: float,
    *,
    stop_time_s: float,
) -> Trajectory:
    if initial_speed_mps <= 0.0:
        return _constant_velocity(heading, 0.0)
    accel = -initial_speed_mps / max(stop_time_s, 1e-6)
    stop_distance = 0.5 * initial_speed_mps * stop_time_s
    trajectory: Trajectory = []
    for step in range(1, 21):
        seconds = step / 4.0
        if seconds < stop_time_s:
            distance = initial_speed_mps * seconds + 0.5 * accel * seconds * seconds
        else:
            distance = stop_distance
        trajectory.append((heading[0] * distance, heading[1] * distance))
    return trajectory


def _offset_trajectory(
    heading: tuple[float, float],
    speed_mps: float,
    final_lateral_offset: float,
) -> Trajectory:
    left = (-heading[1], heading[0])
    trajectory: Trajectory = []
    for step in range(1, 21):
        t = step / 20.0
        smooth_t = t * t * (3.0 - 2.0 * t)
        forward_distance = speed_mps * (step / 4.0)
        lateral_distance = final_lateral_offset * smooth_t
        trajectory.append(
            (
                heading[0] * forward_distance + left[0] * lateral_distance,
                heading[1] * forward_distance + left[1] * lateral_distance,
            )
        )
    return trajectory


def _arc_trajectory(speed_mps: float, lateral_accel_mps2: float) -> Trajectory:
    forward_speed = max(0.65, speed_mps)
    trajectory: Trajectory = []
    for step in range(1, 21):
        seconds = step / 4.0
        x = forward_speed * seconds
        y = 0.5 * lateral_accel_mps2 * seconds * seconds
        trajectory.append((x, y))
    return trajectory


def _ensure_twenty_points(trajectory: Sequence[tuple[float, float]]) -> Trajectory:
    points = [(float(x), float(y)) for x, y in trajectory]
    if not points:
        raise ValueError("candidate trajectory is empty")
    if len(points) >= 20:
        return points[:20]
    return points + [points[-1]] * (20 - len(points))


def _intent_turn_bias(intent: int) -> float:
    if int(intent) == 2:
        return 1.0
    if int(intent) == 3:
        return -1.0
    return 0.0


def _candidate_family(candidate_name: str) -> str:
    if candidate_name.startswith("anchor_residual"):
        return "anchor"
    if candidate_name.startswith("ridge_residual"):
        return "ridge_residual"
    if candidate_name.startswith("offset_left"):
        return "offset_left"
    if candidate_name.startswith("offset_right"):
        return "offset_right"
    if candidate_name.startswith("arc_left") or candidate_name.startswith("intent_left"):
        return "arc_left"
    if candidate_name.startswith("arc_right") or candidate_name.startswith("intent_right"):
        return "arc_right"
    if candidate_name.startswith("decel") or candidate_name.startswith("stop_by"):
        return "decelerate"
    if candidate_name in {"stop", "crawl"}:
        return "low_speed"
    if candidate_name in {"maintain", "constant_velocity", "accelerate"}:
        return "progress"
    return candidate_name


def _heading_changes(trajectory: Trajectory) -> list[float]:
    headings: list[float] = []
    previous = (0.0, 0.0)
    for point in trajectory:
        dx = point[0] - previous[0]
        dy = point[1] - previous[1]
        if dx != 0.0 or dy != 0.0:
            headings.append(math.atan2(dy, dx))
        previous = point
    return [
        _angle_delta(headings[index], headings[index - 1])
        for index in range(1, len(headings))
    ]


def _angle_delta(current: float, previous: float) -> float:
    delta = current - previous
    while delta > math.pi:
        delta -= 2.0 * math.pi
    while delta < -math.pi:
        delta += 2.0 * math.pi
    return delta
