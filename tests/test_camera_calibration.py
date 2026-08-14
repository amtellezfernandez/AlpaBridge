from __future__ import annotations

import io
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from alpabridge.driver.camera_calibration import (
    CameraCalibration,
    calibration_from_available_camera,
    calibrations_from_session_request,
)
from alpabridge.driver.driver_service import AlpaBridgeDriverService


def _pinhole_camera(
    logical_id: str = "camera_front_wide_120fov",
    *,
    width: int = 1920,
    height: int = 1080,
) -> SimpleNamespace:
    return SimpleNamespace(
        logical_id=logical_id,
        intrinsics=SimpleNamespace(
            logical_id=logical_id,
            resolution_w=width,
            resolution_h=height,
            opencv_pinhole_param=SimpleNamespace(
                principal_point_x=960.0,
                principal_point_y=540.0,
                focal_length_x=1545.0,
                focal_length_y=1545.0,
            ),
        ),
    )


def _ftheta_camera(logical_id: str = "camera_cross_left_120fov") -> SimpleNamespace:
    return SimpleNamespace(
        logical_id=logical_id,
        intrinsics=SimpleNamespace(
            logical_id=logical_id,
            resolution_w=1920,
            resolution_h=1080,
            ftheta_param=SimpleNamespace(
                principal_point_x=958.0,
                principal_point_y=542.0,
            ),
        ),
    )


def test_pinhole_intrinsics_are_read_from_the_camera_spec() -> None:
    calibration = calibration_from_available_camera(_pinhole_camera())

    assert calibration is not None
    assert calibration.model == "opencv_pinhole"
    assert calibration.width == 1920
    assert calibration.height == 1080
    assert calibration.principal_point_x == 960.0
    assert calibration.focal_length_x == 1545.0


def test_ftheta_intrinsics_are_read_without_a_focal_length() -> None:
    calibration = calibration_from_available_camera(_ftheta_camera())

    assert calibration is not None
    assert calibration.model == "ftheta"
    assert calibration.principal_point_y == 542.0
    assert calibration.focal_length_x is None


def test_scaling_moves_the_pixel_terms_and_leaves_the_rest() -> None:
    calibration = calibration_from_available_camera(_pinhole_camera())
    assert calibration is not None

    # The official set delivers 1916x1080 on some scenes: width scales, height
    # does not, so the two axes must be treated separately.
    scaled = calibration.scaled_to(1916, 1080)

    assert scaled.width == 1916
    assert scaled.height == 1080
    assert scaled.principal_point_x == pytest.approx(960.0 * 1916 / 1920)
    assert scaled.principal_point_y == 540.0
    assert scaled.focal_length_x == pytest.approx(1545.0 * 1916 / 1920)
    assert scaled.focal_length_y == 1545.0
    assert scaled.model == calibration.model


def test_scaling_to_the_declared_size_is_the_same_object() -> None:
    calibration = calibration_from_available_camera(_pinhole_camera())
    assert calibration is not None

    assert calibration.scaled_to(1920, 1080) is calibration


@pytest.mark.parametrize("size", [(0, 1080), (1920, 0), (-1, 100)])
def test_scaling_rejects_an_unusable_target_size(size: tuple[int, int]) -> None:
    calibration = calibration_from_available_camera(_pinhole_camera())
    assert calibration is not None

    with pytest.raises(ValueError):
        calibration.scaled_to(*size)


def test_a_camera_without_a_declared_resolution_is_skipped() -> None:
    camera = _pinhole_camera(width=0, height=0)

    assert calibration_from_available_camera(camera) is None


def test_a_camera_without_a_known_model_is_skipped() -> None:
    camera = SimpleNamespace(
        logical_id="camera_front_tele_30fov",
        intrinsics=SimpleNamespace(
            logical_id="camera_front_tele_30fov",
            resolution_w=1920,
            resolution_h=1080,
        ),
    )

    assert calibration_from_available_camera(camera) is None


def test_session_request_yields_one_calibration_per_usable_camera() -> None:
    request = SimpleNamespace(
        rollout_spec=SimpleNamespace(
            vehicle=SimpleNamespace(
                available_cameras=[
                    _pinhole_camera(),
                    _ftheta_camera(),
                    _pinhole_camera("camera_broken", width=0, height=0),
                ]
            )
        )
    )

    calibrations = calibrations_from_session_request(request)

    assert set(calibrations) == {
        "camera_front_wide_120fov",
        "camera_cross_left_120fov",
    }
    assert isinstance(calibrations["camera_front_wide_120fov"], CameraCalibration)


def test_a_session_without_a_rollout_spec_yields_nothing() -> None:
    assert calibrations_from_session_request(SimpleNamespace()) == {}


def _jpeg_bytes(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(np.zeros((height, width, 3), dtype=np.uint8)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_the_policy_receives_intrinsics_scaled_to_the_delivered_frame() -> None:
    """The declared resolution is the native camera's, not what arrives."""
    camera_id = "camera_front_wide_120fov"
    adapter = AlpaBridgeDriverService(model_name="route_following", camera_ids=(camera_id,))
    adapter.start_session(
        SimpleNamespace(
            session_uuid="session-calib",
            random_seed=1,
            rollout_spec=SimpleNamespace(
                vehicle=SimpleNamespace(available_cameras=[_pinhole_camera(camera_id)])
            ),
        )
    )
    adapter.submit_image_observation(
        SimpleNamespace(
            session_uuid="session-calib",
            camera_image=SimpleNamespace(
                logical_id=camera_id,
                frame_end_us=1_000_000,
                image_bytes=_jpeg_bytes(1916, 1080),
            ),
        )
    )

    calibrations = adapter.prediction_input(
        "session-calib", time_now_us=1_000_000
    ).camera_calibrations

    assert set(calibrations) == {camera_id}
    scaled = calibrations[camera_id]
    assert (scaled.width, scaled.height) == (1916, 1080)
    assert scaled.principal_point_x == pytest.approx(960.0 * 1916 / 1920)
    assert scaled.focal_length_x == pytest.approx(1545.0 * 1916 / 1920)


def test_calibration_survives_a_frame_that_cannot_be_decoded() -> None:
    """A fallback frame has no dimensions, so the declared ones stand."""
    camera_id = "camera_front_wide_120fov"
    adapter = AlpaBridgeDriverService(model_name="route_following", camera_ids=(camera_id,))
    adapter.start_session(
        SimpleNamespace(
            session_uuid="session-undecodable",
            random_seed=1,
            rollout_spec=SimpleNamespace(
                vehicle=SimpleNamespace(available_cameras=[_pinhole_camera(camera_id)])
            ),
        )
    )
    adapter.submit_image_observation(
        SimpleNamespace(
            session_uuid="session-undecodable",
            camera_image=SimpleNamespace(
                logical_id=camera_id, frame_end_us=1_000_000, image_bytes=b"\x80"
            ),
        )
    )

    calibrations = adapter.prediction_input(
        "session-undecodable", time_now_us=1_000_000
    ).camera_calibrations

    assert (calibrations[camera_id].width, calibrations[camera_id].height) == (
        1920,
        1080,
    )


def test_a_session_without_a_rig_still_serves() -> None:
    adapter = AlpaBridgeDriverService(model_name="route_following", camera_ids=("front",))
    adapter.start_session(SimpleNamespace(session_uuid="session-bare", random_seed=1))

    assert adapter.prediction_input("session-bare", time_now_us=1).camera_calibrations == {}
