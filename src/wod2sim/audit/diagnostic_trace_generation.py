from __future__ import annotations

import hashlib
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from wod2sim.challenge.e2e_driver import WOD2SimChallengeAdapter

DEFAULT_PROTOCOL_SESSION_COUNT = 15


class _Repeated(list[Any]):
    def append(self, value: Any = None, **kwargs: Any) -> None:  # type: ignore[override]
        super().append(SimpleNamespace(**kwargs) if value is None and kwargs else value)


class _CommonProto:
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
            self.poses: _Repeated = _Repeated()


def generate_protocol_trace(
    path: Path,
    *,
    session_count: int = DEFAULT_PROTOCOL_SESSION_COUNT,
) -> dict[str, Any]:
    if session_count < 1:
        raise ValueError("session_count must be positive")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    adapter = WOD2SimChallengeAdapter(
        model_name="route_following",
        camera_ids=("CAM_F0", "camera_front_wide_120fov"),
        telemetry_path=path,
    )

    for session_index in range(session_count):
        session_uuid = f"diagnostic-session-{session_index + 1:02d}"
        adapter.start_session(
            SimpleNamespace(
                session_uuid=session_uuid,
                random_seed=2027 + session_index,
                debug_info=SimpleNamespace(scene_id=f"protocol-fixture-{session_index + 1:02d}"),
            )
        )
        adapter.submit_route(
            SimpleNamespace(
                session_uuid=session_uuid,
                route=SimpleNamespace(
                    waypoints=_route_waypoints(session_index),
                ),
            )
        )
        for step in range(session_index + 1):
            timestamp_us = 1_000_000 + session_index * 20_000_000 + step * 200_000
            speed_mps = 2.0 + (session_index % 8)
            current_x = (step + 1) * speed_mps * 0.2
            camera_id = "CAM_F0" if (session_index + step) % 2 == 0 else "camera_front_wide_120fov"
            adapter.submit_image_observation(
                SimpleNamespace(
                    session_uuid=session_uuid,
                    camera_image=SimpleNamespace(
                        logical_id=camera_id,
                        frame_end_us=timestamp_us,
                        image_bytes=bytes(((session_index * 17 + step) % 251 + 1,)),
                    ),
                )
            )
            adapter.submit_egomotion_observation(
                SimpleNamespace(
                    session_uuid=session_uuid,
                    trajectory=SimpleNamespace(
                        poses=[
                            _pose(
                                timestamp_us - 100_000,
                                x=current_x - speed_mps * 0.1,
                                y=0.0,
                            ),
                            _pose(timestamp_us, x=current_x, y=0.0),
                        ]
                    ),
                    dynamic_states=[],
                )
            )
            adapter.drive_once_to_proto(
                session_uuid,
                time_now_us=timestamp_us + (session_index % 5) * 25_000,
                common_pb2=_CommonProto,
            )
        adapter.close_session(session_uuid)

    summary = adapter.telemetry_summary()
    summary.update(
        {
            "path": path.as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "session_count": session_count,
            "generation": (
                "Dependency-light current-instrumentation sessions emitted through "
                "WOD2SimChallengeAdapter; not external simulator rollouts."
            ),
        }
    )
    return summary


def _route_waypoints(session_index: int) -> list[SimpleNamespace]:
    lateral = float((session_index % 3) - 1) * 4.0
    count = 3 + session_index % 3
    return [
        SimpleNamespace(
            x=float(point_index * 25),
            y=lateral * point_index / max(1, count - 1),
            z=0.0,
        )
        for point_index in range(count)
    ]


def _pose(timestamp_us: int, *, x: float, y: float, yaw: float = 0.0) -> SimpleNamespace:
    half = yaw * 0.5
    return SimpleNamespace(
        timestamp_us=timestamp_us,
        pose=SimpleNamespace(
            vec=SimpleNamespace(x=x, y=y, z=0.0),
            quat=SimpleNamespace(w=math.cos(half), x=0.0, y=0.0, z=math.sin(half)),
        ),
    )
