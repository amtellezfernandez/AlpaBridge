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

import numpy as np

from wod2sim.simulator.baseline_drivers import RouteFollowingAlpaSimModel

from .trace_diagnostics import (
    DEFAULT_CONTEXT,
    FAULT_CODES,
    build_control_traces,
    diagnose_contract_trace,
    load_telemetry_trace,
    mutate_trace,
    status_only_accepts,
    trace_runtime_summary,
)

DEFAULT_RANDOM_SEED = 2027
TRACE_WARMUP_CALLS_PER_CASE = 3
GUARD_WARMUP_CALLS_PER_METHOD = 50


def run_diagnostic_experiment(
    trace_path: Path,
    *,
    timing_iterations: int = 200,
    timing_batch_size: int = 5,
    guard_iterations: int = 200,
    guard_batch_size: int = 20,
    random_seed: int = DEFAULT_RANDOM_SEED,
) -> dict[str, Any]:
    events = load_telemetry_trace(trace_path)
    baseline_diagnostics = diagnose_contract_trace(events, context=DEFAULT_CONTEXT)
    if baseline_diagnostics:
        codes = ", ".join(item.code for item in baseline_diagnostics)
        raise ValueError(f"source trace violates the diagnostic contract: {codes}")
    cases = _build_cases(events)
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
        row["wod2sim_classification_correct"]
        and not row["status_only_classification_correct"]
        for row in case_results
    )
    status_only_correct = sum(
        row["status_only_classification_correct"]
        and not row["wod2sim_classification_correct"]
        for row in case_results
    )

    timing = _benchmark_trace_decisions(
        cases,
        iterations=timing_iterations,
        batch_size=timing_batch_size,
        random_seed=random_seed,
    )
    online_guard = _benchmark_online_guard(
        iterations=guard_iterations,
        batch_size=guard_batch_size,
        random_seed=random_seed,
    )
    source_runtime = trace_runtime_summary(events)
    external_p50_ms = source_runtime["latency_ms"]["p50"]
    if isinstance(external_p50_ms, (int, float)) and external_p50_ms > 0:
        online_guard["incremental_p50_as_source_driver_p50_percent"] = (
            100.0
            * float(online_guard["paired_incremental_us"]["p50"])
            / (float(external_p50_ms) * 1_000.0)
        )
    else:
        online_guard["incremental_p50_as_source_driver_p50_percent"] = None
    total = len(case_results)
    fault_total = len(fault_rows)
    control_total = len(control_rows)
    return {
        "schema": "wod2sim_diagnostic_experiment_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_trace": {
            "path": trace_path.as_posix(),
            "sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
            **source_runtime,
        },
        "design": {
            "fault_cases": fault_total,
            "control_cases": control_total,
            "total_cases": total,
            "fault_codes": list(FAULT_CODES),
            "control_construction": (
                "Fifteen increasing prefixes of the retained external trace, each "
                "terminated by the retained close event."
            ),
            "fault_construction": (
                "One independent field or context mutation per case; the detector "
                "receives only the mutated trace and runtime context."
            ),
            "scoring": (
                "Expected labels are retained by the experiment scorer and are not "
                "passed to diagnose_contract_trace."
            ),
            "random_seed": random_seed,
            "timing_iterations": timing_iterations,
            "timing_batch_size": timing_batch_size,
            "guard_iterations": guard_iterations,
            "guard_batch_size": guard_batch_size,
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
            "paired_mcnemar": {
                "wod2sim_only_correct": wod_only_correct,
                "status_only_only_correct": status_only_correct,
                "exact_two_sided_p": _mcnemar_exact_p(
                    wod_only_correct,
                    status_only_correct,
                ),
            },
        },
        "timing": timing,
        "online_guard_overhead": online_guard,
        "cases": case_results,
        "implementation_sha256": _implementation_hashes(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "processor": _processor_name(),
            "timer": "time.perf_counter_ns",
        },
    }


