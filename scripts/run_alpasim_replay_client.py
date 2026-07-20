from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import struct
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

DEFAULT_CAMERA_ID = "camera_front_wide_120fov"
DEFAULT_ALPASIM_COMMIT = "049f70fbfe8207e1efd4831a6c3e78a38703d473"
DEFAULT_ASL_SHA256 = "237d6b55f4da5b0610f1b8b1e940f52d9efdc9e39c8ca2b35c5b5285ebefdc1f"
DEFAULT_ASL_URL = (
    "https://media.githubusercontent.com/media/NVlabs/alpasim/"
    f"{DEFAULT_ALPASIM_COMMIT}/src/runtime/tests/data/integration/rollout.asl"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay an official AlpaSim integration log against a live driver service."
    )
    parser.add_argument("--asl", required=True, type=Path)
    parser.add_argument("--endpoint", default="127.0.0.1:6791")
    parser.add_argument("--mode", choices=("full_contract", "command_only_route"), required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--frame-dir", type=Path)
    parser.add_argument("--camera-id", default=DEFAULT_CAMERA_ID)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--source-url", default=DEFAULT_ASL_URL)
    parser.add_argument("--alpasim-commit", default=DEFAULT_ALPASIM_COMMIT)
    parser.add_argument("--expected-asl-sha256", default=DEFAULT_ASL_SHA256)
    return parser.parse_args()


def _load_protocol_modules() -> tuple[Any, Any, Any, Any, Any]:
    try:
        import grpc
        from alpasim_grpc.v0 import common_pb2, egodriver_pb2, egodriver_pb2_grpc
        from alpasim_grpc.v0.logging_pb2 import LogEntry
    except ImportError as exc:
        raise SystemExit(
            "This client must run in the AlpaSim challenge image with alpasim_grpc installed."
        ) from exc
    return grpc, common_pb2, egodriver_pb2, egodriver_pb2_grpc, LogEntry


def _read_log_entries(path: Path, log_entry_type: Any) -> Iterator[Any]:
    with path.open("rb") as handle:
        while True:
            size_prefix = handle.read(4)
            if not size_prefix:
                return
            if len(size_prefix) != 4:
                raise ValueError(f"{path}: truncated ASL size prefix")
            (message_size,) = struct.unpack(">L", size_prefix)
            payload = handle.read(message_size)
            if len(payload) != message_size:
                raise ValueError(
                    f"{path}: truncated ASL message; expected {message_size}, got {len(payload)}"
                )
            yield log_entry_type.FromString(payload)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile / 100.0
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    alpha = position - lower
    return ordered[lower] * (1.0 - alpha) + ordered[upper] * alpha


def _trajectory_row(response: Any) -> dict[str, Any]:
    poses = list(getattr(getattr(response, "trajectory", None), "poses", []) or [])
    points: list[list[float]] = []
    ego_points: list[list[float]] = []
    finite = bool(poses)
    origin_x = origin_y = origin_z = origin_yaw = 0.0
    if poses:
        origin_pose = poses[0].pose
        origin_x = float(origin_pose.vec.x)
        origin_y = float(origin_pose.vec.y)
        origin_z = float(origin_pose.vec.z)
        origin_yaw = _yaw_from_quaternion(origin_pose.quat)
    cos_yaw = math.cos(-origin_yaw)
    sin_yaw = math.sin(-origin_yaw)
    for pose_at_time in poses:
        pose = pose_at_time.pose
        point = [
            float(pose.vec.x),
            float(pose.vec.y),
            float(pose.vec.z),
        ]
        quaternion = [
            float(pose.quat.w),
            float(pose.quat.x),
            float(pose.quat.y),
            float(pose.quat.z),
        ]
        finite = finite and all(math.isfinite(value) for value in (*point, *quaternion))
        points.append(point)
        delta_x = point[0] - origin_x
        delta_y = point[1] - origin_y
        ego_points.append(
            [
                cos_yaw * delta_x - sin_yaw * delta_y,
                sin_yaw * delta_x + cos_yaw * delta_y,
            ]
        )
    return {
        "trajectory_points": len(poses),
        "trajectory_finite": finite,
        "trajectory_xyz": points,
        "trajectory_ego_xy": ego_points,
        "trajectory_origin_xyz_yaw": [origin_x, origin_y, origin_z, origin_yaw],
        "trajectory_progress_m": max(
            (math.hypot(point[0], point[1]) for point in ego_points),
            default=0.0,
        ),
    }


def _yaw_from_quaternion(quaternion: Any) -> float:
    w = float(getattr(quaternion, "w", 1.0))
    x = float(getattr(quaternion, "x", 0.0))
    y = float(getattr(quaternion, "y", 0.0))
    z = float(getattr(quaternion, "z", 0.0))
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _write_camera_frame(frame_dir: Path, image: Any, frame_index: int) -> str:
    content = bytes(image.image_bytes)
    if content.startswith(b"\xff\xd8\xff"):
        suffix = ".jpg"
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        suffix = ".png"
    else:
        raise ValueError("recorded camera frame is neither JPEG nor PNG")
    frame_dir.mkdir(parents=True, exist_ok=True)
    path = frame_dir / f"{frame_index:04d}-{int(image.frame_start_us)}{suffix}"
    path.write_bytes(content)
    return path.name


def replay(args: argparse.Namespace) -> dict[str, Any]:
    (
        grpc,
        common_pb2,
        egodriver_pb2,
        egodriver_pb2_grpc,
        log_entry_type,
    ) = _load_protocol_modules()
    asl_sha256 = hashlib.sha256(args.asl.read_bytes()).hexdigest()
    if asl_sha256 != args.expected_asl_sha256:
        raise ValueError(
            f"ASL sha256 mismatch: expected {args.expected_asl_sha256}, got {asl_sha256}"
        )

    channel = grpc.insecure_channel(args.endpoint)
    grpc.channel_ready_future(channel).result(timeout=args.timeout)
    stub = egodriver_pb2_grpc.EgodriverServiceStub(channel)
    version = stub.get_version(
        common_pb2.Empty(),
        timeout=args.timeout,
    )

    entry_counts: Counter[str] = Counter()
    rpc_latencies_ms: dict[str, list[float]] = {}
    drive_rows: list[dict[str, Any]] = []
    session_uuid = ""
    latest_route: list[list[float]] = []
    extracted_frames: list[str] = []
    latest_camera_frame = ""

    def invoke(name: str, method: Any, request: Any) -> Any:
        start_ns = time.perf_counter_ns()
        response = method(request, timeout=args.timeout)
        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
        rpc_latencies_ms.setdefault(name, []).append(elapsed_ms)
        return response

    for entry in _read_log_entries(args.asl, log_entry_type):
        entry_type = str(entry.WhichOneof("log_entry") or "")
        entry_counts[entry_type] += 1
        if entry_type == "driver_session_request":
            request = entry.driver_session_request
            session_uuid = str(request.session_uuid)
            invoke("start_session", stub.start_session, request)
        elif entry_type == "driver_ego_trajectory":
            invoke(
                "submit_egomotion_observation",
                stub.submit_egomotion_observation,
                entry.driver_ego_trajectory,
            )
        elif entry_type == "route_request":
            request = entry.route_request
            latest_route = [
                [float(waypoint.x), float(waypoint.y)]
                for waypoint in request.route.waypoints
            ]
            invoke("submit_route", stub.submit_route, request)
        elif entry_type == "driver_camera_image":
            request = entry.driver_camera_image
            invoke("submit_image_observation", stub.submit_image_observation, request)
            image = request.camera_image
            if args.frame_dir is not None and image.logical_id == args.camera_id:
                latest_camera_frame = _write_camera_frame(
                    args.frame_dir,
                    image,
                    len(extracted_frames),
                )
                extracted_frames.append(latest_camera_frame)
        elif entry_type == "driver_request":
            request = entry.driver_request
            start_ns = time.perf_counter_ns()
            response = stub.drive(request, timeout=args.timeout)
            elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            rpc_latencies_ms.setdefault("drive", []).append(elapsed_ms)
            drive_rows.append(
                {
                    "index": len(drive_rows),
                    "time_now_us": int(request.time_now_us),
                    "time_query_us": int(request.time_query_us),
                    "rpc_latency_ms": elapsed_ms,
                    "route_waypoints_xy": latest_route,
                    "camera_frame": latest_camera_frame,
                    **_trajectory_row(response),
                }
            )

    if session_uuid:
        invoke(
            "close_session",
            stub.close_session,
            egodriver_pb2.DriveSessionCloseRequest(session_uuid=session_uuid),
        )
    channel.close()

    latency_summary = {
        name: {
            "samples": len(values),
            "mean": statistics.fmean(values),
            "p50": _percentile(values, 50.0),
            "p95": _percentile(values, 95.0),
            "max": max(values),
        }
        for name, values in sorted(rpc_latencies_ms.items())
    }
    drive_latencies = rpc_latencies_ms.get("drive", [])
    return {
        "schema": "wod2sim_alpasim_protocol_replay_v1",
        "source": {
            "kind": "official Apache-licensed AlpaSim integration replay",
            "url": args.source_url,
            "alpasim_commit": args.alpasim_commit,
            "asl_sha256": asl_sha256,
            "camera_id": args.camera_id,
            "reactive_closed_loop": False,
        },
        "adapter": {
            "mode": args.mode,
            "endpoint": args.endpoint,
            "version_id": str(version.version_id),
            "git_hash": str(version.git_hash),
        },
        "protocol": {
            "entry_counts": dict(sorted(entry_counts.items())),
            "session_uuid": session_uuid,
            "extracted_camera_frames": extracted_frames,
        },
        "results": {
            "drive_calls": len(drive_rows),
            "finite_drive_outputs": sum(
                row["trajectory_finite"] is True for row in drive_rows
            ),
            "nonstationary_drive_outputs": sum(
                float(row["trajectory_progress_m"]) > 1.0 for row in drive_rows
            ),
            "latency_target_ms": 100.0,
            "drive_calls_within_target": sum(
                latency <= 100.0 for latency in drive_latencies
            ),
            "rpc_latency_ms": latency_summary,
        },
        "drives": drive_rows,
    }


def main() -> int:
    args = _parse_args()
    result = replay(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["results"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
