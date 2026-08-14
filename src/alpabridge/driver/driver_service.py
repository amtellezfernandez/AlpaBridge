from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import signal
import threading
import time
from concurrent import futures
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from alpabridge.driver.camera_calibration import (
    CameraCalibration,
    calibrations_from_session_request,
    camera_protos_from_session_request,
)
from alpabridge.driver.policy_registry import available_policy_names, build_policy
from alpabridge.simulator.alpasim_contract import (
    DriveCommand,
    ModelPrediction,
    prediction_headings,
    prediction_trajectory_xy,
)

LOGGER = logging.getLogger("alpabridge_driver_service")
DRIVER_TELEMETRY_SCHEMA = "alpabridge_driver_telemetry_v3"


class ModelLoadError(RuntimeError):
    """The policy could not be constructed.

    Distinct from a RuntimeError raised by a working policy, so the gRPC layer
    can report a driver that will never serve as FAILED_PRECONDITION rather than
    misreporting it as a malformed request.
    """


@dataclass
class DriverCameraFrame:
    timestamp_us: int
    image: np.ndarray
    # The rig camera this frame came from. Policies receive frames under a
    # single key, so this is the only way back to the matching calibration.
    source_camera_id: str = ""


@dataclass
class DriverSessionState:
    session_uuid: str
    random_seed: int = 0
    debug_scene_id: str | None = None
    camera_images: dict[str, list[DriverCameraFrame]] = field(default_factory=dict)
    camera_calibrations: dict[str, CameraCalibration] = field(default_factory=dict)
    camera_protos: dict[str, Any] = field(default_factory=dict)
    delivered_image_size: dict[str, tuple[int, int]] = field(default_factory=dict)
    ego_pose_history: list[Any] = field(default_factory=list)
    dynamic_states: list[tuple[int, Any]] = field(default_factory=list)
    route_waypoints: list[dict[str, float]] = field(default_factory=list)
    command: Any = DriveCommand.STRAIGHT


class DriverTelemetry:
    def __init__(self, path: str | Path | None) -> None:
        self._path = Path(path).expanduser() if path else None
        self._rows: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(self, row: dict[str, Any]) -> None:
        payload = {
            "schema": DRIVER_TELEMETRY_SCHEMA,
            "created_ns": time.time_ns(),
            **row,
        }
        with self._lock:
            self._rows.append(payload)
            if self._path is None:
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def summary(self) -> dict[str, Any]:
        with self._lock:
            rows = list(self._rows)
        drive_rows = [row for row in rows if row.get("event") == "drive"]
        latencies = [float(row["latency_ms"]) for row in drive_rows if row.get("latency_ms") is not None]
        missed = [row for row in drive_rows if row.get("latency_target_met") is False]
        route_sources = sorted(
            {
                str(row.get("route_source"))
                for row in drive_rows
                if row.get("route_source") not in (None, "")
            }
        )
        return {
            "schema": "alpabridge_driver_telemetry_summary_v1",
            "event_count": len(rows),
            "drive_count": len(drive_rows),
            "latency_ms": {
                "p50": _percentile(latencies, 50.0),
                "p95": _percentile(latencies, 95.0),
                "max": max(latencies) if latencies else None,
            },
            "latency_target_missed": len(missed),
            "route_sources": route_sources,
            "telemetry_path": str(self._path) if self._path is not None else None,
        }


