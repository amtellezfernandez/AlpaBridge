#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import math
import struct
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from wod2sim.cli.runtime_paths import workspace_path

DEFAULT_ALPASIM_ROOT = workspace_path("workspace", "alpasim")


@dataclass(frozen=True)
class Pose2D:
    x: float
    y: float
    yaw: float


@dataclass(frozen=True)
class ActorDef:
    actor_id: str
    label: str
    length: float
    width: float
    height: float


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build an oracle actor-proxy JSON from AlpaSim ASL logs. The output is keyed by "
            "sim timestamp and can be injected into the learned AlpaSim adapter with "
            "WAYSPAN_TOKENBC_ORACLE_ACTOR_PROXY_PATH."
        )
    )
    parser.add_argument("--asl", action="append", type=Path, default=[], help="Input rollout.asl file.")
    parser.add_argument(
        "--run-dir",
        action="append",
        type=Path,
        default=[],
        help="Run or batch directory; rollout.asl files are discovered recursively.",
    )
    parser.add_argument("--output", type=Path, required=True, help="Output oracle proxy JSON path.")
    parser.add_argument("--alpasim-root", type=Path, default=DEFAULT_ALPASIM_ROOT)
    parser.add_argument("--max-actors-per-frame", type=int, default=24)
    parser.add_argument("--forward-min-m", type=float, default=-12.0)
    parser.add_argument("--forward-max-m", type=float, default=90.0)
    parser.add_argument("--lateral-max-m", type=float, default=30.0)
    parser.add_argument(
        "--allow-timestamp-collisions",
        action="store_true",
        help="Keep the first frame if multiple ASL files expose the same timestamp.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    _add_alpasim_paths(args.alpasim_root)
    asl_files = _discover_asl_files(args.asl, args.run_dir)
    if not asl_files:
        raise SystemExit("No rollout.asl files found. Pass --asl or --run-dir.")
    payload = asyncio.run(_build_proxy(args, asl_files))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    stats = payload["stats"]
    print(
        "Wrote oracle actor proxy "
        f"{args.output} with {stats['frames']} frames, "
        f"{stats['frames_with_hazards']} frames_with_hazards, "
        f"{stats['total_hazards']} hazards, {stats['timestamp_collisions']} timestamp_collisions."
    )
    return 0


def _add_alpasim_paths(alpasim_root: Path) -> None:
    for relative in ("src/grpc", "src/utils"):
        path = str((alpasim_root / relative).resolve())
        if path not in sys.path:
            sys.path.insert(0, path)


def _discover_asl_files(asl_files: Iterable[Path], run_dirs: Iterable[Path]) -> list[Path]:
    discovered = [path.resolve() for path in asl_files if path.is_file()]
    for run_dir in run_dirs:
        if run_dir.is_file() and run_dir.name.endswith(".asl"):
            discovered.append(run_dir.resolve())
        elif run_dir.is_dir():
            candidate_run_dirs = [run_dir] if (run_dir / "aggregate").is_dir() else [
                path for path in sorted(run_dir.iterdir()) if path.is_dir()
            ]
            for candidate_run_dir in candidate_run_dirs:
                selected = _asl_for_completed_run(candidate_run_dir)
                if selected is not None:
                    discovered.append(selected)
                    continue
                discovered.extend(path.resolve() for path in candidate_run_dir.rglob("rollout.asl") if path.is_file())
    unique = sorted(dict.fromkeys(discovered))
    return unique


def _asl_for_completed_run(run_dir: Path) -> Path | None:
    rollout_id = _aggregate_rollout_id(run_dir)
    if not rollout_id:
        return None
    matches = [
        path.resolve()
        for path in run_dir.rglob("rollout.asl")
        if path.parent.name == rollout_id
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _aggregate_rollout_id(run_dir: Path) -> str | None:
    aggregate_path = run_dir / "aggregate" / "metrics_unprocessed.parquet"
    if not aggregate_path.is_file():
        return None
    try:
        import pyarrow.parquet as pq

        table = pq.read_table(aggregate_path, columns=["rollout_id"])
    except Exception:
        return None
    values = [
        str(value.as_py())
        for value in table.column("rollout_id")
        if value.as_py() not in (None, "")
    ]
    unique = sorted(set(values))
    if len(unique) == 1:
        return unique[0]
    return None


async def _build_proxy(args: argparse.Namespace, asl_files: list[Path]) -> dict[str, Any]:
    try:
        from alpasim_grpc.v0.logging_pb2 import LogEntry
    except ImportError as exc:
        raise SystemExit(
            f"Could not import AlpaSim logging protobufs ({exc}). Run with the AlpaSim environment, for example:\n"
            "  ALPASIM_ROOT=/path/to/alpasim wod2sim-build-oracle-proxy --run-dir /path/to/run --output oracle.json"
        ) from exc

    async def read_pb_log(fname: str, raise_on_malformed: bool = False) -> Any:
        with open(fname, "rb", buffering=1024 * 1024) as file:
            while size_prefix := file.read(4):
                (message_size,) = struct.unpack(">L", size_prefix)
                message_chunk = file.read(message_size)
                if len(message_chunk) != message_size:
                    message = f"Malformed ASL log {fname}: expected {message_size} bytes, found {len(message_chunk)}"
                    if raise_on_malformed:
                        raise OSError(message)
                    break
                yield LogEntry.FromString(message_chunk)

    frames: dict[str, dict[str, Any]] = {}
    scene_ids: set[str] = set()
    collision_count = 0
    source_files = []

    for index, asl_path in enumerate(asl_files, start=1):
        source_files.append(str(asl_path))
        result = await _frames_from_asl(read_pb_log, asl_path, args)
        print(f"Parsed ASL {index}/{len(asl_files)}: {asl_path}", flush=True)
        scene_id = result["scene_id"]
        if scene_id:
            scene_ids.add(scene_id)
        for timestamp, frame in result["frames"].items():
            key = str(timestamp)
            if key in frames:
                collision_count += 1
                if not args.allow_timestamp_collisions:
                    raise SystemExit(
                        "Timestamp collision while building oracle actor proxy: "
                        f"{timestamp} appears in multiple ASL logs. Re-run with "
                        "--allow-timestamp-collisions only if the scene set is intentionally duplicated."
                    )
                continue
            frames[key] = frame

    total_hazards = sum(len(frame.get("world_actors", [])) for frame in frames.values())
    frames_with_hazards = sum(1 for frame in frames.values() if frame.get("world_actors"))
    return {
        "schema": "alpasim_oracle_actor_proxy_v2",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_asl_files": source_files,
        "frames": frames,
        "stats": {
            "asl_files": len(source_files),
            "scenes": len(scene_ids),
            "frames": len(frames),
            "frames_with_hazards": frames_with_hazards,
            "total_hazards": total_hazards,
            "timestamp_collisions": collision_count,
            "max_actors_per_frame": max(1, int(args.max_actors_per_frame)),
            "forward_min_m": float(args.forward_min_m),
            "forward_max_m": float(args.forward_max_m),
            "lateral_max_m": float(args.lateral_max_m),
        },
    }


async def _frames_from_asl(async_read_pb_log: Any, asl_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    actor_defs: dict[str, ActorDef] = {}
    frames: list[tuple[int, dict[str, Pose2D]]] = []
    scene_id: str | None = None

    async for entry in async_read_pb_log(str(asl_path)):
        kind = entry.WhichOneof("log_entry")
        if kind == "rollout_metadata":
            metadata = entry.rollout_metadata
            scene_id = str(metadata.session_metadata.scene_id)
            actor_defs = _actor_defs_from_metadata(metadata)
        elif kind == "actor_poses":
            poses = _poses_from_actor_poses(entry.actor_poses)
            if "EGO" in poses:
                frames.append((int(entry.actor_poses.timestamp_us), poses))

    velocities = _estimate_velocities(frames)
    output_frames: dict[int, dict[str, Any]] = {}
    for timestamp, poses in frames:
        world_actors, source_ego_pose = _world_actors_for_frame(
            poses,
            velocities.get(timestamp, {}),
            actor_defs,
            args,
        )
        output_frames[timestamp] = {
            "timestamp_us": timestamp,
            "scene_id": scene_id,
            "world_actors": world_actors,
            "source_ego_pose": source_ego_pose,
            "source_asl": str(asl_path),
        }
    return {"scene_id": scene_id, "frames": output_frames}


def _actor_defs_from_metadata(metadata: Any) -> dict[str, ActorDef]:
    actor_defs: dict[str, ActorDef] = {}
    for item in metadata.actor_definitions.actor_aabb:
        aabb = item.aabb
        actor_id = str(item.actor_id)
        actor_defs[actor_id] = ActorDef(
            actor_id=actor_id,
            label=str(getattr(item, "actor_label", "") or "actor"),
            length=max(0.25, float(aabb.size_x)),
            width=max(0.25, float(aabb.size_y)),
            height=max(0.25, float(aabb.size_z)),
        )
    return actor_defs


def _poses_from_actor_poses(actor_poses: Any) -> dict[str, Pose2D]:
    poses: dict[str, Pose2D] = {}
    for item in actor_poses.actor_poses:
        pose = item.actor_pose
        poses[str(item.actor_id)] = Pose2D(
            x=float(pose.vec.x),
            y=float(pose.vec.y),
            yaw=_yaw_from_quat(pose.quat),
        )
    return poses


def _estimate_velocities(frames: list[tuple[int, dict[str, Pose2D]]]) -> dict[int, dict[str, tuple[float, float]]]:
    actor_series: dict[str, list[tuple[int, Pose2D]]] = {}
    for timestamp, poses in frames:
        for actor_id, pose in poses.items():
            actor_series.setdefault(actor_id, []).append((timestamp, pose))

    velocities_by_actor: dict[str, dict[int, tuple[float, float]]] = {}
    for actor_id, series in actor_series.items():
        velocities_by_actor[actor_id] = {}
        for index, (timestamp, pose) in enumerate(series):
            neighbor_timestamp: int | None = None
            neighbor_pose: Pose2D | None = None
            sign = 1.0
            if index + 1 < len(series):
                neighbor_timestamp, neighbor_pose = series[index + 1]
                sign = 1.0
            elif index > 0:
                neighbor_timestamp, neighbor_pose = series[index - 1]
                sign = -1.0
            if neighbor_timestamp is None or neighbor_pose is None:
                velocities_by_actor[actor_id][timestamp] = (0.0, 0.0)
                continue
            dt_s = abs(float(neighbor_timestamp - timestamp)) / 1_000_000.0
            if dt_s <= 1e-6:
                velocities_by_actor[actor_id][timestamp] = (0.0, 0.0)
                continue
            vx = sign * (neighbor_pose.x - pose.x) / dt_s
            vy = sign * (neighbor_pose.y - pose.y) / dt_s
            velocities_by_actor[actor_id][timestamp] = (vx, vy)

    velocities: dict[int, dict[str, tuple[float, float]]] = {}
    for timestamp, poses in frames:
        velocities[timestamp] = {
            actor_id: velocities_by_actor.get(actor_id, {}).get(timestamp, (0.0, 0.0))
            for actor_id in poses
        }
    return velocities


def _world_actors_for_frame(
    poses: dict[str, Pose2D],
    velocities: dict[str, tuple[float, float]],
    actor_defs: dict[str, ActorDef],
    args: argparse.Namespace,
) -> tuple[list[dict[str, float | str]], dict[str, float]]:
    ego = poses["EGO"]
    ego_vx, ego_vy = velocities.get("EGO", (0.0, 0.0))
    forward = (math.cos(ego.yaw), math.sin(ego.yaw))
    left = (-math.sin(ego.yaw), math.cos(ego.yaw))
    world_actors: list[dict[str, float | str]] = []

    for actor_id, actor_pose in poses.items():
        if actor_id == "EGO":
            continue
        actor_def = actor_defs.get(actor_id, ActorDef(actor_id, "actor", 4.5, 2.0, 1.5))
        dx = actor_pose.x - ego.x
        dy = actor_pose.y - ego.y
        rel_x = dx * forward[0] + dy * forward[1]
        rel_y = dx * left[0] + dy * left[1]
        if rel_x < args.forward_min_m or rel_x > args.forward_max_m or abs(rel_y) > args.lateral_max_m:
            continue

        actor_vx, actor_vy = velocities.get(actor_id, (0.0, 0.0))
        radius = max(0.5, 0.5 * math.hypot(actor_def.length, actor_def.width))
        world_actors.append(
            {
                "world_x": round(actor_pose.x, 4),
                "world_y": round(actor_pose.y, 4),
                "world_vx": round(actor_vx, 4),
                "world_vy": round(actor_vy, 4),
                "radius": round(radius, 4),
                "width": round(actor_def.width, 4),
                "length": round(actor_def.length, 4),
                "world_heading": round(actor_pose.yaw, 6),
                "kind": actor_def.label or "actor",
                "label": actor_id,
                "source": "alpasim_oracle_actor_proxy",
                "source_rel_x": round(rel_x, 4),
                "source_rel_y": round(rel_y, 4),
            }
        )

    world_actors.sort(key=lambda actor: math.hypot(float(actor["source_rel_x"]), float(actor["source_rel_y"])))
    source_ego_pose = {
        "world_x": round(ego.x, 4),
        "world_y": round(ego.y, 4),
        "world_vx": round(ego_vx, 4),
        "world_vy": round(ego_vy, 4),
        "world_heading": round(ego.yaw, 6),
    }
    return world_actors[: max(1, int(args.max_actors_per_frame))], source_ego_pose


def _yaw_from_quat(quat: Any) -> float:
    w = float(getattr(quat, "w", 1.0))
    x = float(getattr(quat, "x", 0.0))
    y = float(getattr(quat, "y", 0.0))
    z = float(getattr(quat, "z", 0.0))
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _wrap_angle(value: float) -> float:
    return (float(value) + math.pi) % (2.0 * math.pi) - math.pi


if __name__ == "__main__":
    raise SystemExit(main())
