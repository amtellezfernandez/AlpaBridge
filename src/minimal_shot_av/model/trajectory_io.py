from __future__ import annotations

import math
from typing import Any, Sequence

from .trajectory_resampling import resample_64wp_10hz_to_20wp_4hz


def trajectory_64_to_wod20_from_payload(payload: dict[str, Any]) -> list[tuple[float, float]]:
    return trajectory_to_wod20_from_payload(payload)


def trajectory_to_wod20_from_payload(payload: dict[str, Any]) -> list[tuple[float, float]]:
    trajectory_20 = payload.get("trajectory_20wp_4hz")
    if isinstance(trajectory_20, list):
        points = [_point_from_json(item) for item in trajectory_20]
        return validate_wod20_trajectory(points)
    trajectory_64 = payload.get("trajectory_64wp_10hz")
    if isinstance(trajectory_64, list):
        points = [_point_from_json(item) for item in trajectory_64]
        if len(points) != 64:
            raise ValueError(f"expected 64 trajectory_64wp_10hz points, got {len(points)}")
        return validate_wod20_trajectory(resample_64wp_10hz_to_20wp_4hz(points))
    raise ValueError("payload is missing trajectory_20wp_4hz or trajectory_64wp_10hz")


def validate_wod20_trajectory(trajectory: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    points = [(float(x), float(y)) for x, y in trajectory]
    if len(points) != 20:
        raise ValueError(f"expected 20 WOD-E2E trajectory points, got {len(points)}")
    for index, point in enumerate(points):
        if not math.isfinite(point[0]) or not math.isfinite(point[1]):
            raise ValueError(f"trajectory point {index} is not finite")
    return points


def upsample_20wp_4hz_to_64wp_10hz(trajectory: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(trajectory) != 20:
        raise ValueError("WOD trajectory must contain 20 waypoints")
    source = [(float(x), float(y)) for x, y in trajectory]
    result: list[tuple[float, float]] = []
    for index in range(64):
        timestamp_s = (index + 1) / 10.0
        source_position = timestamp_s * 4.0 - 1.0
        if source_position <= 0.0:
            result.append(source[0])
        elif source_position >= len(source) - 1:
            result.append(source[-1])
        else:
            lower = int(source_position)
            upper = lower + 1
            fraction = source_position - lower
            result.append(
                (
                    source[lower][0] + (source[upper][0] - source[lower][0]) * fraction,
                    source[lower][1] + (source[upper][1] - source[lower][1]) * fraction,
                )
            )
    return result


def _point_from_json(item: Any) -> tuple[float, float]:
    if isinstance(item, dict):
        return (float(item["x"]), float(item["y"]))
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        return (float(item[0]), float(item[1]))
    raise ValueError(f"invalid trajectory point: {item!r}")
