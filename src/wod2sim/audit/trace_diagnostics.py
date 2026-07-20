from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

EXPECTED_TRAJECTORY_POINTS = 50
MAX_IMAGE_AGE_US = 100_000
SUPPORTED_TELEMETRY_SCHEMAS = {
    "wod2sim_challenge_telemetry_v1",
    "wod2sim_challenge_telemetry_v2",
    "wod2sim_challenge_telemetry_v3",
}
CURRENT_TELEMETRY_SCHEMA = "wod2sim_challenge_telemetry_v3"
KNOWN_TELEMETRY_EVENTS = {
    "start_session",
    "image",
    "egomotion",
    "route",
    "drive",
    "close_session",
}

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

DIAGNOSTIC_CODES = (
    "semantic.route_missing",
    "semantic.command_only",
    "semantic.road_center_reference",
    "temporal.missing_observation",
    "temporal.stale_observation",
    "temporal.future_observation",
    "temporal.invalid_sample_count",
    "temporal.nan_trajectory",
    "lifecycle.session_not_started",
    "lifecycle.duplicate_start",
    "lifecycle.duplicate_close",
    "lifecycle.late_image",
    "lifecycle.late_route",
    "lifecycle.late_drive",
    "lifecycle.session_not_closed",
    "plugin.optional_backend_missing",
    "deployment.docker_unavailable",
    "deployment.gpu_runtime_unavailable",
    "deployment.scene_artifact_missing",
    "evidence.telemetry_incomplete",
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

    latest_image_timestamp: dict[str, int] = {}
    started_sessions: set[str] = set()
    active_sessions: set[str] = set()
    closed_sessions: set[str] = set()
    sessions_with_route: set[str] = set()
    for event in events:
        event_name = str(event.get("event", "") or "")
        session_uuid = str(event.get("session_uuid", "") or "")
        schema = str(event.get("schema", "") or "")
        if schema not in SUPPORTED_TELEMETRY_SCHEMAS:
            _record(
                detected,
                "evidence.telemetry_incomplete",
                f"Telemetry row has unsupported or missing schema {schema or '<missing>'}.",
            )
        if not event_name or not session_uuid:
            _record(
                detected,
                "evidence.telemetry_incomplete",
                "Telemetry rows must retain both event and session_uuid fields.",
            )
            continue
        if event_name not in KNOWN_TELEMETRY_EVENTS:
            _record(
                detected,
                "evidence.telemetry_incomplete",
                f"Telemetry row has unknown event {event_name}.",
            )
            continue

        if event_name == "start_session":
            if session_uuid in started_sessions:
                _record(
                    detected,
                    "lifecycle.duplicate_start",
                    f"Session {session_uuid} was started more than once.",
                )
            started_sessions.add(session_uuid)
            active_sessions.add(session_uuid)
            continue

        if session_uuid not in started_sessions:
            _record(
                detected,
                "lifecycle.session_not_started",
                f"Event {event_name} references session {session_uuid} before its start.",
            )

        if event_name == "close_session":
            if session_uuid in closed_sessions:
                _record(
                    detected,
                    "lifecycle.duplicate_close",
                    f"Session {session_uuid or '<missing>'} was closed more than once.",
                )
            active_sessions.discard(session_uuid)
            closed_sessions.add(session_uuid)
            continue

        if session_uuid in closed_sessions:
            late_codes = {
                "image": "lifecycle.late_image",
                "route": "lifecycle.late_route",
                "drive": "lifecycle.late_drive",
            }
            late_code = late_codes.get(event_name)
            if late_code:
                _record(
                    detected,
                    late_code,
                    f"An {event_name} event arrived after session {session_uuid} closed.",
                )
            continue

        if event_name == "route":
            sessions_with_route.add(session_uuid)
            _diagnose_route_source(event, detected)
            continue

        if event_name == "image":
            timestamp = _as_int(event.get("timestamp_us"))
            if timestamp is None:
                _record(
                    detected,
                    "evidence.telemetry_incomplete",
                    f"Image telemetry for session {session_uuid} lacks an integer timestamp.",
                )
            else:
                latest_image_timestamp[session_uuid] = timestamp
            continue

        if event_name != "drive":
            continue

        _diagnose_route_source(event, detected)
        if (
            session_uuid not in sessions_with_route
            and event.get("route_geometry_required") is not False
        ):
            _record(
                detected,
                "semantic.route_missing",
                f"Session {session_uuid} reached Drive before retaining a route event.",
            )

        time_now_us = _as_int(event.get("time_now_us"))
        image_timestamp_us = latest_image_timestamp.get(session_uuid)
        if time_now_us is None:
            _record(
                detected,
                "evidence.telemetry_incomplete",
                f"Drive telemetry for session {session_uuid} lacks an integer runtime timestamp.",
            )
        elif image_timestamp_us is None:
            _record(
                detected,
                "temporal.missing_observation",
                f"Session {session_uuid} reached Drive without a retained image timestamp.",
            )
        elif image_timestamp_us > time_now_us:
            _record(
                detected,
                "temporal.future_observation",
                (
                    f"Image timestamp {image_timestamp_us} us is later than Drive time "
                    f"{time_now_us} us for session {session_uuid}."
                ),
            )
        elif time_now_us - image_timestamp_us > MAX_IMAGE_AGE_US:
            _record(
                detected,
                "temporal.stale_observation",
                (
                    f"Drive input lag was {time_now_us - image_timestamp_us} us, above "
                    f"the {MAX_IMAGE_AGE_US} us contract."
                ),
            )

        if schema == "wod2sim_challenge_telemetry_v3":
            _diagnose_current_trajectory_shape(event, detected, session_uuid)
        else:
            trajectory_points = _as_int(event.get("trajectory_points"))
            if trajectory_points is None:
                _record(
                    detected,
                    "evidence.telemetry_incomplete",
                    f"Drive telemetry for session {session_uuid} lacks trajectory_points.",
                )
            elif trajectory_points != EXPECTED_TRAJECTORY_POINTS:
                _record(
                    detected,
                    "temporal.invalid_sample_count",
                    (
                        f"Trajectory contained {trajectory_points} points; "
                        f"{EXPECTED_TRAJECTORY_POINTS} were required."
                    ),
                )
        if "trajectory_finite" not in event:
            _record(
                detected,
                "evidence.telemetry_incomplete",
                (
                    f"Drive telemetry for session {session_uuid} uses {schema or '<missing>'} "
                    "without an explicit trajectory_finite field."
                ),
            )
        elif event.get("trajectory_finite") is not True:
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
    for session_uuid in sorted(active_sessions):
        _record(
            detected,
            "lifecycle.session_not_closed",
            f"Session {session_uuid} has no retained close event.",
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

    order = {code: index for index, code in enumerate(DIAGNOSTIC_CODES)}
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
        drive = _first_event(mutated, "drive")
        if drive.get("schema") == "wod2sim_challenge_telemetry_v3":
            drive["trajectory_future_points"] = (
                int(drive["trajectory_expected_future_points"]) - 1
            )
        else:
            drive["trajectory_points"] = EXPECTED_TRAJECTORY_POINTS - 1
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


def split_session_traces(
    events: Sequence[Mapping[str, Any]],
) -> list[list[dict[str, Any]]]:
    session_order: list[str] = []
    by_session: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        session_uuid = str(event.get("session_uuid", "") or "")
        if not session_uuid:
            continue
        if session_uuid not in by_session:
            session_order.append(session_uuid)
            by_session[session_uuid] = []
        by_session[session_uuid].append(copy.deepcopy(dict(event)))
    return [by_session[session_uuid] for session_uuid in session_order]


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
    schemas = sorted(
        {
            str(event.get("schema"))
            for event in events
            if event.get("schema") not in (None, "")
        }
    )
    sessions = {
        str(event.get("session_uuid"))
        for event in events
        if event.get("session_uuid") not in (None, "")
    }
    return {
        "event_count": len(events),
        "session_count": len(sessions),
        "drive_count": len(latencies),
        "telemetry_schemas": schemas,
        "explicit_finite_drive_count": sum(
            event.get("event") == "drive" and event.get("trajectory_finite") is True
            for event in events
        ),
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


def _diagnose_route_source(
    event: Mapping[str, Any],
    detected: dict[str, ContractDiagnostic],
) -> None:
    if event.get("route_geometry_required") is False:
        return
    source = str(event.get("route_source", "") or "")
    if source == "command_proxy":
        _record(
            detected,
            "semantic.command_only",
            "A high-level command proxy replaced route geometry.",
        )
    elif source == "road_center_reference":
        _record(
            detected,
            "semantic.road_center_reference",
            "A road-center reference was presented as policy route geometry.",
        )


def _diagnose_current_trajectory_shape(
    event: Mapping[str, Any],
    detected: dict[str, ContractDiagnostic],
    session_uuid: str,
) -> None:
    total = _as_int(event.get("trajectory_points"))
    future = _as_int(event.get("trajectory_future_points"))
    expected = _as_int(event.get("trajectory_expected_future_points"))
    includes_current = event.get("trajectory_includes_current_pose")
    if (
        total is None
        or future is None
        or expected is None
        or includes_current is not True
    ):
        _record(
            detected,
            "evidence.telemetry_incomplete",
            (
                f"Drive telemetry for session {session_uuid} lacks the v3 trajectory "
                "shape fields."
            ),
        )
        return
    if future != expected or total != future + 1:
        _record(
            detected,
            "temporal.invalid_sample_count",
            (
                f"Trajectory contained {future} future points plus the current pose; "
                f"{expected} future points were required."
            ),
        )


def _record(detected: dict[str, ContractDiagnostic], code: str, detail: str) -> None:
    layer = "deployment" if code.startswith("plugin.") else code.split(".", 1)[0]
    detected.setdefault(
        code,
        ContractDiagnostic(layer=layer, code=code, detail=detail),
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
