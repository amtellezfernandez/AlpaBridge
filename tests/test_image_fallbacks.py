from __future__ import annotations

import logging

import pytest

from alpabridge.driver.driver_service import (
    _FALLBACK_WARNINGS,
    _image_array_from_bytes,
)


def test_empty_camera_frame_announces_itself_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An empty frame degrades like a decode failure, so it should say so too."""
    _FALLBACK_WARNINGS.discard("image-bytes-empty")
    with caplog.at_level(logging.WARNING):
        first = _image_array_from_bytes(b"")
        second = _image_array_from_bytes(b"")

    assert first.shape == (1,)
    assert second.shape == (1,)
    warnings = [r for r in caplog.records if "no image bytes" in r.getMessage()]
    assert len(warnings) == 1
