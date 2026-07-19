from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

EXPECTED_TRAJECTORY_POINTS = 50
MAX_IMAGE_AGE_US = 100_000

FAULT_CODES = (
    "semantic.route_missing",
    "semantic.command_only",
    "semantic.road_center_reference",
    "temporal.stale_observation",
    "temporal.invalid_sample_count",
    "temporal.nan_trajectory",
    "lifecycle.duplicate_close",
    "lifecycle.late_image",
    "lifecycle.late_route",
    "plugin.optional_backend_missing",
    "deployment.docker_unavailable",
    "deployment.gpu_runtime_unavailable",
    "deployment.scene_artifact_missing",
    "evidence.manifest_missing",
    "evidence.hash_mismatch",
)

DEFAULT_CONTEXT: dict[str, bool] = {
    "completed": True,
    "metrics_present": True,
    "plugin_available": True,
    "docker_available": True,
    "gpu_runtime_available": True,
    "scene_artifact_available": True,
    "manifest_present": True,
    "manifest_hash_matches": True,
}


@dataclass(frozen=True)
class ContractDiagnostic:
    layer: str
    code: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"layer": self.layer, "code": self.code, "detail": self.detail}


def load_telemetry_trace(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number}: telemetry row must be a JSON object")
        rows.append(payload)
    if not rows:
        raise ValueError(f"{path}: telemetry trace is empty")
    return rows


def status_only_accepts(context: Mapping[str, Any]) -> bool:
    return context.get("completed") is True and context.get("metrics_present") is True


def diagnose_contract_trace(
    events: Sequence[Mapping[str, Any]],
    *,
    context: Mapping[str, Any] | None = None,
) -> list[ContractDiagnostic]:
    state = {**DEFAULT_CONTEXT, **dict(context or {})}
    detected: dict[str, ContractDiagnostic] = {}

    route_events = [event for event in events if event.get("event") == "route"]
    drive_events = [event for event in events if event.get("event") == "drive"]
    if not route_events:
        _record(
            detected,
            "semantic.route_missing",
            "No route event was retained before policy execution.",
        )
    else:
        route_sources = {
            str(event.get("route_source", "") or "")
            for event in (*route_events, *drive_events)
            if event.get("route_source") not in (None, "")
        }
        if "command_proxy" in route_sources:
            _record(
                detected,
                "semantic.command_only",
                "A high-level command proxy replaced route geometry.",
            )
        if "road_center_reference" in route_sources:
            _record(
                detected,
                "semantic.road_center_reference",
                "A road-center reference was presented as policy route geometry.",
            )

    latest_image_timestamp: dict[str, int] = {}
    started_sessions: set[str] = set()
    closed_sessions: set[str] = set()
    for event in events:
        event_name = str(event.get("event", "") or "")
        session_uuid = str(event.get("session_uuid", "") or "")
        if event_name == "start_session":
            if session_uuid:
                started_sessions.add(session_uuid)
            continue
        if event_name == "close_session":
            if session_uuid in closed_sessions:
                _record(
                    detected,
                    "lifecycle.duplicate_close",
                    f"Session {session_uuid or '<missing>'} was closed more than once.",
                )
            if session_uuid:
                closed_sessions.add(session_uuid)
            continue
        if session_uuid in closed_sessions and event_name == "image":
            _record(
                detected,
                "lifecycle.late_image",
                f"An image arrived after session {session_uuid} closed.",
            )
        if session_uuid in closed_sessions and event_name == "route":
            _record(
                detected,
                "lifecycle.late_route",
                f"A route update arrived after session {session_uuid} closed.",
            )
        if event_name == "image":
            timestamp = _as_int(event.get("timestamp_us"))
            if timestamp is not None:
                latest_image_timestamp[session_uuid] = max(
                    timestamp,
                    latest_image_timestamp.get(session_uuid, timestamp),
                )
        if event_name != "drive":
            continue

        time_now_us = _as_int(event.get("time_now_us"))
        image_timestamp_us = latest_image_timestamp.get(session_uuid)
        if (
            time_now_us is not None
            and image_timestamp_us is not None
            and time_now_us - image_timestamp_us > MAX_IMAGE_AGE_US
        ):
            _record(
                detected,
                "temporal.stale_observation",
                (
                    f"Drive input lag was {time_now_us - image_timestamp_us} us, above "
                    f"the {MAX_IMAGE_AGE_US} us contract."
                ),
            )

        trajectory_points = _as_int(event.get("trajectory_points"))
        if (
            trajectory_points is not None
            and trajectory_points != EXPECTED_TRAJECTORY_POINTS
        ):
            _record(
                detected,
                "temporal.invalid_sample_count",
                (
                    f"Trajectory contained {trajectory_points} points; "
                    f"{EXPECTED_TRAJECTORY_POINTS} were required."
                ),
            )
        trajectory_finite = event.get("trajectory_finite", True)
        if trajectory_finite is not True:
            _record(
                detected,
                "temporal.nan_trajectory",
                "Trajectory telemetry reports a non-finite output.",
            )

    if events and not started_sessions:
        _record(
            detected,
            "evidence.manifest_missing",
            "The trace contains events without a retained session start.",
        )
    if state["plugin_available"] is not True:
        _record(
            detected,
            "plugin.optional_backend_missing",
            "The configured model entry point cannot load its optional backend.",
        )
    if state["docker_available"] is not True:
        _record(
            detected,
            "deployment.docker_unavailable",
            "The required container runtime is unavailable.",
        )
    if state["gpu_runtime_available"] is not True:
        _record(
            detected,
            "deployment.gpu_runtime_unavailable",
            "The required GPU runtime is unavailable.",
        )
    if state["scene_artifact_available"] is not True:
        _record(
            detected,
            "deployment.scene_artifact_missing",
            "The configured scene artifact is unavailable.",
        )
    if state["manifest_present"] is not True:
        _record(
            detected,
            "evidence.manifest_missing",
            "The run manifest is unavailable.",
        )
    elif state["manifest_hash_matches"] is not True:
        _record(
            detected,
            "evidence.hash_mismatch",
            "The retained artifact hash does not match the manifest.",
        )

    order = {code: index for index, code in enumerate(FAULT_CODES)}
    return sorted(detected.values(), key=lambda item: order[item.code])