class AlpaBridgeDriverService:
    """Serve any registered policy behind AlpaSim's external-driver gRPC interface."""

    def __init__(
        self,
        *,
        model_name: str = "route_following",
        camera_ids: tuple[str, ...] = ("CAM_F0", "camera_front_wide_120fov"),
        output_frequency_hz: int = 10,
        horizon_seconds: float = 5.0,
        telemetry_path: str | Path | None = None,
        latency_target_ms: float = 100.0,
        checkpoint_path: str | Path | None = None,
        tokenizer_checkpoint_path: str | Path | None = None,
        device: str = "cpu",
        route_contract_mode: str | None = None,
        defer_model_load: bool = False,
    ) -> None:
        self.model_name = _normalize_model_name(model_name)
        self.camera_candidates = tuple(camera_ids)
        self.model_camera_id = "front"
        self.output_frequency_hz = int(output_frequency_hz)
        self.horizon_seconds = float(horizon_seconds)
        if self.model_name == "navsim_ego_status_mlp":
            from alpabridge.simulator.navsim_ego_status_mlp import (
                NAVSIM_EGO_STATUS_HORIZON_SECONDS,
                NAVSIM_EGO_STATUS_OUTPUT_FREQUENCY_HZ,
            )

            self.horizon_seconds = NAVSIM_EGO_STATUS_HORIZON_SECONDS
            self.output_frequency_hz = NAVSIM_EGO_STATUS_OUTPUT_FREQUENCY_HZ
        self.latency_target_ms = float(latency_target_ms)
        self.checkpoint_path = (
            Path(checkpoint_path).expanduser().resolve() if checkpoint_path else None
        )
        self.checkpoint_sha256 = (
            _sha256_file(self.checkpoint_path) if self.checkpoint_path is not None else None
        )
        self.tokenizer_checkpoint_path = (
            Path(tokenizer_checkpoint_path).expanduser().resolve()
            if tokenizer_checkpoint_path
            else None
        )
        self.device = str(device)
        self.route_geometry_required = self.model_name in {
            "route_following",
            "token_dagger_bc",
        }
        self.route_contract_mode = _normalize_route_contract_mode(
            route_contract_mode
            if route_contract_mode is not None
            else os.getenv("ALPABRIDGE_ROUTE_CONTRACT_MODE", "full_contract")
        )
        self._lock = threading.RLock()
        self._sessions: dict[str, DriverSessionState] = {}
        self._telemetry = DriverTelemetry(telemetry_path)

        # Loading can be slow for checkpoint-backed policies. When deferred, the
        # caller is free to bind and serve the gRPC port first, so readiness
        # probes are answerable while the weights are still loading.
        self._model: Any = None
        self._model_error: BaseException | None = None
        self._model_ready = threading.Event()
        if defer_model_load:
            threading.Thread(
                target=self._load_model_in_background,
                name="alpabridge-model-load",
                daemon=True,
            ).start()
        else:
            self._model = self._build_model()
            self._model_ready.set()

    def _load_model_in_background(self) -> None:
        started = time.perf_counter()
        try:
            model = self._build_model()
        except BaseException as exc:  # noqa: BLE001 - re-raised to callers of _require_model
            self._model_error = exc
            LOGGER.exception("AlpaBridge policy %s failed to load", self.model_name)
            self._telemetry.record({"event": "model_load_failed", "error": repr(exc)})
        else:
            self._model = model
            LOGGER.info(
                "AlpaBridge policy %s loaded in %.1fs",
                self.model_name,
                time.perf_counter() - started,
            )
            self._telemetry.record(
                {"event": "model_loaded", "seconds": time.perf_counter() - started}
            )
        finally:
            self._model_ready.set()

    def wait_for_model(self, timeout_s: float | None = None) -> bool:
        """Block until the policy is loaded. False if it is still not ready."""
        return self._model_ready.wait(timeout_s)

    def _require_model(self) -> Any:
        """Return the policy, waiting for a deferred load and failing loudly."""
        if self._model is not None:
            return self._model
        # This wait happens inside drive(), which is budgeted at 100 ms, and the
        # AlpaSim E2E challenge caps a whole PAI evaluation at ~1031 s wall of
        # which only ~250 s is driver time. Blocking here for minutes would end
        # the run rather than rescue it, so the default is a small fraction of
        # that budget: better to fail one call as UNAVAILABLE than to spend the
        # evaluation waiting.
        timeout_s = float(os.getenv("ALPABRIDGE_DRIVER_MODEL_LOAD_TIMEOUT_S", "30"))
        if not self._model_ready.wait(timeout_s):
            raise TimeoutError(
                f"policy {self.model_name} still loading after {timeout_s:.0f}s"
            )
        if self._model_error is not None:
            raise ModelLoadError(
                f"policy {self.model_name} failed to load: {self._model_error!r}"
            ) from self._model_error
        return self._model

    def start_session(self, request: Any) -> None:
        session_uuid = str(request.session_uuid)
        debug_info = getattr(request, "debug_info", None)
        debug_scene_id = getattr(debug_info, "scene_id", None) if debug_info is not None else None
        calibrations = calibrations_from_session_request(request)
        camera_protos = camera_protos_from_session_request(request)
        if not calibrations:
            # Only pixel-reading policies need this, so it is a warning and not a
            # refusal; the geometric baselines run fine without a rig.
            _warn_once(
                "camera-calibration-absent",
                "This session carried no usable camera calibration, so policies "
                "reading pixels have no intrinsics to work from.",
            )
        with self._lock:
            self._sessions[session_uuid] = DriverSessionState(
                session_uuid=session_uuid,
                random_seed=int(getattr(request, "random_seed", 0) or 0),
                debug_scene_id=str(debug_scene_id) if debug_scene_id else None,
                camera_calibrations=calibrations,
                camera_protos=camera_protos,
            )
        self._telemetry.record(
            {
                "event": "start_session",
                "session_uuid": session_uuid,
                "random_seed": int(getattr(request, "random_seed", 0) or 0),
                "debug_scene_id": str(debug_scene_id) if debug_scene_id else None,
            }
        )

    def close_session(self, session_uuid: str) -> None:
        with self._lock:
            self._sessions.pop(str(session_uuid), None)
        inference_cache = getattr(self._model, "_inference_cache", None)
        if inference_cache is not None:
            inference_cache.forget(str(session_uuid))
        self._telemetry.record({"event": "close_session", "session_uuid": str(session_uuid)})

    def submit_image_observation(self, request: Any) -> None:
        session = self._session(str(request.session_uuid))
        grpc_image = request.camera_image
        camera_id = str(getattr(grpc_image, "logical_id", "") or self.camera_candidates[0])
        frame = DriverCameraFrame(
            timestamp_us=int(getattr(grpc_image, "frame_end_us", 0) or 0),
            image=_image_array_from_bytes(getattr(grpc_image, "image_bytes", b"")),
            source_camera_id=camera_id,
        )
        delivered = _delivered_image_size(frame.image)
        with self._lock:
            frames = session.camera_images.setdefault(camera_id, [])
            frames.append(frame)
            del frames[:-1]
            if delivered is not None:
                session.delivered_image_size[camera_id] = delivered
        self._telemetry.record(
            {
                "event": "image",
                "session_uuid": session.session_uuid,
                "camera_id": camera_id,
                "timestamp_us": frame.timestamp_us,
            }
        )

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
        self._telemetry.record(
            {
                "event": "egomotion",
                "session_uuid": session.session_uuid,
                "pose_count": len(poses),
                "dynamic_state_count": len(dynamic_states),
            }
        )

    def submit_route(self, request: Any) -> None:
        session = self._session(str(request.session_uuid))
        route = getattr(request, "route", None)
        waypoints = _route_waypoints_from_proto(route)
        with self._lock:
            session.route_waypoints = waypoints
            session.command = _command_from_waypoints(waypoints)
        self._telemetry.record(
            {
                "event": "route",
                "session_uuid": session.session_uuid,
                "route_waypoint_count": len(waypoints),
                "route_source": "alpasim_waypoints" if len(waypoints) >= 2 else "command_proxy",
                "route_geometry_required": self.route_geometry_required,
            }
        )

    def predict(self, session_uuid: str, *, time_now_us: int) -> ModelPrediction:
        prediction_input = self.prediction_input(session_uuid, time_now_us=time_now_us)
        return self._require_model().predict(prediction_input)

    def drive_once_to_proto(self, session_uuid: str, *, time_now_us: int, common_pb2: Any) -> Any:
        start_ns = time.perf_counter_ns()
        prediction_input = self.prediction_input(session_uuid, time_now_us=time_now_us)
        prediction = self._require_model().predict(prediction_input)
        trajectory = prediction_to_proto_trajectory(
            prediction,
            current_pose=self.latest_pose(session_uuid),
            time_now_us=int(time_now_us),
            common_pb2=common_pb2,
            horizon_seconds=self.horizon_seconds,
        )
        latency_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
        reasoning = _json_object(prediction.reasoning_text)
        signal = reasoning.get("alpasim_signal", {}) if isinstance(reasoning.get("alpasim_signal"), dict) else {}
        visible_waypoints = list(prediction_input.route_waypoints)
        self._telemetry.record(
            {
                "event": "drive",
                "session_uuid": session_uuid,
                "model": self.model_name,
                "checkpoint_sha256": self.checkpoint_sha256,
                "time_now_us": int(time_now_us),
                "latency_ms": round(latency_ms, 6),
                "latency_target_ms": self.latency_target_ms,
                "latency_target_met": latency_ms <= self.latency_target_ms,
                "route_contract_mode": self.route_contract_mode,
                "route_source": (
                    "alpasim_waypoints"
                    if len(visible_waypoints) >= 2
                    else "command_proxy"
                ),
                "route_waypoint_count": len(visible_waypoints),
                "route_geometry_required": self.route_geometry_required,
                "model_input_contract": reasoning.get("input_contract"),
                "route_geometry_consumed": reasoning.get(
                    "route_geometry_consumed",
                    self.route_geometry_required,
                ),
                "camera_count": signal.get(
                    "camera_count",
                    len(prediction_input.camera_images),
                ),
                "speed_mps": float(prediction_input.speed),
                "trajectory_points": len(getattr(trajectory, "poses", []) or []),
                "trajectory_future_points": len(prediction_trajectory_xy(prediction)),
                "trajectory_expected_future_points": int(
                    round(self.output_frequency_hz * self.horizon_seconds)
                ),
                "trajectory_includes_current_pose": True,
                "trajectory_finite": _proto_trajectory_is_finite(trajectory),
            }
        )
        return trajectory

    def telemetry_summary(self) -> dict[str, Any]:
        return self._telemetry.summary()

    def prediction_input(self, session_uuid: str, *, time_now_us: int) -> SimpleNamespace:
        session = self._session(session_uuid)
        with self._lock:
            camera_images = {key: list(value) for key, value in session.camera_images.items()}
            if not camera_images:
                camera_images = {
                    self.model_camera_id: [
                        DriverCameraFrame(timestamp_us=int(time_now_us), image=np.zeros((1,), dtype=np.uint8))
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
            camera_calibrations = _calibrations_for_delivered_images(
                session.camera_calibrations, session.delivered_image_size
            )
            camera_protos = dict(session.camera_protos)
        if self.route_contract_mode == "command_only_route":
            route_waypoints = []
        speed, velocity_xy, acceleration_xy = _estimate_ego_kinematics(
            ego_pose_history,
            dynamic_states,
        )

        return SimpleNamespace(
            camera_images=camera_images,
            camera_calibrations=camera_calibrations,
            camera_protos=camera_protos,
            command=command,
            speed=speed,
            acceleration=float(math.hypot(*acceleration_xy)),
            velocity_xy=velocity_xy,
            acceleration_xy=acceleration_xy,
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
        return build_policy(self.model_name, self)

    def _session(self, session_uuid: str) -> DriverSessionState:
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
    # Read through the contract accessors: AlpaSim's ModelPrediction carries 6-DoF
    # candidates, not a flat path, and only alpasim_contract should know that shape.
    trajectory_xy = prediction_trajectory_xy(prediction)
    headings = prediction_headings(prediction)
    if trajectory_xy.shape[0] < 1:
        raise ValueError("prediction trajectory must contain at least one point")
    if headings.shape != (trajectory_xy.shape[0],):
        raise ValueError(
            "prediction headings must contain one value per trajectory point"
        )
    if not np.isfinite(trajectory_xy).all() or not np.isfinite(headings).all():
        raise ValueError("prediction trajectory and headings must contain only finite values")
    origin_x, origin_y, origin_z, yaw0 = _pose_origin_and_yaw(current_pose)
    if not all(math.isfinite(value) for value in (origin_x, origin_y, origin_z, yaw0)):
        raise ValueError("current pose must contain only finite values")
    cos_yaw = math.cos(yaw0)
    sin_yaw = math.sin(yaw0)
    count = max(1, int(trajectory_xy.shape[0]))
    trajectory = common_pb2.Trajectory()
    step_us = int(round(float(horizon_seconds) * 1_000_000 / count))
    trajectory.poses.append(
        common_pb2.PoseAtTime(
            timestamp_us=int(time_now_us),
            pose=common_pb2.Pose(
                vec=common_pb2.Vec3(x=origin_x, y=origin_y, z=origin_z),
                quat=_quat_from_yaw(yaw0, common_pb2),
            ),
        )
    )
    for offset_index, offset in enumerate(trajectory_xy):
        x_local = (
            origin_x
            + cos_yaw * float(offset[0])
            - sin_yaw * float(offset[1])
        )
        y_local = (
            origin_y
            + sin_yaw * float(offset[0])
            + cos_yaw * float(offset[1])
        )
        heading = yaw0 + float(headings[offset_index])
        if not all(math.isfinite(value) for value in (x_local, y_local, heading)):
            raise ValueError("serialized trajectory must contain only finite values")
        timestamp_us = int(time_now_us) + (offset_index + 1) * step_us
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


def _proto_trajectory_is_finite(trajectory: Any) -> bool:
    poses = list(getattr(trajectory, "poses", []) or [])
    if not poses:
        return False
    for pose_at_time in poses:
        pose = getattr(pose_at_time, "pose", None)
        vec = getattr(pose, "vec", None)
        quat = getattr(pose, "quat", None)
        values = (
            getattr(vec, "x", None),
            getattr(vec, "y", None),
            getattr(vec, "z", None),
            getattr(quat, "w", None),
            getattr(quat, "x", None),
            getattr(quat, "y", None),
            getattr(quat, "z", None),
        )
        if not all(
            isinstance(value, (int, float)) and math.isfinite(float(value))
            for value in values
        ):
            return False
    return True


def _normalize_model_name(model_name: str) -> str:
    value = model_name.strip().lower().replace("-", "_")
    valid = available_policy_names()
    if value not in valid:
        raise ValueError(f"Supported policies: {', '.join(valid)}")
    return value


def _normalize_route_contract_mode(mode: str) -> str:
    value = mode.strip().lower()
    if value in {"", "full", "full_contract"}:
        return "full_contract"
    if value in {"command_only", "command_only_route"}:
        return "command_only_route"
    raise ValueError(
        "route contract mode must be full_contract or command_only_route; "
        f"got {mode!r}"
    )


def run_self_test(
    *,
    model_name: str = "route_following",
    iterations: int = 32,
    latency_target_ms: float = 100.0,
    checkpoint_path: str | Path | None = None,
    tokenizer_checkpoint_path: str | Path | None = None,
    device: str = "cpu",
) -> dict[str, Any]:
    adapter = AlpaBridgeDriverService(
        model_name=model_name,
        latency_target_ms=latency_target_ms,
        telemetry_path=None,
        checkpoint_path=checkpoint_path,
        tokenizer_checkpoint_path=tokenizer_checkpoint_path,
        device=device,
    )
    session_uuid = "alpabridge-self-test"
    adapter.start_session(
        SimpleNamespace(
            session_uuid=session_uuid,
            random_seed=17,
            debug_info=SimpleNamespace(scene_id="driver-self-test"),
        )
    )
    adapter.submit_image_observation(
        SimpleNamespace(
            session_uuid=session_uuid,
            camera_image=SimpleNamespace(
                logical_id="CAM_F0", frame_end_us=1_000_000, image_bytes=_self_test_image_bytes()
            ),
        )
    )
    adapter.submit_egomotion_observation(
        SimpleNamespace(
            session_uuid=session_uuid,
            trajectory=SimpleNamespace(
                poses=[
                    _self_test_pose(900_000, x=0.0, y=0.0, yaw=0.0),
                    _self_test_pose(1_000_000, x=0.5, y=0.0, yaw=0.0),
                ]
            ),
            dynamic_states=[],
        )
    )
    adapter.submit_route(
        SimpleNamespace(
            session_uuid=session_uuid,
            route=SimpleNamespace(
                waypoints=[
                    SimpleNamespace(x=0.0, y=0.0, z=0.0),
                    SimpleNamespace(x=30.0, y=5.0, z=0.0),
                    SimpleNamespace(x=60.0, y=5.0, z=0.0),
                ]
            ),
        )
    )
    count = max(1, int(iterations))
    for index in range(count):
        adapter.drive_once_to_proto(
            session_uuid,
            time_now_us=1_000_000 + index * 100_000,
            common_pb2=_SelfTestCommonPb2,
        )
    summary = adapter.telemetry_summary()
    summary.update(
        {
            "model": adapter.model_name,
            "checkpoint_sha256": adapter.checkpoint_sha256,
            "claim": (
                "learned_policy_driver_self_test"
                if adapter.model_name
                in {"token_dagger_bc", "navsim_ego_status_mlp"}
                else "dependency_light_driver_self_test"
            ),
            "benchmark_result": False,
            "latency_target_ms": latency_target_ms,
        }
    )
    return summary


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
    camera_images: dict[str, list[DriverCameraFrame]],
    candidates: tuple[str, ...],
) -> list[DriverCameraFrame]:
    candidate_frames: list[tuple[int, int, DriverCameraFrame]] = []
    for priority, camera_id in enumerate(candidates):
        frames = camera_images.get(camera_id)
        if frames:
            frame = frames[-1]
            candidate_frames.append((int(frame.timestamp_us), -priority, frame))
    if candidate_frames:
        return [max(candidate_frames, key=lambda item: (item[0], item[1]))[2]]
    fallback_frames = [frames[-1] for frames in camera_images.values() if frames]
    if fallback_frames:
        return [max(fallback_frames, key=lambda frame: int(frame.timestamp_us))]
    return [DriverCameraFrame(timestamp_us=0, image=np.zeros((1,), dtype=np.uint8))]


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


def _estimate_speed_mps(
    ego_pose_history: list[Any],
    dynamic_states: list[tuple[int, Any]],
) -> float:
    return _estimate_ego_kinematics(ego_pose_history, dynamic_states)[0]


def _estimate_ego_kinematics(
    ego_pose_history: list[Any],
    dynamic_states: list[tuple[int, Any]],
) -> tuple[float, tuple[float, float], tuple[float, float]]:
    pose_velocity = _pose_velocity_in_latest_rig(ego_pose_history[-2:])
    pose_acceleration = _pose_acceleration_in_latest_rig(ego_pose_history[-3:])
    dynamic_velocity: tuple[float, float] | None = None
    dynamic_acceleration: tuple[float, float] | None = None
    if dynamic_states:
        state = dynamic_states[-1][1]
        dynamic_velocity = _finite_vec2(getattr(state, "linear_velocity", None))
        dynamic_acceleration = _finite_vec2(
            getattr(state, "linear_acceleration", None)
        )
    pose_speed = (
        float(math.hypot(*pose_velocity))
        if pose_velocity is not None
        else None
    )
    dynamic_speed = (
        float(math.hypot(*dynamic_velocity))
        if dynamic_velocity is not None
        else None
    )
    if (
        dynamic_velocity is not None
        and dynamic_speed is not None
        and (
            dynamic_speed >= 0.1
            or pose_speed is None
            or pose_speed < 0.5
        )
    ):
        velocity_xy = dynamic_velocity
        speed = dynamic_speed
    elif pose_velocity is not None and pose_speed is not None:
        velocity_xy = pose_velocity
        speed = pose_speed
    else:
        velocity_xy = (5.0, 0.0)
        speed = 5.0
    acceleration_xy = (
        dynamic_acceleration
        if dynamic_acceleration is not None
        and math.hypot(*dynamic_acceleration) >= 1e-3
        else pose_acceleration or (0.0, 0.0)
    )
    return speed, velocity_xy, acceleration_xy


def _pose_velocity_in_latest_rig(
    poses: list[Any],
) -> tuple[float, float] | None:
    if len(poses) < 2:
        return None
    earlier, later = poses[-2:]
    dt_s = (
        int(getattr(later, "timestamp_us", 0))
        - int(getattr(earlier, "timestamp_us", 0))
    ) / 1_000_000.0
    if dt_s <= 1e-6:
        return None
    ax, ay, _, _ = _pose_origin_and_yaw(earlier)
    bx, by, _, latest_yaw = _pose_origin_and_yaw(later)
    world_vx = (bx - ax) / dt_s
    world_vy = (by - ay) / dt_s
    cos_yaw = math.cos(-latest_yaw)
    sin_yaw = math.sin(-latest_yaw)
    return (
        cos_yaw * world_vx - sin_yaw * world_vy,
        sin_yaw * world_vx + cos_yaw * world_vy,
    )


def _pose_acceleration_in_latest_rig(
    poses: list[Any],
) -> tuple[float, float] | None:
    if len(poses) < 3:
        return None
    first, middle, last = poses[-3:]
    first_velocity = _world_pose_velocity(first, middle)
    second_velocity = _world_pose_velocity(middle, last)
    if first_velocity is None or second_velocity is None:
        return None
    first_time = int(getattr(first, "timestamp_us", 0))
    last_time = int(getattr(last, "timestamp_us", 0))
    dt_s = (last_time - first_time) / 2_000_000.0
    if dt_s <= 1e-6:
        return None
    world_ax = (second_velocity[0] - first_velocity[0]) / dt_s
    world_ay = (second_velocity[1] - first_velocity[1]) / dt_s
    _, _, _, latest_yaw = _pose_origin_and_yaw(last)
    cos_yaw = math.cos(-latest_yaw)
    sin_yaw = math.sin(-latest_yaw)
    return (
        cos_yaw * world_ax - sin_yaw * world_ay,
        sin_yaw * world_ax + cos_yaw * world_ay,
    )


def _world_pose_velocity(
    earlier: Any,
    later: Any,
) -> tuple[float, float] | None:
    dt_s = (
        int(getattr(later, "timestamp_us", 0))
        - int(getattr(earlier, "timestamp_us", 0))
    ) / 1_000_000.0
    if dt_s <= 1e-6:
        return None
    ax, ay, _, _ = _pose_origin_and_yaw(earlier)
    bx, by, _, _ = _pose_origin_and_yaw(later)
    return ((bx - ax) / dt_s, (by - ay) / dt_s)


def _finite_vec2(value: Any) -> tuple[float, float] | None:
    if value is None:
        return None
    try:
        parsed = (
            float(getattr(value, "x")),
            float(getattr(value, "y")),
        )
    except (AttributeError, TypeError, ValueError):
        return None
    return parsed if all(math.isfinite(item) for item in parsed) else None


_FALLBACK_WARNINGS: set[str] = set()


def _warn_once(key: str, message: str) -> None:
    if key not in _FALLBACK_WARNINGS:
        _FALLBACK_WARNINGS.add(key)
        LOGGER.warning(message)


def _image_array_from_bytes(image_bytes: bytes) -> np.ndarray:
    if not image_bytes:
        # The third degradation in this function, and the only one that stayed
        # silent: a policy reading pixels cannot tell this placeholder from a
        # decoded frame except by shape.
        _warn_once(
            "image-bytes-empty",
            "A camera frame arrived with no image bytes; passing a placeholder array "
            "instead. Further empty frames are not logged.",
        )
        return np.zeros((1,), dtype=np.uint8)

    try:
        from io import BytesIO

        from PIL import Image
    except ImportError:
        # Distinct from a bad frame: without a decoder every frame for the rest
        # of the process degrades, so say so once rather than per frame.
        _warn_once(
            "pillow-missing",
            "Pillow is not installed, so camera frames reach policies as raw undecoded "
            "bytes rather than an RGB array. Install alpabridge[driver] for any policy "
            "that reads pixels.",
        )
        return np.frombuffer(image_bytes, dtype=np.uint8)

    try:
        return np.asarray(Image.open(BytesIO(image_bytes)).convert("RGB"))
    except Exception:
        _warn_once(
            "image-decode-failed",
            "Could not decode a camera frame; passing raw bytes through instead. "
            "Further decode failures are not logged.",
        )
        return np.frombuffer(image_bytes, dtype=np.uint8)


def _delivered_image_size(image: np.ndarray) -> tuple[int, int] | None:
    """(width, height) of a decoded frame, or None for the 1-D fallbacks."""
    if image.ndim < 2:
        return None
    return int(image.shape[1]), int(image.shape[0])


def _calibrations_for_delivered_images(
    calibrations: dict[str, CameraCalibration],
    delivered: dict[str, tuple[int, int]],
) -> dict[str, CameraCalibration]:
    """Express each calibration for the image size that actually arrived.

    The declared resolution is the native camera's; a rig can deliver JPEGs of a
    different size, and intrinsics are only meaningful against the image they
    are applied to.
    """
    scaled: dict[str, CameraCalibration] = {}
    for camera_id, calibration in calibrations.items():
        size = delivered.get(camera_id)
        if size is None:
            scaled[camera_id] = calibration
            continue
        try:
            scaled[camera_id] = calibration.scaled_to(*size)
        except ValueError:
            _warn_once(
                f"calibration-scale-failed-{camera_id}",
                f"Could not scale the calibration for {camera_id} to the delivered "
                f"{size[0]}x{size[1]} image; passing it through unscaled.",
            )
            scaled[camera_id] = calibration
    return scaled


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


def _json_object(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0.0, min(100.0, percentile)) / 100.0 * (len(ordered) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return ordered[lower]
    alpha = rank - lower
    return ordered[lower] * (1.0 - alpha) + ordered[upper] * alpha


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _SelfTestCommonPb2:
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
            self.poses: list[Any] = []


def _self_test_image_bytes() -> bytes:
    try:
        from io import BytesIO

        from PIL import Image

        rng = np.random.default_rng(0)
        pixels = rng.integers(0, 256, size=(90, 160, 3), dtype=np.uint8)
        buffer = BytesIO()
        Image.fromarray(pixels).save(buffer, format="PNG")
        return buffer.getvalue()
    except ImportError:
        return b"\x80"


def _self_test_pose(timestamp_us: int, *, x: float, y: float, yaw: float) -> Any:
    half = yaw * 0.5
    return SimpleNamespace(
        timestamp_us=timestamp_us,
        pose=SimpleNamespace(
            vec=SimpleNamespace(x=x, y=y, z=0.0),
            quat=SimpleNamespace(w=math.cos(half), x=0.0, y=0.0, z=math.sin(half)),
        ),
    )


def _load_grpc_modules() -> tuple[Any, Any, Any, Any]:
    try:
        import grpc
        from alpasim_grpc import API_VERSION_MESSAGE
        from alpasim_grpc.v0 import common_pb2, egodriver_pb2, egodriver_pb2_grpc
    except ImportError as exc:  # pragma: no cover - depends on an AlpaSim checkout.
        raise SystemExit(
            "alpabridge.driver.driver_service requires the AlpaSim gRPC package. "
            "Install or copy AlpaSim src/grpc into the driver image."
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
    class AlpaBridgeDriverServicer(egodriver_pb2_grpc.EgodriverServiceServicer):
        def __init__(self, adapter: AlpaBridgeDriverService) -> None:
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
                trajectory = self._adapter.drive_once_to_proto(
                    request.session_uuid,
                    time_now_us=int(request.time_now_us),
                    common_pb2=common_pb2,
                )
            except KeyError as exc:
                context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
                raise AssertionError("unreachable") from exc
            except TimeoutError as exc:
                # Still loading: retryable, and distinct from a bad request.
                context.abort(grpc.StatusCode.UNAVAILABLE, str(exc))
                raise AssertionError("unreachable") from exc
            except ModelLoadError as exc:
                # The policy will never serve. Not retryable, and emphatically
                # not the caller's fault, so neither UNAVAILABLE nor a bad request.
                LOGGER.error("AlpaBridge driver has no usable policy: %s", exc)
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
                raise AssertionError("unreachable") from exc
            except Exception as exc:
                LOGGER.exception("AlpaBridge driver Drive failed")
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
                raise AssertionError("unreachable") from exc
            return egodriver_pb2.DriveResponse(trajectory=trajectory)

        def get_version(self, request: Any, context: Any) -> Any:
            return common_pb2.VersionId(
                version_id=f"alpabridge-driver-{self._adapter.model_name}",
                git_hash=os.environ.get("ALPABRIDGE_GIT_HASH", "local"),
                grpc_api_version=api_version_message,
            )

        def shut_down(self, request: Any, context: Any) -> Any:
            if self._server is not None:
                threading.Thread(target=lambda: self._server.stop(grace=0.0), daemon=True).start()
            return common_pb2.Empty()

    return AlpaBridgeDriverServicer


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve an AlpaBridge policy behind AlpaSim's external-driver gRPC interface.")
    parser.add_argument(
        "--model",
        choices=available_policy_names(),
        default=os.getenv("ALPABRIDGE_DRIVER_MODEL", "route_following"),
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=(
            Path(os.environ["ALPABRIDGE_DRIVER_CHECKPOINT"])
            if os.environ.get("ALPABRIDGE_DRIVER_CHECKPOINT")
            else None
        ),
        help=(
            "Learned checkpoint path required by token_dagger_bc, "
            "navsim_ego_status_mlp, or vavam."
        ),
    )
    parser.add_argument(
        "--tokenizer-checkpoint",
        type=Path,
        default=(
            Path(os.environ["ALPABRIDGE_DRIVER_TOKENIZER_CHECKPOINT"])
            if os.environ.get("ALPABRIDGE_DRIVER_TOKENIZER_CHECKPOINT")
            else None
        ),
        help="VQ tokenizer checkpoint path required by vavam.",
    )
    parser.add_argument(
        "--device",
        default=os.getenv("ALPABRIDGE_DRIVER_DEVICE", "cpu"),
        help="Torch device for learned policies. Recorded replay defaults to CPU.",
    )
    parser.add_argument("--host", default=os.getenv("ALPASIM_DRIVER_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("ALPASIM_DRIVER_PORT", "6789")))
    parser.add_argument("--workers", type=int, default=int(os.getenv("ALPASIM_DRIVER_GRPC_WORKERS", "8")))
    parser.add_argument("--telemetry-path", default=os.getenv("ALPABRIDGE_DRIVER_TELEMETRY_PATH", "/tmp/alpabridge/driver.jsonl"))
    parser.add_argument("--latency-target-ms", type=float, default=float(os.getenv("ALPABRIDGE_DRIVER_LATENCY_TARGET_MS", "100.0")))
    parser.add_argument("--self-test", action="store_true", help="Run a dependency-light adapter self-test without alpasim_grpc.")
    parser.add_argument("--self-test-iterations", type=int, default=32)
    args = parser.parse_args()

    logging.basicConfig(
        level=os.environ.get("ALPASIM_DRIVER_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.self_test:
        print(
            json.dumps(
                run_self_test(
                    model_name=args.model,
                    iterations=args.self_test_iterations,
                    latency_target_ms=args.latency_target_ms,
                    checkpoint_path=args.checkpoint,
                    tokenizer_checkpoint_path=args.tokenizer_checkpoint,
                    device=args.device,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return
    grpc, api_version_message, common_pb2, egodriver_pb2, egodriver_pb2_grpc = _load_grpc_modules()
    # Serving readiness is what the evaluator gates on, so load off the critical
    # path by default and let the port come up immediately. Set
    # ALPABRIDGE_DRIVER_EAGER_MODEL_LOAD=1 to load before serving, which surfaces
    # construction errors at startup and is usually what you want locally.
    eager = os.getenv("ALPABRIDGE_DRIVER_EAGER_MODEL_LOAD", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    adapter = AlpaBridgeDriverService(
        model_name=args.model,
        telemetry_path=args.telemetry_path,
        latency_target_ms=args.latency_target_ms,
        checkpoint_path=args.checkpoint,
        tokenizer_checkpoint_path=args.tokenizer_checkpoint,
        device=args.device,
        defer_model_load=not eager,
    )
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
    LOGGER.info("AlpaBridge driver listening on %s:%d", args.host, bound_port)
    server.wait_for_termination()


if __name__ == "__main__":
    main()
