from __future__ import annotations

import hashlib
import inspect
import math
import platform
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from wod2sim.challenge.e2e_driver import WOD2SimChallengeAdapter
from wod2sim.simulator.baseline_drivers import RouteFollowingAlpaSimModel

from .trace_diagnostics import (
    CURRENT_TELEMETRY_SCHEMA,
    DEFAULT_CONTEXT,
    FAULT_CODES,
    diagnose_contract_trace,
    load_telemetry_trace,
    mutate_trace,
    split_session_traces,
    status_only_accepts,
    trace_runtime_summary,
)

DEFAULT_RANDOM_SEED = 2027
TRACE_WARMUP_CALLS_PER_CASE = 3
ADAPTER_WARMUP_CALLS_PER_METHOD = 50


def run_diagnostic_experiment(
    trace_path: Path,
    *,
    timing_iterations: int = 200,
    timing_batch_size: int = 5,
    adapter_iterations: int = 1000,
    adapter_batch_size: int = 20,
    random_seed: int = DEFAULT_RANDOM_SEED,
) -> dict[str, Any]:
    events = load_telemetry_trace(trace_path)
    trace_diagnostics = diagnose_contract_trace(events, context=DEFAULT_CONTEXT)
    if trace_diagnostics:
        codes = ", ".join(item.code for item in trace_diagnostics)
        raise ValueError(f"source trace violates the diagnostic contract: {codes}")
    source_runtime = trace_runtime_summary(events)
    if source_runtime["telemetry_schemas"] != [CURRENT_TELEMETRY_SCHEMA]:
        schemas = ", ".join(source_runtime["telemetry_schemas"]) or "<missing>"
        raise ValueError(
            "source trace must use only the current telemetry schema "
            f"{CURRENT_TELEMETRY_SCHEMA}; observed {schemas}"
        )
    session_traces = split_session_traces(events)
    if len(session_traces) != len(FAULT_CODES):
        raise ValueError(
            f"source has {len(session_traces)} sessions; {len(FAULT_CODES)} are required"
        )
    for index, session_trace in enumerate(session_traces, start=1):
        baseline_diagnostics = diagnose_contract_trace(
            session_trace,
            context=DEFAULT_CONTEXT,
        )
        if baseline_diagnostics:
            codes = ", ".join(item.code for item in baseline_diagnostics)
            raise ValueError(f"source session {index} violates the diagnostic contract: {codes}")
    cases = _build_cases(session_traces)
    case_results = [_evaluate_case(case) for case in cases]
    wod_correct = sum(row["wod2sim_classification_correct"] for row in case_results)
    status_correct = sum(row["status_only_classification_correct"] for row in case_results)
    fault_rows = [row for row in case_results if row["expected_fault_code"]]
    control_rows = [row for row in case_results if not row["expected_fault_code"]]
    wod_detected = sum(row["wod2sim_fault_detected"] for row in fault_rows)
    wod_localized = sum(row["wod2sim_localization_correct"] for row in fault_rows)
    status_detected = sum(row["status_only_fault_detected"] for row in fault_rows)
    status_localized = sum(row["status_only_localization_correct"] for row in fault_rows)
    wod_false_positives = sum(row["wod2sim_fault_detected"] for row in control_rows)
    status_false_positives = sum(row["status_only_fault_detected"] for row in control_rows)
    wod_only_correct = sum(
        row["wod2sim_classification_correct"] and not row["status_only_classification_correct"]
        for row in case_results
    )
    status_only_correct = sum(
        row["status_only_classification_correct"] and not row["wod2sim_classification_correct"]
        for row in case_results
    )

    timing = _benchmark_trace_decisions(
        cases,
        iterations=timing_iterations,
        batch_size=timing_batch_size,
        random_seed=random_seed,
    )
    adapter_guard_path = _benchmark_adapter_guard_path(
        iterations=adapter_iterations,
        batch_size=adapter_batch_size,
        random_seed=random_seed,
    )
    total = len(case_results)
    fault_total = len(fault_rows)
    control_total = len(control_rows)
    return {
        "schema": "wod2sim_diagnostic_experiment_v3",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_trace": {
            "path": trace_path.as_posix(),
            "sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
            "kind": (
                "dependency-light current-instrumentation adapter sessions; "
                "not external simulator rollouts"
            ),
            **source_runtime,
        },
        "design": {
            "fault_cases": fault_total,
            "control_cases": control_total,
            "total_cases": total,
            "fault_codes": list(FAULT_CODES),
            "control_construction": (
                "Fifteen unmodified, separately instantiated current-instrumentation "
                "adapter sessions, one paired with each fault operator."
            ),
            "fault_construction": (
                "One predefined telemetry or runtime-context mutation per source "
                "session; the detector receives only the mutated trace and context."
            ),
            "scoring": (
                "Expected labels are retained by the experiment scorer and are not "
                "passed to diagnose_contract_trace."
            ),
            "inference": (
                "No population-level confidence interval or hypothesis test is "
                "reported because sessions and mutations form a designed conformance suite."
            ),
            "random_seed": random_seed,
            "timing_iterations": timing_iterations,
            "timing_batch_size": timing_batch_size,
            "adapter_iterations": adapter_iterations,
            "adapter_batch_size": adapter_batch_size,
        },
        "classification": {
            "wod2sim": _classification_summary(
                correct=wod_correct,
                total=total,
                detected=wod_detected,
                fault_total=fault_total,
                localized=wod_localized,
                false_positives=wod_false_positives,
                control_total=control_total,
            ),
            "status_only": _classification_summary(
                correct=status_correct,
                total=total,
                detected=status_detected,
                fault_total=fault_total,
                localized=status_localized,
                false_positives=status_false_positives,
                control_total=control_total,
            ),
            "paired_comparison": {
                "wod2sim_only_correct": wod_only_correct,
                "status_only_only_correct": status_only_correct,
                "discordant_pairs": wod_only_correct + status_only_correct,
                "scope": (
                    "Descriptive paired counts for this designed suite; no "
                    "independence-based significance test is applied."
                ),
            },
        },
        "timing": timing,
        "adapter_guard_path_timing": adapter_guard_path,
        "cases": case_results,
        "implementation_sha256": _implementation_hashes(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "processor": _processor_name(),
            "timer": "time.perf_counter_ns",
        },
    }


