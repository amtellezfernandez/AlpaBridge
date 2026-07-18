from __future__ import annotations

import argparse
import logging
import math
import os
import signal
import threading
from concurrent import futures
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import numpy as np

from wod2sim.simulator.alpasim_contract import DriveCommand, ModelPrediction
from wod2sim.simulator.baseline_drivers import (
    ConstantVelocityAlpaSimModel,
    RouteFollowingAlpaSimModel,
)

LOGGER = logging.getLogger("wod2sim_challenge_driver")


@dataclass
class ChallengeCameraFrame:
    timestamp_us: int
    image: np.ndarray


@dataclass
class ChallengeSessionState:
    session_uuid: str
    random_seed: int = 0
    debug_scene_id: str | None = None
    camera_images: dict[str, list[ChallengeCameraFrame]] = field(default_factory=dict)
    ego_pose_history: list[Any] = field(default_factory=list)
    dynamic_states: list[tuple[int, Any]] = field(default_factory=list)
    route_waypoints: list[dict[str, float]] = field(default_factory=list)
    command: Any = DriveCommand.STRAIGHT


class WOD2SimChallengeAdapter:
    """Reuse WOD2Sim policy contracts behind an AlpaSim E2E-style driver service."""

    def __init__(
        self,
        *,
        model_name: str = "route_following",
        camera_ids: tuple[str, ...] = ("CAM_F0", "camera_front_wide_120fov"),
        output_frequency_hz: int = 10,
        horizon_seconds: float = 5.0,
    ) -> None:
        self.model_name = _normalize_model_name(model_name)
        self.camera_candidates = tuple(camera_ids)
        self.model_camera_id = "front"
        self.output_frequency_hz = int(output_frequency_hz)
        self.horizon_seconds = float(horizon_seconds)
        self._lock = threading.RLock()
        self._sessions: dict[str, ChallengeSessionState] = {}
        self._model = self._build_model()

    def start_session(self, request: Any) -> None:
        session_uuid = str(request.session_uuid)
        debug_info = getattr(request, "debug_info", None)
        debug_scene_id = getattr(debug_info, "scene_id", None) if debug_info is not None else None
        with self._lock:
            self._sessions[session_uuid] = ChallengeSessionState(
                session_uuid=session_uuid,
                random_seed=int(getattr(request, "random_seed", 0) or 0),
                debug_scene_id=str(debug_scene_id) if debug_scene_id else None,
            )

    def close_session(self, session_uuid: str) -> None:
        with self._lock:
            self._sessions.pop(str(session_uuid), None)

    def submit_image_observation(self, request: Any) -> None:
        session = self._session(str(request.session_uuid))
        grpc_image = request.camera_image
        camera_id = str(getattr(grpc_image, "logical_id", "") or self.camera_candidates[0])
        frame = ChallengeCameraFrame(
            timestamp_us=int(getattr(grpc_image, "frame_end_us", 0) or 0),
            image=_image_array_from_bytes(getattr(grpc_image, "image_bytes", b"")),
        )
        with self._lock:
            frames = session.camera_images.setdefault(camera_id, [])
            frames.append(frame)
            del frames[:-1]

    def submit_egomotion_observation(self, request: Any) -> None:
        session = self._session(str(request.session_uuid))
        trajectory = getattr(request, "trajectory", None)
        poses = list(getattr(trajectory, "poses", []) or [])
        dynamic_states = list(getattr(request, "dynamic_states", []) or [])
        with self._lock:
            session.ego_pose_history.extend(poses)
            session.ego_pose_history = session.ego_pose_history[-32:]
            for index, state in enumerate(dynamic_states):
                if index < len(poses):
                    timestamp_us = int(getattr(poses[index], "timestamp_us", 0) or 0)
                    session.dynamic_states.append((timestamp_us, state))
            session.dynamic_states = session.dynamic_states[-32:]

    def submit_route(self, request: Any) -> None:
        session = self._session(str(request.session_uuid))
        route = getattr(request, "route", None)
        waypoints = _route_waypoints_from_proto(route)
        with self._lock:
            session.route_waypoints = waypoints
            session.command = _command_from_waypoints(waypoints)

    def predict(self, session_uuid: str, *, time_now_us: int) -> ModelPrediction:
        prediction_input = self.prediction_input(session_uuid, time_now_us=time_now_us)
        return self._model.predict(prediction_input)

    def prediction_input(self, session_uuid: str, *, time_now_us: int) -> SimpleNamespace:
        session = self._session(session_uuid)
        with self._lock:
            camera_images = {key: list(value) for key, value in session.camera_images.items()}
            if not camera_images:
                camera_images = {
                    self.model_camera_id: [
                        ChallengeCameraFrame(timestamp_us=int(time_now_us), image=np.zeros((1,), dtype=np.uint8))
                    ]
                }
            else:
                camera_images = {self.model_camera_id: _selected_camera_frames(camera_images, self.camera_candidates)}
            route_waypoints = list(session.route_waypoints)
            ego_pose_history = list(session.ego_pose_history)
            dynamic_states = list(session.dynamic_states)
            command = session.command
            random_seed = session.random_seed
            debug_scene_id = session.debug_scene_id

        return SimpleNamespace(
            camera_images=camera_images,
            command=command,
            speed=_estimate_speed_mps(ego_pose_history, dynamic_states),
            acceleration=0.0,
            ego_pose_history=ego_pose_history,
            route_waypoints=route_waypoints,
            structured_hazards=[],
            session_uuid=session_uuid,
            runtime_random_seed=random_seed,
            debug_scene_id=debug_scene_id,
            scene_id=debug_scene_id,
            time_now_us=int(time_now_us),
        )

    def latest_pose(self, session_uuid: str) -> Any | None:
        session = self._session(session_uuid)
        with self._lock:
            return session.ego_pose_history[-1] if session.ego_pose_history else None

    def _build_model(self) -> Any:
        kwargs = {
            "camera_ids": [self.model_camera_id],
            "context_length": 1,
            "output_frequency_hz": self.output_frequency_hz,
            "config": SimpleNamespace(
                horizon_seconds=self.horizon_seconds,
                point_count=int(round(self.output_frequency_hz * self.horizon_seconds)),
            ),
        }
        if self.model_name == "constant_velocity":
            return ConstantVelocityAlpaSimModel(**kwargs)
        if self.model_name == "route_following":
            return RouteFollowingAlpaSimModel(**kwargs)
        raise ValueError(f"Unsupported challenge model: {self.model_name}")

    def _session(self, session_uuid: str) -> ChallengeSessionState:
        with self._lock:
            session = self._sessions.get(str(session_uuid))
        if session is None:
            raise KeyError(f"unknown session {session_uuid}")
        return session


