from __future__ import annotations

import numpy as np

from alpabridge.simulator.alpasim_contract import DriveCommand
from alpabridge.simulator.vavam_model import (
    VAVAM_NATIVE_FREQUENCY_HZ,
    _fit_to_horizon,
    latest_camera_image,
    vavam_command_id,
)


def test_vavam_command_id_matches_documented_right_left_straight_scheme() -> None:
    assert vavam_command_id(DriveCommand.RIGHT) == 0
    assert vavam_command_id(DriveCommand.LEFT) == 1
    assert vavam_command_id(DriveCommand.STRAIGHT) == 2


def test_vavam_command_id_falls_back_to_straight_for_unknown() -> None:
    assert vavam_command_id(DriveCommand.UNKNOWN) == 2
    assert vavam_command_id("not-a-command") == 2
    assert vavam_command_id(None) == 2


def test_fit_to_horizon_truncates_when_native_trajectory_is_longer() -> None:
    native = np.arange(20, dtype=np.float32).reshape(10, 2)  # 10 points @ 2Hz = 5s native

    fitted, timestamps_s, extrapolated = _fit_to_horizon(
        native, native_frequency_hz=VAVAM_NATIVE_FREQUENCY_HZ, horizon_seconds=3.0
    )

    assert extrapolated is False
    assert fitted.shape == (6, 2)  # 3.0s * 2Hz = 6 points
    np.testing.assert_array_equal(fitted, native[:6])
    assert timestamps_s[-1] <= 3.0
    assert timestamps_s[0] > 0.0


def test_fit_to_horizon_holds_last_position_when_native_trajectory_is_shorter() -> None:
    native = np.array([[0.0, 0.0], [1.0, 0.5]], dtype=np.float32)  # 2 points @ 2Hz = 1s native

    fitted, timestamps_s, extrapolated = _fit_to_horizon(
        native, native_frequency_hz=VAVAM_NATIVE_FREQUENCY_HZ, horizon_seconds=2.5
    )

    assert extrapolated is True
    assert fitted.shape == (5, 2)  # 2.5s * 2Hz = 5 points
    np.testing.assert_array_equal(fitted[:2], native)
    np.testing.assert_array_equal(fitted[2:], np.tile(native[-1], (3, 1)))
    assert timestamps_s[-1] <= 2.5


def test_fit_to_horizon_timestamps_never_exceed_horizon_despite_rounding() -> None:
    native = np.zeros((7, 2), dtype=np.float32)

    _, timestamps_s, _ = _fit_to_horizon(
        native, native_frequency_hz=VAVAM_NATIVE_FREQUENCY_HZ, horizon_seconds=3.3
    )

    assert np.all(timestamps_s <= 3.3)
    assert np.all(timestamps_s > 0.0)


def test_latest_camera_image_returns_most_recent_frame() -> None:
    class _Frame:
        def __init__(self, image: np.ndarray) -> None:
            self.image = image

    older = np.zeros((2, 2, 3), dtype=np.uint8)
    newest = np.ones((2, 2, 3), dtype=np.uint8)
    camera_images = {"front": [_Frame(older), _Frame(newest)]}

    result = latest_camera_image(camera_images, "front")

    np.testing.assert_array_equal(result, newest)


def test_latest_camera_image_requires_at_least_one_frame() -> None:
    try:
        latest_camera_image({"front": []}, "front")
    except ValueError as exc:
        assert "front" in str(exc)
    else:
        raise AssertionError("expected ValueError for missing camera frames")
