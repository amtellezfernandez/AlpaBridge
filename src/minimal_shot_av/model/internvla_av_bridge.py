from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Sequence

from .rfs_metric import Trajectory
from .wod_e2e import WodE2EPreferenceFrame


WOD_FUTURE_WAYPOINTS = 20
_COORDINATE_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class InternVlaNavigationCue:
    frame_name: str
    pixel_goal: tuple[float, float] | None = None
    action: str | None = None
    stop_probability: float | None = None
    confidence: float | None = None
    latency_ms: float | None = None


def load_internvla_navigation_cues(path: str | Path) -> dict[str, InternVlaNavigationCue]:
    """Load offline InternVLA System-2 outputs keyed by WOD frame name.

    Supported inputs are JSONL rows or a JSON object/list. Pixel goals may be
    normalized, image-pixel coordinates with image size, or 0-1000 coordinates.
    """

    payloads = _load_payloads(Path(path))
    cues: dict[str, InternVlaNavigationCue] = {}
    for payload in payloads:
        cue = internvla_navigation_cue_from_payload(payload)
        cues[cue.frame_name] = cue
    return cues


def internvla_navigation_cue_from_payload(payload: dict[str, Any]) -> InternVlaNavigationCue:
    frame_name = str(payload["frame_name"])
    action = payload.get("action", payload.get("output", payload.get("decision")))
    stop_probability = payload.get("stop_probability", payload.get("stop_prob"))
    confidence = payload.get("confidence", payload.get("score"))
    latency_ms = payload.get("latency_ms")
    return InternVlaNavigationCue(
        frame_name=frame_name,
        pixel_goal=_normalized_pixel_goal(payload),
        action=None if action is None else str(action),
        stop_probability=None if stop_probability is None else float(stop_probability),
        confidence=None if confidence is None else float(confidence),
        latency_ms=None if latency_ms is None else float(latency_ms),
    )


def wod_intent_navigation_instruction(intent: int | None) -> str:
    """Map WOD route intent into the compact navigation language InternVLA expects."""

    if intent == 2:
        return "Turn left at the next safe opportunity and stay within the drivable lane."
    if intent == 3:
        return "Turn right at the next safe opportunity and stay within the drivable lane."
    if intent == 1:
        return "Continue forward in the current lane and follow the road."
    return "Proceed safely along the route while staying in the drivable lane."


def internvla_navigation_payload_from_text(
    frame_name: str,
    model_text: str,
    *,
    image_size: tuple[int, int] | None = None,
    latency_ms: float | None = None,
    confidence: float | None = None,
) -> dict[str, object]:
    """Convert an InternVLA text generation into the bridge JSONL cue format."""

    payload: dict[str, object] = {
        "frame_name": str(frame_name),
        "model_text": str(model_text),
    }
    coordinate = _coordinate_from_text(model_text)
    if coordinate is not None:
        payload["pixel_goal"] = [coordinate[0], coordinate[1]]
        if image_size is not None:
            payload["image_size"] = [int(image_size[0]), int(image_size[1])]
    else:
        action = _action_from_text(model_text)
        if action is not None:
            payload["action"] = action
    if latency_ms is not None:
        payload["latency_ms"] = float(latency_ms)
    if confidence is not None:
        payload["confidence"] = float(confidence)
    return payload


def internvla_av_candidate_payloads(
    frames: Iterable[WodE2EPreferenceFrame],
    cues_by_frame: dict[str, InternVlaNavigationCue],
    *,
    source: str = "internvla",
    profile: str = "standard",
) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for frame in frames:
        cue = cues_by_frame.get(frame.frame_name)
        if cue is None:
            continue
        for candidate_name, trajectory in internvla_av_trajectories(
            frame.past_trajectory,
            cue,
            intent=frame.intent,
            init_speed_mps=frame.init_speed_mps,
            profile=profile,
        ):
            payloads.append(
                {
                    "frame_name": frame.frame_name,
                    "source": source,
                    "candidate_name": candidate_name,
                    "candidate_index": len(payloads),
                    "trajectory_20wp_4hz": _json_trajectory(trajectory),
                    "latency_ms": cue.latency_ms,
                }
            )
    return payloads