def prediction_to_proto_trajectory(
    prediction: ModelPrediction,
    *,
    current_pose: Any | None,
    time_now_us: int,
    common_pb2: Any,
    horizon_seconds: float = 5.0,
) -> Any:
    trajectory_xy = np.asarray(prediction.trajectory_xy, dtype=np.float64).reshape(-1, 2)
    headings = np.asarray(prediction.headings, dtype=np.float64).reshape(-1)
    origin_x, origin_y, origin_z, yaw0 = _pose_origin_and_yaw(current_pose)
    cos_yaw = math.cos(yaw0)
    sin_yaw = math.sin(yaw0)
    count = max(1, int(trajectory_xy.shape[0]))
    trajectory = common_pb2.Trajectory()
    for index, offset in enumerate(trajectory_xy):
        x_local = origin_x + cos_yaw * float(offset[0]) - sin_yaw * float(offset[1])
        y_local = origin_y + sin_yaw * float(offset[0]) + cos_yaw * float(offset[1])
        heading = yaw0 + (float(headings[index]) if index < headings.shape[0] else 0.0)
        timestamp_us = int(time_now_us) + int(round((index + 1) * horizon_seconds * 1_000_000 / count))
        trajectory.poses.append(
            common_pb2.PoseAtTime(
                timestamp_us=timestamp_us,
                pose=common_pb2.Pose(
                    vec=common_pb2.Vec3(x=x_local, y=y_local, z=origin_z),
                    quat=_quat_from_yaw(heading, common_pb2),
                ),
            )
        )
    return trajectory


def _normalize_model_name(model_name: str) -> str:
    value = model_name.strip().lower().replace("-", "_")
    if value not in {"constant_velocity", "route_following"}:
        raise ValueError("Challenge compatibility currently supports constant_velocity and route_following")
    return value


def _route_waypoints_from_proto(route: Any) -> list[dict[str, float]]:
    waypoints: list[dict[str, float]] = []
    for waypoint in list(getattr(route, "waypoints", []) or []):
        x = float(getattr(waypoint, "x", 0.0) or 0.0)
        y = float(getattr(waypoint, "y", 0.0) or 0.0)
        z = float(getattr(waypoint, "z", 0.0) or 0.0)
        if math.isfinite(x) and math.isfinite(y) and math.isfinite(z):
            waypoints.append({"x": x, "y": y, "z": z})
    return waypoints