def mutate_trace(
    events: Sequence[Mapping[str, Any]],
    fault_code: str,
) -> tuple[list[dict[str, Any]], dict[str, bool]]:
    if fault_code not in FAULT_CODES:
        raise ValueError(f"unsupported fault mutation: {fault_code}")
    mutated = copy.deepcopy([dict(event) for event in events])
    context = dict(DEFAULT_CONTEXT)

    if fault_code == "semantic.route_missing":
        mutated = [event for event in mutated if event.get("event") != "route"]
        for event in mutated:
            if event.get("event") == "drive":
                event.pop("route_source", None)
                event.pop("route_waypoint_count", None)
    elif fault_code == "semantic.command_only":
        _set_route_source(mutated, source="command_proxy", waypoint_count=0)
    elif fault_code == "semantic.road_center_reference":
        _set_route_source(mutated, source="road_center_reference", waypoint_count=10)
    elif fault_code == "temporal.stale_observation":
        for event in mutated:
            if event.get("event") == "image" and _as_int(event.get("timestamp_us")) is not None:
                event["timestamp_us"] = int(event["timestamp_us"]) - 1_000_000
    elif fault_code == "temporal.invalid_sample_count":
        _first_event(mutated, "drive")["trajectory_points"] = EXPECTED_TRAJECTORY_POINTS - 1
    elif fault_code == "temporal.nan_trajectory":
        _first_event(mutated, "drive")["trajectory_finite"] = False
    elif fault_code == "lifecycle.duplicate_close":
        mutated.append(copy.deepcopy(_last_event(mutated, "close_session")))
    elif fault_code == "lifecycle.late_image":
        late = copy.deepcopy(_last_event(mutated, "image"))
        mutated.append(late)
    elif fault_code == "lifecycle.late_route":
        late = copy.deepcopy(_last_event(mutated, "route"))
        mutated.append(late)
    elif fault_code == "plugin.optional_backend_missing":
        context["plugin_available"] = False
    elif fault_code == "deployment.docker_unavailable":
        context["docker_available"] = False
    elif fault_code == "deployment.gpu_runtime_unavailable":
        context["gpu_runtime_available"] = False
    elif fault_code == "deployment.scene_artifact_missing":
        context["scene_artifact_available"] = False
    elif fault_code == "evidence.manifest_missing":
        context["manifest_present"] = False
    elif fault_code == "evidence.hash_mismatch":
        context["manifest_hash_matches"] = False
    return mutated, context