def write_internvla_av_candidate_jsonl(
    frames: Iterable[WodE2EPreferenceFrame],
    cues_by_frame: dict[str, InternVlaNavigationCue],
    path: str | Path,
    *,
    source: str = "internvla",
    profile: str = "standard",
) -> int:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payloads = internvla_av_candidate_payloads(frames, cues_by_frame, source=source, profile=profile)
    with output_path.open("w", encoding="utf-8") as stream:
        for payload in payloads:
            stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return len(payloads)


def internvla_av_trajectories(
    past_trajectory: Sequence[tuple[float, float]],
    cue: InternVlaNavigationCue,
    *,
    intent: int | None = None,
    init_speed_mps: float | None = None,
    profile: str = "standard",
) -> list[tuple[str, Trajectory]]:
    if len(past_trajectory) < 2:
        raise ValueError("at least two past trajectory points are required")
    if profile not in {"standard", "dense"}:
        raise ValueError(f"unsupported InternVLA AV template profile: {profile!r}")
    step = _step(past_trajectory[-2], past_trajectory[-1])
    action = (cue.action or "").lower()
    trajectories: list[tuple[str, Trajectory]] = []
    if _is_stop(cue, action):
        trajectories.extend(
            [
                ("internvla_s2_stop", _decelerate_to_stop(step, stop_index=8)),
                ("internvla_s1_stop_creep", _decelerate_to_scale(step, final_scale=0.10)),
            ]
        )
        if profile == "dense":
            trajectories.append(("internvla_s1_stop_hold", _decelerate_to_scale(step, final_scale=0.0)))
    if cue.pixel_goal is not None:
        forward_m, lateral_m = _pixel_goal_to_ego_goal(
            cue.pixel_goal,
            step,
            intent=intent,
            init_speed_mps=init_speed_mps,
        )
        trajectories.extend(
            [
                (
                    "internvla_s2_pixel_goal",
                    _smooth_waypoint_path(step, forward_m=forward_m, lateral_m=lateral_m),
                ),
                (
                    "internvla_s2_pixel_goal_cautious",
                    _smooth_waypoint_path(step, forward_m=forward_m * 0.72, lateral_m=lateral_m * 0.72),
                ),
                (
                    "internvla_s1_pixel_goal_yield_track",
                    _yield_then_waypoint(step, forward_m=forward_m * 0.86, lateral_m=lateral_m, yield_steps=5),
                ),
            ]
        )
        if profile == "dense":
            trajectories.extend(
                [
                    (
                        "internvla_s2_pixel_goal_wide",
                        _smooth_waypoint_path(step, forward_m=forward_m * 1.08, lateral_m=lateral_m * 1.08),
                    ),
                    (
                        "internvla_s2_pixel_goal_narrow",
                        _smooth_waypoint_path(step, forward_m=forward_m * 0.62, lateral_m=lateral_m * 0.62),
                    ),
                ]
            )
    if "forward" in action:
        trajectories.append(
            (
                "internvla_s2_forward_track",
                _smooth_waypoint_path(
                    step,
                    forward_m=_expected_progress_5s(step, init_speed_mps) * 0.92,
                    lateral_m=_intent_lateral_prior(intent) * 0.18,
                ),
            )
        )
        if profile == "dense":
            trajectories.append(
                (
                    "internvla_s1_forward_yield",
                    _yield_then_waypoint(
                        step,
                        forward_m=_expected_progress_5s(step, init_speed_mps) * 0.86,
                        lateral_m=_intent_lateral_prior(intent) * 0.08,
                        yield_steps=6,
                    ),
                )
            )
    if "look_down" in action or "look down" in action:
        trajectories.extend(
            [
                (
                    "internvla_s2_lookdown_forward_track",
                    _smooth_waypoint_path(
                        step,
                        forward_m=_expected_progress_5s(step, init_speed_mps) * 0.92,
                        lateral_m=_intent_lateral_prior(intent) * 0.12,
                    ),
                ),
                (
                    "internvla_s2_lookdown_intent_track",
                    _smooth_waypoint_path(
                        step,
                        forward_m=_expected_progress_5s(step, init_speed_mps) * 0.78,
                        lateral_m=_intent_lateral_prior(intent) * 0.58,
                    ),
                ),
                (
                    "internvla_s2_lookdown_cautious_track",
                    _smooth_waypoint_path(
                        step,
                        forward_m=_expected_progress_5s(step, init_speed_mps) * 0.48,
                        lateral_m=_intent_lateral_prior(intent) * 0.10,
                    ),
                ),
                (
                    "internvla_s1_lookdown_yield",
                    _yield_then_waypoint(
                        step,
                        forward_m=_expected_progress_5s(step, init_speed_mps) * 0.55,
                        lateral_m=_intent_lateral_prior(intent) * 0.10,
                        yield_steps=7,
                    ),
                ),
            ]
        )
        if profile == "dense":
            trajectories.extend(
                [
                    (
                        "internvla_s2_lookdown_medium_track",
                        _smooth_waypoint_path(
                            step,
                            forward_m=_expected_progress_5s(step, init_speed_mps) * 0.66,
                            lateral_m=_intent_lateral_prior(intent) * 0.08,
                        ),
                    ),
                    (
                        "internvla_s1_lookdown_yield_long",
                        _yield_then_waypoint(
                            step,
                            forward_m=_expected_progress_5s(step, init_speed_mps) * 0.62,
                            lateral_m=_intent_lateral_prior(intent) * 0.08,
                            yield_steps=9,
                        ),
                    ),
                ]
            )
    if "left" in action:
        expected_progress = _expected_progress_5s(step, init_speed_mps)
        trajectories.extend(
            [
                (
                    "internvla_s2_view_left_track",
                    _smooth_waypoint_path(
                        step,
                        forward_m=expected_progress * 0.84,
                        lateral_m=1.35,
                    ),
                ),
                (
                    "internvla_s2_view_left_probe",
                    _smooth_waypoint_path(
                        step,
                        forward_m=expected_progress * 0.6,
                        lateral_m=2.4,
                    ),
                ),
            ]
        )
        if profile == "dense":
            trajectories.extend(
                [
                    (
                        "internvla_s2_view_left_medium_track",
                        _smooth_waypoint_path(
                            step,
                            forward_m=expected_progress * 0.72,
                            lateral_m=1.75,
                        ),
                    ),
                    (
                        "internvla_s1_view_left_yield",
                        _yield_then_waypoint(
                            step,
                            forward_m=expected_progress * 0.66,
                            lateral_m=1.60,
                            yield_steps=6,
                        ),
                    ),
                ]
            )
    if "right" in action:
        expected_progress = _expected_progress_5s(step, init_speed_mps)
        trajectories.extend(
            [
                (
                    "internvla_s2_view_right_track",
                    _smooth_waypoint_path(
                        step,
                        forward_m=expected_progress * 0.84,
                        lateral_m=-1.35,
                    ),
                ),
                (
                    "internvla_s2_view_right_probe",
                    _smooth_waypoint_path(
                        step,
                        forward_m=expected_progress * 0.6,
                        lateral_m=-2.4,
                    ),
                ),
            ]
        )
        if profile == "dense":
            trajectories.extend(
                [
                    (
                        "internvla_s2_view_right_medium_track",
                        _smooth_waypoint_path(
                            step,
                            forward_m=expected_progress * 0.72,
                            lateral_m=-1.75,
                        ),
                    ),
                    (
                        "internvla_s1_view_right_yield",
                        _yield_then_waypoint(
                            step,
                            forward_m=expected_progress * 0.66,
                            lateral_m=-1.60,
                            yield_steps=6,
                        ),
                    ),
                ]
            )
    return trajectories


