from __future__ import annotations

import numpy as np
import pytest

from alpabridge.simulator.image_ops import resize_and_center_crop

TARGET_HEIGHT, TARGET_WIDTH = 900, 1600


def test_resize_and_center_crop_handles_narrower_than_target_aspect_ratio() -> None:
    pytest.importorskip("PIL")
    # Real camera feed dimensions that triggered a live rollout failure:
    # 568x320 (aspect ~1.775) is very slightly narrower than the 1600x900
    # (~1.778) target, so scaling by height alone always falls a couple
    # pixels short on width, however the fractional pixel is rounded.
    image = np.random.default_rng(0).integers(0, 256, size=(320, 568, 3), dtype=np.uint8)

    result = resize_and_center_crop(image, TARGET_HEIGHT, TARGET_WIDTH)

    assert result.shape == (TARGET_HEIGHT, TARGET_WIDTH, 3)


def test_resize_and_center_crop_handles_wider_than_target_aspect_ratio() -> None:
    pytest.importorskip("PIL")
    image = np.random.default_rng(0).integers(0, 256, size=(300, 800, 3), dtype=np.uint8)

    result = resize_and_center_crop(image, TARGET_HEIGHT, TARGET_WIDTH)

    assert result.shape == (TARGET_HEIGHT, TARGET_WIDTH, 3)


def test_resize_and_center_crop_is_noop_at_exact_target_size() -> None:
    pytest.importorskip("PIL")
    image = np.zeros((TARGET_HEIGHT, TARGET_WIDTH, 3), dtype=np.uint8)

    result = resize_and_center_crop(image, TARGET_HEIGHT, TARGET_WIDTH)

    np.testing.assert_array_equal(result, image)


def test_resize_and_center_crop_handles_taller_than_target_aspect_ratio() -> None:
    pytest.importorskip("PIL")
    # Source is relatively taller than target (needs width-driven cover scale).
    image = np.random.default_rng(1).integers(0, 256, size=(1000, 1600, 3), dtype=np.uint8)

    result = resize_and_center_crop(image, TARGET_HEIGHT, TARGET_WIDTH)

    assert result.shape == (TARGET_HEIGHT, TARGET_WIDTH, 3)