def build_control_traces(
    events: Sequence[Mapping[str, Any]],
    *,
    count: int = 15,
) -> list[list[dict[str, Any]]]:
    if count < 1:
        raise ValueError("control trace count must be positive")
    drive_indices = [
        index for index, event in enumerate(events) if event.get("event") == "drive"
    ]
    if len(drive_indices) < count:
        raise ValueError(
            f"trace has {len(drive_indices)} drive events, fewer than {count} controls"
        )
    start_counts = [
        max(1, round(1 + index * (len(drive_indices) - 1) / max(1, count - 1)))
        for index in range(count)
    ]
    close_event = copy.deepcopy(_last_event(events, "close_session"))
    controls: list[list[dict[str, Any]]] = []
    for drive_count in start_counts:
        end_index = drive_indices[drive_count - 1]
        prefix = copy.deepcopy([dict(event) for event in events[: end_index + 1]])
        prefix.append(copy.deepcopy(close_event))
        controls.append(prefix)
    return controls


def trace_runtime_summary(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    latencies = [
        float(event["latency_ms"])
        for event in events
        if event.get("event") == "drive"
        and isinstance(event.get("latency_ms"), (int, float))
        and math.isfinite(float(event["latency_ms"]))
    ]
    targets = [
        float(event["latency_target_ms"])
        for event in events
        if event.get("event") == "drive"
        and isinstance(event.get("latency_target_ms"), (int, float))
    ]
    target = targets[0] if targets else None
    return {
        "event_count": len(events),
        "drive_count": len(latencies),
        "latency_target_ms": target,
        "latency_target_met_count": (
            sum(latency <= target for latency in latencies) if target is not None else 0
        ),
        "latency_ms": {
            "mean": sum(latencies) / len(latencies) if latencies else None,
            "p50": _percentile(latencies, 50.0),
            "p95": _percentile(latencies, 95.0),
            "max": max(latencies) if latencies else None,
        },
    }


def _record(detected: dict[str, ContractDiagnostic], code: str, detail: str) -> None:
    detected.setdefault(
        code,
        ContractDiagnostic(layer=code.split(".", 1)[0], code=code, detail=detail),
    )


def _set_route_source(
    events: list[dict[str, Any]],
    *,
    source: str,
    waypoint_count: int,
) -> None:
    for event in events:
        if event.get("event") in {"route", "drive"}:
            event["route_source"] = source
            event["route_waypoint_count"] = waypoint_count


def _first_event(events: Sequence[dict[str, Any]], event_name: str) -> dict[str, Any]:
    for event in events:
        if event.get("event") == event_name:
            return event
    raise ValueError(f"trace has no {event_name} event")


def _last_event(
    events: Sequence[Mapping[str, Any]],
    event_name: str,
) -> Mapping[str, Any]:
    for event in reversed(events):
        if event.get("event") == event_name:
            return event
    raise ValueError(f"trace has no {event_name} event")


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * percentile / 100.0
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    alpha = position - lower
    return ordered[lower] * (1.0 - alpha) + ordered[upper] * alpha