def _pixel_goal_to_ego_goal(
    pixel_goal: tuple[float, float],
    step: tuple[float, float],
    *,
    intent: int | None,
    init_speed_mps: float | None,
) -> tuple[float, float]:
    u, v = pixel_goal
    expected_progress = _expected_progress_5s(step, init_speed_mps)
    far_factor = 1.0 - _clamp(v, 0.0, 1.0)
    forward_m = expected_progress * (0.42 + 0.72 * far_factor)
    lane_span = 2.6 + 2.0 * far_factor
    lateral_m = (0.5 - _clamp(u, 0.0, 1.0)) * 2.0 * lane_span
    lateral_m += _intent_lateral_prior(intent) * 0.20
    return max(0.0, forward_m), lateral_m


def _normalized_pixel_goal(payload: dict[str, Any]) -> tuple[float, float] | None:
    raw = (
        payload.get("normalized_pixel_goal")
        or payload.get("pixel_goal_normalized")
        or payload.get("pixel_goal")
        or payload.get("pixel_goal_xy")
        or payload.get("waypoint_pixel")
    )
    if raw is None:
        return None
    if isinstance(raw, dict):
        x = float(raw.get("x", raw.get("u")))
        y = float(raw.get("y", raw.get("v")))
    elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
        x = float(raw[0])
        y = float(raw[1])
    else:
        raise ValueError(f"invalid InternVLA pixel goal: {raw!r}")
    if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
        return (_clamp(x, 0.0, 1.0), _clamp(y, 0.0, 1.0))
    image_size = payload.get("image_size")
    width = payload.get("image_width")
    height = payload.get("image_height")
    if isinstance(image_size, (list, tuple)) and len(image_size) >= 2:
        width = image_size[0]
        height = image_size[1]
    if width is not None and height is not None and float(width) > 0.0 and float(height) > 0.0:
        return (_clamp(x / float(width), 0.0, 1.0), _clamp(y / float(height), 0.0, 1.0))
    scale = payload.get("coordinate_scale", payload.get("pixel_scale"))
    if scale is not None and float(scale) > 0.0:
        return (_clamp(x / float(scale), 0.0, 1.0), _clamp(y / float(scale), 0.0, 1.0))
    if max(abs(x), abs(y)) <= 1000.0:
        return (_clamp(x / 1000.0, 0.0, 1.0), _clamp(y / 1000.0, 0.0, 1.0))
    raise ValueError("InternVLA pixel goal needs normalized coordinates, image_size, or coordinate_scale")


