from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Iterator, Sequence

from .rfs_metric import RfsReference, Trajectory


@dataclass(frozen=True)
class WodCameraImage:
    name: str
    jpeg: bytes


@dataclass(frozen=True)
class WodE2EPreferenceFrame:
    frame_name: str
    past_trajectory: Trajectory
    future_trajectory: Trajectory
    intent: int
    init_speed_mps: float
    references: list[RfsReference]
    camera_images: list[WodCameraImage] = field(default_factory=list)
    scene_tokens: list[float] | None = None
    external_embedding: list[float] | None = None


def load_preference_frames(
    val_dir: str | Path,
    *,
    shard_glob: str | None = None,
    shard_start: int = 0,
    record_start: int = 0,
    max_shards: int | None = None,
    max_records: int | None = None,
    include_camera_images: bool = True,
    require_preferences: bool = True,
) -> Iterator[WodE2EPreferenceFrame]:
    """Yield validation frames with valid WOD-E2E rater preference labels."""

    if record_start < 0:
        raise ValueError("record_start must be non-negative")
    tf, wod_e2ed_pb2 = _import_official_parser()
    if shard_glob is not None:
        shards = _shards_from_glob(shard_glob, glob_fn=tf.io.gfile.glob, shard_start=shard_start, max_shards=max_shards)
    else:
        shards = _validation_shards(Path(val_dir), shard_start=shard_start, max_shards=max_shards)
    records_seen = 0

    for shard in shards:
        dataset = tf.data.TFRecordDataset([str(shard)], compression_type="")
        for record in dataset:
            records_seen += 1
            if records_seen <= record_start:
                continue
            emitted_record_count = records_seen - record_start
            if max_records is not None and emitted_record_count > max_records:
                return

            frame = wod_e2ed_pb2.E2EDFrame()
            frame.ParseFromString(record.numpy())
            parsed = preference_frame_from_proto(
                frame,
                include_camera_images=include_camera_images,
                require_preferences=require_preferences,
            )
            if parsed is not None:
                yield parsed


def preference_frame_from_proto(
    frame: object,
    *,
    include_camera_images: bool = True,
    require_preferences: bool = True,
) -> WodE2EPreferenceFrame | None:
    """Convert an official `E2EDFrame` proto into verifier-ready references."""

    future_trajectory = trajectory_from_states(frame.future_states)
    if require_preferences and len(future_trajectory) != 20:
        return None
    if future_trajectory and len(future_trajectory) != 20:
        return None

    references: list[RfsReference] = []
    for index, preference in enumerate(frame.preference_trajectories):
        if not _has_valid_preference_score(preference):
            continue
        try:
            trajectory = align_preference_trajectory(
                trajectory_from_states(preference),
                target_len=len(future_trajectory) if future_trajectory else 20,
            )
        except ValueError:
            continue
        references.append(
            RfsReference(
                label=f"wod_preference_{index}",
                trajectory=trajectory,
                score=float(preference.preference_score),
            )
        )

    if require_preferences and not references:
        return None

    return WodE2EPreferenceFrame(
        frame_name=str(frame.frame.context.name),
        past_trajectory=trajectory_from_states(frame.past_states),
        future_trajectory=future_trajectory,
        intent=int(frame.intent),
        init_speed_mps=init_speed_from_states(frame.past_states),
        references=references,
        camera_images=camera_images_from_frame(frame) if include_camera_images else [],
    )


def trajectory_from_states(states: object) -> Trajectory:
    return [(float(x), float(y)) for x, y in zip(states.pos_x, states.pos_y)]


def camera_images_from_frame(frame: object) -> list[WodCameraImage]:
    images = getattr(getattr(frame, "frame", None), "images", [])
    return [
        WodCameraImage(name=_camera_name(getattr(image, "name", 0)), jpeg=bytes(getattr(image, "image", b"")))
        for image in images
        if getattr(image, "image", b"")
    ]


def align_preference_trajectory(
    trajectory: Sequence[tuple[float, float]],
    *,
    target_len: int = 20,
) -> Trajectory:
    """Align a rater trajectory exactly like the official RFS utility.

    The official `process_rater_specified_trajectories` truncates trajectories
    longer than the target waypoint count and pads shorter trajectories by
    repeating their final waypoint.
    """

    points = [(float(x), float(y)) for x, y in trajectory]
    if not points:
        raise ValueError("preference trajectory is empty")
    if len(points) >= target_len:
        return points[:target_len]
    return points + [points[-1]] * (target_len - len(points))


def init_speed_from_states(states: object) -> float:
    if len(states.vel_x) and len(states.vel_y):
        return math.hypot(float(states.vel_x[-1]), float(states.vel_y[-1]))
    if len(states.pos_x) >= 2 and len(states.pos_y) >= 2:
        dx = float(states.pos_x[-1]) - float(states.pos_x[-2])
        dy = float(states.pos_y[-1]) - float(states.pos_y[-2])
        return math.hypot(dx, dy) * 4.0
    return 0.0


def _validation_shards(val_dir: Path, *, shard_start: int = 0, max_shards: int | None) -> list[Path]:
    if shard_start < 0:
        raise ValueError("shard_start must be non-negative")
    shards = sorted(val_dir.glob("*.tfrecord-*"))
    if not shards:
        raise FileNotFoundError(f"no WOD-E2E shards found under {val_dir}")
    shards = shards[shard_start:]
    if max_shards is not None:
        return shards[:max_shards]
    return shards


def _shards_from_glob(
    shard_glob: str,
    *,
    glob_fn,
    shard_start: int = 0,
    max_shards: int | None,
) -> list[str]:
    if shard_start < 0:
        raise ValueError("shard_start must be non-negative")
    shards = sorted(str(path) for path in glob_fn(shard_glob))
    if not shards:
        raise FileNotFoundError(f"no WOD-E2E shards matched {shard_glob}")
    shards = shards[shard_start:]
    if max_shards is not None:
        return shards[:max_shards]
    return shards


def _has_valid_preference_score(preference: object) -> bool:
    has_field = getattr(preference, "HasField", None)
    if callable(has_field) and not has_field("preference_score"):
        return False
    return 0.0 <= float(preference.preference_score) <= 10.0


def _camera_name(value: int) -> str:
    return {
        1: "FRONT",
        2: "FRONT_LEFT",
        3: "FRONT_RIGHT",
        4: "SIDE_LEFT",
        5: "SIDE_RIGHT",
        6: "REAR_LEFT",
        7: "REAR",
        8: "REAR_RIGHT",
    }.get(int(value), f"CAMERA_{int(value)}")


def _import_official_parser():
    try:
        import tensorflow as tf
        from waymo_open_dataset.protos import end_to_end_driving_data_pb2 as wod_e2ed_pb2
    except ImportError as exc:
        raise ImportError(
            "WOD-E2E parsing requires the local parser environment. Run with "
            "`PYTHONPATH=.wod-protos .venv-v20/bin/python`, after following "
            "`docs/wod-e2e-parser-setup.md`."
        ) from exc
    return tf, wod_e2ed_pb2
