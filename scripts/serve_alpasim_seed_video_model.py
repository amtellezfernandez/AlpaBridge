#!/usr/bin/env python3
"""Serve a recorded seed frame through AlpaSim's official video-model gRPC API."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

import grpc
from alpasim_grpc.v0 import video_model_pb2_grpc
from alpasim_grpc.v0.common_pb2 import Empty, VersionId
from alpasim_grpc.v0.video_model_pb2 import (
    CameraOutput,
    Image,
    SessionId,
    VideoChunkReturn,
)

ALPASIM_COMMIT = "9177bd0bec547d7516cc77d1864e943780ef7e7a"


class SeedFrameReplayVideoModel(video_model_pb2_grpc.WorldModelServiceServicer):
    """Return each session's initial frame and record the requested live trajectory."""

    def __init__(self, telemetry_path: Path) -> None:
        self._telemetry_path = telemetry_path
        self._sessions: dict[str, dict[str, Image]] = {}
        self._session_counter = 0
        self._render_counter = 0

    def record(self, event: str, **payload: object) -> None:
        record = {"event": event, "monotonic_ns": time.monotonic_ns(), **payload}
        self._telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        with self._telemetry_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")

    async def get_version(self, request: Empty, context: grpc.aio.ServicerContext):
        del request, context
        return VersionId(
            version_id="public-seed-frame-replay-video-model",
            git_hash=f"NVlabs/alpasim@{ALPASIM_COMMIT}",
        )

    async def start_session(self, request, context: grpc.aio.ServicerContext):
        del context
        session_id = f"seed-replay-{self._session_counter}"
        self._session_counter += 1
        frames: dict[str, Image] = {}
        frame_hashes: dict[str, str] = {}
        for camera, frame in zip(request.camera_specs, request.initial_frames, strict=True):
            frames[camera.logical_id] = Image(data=frame.data, format=frame.format)
            frame_hashes[camera.logical_id] = hashlib.sha256(frame.data).hexdigest()
        self._sessions[session_id] = frames
        self.record(
            "start_session",
            session_id=session_id,
            cameras=sorted(frames),
            initial_frame_sha256=frame_hashes,
            hdmap_bytes=len(request.static_world_map.hdmap_parquets),
            rendering_contract="recorded_seed_frame_replay",
        )
        return SessionId(session_id=session_id)

    async def render_video_chunk(self, request, context: grpc.aio.ServicerContext):
        del context
        session_id = request.session_id.session_id
        frames = self._sessions[session_id]
        poses = request.rig_trajectory.poses
        frame_count = len(poses)
        outputs = [
            CameraOutput(
                camera_logical_id=camera_id,
                rgb_frames=[
                    Image(data=frame.data, format=frame.format) for _ in range(frame_count)
                ],
            )
            for camera_id, frame in frames.items()
        ]
        self._render_counter += 1
        self.record(
            "render_video_chunk",
            session_id=session_id,
            request_index=self._render_counter,
            frame_count=frame_count,
            dynamic_actor_count=len(request.dynamic_state.actors),
            first_timestamp_us=poses[0].timestamp_us if poses else None,
            last_timestamp_us=poses[-1].timestamp_us if poses else None,
            first_xyz=(
                [poses[0].pose.vec.x, poses[0].pose.vec.y, poses[0].pose.vec.z]
                if poses
                else None
            ),
            last_xyz=(
                [poses[-1].pose.vec.x, poses[-1].pose.vec.y, poses[-1].pose.vec.z]
                if poses
                else None
            ),
        )
        return VideoChunkReturn(camera_outputs=outputs)

    async def close_session(self, request, context: grpc.aio.ServicerContext):
        del context
        self._sessions.pop(request.session_id, None)
        self.record("close_session", session_id=request.session_id)
        return Empty()


async def serve(host: str, port: int, telemetry_path: Path) -> None:
    telemetry_path.unlink(missing_ok=True)
    server = grpc.aio.server(
        options=[
            ("grpc.max_receive_message_length", 64 * 1024 * 1024),
            ("grpc.max_send_message_length", 64 * 1024 * 1024),
        ]
    )
    service = SeedFrameReplayVideoModel(telemetry_path)
    video_model_pb2_grpc.add_WorldModelServiceServicer_to_server(service, server)
    bound_port = server.add_insecure_port(f"{host}:{port}")
    if not bound_port:
        raise RuntimeError(f"could not bind video-model server to {host}:{port}")
    await server.start()
    service.record(
        "server_started",
        host=host,
        port=port,
        alpasim_commit=ALPASIM_COMMIT,
        rendering_contract="recorded_seed_frame_replay",
    )
    print(f"Seed-frame video-model server listening on {host}:{port}", flush=True)
    try:
        await server.wait_for_termination()
    finally:
        await server.stop(grace=0.5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=6790)
    parser.add_argument("--telemetry", type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(serve(args.host, args.port, args.telemetry))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