def _load_payloads(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        payloads = []
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    payloads.append(json.loads(line))
        return payloads
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        rows = payload.get("annotations", payload.get("frames", payload.get("cues")))
        if isinstance(rows, list):
            return rows
        if "frame_name" in payload:
            return [payload]
    raise ValueError("InternVLA annotations must be a JSONL file, a JSON list, or a JSON object with annotations")


def _coordinate_from_text(model_text: str) -> tuple[float, float] | None:
    values = [float(match.group(0)) for match in _COORDINATE_RE.finditer(model_text)]
    if len(values) < 2:
        return None
    return values[0], values[1]


def _action_from_text(model_text: str) -> str | None:
    normalized = model_text.strip().lower()
    if not normalized:
        return None
    if "stop" in normalized:
        return "STOP"
    if "turn left" in normalized or normalized in {"left", "l"} or "←" in normalized:
        return "TURN_LEFT"
    if "turn right" in normalized or normalized in {"right", "r"} or "→" in normalized:
        return "TURN_RIGHT"
    if "tilt down" in normalized or "look down" in normalized or normalized == "down" or "↓" in normalized:
        return "LOOK_DOWN"
    if "forward" in normalized or normalized in {"up", "go"} or "↑" in normalized:
        return "FORWARD"
    return None


def _is_stop(cue: InternVlaNavigationCue, action: str) -> bool:
    return action.strip().upper() == "STOP" or (cue.stop_probability is not None and cue.stop_probability >= 0.5)


def _step(previous: tuple[float, float], current: tuple[float, float]) -> tuple[float, float]:
    return (float(current[0]) - float(previous[0]), float(current[1]) - float(previous[1]))


def _expected_progress_5s(step: tuple[float, float], init_speed_mps: float | None) -> float:
    if init_speed_mps is not None:
        return max(0.0, float(init_speed_mps) * 5.0)
    return math.hypot(step[0], step[1]) * WOD_FUTURE_WAYPOINTS


def _basis(step: tuple[float, float]) -> tuple[tuple[float, float], tuple[float, float]]:
    norm = math.hypot(step[0], step[1])
    if norm <= 1e-9:
        return (1.0, 0.0), (0.0, 1.0)
    forward = (step[0] / norm, step[1] / norm)
    lateral = (-forward[1], forward[0])
    return forward, lateral


def _intent_lateral_prior(intent: int | None) -> float:
    if intent == 2:
        return 3.0
    if intent == 3:
        return -3.0
    return 0.0


def _smooth_waypoint_path(step: tuple[float, float], *, forward_m: float, lateral_m: float) -> Trajectory:
    forward, lateral = _basis(step)
    trajectory: Trajectory = []
    for index in range(1, WOD_FUTURE_WAYPOINTS + 1):
        progress = _smoothstep(index / WOD_FUTURE_WAYPOINTS)
        trajectory.append(
            (
                forward[0] * forward_m * progress + lateral[0] * lateral_m * progress,
                forward[1] * forward_m * progress + lateral[1] * lateral_m * progress,
            )
        )
    return trajectory


def _yield_then_waypoint(
    step: tuple[float, float],
    *,
    forward_m: float,
    lateral_m: float,
    yield_steps: int,
) -> Trajectory:
    forward, lateral = _basis(step)
    slow_steps = max(1, min(WOD_FUTURE_WAYPOINTS - 1, int(yield_steps)))
    trajectory: Trajectory = []
    for index in range(1, WOD_FUTURE_WAYPOINTS + 1):
        ratio = index / WOD_FUTURE_WAYPOINTS
        if index <= slow_steps:
            progress = _smoothstep(ratio) * 0.35
        else:
            progress = 0.35 * _smoothstep(slow_steps / WOD_FUTURE_WAYPOINTS) + (
                1.0 - 0.35 * _smoothstep(slow_steps / WOD_FUTURE_WAYPOINTS)
            ) * _smoothstep((index - slow_steps) / (WOD_FUTURE_WAYPOINTS - slow_steps))
        trajectory.append(
            (
                forward[0] * forward_m * progress + lateral[0] * lateral_m * progress,
                forward[1] * forward_m * progress + lateral[1] * lateral_m * progress,
            )
        )
    return trajectory


def _decelerate_to_stop(step: tuple[float, float], *, stop_index: int) -> Trajectory:
    stop = max(1, min(WOD_FUTURE_WAYPOINTS, int(stop_index)))
    trajectory: Trajectory = []
    x = 0.0
    y = 0.0
    for index in range(1, WOD_FUTURE_WAYPOINTS + 1):
        scale = max(0.0, 1.0 - (index - 1) / stop)
        x += step[0] * scale
        y += step[1] * scale
        trajectory.append((x, y))
    return trajectory


def _decelerate_to_scale(step: tuple[float, float], *, final_scale: float) -> Trajectory:
    trajectory: Trajectory = []
    x = 0.0
    y = 0.0
    denominator = max(1, WOD_FUTURE_WAYPOINTS - 1)
    for index in range(WOD_FUTURE_WAYPOINTS):
        ratio = index / denominator
        scale = (1.0 - ratio) + max(0.0, final_scale) * ratio
        x += step[0] * scale
        y += step[1] * scale
        trajectory.append((x, y))
    return trajectory


def _smoothstep(value: float) -> float:
    ratio = _clamp(value, 0.0, 1.0)
    return ratio * ratio * (3.0 - 2.0 * ratio)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def _json_trajectory(trajectory: Trajectory) -> list[list[float]]:
    return [[float(x), float(y)] for x, y in trajectory]