def _selected_camera_frames(
    camera_images: dict[str, list[ChallengeCameraFrame]],
    candidates: tuple[str, ...],
) -> list[ChallengeCameraFrame]:
    for camera_id in candidates:
        frames = camera_images.get(camera_id)
        if frames:
            return frames[-1:]
    for frames in camera_images.values():
        if frames:
            return frames[-1:]
    return [ChallengeCameraFrame(timestamp_us=0, image=np.zeros((1,), dtype=np.uint8))]


def _command_from_waypoints(waypoints: list[dict[str, float]]) -> Any:
    candidates = [point for point in waypoints if float(point["x"]) >= 20.0]
    waypoint = candidates[0] if candidates else (waypoints[-1] if waypoints else None)
    if waypoint is None:
        return DriveCommand.STRAIGHT
    if float(waypoint["y"]) > 3.0:
        return DriveCommand.LEFT
    if float(waypoint["y"]) < -3.0:
        return DriveCommand.RIGHT
    return DriveCommand.STRAIGHT


def _estimate_speed_mps(ego_pose_history: list[Any], dynamic_states: list[tuple[int, Any]]) -> float:
    if dynamic_states:
        velocity = getattr(dynamic_states[-1][1], "linear_velocity", None)
        if velocity is not None:
            return float(math.hypot(float(getattr(velocity, "x", 0.0)), float(getattr(velocity, "y", 0.0))))
    if len(ego_pose_history) >= 2:
        a = ego_pose_history[-2]
        b = ego_pose_history[-1]
        dt_s = (int(getattr(b, "timestamp_us", 0)) - int(getattr(a, "timestamp_us", 0))) / 1_000_000.0
        ax, ay, _, _ = _pose_origin_and_yaw(a)
        bx, by, _, _ = _pose_origin_and_yaw(b)
        if dt_s > 1e-6:
            return float(math.hypot(bx - ax, by - ay) / dt_s)
    return 5.0


def _image_array_from_bytes(image_bytes: bytes) -> np.ndarray:
    if not image_bytes:
        return np.zeros((1,), dtype=np.uint8)
    try:
        from io import BytesIO

        from PIL import Image

        return np.asarray(Image.open(BytesIO(image_bytes)).convert("RGB"))
    except Exception:
        return np.frombuffer(image_bytes, dtype=np.uint8)


def _pose_origin_and_yaw(pose_at_time: Any | None) -> tuple[float, float, float, float]:
    pose = getattr(pose_at_time, "pose", None) if pose_at_time is not None else None
    vec = getattr(pose, "vec", None)
    quat = getattr(pose, "quat", None)
    x = float(getattr(vec, "x", 0.0) or 0.0)
    y = float(getattr(vec, "y", 0.0) or 0.0)
    z = float(getattr(vec, "z", 0.0) or 0.0)
    yaw = _yaw_from_quat(quat)
    return x, y, z, yaw


def _yaw_from_quat(quat: Any | None) -> float:
    if quat is None:
        return 0.0
    x = float(getattr(quat, "x", 0.0) or 0.0)
    y = float(getattr(quat, "y", 0.0) or 0.0)
    z = float(getattr(quat, "z", 0.0) or 0.0)
    w = float(getattr(quat, "w", 1.0) or 1.0)
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _quat_from_yaw(yaw: float, common_pb2: Any) -> Any:
    half = 0.5 * yaw
    return common_pb2.Quat(w=math.cos(half), x=0.0, y=0.0, z=math.sin(half))


def _load_grpc_modules() -> tuple[Any, Any, Any, Any]:
    try:
        import grpc
        from alpasim_grpc import API_VERSION_MESSAGE
        from alpasim_grpc.v0 import common_pb2, egodriver_pb2, egodriver_pb2_grpc
    except ImportError as exc:  # pragma: no cover - depends on AlpaSim challenge runtime.
        raise SystemExit(
            "wod2sim.challenge.e2e_driver requires the AlpaSim gRPC package. "
            "Install or copy AlpaSim src/grpc into the challenge driver image."
        ) from exc
    return grpc, API_VERSION_MESSAGE, common_pb2, egodriver_pb2, egodriver_pb2_grpc


