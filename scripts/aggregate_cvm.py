from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wod2sim.audit.trace_diagnostics import (
    diagnose_contract_trace,
    load_telemetry_trace,
    trace_runtime_summary,
)
from wod2sim.cli.commands.audit_run import build_report as build_audit_report
from wod2sim.neutral.alpasim_metrics import load_alpasim_metrics

REQUIRED_RUN_FIELDS = (
    "run_id",
    "matrix",
    "policy",
    "scene_id",
    "seed",
    "adapter_config",
    "status",
    "attempted",
    "completed",
    "blocked",
    "failure_layer",
    "failure_code",
    "detail",
    "claim_valid",
)
BOOLEAN_RUN_FIELDS = ("attempted", "completed", "blocked", "claim_valid")
VALID_RUN_STATUSES = {"completed", "failed", "blocked", "planned"}
LEGACY_PLANNED_CODE = "execution_not_requested"
MANIFEST_MATCH_FIELDS = (
    "run_id",
    "matrix",
    "policy",
    "scene_id",
    "seed",
    "adapter_config",
    "status",
)
SYNTHETIC_MATRICES = {"lifecycle_stress", "fault_injection"}
FULL_CONTRACT_ADAPTERS = {"full_contract", "full_temporal_contract"}
PUBLIC_CORE_POLICIES = ("constant_velocity", "route_following")
OPTIONAL_GATED_POLICIES = ("direct_actor_planner", "token_dagger_bc")
REQUIRED_SCENARIO_CATEGORIES = (
    "straight",
    "intersection",
    "lane_change",
    "dense_traffic",
    "occlusion",
    "merge",
)
CLOSED_LOOP_METRICS = (
    "collision_any",
    "collision_at_fault",
    "offroad",
    "progress",
    "progress_rel",
    "plan_deviation",
    "dist_traveled_m",
    "duration_frac_20s",
)
SEMANTIC_PAIR_METRICS = (
    "progress",
    "progress_rel",
    "offroad",
    "collision_any",
    "plan_deviation",
    "dist_to_gt_trajectory",
)
FRAME_FIELDS = (
    "run_id",
    "frame_index",
    "sim_timestamp",
    "observation_timestamp",
    "observation_age_ms",
    "camera_count",
    "route_source",
    "route_waypoint_count",
    "source_trajectory_samples",
    "target_trajectory_samples",
    "trajectory_valid",
    "inference_latency_ms",
    "end_to_end_action_latency_ms",
    "late_message_count",
    "lifecycle_warning_code",
    "policy_reasoning_status_code",
)
PROTOCOL_REPLAY_SOURCE = {
    "alpasim_commit": "049f70fbfe8207e1efd4831a6c3e78a38703d473",
    "asl_sha256": "237d6b55f4da5b0610f1b8b1e940f52d9efdc9e39c8ca2b35c5b5285ebefdc1f",
    "camera_id": "camera_front_wide_120fov",
    "kind": "official Apache-licensed AlpaSim integration replay",
    "reactive_closed_loop": False,
    "url": (
        "https://media.githubusercontent.com/media/NVlabs/alpasim/"
        "049f70fbfe8207e1efd4831a6c3e78a38703d473/"
        "src/runtime/tests/data/integration/rollout.asl"
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate contract-validation matrix rows.")
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    rows = [_normalize_legacy_planned_row(row) for row in _load_run_rows(args.inputs)]
    validation_errors = _validate_run_rows(rows, args.inputs)
    if validation_errors:
        raise SystemExit(
            "Invalid contract-validation aggregate inputs:\n" + "\n".join(validation_errors[:20])
        )
    duplicate_completed = _duplicate_completed_run_ids(rows)
    if duplicate_completed:
        raise SystemExit(f"Duplicate completed run IDs: {', '.join(duplicate_completed[:5])}")

    rows = sorted(rows, key=lambda row: (row.get("matrix", ""), row.get("run_id", "")))
    failures = [row for row in rows if row.get("status") in {"failed", "blocked"}]
    closed_loop_evidence = _closed_loop_evidence(
        rows,
        fallback_rows=_load_existing_evidence(args.output / "closed_loop_metrics.csv"),
    )
    semantic_pair_rows = _semantic_ablation_pair_rows(closed_loop_evidence)
    external_compatibility = _external_compatibility_summary(
        args.output.parent.parent / "external" / "alpasim_e2e_challenge_conformance"
    )
    protocol_replay = _protocol_replay_summary(
        args.output.parent.parent / "external" / "alpasim_protocol_replay"
    )
    diagnostic_experiment = _diagnostic_experiment_summary(
        args.inputs / "diagnostic_experiment.json"
    )
    summary = _summary(
        rows=rows,
        failures=failures,
        closed_loop_evidence=closed_loop_evidence,
        semantic_pair_rows=semantic_pair_rows,
        external_compatibility=external_compatibility,
        protocol_replay=protocol_replay,
        diagnostic_experiment=diagnostic_experiment,
        created_at=_input_created_at(args.inputs),
    )

    _write_csv(args.output / "runs.csv", rows, _fields(rows))
    _write_csv(args.output / "failures.csv", failures, _fields(rows))
    _write_csv(
        args.output / "closed_loop_metrics.csv", closed_loop_evidence, _fields(closed_loop_evidence)
    )
    _write_csv(
        args.output / "semantic_ablation_pairs.csv",
        semantic_pair_rows,
        _fields(semantic_pair_rows),
    )
    _write_summary_csv(args.output / "summary.csv", summary)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    _write_empty_frames(args.output / "frames.csv")
    _write_fault_rollup(args.inputs, args.output / "fault_injection.csv")
    _write_tables(args.output, summary, rows)
    return 0


def _load_run_rows(inputs: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(inputs.rglob("runs.csv")):
        if path.parent == inputs:
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                row["_source"] = str(path)
                rows.append(row)
    return rows


def _validate_run_rows(rows: list[dict[str, str]], inputs: Path) -> list[str]:
    errors: list[str] = []
    if not rows:
        errors.append(f"no_run_rows:{inputs}")
        return errors

    manifest_dir = inputs.parent / "manifests" / "run_manifests"
    for row in rows:
        run_id = row.get("run_id", "")
        source = row.get("_source", "<unknown>")
        for field in REQUIRED_RUN_FIELDS:
            if field not in row:
                errors.append(f"missing_run_field:{source}:{run_id or '<missing-run-id>'}:{field}")
        if not run_id:
            errors.append(f"missing_run_id:{source}")
            continue
        status = row.get("status", "")
        if status not in VALID_RUN_STATUSES:
            errors.append(f"invalid_status:{source}:{run_id}:{status}")
        for field in BOOLEAN_RUN_FIELDS:
            if row.get(field, "") not in {"true", "false"}:
                errors.append(f"invalid_boolean:{source}:{run_id}:{field}={row.get(field, '')}")
        if status == "completed" and row.get("completed") != "true":
            errors.append(f"completed_status_without_completed_flag:{source}:{run_id}")
        if status in {"failed", "blocked"} and not row.get("failure_code"):
            errors.append(f"noncompleted_row_missing_failure_code:{source}:{run_id}")
        if status == "blocked" and row.get("blocked") != "true":
            errors.append(f"blocked_status_without_blocked_flag:{source}:{run_id}")
        if status == "planned" and row.get("blocked") != "false":
            errors.append(f"planned_status_with_blocked_flag:{source}:{run_id}")
        if row.get("claim_valid") == "true" and status != "completed":
            errors.append(f"claim_valid_noncompleted_row:{source}:{run_id}")
        errors.extend(_manifest_consistency_errors(row, manifest_dir=manifest_dir))
    return errors


def _normalize_legacy_planned_row(row: dict[str, str]) -> dict[str, str]:
    if row.get("failure_code") != LEGACY_PLANNED_CODE:
        return row
    normalized = dict(row)
    normalized.update(
        {
            "status": "planned",
            "attempted": "false",
            "completed": "false",
            "blocked": "false",
            "failure_layer": "",
            "failure_code": "",
            "detail": row.get("detail")
            or "Legacy matrix row was expanded and recorded only; pass --execute for launch.",
            "claim_valid": "false",
        }
    )
    return normalized


def _manifest_consistency_errors(row: dict[str, str], *, manifest_dir: Path) -> list[str]:
    run_id = row.get("run_id", "")
    source = row.get("_source", "<unknown>")
    manifest_path = manifest_dir / f"{run_id}.json"
    if not manifest_path.is_file():
        return [f"missing_run_manifest:{source}:{run_id}:{manifest_path}"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [f"invalid_run_manifest_json:{source}:{run_id}:{manifest_path}"]

    errors: list[str] = []
    if manifest.get("schema") != "cvm_run_manifest_v1":
        errors.append(f"invalid_run_manifest_schema:{source}:{run_id}:{manifest_path}")
    manifest = _normalize_legacy_planned_manifest(manifest)
    for field in MANIFEST_MATCH_FIELDS:
        if str(manifest.get(field, "")) != row.get(field, ""):
            errors.append(f"run_manifest_field_mismatch:{source}:{run_id}:{field}")
    for field in BOOLEAN_RUN_FIELDS:
        if _manifest_bool(manifest.get(field)) != row.get(field, ""):
            errors.append(f"run_manifest_field_mismatch:{source}:{run_id}:{field}")
    if str(manifest.get("failure_code", "")) != row.get("failure_code", ""):
        errors.append(f"run_manifest_field_mismatch:{source}:{run_id}:failure_code")
    if str(manifest.get("failure_layer", "")) != row.get("failure_layer", ""):
        errors.append(f"run_manifest_field_mismatch:{source}:{run_id}:failure_layer")
    return errors


def _normalize_legacy_planned_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if str(manifest.get("failure_code", "")) != LEGACY_PLANNED_CODE:
        return manifest
    normalized = dict(manifest)
    normalized.update(
        {
            "status": "planned",
            "attempted": False,
            "completed": False,
            "blocked": False,
            "failure_layer": "",
            "failure_code": "",
            "claim_valid": False,
        }
    )
    return normalized


def _manifest_bool(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).lower()


def _duplicate_completed_run_ids(rows: list[dict[str, str]]) -> list[str]:
    counts = Counter(row["run_id"] for row in rows if row.get("status") == "completed")
    return sorted(run_id for run_id, count in counts.items() if count > 1)


def _external_compatibility_summary(path: Path) -> dict[str, Any]:
    """Summarize optional external evaluator artifacts without changing CVM rows."""
    driver_path = path / "challenge-driver-fixed.jsonl"
    results_path = path / "results-summary.json"
    driver_events: list[dict[str, Any]] = []
    if driver_path.is_file():
        for line in driver_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                driver_events.append(event)

    results: dict[str, Any] = {}
    if results_path.is_file():
        try:
            loaded = json.loads(results_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            results = loaded

    event_counts = Counter(str(event.get("event", "")) for event in driver_events)
    drive_latencies_ms = [
        float(event["latency_ms"])
        for event in driver_events
        if event.get("event") == "drive"
        and isinstance(event.get("latency_ms"), (int, float))
        and math.isfinite(float(event["latency_ms"]))
    ]
    rollouts = results.get("rollouts")
    rollout_items = rollouts if isinstance(rollouts, list) else []
    passed_rollouts = sum(
        1
        for rollout in rollout_items
        if isinstance(rollout, dict)
        and (rollout.get("passed") is True or rollout.get("status") == "pass")
    )
    drive_count = event_counts.get("drive", 0)
    latency_target_met = sum(
        1
        for event in driver_events
        if event.get("event") == "drive" and event.get("latency_target_met") is True
    )
    return {
        "artifact_dir": str(path),
        "available": bool(driver_events or results),
        "rollouts": len(rollout_items),
        "passed_rollouts": passed_rollouts,
        "driver_events": len(driver_events),
        "drive_rpc_count": drive_count,
        "image_event_count": event_counts.get("image", 0),
        "route_event_count": event_counts.get("route", 0),
        "egomotion_event_count": event_counts.get("egomotion", 0),
        "latency_target_met_count": latency_target_met,
        "latency_target_denominator": drive_count,
        "driver_latency_mean_ms": round(sum(drive_latencies_ms) / len(drive_latencies_ms), 3)
        if drive_latencies_ms
        else None,
        "driver_latency_max_ms": round(max(drive_latencies_ms), 3) if drive_latencies_ms else None,
        "score": _external_score(results),
        "claim_boundary": (
            "External evaluator conformance evidence checks interface portability only. It is "
            "not a challenge submission, leaderboard result, policy-quality benchmark, "
            "or scenario-coverage claim."
        ),
    }


def _protocol_replay_summary(path: Path) -> dict[str, Any]:
    """Validate and summarize the current-schema, transport-inclusive replay."""
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        return {
            "artifact_dir": str(path),
            "available": False,
            "claim_boundary": (
                "No protocol replay artifact is present. No client-to-service latency "
                "or replay diagnostic claim is available."
            ),
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid protocol replay manifest JSON: {manifest_path}: {exc}") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != "wod2sim_alpasim_replay_demo_manifest_v1"
    ):
        raise SystemExit(f"Invalid protocol replay manifest schema: {manifest_path}")

    source = manifest.get("source")
    if not isinstance(source, dict) or source != PROTOCOL_REPLAY_SOURCE:
        raise SystemExit(f"Invalid protocol replay source scope: {manifest_path}")
    source_sha256 = source.get("asl_sha256")
    if not isinstance(source_sha256, str) or len(source_sha256) != 64:
        raise SystemExit(f"Invalid protocol replay source hash: {manifest_path}")

    repo_root = path.resolve().parents[2]
    _validate_replay_source_hashes(
        manifest.get("reproduction_sources"),
        repo_root=repo_root,
        manifest_path=manifest_path,
    )
    arms_manifest = manifest.get("arms")
    if not isinstance(arms_manifest, dict):
        raise SystemExit(f"Missing protocol replay arms: {manifest_path}")

    normalized_arms: dict[str, Any] = {}
    for arm_name, expected_codes in (
        ("full_contract", []),
        ("command_only_route", ["semantic.command_only"]),
    ):
        result_path = path / f"{arm_name}.json"
        telemetry_path = path / f"{arm_name}-telemetry.jsonl"
        arm_manifest = arms_manifest.get(arm_name)
        if not isinstance(arm_manifest, dict):
            raise SystemExit(f"Missing protocol replay arm: {manifest_path}:{arm_name}")
        _require_artifact_hash(
            result_path,
            arm_manifest.get("result_sha256"),
            label=f"{arm_name} result",
        )
        _require_artifact_hash(
            telemetry_path,
            arm_manifest.get("telemetry_sha256"),
            label=f"{arm_name} telemetry",
        )
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid protocol replay result JSON: {result_path}: {exc}") from exc
        if not isinstance(result, dict) or result.get("schema") != "wod2sim_alpasim_protocol_replay_v1":
            raise SystemExit(f"Invalid protocol replay result schema: {result_path}")
        result_source = result.get("source")
        adapter = result.get("adapter")
        if (
            not isinstance(result_source, dict)
            or result_source.get("asl_sha256") != source_sha256
            or not isinstance(adapter, dict)
            or adapter.get("mode") != arm_name
        ):
            raise SystemExit(f"Protocol replay arm provenance mismatch: {result_path}")

        events = load_telemetry_trace(telemetry_path)
        diagnostics = diagnose_contract_trace(events)
        diagnostic_dicts = [item.to_dict() for item in diagnostics]
        diagnostic_codes = [item.code for item in diagnostics]
        if diagnostic_codes != expected_codes:
            raise SystemExit(
                f"Protocol replay diagnostics mismatch: {telemetry_path}:"
                f"{','.join(diagnostic_codes)}"
            )
        if diagnostic_dicts != arm_manifest.get("diagnostics"):
            raise SystemExit(f"Protocol replay manifest diagnostics drift: {manifest_path}:{arm_name}")
        runtime = trace_runtime_summary(events)
        if runtime != arm_manifest.get("runtime"):
            raise SystemExit(f"Protocol replay manifest runtime drift: {manifest_path}:{arm_name}")

        results = result.get("results")
        drives = result.get("drives")
        if not isinstance(results, dict) or not isinstance(drives, list):
            raise SystemExit(f"Protocol replay result payload is incomplete: {result_path}")
        drive_calls = results.get("drive_calls")
        finite_outputs = results.get("finite_drive_outputs")
        within_target = results.get("drive_calls_within_target")
        drive_latency = _nested_value(results, "rpc_latency_ms.drive")
        if (
            not isinstance(drive_calls, int)
            or drive_calls != len(drives)
            or not isinstance(finite_outputs, int)
            or finite_outputs != sum(
                row.get("trajectory_finite") is True for row in drives if isinstance(row, dict)
            )
            or not isinstance(within_target, int)
            or not isinstance(drive_latency, dict)
            or drive_latency.get("samples") != drive_calls
        ):
            raise SystemExit(f"Protocol replay result denominator mismatch: {result_path}")
        for metric in ("mean", "p50", "p95", "max"):
            value = drive_latency.get(metric)
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise SystemExit(f"Invalid protocol replay latency: {result_path}:{metric}")
        if results != arm_manifest.get("results"):
            raise SystemExit(f"Protocol replay manifest result drift: {manifest_path}:{arm_name}")
        normalized_arms[arm_name] = {
            "diagnostic_codes": diagnostic_codes,
            "diagnostic_count": len(diagnostic_codes),
            "drive_calls": drive_calls,
            "finite_drive_outputs": finite_outputs,
            "drive_calls_within_target": within_target,
            "latency_target_ms": results.get("latency_target_ms"),
            "drive_rpc_latency_ms": drive_latency,
            "telemetry_runtime": runtime,
            "result_sha256": arm_manifest["result_sha256"],
            "telemetry_sha256": arm_manifest["telemetry_sha256"],
        }

    media = _validated_replay_media(
        manifest.get("media"),
        repo_root=repo_root,
        manifest_path=manifest_path,
    )
    full_camera_names = {
        str(row.get("camera_frame"))
        for row in json.loads((path / "full_contract.json").read_text(encoding="utf-8"))["drives"]
        if isinstance(row, dict) and row.get("camera_frame")
    }
    if media["camera_frames"] != len(full_camera_names):
        raise SystemExit(f"Protocol replay camera denominator mismatch: {manifest_path}")

    return {
        "artifact_dir": str(path),
        "artifact_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "available": True,
        "source": source,
        "execution_environment": manifest.get("execution_environment"),
        "arms": normalized_arms,
        "media": media,
        "claim_boundary": (
            "This is an executed client-to-service gRPC replay of recorded camera, route, "
            "egomotion, and Drive messages. It measures transport-inclusive driver RPC "
            "latency and contract diagnostics. Recorded inputs are non-reactive, so it "
            "does not measure simulator runtime, policy quality, human diagnosis time, "
            "or generalization to another integration framework."
        ),
    }


def _validate_replay_source_hashes(
    value: object,
    *,
    repo_root: Path,
    manifest_path: Path,
) -> None:
    if not isinstance(value, dict) or set(value) != {"client", "renderer", "runner"}:
        raise SystemExit(f"Invalid protocol replay source manifest: {manifest_path}")
    for label, item in value.items():
        if not isinstance(item, dict):
            raise SystemExit(f"Invalid protocol replay source entry: {manifest_path}:{label}")
        relative_path = item.get("path")
        if not isinstance(relative_path, str) or Path(relative_path).is_absolute():
            raise SystemExit(f"Invalid protocol replay source path: {manifest_path}:{label}")
        _require_artifact_hash(
            repo_root / relative_path,
            item.get("sha256"),
            label=f"replay source {label}",
        )


def _validated_replay_media(
    value: object,
    *,
    repo_root: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SystemExit(f"Missing protocol replay media: {manifest_path}")
    camera_frames = value.get("camera_frames")
    duration_seconds = value.get("duration_seconds")
    if (
        not isinstance(camera_frames, int)
        or camera_frames < 1
        or not isinstance(duration_seconds, (int, float))
        or not math.isfinite(float(duration_seconds))
        or float(duration_seconds) <= 0
    ):
        raise SystemExit(f"Invalid protocol replay media counts: {manifest_path}")
    normalized: dict[str, Any] = {
        "camera_frames": camera_frames,
        "duration_seconds": float(duration_seconds),
    }
    for key, expected_format in (
        ("video", "H.264 MP4"),
        ("readme_preview", "animated GIF"),
    ):
        item = value.get(key)
        if not isinstance(item, dict) or item.get("format") != expected_format:
            raise SystemExit(f"Invalid protocol replay media entry: {manifest_path}:{key}")
        relative_path = item.get("path")
        if not isinstance(relative_path, str) or Path(relative_path).is_absolute():
            raise SystemExit(f"Invalid protocol replay media path: {manifest_path}:{key}")
        artifact_path = repo_root / relative_path
        _require_artifact_hash(
            artifact_path,
            item.get("sha256"),
            label=f"replay media {key}",
        )
        if item.get("bytes") != artifact_path.stat().st_size:
            raise SystemExit(f"Protocol replay media size mismatch: {artifact_path}")
        normalized[key] = dict(item)
    return normalized


def _require_artifact_hash(path: Path, expected: object, *, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"Missing {label}: {path}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if not isinstance(expected, str) or actual != expected:
        raise SystemExit(f"{label} sha256 mismatch: {path}: expected {expected}, got {actual}")


def _diagnostic_experiment_summary(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Missing diagnostic experiment artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid diagnostic experiment JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != "wod2sim_diagnostic_experiment_v3":
        raise SystemExit(f"Invalid diagnostic experiment schema: {path}")

    required_numbers = (
        "design.total_cases",
        "design.fault_cases",
        "design.control_cases",
        "classification.wod2sim.classification_correct",
        "classification.wod2sim.faults_detected",
        "classification.wod2sim.faults_correctly_localized",
        "classification.wod2sim.false_positives",
        "classification.status_only.classification_correct",
        "classification.status_only.faults_detected",
        "classification.status_only.false_positives",
        "classification.paired_comparison.discordant_pairs",
        "timing.contract_gate_decision_us.p50",
        "timing.contract_gate_decision_us.p95",
        "timing.fault_case_detector_us.p50",
        "timing.fault_case_detector_us.p95",
        "adapter_guard_path_timing.guarded_drive_path_us.p50",
        "adapter_guard_path_timing.guarded_drive_path_us.p95",
        "adapter_guard_path_timing.paired_incremental_us.p50",
        "adapter_guard_path_timing.paired_incremental_us.p95",
        "adapter_guard_path_timing.paired_incremental_us.samples",
        "adapter_guard_path_timing.input_cases",
        "source_trace.session_count",
        "source_trace.drive_count",
        "source_trace.explicit_finite_drive_count",
    )
    for dotted_path in required_numbers:
        value = _nested_value(payload, dotted_path)
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise SystemExit(
                f"Diagnostic experiment field is missing or non-finite: {path}:{dotted_path}"
            )

    total = int(_nested_value(payload, "design.total_cases"))
    faults = int(_nested_value(payload, "design.fault_cases"))
    controls = int(_nested_value(payload, "design.control_cases"))
    cases = payload.get("cases")
    if total != faults + controls or not isinstance(cases, list) or len(cases) != total:
        raise SystemExit(f"Diagnostic experiment denominator mismatch: {path}")
    pair_counts = Counter(str(case.get("pair_id", "")) for case in cases if isinstance(case, dict))
    if len(pair_counts) != faults or any(
        not pair_id or count != 2 for pair_id, count in pair_counts.items()
    ):
        raise SystemExit(f"Diagnostic experiment pairing mismatch: {path}")
    source_sessions = int(_nested_value(payload, "source_trace.session_count"))
    source_drives = int(_nested_value(payload, "source_trace.drive_count"))
    finite_drives = int(_nested_value(payload, "source_trace.explicit_finite_drive_count"))
    telemetry_schemas = _nested_value(payload, "source_trace.telemetry_schemas")
    if (
        source_sessions != faults
        or finite_drives != source_drives
        or telemetry_schemas != ["wod2sim_challenge_telemetry_v2"]
    ):
        raise SystemExit(f"Diagnostic experiment source-evidence mismatch: {path}")

    result = dict(payload)
    result["artifact_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _nested_value(payload: object, dotted_path: str) -> object:
    value = payload
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _external_score(results: dict[str, Any]) -> float | None:
    rollouts = results.get("rollouts")
    if not isinstance(rollouts, list) or not rollouts:
        return None
    first = rollouts[0]
    if not isinstance(first, dict):
        return None
    score = first.get("score")
    if isinstance(score, (int, float)) and math.isfinite(float(score)):
        return round(float(score), 6)
    return None


def _input_created_at(inputs: Path) -> str:
    timestamps: list[str] = []
    for path in sorted(inputs.rglob("summary.json")):
        if path.parent == inputs:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        created_at = payload.get("created_at")
        if isinstance(created_at, str) and created_at:
            timestamps.append(created_at)
    return max(timestamps) if timestamps else datetime.fromtimestamp(0, timezone.utc).isoformat()


def _summary(
    *,
    rows: list[dict[str, str]],
    failures: list[dict[str, str]],
    closed_loop_evidence: list[dict[str, Any]],
    semantic_pair_rows: list[dict[str, Any]],
    external_compatibility: dict[str, Any],
    protocol_replay: dict[str, Any],
    diagnostic_experiment: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    status_counts = Counter(row.get("status", "") for row in rows)
    matrix_counts = Counter(row.get("matrix", "") for row in rows)
    failure_code_counts = Counter(
        row.get("failure_code", "") for row in rows if row.get("failure_code")
    )
    blocker_counts = Counter(
        row.get("failure_code", "")
        for row in rows
        if row.get("status") == "blocked" and row.get("failure_code")
    )
    metric_summary = _closed_loop_metric_summary(closed_loop_evidence)
    effectiveness_summary = _integration_effectiveness_summary(closed_loop_evidence)
    scenario_coverage_summary = _scenario_coverage_summary(closed_loop_evidence)
    semantic_delta_summary = _semantic_ablation_delta_summary(semantic_pair_rows)
    failure_attribution_summary = _failure_attribution_summary(rows, closed_loop_evidence)
    release_scope_summary = _release_scope_summary(rows, closed_loop_evidence)
    return {
        "schema": "cvm_aggregate_summary_v1",
        "created_at": created_at,
        "data_hash": _hash_rows(
            rows,
            diagnostic_experiment=diagnostic_experiment,
            protocol_replay=protocol_replay,
        ),
        "planned_runs": status_counts.get("planned", 0),
        "attempted_runs": sum(row.get("attempted") == "true" for row in rows),
        "completed_runs": sum(row.get("completed") == "true" for row in rows),
        "synthetic_completed_runs": sum(
            row.get("completed") == "true" and row.get("matrix") in SYNTHETIC_MATRICES
            for row in rows
        ),
        "closed_loop_completed_runs": sum(
            row.get("completed") == "true" and row.get("matrix") not in SYNTHETIC_MATRICES
            for row in rows
        ),
        "closed_loop_audit_valid_runs": sum(
            item.get("audit_valid") == "true" for item in closed_loop_evidence
        ),
        "closed_loop_metric_rows": sum(
            item.get("metrics_present") == "true" for item in closed_loop_evidence
        ),
        "closed_loop_metrics": metric_summary,
        "core_policy_results": _core_policy_results(rows, closed_loop_evidence),
        "public_core_policy_results": _core_policy_results(
            rows,
            closed_loop_evidence,
            include_policies=set(PUBLIC_CORE_POLICIES),
        ),
        "release_scope": release_scope_summary,
        "integration_effectiveness": effectiveness_summary,
        "scenario_coverage": scenario_coverage_summary,
        "failure_attribution": failure_attribution_summary,
        "external_compatibility": external_compatibility,
        "protocol_replay": protocol_replay,
        "diagnostic_experiment": diagnostic_experiment,
        "semantic_ablation_deltas": semantic_delta_summary,
        "failed_runs": status_counts.get("failed", 0),
        "blocked_runs": status_counts.get("blocked", 0),
        "total_rows": len(rows),
        "failure_rows": len(failures),
        "claim_valid": False,
        "status_counts": dict(sorted(status_counts.items())),
        "matrix_counts": dict(sorted(matrix_counts.items())),
        "failure_code_counts": dict(sorted(failure_code_counts.items())),
        "blocker_counts": dict(sorted(blocker_counts.items())),
    }


def _core_policy_results(
    rows: list[dict[str, str]],
    closed_loop_evidence: list[dict[str, Any]],
    *,
    include_policies: set[str] | None = None,
) -> list[dict[str, Any]]:
    core_rows = [row for row in rows if row.get("matrix") == "core"]
    policies = list(dict.fromkeys(row.get("policy", "") for row in core_rows if row.get("policy")))
    if include_policies is not None:
        policies = [policy for policy in policies if policy in include_policies]
    results: list[dict[str, Any]] = []
    for policy in policies:
        policy_rows = [row for row in core_rows if row.get("policy") == policy]
        policy_evidence = [
            row
            for row in closed_loop_evidence
            if row.get("matrix") == "core" and row.get("policy") == policy
        ]
        metric_rows = [row for row in policy_evidence if row.get("metrics_present") == "true"]
        results.append(
            {
                "policy": policy,
                "configured_rows": len(policy_rows),
                "attempted_runs": sum(row.get("attempted") == "true" for row in policy_rows),
                "completed_runs": sum(row.get("completed") == "true" for row in policy_rows),
                "audit_valid_runs": sum(
                    row.get("audit_valid") == "true" for row in policy_evidence
                ),
                "route_valid_runs": sum(
                    row.get("route_contract_ok") == "true" for row in policy_evidence
                ),
                "sensor_valid_runs": sum(
                    row.get("sensor_pipeline_ok") == "true" for row in policy_evidence
                ),
                "metric_rows": len(metric_rows),
                "blocked_runs": sum(row.get("status") == "blocked" for row in policy_rows),
                "progress_mean": _mean_metric(metric_rows, "progress"),
                "collision_any_mean": _mean_metric(metric_rows, "collision_any"),
                "offroad_mean": _mean_metric(metric_rows, "offroad"),
                "action_latency_p95_ms": _mean_metric(metric_rows, "action_latency_p95_ms"),
                "service_crash_rows": _service_crash_rows(policy_rows),
            }
        )
    return results


def _release_scope_summary(
    rows: list[dict[str, str]],
    closed_loop_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    public_core_rows = [
        row
        for row in rows
        if row.get("matrix") == "core" and row.get("policy") in PUBLIC_CORE_POLICIES
    ]
    public_core_evidence = [
        row
        for row in closed_loop_evidence
        if row.get("matrix") == "core" and row.get("policy") in PUBLIC_CORE_POLICIES
    ]
    optional_rows = [
        row
        for row in rows
        if row.get("policy") in OPTIONAL_GATED_POLICIES
        or row.get("failure_code")
        in {"direct_actor_oracle_proxy_missing", "token_checkpoint_missing"}
    ]
    direct_actor_rows = [row for row in rows if row.get("policy") == "direct_actor_planner"]
    return {
        "public_core_policy_names": list(PUBLIC_CORE_POLICIES),
        "optional_gated_policy_names": list(OPTIONAL_GATED_POLICIES),
        "public_core_configured_rows": len(public_core_rows),
        "public_core_attempted_runs": sum(
            row.get("attempted") == "true" for row in public_core_rows
        ),
        "public_core_completed_runs": sum(
            row.get("completed") == "true" for row in public_core_rows
        ),
        "public_core_audit_valid_runs": sum(
            row.get("audit_valid") == "true" for row in public_core_evidence
        ),
        "public_core_blocked_rows": sum(row.get("status") == "blocked" for row in public_core_rows),
        "optional_gated_configured_rows": len(optional_rows),
        "optional_gated_blocked_rows": sum(row.get("status") == "blocked" for row in optional_rows),
        "direct_actor_configured_rows": len(direct_actor_rows),
        "direct_actor_blocked_rows": sum(
            row.get("status") == "blocked" for row in direct_actor_rows
        ),
        "public_learned_checkpoint_bundled": False,
        "restricted_scene_assets_bundled": False,
        "scope_rule": (
            "The public release core is the dependency-light contract adapter path "
            "using constant_velocity and route_following. Direct actor-aware planning, "
            "learned checkpoint execution, restricted scene redistribution, and a full "
            "policy benchmark are optional gated extensions, not release-core "
            "dependencies."
        ),
    }


def _mean_metric(rows: list[dict[str, Any]], metric: str) -> float | None:
    values: list[float] = []
    for row in rows:
        value = row.get(metric)
        try:
            parsed = float(str(value))
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            values.append(parsed)
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _service_crash_rows(rows: list[dict[str, str]]) -> int:
    crashes = 0
    for row in rows:
        code = row.get("failure_code", "").lower()
        detail = row.get("detail", "").lower()
        service_survived = row.get("service_survived", "")
        if service_survived == "false":
            crashes += 1
        elif row.get("status") == "failed" and ("crash" in code or "crash" in detail):
            crashes += 1
    return crashes


def _failure_attribution_summary(
    rows: list[dict[str, str]],
    closed_loop_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Separate integration/evidence validity from policy-behavior attribution."""
    contract_valid_closed_loop = [
        row
        for row in closed_loop_evidence
        if row.get("audit_valid") == "true"
        and row.get("route_contract_ok") == "true"
        and row.get("sensor_pipeline_ok") == "true"
    ]
    integration_invalid_closed_loop = [
        row for row in closed_loop_evidence if row not in contract_valid_closed_loop
    ]
    policy_behavior_run_ids = {
        str(row.get("run_id", ""))
        for row in contract_valid_closed_loop
        if str(row.get("run_id", ""))
    }
    claim_valid_policy_rows = [
        row for row in rows if row.get("claim_valid") == "true" and row.get("status") == "completed"
    ]
    policy_failure_rows = [
        row for row in claim_valid_policy_rows if row.get("failure_layer") == "policy"
    ]
    integration_failure_rows = [
        row
        for row in rows
        if row.get("claim_valid") != "true"
        and row.get("status") in {"blocked", "failed"}
        and bool(row.get("failure_layer"))
    ]
    diagnostic_not_policy_rows = [
        row
        for row in rows
        if row.get("status") == "completed"
        and str(row.get("run_id", "")) not in policy_behavior_run_ids
    ]
    return {
        "rule": (
            "Closed-loop behavior can be attributed to the policy only after the semantic "
            "route contract, temporal adapter, sensor-freshness audit, lifecycle state, "
            "deployment preconditions, and evidence gate pass. Public policy benchmark "
            "claims require the stricter benchmark gate. Rows outside the integration "
            "gate remain integration, precondition, evidence, or diagnostic records and "
            "cannot be counted as policy failures. A policy failure also requires the "
            "retained failure layer to be policy."
        ),
        "contract_valid_closed_loop_rows": len(contract_valid_closed_loop),
        "integration_or_evidence_invalid_closed_loop_rows": len(integration_invalid_closed_loop),
        "precondition_blocked_rows": sum(row.get("status") == "blocked" for row in rows),
        "planned_not_launched_rows": sum(row.get("status") == "planned" for row in rows),
        "synthetic_diagnostic_rows": sum(
            row.get("completed") == "true" and row.get("matrix") in SYNTHETIC_MATRICES
            for row in rows
        ),
        "claim_valid_policy_benchmark_rows": len(claim_valid_policy_rows),
        "policy_behavior_attributable_rows": len(policy_behavior_run_ids),
        "policy_failure_attributable_rows": len(policy_failure_rows),
        "integration_failure_attributable_rows": len(integration_failure_rows),
        "diagnostic_not_policy_rows": len(diagnostic_not_policy_rows),
        "non_policy_attributed_rows": len(rows) - len(policy_behavior_run_ids),
    }


def _hash_rows(
    rows: list[dict[str, str]],
    *,
    diagnostic_experiment: dict[str, Any] | None = None,
    protocol_replay: dict[str, Any] | None = None,
) -> str:
    evidence = {
        "rows": rows,
        "diagnostic_experiment": diagnostic_experiment or {},
        "protocol_replay": protocol_replay or {},
    }
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_existing_evidence(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {row.get("run_id", ""): row for row in csv.DictReader(handle) if row.get("run_id")}


def _closed_loop_evidence(
    rows: list[dict[str, str]],
    *,
    fallback_rows: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    fallback_rows = fallback_rows or {}
    evidence_rows: list[dict[str, Any]] = []
    for row in rows:
        if row.get("status") != "completed" or row.get("matrix") in SYNTHETIC_MATRICES:
            continue
        run_dir = _run_dir_for(row)
        item: dict[str, Any] = {
            "run_id": row.get("run_id", ""),
            "matrix": row.get("matrix", ""),
            "policy": row.get("policy", ""),
            "scene_id": row.get("scene_id", ""),
            "seed": row.get("seed", ""),
            "adapter_config": row.get("adapter_config", ""),
            "run_dir": str(run_dir) if run_dir is not None else "",
            "audit_valid": "false",
            "frame_count": "",
            "route_contract_ok": "",
            "sensor_pipeline_ok": "",
            "metrics_present": "false",
            "metrics_path": "",
        }
        item.update(_manifest_scene_evidence(row))
        if run_dir is None or not run_dir.is_dir():
            fallback = fallback_rows.get(str(row.get("run_id", "")))
            if _fallback_matches_row(fallback, row):
                item.update(fallback or {})
            evidence_rows.append(item)
            continue
        if run_dir is not None and run_dir.is_dir():
            try:
                audit = build_audit_report(run_dir=run_dir)
            except Exception as exc:  # pragma: no cover - defensive evidence retention
                item["audit_error"] = str(exc)
            else:
                item.update(
                    {
                        "audit_valid": "true" if audit.get("valid") is True else "false",
                        "frame_count": str(audit.get("frame_count", "")),
                        "route_contract_ok": "true"
                        if audit.get("route_contract_ok") is True
                        else "false",
                        "sensor_pipeline_ok": "true"
                        if audit.get("sensor_pipeline_ok") is True
                        else "false",
                    }
                )
            try:
                metrics_path, metrics, _run_count = load_alpasim_metrics(run_dir)
            except Exception as exc:  # pragma: no cover - defensive evidence retention
                item["metrics_error"] = str(exc)
            else:
                item["metrics_present"] = "true"
                item["metrics_path"] = str(metrics_path)
                for metric in CLOSED_LOOP_METRICS:
                    value = metrics.get(metric)
                    if isinstance(value, (int, float)) and math.isfinite(float(value)):
                        item[metric] = f"{float(value):.6g}"
        evidence_rows.append(item)
    return evidence_rows


def _manifest_scene_evidence(row: dict[str, str]) -> dict[str, str]:
    manifest_path = _manifest_path_for(row)
    if manifest_path is None or not manifest_path.is_file():
        return {
            "scenario_category": "",
            "categories_verified": "false",
            "asset_availability": "",
            "license_gating_status": "",
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "scenario_category": "",
            "categories_verified": "false",
            "asset_availability": "",
            "license_gating_status": "",
        }
    scene = manifest.get("scene") if isinstance(manifest.get("scene"), dict) else {}
    categories_verified = scene.get("categories_verified")
    return {
        "scenario_category": str(
            manifest.get("scenario_category")
            or scene.get("scenario_category")
            or scene.get("category")
            or ""
        ),
        "categories_verified": "true" if categories_verified is True else "false",
        "asset_availability": str(scene.get("asset_availability", "")),
        "license_gating_status": str(scene.get("license_gating_status", "")),
    }


def _manifest_path_for(row: dict[str, str]) -> Path | None:
    run_id = str(row.get("run_id", ""))
    source = str(row.get("_source", ""))
    if not run_id or not source:
        return None
    source_path = Path(source)
    if len(source_path.parents) >= 3 and source_path.parent.parent.name == "results":
        return source_path.parent.parent.parent / "manifests" / "run_manifests" / f"{run_id}.json"
    return source_path.parent / "run_manifests" / f"{run_id}.json"


def _fallback_matches_row(
    fallback: dict[str, str] | None,
    row: dict[str, str],
) -> bool:
    if fallback is None:
        return False
    for field in ("run_id", "matrix", "policy", "scene_id", "seed", "adapter_config"):
        if fallback.get(field, "") != row.get(field, ""):
            return False
    return True


def _run_dir_for(row: dict[str, str]) -> Path | None:
    source = row.get("_source", "")
    if not source:
        return None
    return Path(source).parent / "run_dirs" / _safe_filename(row.get("run_id", ""))


def _safe_filename(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in "._-" else "_" for character in value
    )


def _closed_loop_metric_summary(
    evidence_rows: list[dict[str, Any]],
) -> dict[str, dict[str, float | int]]:
    summary: dict[str, dict[str, float | int]] = {}
    for metric in CLOSED_LOOP_METRICS:
        values: list[float] = []
        for row in evidence_rows:
            value = row.get(metric)
            try:
                parsed = float(str(value))
            except (TypeError, ValueError):
                continue
            if math.isfinite(parsed):
                values.append(parsed)
        if values:
            summary[metric] = {
                "count": len(values),
                "mean": round(sum(values) / len(values), 6),
                "min": round(min(values), 6),
                "max": round(max(values), 6),
            }
    return summary


def _integration_effectiveness_summary(evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    full_contract_rows = [
        row for row in evidence_rows if row.get("adapter_config") in FULL_CONTRACT_ADAPTERS
    ]
    full_contract_audit_valid = [
        row for row in full_contract_rows if row.get("audit_valid") == "true"
    ]
    semantic_rows = [row for row in evidence_rows if row.get("matrix") == "semantic_ablation"]
    semantic_pairs = _semantic_ablation_pairs(semantic_rows)
    command_proxy_rows = [
        row for row in semantic_rows if row.get("adapter_config") == "command_only_route"
    ]
    command_proxy_rejected = [
        row
        for row in command_proxy_rows
        if row.get("route_contract_ok") == "false" or row.get("audit_valid") == "false"
    ]
    command_proxy_metric_rows = [
        row for row in command_proxy_rows if row.get("metrics_present") == "true"
    ]
    invalid_rejection_denominator = len(command_proxy_rows)
    invalid_rejection_rate = (
        None
        if invalid_rejection_denominator == 0
        else round(len(command_proxy_rejected) / invalid_rejection_denominator, 6)
    )
    return {
        "rule": (
            "Integration-effectiveness is measured on executed closed-loop rows: "
            "completed full-contract rollouts are audited, and completed metric-bearing "
            "command-only rows are compared with a defined status-only acceptance "
            "baseline before route-invalid evidence is rejected."
        ),
        "full_contract_completed_runs": len(full_contract_rows),
        "full_contract_audit_valid_runs": len(full_contract_audit_valid),
        "semantic_ablation_completed_pairs": semantic_pairs["completed_pairs"],
        "semantic_ablation_comparison_eligible_pairs": semantic_pairs["comparison_eligible_pairs"],
        "semantic_ablation_command_proxy_completed_runs": len(command_proxy_rows),
        "semantic_ablation_command_proxy_metric_runs": len(command_proxy_metric_rows),
        "semantic_ablation_command_proxy_rejected_runs": len(command_proxy_rejected),
        "status_only_baseline_accepted_runs": len(command_proxy_metric_rows),
        "status_only_baseline_acceptance_denominator": len(command_proxy_rows),
        "contract_invalid_evidence_rejected_runs": len(command_proxy_rejected),
        "contract_invalid_evidence_rejection_denominator": invalid_rejection_denominator,
        "contract_invalid_evidence_rejection_rate": invalid_rejection_rate,
        "status_only_accepted_contract_rejected_runs": sum(
            row.get("metrics_present") == "true"
            and (row.get("route_contract_ok") == "false" or row.get("audit_valid") == "false")
            for row in command_proxy_rows
        ),
    }


def _scenario_coverage_summary(evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    scene_rows: dict[str, dict[str, Any]] = {}
    for row in evidence_rows:
        scene_id = str(row.get("scene_id", ""))
        if not scene_id:
            continue
        scene_rows.setdefault(scene_id, row)

    verified_categories = sorted(
        {
            str(row.get("scenario_category", ""))
            for row in scene_rows.values()
            if row.get("categories_verified") == "true"
            and str(row.get("scenario_category", ""))
            and "unclassified" not in str(row.get("scenario_category", ""))
        }
    )
    required_categories = set(REQUIRED_SCENARIO_CATEGORIES)
    verified_required = sorted(required_categories.intersection(verified_categories))
    unclassified_scene_count = sum(
        row.get("categories_verified") != "true"
        or "unclassified" in str(row.get("scenario_category", ""))
        for row in scene_rows.values()
    )
    coverage_claimed = (
        bool(scene_rows)
        and unclassified_scene_count == 0
        and required_categories.issubset(set(verified_categories))
    )
    return {
        "rule": (
            "Scenario-category coverage can be claimed only when authoritative metadata "
            "verifies each required category for the retained closed-loop scene set. "
            "Availability-selected unclassified scenes count as integration instances, "
            "not as coverage evidence."
        ),
        "closed_loop_scene_count": len(scene_rows),
        "required_category_count": len(REQUIRED_SCENARIO_CATEGORIES),
        "required_categories": list(REQUIRED_SCENARIO_CATEGORIES),
        "verified_required_category_count": len(verified_required),
        "verified_required_categories": verified_required,
        "verified_category_count": len(verified_categories),
        "verified_categories": verified_categories,
        "unclassified_closed_loop_scene_count": unclassified_scene_count,
        "scenario_category_coverage_claimed": coverage_claimed,
        "scenario_category_coverage_claimed_int": 1 if coverage_claimed else 0,
    }


def _semantic_ablation_pairs(evidence_rows: list[dict[str, Any]]) -> dict[str, int]:
    grouped: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = {}
    for row in evidence_rows:
        key = (
            str(row.get("policy", "")),
            str(row.get("scene_id", "")),
            str(row.get("seed", "")),
        )
        grouped.setdefault(key, {})[str(row.get("adapter_config", ""))] = row
    completed_pairs = 0
    comparison_eligible_pairs = 0
    for adapters in grouped.values():
        full = adapters.get("full_contract")
        command_only = adapters.get("command_only_route")
        if full is None or command_only is None:
            continue
        completed_pairs += 1
        if _semantic_pair_comparison_eligible(full, command_only):
            comparison_eligible_pairs += 1
    return {
        "completed_pairs": completed_pairs,
        "comparison_eligible_pairs": comparison_eligible_pairs,
    }


def _semantic_pair_comparison_eligible(
    full: dict[str, Any],
    command_only: dict[str, Any],
) -> bool:
    return (
        full.get("metrics_present") == "true"
        and command_only.get("metrics_present") == "true"
        and full.get("audit_valid") == "true"
        and full.get("route_contract_ok") == "true"
        and command_only.get("audit_valid") == "false"
        and command_only.get("route_contract_ok") == "false"
    )


def _semantic_ablation_pair_rows(evidence_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = {}
    for row in evidence_rows:
        if row.get("matrix") != "semantic_ablation":
            continue
        key = (
            str(row.get("policy", "")),
            str(row.get("scene_id", "")),
            str(row.get("seed", "")),
        )
        grouped.setdefault(key, {})[str(row.get("adapter_config", ""))] = row

    pair_rows: list[dict[str, Any]] = []
    for key in sorted(grouped):
        adapters = grouped[key]
        full = adapters.get("full_contract")
        command_only = adapters.get("command_only_route")
        if full is None or command_only is None:
            continue
        comparison_eligible = _semantic_pair_comparison_eligible(full, command_only)
        row: dict[str, Any] = {
            "policy": key[0],
            "scene_id": key[1],
            "seed": key[2],
            "full_run_id": full.get("run_id", ""),
            "command_only_run_id": command_only.get("run_id", ""),
            "full_audit_valid": full.get("audit_valid", ""),
            "command_only_audit_valid": command_only.get("audit_valid", ""),
            "full_route_contract_ok": full.get("route_contract_ok", ""),
            "command_only_route_contract_ok": command_only.get("route_contract_ok", ""),
            "metrics_present": "true"
            if full.get("metrics_present") == "true"
            and command_only.get("metrics_present") == "true"
            else "false",
            "comparison_eligible": "true" if comparison_eligible else "false",
        }
        for metric in SEMANTIC_PAIR_METRICS:
            full_value = _metric_float(full, metric)
            command_value = _metric_float(command_only, metric)
            row[f"full_{metric}"] = "" if full_value is None else f"{full_value:.6g}"
            row[f"command_only_{metric}"] = "" if command_value is None else f"{command_value:.6g}"
            row[f"delta_{metric}"] = (
                ""
                if full_value is None or command_value is None
                else f"{(full_value - command_value):.6g}"
            )
        pair_rows.append(row)
    return pair_rows


def _semantic_ablation_delta_summary(
    pair_rows: list[dict[str, Any]],
) -> dict[str, dict[str, float | int]]:
    summary: dict[str, dict[str, float | int]] = {}
    for metric in SEMANTIC_PAIR_METRICS:
        values: list[float] = []
        key = f"delta_{metric}"
        for row in pair_rows:
            if row.get("comparison_eligible") != "true":
                continue
            try:
                value = float(str(row.get(key, "")))
            except ValueError:
                continue
            if math.isfinite(value):
                values.append(value)
        if values:
            summary[metric] = {
                "count": len(values),
                "mean_delta_full_minus_command_only": round(sum(values) / len(values), 6),
                "median_delta": round(statistics.median(values), 6),
                "min_delta": round(min(values), 6),
                "max_delta": round(max(values), 6),
                "positive_count": sum(value > 0 for value in values),
                "negative_count": sum(value < 0 for value in values),
                "zero_count": sum(value == 0 for value in values),
            }
    return summary


def _metric_float(row: dict[str, Any], metric: str) -> float | None:
    try:
        value = float(str(row.get(metric, "")))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _fields(rows: list[dict[str, str]]) -> list[str]:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    return fields or ["run_id", "status"]


def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_summary_csv(path: Path, summary: dict[str, Any]) -> None:
    fields = [
        "total_rows",
        "planned_runs",
        "attempted_runs",
        "completed_runs",
        "synthetic_completed_runs",
        "closed_loop_completed_runs",
        "closed_loop_audit_valid_runs",
        "closed_loop_metric_rows",
        "full_contract_audit_valid_runs",
        "semantic_ablation_completed_pairs",
        "semantic_ablation_comparison_eligible_pairs",
        "semantic_ablation_command_proxy_metric_runs",
        "status_only_baseline_accepted_runs",
        "status_only_baseline_acceptance_denominator",
        "contract_invalid_evidence_rejected_runs",
        "contract_invalid_evidence_rejection_denominator",
        "status_only_accepted_contract_rejected_runs",
        "public_core_configured_rows",
        "public_core_completed_runs",
        "public_core_blocked_rows",
        "optional_gated_configured_rows",
        "optional_gated_blocked_rows",
        "direct_actor_blocked_rows",
        "closed_loop_scene_count",
        "verified_required_category_count",
        "required_category_count",
        "unclassified_closed_loop_scene_count",
        "scenario_category_coverage_claimed",
        "scenario_category_coverage_claimed_int",
        "contract_valid_closed_loop_rows",
        "integration_or_evidence_invalid_closed_loop_rows",
        "claim_valid_policy_benchmark_rows",
        "policy_behavior_attributable_rows",
        "policy_failure_attributable_rows",
        "integration_failure_attributable_rows",
        "diagnostic_not_policy_rows",
        "non_policy_attributed_rows",
        "failed_runs",
        "blocked_runs",
        "claim_valid",
        "data_hash",
    ]
    effectiveness = summary.get("integration_effectiveness", {})
    scenario_coverage = summary.get("scenario_coverage", {})
    attribution = summary.get("failure_attribution", {})
    release_scope = summary.get("release_scope", {})
    row: dict[str, str] = {}
    for field in fields:
        if field in summary:
            row[field] = str(summary[field])
        elif isinstance(effectiveness, dict) and field in effectiveness:
            row[field] = str(effectiveness[field])
        elif isinstance(scenario_coverage, dict) and field in scenario_coverage:
            row[field] = str(scenario_coverage[field])
        elif isinstance(attribution, dict) and field in attribution:
            row[field] = str(attribution[field])
        elif isinstance(release_scope, dict) and field in release_scope:
            row[field] = str(release_scope[field])
        else:
            row[field] = ""
    _write_csv(path, [row], fields)


def _write_empty_frames(path: Path) -> None:
    _write_csv(path, [], list(FRAME_FIELDS))


def _write_fault_rollup(inputs: Path, output: Path) -> None:
    rows: list[dict[str, str]] = []
    for path in sorted(inputs.rglob("fault_injection.csv")):
        if path == output:
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            rows.extend(csv.DictReader(handle))
    fields = list(rows[0].keys()) if rows else ["injection", "status"]
    _write_csv(output, rows, fields)


def _core_policy_table_rows(summary: dict[str, Any]) -> list[str]:
    results = summary.get("public_core_policy_results")
    if not isinstance(results, list):
        return []
    rows: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        completed = _summary_int(item, "completed_runs")
        attempted = _summary_int(item, "attempted_runs")
        audit_valid = _summary_int(item, "audit_valid_runs")
        route_valid = _summary_int(item, "route_valid_runs")
        sensor_valid = _summary_int(item, "sensor_valid_runs")
        blocked = _summary_int(item, "blocked_runs")
        rows.append(
            f"{_latex_text(str(item.get('policy', '')))} & "
            f"{_summary_int(item, 'configured_rows')} & "
            f"{completed}/{attempted} & "
            f"{audit_valid}/{completed} & "
            f"{route_valid}/{completed} & "
            f"{sensor_valid}/{completed} & "
            f"{_summary_int(item, 'service_crash_rows')} & "
            f"{blocked} \\\\"
        )
    return rows


def _format_table_metric(value: object) -> str:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return "--"
    return f"{float(value):.3f}"


def _latex_text(value: str) -> str:
    return value.replace("\\", r"\textbackslash{}").replace("_", r"\_")


def _write_tables(output: Path, summary: dict[str, Any], rows: list[dict[str, str]]) -> None:
    tables = output.parent / "tables" if output.name == "results" else output / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    data_hash = summary["data_hash"]
    lifecycle_full_total = sum(
        row.get("matrix") == "lifecycle_stress"
        and row.get("adapter_config") == "full_lifecycle_hardening"
        for row in rows
    )
    lifecycle_full_survived = sum(
        row.get("matrix") == "lifecycle_stress"
        and row.get("adapter_config") == "full_lifecycle_hardening"
        and row.get("service_survived") == "true"
        for row in rows
    )
    lifecycle_strict_total = sum(
        row.get("matrix") == "lifecycle_stress"
        and row.get("adapter_config") == "strict_or_pre_hardening_behavior"
        for row in rows
    )
    lifecycle_strict_survived = sum(
        row.get("matrix") == "lifecycle_stress"
        and row.get("adapter_config") == "strict_or_pre_hardening_behavior"
        and row.get("service_survived") == "true"
        for row in rows
    )
    fault_total = sum(row.get("matrix") == "fault_injection" for row in rows)
    fault_detected = sum(
        row.get("matrix") == "fault_injection" and row.get("detected") == "true" for row in rows
    )
    fault_localized = sum(
        row.get("matrix") == "fault_injection" and row.get("correctly_localized") == "true"
        for row in rows
    )
    effectiveness = summary.get("integration_effectiveness", {})
    full_contract_completed = _summary_int(effectiveness, "full_contract_completed_runs")
    full_contract_audit_valid = _summary_int(effectiveness, "full_contract_audit_valid_runs")
    semantic_completed_pairs = _summary_int(effectiveness, "semantic_ablation_completed_pairs")
    semantic_eligible_pairs = _summary_int(
        effectiveness, "semantic_ablation_comparison_eligible_pairs"
    )
    command_proxy_completed = _summary_int(
        effectiveness, "semantic_ablation_command_proxy_completed_runs"
    )
    command_proxy_rejected = _summary_int(
        effectiveness, "semantic_ablation_command_proxy_rejected_runs"
    )
    status_only_accepted = _summary_int(effectiveness, "status_only_baseline_accepted_runs")
    status_only_denominator = _summary_int(
        effectiveness, "status_only_baseline_acceptance_denominator"
    )
    contract_invalid_rejected = _summary_int(
        effectiveness, "contract_invalid_evidence_rejected_runs"
    )
    contract_invalid_denominator = _summary_int(
        effectiveness, "contract_invalid_evidence_rejection_denominator"
    )
    status_only_accepted_contract_rejected = _summary_int(
        effectiveness, "status_only_accepted_contract_rejected_runs"
    )
    attribution = summary.get("failure_attribution", {})
    scenario_coverage = summary.get("scenario_coverage", {})
    closed_loop_scene_count = _summary_int(scenario_coverage, "closed_loop_scene_count")
    required_category_count = _summary_int(scenario_coverage, "required_category_count")
    verified_required_category_count = _summary_int(
        scenario_coverage, "verified_required_category_count"
    )
    unclassified_closed_loop_scene_count = _summary_int(
        scenario_coverage, "unclassified_closed_loop_scene_count"
    )
    scenario_category_coverage_claimed = (
        1 if scenario_coverage.get("scenario_category_coverage_claimed") is True else 0
    )
    contract_valid_closed_loop = _summary_int(attribution, "contract_valid_closed_loop_rows")
    integration_invalid_closed_loop = _summary_int(
        attribution, "integration_or_evidence_invalid_closed_loop_rows"
    )
    claim_valid_policy_benchmark = _summary_int(attribution, "claim_valid_policy_benchmark_rows")
    policy_behavior_attributable = _summary_int(attribution, "policy_behavior_attributable_rows")
    policy_failure_attributable = _summary_int(attribution, "policy_failure_attributable_rows")
    integration_failure_attributable = _summary_int(
        attribution, "integration_failure_attributable_rows"
    )
    diagnostic_not_policy = _summary_int(attribution, "diagnostic_not_policy_rows")
    non_policy_attributed = _summary_int(attribution, "non_policy_attributed_rows")
    synthetic_diagnostic = _summary_int(attribution, "synthetic_diagnostic_rows")
    release_scope = summary.get("release_scope", {})
    external = summary.get("external_compatibility", {})
    replay = summary.get("protocol_replay", {})
    replay_arms = replay.get("arms", {}) if isinstance(replay, dict) else {}
    replay_full = replay_arms.get("full_contract", {}) if isinstance(replay_arms, dict) else {}
    replay_command = (
        replay_arms.get("command_only_route", {}) if isinstance(replay_arms, dict) else {}
    )
    replay_media = replay.get("media", {}) if isinstance(replay, dict) else {}
    diagnostic = summary.get("diagnostic_experiment", {})
    diagnostic_design = diagnostic.get("design", {}) if isinstance(diagnostic, dict) else {}
    diagnostic_classification = (
        diagnostic.get("classification", {}) if isinstance(diagnostic, dict) else {}
    )
    diagnostic_wod2sim = (
        diagnostic_classification.get("wod2sim", {})
        if isinstance(diagnostic_classification, dict)
        else {}
    )
    diagnostic_status = (
        diagnostic_classification.get("status_only", {})
        if isinstance(diagnostic_classification, dict)
        else {}
    )
    diagnostic_paired = (
        diagnostic_classification.get("paired_comparison", {})
        if isinstance(diagnostic_classification, dict)
        else {}
    )
    diagnostic_source = diagnostic.get("source_trace", {}) if isinstance(diagnostic, dict) else {}
    diagnostic_adapter = (
        diagnostic.get("adapter_guard_path_timing", {}) if isinstance(diagnostic, dict) else {}
    )
    public_core_configured = _summary_int(release_scope, "public_core_configured_rows")
    public_core_completed = _summary_int(release_scope, "public_core_completed_runs")
    public_core_attempted = _summary_int(release_scope, "public_core_attempted_runs")
    public_core_audit_valid = _summary_int(release_scope, "public_core_audit_valid_runs")
    public_core_blocked = _summary_int(release_scope, "public_core_blocked_rows")
    optional_gated_configured = _summary_int(release_scope, "optional_gated_configured_rows")
    optional_gated_blocked = _summary_int(release_scope, "optional_gated_blocked_rows")
    direct_actor_configured = _summary_int(release_scope, "direct_actor_configured_rows")
    direct_actor_blocked = _summary_int(release_scope, "direct_actor_blocked_rows")
    (tables / "contract_map.tex").write_text(
        "% generated by contract-validation aggregate; data_hash="
        + data_hash
        + "\n"
        + "\\begin{tabular}{llll}\n"
        + "\\toprule\nMismatch & Contract & Mechanism & Validation \\\\\n"
        + "\\midrule\n"
        + "Command-only route & Semantic & Preserve route geometry & route-source audit \\\\\n"
        + "Policy horizon/runtime grid & Temporal & Deterministic resampling & cadence tests \\\\\n"
        + "Script flow/session service & Lifecycle & Idempotent late-event handling & lifecycle tests \\\\\n"
        + "Implicit host state & Deployment & Materialized manifests & readiness checks \\\\\n"
        + "Process exit/evidence & Evidence & Audit-valid summaries & claim gate \\\\\n"
        + "\\bottomrule\n\\end{tabular}\n",
        encoding="utf-8",
    )
    core_policy_rows = _core_policy_table_rows(summary)
    (tables / "main_results.tex").write_text(
        "% generated by contract-validation aggregate; data_hash="
        + data_hash
        + "\n"
        + "\\begin{tabular}{llllllll}\n"
        + "\\toprule\n"
        + "Public core policy & Rows & Done/att. & Audit & Route & Sensor & Crash & Blocked \\\\\n"
        + "\\midrule\n"
        + "\n".join(core_policy_rows)
        + "\n"
        + "\\bottomrule\n\\end{tabular}\n",
        encoding="utf-8",
    )
    (tables / "ablations.tex").write_text(
        "% generated by contract-validation aggregate; data_hash="
        + data_hash
        + "\n"
        + "\\begin{tabular}{lrrl}\n"
        + "\\toprule\nClosed-loop check & Obs. & Denom. & Meaning \\\\\n"
        + "\\midrule\n"
        + f"Full-contract audit-valid & {full_contract_audit_valid} & {full_contract_completed} & audit passed \\\\\n"
        + f"Comparison-eligible pairs & {semantic_eligible_pairs} & {semantic_completed_pairs} & valid/invalid arms \\\\\n"
        + f"Status-only baseline accepted & {status_only_accepted} & {status_only_denominator} & completion + metrics \\\\\n"
        + f"Invalid route rows rejected & {contract_invalid_rejected} & {contract_invalid_denominator} & route gate \\\\\n"
        + f"Verified scenario categories & {verified_required_category_count} & {required_category_count} & coverage withheld \\\\\n"
        + "\\bottomrule\n\\end{tabular}\n",
        encoding="utf-8",
    )
    (tables / "fault_localization.tex").write_text(
        "% generated by contract-validation aggregate; data_hash="
        + data_hash
        + "\n"
        + "\\begin{tabular}{lrr}\n"
        + "\\toprule\nSynthetic diagnostic & Count & Total \\\\\n"
        + "\\midrule\n"
        + f"Lifecycle hardening survived & {lifecycle_full_survived} & {lifecycle_full_total} \\\\\n"
        + f"Pre-hardening survived & {lifecycle_strict_survived} & {lifecycle_strict_total} \\\\\n"
        + f"Faults detected & {fault_detected} & {fault_total} \\\\\n"
        + f"Faults localized & {fault_localized} & {fault_total} \\\\\n"
        + "\\bottomrule\n\\end{tabular}\n",
        encoding="utf-8",
    )
    matrix_counts = summary.get("matrix_counts", {})
    (tables / "paper_numbers.tex").write_text(
        "% generated by contract-validation aggregate; data_hash="
        + data_hash
        + "\n"
        + f"\\newcommand{{\\CVMTotalRows}}{{{summary['total_rows']}}}\n"
        + f"\\newcommand{{\\CVMPlannedRuns}}{{{summary['planned_runs']}}}\n"
        + f"\\newcommand{{\\CVMAttemptedRuns}}{{{summary['attempted_runs']}}}\n"
        + f"\\newcommand{{\\CVMCompletedRuns}}{{{summary['completed_runs']}}}\n"
        + f"\\newcommand{{\\CVMSyntheticCompletedRuns}}{{{summary['synthetic_completed_runs']}}}\n"
        + f"\\newcommand{{\\CVMClosedLoopCompletedRuns}}{{{summary['closed_loop_completed_runs']}}}\n"
        + f"\\newcommand{{\\CVMClosedLoopAuditValidRuns}}{{{summary['closed_loop_audit_valid_runs']}}}\n"
        + f"\\newcommand{{\\CVMClosedLoopMetricRows}}{{{summary['closed_loop_metric_rows']}}}\n"
        + f"\\newcommand{{\\CVMFullContractCompletedRuns}}{{{full_contract_completed}}}\n"
        + f"\\newcommand{{\\CVMFullContractAuditValidRuns}}{{{full_contract_audit_valid}}}\n"
        + f"\\newcommand{{\\CVMClosedLoopSceneCount}}{{{closed_loop_scene_count}}}\n"
        + f"\\newcommand{{\\CVMRequiredScenarioCategoryCount}}{{{required_category_count}}}\n"
        + f"\\newcommand{{\\CVMVerifiedRequiredScenarioCategoryCount}}{{{verified_required_category_count}}}\n"
        + f"\\newcommand{{\\CVMUnclassifiedClosedLoopSceneCount}}{{{unclassified_closed_loop_scene_count}}}\n"
        + f"\\newcommand{{\\CVMScenarioCategoryCoverageClaimed}}{{{scenario_category_coverage_claimed}}}\n"
        + f"\\newcommand{{\\CVMContractValidClosedLoopRows}}{{{contract_valid_closed_loop}}}\n"
        + f"\\newcommand{{\\CVMIntegrationInvalidClosedLoopRows}}{{{integration_invalid_closed_loop}}}\n"
        + f"\\newcommand{{\\CVMClaimValidPolicyBenchmarkRows}}{{{claim_valid_policy_benchmark}}}\n"
        + f"\\newcommand{{\\CVMPolicyBehaviorAttributableRows}}{{{policy_behavior_attributable}}}\n"
        + f"\\newcommand{{\\CVMPolicyFailureAttributableRows}}{{{policy_failure_attributable}}}\n"
        + f"\\newcommand{{\\CVMIntegrationFailureAttributableRows}}{{{integration_failure_attributable}}}\n"
        + f"\\newcommand{{\\CVMDiagnosticNotPolicyRows}}{{{diagnostic_not_policy}}}\n"
        + f"\\newcommand{{\\CVMNonPolicyAttributedRows}}{{{non_policy_attributed}}}\n"
        + f"\\newcommand{{\\CVMSyntheticDiagnosticRows}}{{{synthetic_diagnostic}}}\n"
        + f"\\newcommand{{\\CVMPublicCoreRows}}{{{public_core_configured}}}\n"
        + f"\\newcommand{{\\CVMPublicCoreCompletedRuns}}{{{public_core_completed}}}\n"
        + f"\\newcommand{{\\CVMPublicCoreAttemptedRuns}}{{{public_core_attempted}}}\n"
        + f"\\newcommand{{\\CVMPublicCoreAuditValidRuns}}{{{public_core_audit_valid}}}\n"
        + f"\\newcommand{{\\CVMPublicCoreBlockedRows}}{{{public_core_blocked}}}\n"
        + f"\\newcommand{{\\CVMOptionalGatedRows}}{{{optional_gated_configured}}}\n"
        + f"\\newcommand{{\\CVMOptionalGatedBlockedRows}}{{{optional_gated_blocked}}}\n"
        + f"\\newcommand{{\\CVMDirectActorRows}}{{{direct_actor_configured}}}\n"
        + f"\\newcommand{{\\CVMDirectActorBlockedRows}}{{{direct_actor_blocked}}}\n"
        + f"\\newcommand{{\\CVMSemanticAblationCompletedPairs}}{{{semantic_completed_pairs}}}\n"
        + f"\\newcommand{{\\CVMSemanticAblationEligiblePairs}}{{{semantic_eligible_pairs}}}\n"
        + f"\\newcommand{{\\CVMCommandProxyCompletedRuns}}{{{command_proxy_completed}}}\n"
        + f"\\newcommand{{\\CVMCommandProxyRejectedRuns}}{{{command_proxy_rejected}}}\n"
        + f"\\newcommand{{\\CVMStatusOnlyAcceptedRuns}}{{{status_only_accepted}}}\n"
        + f"\\newcommand{{\\CVMStatusOnlyAcceptanceDenominator}}{{{status_only_denominator}}}\n"
        + f"\\newcommand{{\\CVMContractInvalidRejectedRuns}}{{{contract_invalid_rejected}}}\n"
        + f"\\newcommand{{\\CVMContractInvalidRejectionDenominator}}{{{contract_invalid_denominator}}}\n"
        + f"\\newcommand{{\\CVMStatusOnlyAcceptedContractRejectedRuns}}{{{status_only_accepted_contract_rejected}}}\n"
        + "\\newcommand{\\CVMSemanticProgressDeltaMean}{"
        + _paper_semantic_delta(summary, "progress")
        + "}\n"
        + "\\newcommand{\\CVMSemanticProgressRelDeltaMean}{"
        + _paper_semantic_delta(summary, "progress_rel")
        + "}\n"
        + "\\newcommand{\\CVMSemanticOffroadDeltaMean}{"
        + _paper_semantic_delta(summary, "offroad")
        + "}\n"
        + "\\newcommand{\\CVMSemanticCollisionAnyDeltaMean}{"
        + _paper_semantic_delta(summary, "collision_any")
        + "}\n"
        + "\\newcommand{\\CVMSemanticPlanDeviationDeltaMean}{"
        + _paper_semantic_delta(summary, "plan_deviation")
        + "}\n"
        + "\\newcommand{\\CVMClosedLoopCollisionAnyMean}{"
        + _paper_metric(summary, "collision_any")
        + "}\n"
        + "\\newcommand{\\CVMClosedLoopOffroadMean}{"
        + _paper_metric(summary, "offroad")
        + "}\n"
        + "\\newcommand{\\CVMClosedLoopProgressMean}{"
        + _paper_metric(summary, "progress")
        + "}\n"
        + f"\\newcommand{{\\CVMExternalChallengeRollouts}}{{{_summary_int(external, 'rollouts')}}}\n"
        + f"\\newcommand{{\\CVMExternalChallengePassedRollouts}}{{{_summary_int(external, 'passed_rollouts')}}}\n"
        + f"\\newcommand{{\\CVMExternalChallengeDriveRPCs}}{{{_summary_int(external, 'drive_rpc_count')}}}\n"
        + f"\\newcommand{{\\CVMExternalChallengeImageEvents}}{{{_summary_int(external, 'image_event_count')}}}\n"
        + f"\\newcommand{{\\CVMExternalChallengeLatencyTargetMet}}{{{_summary_int(external, 'latency_target_met_count')}}}\n"
        + f"\\newcommand{{\\CVMExternalChallengeLatencyTargetDenominator}}{{{_summary_int(external, 'latency_target_denominator')}}}\n"
        + "\\newcommand{\\CVMExternalChallengeDriverLatencyMeanMs}{"
        + _paper_external_metric(summary, "driver_latency_mean_ms")
        + "}\n"
        + "\\newcommand{\\CVMExternalChallengeDriverLatencyMaxMs}{"
        + _paper_external_metric(summary, "driver_latency_max_ms")
        + "}\n"
        + f"\\newcommand{{\\CVMReplayDriveRPCsPerArm}}{{{_summary_int(replay_full, 'drive_calls')}}}\n"
        + f"\\newcommand{{\\CVMReplayCameraFrames}}{{{_summary_int(replay_media, 'camera_frames')}}}\n"
        + f"\\newcommand{{\\CVMReplayFullFiniteDriveOutputs}}{{{_summary_int(replay_full, 'finite_drive_outputs')}}}\n"
        + f"\\newcommand{{\\CVMReplayCommandFiniteDriveOutputs}}{{{_summary_int(replay_command, 'finite_drive_outputs')}}}\n"
        + f"\\newcommand{{\\CVMReplayFullLatencyTargetMet}}{{{_summary_int(replay_full, 'drive_calls_within_target')}}}\n"
        + f"\\newcommand{{\\CVMReplayCommandLatencyTargetMet}}{{{_summary_int(replay_command, 'drive_calls_within_target')}}}\n"
        + f"\\newcommand{{\\CVMReplayFullDiagnosticCount}}{{{_summary_int(replay_full, 'diagnostic_count')}}}\n"
        + f"\\newcommand{{\\CVMReplayCommandDiagnosticCount}}{{{_summary_int(replay_command, 'diagnostic_count')}}}\n"
        + "\\newcommand{\\CVMReplayFullLatencyMedianMs}{"
        + _paper_replay_metric(
            summary,
            "arms.full_contract.drive_rpc_latency_ms.p50",
        )
        + "}\n"
        + "\\newcommand{\\CVMReplayFullLatencyNinetyFifthMs}{"
        + _paper_replay_metric(
            summary,
            "arms.full_contract.drive_rpc_latency_ms.p95",
        )
        + "}\n"
        + "\\newcommand{\\CVMReplayCommandLatencyMedianMs}{"
        + _paper_replay_metric(
            summary,
            "arms.command_only_route.drive_rpc_latency_ms.p50",
        )
        + "}\n"
        + "\\newcommand{\\CVMReplayCommandLatencyNinetyFifthMs}{"
        + _paper_replay_metric(
            summary,
            "arms.command_only_route.drive_rpc_latency_ms.p95",
        )
        + "}\n"
        + f"\\newcommand{{\\CVMDiagnosticCases}}{{{_summary_int(diagnostic_design, 'total_cases')}}}\n"
        + f"\\newcommand{{\\CVMDiagnosticFaultCases}}{{{_summary_int(diagnostic_design, 'fault_cases')}}}\n"
        + f"\\newcommand{{\\CVMDiagnosticControlCases}}{{{_summary_int(diagnostic_design, 'control_cases')}}}\n"
        + f"\\newcommand{{\\CVMWODDiagnosticCorrect}}{{{_summary_int(diagnostic_wod2sim, 'classification_correct')}}}\n"
        + f"\\newcommand{{\\CVMStatusDiagnosticCorrect}}{{{_summary_int(diagnostic_status, 'classification_correct')}}}\n"
        + f"\\newcommand{{\\CVMWODDiagnosticFaultDetected}}{{{_summary_int(diagnostic_wod2sim, 'faults_detected')}}}\n"
        + f"\\newcommand{{\\CVMWODDiagnosticLocalized}}{{{_summary_int(diagnostic_wod2sim, 'faults_correctly_localized')}}}\n"
        + f"\\newcommand{{\\CVMWODDiagnosticFalsePositives}}{{{_summary_int(diagnostic_wod2sim, 'false_positives')}}}\n"
        + f"\\newcommand{{\\CVMStatusDiagnosticFaultDetected}}{{{_summary_int(diagnostic_status, 'faults_detected')}}}\n"
        + f"\\newcommand{{\\CVMStatusDiagnosticFalsePositives}}{{{_summary_int(diagnostic_status, 'false_positives')}}}\n"
        + f"\\newcommand{{\\CVMDiagnosticDiscordantPairs}}{{{_summary_int(diagnostic_paired, 'discordant_pairs')}}}\n"
        + f"\\newcommand{{\\CVMProtocolTraceSessions}}{{{_summary_int(diagnostic_source, 'session_count')}}}\n"
        + f"\\newcommand{{\\CVMProtocolTraceDriveRPCs}}{{{_summary_int(diagnostic_source, 'drive_count')}}}\n"
        + f"\\newcommand{{\\CVMProtocolFiniteDriveRecords}}{{{_summary_int(diagnostic_source, 'explicit_finite_drive_count')}}}\n"
        + "\\newcommand{\\CVMDetectorDecisionMedianUs}{"
        + _paper_diagnostic_metric(summary, "timing.contract_gate_decision_us.p50")
        + "}\n"
        + "\\newcommand{\\CVMDetectorDecisionNinetyFifthUs}{"
        + _paper_diagnostic_metric(summary, "timing.contract_gate_decision_us.p95")
        + "}\n"
        + "\\newcommand{\\CVMFaultDetectorMedianUs}{"
        + _paper_diagnostic_metric(summary, "timing.fault_case_detector_us.p50")
        + "}\n"
        + "\\newcommand{\\CVMFaultDetectorNinetyFifthUs}{"
        + _paper_diagnostic_metric(summary, "timing.fault_case_detector_us.p95")
        + "}\n"
        + "\\newcommand{\\CVMAdapterDriveMedianUs}{"
        + _paper_diagnostic_metric(
            summary,
            "adapter_guard_path_timing.guarded_drive_path_us.p50",
        )
        + "}\n"
        + "\\newcommand{\\CVMAdapterDriveNinetyFifthUs}{"
        + _paper_diagnostic_metric(
            summary,
            "adapter_guard_path_timing.guarded_drive_path_us.p95",
        )
        + "}\n"
        + "\\newcommand{\\CVMAdapterGuardIncrementMedianUs}{"
        + _paper_diagnostic_metric(
            summary,
            "adapter_guard_path_timing.paired_incremental_us.p50",
        )
        + "}\n"
        + "\\newcommand{\\CVMAdapterGuardIncrementNinetyFifthUs}{"
        + _paper_diagnostic_metric(
            summary,
            "adapter_guard_path_timing.paired_incremental_us.p95",
        )
        + "}\n"
        + f"\\newcommand{{\\CVMAdapterTimingSamples}}{{{_summary_int(diagnostic_adapter.get('paired_incremental_us', {}), 'samples')}}}\n"
        + f"\\newcommand{{\\CVMAdapterInputCases}}{{{_summary_int(diagnostic_adapter, 'input_cases')}}}\n"
        + f"\\newcommand{{\\CVMFailedRuns}}{{{summary['failed_runs']}}}\n"
        + f"\\newcommand{{\\CVMBlockedRuns}}{{{summary['blocked_runs']}}}\n"
        + f"\\newcommand{{\\CVMSyntheticRuns}}{{{summary['synthetic_completed_runs']}}}\n"
        + f"\\newcommand{{\\CVMCoreRows}}{{{matrix_counts.get('core', 0)}}}\n"
        + f"\\newcommand{{\\CVMSemanticRows}}{{{matrix_counts.get('semantic_ablation', 0)}}}\n"
        + f"\\newcommand{{\\CVMTemporalRows}}{{{matrix_counts.get('temporal_ablation', 0)}}}\n"
        + f"\\newcommand{{\\CVMLifecycleRows}}{{{matrix_counts.get('lifecycle_stress', 0)}}}\n"
        + f"\\newcommand{{\\CVMFaultRows}}{{{matrix_counts.get('fault_injection', 0)}}}\n"
        + f"\\newcommand{{\\CVMLifecycleFullSurvived}}{{{lifecycle_full_survived}}}\n"
        + f"\\newcommand{{\\CVMLifecycleFullTotal}}{{{lifecycle_full_total}}}\n"
        + f"\\newcommand{{\\CVMLifecycleStrictSurvived}}{{{lifecycle_strict_survived}}}\n"
        + f"\\newcommand{{\\CVMLifecycleStrictTotal}}{{{lifecycle_strict_total}}}\n"
        + f"\\newcommand{{\\CVMFaultDetected}}{{{fault_detected}}}\n"
        + f"\\newcommand{{\\CVMFaultLocalized}}{{{fault_localized}}}\n"
        + f"\\newcommand{{\\CVMFaultTotal}}{{{fault_total}}}\n",
        encoding="utf-8",
    )


def _summary_int(summary: object, key: str) -> int:
    if not isinstance(summary, dict):
        return 0
    value = summary.get(key)
    return int(value) if isinstance(value, int) else 0


def _paper_metric(summary: dict[str, Any], metric: str) -> str:
    metrics = summary.get("closed_loop_metrics")
    if not isinstance(metrics, dict):
        return "n/a"
    item = metrics.get(metric)
    if not isinstance(item, dict) or "mean" not in item:
        return "n/a"
    value = item["mean"]
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{float(value):.3f}"


def _paper_external_metric(summary: dict[str, Any], metric: str) -> str:
    external = summary.get("external_compatibility")
    if not isinstance(external, dict):
        return "n/a"
    value = external.get(metric)
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{float(value):.3f}"


def _paper_diagnostic_metric(
    summary: dict[str, Any],
    dotted_path: str,
    *,
    precision: int = 3,
) -> str:
    diagnostic = summary.get("diagnostic_experiment")
    value = _nested_value(diagnostic, dotted_path)
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return "n/a"
    return f"{float(value):.{precision}f}"


def _paper_replay_metric(
    summary: dict[str, Any],
    dotted_path: str,
    *,
    precision: int = 3,
) -> str:
    replay = summary.get("protocol_replay")
    value = _nested_value(replay, dotted_path)
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return "n/a"
    return f"{float(value):.{precision}f}"


def _paper_semantic_delta(summary: dict[str, Any], metric: str) -> str:
    deltas = summary.get("semantic_ablation_deltas")
    if not isinstance(deltas, dict):
        return "n/a"
    item = deltas.get(metric)
    if not isinstance(item, dict):
        return "n/a"
    value = item.get("mean_delta_full_minus_command_only")
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{float(value):.3f}"


if __name__ == "__main__":
    raise SystemExit(main())
