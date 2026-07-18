from __future__ import annotations

import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import numpy as np

from wod2sim.challenge.e2e_driver import (
    WOD2SimChallengeAdapter,
    prediction_to_proto_trajectory,
    run_self_test,
)
from wod2sim.simulator.alpasim_contract import ModelPrediction


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


def test_challenge_adapter_preserves_route_geometry_for_route_following() -> None:
    adapter = WOD2SimChallengeAdapter(model_name="route_following", camera_ids=("front",))
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
    assert prediction.trajectory_xy.shape == (50, 2)
    assert float(prediction.trajectory_xy[-1, 1]) > 10.0


def test_challenge_adapter_maps_challenge_camera_id_to_internal_contract_key() -> None:
    adapter = WOD2SimChallengeAdapter(model_name="constant_velocity")
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
    assert prediction.trajectory_xy.shape == (50, 2)


def test_challenge_adapter_writes_drive_telemetry() -> None:
    with TemporaryDirectory() as tmp:
        telemetry_path = Path(tmp) / "telemetry.jsonl"
        adapter = WOD2SimChallengeAdapter(
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
    assert len(trajectory.poses) == 50
    assert len(drive_rows) == 1
    assert drive_rows[0]["route_source"] == "alpasim_waypoints"
    assert drive_rows[0]["latency_target_ms"] == 100.0
    assert summary["drive_count"] == 1
    assert summary["latency_ms"]["p95"] is not None


def test_challenge_self_test_reports_non_benchmark_latency_summary() -> None:
    summary = run_self_test(model_name="route_following", iterations=3)

    assert summary["benchmark_result"] is False
    assert summary["drive_count"] == 3
    assert summary["latency_ms"]["p95"] is not None
    assert summary["route_sources"] == ["alpasim_waypoints"]


def test_challenge_adapter_rejects_unknown_session() -> None:
    adapter = WOD2SimChallengeAdapter(model_name="constant_velocity", camera_ids=("front",))

    try:
        adapter.predict("missing-session", time_now_us=0)
    except KeyError as exc:
        assert "unknown session" in str(exc)
    else:  # pragma: no cover - failure path
        raise AssertionError("missing session unexpectedly predicted")


def test_prediction_to_proto_trajectory_rotates_ego_relative_offsets() -> None:
    prediction = ModelPrediction(
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

    assert [pose.timestamp_us for pose in trajectory.poses] == [510_000, 1_010_000]
    np.testing.assert_allclose(
        [[pose.pose.vec.x, pose.pose.vec.y] for pose in trajectory.poses],
        [[10.0, 21.0], [10.0, 22.0]],
        atol=1e-6,
    )
