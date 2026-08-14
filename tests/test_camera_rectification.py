from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from alpabridge.simulator import camera_rectification as rect
from alpabridge.simulator import vavam_model
from alpabridge.simulator.vavam_model import VAVAMAlpaSimModel


@pytest.fixture(autouse=True)
def _forget_warnings() -> None:
    rect._WARNED.clear()
    vavam_model._CENTRE_WARNINGS.clear()


def _frame(height: int = 4, width: int = 6) -> np.ndarray:
    return np.zeros((height, width, 3), dtype=np.uint8)


@pytest.mark.parametrize("raw", ["1", "true", "YES"])
def test_rectification_can_be_turned_off(raw: str) -> None:
    with patch.dict("os.environ", {"ALPABRIDGE_DISABLE_RECTIFICATION": raw}, clear=False):
        assert rect.rectification_disabled() is True


@pytest.mark.parametrize("raw", ["0", "", "no", "off"])
def test_rectification_is_on_by_default(raw: str) -> None:
    with patch.dict("os.environ", {"ALPABRIDGE_DISABLE_RECTIFICATION": raw}, clear=False):
        assert rect.rectification_disabled() is False


def test_a_missing_camera_yields_no_rectifier() -> None:
    assert rect.build_rectifier(None, (1080, 1920)) is None


def test_an_unavailable_transform_says_so_once_and_yields_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """alpasim_grpc and cv2 are optional, so this is the common local case."""
    with patch.object(rect, "default_target_config", side_effect=[None, None]) as target:
        with caplog.at_level("WARNING"):
            first = rect.build_rectifier(object(), (1080, 1920))
            second = rect.build_rectifier(object(), (1080, 1920))

    assert first is None and second is None
    assert target.call_count == 2


def _fake_transform_module(monkeypatch: pytest.MonkeyPatch, builder) -> None:
    """Stand in for the vendored transform.

    It imports cv2 and alpasim_grpc, neither of which CI installs, so the real
    module cannot be imported here - which is itself the point: this exercises
    the wrapper, not NVIDIA's transform.
    """
    import sys
    import types

    module = types.ModuleType("alpabridge.third_party.alpasim_rectification")
    module.RectificationTargetConfig = lambda **kwargs: SimpleNamespace(**kwargs)
    module.build_ftheta_rectifier_for_resolution = builder
    monkeypatch.setitem(sys.modules, "alpabridge.third_party.alpasim_rectification", module)


def test_the_target_matches_the_reference_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_transform_module(monkeypatch, lambda *args, **kwargs: None)

    target = rect.default_target_config()

    assert target.focal_length == (1545.0, 1545.0)
    assert target.principal_point == (960.0, 560.0)
    assert target.resolution_hw == (1080, 1920)


