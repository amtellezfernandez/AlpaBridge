from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from wod2sim.audit.diagnostic_experiment import run_diagnostic_experiment
from wod2sim.audit.diagnostic_trace_generation import (
    DEFAULT_PROTOCOL_SESSION_COUNT,
    generate_protocol_trace,
)
from wod2sim.audit.trace_diagnostics import (
    DEFAULT_CONTEXT,
    FAULT_CODES,
    diagnose_contract_trace,
    load_telemetry_trace,
    mutate_trace,
    split_session_traces,
    status_only_accepts,
)

ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / "artifacts" / "cvm" / "inputs" / "diagnostic_protocol_sessions.jsonl"
EXTERNAL_V1_TRACE = (
    ROOT
    / "artifacts"
    / "external"
    / "alpasim_e2e_challenge_conformance"
    / "challenge-driver-fixed.jsonl"
)


def test_retained_protocol_sessions_are_separate_and_contract_clean() -> None:
    events = load_telemetry_trace(TRACE)
    sessions = split_session_traces(events)

    assert len(sessions) == DEFAULT_PROTOCOL_SESSION_COUNT
    assert len({session[0]["session_uuid"] for session in sessions}) == len(sessions)
    assert all(
        diagnose_contract_trace(session, context=DEFAULT_CONTEXT) == [] for session in sessions
    )
    drive_events = [event for event in events if event["event"] == "drive"]
    assert len(drive_events) == 120
    assert all(event["trajectory_finite"] is True for event in drive_events)
    assert {event["camera_id"] for event in events if event["event"] == "image"} == {
        "CAM_F0",
        "camera_front_wide_120fov",
    }
    assert {round(event["speed_mps"], 6) for event in drive_events} == {
        float(speed) for speed in range(2, 10)
    }
    latest_image_by_session: dict[str, int] = {}
    sensor_ages: set[int] = set()
    for event in events:
        if event["event"] == "image":
            latest_image_by_session[event["session_uuid"]] = event["timestamp_us"]
        elif event["event"] == "drive":
            sensor_ages.add(event["time_now_us"] - latest_image_by_session[event["session_uuid"]])
    assert sensor_ages == {0, 25_000, 50_000, 75_000, 100_000}


def test_protocol_trace_generator_emits_current_instrumentation(tmp_path: Path) -> None:
    path = tmp_path / "protocol.jsonl"

    summary = generate_protocol_trace(path, session_count=DEFAULT_PROTOCOL_SESSION_COUNT)
    sessions = split_session_traces(load_telemetry_trace(path))

    assert summary["session_count"] == DEFAULT_PROTOCOL_SESSION_COUNT
    assert summary["drive_count"] == 120
    assert all(
        diagnose_contract_trace(session, context=DEFAULT_CONTEXT) == [] for session in sessions
    )


@pytest.mark.parametrize(
    "mutation",
    ("legacy_schema", "missing_session_uuid", "unknown_event"),
)
def test_diagnostic_experiment_rejects_noncurrent_or_orphaned_telemetry(
    tmp_path: Path,
    mutation: str,
) -> None:
    events = load_telemetry_trace(TRACE)
    if mutation == "legacy_schema":
        for event in events:
            event["schema"] = "wod2sim_challenge_telemetry_v1"
    elif mutation == "missing_session_uuid":
        events[1].pop("session_uuid")
    else:
        events[1]["event"] = "unexpected_protocol_event"
    path = tmp_path / f"{mutation}.jsonl"
    path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source trace"):
        run_diagnostic_experiment(
            path,
            timing_iterations=1,
            timing_batch_size=1,
            adapter_iterations=1,
            adapter_batch_size=1,
        )


def test_retained_external_v1_trace_exposes_missing_finite_output_evidence() -> None:
    events = load_telemetry_trace(EXTERNAL_V1_TRACE)

    observed = diagnose_contract_trace(events, context=DEFAULT_CONTEXT)

    assert [item.code for item in observed] == ["evidence.telemetry_incomplete"]
    assert "trajectory_finite" in observed[0].detail


@pytest.mark.parametrize("fault_code", FAULT_CODES)
def test_mutated_trace_is_classified_without_expected_label(fault_code: str) -> None:
    sessions = split_session_traces(load_telemetry_trace(TRACE))
    source = sessions[FAULT_CODES.index(fault_code)]
    mutated, context = mutate_trace(source, fault_code)

    observed = diagnose_contract_trace(mutated, context=context)

    assert [item.code for item in observed] == [fault_code]
    assert status_only_accepts(context) is True


