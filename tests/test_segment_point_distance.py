"""Tests for segment_point_distance / _distance_to_polyline, AlpaBridge's
point-to-polyline projection math (environment.py, mpc_planner.py).

Deliberately structured to mirror AlpaSim's own polyline-projection tests
(src/utils/tests/test_polyline.py's test_project_point_to_polyline_mid_segment
and test_polyline_degenerate_segments) - plain functions, bare asserts -
since this function's clamped-projection math was confirmed algorithmically
equivalent to AlpaSim's real Polyline.project_point (utils_rs/src/polyline.rs)
during an audit of AlpaBridge/AlpaSim logic overlap. AlpaBridge's version is
2D (ground-plane) and returns only the scalar distance, not AlpaSim's
richer (projected_point, segment_idx, distance_along) tuple, since that is
all mpc_planner's route-tracking cost needs - but the underlying per-segment
clamped-projection formula is the same one, so the same geometric cases are
worth testing here.
"""

from __future__ import annotations

import pytest

from alpabridge.simulator.environment import segment_point_distance
from alpabridge.simulator.mpc_planner import _distance_to_polyline


def test_distance_to_mid_segment() -> None:
    # Same geometry as AlpaSim's test_project_point_to_polyline_mid_segment:
    # an L-shaped polyline, point (4, 3) projects onto the first segment at
    # (4, 0), distance 3.0.
    polyline = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]

    assert segment_point_distance(polyline[0], polyline[1], (4.0, 3.0)) == pytest.approx(3.0)
    assert _distance_to_polyline((4.0, 3.0), polyline) == pytest.approx(3.0)


def test_distance_clamps_past_segment_end() -> None:
    # Point projects beyond the segment's end - the clamped projection must
    # fall back to the endpoint distance, not extrapolate past it (mirrors
    # AlpaSim's remaining_from_point end-of-route clamping behavior).
    polyline = [(0.0, 0.0), (10.0, 0.0)]

    assert _distance_to_polyline((20.0, 0.0), polyline) == pytest.approx(10.0)


def test_distance_across_a_degenerate_zero_length_segment() -> None:
    # Same case as AlpaSim's test_polyline_degenerate_segments: a repeated
    # waypoint produces a zero-length segment. A point abeam the repeated
    # waypoint must still project onto it (distance 5.0), not raise or
    # divide by zero.
    polyline = [(0.0, 0.0), (10.0, 0.0), (10.0, 0.0), (20.0, 0.0)]

    assert _distance_to_polyline((10.0, 5.0), polyline) == pytest.approx(5.0)


def test_distance_to_nearest_of_several_segments_not_nearest_vertex() -> None:
    # Regression test: a naive "nearest discrete vertex" distance would
    # overstate this as the distance to (10, 0) or (10, 10) - the correct
    # perpendicular distance to the segment between them is 1.0.
    polyline = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]

    assert _distance_to_polyline((9.0, 5.0), polyline) == pytest.approx(1.0)