def _build_cases(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for fault_code in FAULT_CODES:
        mutated, context = mutate_trace(events, fault_code)
        cases.append(
            {
                "case_id": f"fault:{fault_code}",
                "expected_fault_code": fault_code,
                "events": mutated,
                "context": context,
            }
        )
    for index, control in enumerate(build_control_traces(events, count=15), start=1):
        cases.append(
            {
                "case_id": f"control:trace_prefix_{index:02d}",
                "expected_fault_code": "",
                "events": control,
                "context": dict(DEFAULT_CONTEXT),
            }
        )
    return cases


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    diagnostics = diagnose_contract_trace(case["events"], context=case["context"])
    observed_codes = [item.code for item in diagnostics]
    expected_code = str(case["expected_fault_code"])
    expected_valid = not expected_code
    wod_valid = not observed_codes
    status_valid = status_only_accepts(case["context"])
    return {
        "case_id": case["case_id"],
        "event_count": len(case["events"]),
        "expected_valid": expected_valid,
        "expected_fault_code": expected_code,
        "wod2sim_valid": wod_valid,
        "wod2sim_observed_codes": observed_codes,
        "wod2sim_fault_detected": bool(observed_codes),
        "wod2sim_classification_correct": wod_valid == expected_valid,
        "wod2sim_localization_correct": (
            bool(expected_code)
            and len(observed_codes) == 1
            and observed_codes[0] == expected_code
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
        "classification_accuracy_wilson95": _wilson_interval(correct, total),
        "faults_detected": detected,
        "fault_total": fault_total,
        "fault_recall": detected / fault_total,
        "fault_recall_wilson95": _wilson_interval(detected, fault_total),
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
    diagnosis_samples: list[float] = []

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
                    diagnosis_samples.append(elapsed_us)

    wod_summary = _timing_summary(samples["wod2sim"])
    status_summary = _timing_summary(samples["status_only"])
    return {
        "scope": "in-memory post-run classification of parsed telemetry and runtime context",
        "pairing": (
            "Method order is randomized within every case and iteration; reported "
            "samples are per-call batch means."
        ),
        "warmup_calls_per_case_and_method": TRACE_WARMUP_CALLS_PER_CASE,
        "wod2sim_decision_us": wod_summary,
        "status_only_decision_us": status_summary,
        "incremental_decision_p50_us": (
            wod_summary["p50"] - status_summary["p50"]
        ),
        "correct_fault_diagnosis_us": _timing_summary(diagnosis_samples),
        "status_only_correct_fault_diagnoses": 0,
    }


def _benchmark_online_guard(
    *,
    iterations: int,
    batch_size: int,
    random_seed: int,
) -> dict[str, Any]:
    if iterations < 1 or batch_size < 1:
        raise ValueError("guard iterations and batch size must be positive")
    prediction_input = _guard_benchmark_input()
    guarded = RouteFollowingAlpaSimModel(
        camera_ids=["front"],
        context_length=1,
        output_frequency_hz=10,
    )
    unchecked = RouteFollowingAlpaSimModel(
        camera_ids=["front"],
        context_length=1,
        output_frequency_hz=10,
    )
    unchecked._validate_cameras = lambda _images: None  # type: ignore[method-assign]
    unchecked._sensor_freshness_guard = _UncheckedFreshnessGuard()

    guarded_output = guarded.predict(prediction_input)
    unchecked_output = unchecked.predict(prediction_input)
    if not (
        np.array_equal(guarded_output.trajectory_xy, unchecked_output.trajectory_xy)
        and np.array_equal(guarded_output.headings, unchecked_output.headings)
    ):
        raise RuntimeError("guard benchmark produced different trajectories or headings")
    for _ in range(GUARD_WARMUP_CALLS_PER_METHOD):
        guarded.predict(prediction_input)
        unchecked.predict(prediction_input)

    rng = random.Random(random_seed + 1)
    samples: dict[str, list[float]] = {"guarded": [], "unchecked": []}
    paired_overhead: list[float] = []
    for _ in range(iterations):
        round_samples: dict[str, float] = {}
        methods = ["guarded", "unchecked"]
        rng.shuffle(methods)
        for method in methods:
            model = guarded if method == "guarded" else unchecked
            elapsed_us = _time_call_us(
                lambda model=model: model.predict(prediction_input),
                batch_size=batch_size,
            )
            samples[method].append(elapsed_us)
            round_samples[method] = elapsed_us
        paired_overhead.append(round_samples["guarded"] - round_samples["unchecked"])

    guarded_summary = _timing_summary(samples["guarded"])
    unchecked_summary = _timing_summary(samples["unchecked"])
    overhead_summary = _timing_summary(paired_overhead)
    return {
        "scope": (
            "dependency-light route-following prediction; guarded path enables camera "
            "shape/context and sensor-freshness checks, while both paths preserve route "
            "extraction, trajectory generation, resampling, and reasoning serialization"
        ),
        "pairing": (
            "Guarded and unchecked order is randomized per iteration; paired "
            "differences use per-call batch means."
        ),
        "warmup_calls_per_method": GUARD_WARMUP_CALLS_PER_METHOD,
        "trajectory_outputs_equal": True,
        "guarded_prediction_us": guarded_summary,
        "unchecked_prediction_us": unchecked_summary,
        "paired_incremental_us": overhead_summary,
        "paired_incremental_p50_percent": (
            100.0 * overhead_summary["p50"] / unchecked_summary["p50"]
            if unchecked_summary["p50"]
            else None
        ),
    }


def _guard_benchmark_input() -> SimpleNamespace:
    frame = SimpleNamespace(
        timestamp_us=1_000_000,
        image=np.arange(64, dtype=np.uint8).reshape(8, 8),
    )
    pose = SimpleNamespace(timestamp_us=1_000_000, x=0.0, y=0.0, yaw=0.0)
    return SimpleNamespace(
        camera_images={"front": [frame]},
        command=1,
        speed=8.0,
        acceleration=0.0,
        ego_pose_history=[pose],
        route_waypoints=[
            {"x": 0.0, "y": 0.0, "z": 0.0},
            {"x": 30.0, "y": 4.0, "z": 0.0},
            {"x": 60.0, "y": 4.0, "z": 0.0},
        ],
        structured_hazards=[],
        session_uuid="diagnostic-overhead",
        runtime_random_seed=DEFAULT_RANDOM_SEED,
        debug_scene_id="diagnostic-overhead",
        scene_id="diagnostic-overhead",
        time_now_us=1_000_000,
    )


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


def _wilson_interval(successes: int, total: int) -> list[float]:
    if total <= 0:
        return [0.0, 0.0]
    z = 1.959963984540054
    observed = successes / total
    denominator = 1.0 + z * z / total
    center = (observed + z * z / (2.0 * total)) / denominator
    radius = (
        z
        * math.sqrt(
            observed * (1.0 - observed) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return [max(0.0, center - radius), min(1.0, center + radius)]


def _mcnemar_exact_p(left_only_correct: int, right_only_correct: int) -> float:
    discordant = left_only_correct + right_only_correct
    if discordant == 0:
        return 1.0
    smaller = min(left_only_correct, right_only_correct)
    tail = sum(math.comb(discordant, value) for value in range(smaller + 1))
    return min(1.0, 2.0 * tail / (2**discordant))


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
        Path(__file__).with_name("trace_diagnostics.py").resolve(),
        Path(inspect.getsourcefile(RouteFollowingAlpaSimModel) or "").resolve(),
    )
    return {
        path.relative_to(repository_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_files
    }
