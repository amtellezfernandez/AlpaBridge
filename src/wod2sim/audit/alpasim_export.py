from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from wod2sim.neutral.alpasim_metrics import build_alpasim_evidence
from wod2sim.simulator.alpasim_signal import scenario_from_command
from wod2sim.simulator.environment import route_centerline


def export_alpasim_audit_log(run_dir: Path, output_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    launch_metadata = _load_json_if_exists(run_dir / "launch-metadata.json")
    spotlight_rows = _load_jsonl_if_exists(run_dir / "driver" / "spotlight-log.jsonl")
    selection_rows = _load_jsonl_if_exists(run_dir / "driver" / "selection-log.jsonl")
    direct_rows = _load_jsonl_if_exists(run_dir / "driver" / "direct-planner-log.jsonl")
    controller_rows = _load_controller_rows(run_dir / "controller")
    frames = _build_alpasim_frames(spotlight_rows, selection_rows, direct_rows, controller_rows)
    metrics_evidence = _safe_metrics_evidence(run_dir)

    manifest = {
        "format_version": 1,
        "source": "alpasim",
        "model": launch_metadata.get("model"),
        "scene_preset": launch_metadata.get("scene_preset"),
        "scene_ids": launch_metadata.get("scene_ids", []),
        "frame_count": len(frames),
        "files": {
            "manifest": "manifest.json",
            "frames": "frames.jsonl",
            "launch_metadata": "launch_metadata.json",
            "metrics_evidence": "metrics_evidence.json",
        },
    }

    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (output_dir / "launch_metadata.json").write_text(json.dumps(launch_metadata, indent=2))
    (output_dir / "metrics_evidence.json").write_text(json.dumps(metrics_evidence, indent=2))
    with (output_dir / "frames.jsonl").open("w", encoding="utf-8") as handle:
        for frame in frames:
            handle.write(json.dumps(frame) + "\n")
    return manifest


def _build_alpasim_frames(
    spotlight_rows: list[dict[str, Any]],
    selection_rows: list[dict[str, Any]],
    direct_rows: list[dict[str, Any]],
    controller_rows: list[dict[str, float | int]],
) -> list[dict[str, Any]]:
    if direct_rows:
        return [_frame_from_direct_row(row, controller_rows) for row in direct_rows]
    if selection_rows:
        return [_frame_from_selection_row(row, controller_rows) for row in selection_rows]
    if spotlight_rows:
        return [_frame_from_spotlight_row(row, controller_rows) for row in spotlight_rows]
    return []


def _frame_from_selection_row(row: dict[str, Any], controller_rows: list[dict[str, float | int]]) -> dict[str, Any]:
    command = str(row.get("command", "straight"))
    signal = row.get("alpasim_signal", {}) if isinstance(row.get("alpasim_signal"), dict) else {}
    scenario = scenario_from_command(command, signal)
    controller_row = _nearest_controller_row(controller_rows, _signal_timestamp_us(signal))
    ego_x, ego_y, ego_speed = _ego_state_from_sources(controller_row, signal, scenario)
    return {
        "frame_idx": int(row.get("frame_index", 0)),
        "timestamp_s": round((int(row.get("frame_index", 0)) - 1) * 0.25, 3),
        "ego": {
            "x": ego_x,
            "y": ego_y,
            "speed": ego_speed if ego_speed is not None else float(row.get("speed_mps", 0.0)),
        },
        "route": {
            "start": list(scenario.start),
            "goal": list(scenario.goal),
            "lane_center": [list(point) for point in scenario.lane_center],
            "route_center": [list(point) for point in route_centerline(scenario)],
            "lane_half_width": float(scenario.lane_half_width),
        },
        "actors": [row_actor for row_actor in signal.get("structured_hazards", []) if _is_moving_hazard(row_actor)],
        "active_obstacles": [row_actor for row_actor in signal.get("structured_hazards", []) if not _is_moving_hazard(row_actor)],
        "media": _media_refs_from_row(row, signal),
        "step": {
            "action_mode": str(row.get("hybrid_token", row.get("spotlight_token", ""))),
            "decision_type": row.get("decision_type"),
            "collision_risk": float(signal.get("dynamics_risk", 0.0) or 0.0),
            "lane_error": 0.0,
            "min_obstacle_distance": float(row.get("dagger_argmax_geo_gap", 0.0) or 0.0),
            "selected_maneuver": row.get("hybrid_token"),
        },
        "planner": {
            "selection_mode": row.get("selection_mode"),
            "trajectory_mode": row.get("trajectory_mode"),
            "top_logits": row.get("top_logits", []),
            "selection_trace": {k: v for k, v in row.items() if k not in {"alpasim_signal", "top_logits", "spotlight_top_candidates"}},
            "spotlight_top_candidates": row.get("spotlight_top_candidates", []),
        },
        "controller": controller_row,
        "trigger_state": {
            "sensor_freshness": row.get("sensor_freshness"),
            "sensor_error": row.get("sensor_error"),
            "result": row.get("result"),
        },
        "signal": signal,
    }


def _frame_from_direct_row(row: dict[str, Any], controller_rows: list[dict[str, float | int]]) -> dict[str, Any]:
    command = str(row.get("command", "straight"))
    signal = row.get("alpasim_signal", {}) if isinstance(row.get("alpasim_signal"), dict) else {}
    scenario = scenario_from_command(command, signal)
    plan = row.get("plan", {}) if isinstance(row.get("plan"), dict) else {}
    controller_row = _nearest_controller_row(controller_rows, _signal_timestamp_us(signal))
    ego_x, ego_y, ego_speed = _ego_state_from_sources(controller_row, signal, scenario)
    return {
        "frame_idx": int(row.get("frame_index", 0)),
        "timestamp_s": round((int(row.get("frame_index", 0)) - 1) * 0.25, 3),
        "ego": {
            "x": ego_x,
            "y": ego_y,
            "speed": ego_speed if ego_speed is not None else float(row.get("speed_mps", 0.0)),
        },
        "route": {
            "start": list(scenario.start),
            "goal": list(scenario.goal),
            "lane_center": [list(point) for point in scenario.lane_center],
            "route_center": [list(point) for point in route_centerline(scenario)],
            "lane_half_width": float(scenario.lane_half_width),
        },
        "actors": [row_actor for row_actor in signal.get("structured_hazards", []) if _is_moving_hazard(row_actor)],
        "active_obstacles": [row_actor for row_actor in signal.get("structured_hazards", []) if not _is_moving_hazard(row_actor)],
        "media": _media_refs_from_row(row, signal),
        "step": {
            "action_mode": "direct_actor_planner",
            "collision_risk": float(signal.get("dynamics_risk", 0.0) or 0.0),
            "lane_error": 0.0,
            "min_obstacle_distance": float(plan.get("min_clearance_m", 0.0) or 0.0),
            "selected_maneuver": "direct_plan",
        },
        "planner": {
            "planner": row.get("planner"),
            "latency_ms": row.get("planner_latency_ms"),
            "plan": plan,
        },
        "controller": controller_row,
        "trigger_state": {
            "sensor_freshness": row.get("sensor_freshness"),
            "sensor_error": row.get("sensor_error"),
            "result": row.get("result"),
        },
        "signal": signal,
    }


def _frame_from_spotlight_row(row: dict[str, Any], controller_rows: list[dict[str, float | int]]) -> dict[str, Any]:
    command = str(row.get("command", "straight"))
    signal = row.get("alpasim_signal", {}) if isinstance(row.get("alpasim_signal"), dict) else {}
    scenario = scenario_from_command(command, signal)
    controller_row = _nearest_controller_row(controller_rows, _signal_timestamp_us(signal))
    ego_x, ego_y, ego_speed = _ego_state_from_sources(controller_row, signal, scenario)
    return {
        "frame_idx": int(row.get("frame_index", 0)),
        "timestamp_s": round((int(row.get("frame_index", 0)) - 1) * 0.25, 3),
        "ego": {
            "x": ego_x,
            "y": ego_y,
            "speed": ego_speed if ego_speed is not None else float(row.get("speed_mps", 0.0)),
        },
        "route": {
            "start": list(scenario.start),
            "goal": list(scenario.goal),
            "lane_center": [list(point) for point in scenario.lane_center],
            "route_center": [list(point) for point in route_centerline(scenario)],
            "lane_half_width": float(scenario.lane_half_width),
        },
        "actors": [row_actor for row_actor in signal.get("structured_hazards", []) if _is_moving_hazard(row_actor)],
        "active_obstacles": [
            row_actor for row_actor in signal.get("structured_hazards", []) if not _is_moving_hazard(row_actor)
        ],
        "media": _media_refs_from_row(row, signal),
        "step": {
            "action_mode": str(row.get("selected_maneuver", "")),
            "decision_type": row.get("decision_reason"),
            "collision_risk": float(signal.get("dynamics_risk", 0.0) or 0.0),
            "lane_error": 0.0,
            "min_obstacle_distance": 0.0,
            "selected_maneuver": row.get("selected_maneuver"),
        },
        "planner": {
            "planner": "spotlight_reflex",
            "candidate_count": row.get("candidate_count"),
            "reference_count": row.get("reference_count"),
            "top_candidate_summaries": row.get("top_candidate_summaries", []),
        },
        "controller": controller_row,
        "trigger_state": {
            "sensor_freshness": row.get("sensor_freshness"),
            "sensor_error": row.get("sensor_error"),
            "result": row.get("result"),
        },
        "signal": signal,
    }


def _safe_metrics_evidence(run_dir: Path) -> dict[str, Any]:
    try:
        return build_alpasim_evidence(run_dir).to_dict()
    except Exception as exc:
        return {"source": "alpasim", "error": str(exc)}


def _load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _load_jsonl_if_exists(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _is_moving_hazard(hazard: dict[str, Any]) -> bool:
    vx = float(hazard.get("vx", 0.0) or 0.0)
    vy = float(hazard.get("vy", 0.0) or 0.0)
    return abs(vx) > 1e-6 or abs(vy) > 1e-6


def _load_controller_rows(controller_dir: Path) -> list[dict[str, float | int]]:
    csv_paths = sorted(controller_dir.glob("*.csv"))
    if not csv_paths:
        return []
    rows: list[dict[str, float | int]] = []
    with csv_paths[0].open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for item in reader:
            timestamp = item.get("timestamp_us")
            if timestamp is None:
                continue
            qx = _as_float(item.get("qx"), default=0.0)
            qy = _as_float(item.get("qy"), default=0.0)
            qz = _as_float(item.get("qz"), default=0.0)
            qw = _as_float(item.get("qw"), default=1.0)
            yaw = math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))
            rows.append(
                {
                    "timestamp_us": int(float(timestamp)),
                    "world_x": _as_float(item.get("x"), default=0.0),
                    "world_y": _as_float(item.get("y"), default=0.0),
                    "world_heading": yaw,
                    "world_vx": _as_float(item.get("vx"), default=0.0),
                    "world_vy": _as_float(item.get("vy"), default=0.0),
                }
            )
    rows.sort(key=lambda row: int(row["timestamp_us"]))
    return rows


