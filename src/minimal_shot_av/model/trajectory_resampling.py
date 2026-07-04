from __future__ import annotations

from typing import Sequence

from .rfs_metric import Trajectory


def resample_trajectory(
    trajectory: Sequence[tuple[float, float]],
    *,
    source_hz: float,
    target_hz: float,
    horizon_s: float,
) -> Trajectory:
    """Resample future waypoints with linear interpolation on timestamped samples."""

    if source_hz <= 0.0 or target_hz <= 0.0 or horizon_s <= 0.0:
        raise ValueError("source_hz, target_hz, and horizon_s must be positive")
    points = [(float(x), float(y)) for x, y in trajectory]
    if not points:
        raise ValueError("trajectory must contain at least one waypoint")

    target_count = int(round(target_hz * horizon_s))
    if target_count <= 0:
        raise ValueError("target sampling produces no waypoints")

    return [
        _interpolate_at_time(points, source_hz=source_hz, timestamp_s=(index + 1) / target_hz)
        for index in range(target_count)
    ]


def resample_64wp_10hz_to_20wp_4hz(trajectory: Sequence[tuple[float, float]]) -> Trajectory:
    """Convert a 64-waypoint 10 Hz decoder output to the WOD-E2E 20 waypoint 4 Hz format."""

    return resample_trajectory(trajectory, source_hz=10.0, target_hz=4.0, horizon_s=5.0)


def _interpolate_at_time(
    points: Sequence[tuple[float, float]],
    *,
    source_hz: float,
    timestamp_s: float,
) -> tuple[float, float]:
    if timestamp_s <= 1.0 / source_hz:
        return points[0]

    source_position = timestamp_s * source_hz - 1.0
    lower_index = int(source_position)
    if lower_index >= len(points) - 1:
        return points[-1]
    upper_index = lower_index + 1
    fraction = source_position - lower_index
    lower = points[lower_index]
    upper = points[upper_index]
    return (
        lower[0] + (upper[0] - lower[0]) * fraction,
        lower[1] + (upper[1] - lower[1]) * fraction,
    )
