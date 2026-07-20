#!/usr/bin/env python3
"""Package and validate one reactive AlpaSim NAVSIM external-driver rollout."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

ALPASIM_COMMIT = "9177bd0bec547d7516cc77d1864e943780ef7e7a"
ALPASIM_IMAGE_ID = (
    "sha256:a305ca08dc51ddabd668857fad704fca92772638fb21a9cf012d75767d71cee4"
)
CHECKPOINT_REVISION = "32d89c0ae6e7c13c311f4a034002006c250afab0"
CHECKPOINT_SHA256 = "87d75b0f43d077ac3531370d7cccac98656d4e9b5ce5fa6618e28b7358b3a86b"
CHECKPOINT_URL = (
    "https://huggingface.co/autonomousvision/navsim_baselines/resolve/"
    f"{CHECKPOINT_REVISION}/ego_status_mlp/ego_status_mlp_seed_0.ckpt"
)
SOURCE_FIXTURE_SHA256 = (
    "0ee95b5bc3a69693cd5a3da3a7d430b673f15371f6844f641866302b5deab2f6"
)
DERIVED_FIXTURE_SHA256 = (
    "069fd063a64c82112ec971b585b7eb08d09f9233a4f2ac5e816e19af7185d70d"
)
SOURCE_FIXTURE_URL = (
    "https://media.githubusercontent.com/media/NVlabs/alpasim/"
    f"{ALPASIM_COMMIT}/src/runtime/tests/data/mock_video_model/"
    "clipgt-0b10bce8-61f1-4350-8577-cf3c9493ffc3.usdz"
)
EXPECTED_SESSION_COUNTS = {
    "close_session": 1,
    "drive": 197,
    "egomotion": 197,
    "image": 198,
    "route": 197,
    "start_session": 1,
}
EXPECTED_VIDEO_MODEL_COUNTS = {
    "close_session": 1,
    "render_video_chunk": 198,
    "server_started": 1,
    "start_session": 1,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number}: expected JSON object")
            records.append(record)
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        raise ValueError("cannot compute a percentile without values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile_value / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def latency_summary(records: list[dict[str, Any]]) -> dict[str, float]:
    values = [float(record["latency_ms"]) for record in records if record["event"] == "drive"]
    return {
        "max": max(values),
        "mean": sum(values) / len(values),
        "min": min(values),
        "p50": percentile(values, 50.0),
        "p95": percentile(values, 95.0),
    }


def event_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(record["event"]) for record in records).items()))


def copy_evidence_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    shutil.copyfile(source, destination)


def probe_video(path: Path) -> dict[str, Any]:
    process = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate,nb_frames,duration",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(process.stdout)
    streams = payload.get("streams")
    format_record = payload.get("format")
    if (
        not isinstance(streams, list)
        or len(streams) != 1
        or not isinstance(streams[0], dict)
        or not isinstance(format_record, dict)
    ):
        raise ValueError(f"unexpected video metadata: {path}")
    stream = streams[0]
    record = {
        "bytes": int(format_record["size"]),
        "codec": str(stream["codec_name"]),
        "duration_s": float(format_record["duration"]),
        "frames": int(stream["nb_frames"]),
        "height": int(stream["height"]),
        "r_frame_rate": str(stream["r_frame_rate"]),
        "width": int(stream["width"]),
    }
    if (
        record["codec"] != "h264"
        or record["bytes"] != path.stat().st_size
        or record["duration_s"] <= 0.0
        or record["frames"] < 1
        or record["width"] < 1
        or record["height"] < 1
    ):
        raise ValueError(f"invalid H.264 evidence video: {path}")
    return record


def parse_runtime_durations(runtime_log: str) -> dict[str, float]:
    match = re.search(
        r"simulated ([0-9.]+) sim seconds in ([0-9.]+) wall clock seconds "
        r"for ([0-9.]+)x real time \(total rollout ([0-9.]+)s incl\. setup/warmup\)",
        runtime_log,
    )
    if match is None:
        raise ValueError("successful runtime log does not contain rollout durations")
    simulated, active_wall, realtime_factor, total_wall = map(float, match.groups())
    return {
        "active_wall_clock_s": active_wall,
        "realtime_factor": realtime_factor,
        "simulated_s": simulated,
        "total_wall_clock_s": total_wall,
    }


def parse_negative_control_diagnostic(runtime_log: str) -> str:
    match = re.search(
        r'details = "(RouteFollowingAlpaSimModel detected a frozen camera stream:[^"]+)"',
        runtime_log,
    )
    if match is None:
        raise ValueError("negative-control log does not contain the frozen-camera diagnostic")
    return match.group(1)


def package(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output
    output.mkdir(parents=True, exist_ok=True)

    driver_records = [
        record
        for record in read_jsonl(args.driver_telemetry)
        if record.get("session_uuid") == args.session_uuid
    ]
    counts = event_counts(driver_records)
    if counts != EXPECTED_SESSION_COUNTS:
        raise ValueError(f"unexpected learned-run event counts: {counts}")
    drive_records = [record for record in driver_records if record["event"] == "drive"]
    if not all(
        record.get("trajectory_finite") is True
        and record.get("latency_target_met") is True
        and record.get("trajectory_includes_current_pose") is True
        for record in drive_records
    ):
        raise ValueError("learned run contains a non-finite, late, or malformed drive output")

    video_model_records = read_jsonl(args.video_model_telemetry)
    video_model_counts = event_counts(video_model_records)
    if video_model_counts != EXPECTED_VIDEO_MODEL_COUNTS:
        raise ValueError(f"unexpected video-model event counts: {video_model_counts}")
    render_records = [
        record for record in video_model_records if record["event"] == "render_video_chunk"
    ]

    negative_records = [
        record
        for record in read_jsonl(args.negative_control_driver_telemetry)
        if record.get("session_uuid") == args.negative_control_session_uuid
    ]
    negative_counts = event_counts(negative_records)
    expected_negative_counts = {
        "close_session": 1,
        "drive": 4,
        "egomotion": 5,
        "image": 5,
        "route": 5,
        "start_session": 1,
    }
    if negative_counts != expected_negative_counts:
        raise ValueError(f"unexpected negative-control event counts: {negative_counts}")

    negative_video_model_records = read_jsonl(args.negative_control_video_model_telemetry)
    expected_negative_video_counts = {
        "close_session": 1,
        "render_video_chunk": 5,
        "server_started": 1,
        "start_session": 1,
    }
    negative_video_counts = event_counts(negative_video_model_records)
    if negative_video_counts != expected_negative_video_counts:
        raise ValueError(
            f"unexpected negative video-model event counts: {negative_video_counts}"
        )

    result_summary = json.loads((args.run_dir / "aggregate/results-summary.json").read_text())
    rollouts = result_summary["rollouts"]
    if len(rollouts) != 1 or rollouts[0]["status"] != "pass":
        raise ValueError("expected exactly one passed AlpaSim rollout")
    rollout = rollouts[0]
    if rollout["rollout_id"] != args.session_uuid:
        raise ValueError("AlpaSim rollout ID does not match driver session UUID")
    metrics = result_summary["metrics_results"][0]
    telemetry_metrics = result_summary["telemetry"]
    if telemetry_metrics["driver_drive_rpc_duration_count"] != len(drive_records):
        raise ValueError("AlpaSim and driver telemetry disagree on Drive count")

    videos = list((args.run_dir / "rollouts").glob("**/*.mp4"))
    if len(videos) != 1:
        raise ValueError(f"expected one rollout video, found {len(videos)}")

    successful_runtime_log_path = args.run_dir / "txt-logs/runtime_worker_0.log"
    successful_runtime_log = successful_runtime_log_path.read_text(encoding="utf-8")
    runtime_durations = parse_runtime_durations(successful_runtime_log)
    negative_runtime_log = args.negative_control_runtime_log.read_text(encoding="utf-8")
    negative_diagnostic = parse_negative_control_diagnostic(negative_runtime_log)
    video_metadata = probe_video(videos[0])

    output_files = {
        "camera-map.mp4": videos[0],
        "driver-telemetry.jsonl": None,
        "generated-network-config.yaml": args.run_dir / "generated-network-config.yaml",
        "generated-user-config.yaml": args.run_dir / "generated-user-config-0.yaml",
        "metrics_results.txt": args.run_dir / "aggregate/metrics_results.txt",
        "negative-control-driver-telemetry.jsonl": None,
        "negative-control-runtime.log": args.negative_control_runtime_log,
        "negative-control-video-model-telemetry.jsonl": None,
        "results-summary.json": args.run_dir / "aggregate/results-summary.json",
        "runtime.log": successful_runtime_log_path,
        "video-model-telemetry.jsonl": None,
    }
    for name, source in output_files.items():
        destination = output / name
        if source is not None:
            copy_evidence_file(source, destination)
    write_jsonl(output / "driver-telemetry.jsonl", driver_records)
    write_jsonl(output / "video-model-telemetry.jsonl", video_model_records)
    write_jsonl(output / "negative-control-driver-telemetry.jsonl", negative_records)
    write_jsonl(
        output / "negative-control-video-model-telemetry.jsonl",
        negative_video_model_records,
    )

    file_records = {
        name: {
            "bytes": (output / name).stat().st_size,
            "sha256": sha256_file(output / name),
        }
        for name in sorted(output_files)
    }
    start_record = next(
        record for record in video_model_records if record["event"] == "start_session"
    )
    first_render = render_records[0]
    last_render = render_records[-1]
    learned_latency = latency_summary(driver_records)
    behavior_metrics = {
        key: metrics[key]
        for key in (
            "collision_any",
            "dist_to_gt_location",
            "dist_to_gt_trajectory",
            "dist_traveled_m",
            "gt_dist_traveled_m",
            "offroad",
            "plan_deviation",
            "progress",
            "progress_rel",
            "wrong_lane",
        )
    }
    behavior_metrics["score"] = rollout["score"]

    manifest = {
        "schema": "wod2sim_alpasim_navsim_reactive_evidence_v1",
        "run": {
            "alpasim_commit": ALPASIM_COMMIT,
            "alpasim_runtime_image_id": ALPASIM_IMAGE_ID,
            "checkpoint": {
                "name": "NAVSIM EgoStatusMLP seed 0",
                "revision": CHECKPOINT_REVISION,
                "sha256": CHECKPOINT_SHA256,
                "url": CHECKPOINT_URL,
            },
            "model": "navsim_ego_status_mlp",
            "model_input_contract": (
                "velocity_xy+acceleration_xy+discrete_command"
            ),
            "rollout_id": rollout["rollout_id"],
            "scene_id": rollout["clipgt_id"],
            "status": rollout["status"],
            "wod2sim_commit": args.wod2sim_commit,
        },
        "fixture": {
            "alpasim_source_sha256": SOURCE_FIXTURE_SHA256,
            "alpasim_source_url": SOURCE_FIXTURE_URL,
            "derived_sha256": DERIVED_FIXTURE_SHA256,
            "derived_surface": {
                "files_added": ["mesh.ply", "mesh_ground.ply", "WOD2SIM_DERIVATION.json"],
                "geometry": "flat z=0 m rectangle x=[-100,200], y=[-100,100]",
                "recorded_payloads_changed": False,
            },
        },
        "execution": {
            "camera_events": counts["image"],
            "drive_calls": counts["drive"],
            "event_count": len(driver_records),
            "finite_drive_outputs": sum(
                record["trajectory_finite"] is True for record in drive_records
            ),
            "internal_driver_latency_ms": learned_latency,
            "latency_target_met_count": sum(
                record["latency_target_met"] is True for record in drive_records
            ),
            "latency_target_ms": 100.0,
            "renderer": {
                "camera_contract": "recorded_seed_frame_replay",
                "first_requested_xyz": first_render["first_xyz"],
                "initial_frame_sha256": start_record["initial_frame_sha256"],
                "kind": "video_model",
                "last_requested_xyz": last_render["last_xyz"],
                "render_calls": len(render_records),
            },
            "route_events": counts["route"],
            "route_geometry_consumed": False,
            "route_source": "alpasim_waypoints",
            "runtime": runtime_durations,
            "service_drive_rpc": {
                "count": telemetry_metrics["driver_drive_rpc_duration_count"],
                "mean_ms": telemetry_metrics["driver_drive_rpc_duration_mean_s"] * 1000.0,
                "sum_s": telemetry_metrics["driver_drive_rpc_duration_sum_s"],
            },
        },
        "behavior_metrics_not_used_as_policy_quality_claims": behavior_metrics,
        "media": {
            "camera_map": {
                **video_metadata,
                "content": (
                    "raw AlpaSim map, metrics, and recorded seed camera; "
                    "camera panel has no WOD2Sim text overlay"
                ),
                "path": (
                    "artifacts/external/alpasim_navsim_reactive_rollout/camera-map.mp4"
                ),
                "sha256": file_records["camera-map.mp4"]["sha256"],
            }
        },
        "negative_control": {
            "camera_events": negative_counts["image"],
            "diagnostic": negative_diagnostic,
            "drive_calls_before_rejection": negative_counts["drive"],
            "model": "route_following",
            "render_calls": negative_video_counts["render_video_chunk"],
            "result": "rejected_frozen_camera_stream",
            "session_uuid": args.negative_control_session_uuid,
        },
        "claim_boundary": {
            "supports": [
                "one-scene reactive external-driver lifecycle completion",
                "live learned-policy/controller/physics feedback for a camera-blind model",
                "service timing for this exact configuration",
                "frozen-camera rejection for a camera-validating negative control",
            ],
            "does_not_support": [
                "reactive camera rendering or visual-policy evaluation",
                "NuRec rendering quality",
                "learned-policy quality or benchmark superiority",
                "runtime overhead versus another integration",
                "human time-to-diagnosis",
                "cross-simulator transfer or population generalization",
            ],
        },
        "files": file_records,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--driver-telemetry", type=Path, required=True)
    parser.add_argument("--video-model-telemetry", type=Path, required=True)
    parser.add_argument("--negative-control-driver-telemetry", type=Path, required=True)
    parser.add_argument("--negative-control-video-model-telemetry", type=Path, required=True)
    parser.add_argument("--negative-control-runtime-log", type=Path, required=True)
    parser.add_argument("--session-uuid", required=True)
    parser.add_argument("--negative-control-session-uuid", required=True)
    parser.add_argument("--wod2sim-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = package(args)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
