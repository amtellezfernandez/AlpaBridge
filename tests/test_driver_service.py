from __future__ import annotations

import json
import math
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from alpabridge.driver.driver_service import (
    DRIVER_TELEMETRY_SCHEMA,
    AlpaBridgeDriverService,
    ModelLoadError,
    prediction_to_proto_trajectory,
    run_self_test,
)
from alpabridge.simulator.alpasim_contract import (
    DriveCommand,
    make_model_prediction,
    prediction_trajectory_xy,
)


class _Repeated(list):
    def append(self, value=None, **kwargs):  # type: ignore[override]
        if value is None and kwargs:
            value = SimpleNamespace(**kwargs)
        super().append(value)


class _FakeCommonPb2:
    class Vec3(SimpleNamespace):
        pass

    class Quat(SimpleNamespace):
        pass

    class Pose(SimpleNamespace):
        pass

    class PoseAtTime(SimpleNamespace):
        pass

    class Trajectory:
        def __init__(self) -> None:
            self.poses = _Repeated()


def _pose_at(timestamp_us: int, *, x: float, y: float, yaw: float = 0.0) -> SimpleNamespace:
    half = yaw * 0.5
    return SimpleNamespace(
        timestamp_us=timestamp_us,
        pose=SimpleNamespace(
            vec=SimpleNamespace(x=x, y=y, z=0.0),
            quat=SimpleNamespace(w=math.cos(half), x=0.0, y=0.0, z=math.sin(half)),
        ),
    )


def test_driver_service_preserves_route_geometry_for_route_following() -> None:
    adapter = AlpaBridgeDriverService(model_name="route_following", camera_ids=("front",))
    adapter.start_session(SimpleNamespace(session_uuid="session-a", random_seed=7))
    adapter.submit_image_observation(
        SimpleNamespace(
            session_uuid="session-a",
            camera_image=SimpleNamespace(logical_id="front", frame_end_us=1_000_000, image_bytes=b"\x80"),
        )
    )
    adapter.submit_egomotion_observation(
        SimpleNamespace(
            session_uuid="session-a",
            trajectory=SimpleNamespace(
                poses=[
                    _pose_at(900_000, x=0.0, y=0.0),
                    _pose_at(1_000_000, x=0.5, y=0.0),
                ]
            ),
            dynamic_states=[],
        )
    )
    adapter.submit_route(
        SimpleNamespace(
            session_uuid="session-a",
            route=SimpleNamespace(
                waypoints=[
                    SimpleNamespace(x=0.0, y=0.0, z=0.0),
                    SimpleNamespace(x=20.0, y=15.0, z=0.0),
                    SimpleNamespace(x=45.0, y=15.0, z=0.0),
                ]
            ),
        )
    )

    prediction_input = adapter.prediction_input("session-a", time_now_us=1_000_000)
    prediction = adapter.predict("session-a", time_now_us=1_000_000)

    assert prediction_input.route_waypoints[1]["y"] == 15.0
    assert prediction_trajectory_xy(prediction).shape == (50, 2)
    assert float(prediction_trajectory_xy(prediction)[-1, 1]) > 10.0


def test_driver_service_applies_command_only_route_at_shared_boundary() -> None:
    adapter = AlpaBridgeDriverService(
        model_name="route_following",
        camera_ids=("front",),
        route_contract_mode="command_only_route",
    )
    adapter.start_session(SimpleNamespace(session_uuid="session-command", random_seed=9))
    adapter.submit_image_observation(
        SimpleNamespace(
            session_uuid="session-command",
            camera_image=SimpleNamespace(
                logical_id="front",
                frame_end_us=1_000_000,
                image_bytes=b"\x80",
            ),
        )
    )
    adapter.submit_route(
        SimpleNamespace(
            session_uuid="session-command",
            route=SimpleNamespace(
                waypoints=[
                    SimpleNamespace(x=0.0, y=0.0, z=0.0),
                    SimpleNamespace(x=20.0, y=15.0, z=0.0),
                    SimpleNamespace(x=45.0, y=15.0, z=0.0),
                ]
            ),
        )
    )

    prediction_input = adapter.prediction_input(
        "session-command",
        time_now_us=1_000_000,
    )

    assert prediction_input.route_waypoints == []
    assert prediction_input.command == DriveCommand.LEFT


