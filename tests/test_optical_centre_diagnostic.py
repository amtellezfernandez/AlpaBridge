from __future__ import annotations

from types import SimpleNamespace

import pytest

from alpabridge.simulator.vavam_model import _check_optical_centre


def _calibration(principal_point_y: float) -> SimpleNamespace:
    return SimpleNamespace(
        principal_point_x=957.5,
        principal_point_y=principal_point_y,
        width=1920,
        height=1080,
    )


def _prediction_input(source_camera_id: str, calibrations: dict) -> SimpleNamespace:
    frame = SimpleNamespace(image=None, source_camera_id=source_camera_id)
    return SimpleNamespace(camera_images={"front": [frame]}, camera_calibrations=calibrations)


def test_the_offset_is_measured_through_the_frame_source_camera() -> None:
    camera_id = "camera_front_wide_120fov"
    prediction_input = _prediction_input(camera_id, {camera_id: _calibration(743.2)})

    offset = _check_optical_centre(prediction_input, prediction_input.camera_images, "front")

    assert offset == pytest.approx(203.2)


def test_a_centred_camera_reports_a_small_offset() -> None:
    camera_id = "camera_front_tele_30fov"
    prediction_input = _prediction_input(camera_id, {camera_id: _calibration(540.0)})

    assert _check_optical_centre(
        prediction_input, prediction_input.camera_images, "front"
    ) == pytest.approx(0.0)


def test_a_frame_whose_camera_is_not_in_the_rig_reports_nothing() -> None:
    prediction_input = _prediction_input(
        "camera_not_in_the_rig", {"camera_front_wide_120fov": _calibration(743.2)}
    )

    assert _check_optical_centre(prediction_input, prediction_input.camera_images, "front") is None


def test_a_session_without_calibration_reports_nothing() -> None:
    frame = SimpleNamespace(image=None, source_camera_id="camera_front_wide_120fov")
    prediction_input = SimpleNamespace(camera_images={"front": [frame]})

    assert _check_optical_centre(prediction_input, prediction_input.camera_images, "front") is None


def test_no_frames_reports_nothing() -> None:
    prediction_input = SimpleNamespace(camera_images={}, camera_calibrations={})

    assert _check_optical_centre(prediction_input, prediction_input.camera_images, "front") is None


@pytest.mark.parametrize(("principal_point_y", "expect_warning"), [(743.2, True), (545.0, False)])
def test_a_far_optical_centre_says_so_once(
    caplog: pytest.LogCaptureFixture, principal_point_y: float, expect_warning: bool
) -> None:
    from alpabridge.simulator import vavam_model

    camera_id = f"camera_probe_{principal_point_y}"
    vavam_model._CENTRE_WARNINGS.discard(f"optical-centre-offset-{camera_id}")
    prediction_input = _prediction_input(camera_id, {camera_id: _calibration(principal_point_y)})

    with caplog.at_level("WARNING"):
        _check_optical_centre(prediction_input, prediction_input.camera_images, "front")
        _check_optical_centre(prediction_input, prediction_input.camera_images, "front")

    warnings = [r for r in caplog.records if "optical centre" in r.getMessage()]
    assert len(warnings) == (1 if expect_warning else 0)
    if expect_warning:
        assert "only rectification can" in warnings[0].getMessage()
