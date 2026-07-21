from __future__ import annotations

import unittest

from alpabridge.simulator.lifecycle_service import (
    SyntheticLifecycleService,
    run_synthetic_lifecycle_cycle,
)


class LifecycleContractTests(unittest.TestCase):
    def test_duplicate_close_is_idempotent(self) -> None:
        service = SyntheticLifecycleService(hardened=True)

        service.start_session("session-a")
        service.close_session("session-a")
        event = service.close_session("session-a")
        evidence = service.evidence()

        self.assertEqual("duplicate_close_idempotent", event.code)
        self.assertEqual("warning", event.severity)
        self.assertTrue(evidence["service_survived"])
        self.assertEqual({"duplicate_close_idempotent": 1}, evidence["warning_counts"])
        self.assertEqual([], evidence["active_sessions"])

    def test_late_image_after_close_does_not_crash(self) -> None:
        service = SyntheticLifecycleService(hardened=True)

        service.start_session("session-a")
        service.close_session("session-a")
        event = service.submit_image_observation("session-a", timestamp_us=2_000)
        evidence = service.evidence()

        self.assertEqual("late_image_after_close", event.code)
        self.assertEqual("warning", event.severity)
        self.assertTrue(evidence["service_survived"])
        self.assertEqual(1, evidence["warning_counts"]["late_image_after_close"])

    def test_late_egomotion_after_close_does_not_crash(self) -> None:
        service = SyntheticLifecycleService(hardened=True)

        service.start_session("session-a")
        service.close_session("session-a")
        event = service.submit_egomotion_observation("session-a", timestamp_us=2_000)
        evidence = service.evidence()

        self.assertEqual("late_egomotion_after_close", event.code)
        self.assertEqual("warning", event.severity)
        self.assertTrue(evidence["service_survived"])
        self.assertEqual(1, evidence["warning_counts"]["late_egomotion_after_close"])

    def test_late_route_after_close_does_not_crash(self) -> None:
        service = SyntheticLifecycleService(hardened=True)

        service.start_session("session-a")
        service.close_session("session-a")
        event = service.submit_route("session-a", route_waypoints=[{"x": 1.0, "y": 0.0}])
        evidence = service.evidence()

        self.assertEqual("late_route_after_close", event.code)
        self.assertEqual("warning", event.severity)
        self.assertTrue(evidence["service_survived"])
        self.assertEqual(1, evidence["warning_counts"]["late_route_after_close"])

    def test_unknown_session_event_is_structured_and_counted(self) -> None:
        service = SyntheticLifecycleService(hardened=True)

        event = service.submit_image_observation("missing-session", timestamp_us=10)
        evidence = service.evidence()

        self.assertEqual(
            {
                "session_id": "missing-session",
                "event_type": "submit_image_observation",
                "code": "late_image_after_close",
                "severity": "warning",
                "detail": "Image frame at 10 ignored for a non-active session.",
            },
            event.as_dict(),
        )
        self.assertEqual(1, evidence["late_message_count"])
        self.assertEqual(1, evidence["warning_counts"]["late_image_after_close"])

    def test_session_cleanup_prevents_state_leak(self) -> None:
        service = SyntheticLifecycleService(hardened=True)

        service.start_session("first")
        service.submit_route("first", route_waypoints=[{"x": 1.0, "y": 0.0}])
        service.close_session("first")
        service.start_session("second")
        evidence = service.evidence()

        self.assertEqual(["second"], evidence["active_sessions"])
        self.assertEqual(0, evidence["session_state"]["second"]["route_count"])
        self.assertNotIn("first", evidence["session_state"])

    def test_interleaved_sessions_remain_isolated(self) -> None:
        service = SyntheticLifecycleService(hardened=True)

        service.start_session("session-a")
        service.start_session("session-b")
        service.submit_image_observation("session-a", timestamp_us=1_000)
        service.submit_route("session-b", route_waypoints=[{"x": 2.0, "y": 0.0}])
        service.close_session("session-a")
        evidence = service.evidence()

        self.assertEqual(["session-b"], evidence["active_sessions"])
        self.assertEqual(1, evidence["session_state"]["session-b"]["route_count"])
        self.assertEqual(1, evidence["session_state"]["session-b"]["route_waypoint_count"])
        self.assertNotIn("session-a", evidence["session_state"])

    def test_repeated_start_stop_cycles_are_stable(self) -> None:
        schedule = [
            "lifecycle.duplicate_close",
            "lifecycle.late_image",
            "lifecycle.late_egomotion",
            "lifecycle.late_route",
        ]

        results = [
            run_synthetic_lifecycle_cycle(
                hardened=True,
                schedule=schedule,
                session_id=f"session-{cycle:02d}",
            )
            for cycle in range(20)
        ]

        self.assertTrue(all(result["service_survived"] for result in results))
        self.assertTrue(all(result["observed_code"] == "late_events_classified" for result in results))
        self.assertEqual([4] * 20, [result["late_message_count"] for result in results])

    def test_strict_pre_hardening_behavior_stops_on_duplicate_close(self) -> None:
        result = run_synthetic_lifecycle_cycle(
            hardened=False,
            schedule=[
                "lifecycle.duplicate_close",
                "lifecycle.late_image",
                "lifecycle.late_egomotion",
                "lifecycle.late_route",
            ],
            session_id="strict-session",
        )

        self.assertFalse(result["service_survived"])
        self.assertEqual("duplicate_close_unhandled", result["observed_code"])
        self.assertEqual(1, result["late_message_count"])
        self.assertFalse(result["correctly_localized"])


if __name__ == "__main__":
    unittest.main()
