"""The route follower's speed ramp.

The historical sampler multiplies its time grid by the current speed, which
locks the launch speed in for the whole rollout. The ramp accelerates toward a
target instead, and is disabled by default so the historical behaviour is
preserved byte for byte.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import pytest
from alpabridge.simulator.baseline_drivers import (
    _ramp_settings,
    _ramped_distances,
    _sample_route,
)

TIMES = np.linspace(0.25, 5.0, 20)


class TestRampedDistances:
    def test_disabled_ramp_is_exactly_constant_speed(self) -> None:
        distances = _ramped_distances(
            TIMES, speed_mps=3.0, target_speed_mps=0.0, accel_mps2=1.5
        )

        assert np.array_equal(distances, TIMES * 3.0)

    def test_ramp_up_matches_closed_form(self) -> None:
        # v0=2, target=10, a=2 -> ramp ends at t=4s;
        # d(5) = 2*4 + 0.5*2*16 + 10*1 = 34.
        distances = _ramped_distances(
            TIMES, speed_mps=2.0, target_speed_mps=10.0, accel_mps2=2.0
        )

        assert distances[-1] == pytest.approx(34.0)
        assert np.all(np.diff(distances) > 0), "distance must be monotone"

    def test_ramp_down_matches_closed_form(self) -> None:
        # v0=12, target=6, a=3 -> ramp ends at t=2s;
        # d(5) = 12*2 - 0.5*3*4 + 6*3 = 36.
        distances = _ramped_distances(
            TIMES, speed_mps=12.0, target_speed_mps=6.0, accel_mps2=3.0
        )

        assert distances[-1] == pytest.approx(36.0)

    def test_target_equal_to_current_speed_is_constant(self) -> None:
        distances = _ramped_distances(
            TIMES, speed_mps=7.0, target_speed_mps=7.0, accel_mps2=2.0
        )

        assert np.allclose(distances, TIMES * 7.0)


class TestRampSettings:
    def test_defaults_to_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ALPABRIDGE_RF_TARGET_SPEED_MPS", raising=False)
        monkeypatch.delenv("ALPABRIDGE_RF_ACCEL_MPS2", raising=False)

        assert _ramp_settings() == (0.0, 1.5)

    def test_valid_override_applies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALPABRIDGE_RF_TARGET_SPEED_MPS", "9.0")
        monkeypatch.setenv("ALPABRIDGE_RF_ACCEL_MPS2", "2.0")

        assert _ramp_settings() == (9.0, 2.0)

    @pytest.mark.parametrize("raw", ["junk", "nan", "-inf", ""])
    def test_unusable_values_disable_rather_than_raise(
        self, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        monkeypatch.setenv("ALPABRIDGE_RF_TARGET_SPEED_MPS", raw)

        target, accel = _ramp_settings()

        assert target == 0.0
        assert accel > 0.0


class TestSampleRouteWithRamp:
    ROUTE: ClassVar[list[tuple[float, float]]] = [
        (float(x), 0.0) for x in range(0, 120, 4)
    ]

    def test_ramp_covers_more_route_from_a_slow_start(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPABRIDGE_RF_TARGET_SPEED_MPS", "0")
        locked = _sample_route(
            self.ROUTE, speed_mps=2.0, horizon_seconds=5.0, point_count=20
        )

        monkeypatch.setenv("ALPABRIDGE_RF_TARGET_SPEED_MPS", "9.0")
        ramped = _sample_route(
            self.ROUTE, speed_mps=2.0, horizon_seconds=5.0, point_count=20
        )

        assert ramped[-1][0] > locked[-1][0] * 2

    def test_disabled_ramp_reproduces_historical_samples_exactly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ALPABRIDGE_RF_TARGET_SPEED_MPS", raising=False)
        samples = _sample_route(
            self.ROUTE, speed_mps=4.0, horizon_seconds=5.0, point_count=20
        )
        # Historical behaviour: point k sits at t_k * v0 along the route.
        times = np.linspace(0.25, 5.0, 20)

        assert np.allclose(samples[:, 0], times * 4.0, atol=1e-4)
