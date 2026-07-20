from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from wod2sim.simulator.alpasim_contract import DriveCommand
from wod2sim.simulator.navsim_ego_status_mlp import (
    navsim_ego_status_feature,
)


def test_navsim_ego_status_feature_matches_published_eight_value_contract() -> None:
    feature = navsim_ego_status_feature(
        SimpleNamespace(
            velocity_xy=(7.5, -0.25),
            acceleration_xy=(0.75, 0.125),
            command=DriveCommand.LEFT,
        )
    )

    np.testing.assert_array_equal(
        feature,
        np.asarray(
            [7.5, -0.25, 0.75, 0.125, 1.0, 0.0, 0.0, 0.0],
            dtype=np.float32,
        ),
    )


def test_navsim_ego_status_feature_falls_back_to_scalar_kinematics() -> None:
    feature = navsim_ego_status_feature(
        SimpleNamespace(
            speed=3.5,
            acceleration=0.5,
            command=DriveCommand.RIGHT,
        )
    )

    np.testing.assert_array_equal(
        feature,
        np.asarray(
            [3.5, 0.0, 0.5, 0.0, 0.0, 0.0, 1.0, 0.0],
            dtype=np.float32,
        ),
    )
