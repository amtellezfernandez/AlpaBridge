from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LifecycleEvent:
    session_id: str
    event_type: str
    code: str
    severity: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "session_id": self.session_id,
            "event_type": self.event_type,
            "code": self.code,
            "severity": self.severity,
            "detail": self.detail,
        }


@dataclass
class _SessionState:
    session_id: str
    image_count: int = 0
    egomotion_count: int = 0
    route_count: int = 0
    route_waypoints: list[Any] = field(default_factory=list)


class SyntheticLifecycleService:
    """Dependency-light lifecycle model for service-contract tests and CVM diagnostics."""

    def __init__(self, *, hardened: bool) -> None:
        self._hardened = hardened
        self._sessions: dict[str, _SessionState] = {}
        self._closed_sessions: set[str] = set()
        self._events: list[LifecycleEvent] = []
        self._alive = True

    def start_session(self, session_id: str) -> LifecycleEvent:
        self._ensure_alive()
        self._sessions[session_id] = _SessionState(session_id=session_id)
        self._closed_sessions.discard(session_id)
        return self._record(
            session_id=session_id,
            event_type="start_session",
            code="session_started",
            severity="info",
            detail="Session created and marked active.",
        )

    def close_session(self, session_id: str) -> LifecycleEvent:
        if session_id in self._sessions:
            del self._sessions[session_id]
            self._closed_sessions.add(session_id)
            return self._record(
                session_id=session_id,
                event_type="close_session",
                code="session_closed",
                severity="info",
                detail="Session closed and state removed.",
            )
        return self._unknown_session_event(
            session_id=session_id,
            event_type="close_session",
            hardened_code="duplicate_close_idempotent",
            strict_code="duplicate_close_unhandled",
            detail="Close received for a non-active session.",
        )

    def submit_image_observation(self, session_id: str, timestamp_us: int) -> LifecycleEvent:
        session = self._sessions.get(session_id)
        if session is None:
            return self._unknown_session_event(
                session_id=session_id,
                event_type="submit_image_observation",
                hardened_code="late_image_after_close",
                strict_code="late_image_unhandled",
                detail=f"Image frame at {timestamp_us} ignored for a non-active session.",
            )
        session.image_count += 1
        return self._record(
            session_id=session_id,
            event_type="submit_image_observation",
            code="image_observation_accepted",
            severity="info",
            detail=f"Image frame at {timestamp_us} accepted.",
        )

    def submit_egomotion_observation(self, session_id: str, timestamp_us: int) -> LifecycleEvent:
        session = self._sessions.get(session_id)
        if session is None:
            return self._unknown_session_event(
                session_id=session_id,
                event_type="submit_egomotion_observation",
                hardened_code="late_egomotion_after_close",
                strict_code="late_egomotion_unhandled",
                detail=f"Egomotion at {timestamp_us} ignored for a non-active session.",
            )
        session.egomotion_count += 1
        return self._record(
            session_id=session_id,
            event_type="submit_egomotion_observation",
            code="egomotion_observation_accepted",
            severity="info",
            detail=f"Egomotion at {timestamp_us} accepted.",
        )

    def submit_route(self, session_id: str, route_waypoints: list[Any]) -> LifecycleEvent:
        session = self._sessions.get(session_id)
        if session is None:
            return self._unknown_session_event(
                session_id=session_id,
                event_type="submit_route",
                hardened_code="late_route_after_close",
                strict_code="late_route_unhandled",
                detail="Route update ignored for a non-active session.",
            )
        session.route_count += 1
        session.route_waypoints = list(route_waypoints)
        return self._record(
            session_id=session_id,
            event_type="submit_route",
            code="route_update_accepted",
            severity="info",
            detail=f"Route update with {len(route_waypoints)} waypoints accepted.",
        )

    def evidence(self) -> dict[str, Any]:
        warning_events = [event for event in self._events if event.severity in {"warning", "fatal"}]
        warning_counts: dict[str, int] = {}
        for event in warning_events:
            warning_counts[event.code] = warning_counts.get(event.code, 0) + 1
        return {
            "active_sessions": sorted(self._sessions),
            "closed_sessions": sorted(self._closed_sessions),
            "session_state": {
                session_id: {
                    "image_count": session.image_count,
                    "egomotion_count": session.egomotion_count,
                    "route_count": session.route_count,
                    "route_waypoint_count": len(session.route_waypoints),
                }
                for session_id, session in sorted(self._sessions.items())
            },
            "events": [event.as_dict() for event in self._events],
            "warning_counts": warning_counts,
            "late_message_count": len(warning_events),
            "service_survived": self._alive,
            "fatal_code": "" if self._alive else warning_events[-1].code,
        }

    def _unknown_session_event(
        self,
        *,
        session_id: str,
        event_type: str,
        hardened_code: str,
        strict_code: str,
        detail: str,
    ) -> LifecycleEvent:
        if self._hardened:
            return self._record(
                session_id=session_id,
                event_type=event_type,
                code=hardened_code,
                severity="warning",
                detail=detail,
            )
        self._alive = False
        return self._record(
            session_id=session_id,
            event_type=event_type,
            code=strict_code,
            severity="fatal",
            detail=detail,
        )

    def _record(
        self,
        *,
        session_id: str,
        event_type: str,
        code: str,
        severity: str,
        detail: str,
    ) -> LifecycleEvent:
        event = LifecycleEvent(
            session_id=session_id,
            event_type=event_type,
            code=code,
            severity=severity,
            detail=detail,
        )
        self._events.append(event)
        return event

    def _ensure_alive(self) -> None:
        if not self._alive:
            raise RuntimeError("Lifecycle service is no longer active after a fatal event")


def run_synthetic_lifecycle_cycle(
    *,
    hardened: bool,
    schedule: list[str],
    session_id: str,
) -> dict[str, Any]:
    service = SyntheticLifecycleService(hardened=hardened)
    service.start_session(session_id)
    service.submit_image_observation(session_id, timestamp_us=1_000)
    service.submit_egomotion_observation(session_id, timestamp_us=1_000)
    service.submit_route(session_id, route_waypoints=[{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}])
    service.close_session(session_id)
    for item in schedule:
        if not service.evidence()["service_survived"]:
            break
        if item == "lifecycle.duplicate_close":
            service.close_session(session_id)
        elif item == "lifecycle.late_image":
            service.submit_image_observation(session_id, timestamp_us=2_000)
        elif item == "lifecycle.late_egomotion":
            service.submit_egomotion_observation(session_id, timestamp_us=2_000)
        elif item == "lifecycle.late_route":
            service.submit_route(session_id, route_waypoints=[{"x": 20.0, "y": 0.0}])
        else:
            service._record(
                session_id=session_id,
                event_type="unknown_lifecycle_schedule_item",
                code="unknown_lifecycle_schedule_item",
                severity="warning",
                detail=f"Unknown lifecycle schedule item: {item}",
            )

    evidence = service.evidence()
    observed_code = (
        "late_events_classified"
        if evidence["service_survived"]
        else str(evidence["fatal_code"] or "lifecycle_unhandled")
    )
    evidence["observed_code"] = observed_code
    evidence["correctly_localized"] = evidence["service_survived"] and observed_code == "late_events_classified"
    return evidence