def _nearest_controller_row(rows: list[dict[str, float | int]], timestamp_us: int | None) -> dict[str, float | int] | None:
    if timestamp_us is None or not rows:
        return None
    return min(rows, key=lambda row: abs(int(row["timestamp_us"]) - int(timestamp_us)))


def _signal_timestamp_us(signal: dict[str, Any]) -> int | None:
    for key in ("oracle_actor_proxy_timestamp_us", "oracle_actor_proxy_matched_timestamp_us"):
        value = signal.get(key)
        if value is not None:
            return int(value)
    return None


def _ego_state_from_sources(
    controller_row: dict[str, float | int] | None,
    signal: dict[str, Any],
    scenario: Any,
) -> tuple[float, float, float | None]:
    if controller_row is not None:
        vx = float(controller_row.get("world_vx", 0.0))
        vy = float(controller_row.get("world_vy", 0.0))
        return (
            float(controller_row["world_x"]),
            float(controller_row["world_y"]),
            math.hypot(vx, vy),
        )
    ego_pose = signal.get("oracle_actor_proxy_current_ego_pose") if isinstance(signal.get("oracle_actor_proxy_current_ego_pose"), dict) else {}
    if ego_pose:
        x = float(ego_pose.get("world_x", scenario.start[0]))
        y = float(ego_pose.get("world_y", scenario.start[1]))
        vx = float(ego_pose.get("world_vx", 0.0) or 0.0)
        vy = float(ego_pose.get("world_vy", 0.0) or 0.0)
        return (x, y, math.hypot(vx, vy) if vx or vy else None)
    return (float(scenario.start[0]), float(scenario.start[1]), None)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _media_refs_from_row(row: dict[str, Any], signal: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    _append_media_ref(refs, seen, source="row", payload=row)
    _append_media_ref(refs, seen, source="signal", payload=signal)
    return refs


def _append_media_ref(
    refs: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    *,
    source: str,
    payload: dict[str, Any],
) -> None:
    for key, value in payload.items():
        lowered = str(key).lower()
        if not any(token in lowered for token in ("image", "frame", "camera")):
            continue
        if not any(token in lowered for token in ("path", "file", "uri", "jpg", "jpeg", "png")):
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        media_type = "image"
        if lowered.endswith("_uri"):
            media_type = "uri"
        dedupe_key = (media_type, value)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        refs.append({"source": source, "kind": media_type, "label": str(key), "path": value})
