"""Route extent as an in-band signal.

The waypoint count is constant across scenes and therefore carries no
information. The route's arc length is not: the route is built from the
recorded drive and extended along lane centres to a fixed lookahead, so it
shortens when there is less recording left to project.
"""

from __future__ import annotations

import pytest

from alpabridge.driver.driver_service import route_arc_length_m


class TestRouteArcLength:
    def test_straight_route_measures_its_span(self) -> None:
        waypoints = [{"x": float(x), "y": 0.0, "z": 0.0} for x in range(0, 50, 10)]

        assert route_arc_length_m(waypoints) == pytest.approx(40.0)

    def test_arc_length_follows_the_path_not_the_chord(self) -> None:
        # Right angle: 3 across then 4 up is 7 m of travel, 5 m of displacement.
        waypoints = [
            {"x": 0.0, "y": 0.0, "z": 0.0},
            {"x": 3.0, "y": 0.0, "z": 0.0},
            {"x": 3.0, "y": 4.0, "z": 0.0},
        ]

        assert route_arc_length_m(waypoints) == pytest.approx(7.0)

    @pytest.mark.parametrize("waypoints", [[], [{"x": 1.0, "y": 2.0, "z": 0.0}]])
    def test_degenerate_routes_measure_zero(
        self, waypoints: list[dict[str, float]]
    ) -> None:
        assert route_arc_length_m(waypoints) == 0.0

    def test_z_is_ignored_because_the_metric_is_ground_plane(self) -> None:
        waypoints = [
            {"x": 0.0, "y": 0.0, "z": 0.0},
            {"x": 10.0, "y": 0.0, "z": 5.0},
        ]

        assert route_arc_length_m(waypoints) == pytest.approx(10.0)