def test_diagnostic_experiment_scores_controls_faults_comparator_and_timing() -> None:
    result = run_diagnostic_experiment(
        TRACE,
        timing_iterations=1,
        timing_batch_size=1,
        adapter_iterations=2,
        adapter_batch_size=2,
    )

    wod2sim = result["classification"]["wod2sim"]
    status_only = result["classification"]["status_only"]
    paired = result["classification"]["paired_comparison"]
    assert result["design"]["total_cases"] == 30
    assert result["source_trace"]["session_count"] == 15
    assert result["source_trace"]["explicit_finite_drive_count"] == 120
    assert wod2sim["classification_correct"] == 30
    assert wod2sim["faults_detected"] == 15
    assert wod2sim["faults_correctly_localized"] == 15
    assert wod2sim["false_positives"] == 0
    assert status_only["classification_correct"] == 15
    assert status_only["faults_detected"] == 0
    assert paired["wod2sim_only_correct"] == 15
    assert paired["status_only_only_correct"] == 0
    assert paired["discordant_pairs"] == 15
    assert result["timing"]["contract_gate_decision_us"]["samples"] == 30
    assert result["timing"]["fault_case_detector_us"]["samples"] == 15
    assert "human investigation time" in result["timing"]["scope"]
    adapter_timing = result["adapter_guard_path_timing"]
    assert adapter_timing["input_cases"] == 15
    assert adapter_timing["trajectory_outputs_equal"] is True
    assert "drive_once_to_proto" in adapter_timing["scope"]
    assert "gRPC transport" in adapter_timing["scope"]
    assert sorted(result["implementation_sha256"]) == [
        "src/wod2sim/audit/diagnostic_experiment.py",
        "src/wod2sim/audit/diagnostic_trace_generation.py",
        "src/wod2sim/audit/trace_diagnostics.py",
        "src/wod2sim/challenge/e2e_driver.py",
        "src/wod2sim/simulator/baseline_drivers.py",
    ]


def test_drive_before_route_is_not_rehabilitated_by_a_later_route() -> None:
    session = _session(0)
    route_index = _event_index(session, "route")
    route = session.pop(route_index)
    first_drive_index = _event_index(session, "drive")
    session.insert(first_drive_index + 1, route)

    observed = diagnose_contract_trace(session, context=DEFAULT_CONTEXT)

    assert [item.code for item in observed] == ["semantic.route_missing"]


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("missing_image", "temporal.missing_observation"),
        ("future_image", "temporal.future_observation"),
        ("missing_finite_field", "evidence.telemetry_incomplete"),
        ("missing_close", "lifecycle.session_not_closed"),
        ("late_drive", "lifecycle.late_drive"),
    ),
)
def test_protocol_ordering_and_completeness_faults_are_detected(
    mutation: str,
    expected_code: str,
) -> None:
    session = _session(0)
    if mutation == "missing_image":
        session = [event for event in session if event["event"] != "image"]
    elif mutation == "future_image":
        drive = session[_event_index(session, "drive")]
        image = session[_event_index(session, "image")]
        image["timestamp_us"] = int(drive["time_now_us"]) + 1
    elif mutation == "missing_finite_field":
        session[_event_index(session, "drive")].pop("trajectory_finite")
    elif mutation == "missing_close":
        session = [event for event in session if event["event"] != "close_session"]
    elif mutation == "late_drive":
        session.append(copy.deepcopy(session[_event_index(session, "drive")]))

    observed = diagnose_contract_trace(session, context=DEFAULT_CONTEXT)

    assert [item.code for item in observed] == [expected_code]


def test_contract_clean_trace_is_invariant_to_noncontract_metadata_and_session_name() -> None:
    session = _session(4)
    for event in session:
        event["session_uuid"] = "renamed-session"
        event["unrecognized_metadata"] = {"retained": True}

    observed = diagnose_contract_trace(session, context=DEFAULT_CONTEXT)

    assert observed == []


def _session(index: int) -> list[dict[str, object]]:
    sessions = split_session_traces(load_telemetry_trace(TRACE))
    return copy.deepcopy(sessions[index])


def _event_index(events: list[dict[str, object]], event_name: str) -> int:
    return next(index for index, event in enumerate(events) if event.get("event") == event_name)