def test_driver_service_maps_external_camera_id_to_internal_contract_key() -> None:
    adapter = AlpaBridgeDriverService(model_name="constant_velocity")
    adapter.start_session(SimpleNamespace(session_uuid="session-cam", random_seed=3))
    adapter.submit_image_observation(
        SimpleNamespace(
            session_uuid="session-cam",
            camera_image=SimpleNamespace(logical_id="CAM_F0", frame_end_us=2_000_000, image_bytes=b"\x20"),
        )
    )

    prediction_input = adapter.prediction_input("session-cam", time_now_us=2_000_000)
    prediction = adapter.predict("session-cam", time_now_us=2_000_000)

    assert sorted(prediction_input.camera_images) == ["front"]
    assert prediction_input.camera_images["front"][0].timestamp_us == 2_000_000
    assert prediction_trajectory_xy(prediction).shape == (50, 2)


def test_driver_service_writes_drive_telemetry() -> None:
    with TemporaryDirectory() as tmp:
        telemetry_path = Path(tmp) / "telemetry.jsonl"
        adapter = AlpaBridgeDriverService(
            model_name="route_following",
            camera_ids=("CAM_F0",),
            telemetry_path=telemetry_path,
        )
        adapter.start_session(SimpleNamespace(session_uuid="session-telemetry", random_seed=11))
        adapter.submit_image_observation(
            SimpleNamespace(
                session_uuid="session-telemetry",
                camera_image=SimpleNamespace(logical_id="CAM_F0", frame_end_us=1_000_000, image_bytes=b"\x80"),
            )
        )
        adapter.submit_route(
            SimpleNamespace(
                session_uuid="session-telemetry",
                route=SimpleNamespace(
                    waypoints=[
                        SimpleNamespace(x=0.0, y=0.0, z=0.0),
                        SimpleNamespace(x=40.0, y=4.0, z=0.0),
                    ]
                ),
            )
        )

        trajectory = adapter.drive_once_to_proto(
            "session-telemetry",
            time_now_us=1_000_000,
            common_pb2=_FakeCommonPb2,
        )
        rows = [
            json.loads(line)
            for line in telemetry_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        summary = adapter.telemetry_summary()

    drive_rows = [row for row in rows if row["event"] == "drive"]
    assert len(trajectory.poses) == 51
    assert len(drive_rows) == 1
    assert drive_rows[0]["schema"] == DRIVER_TELEMETRY_SCHEMA
    assert drive_rows[0]["route_source"] == "alpasim_waypoints"
    assert drive_rows[0]["latency_target_ms"] == 100.0
    assert drive_rows[0]["speed_mps"] == pytest.approx(5.0)
    assert drive_rows[0]["trajectory_points"] == 51
    assert drive_rows[0]["trajectory_future_points"] == 50
    assert drive_rows[0]["trajectory_expected_future_points"] == 50
    assert drive_rows[0]["trajectory_includes_current_pose"] is True
    assert drive_rows[0]["trajectory_finite"] is True
    assert summary["drive_count"] == 1
    assert summary["latency_ms"]["p95"] is not None


def test_driver_service_uses_pose_speed_when_recorded_dynamic_speed_is_zero() -> None:
    adapter = AlpaBridgeDriverService(
        model_name="constant_velocity",
        camera_ids=("CAM_F0",),
    )
    adapter.start_session(SimpleNamespace(session_uuid="session-speed", random_seed=13))
    adapter.submit_image_observation(
        SimpleNamespace(
            session_uuid="session-speed",
            camera_image=SimpleNamespace(
                logical_id="CAM_F0",
                frame_end_us=1_000_000,
                image_bytes=b"\x80",
            ),
        )
    )
    adapter.submit_egomotion_observation(
        SimpleNamespace(
            session_uuid="session-speed",
            trajectory=SimpleNamespace(
                poses=[
                    _pose_at(900_000, x=0.0, y=0.0),
                    _pose_at(1_000_000, x=1.0, y=0.0),
                ]
            ),
            dynamic_states=[
                SimpleNamespace(linear_velocity=SimpleNamespace(x=0.0, y=0.0))
            ],
        )
    )

    prediction_input = adapter.prediction_input("session-speed", time_now_us=1_000_000)
    prediction = adapter.predict("session-speed", time_now_us=1_000_000)

    assert prediction_input.speed == pytest.approx(10.0)
    assert float(prediction_trajectory_xy(prediction)[-1, 0]) == pytest.approx(50.0)


@pytest.mark.parametrize(
    "model_name",
    ("token_dagger_bc", "navsim_ego_status_mlp", "vavam"),
)
def test_learned_policy_driver_service_requires_checkpoint(model_name: str) -> None:
    with pytest.raises(ValueError, match="requires a checkpoint"):
        AlpaBridgeDriverService(model_name=model_name)


def test_vavam_driver_service_requires_tokenizer_checkpoint(tmp_path: Path) -> None:
    checkpoint = tmp_path / "vavam.pt"
    checkpoint.write_bytes(b"placeholder")

    with pytest.raises(ValueError, match="requires a tokenizer checkpoint"):
        AlpaBridgeDriverService(model_name="vavam", checkpoint_path=checkpoint)


def test_vavam_driver_service_dispatches_to_vavam_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asserts dispatch directly, by substituting VAVAMAlpaSimModel and checking what it
    was constructed with.

    This used to assert `pytest.raises(ImportError, match="requires torch")` -- using the
    model's own optional-dependency guard as a proxy for "dispatch reached the model". The
    proxy only holds when torch is absent, which is true in CI and false for anyone who has
    run ./scripts/bootstrap_alpasim_env.sh (it installs torch into this repo's venv). With
    torch present, dispatch still happens correctly and the test failed anyway, on a later
    `No module named 'vam'` from the real VideoActionModel import. Assert the thing the test
    is named for instead of an error message that happens to accompany it.
    """
    checkpoint = tmp_path / "vavam.pt"
    tokenizer_checkpoint = tmp_path / "vavam_tokenizer.jit"
    checkpoint.write_bytes(b"placeholder")
    tokenizer_checkpoint.write_bytes(b"placeholder")

    constructed: dict[str, Any] = {}

    class _StubVAVAMAlpaSimModel:
        def __init__(self, **kwargs: Any) -> None:
            constructed.update(kwargs)

    import alpabridge.simulator.vavam_model as vavam_module

    monkeypatch.setattr(vavam_module, "VAVAMAlpaSimModel", _StubVAVAMAlpaSimModel)

    AlpaBridgeDriverService(
        model_name="vavam",
        checkpoint_path=checkpoint,
        tokenizer_checkpoint_path=tokenizer_checkpoint,
        device="cpu",
    )

    assert constructed, "vavam policy did not dispatch to VAVAMAlpaSimModel"
    assert Path(constructed["checkpoint_path"]) == checkpoint
    assert Path(constructed["tokenizer_checkpoint_path"]) == tokenizer_checkpoint
    assert constructed["device"] == "cpu"


def test_learned_policy_driver_service_records_pinned_checkpoint_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = tmp_path / "policy.pt"
    checkpoint.write_bytes(b"pinned learned policy checkpoint")
    monkeypatch.setattr(
        AlpaBridgeDriverService,
        "_build_model",
        lambda _self: object(),
    )

    adapter = AlpaBridgeDriverService(
        model_name="token_dagger_bc",
        checkpoint_path=checkpoint,
        device="cpu",
    )

    assert (
        adapter.checkpoint_sha256
        == "d6c9c340aea7e04bc485aad78a301182aacc2a8dce0f09a210fa042375c54cca"
    )
    assert adapter.device == "cpu"


def test_driver_self_test_reports_non_benchmark_latency_summary() -> None:
    summary = run_self_test(model_name="route_following", iterations=3)

    assert summary["benchmark_result"] is False
    assert summary["drive_count"] == 3
    assert summary["latency_ms"]["p95"] is not None
    assert summary["route_sources"] == ["alpasim_waypoints"]


def test_driver_service_rejects_unknown_session() -> None:
    adapter = AlpaBridgeDriverService(model_name="constant_velocity", camera_ids=("front",))

    try:
        adapter.predict("missing-session", time_now_us=0)
    except KeyError as exc:
        assert "unknown session" in str(exc)
    else:  # pragma: no cover - failure path
        raise AssertionError("missing session unexpectedly predicted")


def test_close_session_forgets_the_models_inference_cache_if_it_has_one() -> None:
    adapter = AlpaBridgeDriverService(model_name="constant_velocity", camera_ids=("front",))
    forgotten = []
    adapter._model = SimpleNamespace(
        _inference_cache=SimpleNamespace(forget=lambda session_uuid: forgotten.append(session_uuid))
    )

    adapter.close_session("some-session")

    assert forgotten == ["some-session"]


def test_close_session_is_safe_for_models_without_an_inference_cache() -> None:
    adapter = AlpaBridgeDriverService(model_name="constant_velocity", camera_ids=("front",))

    adapter.close_session("some-session")  # constant_velocity has no _inference_cache - must not raise


def test_driver_service_selects_freshest_accepted_camera_alias() -> None:
    adapter = AlpaBridgeDriverService(
        model_name="constant_velocity",
        camera_ids=("CAM_F0", "camera_front_wide_120fov"),
    )
    adapter.start_session(SimpleNamespace(session_uuid="session-alias", random_seed=5))
    for camera_id, timestamp_us, image_byte in (
        ("CAM_F0", 1_000_000, b"\x10"),
        ("camera_front_wide_120fov", 1_100_000, b"\x20"),
    ):
        adapter.submit_image_observation(
            SimpleNamespace(
                session_uuid="session-alias",
                camera_image=SimpleNamespace(
                    logical_id=camera_id,
                    frame_end_us=timestamp_us,
                    image_bytes=image_byte,
                ),
            )
        )

    prediction_input = adapter.prediction_input(
        "session-alias",
        time_now_us=1_100_000,
    )

    assert prediction_input.camera_images["front"][0].timestamp_us == 1_100_000


def test_prediction_to_proto_trajectory_rotates_ego_relative_offsets() -> None:
    prediction = make_model_prediction(
        trajectory_xy=np.asarray([[1.0, 0.0], [2.0, 0.0]], dtype=np.float32),
        headings=np.asarray([0.0, 0.0], dtype=np.float32),
    )
    trajectory = prediction_to_proto_trajectory(
        prediction,
        current_pose=_pose_at(10_000, x=10.0, y=20.0, yaw=math.pi / 2.0),
        time_now_us=10_000,
        common_pb2=_FakeCommonPb2,
        horizon_seconds=1.0,
    )

    assert [pose.timestamp_us for pose in trajectory.poses] == [
        10_000,
        510_000,
        1_010_000,
    ]
    np.testing.assert_allclose(
        [[pose.pose.vec.x, pose.pose.vec.y] for pose in trajectory.poses],
        [[10.0, 20.0], [10.0, 21.0], [10.0, 22.0]],
        atol=1e-6,
    )


@pytest.mark.parametrize(
    ("trajectory", "headings", "message"),
    (
        (np.empty((0, 2)), np.empty((0,)), "at least one point"),
        (np.asarray([[1.0, 0.0], [2.0, 0.0]]), np.asarray([0.0]), "one value"),
        (np.asarray([[np.nan, 0.0]]), np.asarray([0.0]), "finite"),
        (np.asarray([[1.0, 0.0]]), np.asarray([np.inf]), "finite"),
    ),
)
def test_prediction_to_proto_trajectory_rejects_invalid_outputs(
    trajectory: np.ndarray,
    headings: np.ndarray,
    message: str,
) -> None:
    # Construction is inside the raises block on purpose: some of these are now caught
    # when the prediction is built (empty path, heading/point count mismatch) rather than
    # at conversion. What matters is that the pipeline rejects them with the same message,
    # not which half of it holds the guard.
    with pytest.raises(ValueError, match=message):
        prediction_to_proto_trajectory(
            make_model_prediction(trajectory_xy=trajectory, headings=headings),
            current_pose=None,
            time_now_us=10_000,
            common_pb2=_FakeCommonPb2,
        )


def test_prediction_to_proto_trajectory_rejects_nonfinite_world_pose() -> None:
    prediction = make_model_prediction(
        trajectory_xy=np.asarray([[1.0, 0.0]], dtype=np.float64),
        headings=np.asarray([0.0], dtype=np.float64),
    )

    with pytest.raises(ValueError, match="current pose"):
        prediction_to_proto_trajectory(
            prediction,
            current_pose=_pose_at(10_000, x=np.nan, y=0.0, yaw=0.0),
            time_now_us=10_000,
            common_pb2=_FakeCommonPb2,
        )


def test_prediction_to_proto_trajectory_rejects_nonfinite_transformed_output() -> None:
    prediction = make_model_prediction(
        trajectory_xy=np.asarray(
            [
                [np.finfo(np.float64).max, 0.0],
                [np.finfo(np.float64).max, 0.0],
            ],
            dtype=np.float64,
        ),
        headings=np.asarray([0.0, 0.0], dtype=np.float64),
    )

    with pytest.raises(ValueError, match="serialized trajectory"):
        prediction_to_proto_trajectory(
            prediction,
            current_pose=_pose_at(
                10_000,
                x=np.finfo(np.float64).max,
                y=0.0,
                yaw=0.0,
            ),
            time_now_us=10_000,
            common_pb2=_FakeCommonPb2,
        )


class TestDeferredModelLoad:
    """The evaluator gates on get_version answering within its readiness window
    while several replicas cold-start on one GPU, so a slow policy load must not
    hold the gRPC port. What must never happen is a driver that quietly serves
    something other than the policy it claims."""

    def test_eager_construction_is_unchanged(self) -> None:
        service = AlpaBridgeDriverService(model_name="route_following")

        assert service.wait_for_model(0) is True
        assert service._require_model() is not None

    def test_deferred_construction_returns_before_the_policy_is_ready(self) -> None:
        release = threading.Event()
        built = threading.Event()

        class SlowService(AlpaBridgeDriverService):
            def _build_model(self) -> Any:
                release.wait(5)
                built.set()
                return SimpleNamespace(name="slow-policy")

        service = SlowService(model_name="route_following", defer_model_load=True)
        try:
            # The constructor must not have waited on the load.
            assert service.wait_for_model(0) is False
            assert built.is_set() is False
        finally:
            release.set()

        assert service.wait_for_model(5) is True
        assert service._require_model().name == "slow-policy"

    def test_a_still_loading_policy_raises_rather_than_substituting_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPABRIDGE_DRIVER_MODEL_LOAD_TIMEOUT_S", "0.05")
        service = AlpaBridgeDriverService.__new__(AlpaBridgeDriverService)
        service.model_name = "slow"
        service._model = None
        service._model_error = None
        service._model_ready = threading.Event()

        with pytest.raises(TimeoutError, match="still loading"):
            service._require_model()

    def test_a_failed_load_surfaces_the_original_error(self) -> None:
        service = AlpaBridgeDriverService.__new__(AlpaBridgeDriverService)
        service.model_name = "broken"
        service._model = None
        service._model_error = ValueError("checkpoint missing")
        service._model_ready = threading.Event()
        service._model_ready.set()

        with pytest.raises(ModelLoadError, match="checkpoint missing") as excinfo:
            service._require_model()

        # Distinct from a RuntimeError raised by a working policy, so the gRPC
        # layer can report it as FAILED_PRECONDITION rather than a bad request.
        assert isinstance(excinfo.value, RuntimeError)
        assert isinstance(excinfo.value.__cause__, ValueError)

    def test_a_background_load_failure_still_releases_waiters(self) -> None:
        class BrokenService(AlpaBridgeDriverService):
            def _build_model(self) -> Any:
                raise ValueError("checkpoint missing")

        service = BrokenService(model_name="route_following", defer_model_load=True)

        assert service.wait_for_model(5) is True, "waiters must not hang on failure"
        with pytest.raises(ModelLoadError):
            service._require_model()


class TestWarmupReferenceSpeed:
    """The evaluator drives the ego along the recorded human trajectory for the
    first ~1.7 s while still calling drive(), so the session's opening speeds
    are the human's own pace for the scene. The reference must be per-session:
    the evaluator runs two concurrent rollouts per replica against one adapter."""

    def _egomotion(
        self, service: AlpaBridgeDriverService, uuid: str, t_us: int, x: float
    ) -> None:
        pose = SimpleNamespace(
            timestamp_us=t_us,
            pose=SimpleNamespace(
                vec=SimpleNamespace(x=x, y=0.0, z=0.0),
                quat=SimpleNamespace(w=1.0, x=0.0, y=0.0, z=0.0),
            ),
        )
        request = SimpleNamespace(
            session_uuid=uuid,
            trajectory=SimpleNamespace(poses=[pose]),
            dynamic_states=[],
        )
        service.submit_egomotion_observation(request)

    def test_reference_is_the_max_of_the_warmup_window(self) -> None:
        service = AlpaBridgeDriverService(model_name="route_following")
        service.start_session(SimpleNamespace(session_uuid="s1", random_seed=0))
        # Accelerating human: 2 m/s then 4 m/s between consecutive 100 ms poses.
        self._egomotion(service, "s1", 1_000_000, 0.0)
        self._egomotion(service, "s1", 1_100_000, 0.2)
        first = service.prediction_input("s1", time_now_us=1_100_000)
        self._egomotion(service, "s1", 1_200_000, 0.6)
        second = service.prediction_input("s1", time_now_us=1_200_000)

        assert first.reference_speed_mps == pytest.approx(2.0, abs=0.2)
        assert second.reference_speed_mps == pytest.approx(4.0, abs=0.2)

    def test_reference_is_isolated_between_sessions(self) -> None:
        service = AlpaBridgeDriverService(model_name="route_following")
        service.start_session(SimpleNamespace(session_uuid="fast", random_seed=0))
        service.start_session(SimpleNamespace(session_uuid="slow", random_seed=0))
        self._egomotion(service, "fast", 1_000_000, 0.0)
        self._egomotion(service, "fast", 1_100_000, 1.0)  # 10 m/s
        self._egomotion(service, "slow", 1_000_000, 0.0)
        self._egomotion(service, "slow", 1_100_000, 0.1)  # 1 m/s

        fast = service.prediction_input("fast", time_now_us=1_100_000)
        slow = service.prediction_input("slow", time_now_us=1_100_000)

        assert fast.reference_speed_mps == pytest.approx(10.0, abs=0.5)
        assert slow.reference_speed_mps == pytest.approx(1.0, abs=0.2)