def _build_service_class(
    *,
    grpc: Any,
    api_version_message: Any,
    common_pb2: Any,
    egodriver_pb2: Any,
    egodriver_pb2_grpc: Any,
) -> type:
    class WOD2SimChallengeService(egodriver_pb2_grpc.EgodriverServiceServicer):
        def __init__(self, adapter: WOD2SimChallengeAdapter) -> None:
            self._adapter = adapter
            self._server = None

        def attach_server(self, server: Any) -> None:
            self._server = server

        def start_session(self, request: Any, context: Any) -> Any:
            self._adapter.start_session(request)
            return common_pb2.SessionRequestStatus()

        def close_session(self, request: Any, context: Any) -> Any:
            self._adapter.close_session(request.session_uuid)
            return common_pb2.Empty()

        def submit_image_observation(self, request: Any, context: Any) -> Any:
            self._adapter.submit_image_observation(request)
            return common_pb2.Empty()

        def submit_egomotion_observation(self, request: Any, context: Any) -> Any:
            self._adapter.submit_egomotion_observation(request)
            return common_pb2.Empty()

        def submit_route(self, request: Any, context: Any) -> Any:
            self._adapter.submit_route(request)
            return common_pb2.Empty()

        def submit_recording_ground_truth(self, request: Any, context: Any) -> Any:
            return common_pb2.Empty()

        def drive(self, request: Any, context: Any) -> Any:
            try:
                prediction = self._adapter.predict(request.session_uuid, time_now_us=int(request.time_now_us))
                trajectory = prediction_to_proto_trajectory(
                    prediction,
                    current_pose=self._adapter.latest_pose(request.session_uuid),
                    time_now_us=int(request.time_now_us),
                    common_pb2=common_pb2,
                    horizon_seconds=self._adapter.horizon_seconds,
                )
            except KeyError as exc:
                context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
                raise AssertionError("unreachable") from exc
            except Exception as exc:
                LOGGER.exception("WOD2Sim challenge Drive failed")
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
                raise AssertionError("unreachable") from exc
            return egodriver_pb2.DriveResponse(trajectory=trajectory)

        def get_version(self, request: Any, context: Any) -> Any:
            return common_pb2.VersionId(
                version_id=f"wod2sim-challenge-{self._adapter.model_name}",
                git_hash=os.environ.get("WOD2SIM_GIT_HASH", "local"),
                grpc_api_version=api_version_message,
            )

        def shut_down(self, request: Any, context: Any) -> Any:
            if self._server is not None:
                threading.Thread(target=lambda: self._server.stop(grace=0.0), daemon=True).start()
            return common_pb2.Empty()

    return WOD2SimChallengeService


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve WOD2Sim as an AlpaSim E2E-style gRPC driver.")
    parser.add_argument("--model", choices=("constant_velocity", "route_following"), default=os.getenv("WOD2SIM_CHALLENGE_MODEL", "route_following"))
    parser.add_argument("--host", default=os.getenv("ALPASIM_DRIVER_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("ALPASIM_DRIVER_PORT", "6789")))
    parser.add_argument("--workers", type=int, default=int(os.getenv("ALPASIM_DRIVER_GRPC_WORKERS", "8")))
    args = parser.parse_args()

    logging.basicConfig(
        level=os.environ.get("ALPASIM_DRIVER_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    grpc, api_version_message, common_pb2, egodriver_pb2, egodriver_pb2_grpc = _load_grpc_modules()
    adapter = WOD2SimChallengeAdapter(model_name=args.model)
    service_cls = _build_service_class(
        grpc=grpc,
        api_version_message=api_version_message,
        common_pb2=common_pb2,
        egodriver_pb2=egodriver_pb2,
        egodriver_pb2_grpc=egodriver_pb2_grpc,
    )
    service = service_cls(adapter)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max(1, args.workers)))
    egodriver_pb2_grpc.add_EgodriverServiceServicer_to_server(service, server)
    service.attach_server(server)
    bound_port = server.add_insecure_port(f"{args.host}:{args.port}")
    if bound_port == 0:
        raise SystemExit(f"failed to bind {args.host}:{args.port}")

    def stop(signum: int, frame: object) -> None:
        LOGGER.info("received signal %s, stopping", signum)
        server.stop(grace=0.0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    server.start()
    LOGGER.info("WOD2Sim challenge driver listening on %s:%d", args.host, bound_port)
    server.wait_for_termination()


if __name__ == "__main__":
    main()
