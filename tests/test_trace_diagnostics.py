from __future__ import annotations

from pathlib import Path

import pytest

from wod2sim.audit.diagnostic_experiment import run_diagnostic_experiment
from wod2sim.audit.trace_diagnostics import (
    DEFAULT_CONTEXT,
    FAULT_CODES,
    build_control_traces,
    diagnose_contract_trace,
    load_telemetry_trace,
    mutate_trace,
    status_only_accepts,
)

ROOT = Path(__file__).resolve().parents[1]
TRACE = (
    ROOT
    / "artifacts"
    / "external"
    / "alpasim_e2e_challenge_conformance"
    / "challenge-driver-fixed.jsonl"
)


def test_retained_external_trace_and_prefix_controls_are_contract_clean() -> None:
    events = load_telemetry_trace(TRACE)

    assert diagnose_contract_trace(events, context=DEFAULT_CONTEXT) == []
    controls = build_control_traces(events, count=15)
    assert len(controls) == 15
    assert all(
        diagnose_contract_trace(control, context=DEFAULT_CONTEXT) == []
        for control in controls
    )


@pytest.mark.parametrize("fault_code", FAULT_CODES)
def test_mutated_trace_is_classified_without_expected_label(fault_code: str) -> None:
    events = load_telemetry_trace(TRACE)
    mutated, context = mutate_trace(events, fault_code)

    observed = diagnose_contract_trace(mutated, context=context)

    assert [item.code for item in observed] == [fault_code]
    assert status_only_accepts(context) is True


def test_diagnostic_experiment_scores_controls_faults_comparator_and_timing() -> None:
    result = run_diagnostic_experiment(
        TRACE,
        timing_iterations=1,
        timing_batch_size=1,
        guard_iterations=2,
        guard_batch_size=2,
    )

    wod2sim = result["classification"]["wod2sim"]
    status_only = result["classification"]["status_only"]
    paired = result["classification"]["paired_mcnemar"]
    assert result["design"]["total_cases"] == 30
    assert wod2sim["classification_correct"] == 30
    assert wod2sim["faults_detected"] == 15
    assert wod2sim["faults_correctly_localized"] == 15
    assert wod2sim["false_positives"] == 0
    assert status_only["classification_correct"] == 15
    assert status_only["faults_detected"] == 0
    assert paired["wod2sim_only_correct"] == 15
    assert paired["status_only_only_correct"] == 0
    assert paired["exact_two_sided_p"] == pytest.approx(2 / (2**15))
    assert result["timing"]["wod2sim_decision_us"]["samples"] == 30
    assert result["timing"]["correct_fault_diagnosis_us"]["samples"] == 15
    assert result["online_guard_overhead"]["trajectory_outputs_equal"] is True
    assert (
        result["online_guard_overhead"][
            "incremental_p50_as_source_driver_p50_percent"
        ]
        is not None
    )
    assert sorted(result["implementation_sha256"]) == [
        "src/wod2sim/audit/diagnostic_experiment.py",
        "src/wod2sim/audit/trace_diagnostics.py",
        "src/wod2sim/simulator/baseline_drivers.py",
    ]