def _build_cases(
    session_traces: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    paired_controls: list[dict[str, Any]] = []
    for index, (fault_code, session_trace) in enumerate(
        zip(FAULT_CODES, session_traces, strict=True),
        start=1,
    ):
        mutated, context = mutate_trace(session_trace, fault_code)
        cases.append(
            {
                "case_id": f"fault:{index:02d}:{fault_code}",
                "pair_id": f"session_pair_{index:02d}",
                "expected_fault_code": fault_code,
                "events": mutated,
                "context": context,
            }
        )
        paired_controls.append(
            {
                "case_id": f"control:{index:02d}",
                "pair_id": f"session_pair_{index:02d}",
                "expected_fault_code": "",
                "events": session_trace,
                "context": dict(DEFAULT_CONTEXT),
            }
        )
    return [*cases, *paired_controls]


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    diagnostics = diagnose_contract_trace(case["events"], context=case["context"])
    observed_codes = [item.code for item in diagnostics]
    expected_code = str(case["expected_fault_code"])
    expected_valid = not expected_code
    wod_valid = not observed_codes
    status_valid = status_only_accepts(case["context"])
    return {
        "case_id": case["case_id"],
        "pair_id": case["pair_id"],
        "event_count": len(case["events"]),
        "expected_valid": expected_valid,
        "expected_fault_code": expected_code,
        "wod2sim_valid": wod_valid,
        "wod2sim_observed_codes": observed_codes,
        "wod2sim_fault_detected": bool(observed_codes),
        "wod2sim_classification_correct": wod_valid == expected_valid,
        "wod2sim_localization_correct": (
            bool(expected_code) and len(observed_codes) == 1 and observed_codes[0] == expected_code
        ),
        "status_only_valid": status_valid,
        "status_only_fault_detected": False,
        "status_only_classification_correct": status_valid == expected_valid,
        "status_only_localization_correct": False,
    }


def _classification_summary(
    *,
    correct: int,
    total: int,
    detected: int,
    fault_total: int,
    localized: int,
    false_positives: int,
    control_total: int,
) -> dict[str, Any]:
    return {
        "classification_correct": correct,
        "classification_total": total,
        "classification_accuracy": correct / total,
        "faults_detected": detected,
        "fault_total": fault_total,
        "fault_recall": detected / fault_total,
        "faults_correctly_localized": localized,
        "localization_rate": localized / fault_total,
        "false_positives": false_positives,
        "control_total": control_total,
        "specificity": (control_total - false_positives) / control_total,
    }


def _benchmark_trace_decisions(
    cases: list[dict[str, Any]],
    *,
    iterations: int,
    batch_size: int,
    random_seed: int,
) -> dict[str, Any]:
    if iterations < 1 or batch_size < 1:
        raise ValueError("timing iterations and batch size must be positive")
    rng = random.Random(random_seed)
    samples: dict[str, list[float]] = {"wod2sim": [], "status_only": []}
    fault_case_samples: list[float] = []

    for case in cases:
        for _ in range(TRACE_WARMUP_CALLS_PER_CASE):
            diagnose_contract_trace(case["events"], context=case["context"])
            status_only_accepts(case["context"])

    for _ in range(iterations):
        case_order = list(cases)
        rng.shuffle(case_order)
        for case in case_order:
            methods = ["wod2sim", "status_only"]
            rng.shuffle(methods)
            for method in methods:
                if method == "wod2sim":
                    call = lambda: diagnose_contract_trace(  # noqa: E731
                        case["events"],
                        context=case["context"],
                    )
                else:
                    call = lambda: status_only_accepts(case["context"])  # noqa: E731
                elapsed_us = _time_call_us(call, batch_size=batch_size)
                samples[method].append(elapsed_us)
                if method == "wod2sim" and case["expected_fault_code"]:
                    fault_case_samples.append(elapsed_us)

    wod_summary = _timing_summary(samples["wod2sim"])
    status_summary = _timing_summary(samples["status_only"])
    return {
        "scope": (
            "in-memory detector execution on already-parsed telemetry and runtime "
            "context; excludes JSON parsing, file I/O, and human investigation time"
        ),
        "pairing": (
            "Method order is randomized within every case and iteration; reported "
            "samples are per-call batch means."
        ),
        "warmup_calls_per_case_and_method": TRACE_WARMUP_CALLS_PER_CASE,
        "contract_gate_decision_us": wod_summary,
        "completion_gate_decision_us": status_summary,
        "incremental_decision_p50_us": (wod_summary["p50"] - status_summary["p50"]),
        "fault_case_detector_us": _timing_summary(fault_case_samples),
    }


def _benchmark_adapter_guard_path(
    *,
    iterations: int,
    batch_size: int,
    random_seed: int,
) -> dict[str, Any]:
    if iterations < 1 or batch_size < 1:
        raise ValueError("adapter iterations and batch size must be positive")
    guarded, inputs = _adapter_benchmark_fixture(guarded=True)
    unchecked, unchecked_inputs = _adapter_benchmark_fixture(guarded=False)
    if inputs != unchecked_inputs:
        raise RuntimeError("guarded and unchecked adapter fixtures differ")

    for session_uuid, time_now_us in inputs:
        guarded_output = guarded.drive_once_to_proto(
            session_uuid,
            time_now_us=time_now_us,
            common_pb2=_BenchmarkCommonPb2,
        )
        unchecked_output = unchecked.drive_once_to_proto(
            session_uuid,
            time_now_us=time_now_us,
            common_pb2=_BenchmarkCommonPb2,
        )
        if _proto_trajectory_signature(guarded_output) != _proto_trajectory_signature(
            unchecked_output
        ):
            raise RuntimeError("adapter guard benchmark produced different trajectories")
    for index in range(ADAPTER_WARMUP_CALLS_PER_METHOD):
        session_uuid, time_now_us = inputs[index % len(inputs)]
        guarded.drive_once_to_proto(
            session_uuid,
            time_now_us=time_now_us,
            common_pb2=_BenchmarkCommonPb2,
        )
        unchecked.drive_once_to_proto(
            session_uuid,
            time_now_us=time_now_us,
            common_pb2=_BenchmarkCommonPb2,
        )

    rng = random.Random(random_seed + 1)
    samples: dict[str, list[float]] = {"guarded": [], "unchecked": []}
    paired_increment: list[float] = []
    input_order = list(inputs)
    for iteration in range(iterations):
        if iteration % len(input_order) == 0:
            rng.shuffle(input_order)
        session_uuid, time_now_us = input_order[iteration % len(input_order)]
        round_samples: dict[str, float] = {}
        methods = ["guarded", "unchecked"]
        rng.shuffle(methods)
        for method in methods:
            adapter = guarded if method == "guarded" else unchecked
            elapsed_us = _time_call_us(
                lambda adapter=adapter: adapter.drive_once_to_proto(
                    session_uuid,
                    time_now_us=time_now_us,
                    common_pb2=_BenchmarkCommonPb2,
                ),
                batch_size=batch_size,
            )
            samples[method].append(elapsed_us)
            round_samples[method] = elapsed_us
        paired_increment.append(round_samples["guarded"] - round_samples["unchecked"])

    guarded_summary = _timing_summary(samples["guarded"])
    unchecked_summary = _timing_summary(samples["unchecked"])
    increment_summary = _timing_summary(paired_increment)
    return {
        "scope": (
            "in-process WOD2SimChallengeAdapter.drive_once_to_proto route-following "
            "path; includes state-to-input assembly, prediction, trajectory "
            "serialization, finite-output validation, reasoning parsing, and in-memory "
            "telemetry, but excludes gRPC transport, file I/O, simulator work, and "
            "human investigation"
        ),
        "pairing": (
            "Guarded and unchecked order is randomized per iteration across 15 "
            "deterministic valid adapter sessions; paired differences use per-call "
            "batch means. The unchecked path disables only camera-set and "
            "sensor-freshness guards; context-length validation remains active in "
            "both paths."
        ),
        "input_cases": len(inputs),
        "warmup_calls_per_method": ADAPTER_WARMUP_CALLS_PER_METHOD,
        "trajectory_outputs_equal": True,
        "guarded_drive_path_us": guarded_summary,
        "unchecked_drive_path_us": unchecked_summary,
        "paired_incremental_us": increment_summary,
        "paired_incremental_p50_percent": (
            100.0 * increment_summary["p50"] / unchecked_summary["p50"]
            if unchecked_summary["p50"]
            else None
        ),
    }


def _adapter_benchmark_fixture(
    *,
    guarded: bool,
) -> tuple[WOD2SimChallengeAdapter, list[tuple[str, int]]]:
    adapter = WOD2SimChallengeAdapter(
        model_name="route_following",
        camera_ids=("CAM_F0", "camera_front_wide_120fov"),
        output_frequency_hz=10,
        telemetry_path=None,
    )
    if not guarded:
        adapter._model._validate_cameras = lambda _images: None  # type: ignore[method-assign]
        adapter._model._sensor_freshness_guard = _UncheckedFreshnessGuard()

    inputs: list[tuple[str, int]] = []
    for index in range(15):
        session_uuid = f"adapter-benchmark-{index + 1:02d}"
        timestamp_us = 1_000_000 + index * 500_000
        speed_mps = 2.0 + index * 0.5
        lateral = float((index % 5) - 2)
        adapter.start_session(
            SimpleNamespace(
                session_uuid=session_uuid,
                random_seed=DEFAULT_RANDOM_SEED + index,
                debug_info=SimpleNamespace(scene_id=session_uuid),
            )
        )
        adapter.submit_route(
            SimpleNamespace(
                session_uuid=session_uuid,
                route=SimpleNamespace(
                    waypoints=[
                        SimpleNamespace(x=0.0, y=0.0, z=0.0),
                        SimpleNamespace(x=30.0, y=lateral, z=0.0),
                        SimpleNamespace(x=60.0, y=lateral * 1.5, z=0.0),
                    ]
                ),
            )
        )
        adapter.submit_image_observation(
            SimpleNamespace(
                session_uuid=session_uuid,
                camera_image=SimpleNamespace(
                    logical_id=("CAM_F0" if index % 2 == 0 else "camera_front_wide_120fov"),
                    frame_end_us=timestamp_us,
                    image_bytes=bytes(((index * 17 + value) % 251 + 1 for value in range(32))),
                ),
            )
        )
        adapter.submit_egomotion_observation(
            SimpleNamespace(
                session_uuid=session_uuid,
                trajectory=SimpleNamespace(
                    poses=[
                        _adapter_benchmark_pose(
                            timestamp_us - 100_000,
                            x=float(index) * 0.25 - speed_mps * 0.1,
                        ),
                        _adapter_benchmark_pose(
                            timestamp_us,
                            x=float(index) * 0.25,
                        ),
                    ]
                ),
                dynamic_states=[],
            )
        )
        inputs.append((session_uuid, timestamp_us + (index % 5) * 25_000))
    return adapter, inputs


def _adapter_benchmark_pose(timestamp_us: int, *, x: float) -> SimpleNamespace:
    return SimpleNamespace(
        timestamp_us=timestamp_us,
        pose=SimpleNamespace(
            vec=SimpleNamespace(x=x, y=0.0, z=0.0),
            quat=SimpleNamespace(w=1.0, x=0.0, y=0.0, z=0.0),
        ),
    )


def _proto_trajectory_signature(trajectory: Any) -> tuple[tuple[float, ...], ...]:
    signature: list[tuple[float, ...]] = []
    for pose_at_time in list(getattr(trajectory, "poses", []) or []):
        pose = pose_at_time.pose
        signature.append(
            (
                float(pose_at_time.timestamp_us),
                float(pose.vec.x),
                float(pose.vec.y),
                float(pose.vec.z),
                float(pose.quat.w),
                float(pose.quat.x),
                float(pose.quat.y),
                float(pose.quat.z),
            )
        )
    return tuple(signature)


class _BenchmarkCommonPb2:
    class Vec3(SimpleNamespace):
        pass

    class Quat(SimpleNamespace):
        pass

    class Pose(SimpleNamespace):
        pass

    class PoseAtTime(SimpleNamespace):
        pass

    class Trajectory:
        def __init__(self) -> None:
            self.poses: list[Any] = []


class _UncheckedFreshnessGuard:
    def validate(self, _prediction_input: Any) -> dict[str, str]:
        return {"status": "unchecked"}


def _time_call_us(call: Callable[[], Any], *, batch_size: int) -> float:
    start_ns = time.perf_counter_ns()
    for _ in range(batch_size):
        call()
    return (time.perf_counter_ns() - start_ns) / (batch_size * 1_000.0)


def _timing_summary(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"samples": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0}
    return {
        "samples": len(values),
        "mean": sum(values) / len(values),
        "p50": _percentile(values, 50.0),
        "p95": _percentile(values, 95.0),
        "min": min(values),
        "max": max(values),
    }


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100.0
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    alpha = position - lower
    return ordered[lower] * (1.0 - alpha) + ordered[upper] * alpha


def _processor_name() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lower().startswith("model name") and ":" in line:
                return line.split(":", 1)[1].strip()
    return platform.processor() or "unknown"


def _implementation_hashes() -> dict[str, str]:
    repository_root = Path(__file__).resolve().parents[3]
    source_files = (
        Path(__file__).resolve(),
        Path(__file__).with_name("diagnostic_trace_generation.py").resolve(),
        Path(__file__).with_name("trace_diagnostics.py").resolve(),
        Path(inspect.getsourcefile(WOD2SimChallengeAdapter) or "").resolve(),
        Path(inspect.getsourcefile(RouteFollowingAlpaSimModel) or "").resolve(),
    )
    return {
        path.relative_to(repository_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_files
    }
