from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .review import as_float, bookmarks_for_frame, frame_bookmarks, severity_policy


def load_audit_log(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads((root / "manifest.json").read_text())
    frames: list[dict[str, Any]] = []
    with (root / "frames.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                frames.append(json.loads(line))
    return manifest, frames


def summarize_audit_log(root: Path) -> dict[str, Any]:
    manifest, frames = load_audit_log(root)
    bookmarks = frame_bookmarks(frames, manifest=manifest)
    return {
        "manifest": manifest,
        "severity_policy": severity_policy(manifest),
        "frame_count": len(frames),
        "media_frame_count": sum(1 for frame in frames if frame.get("media")),
        "bookmark_count": len(bookmarks),
        "bookmark_index": bookmarks,
    }


def view_audit_log_with_rerun(root: Path, *, spawn: bool = False) -> dict[str, Any]:
    manifest, frames = load_audit_log(root)
    try:
        import rerun as rr
    except ImportError as exc:  # pragma: no cover - depends on optional package.
        raise RuntimeError("rerun is not installed; install with `pip install rerun-sdk`") from exc

    rr.init(f"wod2sim:{manifest['scenario_cluster']}", spawn=spawn)
    if frames:
        first = frames[0]
        lane_center = first["route"]["lane_center"]
        rr.log("world/route/center", rr.LineStrips2D([lane_center]))
        rr.log("world/route/start", rr.Points2D([first["route"]["start"]], colors=[[0, 150, 150]], radii=[6.0]))
        rr.log("world/route/goal", rr.Points2D([first["route"]["goal"]], colors=[[238, 155, 0]], radii=[6.0]))

    for frame in frames:
        rr.set_time_sequence("frame", int(frame["frame_idx"]))
        rr.set_time_seconds("sim_time", float(frame["timestamp_s"]))
        ego = frame["ego"]
        rr.log("world/ego", rr.Points2D([[ego["x"], ego["y"]]], colors=[[0, 95, 115]], radii=[5.0]))
        if frame["active_obstacles"]:
            rr.log(
                "world/obstacles",
                rr.Points2D(
                    [[item["x"], item["y"]] for item in frame["active_obstacles"]],
                    colors=[[163, 61, 43] for _ in frame["active_obstacles"]],
                    radii=[max(2.0, float(item["radius"]) * 3.0) for item in frame["active_obstacles"]],
                ),
            )
        step = frame["step"]
        rr.log("metrics/min_clearance", rr.Scalars([float(step.get("min_obstacle_distance", 0.0))]))
        rr.log("metrics/collision_risk", rr.Scalars([float(step.get("collision_risk", 0.0))]))
        rr.log("metrics/lane_error", rr.Scalars([float(step.get("lane_error", 0.0))]))
        rr.log("planner/action_mode", rr.TextLog(str(step.get("action_mode", ""))))
        for bookmark in bookmarks_for_frame(frame, manifest=manifest):
            rr.log("events/bookmarks", rr.TextLog(f"{bookmark['kind']}: {json.dumps(bookmark['detail'], sort_keys=True)}"))
        _log_frame_media(rr, root, frame)
    return manifest


def _log_frame_media(rr, audit_root: Path, frame: dict[str, Any]) -> None:  # pragma: no cover - depends on optional packages.
    media_refs = frame.get("media", [])
    if not isinstance(media_refs, list):
        return
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return
    for item in media_refs:
        if not isinstance(item, dict):
            continue
        path_value = item.get("path")
        if not isinstance(path_value, str) or not path_value:
            continue
        media_path = Path(path_value)
        if not media_path.is_absolute():
            media_path = audit_root / media_path
        if not media_path.is_file():
            continue
        try:
            with Image.open(media_path) as image:
                rgb = image.convert("RGB")
                rr.log(f"media/{item.get('label', 'frame')}", rr.Image(np.asarray(rgb)))
        except Exception:
            continue
