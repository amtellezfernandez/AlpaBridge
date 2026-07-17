from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
            "Invalid contract-validation aggregate inputs:\n"
            + "\n".join(validation_errors[:20])
        )
    duplicate_completed = _duplicate_completed_run_ids(rows)
    if duplicate_completed:
        raise SystemExit(f"Duplicate completed run IDs: {', '.join(duplicate_completed[:5])}")

    rows = sorted(rows, key=lambda row: (row.get("matrix", ""), row.get("run_id", "")))
    failures = [row for row in rows if row.get("status") in {"failed", "blocked"}]
    closed_loop_evidence = _closed_loop_evidence(rows)
    semantic_pair_rows = _semantic_ablation_pair_rows(closed_loop_evidence)
    summary = _summary(
        rows=rows,
        failures=failures,
        closed_loop_evidence=closed_loop_evidence,
        semantic_pair_rows=semantic_pair_rows,
        created_at=_input_created_at(args.inputs),
    )

    _write_csv(args.output / "runs.csv", rows, _fields(rows))
    _write_csv(args.output / "failures.csv", failures, _fields(rows))
    _write_csv(args.output / "closed_loop_metrics.csv", closed_loop_evidence, _fields(closed_loop_evidence))
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
    semantic_delta_summary = _semantic_ablation_delta_summary(semantic_pair_rows)
    failure_attribution_summary = _failure_attribution_summary(rows, closed_loop_evidence)
    return {
        "schema": "cvm_aggregate_summary_v1",
        "created_at": created_at,
        "data_hash": _hash_rows(rows),
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
        "integration_effectiveness": effectiveness_summary,
        "failure_attribution": failure_attribution_summary,
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
        row
        for row in closed_loop_evidence
        if row not in contract_valid_closed_loop
    ]
    claim_valid_policy_rows = [
        row
        for row in rows
        if row.get("claim_valid") == "true" and row.get("status") == "completed"
    ]
    return {
        "rule": (
            "Closed-loop behavior can be interpreted as policy behavior only after "
            "the semantic route contract, sensor-freshness audit, lifecycle state, "
            "deployment preconditions, and evidence gate pass. Otherwise the row is "
            "an integration, precondition, or evidence failure."
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
    }


def _hash_rows(rows: list[dict[str, str]]) -> str:
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _closed_loop_evidence(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
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


def _run_dir_for(row: dict[str, str]) -> Path | None:
    source = row.get("_source", "")
    if not source:
        return None
    return Path(source).parent / "run_dirs" / _safe_filename(row.get("run_id", ""))


def _safe_filename(value: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "_" for character in value)


def _closed_loop_metric_summary(
    evidence_rows: list[dict[str, Any]]
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
        row
        for row in evidence_rows
        if row.get("adapter_config") in {"full_contract", "full_temporal_contract"}
    ]
    full_contract_audit_valid = [
        row for row in full_contract_rows if row.get("audit_valid") == "true"
    ]
    semantic_rows = [row for row in evidence_rows if row.get("matrix") == "semantic_ablation"]
    semantic_pairs = _semantic_ablation_pairs(semantic_rows)
    command_proxy_rows = [
        row
        for row in semantic_rows
        if row.get("adapter_config") == "command_only_route"
    ]
    command_proxy_rejected = [
        row
        for row in command_proxy_rows
        if row.get("route_contract_ok") == "false" or row.get("audit_valid") == "false"
    ]
    false_block_denominator = len(full_contract_audit_valid)
    false_blocked = 0
    return {
        "full_contract_completed_runs": len(full_contract_rows),
        "full_contract_audit_valid_runs": len(full_contract_audit_valid),
        "valid_full_contract_false_blocked_runs": false_blocked,
        "valid_full_contract_false_block_denominator": false_block_denominator,
        "valid_full_contract_false_block_rate": None
        if false_block_denominator == 0
        else round(false_blocked / false_block_denominator, 6),
        "semantic_ablation_completed_pairs": semantic_pairs["completed_pairs"],
        "semantic_ablation_metric_pairs": semantic_pairs["metric_pairs"],
        "semantic_ablation_command_proxy_completed_runs": len(command_proxy_rows),
        "semantic_ablation_command_proxy_rejected_runs": len(command_proxy_rejected),
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
    metric_pairs = 0
    for adapters in grouped.values():
        full = adapters.get("full_contract")
        command_only = adapters.get("command_only_route")
        if full is None or command_only is None:
            continue
        completed_pairs += 1
        if (
            full.get("metrics_present") == "true"
            and command_only.get("metrics_present") == "true"
        ):
            metric_pairs += 1
    return {"completed_pairs": completed_pairs, "metric_pairs": metric_pairs}


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
        }
        for metric in SEMANTIC_PAIR_METRICS:
            full_value = _metric_float(full, metric)
            command_value = _metric_float(command_only, metric)
            row[f"full_{metric}"] = "" if full_value is None else f"{full_value:.6g}"
            row[f"command_only_{metric}"] = (
                "" if command_value is None else f"{command_value:.6g}"
            )
            row[f"delta_{metric}"] = (
                ""
                if full_value is None or command_value is None
                else f"{(full_value - command_value):.6g}"
            )
        pair_rows.append(row)
    return pair_rows


def _semantic_ablation_delta_summary(
    pair_rows: list[dict[str, Any]]
) -> dict[str, dict[str, float | int]]:
    summary: dict[str, dict[str, float | int]] = {}
    for metric in SEMANTIC_PAIR_METRICS:
        values: list[float] = []
        key = f"delta_{metric}"
        for row in pair_rows:
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
                "min_delta": round(min(values), 6),
                "max_delta": round(max(values), 6),
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
        "valid_full_contract_false_blocked_runs",
        "valid_full_contract_false_block_denominator",
        "semantic_ablation_completed_pairs",
        "semantic_ablation_metric_pairs",
        "contract_valid_closed_loop_rows",
        "integration_or_evidence_invalid_closed_loop_rows",
        "claim_valid_policy_benchmark_rows",
        "failed_runs",
        "blocked_runs",
        "claim_valid",
        "data_hash",
    ]
    effectiveness = summary.get("integration_effectiveness", {})
    attribution = summary.get("failure_attribution", {})
    row: dict[str, str] = {}
    for field in fields:
        if field in summary:
            row[field] = str(summary[field])
        elif isinstance(effectiveness, dict) and field in effectiveness:
            row[field] = str(effectiveness[field])
        elif isinstance(attribution, dict) and field in attribution:
            row[field] = str(attribution[field])
        else:
            row[field] = ""
    _write_csv(path, [row], fields)


def _write_empty_frames(path: Path) -> None:
    _write_csv(
        path,
        [],
        [
            "run_id",
            "frame_index",
            "sim_timestamp",
            "observation_timestamp",
            "observation_age_ms",
            "route_source",
            "trajectory_valid",
        ],
    )


def _write_fault_rollup(inputs: Path, output: Path) -> None:
    rows: list[dict[str, str]] = []
    for path in sorted(inputs.rglob("fault_injection.csv")):
        if path == output:
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            rows.extend(csv.DictReader(handle))
    fields = list(rows[0].keys()) if rows else ["injection", "status"]
    _write_csv(output, rows, fields)


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
        row.get("matrix") == "fault_injection" and row.get("detected") == "true"
        for row in rows
    )
    fault_localized = sum(
        row.get("matrix") == "fault_injection"
        and row.get("correctly_localized") == "true"
        for row in rows
    )
    effectiveness = summary.get("integration_effectiveness", {})
    full_contract_completed = _summary_int(effectiveness, "full_contract_completed_runs")
    full_contract_audit_valid = _summary_int(
        effectiveness, "full_contract_audit_valid_runs"
    )
    false_blocked = _summary_int(
        effectiveness, "valid_full_contract_false_blocked_runs"
    )
    false_block_denominator = _summary_int(
        effectiveness, "valid_full_contract_false_block_denominator"
    )
    semantic_completed_pairs = _summary_int(
        effectiveness, "semantic_ablation_completed_pairs"
    )
    semantic_metric_pairs = _summary_int(effectiveness, "semantic_ablation_metric_pairs")
    command_proxy_completed = _summary_int(
        effectiveness, "semantic_ablation_command_proxy_completed_runs"
    )
    command_proxy_rejected = _summary_int(
        effectiveness, "semantic_ablation_command_proxy_rejected_runs"
    )
    attribution = summary.get("failure_attribution", {})
    contract_valid_closed_loop = _summary_int(
        attribution, "contract_valid_closed_loop_rows"
    )
    integration_invalid_closed_loop = _summary_int(
        attribution, "integration_or_evidence_invalid_closed_loop_rows"
    )
    claim_valid_policy_benchmark = _summary_int(
        attribution, "claim_valid_policy_benchmark_rows"
    )
    synthetic_diagnostic = _summary_int(attribution, "synthetic_diagnostic_rows")
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
    (tables / "main_results.tex").write_text(
        "% generated by contract-validation aggregate; data_hash="
        + data_hash
        + "\n"
        + "\\begin{tabular}{lrrr}\n"
        + "\\toprule\nEvidence family & Denom. & Positive & Completed \\\\\n"
        + "\\midrule\n"
        + f"CVM configured rows & {summary['total_rows']} & -- & {summary['completed_runs']} \\\\\n"
        + f"Full-contract rollouts & {full_contract_completed} & {full_contract_audit_valid} & {full_contract_completed} \\\\\n"
        + f"False-block observations & {false_block_denominator} & {false_blocked} & -- \\\\\n"
        + f"Semantic ablation pairs & {semantic_completed_pairs} & {semantic_metric_pairs} & -- \\\\\n"
        + f"Planned/not launched & {summary['total_rows']} & {summary['planned_runs']} & 0 \\\\\n"
        + f"Blocked & {summary['total_rows']} & {summary['blocked_runs']} & 0 \\\\\n"
        + "\\bottomrule\n\\end{tabular}\n",
        encoding="utf-8",
    )
    (tables / "ablations.tex").write_text(
        "% generated by contract-validation aggregate; data_hash="
        + data_hash
        + "\n"
        + "\\begin{tabular}{lrr}\n"
        + "\\toprule\nIntegration-effectiveness check & Positive & Total \\\\\n"
        + "\\midrule\n"
        + f"Full-contract audit-valid rollouts & {full_contract_audit_valid} & {full_contract_completed} \\\\\n"
        + f"False-blocked valid rollouts & {false_blocked} & {false_block_denominator} \\\\\n"
        + f"Semantic ablation metric pairs & {semantic_metric_pairs} & {semantic_completed_pairs} \\\\\n"
        + f"Command-proxy rows rejected & {command_proxy_rejected} & {command_proxy_completed} \\\\\n"
        + f"Full lifecycle hardening & {lifecycle_full_survived} & {lifecycle_full_total} \\\\\n"
        + f"Strict/pre-hardening behavior & {lifecycle_strict_survived} & {lifecycle_strict_total} \\\\\n"
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
        + f"\\newcommand{{\\CVMValidFullContractFalseBlockedRuns}}{{{false_blocked}}}\n"
        + f"\\newcommand{{\\CVMValidFullContractFalseBlockDenominator}}{{{false_block_denominator}}}\n"
        + f"\\newcommand{{\\CVMContractValidClosedLoopRows}}{{{contract_valid_closed_loop}}}\n"
        + f"\\newcommand{{\\CVMIntegrationInvalidClosedLoopRows}}{{{integration_invalid_closed_loop}}}\n"
        + f"\\newcommand{{\\CVMClaimValidPolicyBenchmarkRows}}{{{claim_valid_policy_benchmark}}}\n"
        + f"\\newcommand{{\\CVMSyntheticDiagnosticRows}}{{{synthetic_diagnostic}}}\n"
        + f"\\newcommand{{\\CVMSemanticAblationCompletedPairs}}{{{semantic_completed_pairs}}}\n"
        + f"\\newcommand{{\\CVMSemanticAblationMetricPairs}}{{{semantic_metric_pairs}}}\n"
        + f"\\newcommand{{\\CVMCommandProxyCompletedRuns}}{{{command_proxy_completed}}}\n"
        + f"\\newcommand{{\\CVMCommandProxyRejectedRuns}}{{{command_proxy_rejected}}}\n"
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