def test_a_transform_that_cannot_be_built_falls_back_and_warns_once(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("no polynomial")

    _fake_transform_module(monkeypatch, _boom)

    with caplog.at_level("WARNING"):
        assert rect.build_rectifier(object(), (1080, 1920)) is None
        assert rect.build_rectifier(object(), (1080, 1920)) is None

    warnings = [r for r in caplog.records if "unrectified" in r.getMessage()]
    assert len(warnings) == 1


def test_a_buildable_transform_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    _fake_transform_module(monkeypatch, lambda *args, **kwargs: sentinel)

    assert rect.build_rectifier(object(), (1080, 1920)) is sentinel


def test_no_rectifier_returns_the_frame_untouched() -> None:
    image = _frame()

    assert rect.rectify_image(None, image) is image


def test_a_working_rectifier_output_is_what_comes_back() -> None:
    image = _frame()
    rectified = _frame(8, 8)
    rectifier = SimpleNamespace(rectify=lambda _: rectified)

    assert np.array_equal(rect.rectify_image(rectifier, image), rectified)


def test_a_failing_rectifier_returns_the_original_and_warns_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    image = _frame()

    def _boom(_: np.ndarray) -> np.ndarray:
        raise ValueError("bad remap")

    rectifier = SimpleNamespace(rectify=_boom)
    with caplog.at_level("WARNING"):
        first = rect.rectify_image(rectifier, image)
        second = rect.rectify_image(rectifier, image)

    assert first is image and second is image
    warnings = [r for r in caplog.records if "as rendered" in r.getMessage()]
    assert len(warnings) == 1


def _model_with(camera_id: str = "front") -> VAVAMAlpaSimModel:
    """A VAVAM adapter without its weights: only the frame path is under test."""
    model = object.__new__(VAVAMAlpaSimModel)
    model._camera_ids = [camera_id]
    model._rectifiers = {}
    return model


def _prediction_input(source_camera_id: str = "camera_front_wide_120fov") -> SimpleNamespace:
    frame = SimpleNamespace(image=None, source_camera_id=source_camera_id)
    return SimpleNamespace(
        camera_images={"front": [frame]},
        camera_protos={source_camera_id: object()},
    )


def test_the_rectified_frame_is_what_reaches_inference() -> None:
    model = _model_with()
    prediction_input = _prediction_input()
    image = _frame(1080, 1920)
    rectified = _frame(1080, 1920)
    rectified[0, 0, 0] = 7

    with patch.object(vavam_model, "build_rectifier") as build:
        build.return_value = SimpleNamespace(rectify=lambda _: rectified)
        out = model._rectified(prediction_input, image)

    assert int(out[0, 0, 0]) == 7


def test_a_rectifier_is_built_once_per_camera_and_size() -> None:
    model = _model_with()
    prediction_input = _prediction_input()
    image = _frame(1080, 1920)

    with patch.object(vavam_model, "build_rectifier") as build:
        build.return_value = None
        for _ in range(3):
            model._rectified(prediction_input, image)
        model._rectified(prediction_input, _frame(1080, 1916))

    # Three identical frames share one rectifier; a new size needs its own.
    assert build.call_count == 2


def test_opting_out_skips_the_transform_entirely() -> None:
    model = _model_with()
    prediction_input = _prediction_input()
    image = _frame(1080, 1920)

    with patch.dict("os.environ", {"ALPABRIDGE_DISABLE_RECTIFICATION": "1"}, clear=False):
        with patch.object(vavam_model, "build_rectifier") as build:
            out = model._rectified(prediction_input, image)

    assert out is image
    build.assert_not_called()


def test_a_frame_with_no_source_camera_is_left_alone() -> None:
    model = _model_with()
    prediction_input = _prediction_input(source_camera_id="")

    image = _frame(1080, 1920)
    assert model._rectified(prediction_input, image) is image


def test_an_undecodable_frame_is_left_alone() -> None:
    model = _model_with()
    prediction_input = _prediction_input()

    image = np.zeros((1,), dtype=np.uint8)
    assert model._rectified(prediction_input, image) is image


def _calibrated_input(offset_y: float, source_camera_id: str) -> SimpleNamespace:
    frame = SimpleNamespace(image=None, source_camera_id=source_camera_id)
    return SimpleNamespace(
        camera_images={"front": [frame]},
        camera_protos={source_camera_id: object()},
        camera_calibrations={
            source_camera_id: SimpleNamespace(
                principal_point_x=960.0,
                principal_point_y=540.0 + offset_y,
                width=1920,
                height=1080,
            )
        },
    )


def test_an_unrectified_frame_with_an_off_centre_axis_warns_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The opt-out is a footgun on such a camera, so it must not be silent."""
    model = _model_with()
    prediction_input = _calibrated_input(200.0, "camera_off_centre")
    image = _frame(1080, 1920)

    with patch.dict("os.environ", {"ALPABRIDGE_DISABLE_RECTIFICATION": "1"}, clear=False):
        with caplog.at_level("WARNING"):
            model._rectified(prediction_input, image)
            model._rectified(prediction_input, image)

    warnings = [r for r in caplog.records if "unrectified" in r.getMessage()]
    assert len(warnings) == 1


def test_a_centred_camera_does_not_warn_when_unrectified(
    caplog: pytest.LogCaptureFixture,
) -> None:
    model = _model_with()
    prediction_input = _calibrated_input(0.0, "camera_centred")
    image = _frame(1080, 1920)

    with patch.dict("os.environ", {"ALPABRIDGE_DISABLE_RECTIFICATION": "1"}, clear=False):
        with caplog.at_level("WARNING"):
            model._rectified(prediction_input, image)

    assert [r for r in caplog.records if "unrectified" in r.getMessage()] == []


def test_a_rectified_frame_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    model = _model_with()
    prediction_input = _calibrated_input(200.0, "camera_off_centre_rectified")
    image = _frame(1080, 1920)

    with patch.object(vavam_model, "build_rectifier") as build:
        build.return_value = SimpleNamespace(rectify=lambda _: _frame(900, 1600))
        with caplog.at_level("WARNING"):
            model._rectified(prediction_input, image)

    assert [r for r in caplog.records if "unrectified" in r.getMessage()] == []
