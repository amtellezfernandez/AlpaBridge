"""Tests for _yaw_from_quat_like, AlpaBridge's yaw-from-quaternion
extraction (alpasim_contract.py).

Deliberately structured to mirror AlpaSim's own yaw test
(TestPose::test_yaw in src/utils/tests/test_utils_rs.py) - plain classes,
bare asserts, numpy.testing.assert_allclose for float comparisons - rather
than this repo's more common unittest.TestCase style, since this is the
one place both projects independently implement the exact same formula
(atan2(2*(w*z+x*y), 1-2*(y*y+z*z)), see utils_rs/src/pose.rs's Pose.yaw())
and disagreeing here is a real, previously-shipped bug, not just a style
choice. Keeping the test shape recognizably similar makes it easy for
someone maintaining both projects to tell at a glance that they agree.

AlpaSim's own test only covers the pure-yaw case (no roll/pitch) - see
test_combined_roll_and_pitch below for the case that actually exposed the
bug this file guards against.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

from numpy.testing import assert_allclose

from alpabridge.simulator.alpasim_contract import (
    _pose_like_to_signature,
    _yaw_from_quat_like,
)


def _quat_from_euler(roll: float, pitch: float, yaw: float) -> SimpleNamespace:
    """Build a scipy-convention (x, y, z, w) quaternion from ZYX Euler
    angles - the same convention alpasim_utils.geometry documents its own
    Pose type as using ("Quaternions use scipy convention (x, y, z, w)
    internally.")."""
    cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    return SimpleNamespace(
        w=cr * cp * cy + sr * sp * sy,
        x=sr * cp * cy - cr * sp * sy,
        y=cr * sp * cy + sr * cp * sy,
        z=cr * cp * sy - sr * sp * cy,
    )


class TestYawFromQuatLike:
    """Tests for _yaw_from_quat_like."""

    def test_pure_yaw(self) -> None:
        # Same case as AlpaSim's own TestPose::test_yaw: no roll/pitch,
        # so x=y=0 and the pure-yaw shortcut this function used to
        # hardcode happens to already be exactly correct here.
        yaw = math.pi / 2
        quat = _quat_from_euler(0.0, 0.0, yaw)

        assert_allclose(_yaw_from_quat_like(quat), yaw, atol=1e-6)

    def test_combined_roll_and_pitch(self) -> None:
        # The case AlpaSim's own test suite doesn't cover: a combined ~10
        # degree roll+pitch (a plausible hard-brake-while-cornering
        # moment) - the previous x=y=0 shortcut computed yaw with ~0.02
        # rad of error here, enough to trip SensorFreshnessGuard's 0.01
        # rad pose-changed threshold on tilt alone.
        true_yaw = 0.3
        quat = _quat_from_euler(math.radians(10), math.radians(10), true_yaw)

        assert_allclose(_yaw_from_quat_like(quat), true_yaw, atol=1e-4)

    def test_quat_missing_x_and_y_still_works(self) -> None:
        # Some quat-like objects in this codebase only ever expose z/w -
        # x/y must default to 0.0 (reducing to the pure-yaw case), not
        # raise.
        half = 0.15
        stub = SimpleNamespace(z=math.sin(half), w=math.cos(half))

        assert_allclose(_yaw_from_quat_like(stub), 0.3, atol=1e-6)

    def test_quat_missing_every_field_defaults_to_identity(self) -> None:
        # Regression test: this used to return None when z/w were both
        # absent, which crashed _pose_like_to_signature's final
        # round(float(yaw), 6) with an uncaught TypeError. A quat object
        # present but missing fields must degrade to "no rotation known"
        # (yaw=0.0), the same as an entirely absent quat, not raise.
        assert _yaw_from_quat_like(None) == 0.0
        assert _yaw_from_quat_like(SimpleNamespace(some_other_field=1.0)) == 0.0


class TestPoseLikeToSignatureYawHandling:
    """Tests for _pose_like_to_signature's use of _yaw_from_quat_like -
    one level up from the pure formula, confirming the fix actually
    reaches the caller that used to crash."""

    def test_quat_present_but_missing_fields_degrades_instead_of_raising(self) -> None:
        pose = SimpleNamespace(x=1.0, y=2.0, quat=SimpleNamespace(some_other_field=1.0))

        assert _pose_like_to_signature(pose) == (1.0, 2.0, 0.0)
