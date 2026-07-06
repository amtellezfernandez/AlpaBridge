from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from wod2sim.cli.commands.benchmark_operator_matrix import (
    MATRIX_SCHEMA,
    build_operator_matrix,
)
from wod2sim.cli.commands.benchmark_regeneration_commands import (
    COMMANDS_SCHEMA,
    build_resume_plan_summary,
    render_commands,
    render_resume_commands_from_audit,
)
from wod2sim.cli.commands.benchmark_regeneration_plan import build_plan

AUDIT_SCHEMA = "wod2sim_benchmark_regeneration_audit_v1"
PLAN_SCHEMA = "wod2sim_benchmark_regeneration_plan_v1"
STATUS_SCHEMA = "wod2sim_benchmark_regeneration_status_v1"
READINESS_SCHEMA = "wod2sim_benchmark_regeneration_readiness_v1"
BATCH_SCHEMA = "wod2sim_closed_loop_batch_summary_v1"
PUBLIC_EVIDENCE_MANIFEST_SCHEMA = "wod2sim_benchmark_public_evidence_manifest_v1"
DEFAULT_AUDIT = Path("docs/evidence/benchmark_regeneration_audit_20260706.json")
DEFAULT_PLAN = Path("docs/evidence/benchmark_regeneration_plan_20260706.json")
DEFAULT_STATUS = Path("docs/evidence/benchmark_regeneration_status_20260706.json")
DEFAULT_HANDOFF = Path("docs/benchmark_regeneration_handoff.md")
DEFAULT_RESUME_COMMANDS = Path("docs/evidence/benchmark_regeneration_resume_commands_20260706.json")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit tracked WOD2Sim benchmark regeneration artifacts and gate whether "
            "the 10/50/100 closed-loop claim is ready."
        )
    )
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--created-at", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit nonzero unless every planned stage has claim-valid closed-loop evidence.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    audit = build_audit(
        plan_path=args.plan,
        status_path=args.status,
        repo_root=args.repo_root,
        created_at=args.created_at,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(audit, indent=2, sort_keys=True))
    else:
        _print_human_summary(audit)
    if args.strict and not audit["claim_ready"]:
        return 1
    return 0 if audit["valid"] else 1


def build_audit(
    *,
    plan_path: Path = DEFAULT_PLAN,
    status_path: Path = DEFAULT_STATUS,
    repo_root: Path = Path.cwd(),
    created_at: str | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    errors: list[str] = []
    plan = _load_json(_resolve_path(repo_root, plan_path), errors=errors, label="plan")
    status = _load_json(_resolve_path(repo_root, status_path), errors=errors, label="status")
    readiness_artifact = str(plan.get("readiness_artifact") or "") if plan else ""
    readiness = (
        _load_json(
            _resolve_path(repo_root, Path(readiness_artifact)), errors=errors, label="readiness"
        )
        if readiness_artifact
        else {}
    )

    if plan and plan.get("schema") != PLAN_SCHEMA:
        errors.append(f"plan schema must be {PLAN_SCHEMA}")
    if status and status.get("schema") != STATUS_SCHEMA:
        errors.append(f"status schema must be {STATUS_SCHEMA}")
    if plan and not readiness_artifact:
        errors.append("plan readiness_artifact is missing")
    if readiness and readiness.get("schema") != READINESS_SCHEMA:
        errors.append(f"readiness schema must be {READINESS_SCHEMA}")

    stage_reports = [
        _audit_stage(stage, repo_root=repo_root)
        for stage in _list_or_empty(plan.get("stages"))
        if isinstance(stage, dict)
    ]
    if plan and not stage_reports:
        errors.append("plan has no stages")

    input_valid = not errors
    claim_ready = input_valid and all(stage["claim_valid"] for stage in stage_reports)
    readiness_consistency = _readiness_consistency(
        plan_path=plan_path,
        status_path=status_path,
        readiness=readiness,
        stage_reports=stage_reports,
    )
    diagnostic_evidence = _diagnostic_evidence(status=status, repo_root=repo_root)
    regeneration_provenance = _regeneration_provenance(stage_reports)
    objective_completion = _objective_completion(
        stage_reports=stage_reports,
        diagnostic_evidence=diagnostic_evidence,
        readiness=readiness,
        claim_ready=claim_ready,
    )
    status_consistency = _status_consistency(
        plan_path=plan_path,
        readiness_artifact=readiness_artifact,
        readiness=readiness,
        status=status,
        stage_reports=stage_reports,
        claim_ready=claim_ready,
        objective_completion=objective_completion,
        repo_root=repo_root,
    )
    regeneration_plan = _regeneration_plan_consistency(
        plan_path=plan_path,
        plan=plan,
        input_valid=input_valid,
    )
    regeneration_commands = _regeneration_commands_consistency(
        plan_path=plan_path,
        readiness=readiness,
        status=status,
        repo_root=repo_root,
    )
    regeneration_resume_commands = _regeneration_resume_commands_consistency(
        plan_path=plan_path,
        plan=plan,
        status=status,
        stage_reports=stage_reports,
        repo_root=repo_root,
    )
    operator_matrix = _operator_matrix_consistency(
        plan_path=plan_path,
        status_path=status_path,
        readiness_artifact=readiness_artifact,
        status=status,
        repo_root=repo_root,
    )
    public_handoff_doc = _public_handoff_doc_consistency(
        claim_ready=claim_ready,
        plan_path=plan_path,
        status_path=status_path,
        status=status,
        readiness=readiness,
        stage_reports=stage_reports,
        repo_root=repo_root,
    )
    expected_valid_without_manifest = (
        input_valid
        and status_consistency["valid"]
        and readiness_consistency["valid"]
        and diagnostic_evidence["valid"]
        and regeneration_plan["valid"]
        and regeneration_commands["valid"]
        and regeneration_resume_commands["valid"]
        and operator_matrix["valid"]
        and public_handoff_doc["valid"]
    )
    public_evidence_manifest = _public_evidence_manifest_consistency(
        plan_path=plan_path,
        status_path=status_path,
        status=status,
        stage_reports=stage_reports,
        objective_completion=objective_completion,
        regeneration_resume_commands=regeneration_resume_commands,
        claim_ready=claim_ready,
        expected_audit_valid_without_manifest=expected_valid_without_manifest,
        repo_root=repo_root,
    )
    valid = expected_valid_without_manifest and public_evidence_manifest["valid"]

    return {
        "schema": AUDIT_SCHEMA,
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "valid": valid,
        "claim_ready": claim_ready,
        "claim_rule": (
            "Every stage in the regeneration plan must have a tracked "
            "wod2sim_closed_loop_batch_summary_v1 artifact with clean_closed_loop_batch=true, "
            "matching scene counts, zero failed scenes, and zero sensor-pipeline failures."
        ),
        "plan_artifact": _display_path(plan_path),
        "status_artifact": _display_path(status_path),
        "readiness_artifact": readiness_artifact,
        "errors": errors,
        "missing_claim_valid_summaries": [
            stage["summary_artifact"] for stage in stage_reports if not stage["claim_valid"]
        ],
        "objective_completion": objective_completion,
        "regeneration_provenance": regeneration_provenance,
        "diagnostic_evidence": diagnostic_evidence,
        "regeneration_plan": regeneration_plan,
        "regeneration_commands": regeneration_commands,
        "regeneration_resume_commands": regeneration_resume_commands,
        "operator_matrix": operator_matrix,
        "public_handoff_doc": public_handoff_doc,
        "public_evidence_manifest": public_evidence_manifest,
        "status_consistency": status_consistency,
        "readiness_consistency": readiness_consistency,
        "stages": stage_reports,
    }


def audit_stage_claim(stage: dict[str, Any], *, repo_root: Path) -> dict[str, Any]:
    return _audit_stage(stage, repo_root=repo_root)


def _audit_stage(stage: dict[str, Any], *, repo_root: Path) -> dict[str, Any]:
    stage_errors: list[str] = []
    expected_scene_count = _int_value(stage.get("scene_count"))
    summary_artifact = str(stage.get("public_summary_target") or "")
    summary_path = _resolve_path(repo_root, Path(summary_artifact))
    summary_present = bool(summary_artifact) and summary_path.is_file()
    summary: dict[str, Any] = {}
    if summary_present:
        try:
            summary = _read_json(summary_path)
        except json.JSONDecodeError as exc:
            stage_errors.append(f"summary_invalid_json:{exc}")
    aggregate = _dict_or_empty(summary.get("aggregate"))

    if not summary_artifact:
        stage_errors.append("summary_artifact_missing")
    if not summary_present:
        stage_errors.append("summary_missing")
    else:
        if summary.get("schema") != BATCH_SCHEMA:
            stage_errors.append(f"summary_schema_mismatch:{summary.get('schema')}")
        if summary.get("clean_closed_loop_batch") is not True:
            stage_errors.append("clean_closed_loop_batch_not_true")
        if _int_value(aggregate.get("planned_scene_count")) != expected_scene_count:
            stage_errors.append("planned_scene_count_mismatch")
        if _int_value(aggregate.get("completed_scene_count")) != expected_scene_count:
            stage_errors.append("completed_scene_count_mismatch")
        if _int_value(aggregate.get("failed_scene_count")) != 0:
            stage_errors.append("failed_scene_count_nonzero")
        if _int_value(aggregate.get("sensor_failure_scene_count")) != 0:
            stage_errors.append("sensor_failure_scene_count_nonzero")
    merge_provenance = _merge_provenance(summary=summary, stage=stage, repo_root=repo_root)
    stage_errors.extend(merge_provenance["errors"])
    summary_provenance = _summary_provenance(
        summary=summary,
        stage=stage,
        summary_present=summary_present,
        merge_provenance=merge_provenance,
    )

    return {
        "stage": stage.get("stage"),
        "scene_preset": stage.get("scene_preset"),
        "expected_scene_count": expected_scene_count,
        "summary_artifact": summary_artifact,
        "summary_present": summary_present,
        "claim_valid": not stage_errors,
        "errors": stage_errors,
        "observed": {
            "schema": summary.get("schema"),
            "clean_closed_loop_batch": summary.get("clean_closed_loop_batch"),
            "created_at": summary.get("created_at"),
            "planned_scene_count": _optional_int(aggregate.get("planned_scene_count")),
            "completed_scene_count": _optional_int(aggregate.get("completed_scene_count")),
            "failed_scene_count": _optional_int(aggregate.get("failed_scene_count")),
            "sensor_failure_scene_count": _optional_int(
                aggregate.get("sensor_failure_scene_count")
            ),
            "total_audited_frames": _optional_int(aggregate.get("total_audited_frames")),
        },
        "merge_provenance": merge_provenance,
        "summary_provenance": summary_provenance,
    }


def _merge_provenance(
    *,
    summary: dict[str, Any],
    stage: dict[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    commands = _dict_or_empty(stage.get("commands"))
    merge_command = _dict_or_empty(commands.get("merge_shard_summaries"))
    expected_inputs = _merge_summary_inputs_from_command(merge_command)
    expected_input_statuses = _merge_input_summary_statuses(
        stage=stage,
        expected_inputs=expected_inputs,
        repo_root=repo_root,
    )
    source = _dict_or_empty(summary.get("source"))
    actual_inputs = [
        str(item) for item in _list_or_empty(source.get("input_summaries")) if isinstance(item, str)
    ]
    is_merged = source.get("summary_kind") == "merged_batch_summaries"
    errors: list[str] = []
    if is_merged and expected_inputs and actual_inputs != expected_inputs:
        errors.append("merge_input_summaries_mismatch")

    return {
        "required_for_stage": bool(expected_inputs),
        "summary_is_merged": is_merged,
        "expected_input_summaries": expected_inputs,
        "expected_input_summary_progress": _merge_input_summary_progress(expected_input_statuses),
        "expected_input_summary_statuses": expected_input_statuses,
        "actual_input_summaries": actual_inputs,
        "input_summaries_match_plan": actual_inputs == expected_inputs if is_merged else None,
        "errors": errors,
    }


def _merge_input_summary_statuses(
    *,
    stage: dict[str, Any],
    expected_inputs: list[str],
    repo_root: Path,
) -> list[dict[str, Any]]:
    expected_counts = _expected_merge_input_scene_counts(stage)
    statuses: list[dict[str, Any]] = []
    for expected_input in expected_inputs:
        expected_scene_count = expected_counts.get(expected_input)
        path = _resolve_path(repo_root, Path(expected_input))
        if not path.is_file():
            statuses.append(
                _merge_input_summary_status(
                    path=expected_input,
                    expected_scene_count=expected_scene_count,
                    present=False,
                    errors=["summary_missing"],
                    summary={},
                )
            )
            continue
        try:
            summary = _read_json(path)
        except json.JSONDecodeError as exc:
            statuses.append(
                _merge_input_summary_status(
                    path=expected_input,
                    expected_scene_count=expected_scene_count,
                    present=True,
                    errors=[f"summary_invalid_json:{exc}"],
                    summary={},
                )
            )
            continue
        statuses.append(
            _merge_input_summary_status(
                path=expected_input,
                expected_scene_count=expected_scene_count,
                present=True,
                errors=_merge_input_summary_errors(
                    summary=summary,
                    expected_scene_count=expected_scene_count,
                ),
                summary=summary,
            )
        )
    return statuses


def _expected_merge_input_scene_counts(stage: dict[str, Any]) -> dict[str, int | None]:
    counts: dict[str, int | None] = {}
    for shard in _list_or_empty(stage.get("shards")):
        shard_map = _dict_or_empty(shard)
        output = _shard_summary_output(shard_map)
        if not output:
            continue
        counts[output] = _optional_int(shard_map.get("scene_limit"))
    return counts


def _shard_summary_output(shard: dict[str, Any]) -> str | None:
    commands = _dict_or_empty(shard.get("commands"))
    write_command = _dict_or_empty(commands.get("write_batch_summary"))
    output = _argv_value(write_command, "--output")
    if output:
        return output
    run_dir = shard.get("run_dir")
    if isinstance(run_dir, str) and run_dir:
        return (Path(run_dir) / "wod2sim-batch-summary.json").as_posix()
    return None


def _argv_value(command: dict[str, Any], option: str) -> str | None:
    argv = _list_or_empty(command.get("argv"))
    for index, value in enumerate(argv):
        if value == option and index + 1 < len(argv) and isinstance(argv[index + 1], str):
            return str(argv[index + 1])
    return None


def _merge_input_summary_errors(
    *,
    summary: dict[str, Any],
    expected_scene_count: int | None,
) -> list[str]:
    aggregate = _dict_or_empty(summary.get("aggregate"))
    errors: list[str] = []
    if summary.get("schema") != BATCH_SCHEMA:
        errors.append(f"summary_schema_mismatch:{summary.get('schema')}")
    if summary.get("clean_closed_loop_batch") is not True:
        errors.append("clean_closed_loop_batch_not_true")
    if expected_scene_count is not None:
        if _int_value(aggregate.get("planned_scene_count")) != expected_scene_count:
            errors.append("planned_scene_count_mismatch")
        if _int_value(aggregate.get("completed_scene_count")) != expected_scene_count:
            errors.append("completed_scene_count_mismatch")
    if _int_value(aggregate.get("failed_scene_count")) != 0:
        errors.append("failed_scene_count_nonzero")
    if _int_value(aggregate.get("sensor_failure_scene_count")) != 0:
        errors.append("sensor_failure_scene_count_nonzero")
    return errors


def _merge_input_summary_status(
    *,
    path: str,
    expected_scene_count: int | None,
    present: bool,
    errors: list[str],
    summary: dict[str, Any],
) -> dict[str, Any]:
    aggregate = _dict_or_empty(summary.get("aggregate"))
    return {
        "path": path,
        "expected_scene_count": expected_scene_count,
        "present": present,
        "claim_valid": present and not errors,
        "errors": errors,
        "observed": {
            "schema": summary.get("schema"),
            "clean_closed_loop_batch": summary.get("clean_closed_loop_batch"),
            "planned_scene_count": _optional_int(aggregate.get("planned_scene_count")),
            "completed_scene_count": _optional_int(aggregate.get("completed_scene_count")),
            "failed_scene_count": _optional_int(aggregate.get("failed_scene_count")),
            "sensor_failure_scene_count": _optional_int(
                aggregate.get("sensor_failure_scene_count")
            ),
            "total_audited_frames": _optional_int(aggregate.get("total_audited_frames")),
        },
    }


def _merge_input_summary_progress(statuses: list[dict[str, Any]]) -> dict[str, Any]:
    expected_count = len(statuses)
    present_count = sum(1 for status in statuses if status.get("present") is True)
    claim_valid_count = sum(1 for status in statuses if status.get("claim_valid") is True)
    return {
        "expected_count": expected_count,
        "present_count": present_count,
        "missing_count": expected_count - present_count,
        "claim_valid_count": claim_valid_count,
        "invalid_present_count": present_count - claim_valid_count,
        "complete": bool(expected_count) and claim_valid_count == expected_count,
    }


def _summary_provenance(
    *,
    summary: dict[str, Any],
    stage: dict[str, Any],
    summary_present: bool,
    merge_provenance: dict[str, Any],
) -> dict[str, Any]:
    source = _dict_or_empty(summary.get("source"))
    expected_inputs = _list_or_empty(merge_provenance.get("expected_input_summaries"))
    expected_summary_kind = (
        "merged_batch_summaries" if expected_inputs else "batch_directory_summary"
    )
    observed_summary_kind = _observed_summary_kind(source=source)
    expected_batch_dir_name = _path_name(stage.get("run_dir"))
    observed_batch_dir_name = (
        str(source.get("batch_dir_name")) if source.get("batch_dir_name") is not None else None
    )
    notes: list[str] = []

    if not summary_present:
        notes.append("summary is not present")
        source_matches_plan = False
    elif expected_summary_kind == "merged_batch_summaries":
        source_matches_plan = bool(merge_provenance.get("input_summaries_match_plan"))
        if not source_matches_plan:
            notes.append("merged summary inputs do not match the regeneration plan")
    else:
        source_matches_plan = (
            observed_summary_kind == "batch_directory_summary"
            and observed_batch_dir_name == expected_batch_dir_name
        )
        if observed_summary_kind != "batch_directory_summary":
            notes.append("summary source is not a direct batch-directory summary")
        if observed_batch_dir_name != expected_batch_dir_name:
            notes.append("summary batch directory does not match the regeneration plan")

    return {
        "expected_summary_kind": expected_summary_kind,
        "observed_summary_kind": observed_summary_kind,
        "expected_batch_dir_name": expected_batch_dir_name,
        "observed_batch_dir_name": observed_batch_dir_name,
        "created_at": summary.get("created_at"),
        "source_matches_plan": source_matches_plan,
        "notes": notes,
    }


def _regeneration_provenance(stage_reports: list[dict[str, Any]]) -> dict[str, Any]:
    source_mismatch_or_missing_stages = [
        str(stage.get("scene_preset") or stage.get("stage") or "")
        for stage in stage_reports
        if not _dict_or_empty(stage.get("summary_provenance")).get("source_matches_plan")
    ]
    present_stage_source_mismatches = [
        str(stage.get("scene_preset") or stage.get("stage") or "")
        for stage in stage_reports
        if stage.get("summary_present")
        and not _dict_or_empty(stage.get("summary_provenance")).get("source_matches_plan")
    ]
    return {
        "all_stage_sources_match_plan": bool(stage_reports)
        and not source_mismatch_or_missing_stages,
        "source_mismatch_or_missing_stages": source_mismatch_or_missing_stages,
        "present_stage_source_mismatches": present_stage_source_mismatches,
    }


def _diagnostic_evidence(*, status: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    evidence_artifacts = _dict_or_empty(status.get("evidence_artifacts"))
    public_evidence = _dict_or_empty(status.get("current_public_evidence"))
    status_row = _dict_or_empty(public_evidence.get("fifty_scene_local_probe"))
    artifact = str(
        evidence_artifacts.get("fifty_scene_local_probe") or status_row.get("artifact") or ""
    )
    checks: dict[str, bool] = {}
    notes: list[str] = []
    summary: dict[str, Any] = {}
    summary_present = False

    if not artifact and not status_row:
        return {
            "valid": True,
            "artifact": None,
            "summary_present": False,
            "checks": {"diagnostic_probe_not_declared": True},
            "notes": ["no diagnostic probe evidence declared in status"],
            "observed": {},
        }

    checks["diagnostic_probe_artifact_declared"] = bool(artifact)
    if not checks["diagnostic_probe_artifact_declared"]:
        notes.append("current_public_evidence.fifty_scene_local_probe has no artifact")
        return _diagnostic_report(
            valid=False,
            artifact=None,
            summary_present=False,
            checks=checks,
            notes=notes,
            summary=summary,
        )

    summary_path = _resolve_path(repo_root, Path(artifact))
    summary_present = summary_path.is_file()
    checks["diagnostic_probe_summary_present"] = summary_present
    if not summary_present:
        notes.append(f"diagnostic probe summary missing: {artifact}")
        return _diagnostic_report(
            valid=False,
            artifact=artifact,
            summary_present=False,
            checks=checks,
            notes=notes,
            summary=summary,
        )

    try:
        summary = _read_json(summary_path)
    except json.JSONDecodeError as exc:
        checks["diagnostic_probe_summary_valid_json"] = False
        notes.append(f"diagnostic probe summary invalid JSON: {exc}")
        return _diagnostic_report(
            valid=False,
            artifact=artifact,
            summary_present=True,
            checks=checks,
            notes=notes,
            summary=summary,
        )

    checks["diagnostic_probe_summary_valid_json"] = True
    aggregate = _dict_or_empty(summary.get("aggregate"))
    run_config = _dict_or_empty(summary.get("run_config"))
    checks["diagnostic_probe_status_artifact_matches"] = status_row.get("artifact") == artifact
    checks["diagnostic_probe_status_scope_is_non_claim"] = status_row.get(
        "status"
    ) == "tracked_public_probe_summary" and "not a claim-valid 50-scene" in str(
        status_row.get("claim_scope") or ""
    )
    checks["diagnostic_probe_schema_matches"] = summary.get("schema") == BATCH_SCHEMA
    checks["diagnostic_probe_preset_matches"] = (
        run_config.get("scene_preset") == "front_camera_50scene_public2602"
    )
    checks["diagnostic_probe_clean_one_scene"] = (
        summary.get("clean_closed_loop_batch") is True
        and _int_value(aggregate.get("planned_scene_count")) == 1
        and _int_value(aggregate.get("completed_scene_count")) == 1
        and _int_value(aggregate.get("failed_scene_count")) == 0
        and _int_value(aggregate.get("sensor_failure_scene_count")) == 0
    )
    checks["diagnostic_probe_status_counts_match_summary"] = (
        _int_value(status_row.get("planned_scene_count"))
        == _int_value(aggregate.get("planned_scene_count"))
        and _int_value(status_row.get("completed_scene_count"))
        == _int_value(aggregate.get("completed_scene_count"))
        and _int_value(status_row.get("failed_scene_count"))
        == _int_value(aggregate.get("failed_scene_count"))
        and _int_value(status_row.get("sensor_failure_scene_count"))
        == _int_value(aggregate.get("sensor_failure_scene_count"))
    )
    for key, passed in checks.items():
        if not passed:
            notes.append(f"{key} failed")

    probe_report = _diagnostic_report(
        valid=all(checks.values()),
        artifact=artifact,
        summary_present=summary_present,
        checks=checks,
        notes=notes,
        summary=summary,
    )
    partial_attempt = _partial_attempt_evidence(
        evidence_artifacts=evidence_artifacts,
        public_evidence=public_evidence,
        repo_root=repo_root,
    )
    return {
        **probe_report,
        "valid": bool(probe_report["valid"]) and bool(partial_attempt["valid"]),
        "scale_attempts": {
            "fifty_scene_partial_attempt": partial_attempt,
        },
    }


def _partial_attempt_evidence(
    *,
    evidence_artifacts: dict[str, Any],
    public_evidence: dict[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    status_row = _dict_or_empty(public_evidence.get("fifty_scene_partial_attempt"))
    artifact = str(
        evidence_artifacts.get("fifty_scene_partial_attempt") or status_row.get("artifact") or ""
    )
    checks: dict[str, bool] = {"partial_attempt_declared": bool(artifact or status_row)}
    notes: list[str] = []
    summary: dict[str, Any] = {}

    if not checks["partial_attempt_declared"]:
        return _diagnostic_report(
            valid=True,
            artifact=None,
            summary_present=False,
            checks=checks,
            notes=["no partial scale attempt evidence declared in status"],
            summary=summary,
        )

    checks["partial_attempt_artifact_declared"] = bool(artifact)
    if not checks["partial_attempt_artifact_declared"]:
        notes.append("current_public_evidence.fifty_scene_partial_attempt has no artifact")
        return _diagnostic_report(
            valid=False,
            artifact=None,
            summary_present=False,
            checks=checks,
            notes=notes,
            summary=summary,
        )

    summary_path = _resolve_path(repo_root, Path(artifact))
    summary_present = summary_path.is_file()
    checks["partial_attempt_summary_present"] = summary_present
    if not summary_present:
        notes.append(f"partial scale attempt summary missing: {artifact}")
        return _diagnostic_report(
            valid=False,
            artifact=artifact,
            summary_present=False,
            checks=checks,
            notes=notes,
            summary=summary,
        )

    try:
        summary = _read_json(summary_path)
    except json.JSONDecodeError as exc:
        checks["partial_attempt_summary_valid_json"] = False
        notes.append(f"partial scale attempt summary invalid JSON: {exc}")
        return _diagnostic_report(
            valid=False,
            artifact=artifact,
            summary_present=True,
            checks=checks,
            notes=notes,
            summary=summary,
        )

    checks["partial_attempt_summary_valid_json"] = True
    aggregate = _dict_or_empty(summary.get("aggregate"))
    run_config = _dict_or_empty(summary.get("run_config"))
    checks["partial_attempt_status_artifact_matches"] = status_row.get("artifact") == artifact
    checks["partial_attempt_status_scope_is_non_claim"] = status_row.get(
        "status"
    ) == "tracked_public_partial_attempt_summary" and "not a claim-valid 50-scene" in str(
        status_row.get("claim_scope") or ""
    )
    checks["partial_attempt_summary_scope_is_non_claim"] = "not a claim-valid stage summary" in str(
        summary.get("claim_boundary") or ""
    )
    checks["partial_attempt_schema_matches"] = summary.get("schema") == BATCH_SCHEMA
    checks["partial_attempt_preset_matches"] = (
        run_config.get("scene_preset") == "front_camera_50scene_public2602"
    )
    checks["partial_attempt_is_failed_two_scene_prefix"] = (
        summary.get("clean_closed_loop_batch") is False
        and _int_value(aggregate.get("planned_scene_count")) == 50
        and _int_value(aggregate.get("observed_scene_count")) == 2
        and _int_value(aggregate.get("completed_scene_count")) == 0
        and _int_value(aggregate.get("failed_scene_count")) == 2
        and _int_value(aggregate.get("sensor_failure_scene_count")) == 0
    )
    checks["partial_attempt_status_counts_match_summary"] = (
        _int_value(status_row.get("planned_scene_count"))
        == _int_value(aggregate.get("planned_scene_count"))
        and _int_value(status_row.get("observed_scene_count"))
        == _int_value(aggregate.get("observed_scene_count"))
        and _int_value(status_row.get("completed_scene_count"))
        == _int_value(aggregate.get("completed_scene_count"))
        and _int_value(status_row.get("failed_scene_count"))
        == _int_value(aggregate.get("failed_scene_count"))
        and _int_value(status_row.get("sensor_failure_scene_count"))
        == _int_value(aggregate.get("sensor_failure_scene_count"))
    )
    for key, passed in checks.items():
        if not passed:
            notes.append(f"{key} failed")
    return _diagnostic_report(
        valid=all(checks.values()),
        artifact=artifact,
        summary_present=True,
        checks=checks,
        notes=notes,
        summary=summary,
    )


def _diagnostic_report(
    *,
    valid: bool,
    artifact: str | None,
    summary_present: bool,
    checks: dict[str, bool],
    notes: list[str],
    summary: dict[str, Any],
) -> dict[str, Any]:
    aggregate = _dict_or_empty(summary.get("aggregate"))
    run_config = _dict_or_empty(summary.get("run_config"))
    return {
        "valid": valid,
        "artifact": artifact,
        "summary_present": summary_present,
        "claim_scope": "diagnostic_only_not_full_stage_claim",
        "checks": checks,
        "notes": notes,
        "observed": {
            "schema": summary.get("schema"),
            "clean_closed_loop_batch": summary.get("clean_closed_loop_batch"),
            "scene_preset": run_config.get("scene_preset"),
            "planned_scene_count": _optional_int(aggregate.get("planned_scene_count")),
            "observed_scene_count": _optional_int(aggregate.get("observed_scene_count")),
            "completed_scene_count": _optional_int(aggregate.get("completed_scene_count")),
            "failed_scene_count": _optional_int(aggregate.get("failed_scene_count")),
            "sensor_failure_scene_count": _optional_int(
                aggregate.get("sensor_failure_scene_count")
            ),
            "total_audited_frames": _optional_int(aggregate.get("total_audited_frames")),
        },
    }


def _objective_completion(
    *,
    stage_reports: list[dict[str, Any]],
    diagnostic_evidence: dict[str, Any],
    readiness: dict[str, Any],
    claim_ready: bool,
) -> dict[str, Any]:
    by_count = {_int_value(stage.get("expected_scene_count")): stage for stage in stage_reports}
    readiness_context = _readiness_completion_context(readiness)
    fifty_preset = "front_camera_50scene_public2602"
    hundred_preset = "front_camera_100scene_public2602"
    requirements = [
        _objective_requirement(
            requirement="validate_10_scene_pilot",
            satisfied=bool(_dict_or_empty(by_count.get(10)).get("claim_valid")),
            evidence=_dict_or_empty(by_count.get(10)).get("summary_artifact"),
            detail="Tracked 10-scene batch summary is claim-valid.",
            blockers=[],
            next_command_groups=[],
        ),
        _objective_requirement(
            requirement="track_50_scene_scale_progress",
            satisfied=bool(diagnostic_evidence.get("valid")),
            evidence=_diagnostic_scale_evidence(diagnostic_evidence),
            detail="Diagnostic 50-preset probe and partial-attempt summaries are audited as non-claim evidence.",
            blockers=[],
            next_command_groups=[],
        ),
        _objective_requirement(
            requirement="produce_claim_valid_50_scene_summary",
            satisfied=bool(_dict_or_empty(by_count.get(50)).get("claim_valid")),
            evidence=_dict_or_empty(by_count.get(50)).get("summary_artifact"),
            detail="Requires a clean full-stage 50-scene public summary.",
            blockers=_requirement_blockers(readiness_context, scene_preset=fifty_preset),
            next_command_groups=_scale_command_groups(readiness_context),
        ),
        _objective_requirement(
            requirement="produce_claim_valid_100_scene_summary",
            satisfied=bool(_dict_or_empty(by_count.get(100)).get("claim_valid")),
            evidence=_dict_or_empty(by_count.get(100)).get("summary_artifact"),
            detail="Requires a clean full-stage 100-scene public summary.",
            blockers=_requirement_blockers(readiness_context, scene_preset=hundred_preset),
            next_command_groups=_scale_command_groups(readiness_context),
        ),
        _objective_requirement(
            requirement="pass_strict_claim_gate",
            satisfied=claim_ready,
            evidence="wod2sim-benchmark-audit --strict --json",
            detail="Strict audit passes only when every planned stage is claim-valid.",
            blockers=_claim_gate_blockers(readiness_context),
            next_command_groups=[
                group
                for group in _next_command_group_names(readiness_context)
                if group in {"refresh_status", "verify_claim_gate"}
            ],
        ),
    ]
    remaining_requirements = [
        requirement["requirement"] for requirement in requirements if not requirement["satisfied"]
    ]
    blocking_requirements = _unique_strings(
        blocker
        for requirement in requirements
        if not requirement["satisfied"]
        for blocker in _list_or_empty(requirement.get("blocking_requirements"))
    )
    next_command_groups = _next_command_group_names(readiness_context) if not claim_ready else []
    next_command_renderer_groups = (
        _next_command_renderer_groups(readiness_context) if not claim_ready else {}
    )
    scale_claim_gaps = _scale_claim_gaps(
        stage_reports=stage_reports,
        readiness=readiness,
        readiness_context=readiness_context,
    )
    return {
        "objective": (
            "Regenerate WOD2Sim closed-loop benchmark artifacts from scratch, validate "
            "10-scene pilot, scale as feasible to 50/100 scenes, and track public-safe evidence."
        ),
        "complete": claim_ready,
        "requirements": requirements,
        "satisfied_count": sum(1 for requirement in requirements if requirement["satisfied"]),
        "total_count": len(requirements),
        "remaining_requirements": remaining_requirements,
        "blocking_requirements": blocking_requirements,
        "next_command_groups": next_command_groups,
        "next_command_renderer_groups": next_command_renderer_groups,
        "scale_claim_gaps": scale_claim_gaps,
    }


def _objective_requirement(
    *,
    requirement: str,
    satisfied: bool,
    evidence: object,
    detail: str,
    blockers: list[str],
    next_command_groups: list[str],
) -> dict[str, Any]:
    row = {
        "requirement": requirement,
        "satisfied": satisfied,
        "evidence": evidence,
        "detail": detail,
    }
    if not satisfied:
        row["blocking_requirements"] = blockers
        row["next_command_groups"] = next_command_groups
    return row


def _scale_claim_gaps(
    *,
    stage_reports: list[dict[str, Any]],
    readiness: dict[str, Any],
    readiness_context: dict[str, Any],
) -> list[dict[str, Any]]:
    readiness_stages = {
        str(stage.get("scene_preset")): stage
        for stage in _list_or_empty(readiness.get("stages"))
        if isinstance(stage, dict) and stage.get("scene_preset")
    }
    rows = []
    for stage_report in stage_reports:
        expected_scene_count = _int_value(stage_report.get("expected_scene_count"))
        if expected_scene_count not in {50, 100}:
            continue
        scene_preset = str(stage_report.get("scene_preset") or "")
        readiness_stage = _dict_or_empty(readiness_stages.get(scene_preset))
        local_cache = _cache_gap_status(readiness_stage.get("local_usdz_cache"))
        source_cache = _cache_gap_status(readiness_stage.get("source_usdz_cache"))
        public_summary = _dict_or_empty(readiness_stage.get("public_summary"))
        merge_provenance = _dict_or_empty(stage_report.get("merge_provenance"))
        expected_merge_inputs = [
            str(item)
            for item in _list_or_empty(merge_provenance.get("expected_input_summaries"))
            if isinstance(item, str)
        ]
        merge_input_progress = _dict_or_empty(
            merge_provenance.get("expected_input_summary_progress")
        )
        rows.append(
            {
                "scene_preset": scene_preset,
                "expected_scene_count": expected_scene_count,
                "summary_artifact": stage_report.get("summary_artifact"),
                "claim_summary_acceptance": _claim_summary_acceptance(
                    expected_scene_count=expected_scene_count,
                    expected_merge_inputs=expected_merge_inputs,
                ),
                "expected_merge_input_count": len(expected_merge_inputs),
                "expected_merge_input_summaries": expected_merge_inputs,
                "merge_input_progress": merge_input_progress,
                "claim_valid": bool(stage_report.get("claim_valid")),
                "public_summary_present": bool(public_summary.get("present")),
                "public_summary_claim_valid": bool(public_summary.get("claim_valid")),
                "public_summary_errors": [
                    str(error)
                    for error in _list_or_empty(public_summary.get("errors"))
                    if isinstance(error, str)
                ],
                "local_usdz_cache": local_cache,
                "source_usdz_cache": source_cache,
                "blocking_requirements": _requirement_blockers(
                    readiness_context,
                    scene_preset=scene_preset,
                ),
                "next_command_groups": _scale_command_groups(readiness_context),
            }
        )
    return rows


def _claim_summary_acceptance(
    *,
    expected_scene_count: int,
    expected_merge_inputs: list[str],
) -> dict[str, Any]:
    return {
        "schema": BATCH_SCHEMA,
        "clean_closed_loop_batch": True,
        "planned_scene_count": expected_scene_count,
        "completed_scene_count": expected_scene_count,
        "failed_scene_count": 0,
        "sensor_failure_scene_count": 0,
        "source_kind": (
            "merged_batch_summaries" if expected_merge_inputs else "batch_directory_summary"
        ),
        "merge_input_summary_count": len(expected_merge_inputs),
        "merge_input_summaries": expected_merge_inputs,
    }


def _cache_gap_status(cache: object) -> dict[str, Any]:
    cache_map = _dict_or_empty(cache)
    validation = _dict_or_empty(cache_map.get("validation"))
    return {
        "required": bool(cache_map.get("required")),
        "valid": bool(validation.get("valid")),
        "expected_scene_count": _optional_int(validation.get("expected_scene_count")),
        "present_scene_count": _optional_int(validation.get("present_scene_count")),
        "missing_scene_count": _optional_int(validation.get("missing_scene_count")),
        "usdz_file_count": _optional_int(cache_map.get("usdz_file_count")),
        "matching_scene_count": _optional_int(cache_map.get("matching_scene_count")),
        "nonmatching_usdz_file_count": _optional_int(cache_map.get("nonmatching_usdz_file_count")),
    }


def _readiness_completion_context(readiness: dict[str, Any]) -> dict[str, Any]:
    blockers = [
        blocker
        for blocker in _list_or_empty(readiness.get("blocking_requirements"))
        if isinstance(blocker, dict)
    ]
    command_groups = [
        group
        for group in _list_or_empty(readiness.get("next_command_groups"))
        if isinstance(group, dict)
    ]
    return {
        "blockers": blockers,
        "command_groups": command_groups,
    }


def _requirement_blockers(
    readiness_context: dict[str, Any],
    *,
    scene_preset: str,
) -> list[str]:
    blockers = []
    for blocker in _list_or_empty(readiness_context.get("blockers")):
        blocker_map = _dict_or_empty(blocker)
        blocker_id = blocker_map.get("id")
        if not isinstance(blocker_id, str):
            continue
        if (
            blocker_map.get("scene_preset") == scene_preset
            or blocker_map.get("scene_preset") is None
        ):
            blockers.append(blocker_id)
    return blockers


def _claim_gate_blockers(readiness_context: dict[str, Any]) -> list[str]:
    return [
        str(blocker["id"])
        for blocker in _list_or_empty(readiness_context.get("blockers"))
        if isinstance(blocker, dict)
        and blocker.get("id")
        and blocker.get("blocks") in {"full_benchmark_claim", "closed_loop_rollout"}
    ]


def _scale_command_groups(readiness_context: dict[str, Any]) -> list[str]:
    return [
        group
        for group in _next_command_group_names(readiness_context)
        if group
        in {
            "build_and_validate_scale_caches",
            "run_scale_shards_and_promote_summaries",
            "refresh_status",
            "verify_claim_gate",
        }
    ]


def _next_command_group_names(readiness_context: dict[str, Any]) -> list[str]:
    return [
        str(group["name"])
        for group in _list_or_empty(readiness_context.get("command_groups"))
        if isinstance(group, dict) and group.get("name")
    ]


def _next_command_renderer_groups(readiness_context: dict[str, Any]) -> dict[str, list[str]]:
    renderer_groups: dict[str, list[str]] = {}
    for group in _list_or_empty(readiness_context.get("command_groups")):
        group_map = _dict_or_empty(group)
        name = group_map.get("name")
        if not isinstance(name, str) or not name:
            continue
        renderer_groups[name] = [
            str(renderer_group)
            for renderer_group in _list_or_empty(group_map.get("command_renderer_groups"))
            if isinstance(renderer_group, str) and renderer_group
        ]
    return renderer_groups


def _unique_strings(values: Iterable[object]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        if not isinstance(value, str) or not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _diagnostic_scale_evidence(diagnostic_evidence: dict[str, Any]) -> list[str]:
    evidence = []
    artifact = diagnostic_evidence.get("artifact")
    if isinstance(artifact, str) and artifact:
        evidence.append(artifact)
    attempts = _dict_or_empty(diagnostic_evidence.get("scale_attempts"))
    for attempt in attempts.values():
        attempt_artifact = _dict_or_empty(attempt).get("artifact")
        if isinstance(attempt_artifact, str) and attempt_artifact:
            evidence.append(attempt_artifact)
    return evidence


def _observed_summary_kind(*, source: dict[str, Any]) -> str | None:
    summary_kind = source.get("summary_kind")
    if isinstance(summary_kind, str) and summary_kind:
        return summary_kind
    if source.get("batch_dir_name") is not None:
        return "batch_directory_summary"
    return None


def _path_name(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return Path(value).name


def _merge_summary_inputs_from_command(command: dict[str, Any]) -> list[str]:
    argv = _list_or_empty(command.get("argv"))
    inputs: list[str] = []
    for index, value in enumerate(argv):
        if value == "--merge-summary" and index + 1 < len(argv):
            next_value = argv[index + 1]
            if isinstance(next_value, str):
                inputs.append(next_value)
    return inputs


def _status_consistency(
    *,
    plan_path: Path,
    readiness_artifact: str,
    readiness: dict[str, Any],
    status: dict[str, Any],
    stage_reports: list[dict[str, Any]],
    claim_ready: bool,
    objective_completion: dict[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    notes: list[str] = []

    checks["status_claim_ready_matches_audit"] = status.get("claim_ready") is claim_ready
    if not checks["status_claim_ready_matches_audit"]:
        notes.append("status.claim_ready does not match audited claim_ready")

    completion_status = _dict_or_empty(status.get("completion_status"))
    checks["full_objective_flag_matches_audit"] = (
        completion_status.get("full_objective_complete") is claim_ready
    )
    if not checks["full_objective_flag_matches_audit"]:
        notes.append("completion_status.full_objective_complete does not match audited claim_ready")

    status_objective_completion = _dict_or_empty(status.get("objective_completion"))
    checks["status_objective_completion_matches_audit"] = (
        status_objective_completion.get("complete") is claim_ready
        and _optional_int(status_objective_completion.get("satisfied_count"))
        == _optional_int(objective_completion.get("satisfied_count"))
        and _optional_int(status_objective_completion.get("total_count"))
        == _optional_int(objective_completion.get("total_count"))
        and status_objective_completion.get("remaining_requirements")
        == objective_completion.get("remaining_requirements")
        and status_objective_completion.get("blocking_requirements")
        == objective_completion.get("blocking_requirements")
        and status_objective_completion.get("next_command_groups")
        == objective_completion.get("next_command_groups")
        and status_objective_completion.get("next_command_renderer_groups")
        == objective_completion.get("next_command_renderer_groups")
    )
    if not checks["status_objective_completion_matches_audit"]:
        notes.append("status.objective_completion does not match audited objective completion")

    public_evidence = _dict_or_empty(status.get("current_public_evidence"))
    ten_scene_status = _dict_or_empty(public_evidence.get("ten_scene_pilot"))
    ten_scene_stage = _stage_by_scene_count(stage_reports, 10)
    if ten_scene_stage is not None:
        checks["ten_scene_status_matches_audit"] = ten_scene_status.get(
            "artifact"
        ) == ten_scene_stage["summary_artifact"] and bool(
            ten_scene_status.get("clean_closed_loop_batch")
        ) == bool(ten_scene_stage["claim_valid"])
        if not checks["ten_scene_status_matches_audit"]:
            notes.append("current_public_evidence.ten_scene_pilot does not match the audit")
    else:
        checks["ten_scene_status_matches_audit"] = False
        notes.append("plan does not include a 10-scene stage")

    evidence_artifacts = _dict_or_empty(status.get("evidence_artifacts"))
    checks["status_evidence_artifacts_match_audit_inputs"] = (
        evidence_artifacts.get("ten_scene_pilot")
        == (ten_scene_stage["summary_artifact"] if ten_scene_stage is not None else None)
        and evidence_artifacts.get("regeneration_plan") == _display_path(plan_path)
        and evidence_artifacts.get("readiness_snapshot") == readiness_artifact
        and evidence_artifacts.get("regeneration_resume_commands")
        == _display_path(DEFAULT_RESUME_COMMANDS)
        and evidence_artifacts.get("public_handoff_doc") == _display_path(DEFAULT_HANDOFF)
        and evidence_artifacts.get("claim_audit") == _display_path(DEFAULT_AUDIT)
    )
    if not checks["status_evidence_artifacts_match_audit_inputs"]:
        notes.append("status.evidence_artifacts does not match the audited evidence chain")

    expected_status = _expected_status(
        plan_path=plan_path,
        readiness_artifact=readiness_artifact,
        status=status,
        repo_root=repo_root,
        notes=notes,
    )
    checks["status_expected_rebuilt"] = bool(expected_status)
    checks["status_matches_generator"] = bool(expected_status) and status == expected_status
    if not checks["status_matches_generator"]:
        notes.append("status artifact does not match wod2sim-benchmark-status output")

    scale_status = _dict_or_empty(status.get("scale_status"))
    readiness_stages = _stages_by_preset(
        [stage for stage in _list_or_empty(readiness.get("stages")) if isinstance(stage, dict)]
    )
    for stage in stage_reports:
        preset = str(stage.get("scene_preset") or "")
        if "public2602" not in preset:
            continue
        status_row = _dict_or_empty(scale_status.get(preset))
        key = f"{preset}_claim_flag_matches_audit"
        checks[key] = bool(status_row.get("claim_valid_closed_loop_summary_tracked")) == bool(
            stage["claim_valid"]
        )
        if not checks[key]:
            notes.append(f"scale_status.{preset}.claim_valid_closed_loop_summary_tracked mismatch")
        readiness_stage = _dict_or_empty(readiness_stages.get(preset))
        for cache_name in ("local_usdz_cache", "source_usdz_cache"):
            cache_key = f"{preset}_{cache_name}_inventory_matches_readiness"
            checks[cache_key] = _dict_or_empty(status_row.get(cache_name)) == (
                _status_cache_inventory(_dict_or_empty(readiness_stage.get(cache_name)))
            )
            if not checks[cache_key]:
                notes.append(f"scale_status.{preset}.{cache_name} does not match readiness")

    return {
        "valid": all(checks.values()) if checks else False,
        "checks": checks,
        "notes": notes,
    }


def _status_cache_inventory(cache: dict[str, Any]) -> dict[str, Any]:
    validation = _dict_or_empty(cache.get("validation"))
    return {
        "required": cache.get("required"),
        "valid": validation.get("valid"),
        "expected_scene_count": _optional_int(validation.get("expected_scene_count")),
        "present_scene_count": _optional_int(validation.get("present_scene_count")),
        "missing_scene_count": _optional_int(validation.get("missing_scene_count")),
        "usdz_file_count": _optional_int(cache.get("usdz_file_count")),
        "matching_scene_count": _optional_int(cache.get("matching_scene_count")),
        "nonmatching_usdz_file_count": _optional_int(cache.get("nonmatching_usdz_file_count")),
    }


def _public_evidence_manifest_consistency(
    *,
    plan_path: Path,
    status_path: Path,
    status: dict[str, Any],
    stage_reports: list[dict[str, Any]],
    objective_completion: dict[str, Any],
    regeneration_resume_commands: dict[str, Any],
    claim_ready: bool,
    expected_audit_valid_without_manifest: bool,
    repo_root: Path,
) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    notes: list[str] = []
    evidence_artifacts = _dict_or_empty(status.get("evidence_artifacts"))
    manifest_artifact = str(evidence_artifacts.get("public_evidence_manifest") or "")

    checks["public_evidence_manifest_referenced"] = bool(manifest_artifact)
    if not checks["public_evidence_manifest_referenced"]:
        notes.append("status.evidence_artifacts.public_evidence_manifest is missing")
        return {"valid": False, "artifact": manifest_artifact, "checks": checks, "notes": notes}

    manifest_path = _resolve_path(repo_root, Path(manifest_artifact))
    manifest = _load_manifest(manifest_path, notes=notes, label="public evidence manifest")
    checks["public_evidence_manifest_loaded"] = bool(manifest)
    if not checks["public_evidence_manifest_loaded"]:
        return {"valid": False, "artifact": manifest_artifact, "checks": checks, "notes": notes}

    checks["public_evidence_manifest_schema_matches"] = (
        manifest.get("schema") == PUBLIC_EVIDENCE_MANIFEST_SCHEMA
    )
    if not checks["public_evidence_manifest_schema_matches"]:
        notes.append("public evidence manifest schema mismatch")

    checks["public_evidence_manifest_self_path_matches_status"] = (
        manifest.get("manifest_artifact") == manifest_artifact
    )
    if not checks["public_evidence_manifest_self_path_matches_status"]:
        notes.append("public evidence manifest self path does not match status reference")

    source_artifacts = _dict_or_empty(manifest.get("source_artifacts"))
    checks["public_evidence_manifest_sources_match_audit"] = (
        source_artifacts.get("plan") == _display_path(plan_path)
        and source_artifacts.get("status") == _display_path(status_path)
        and source_artifacts.get("audit") == _display_path(DEFAULT_AUDIT)
    )
    if not checks["public_evidence_manifest_sources_match_audit"]:
        notes.append("public evidence manifest source_artifacts do not match audit inputs")

    expected_missing = [
        stage["summary_artifact"] for stage in stage_reports if not stage["claim_valid"]
    ]
    claim_gate = _dict_or_empty(manifest.get("claim_gate"))
    checks["public_evidence_manifest_claim_gate_matches_audit"] = (
        bool(claim_gate.get("valid")) == bool(expected_audit_valid_without_manifest)
        and bool(claim_gate.get("claim_ready")) == bool(claim_ready)
        and claim_gate.get("missing_claim_valid_summaries") == expected_missing
        and claim_gate.get("strict_command") == "wod2sim-benchmark-audit --strict --json"
    )
    if not checks["public_evidence_manifest_claim_gate_matches_audit"]:
        notes.append("public evidence manifest claim_gate does not match current audit")

    checks["public_evidence_manifest_objective_completion_matches_audit"] = (
        claim_gate.get("objective") == objective_completion.get("objective")
        and bool(claim_gate.get("objective_complete")) == bool(objective_completion.get("complete"))
        and _optional_int(claim_gate.get("satisfied_requirement_count"))
        == _optional_int(objective_completion.get("satisfied_count"))
        and _optional_int(claim_gate.get("total_requirement_count"))
        == _optional_int(objective_completion.get("total_count"))
        and claim_gate.get("remaining_requirements")
        == objective_completion.get("remaining_requirements")
        and claim_gate.get("blocking_requirements")
        == objective_completion.get("blocking_requirements")
        and claim_gate.get("next_command_groups") == objective_completion.get("next_command_groups")
        and claim_gate.get("next_command_renderer_groups")
        == objective_completion.get("next_command_renderer_groups")
    )
    if not checks["public_evidence_manifest_objective_completion_matches_audit"]:
        notes.append("public evidence manifest objective completion does not match current audit")

    checks["public_evidence_manifest_scale_claim_gaps_match_audit"] = claim_gate.get(
        "scale_claim_gaps"
    ) == objective_completion.get("scale_claim_gaps")
    if not checks["public_evidence_manifest_scale_claim_gaps_match_audit"]:
        notes.append("public evidence manifest scale_claim_gaps do not match current audit")

    checks["public_evidence_manifest_resume_repair_scope_matches_audit"] = claim_gate.get(
        "resume_repair_scope"
    ) == _dict_or_empty(regeneration_resume_commands.get("resume_plan"))
    if not checks["public_evidence_manifest_resume_repair_scope_matches_audit"]:
        notes.append("public evidence manifest resume_repair_scope does not match current audit")

    artifacts = [
        artifact
        for artifact in _list_or_empty(manifest.get("artifacts"))
        if isinstance(artifact, dict)
    ]
    checks["public_evidence_manifest_artifact_count_matches"] = _int_value(
        manifest.get("artifact_count")
    ) == len(artifacts)
    if not checks["public_evidence_manifest_artifact_count_matches"]:
        notes.append("public evidence manifest artifact_count does not match artifacts length")

    artifact_paths = [str(artifact.get("path") or "") for artifact in artifacts]
    checks["public_evidence_manifest_artifact_paths_unique"] = len(artifact_paths) == len(
        set(artifact_paths)
    ) and all(artifact_paths)
    if not checks["public_evidence_manifest_artifact_paths_unique"]:
        notes.append("public evidence manifest artifact paths are missing or duplicated")

    checks["public_evidence_manifest_excludes_self_hash"] = manifest_artifact not in set(
        artifact_paths
    )
    if not checks["public_evidence_manifest_excludes_self_hash"]:
        notes.append("public evidence manifest must not include its own hash entry")

    hash_mismatches = _manifest_hash_mismatches(
        artifacts,
        repo_root=repo_root,
        audit_artifact=_display_path(DEFAULT_AUDIT),
    )
    checks["public_evidence_manifest_hashes_match_tracked_files"] = not hash_mismatches
    if hash_mismatches:
        notes.extend(hash_mismatches)

    missing_expected = [
        item
        for item in _list_or_empty(manifest.get("missing_expected_artifacts"))
        if isinstance(item, dict)
    ]
    expected_missing_rows = [
        {
            "path": path,
            "present": False,
            "required_for_full_claim": True,
            "claim_scope": "missing_claim_valid_scale_summary",
        }
        for path in expected_missing
    ]
    checks["public_evidence_manifest_missing_expected_matches_audit"] = (
        missing_expected == expected_missing_rows
    )
    if not checks["public_evidence_manifest_missing_expected_matches_audit"]:
        notes.append("public evidence manifest missing_expected_artifacts do not match audit")

    return {
        "valid": all(checks.values()) if checks else False,
        "artifact": manifest_artifact,
        "checks": checks,
        "notes": notes,
        "artifact_count": len(artifacts),
    }


def _regeneration_plan_consistency(
    *,
    plan_path: Path,
    plan: dict[str, Any],
    input_valid: bool,
) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    notes: list[str] = []
    artifact = _display_path(plan_path)

    checks["regeneration_plan_loaded"] = bool(plan)
    if not checks["regeneration_plan_loaded"]:
        notes.append("regeneration plan is missing or invalid JSON")
        return {"valid": False, "artifact": artifact, "checks": checks, "notes": notes}

    checks["regeneration_plan_input_valid"] = bool(input_valid)
    if not checks["regeneration_plan_input_valid"]:
        notes.append("regeneration plan failed basic audit input validation")

    checks["regeneration_plan_schema_matches"] = plan.get("schema") == PLAN_SCHEMA
    if not checks["regeneration_plan_schema_matches"]:
        notes.append("regeneration plan schema mismatch")

    expected = build_plan(created_at=str(plan.get("created_at") or "audit_expected"))
    checks["regeneration_plan_matches_generator"] = plan == expected
    if not checks["regeneration_plan_matches_generator"]:
        notes.append("regeneration plan does not match wod2sim-benchmark-plan output")

    stages = [stage for stage in _list_or_empty(plan.get("stages")) if isinstance(stage, dict)]
    return {
        "valid": all(checks.values()) if checks else False,
        "artifact": artifact,
        "checks": checks,
        "notes": notes,
        "stage_count": len(stages),
    }


def _regeneration_commands_consistency(
    *,
    plan_path: Path,
    readiness: dict[str, Any],
    status: dict[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    notes: list[str] = []
    evidence_artifacts = _dict_or_empty(status.get("evidence_artifacts"))
    commands_artifact = str(evidence_artifacts.get("regeneration_commands") or "")

    checks["regeneration_commands_referenced"] = bool(commands_artifact)
    if not checks["regeneration_commands_referenced"]:
        notes.append("status.evidence_artifacts.regeneration_commands is missing")
        return {"valid": False, "artifact": commands_artifact, "checks": checks, "notes": notes}

    commands_path = _resolve_path(repo_root, Path(commands_artifact))
    commands = _load_manifest(commands_path, notes=notes, label="regeneration commands artifact")
    checks["regeneration_commands_loaded"] = bool(commands)
    if not checks["regeneration_commands_loaded"]:
        return {"valid": False, "artifact": commands_artifact, "checks": checks, "notes": notes}

    checks["regeneration_commands_schema_matches"] = commands.get("schema") == COMMANDS_SCHEMA
    if not checks["regeneration_commands_schema_matches"]:
        notes.append("regeneration commands schema mismatch")

    checks["regeneration_commands_plan_matches_audit"] = commands.get(
        "plan_artifact"
    ) == _display_path(plan_path)
    if not checks["regeneration_commands_plan_matches_audit"]:
        notes.append("regeneration commands plan_artifact does not match audited plan")

    renderer = _dict_or_empty(commands.get("renderer"))
    checks["regeneration_commands_renderer_is_non_runtime"] = (
        renderer.get("command") == "wod2sim-benchmark-commands"
        and renderer.get("no_runtime_execution") is True
    )
    if not checks["regeneration_commands_renderer_is_non_runtime"]:
        notes.append("regeneration commands renderer metadata is not public-safe")

    filters = _dict_or_empty(commands.get("filters"))
    checks["regeneration_commands_filters_are_all_stage"] = (
        filters.get("stages") == []
        and filters.get("groups") == ["all"]
        and filters.get("shard_indexes") == []
    )
    if not checks["regeneration_commands_filters_are_all_stage"]:
        notes.append("regeneration commands artifact must render the all-stage plan")

    rows = [row for row in _list_or_empty(commands.get("commands")) if isinstance(row, dict)]
    expected_rows = render_commands(plan_path=_resolve_path(repo_root, plan_path), groups=["all"])
    checks["regeneration_commands_row_count_matches"] = (
        _int_value(commands.get("row_count")) == len(rows) == len(expected_rows)
    )
    if not checks["regeneration_commands_row_count_matches"]:
        notes.append("regeneration commands row_count does not match expected rows")

    expected_group_counts = dict(
        sorted(Counter(str(row.get("group") or "unknown") for row in expected_rows).items())
    )
    checks["regeneration_commands_group_counts_match"] = (
        _dict_or_empty(commands.get("group_counts")) == expected_group_counts
    )
    if not checks["regeneration_commands_group_counts_match"]:
        notes.append("regeneration commands group_counts do not match expected rows")

    expected_execution_boundary_counts = dict(
        sorted(
            Counter(
                str(row.get("execution_boundary") or "unknown") for row in expected_rows
            ).items()
        )
    )
    checks["regeneration_commands_execution_boundary_counts_match"] = (
        _dict_or_empty(commands.get("execution_boundary_counts"))
        == expected_execution_boundary_counts
    )
    if not checks["regeneration_commands_execution_boundary_counts_match"]:
        notes.append("regeneration commands execution_boundary_counts do not match expected rows")

    expected_operator_role_counts = dict(
        sorted(Counter(str(row.get("operator_role") or "unknown") for row in expected_rows).items())
    )
    checks["regeneration_commands_operator_role_counts_match"] = (
        _dict_or_empty(commands.get("operator_role_counts")) == expected_operator_role_counts
    )
    if not checks["regeneration_commands_operator_role_counts_match"]:
        notes.append("regeneration commands operator_role_counts do not match expected rows")

    expected_private_execution_count = sum(
        1 for row in expected_rows if bool(row.get("requires_private_execution_context"))
    )
    expected_public_review_count = len(expected_rows) - expected_private_execution_count
    checks["regeneration_commands_boundary_totals_match"] = (
        _int_value(commands.get("private_execution_command_count"))
        == expected_private_execution_count
        and _int_value(commands.get("public_review_command_count")) == expected_public_review_count
    )
    if not checks["regeneration_commands_boundary_totals_match"]:
        notes.append(
            "regeneration commands public/private execution totals do not match expected rows"
        )

    readiness_renderer_groups = _readiness_command_renderer_groups(readiness)
    command_group_counts = _dict_or_empty(commands.get("group_counts"))
    checks["regeneration_commands_cover_readiness_renderer_groups"] = all(
        _int_value(command_group_counts.get(group)) > 0 for group in readiness_renderer_groups
    )
    if not checks["regeneration_commands_cover_readiness_renderer_groups"]:
        notes.append("regeneration commands do not cover readiness command_renderer_groups")

    checks["regeneration_commands_rows_match_plan_renderer"] = rows == expected_rows
    if not checks["regeneration_commands_rows_match_plan_renderer"]:
        notes.append("regeneration commands rows do not match the audited plan renderer output")

    return {
        "valid": all(checks.values()) if checks else False,
        "artifact": commands_artifact,
        "checks": checks,
        "notes": notes,
        "row_count": len(rows),
        "group_counts": _dict_or_empty(commands.get("group_counts")),
        "execution_boundary_counts": _dict_or_empty(commands.get("execution_boundary_counts")),
        "operator_role_counts": _dict_or_empty(commands.get("operator_role_counts")),
        "private_execution_command_count": _int_value(
            commands.get("private_execution_command_count")
        ),
        "public_review_command_count": _int_value(commands.get("public_review_command_count")),
        "readiness_renderer_groups": readiness_renderer_groups,
    }


def _regeneration_resume_commands_consistency(
    *,
    plan_path: Path,
    plan: dict[str, Any],
    status: dict[str, Any],
    stage_reports: list[dict[str, Any]],
    repo_root: Path,
) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    notes: list[str] = []
    evidence_artifacts = _dict_or_empty(status.get("evidence_artifacts"))
    commands_artifact = str(evidence_artifacts.get("regeneration_resume_commands") or "")

    checks["regeneration_resume_commands_referenced"] = bool(commands_artifact)
    if not checks["regeneration_resume_commands_referenced"]:
        notes.append("status.evidence_artifacts.regeneration_resume_commands is missing")
        return {"valid": False, "artifact": commands_artifact, "checks": checks, "notes": notes}

    commands_path = _resolve_path(repo_root, Path(commands_artifact))
    commands = _load_manifest(
        commands_path,
        notes=notes,
        label="regeneration resume commands artifact",
    )
    checks["regeneration_resume_commands_loaded"] = bool(commands)
    if not checks["regeneration_resume_commands_loaded"]:
        return {"valid": False, "artifact": commands_artifact, "checks": checks, "notes": notes}

    checks["regeneration_resume_commands_schema_matches"] = (
        commands.get("schema") == COMMANDS_SCHEMA
    )
    if not checks["regeneration_resume_commands_schema_matches"]:
        notes.append("regeneration resume commands schema mismatch")

    checks["regeneration_resume_commands_plan_matches_audit"] = commands.get(
        "plan_artifact"
    ) == _display_path(plan_path)
    if not checks["regeneration_resume_commands_plan_matches_audit"]:
        notes.append("regeneration resume commands plan_artifact does not match audited plan")

    renderer = _dict_or_empty(commands.get("renderer"))
    checks["regeneration_resume_commands_renderer_is_non_runtime"] = (
        renderer.get("command") == "wod2sim-benchmark-commands"
        and renderer.get("no_runtime_execution") is True
    )
    if not checks["regeneration_resume_commands_renderer_is_non_runtime"]:
        notes.append("regeneration resume commands renderer metadata is not public-safe")

    filters = _dict_or_empty(commands.get("filters"))
    checks["regeneration_resume_commands_filters_match_resume_mode"] = (
        filters.get("stages") == []
        and filters.get("groups") == ["all"]
        and filters.get("shard_indexes") == []
        and filters.get("resume_missing_shards_from_audit") is True
        and filters.get("audit_artifact") == _display_path(DEFAULT_AUDIT)
    )
    if not checks["regeneration_resume_commands_filters_match_resume_mode"]:
        notes.append("regeneration resume commands artifact must render audit-derived resume rows")

    audit_projection = {
        "schema": AUDIT_SCHEMA,
        "stages": stage_reports,
    }
    expected_rows = render_resume_commands_from_audit(
        plan=plan,
        audit=audit_projection,
        audit_path=DEFAULT_AUDIT,
    )
    rows = [row for row in _list_or_empty(commands.get("commands")) if isinstance(row, dict)]
    checks["regeneration_resume_commands_row_count_matches"] = (
        _int_value(commands.get("row_count")) == len(rows) == len(expected_rows)
    )
    if not checks["regeneration_resume_commands_row_count_matches"]:
        notes.append("regeneration resume commands row_count does not match expected rows")

    expected_group_counts = dict(
        sorted(Counter(str(row.get("group") or "unknown") for row in expected_rows).items())
    )
    checks["regeneration_resume_commands_group_counts_match"] = (
        _dict_or_empty(commands.get("group_counts")) == expected_group_counts
    )
    if not checks["regeneration_resume_commands_group_counts_match"]:
        notes.append("regeneration resume commands group_counts do not match expected rows")

    expected_execution_boundary_counts = dict(
        sorted(
            Counter(
                str(row.get("execution_boundary") or "unknown") for row in expected_rows
            ).items()
        )
    )
    checks["regeneration_resume_commands_execution_boundary_counts_match"] = (
        _dict_or_empty(commands.get("execution_boundary_counts"))
        == expected_execution_boundary_counts
    )
    if not checks["regeneration_resume_commands_execution_boundary_counts_match"]:
        notes.append(
            "regeneration resume commands execution_boundary_counts do not match expected rows"
        )

    expected_operator_role_counts = dict(
        sorted(Counter(str(row.get("operator_role") or "unknown") for row in expected_rows).items())
    )
    checks["regeneration_resume_commands_operator_role_counts_match"] = (
        _dict_or_empty(commands.get("operator_role_counts")) == expected_operator_role_counts
    )
    if not checks["regeneration_resume_commands_operator_role_counts_match"]:
        notes.append("regeneration resume commands operator_role_counts do not match expected rows")

    expected_private_count = sum(
        1 for row in expected_rows if bool(row.get("requires_private_execution_context"))
    )
    expected_public_count = len(expected_rows) - expected_private_count
    checks["regeneration_resume_commands_boundary_totals_match"] = (
        _int_value(commands.get("private_execution_command_count")) == expected_private_count
        and _int_value(commands.get("public_review_command_count")) == expected_public_count
    )
    if not checks["regeneration_resume_commands_boundary_totals_match"]:
        notes.append("regeneration resume commands public/private command counts do not match")

    checks["regeneration_resume_commands_rows_match_audit_renderer"] = rows == expected_rows
    if not checks["regeneration_resume_commands_rows_match_audit_renderer"]:
        notes.append(
            "regeneration resume commands rows do not match current audit-derived renderer"
        )

    expected_resume_plan = build_resume_plan_summary(
        plan=plan,
        audit=audit_projection,
        audit_path=DEFAULT_AUDIT,
        rows=expected_rows,
    )
    resume_plan = _dict_or_empty(commands.get("resume_plan"))
    checks["regeneration_resume_commands_resume_plan_matches_audit"] = (
        resume_plan == expected_resume_plan
    )
    if not checks["regeneration_resume_commands_resume_plan_matches_audit"]:
        notes.append("regeneration resume commands resume_plan does not match current audit")

    return {
        "valid": all(checks.values()) if checks else False,
        "artifact": commands_artifact,
        "checks": checks,
        "notes": notes,
        "row_count": len(rows),
        "expected_row_count": len(expected_rows),
        "group_counts": _dict_or_empty(commands.get("group_counts")),
        "execution_boundary_counts": _dict_or_empty(commands.get("execution_boundary_counts")),
        "operator_role_counts": _dict_or_empty(commands.get("operator_role_counts")),
        "private_execution_command_count": _int_value(
            commands.get("private_execution_command_count")
        ),
        "public_review_command_count": _int_value(commands.get("public_review_command_count")),
        "resume_plan": resume_plan,
    }


def _readiness_command_renderer_groups(readiness: dict[str, Any]) -> list[str]:
    groups: set[str] = set()
    for command_group in _list_or_empty(readiness.get("next_command_groups")):
        if not isinstance(command_group, dict):
            continue
        for renderer_group in _list_or_empty(command_group.get("command_renderer_groups")):
            if isinstance(renderer_group, str) and renderer_group:
                groups.add(renderer_group)
    return sorted(groups)


def _public_handoff_doc_consistency(
    *,
    claim_ready: bool,
    plan_path: Path,
    status_path: Path,
    status: dict[str, Any],
    readiness: dict[str, Any],
    stage_reports: list[dict[str, Any]],
    repo_root: Path,
) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    notes: list[str] = []
    handoff_path = _resolve_path(repo_root, DEFAULT_HANDOFF)
    artifact = _display_path(DEFAULT_HANDOFF)
    text = ""
    size_bytes: int | None = None
    sha256: str | None = None

    checks["public_handoff_doc_present"] = handoff_path.is_file()
    if checks["public_handoff_doc_present"]:
        raw = handoff_path.read_bytes()
        size_bytes = len(raw)
        sha256 = hashlib.sha256(raw).hexdigest()
        text = raw.decode("utf-8")
    else:
        notes.append(f"public handoff doc missing: {artifact}")

    evidence_artifacts = _dict_or_empty(status.get("evidence_artifacts"))
    required_links = [
        _display_path(plan_path),
        _display_path(status_path),
        evidence_artifacts.get("readiness_snapshot"),
        evidence_artifacts.get("regeneration_commands"),
        evidence_artifacts.get("regeneration_resume_commands"),
        evidence_artifacts.get("operator_matrix"),
        evidence_artifacts.get("claim_audit") or _display_path(DEFAULT_AUDIT),
        evidence_artifacts.get("public_evidence_manifest"),
    ]
    required_link_strings = [str(link) for link in required_links if isinstance(link, str) and link]
    checks["public_handoff_doc_links_core_artifacts"] = all(
        link in text for link in required_link_strings
    )
    if not checks["public_handoff_doc_links_core_artifacts"]:
        notes.append("public handoff doc does not link every core benchmark artifact")

    missing_summaries = [
        str(stage.get("summary_artifact") or "")
        for stage in stage_reports
        if not bool(stage.get("claim_valid"))
    ]
    checks["public_handoff_doc_lists_missing_claim_summaries"] = all(
        summary in text for summary in missing_summaries
    )
    if not checks["public_handoff_doc_lists_missing_claim_summaries"]:
        notes.append("public handoff doc does not list current missing claim summaries")

    blocker_ids = [
        str(row.get("id") or "")
        for row in _list_or_empty(readiness.get("blocking_requirements"))
        if isinstance(row, dict) and row.get("id")
    ]
    checks["public_handoff_doc_lists_readiness_blockers"] = all(
        blocker_id in text for blocker_id in blocker_ids
    )
    if not checks["public_handoff_doc_lists_readiness_blockers"]:
        notes.append("public handoff doc does not list current readiness blockers")

    next_groups = [
        row for row in _list_or_empty(readiness.get("next_command_groups")) if isinstance(row, dict)
    ]
    next_group_names = [str(row.get("name") or "") for row in next_groups if row.get("name")]
    checks["public_handoff_doc_lists_next_command_groups"] = all(
        group_name in text for group_name in next_group_names
    )
    if not checks["public_handoff_doc_lists_next_command_groups"]:
        notes.append("public handoff doc does not list current next command groups")

    renderer_groups = _readiness_command_renderer_groups(readiness)
    checks["public_handoff_doc_lists_command_renderer_groups"] = all(
        f"`{group}`" in text for group in renderer_groups
    )
    if not checks["public_handoff_doc_lists_command_renderer_groups"]:
        notes.append("public handoff doc does not list command renderer groups")

    checks["public_handoff_doc_lists_resume_command"] = (
        "wod2sim-benchmark-commands --resume-missing-shards-from-audit" in text
    )
    if not checks["public_handoff_doc_lists_resume_command"]:
        notes.append("public handoff doc does not list the audit-based shard resume command")

    checks["public_handoff_doc_states_current_strict_gate"] = (
        "wod2sim-benchmark-audit --strict --json" in text
        and "valid=true" in text
        and f"claim_ready={str(claim_ready).lower()}" in text
    )
    if not checks["public_handoff_doc_states_current_strict_gate"]:
        notes.append("public handoff doc does not state the current strict gate result")

    safety_terms = (
        "Do not commit raw USDZ assets",
        "Docker layers",
        "Hugging Face caches",
        "rollout videos",
        "support bundles",
    )
    checks["public_handoff_doc_states_public_safety_boundary"] = all(
        term in text for term in safety_terms
    )
    if not checks["public_handoff_doc_states_public_safety_boundary"]:
        notes.append("public handoff doc does not state the public artifact safety boundary")

    cleanup_terms = (
        "wod2sim-benchmark-cleanup --json",
        "dry-run by default",
        "tracked files",
        "--include-gated-assets",
        "--include-scale-caches",
        "--apply",
    )
    checks["public_handoff_doc_states_cleanup_boundary"] = all(
        term in text for term in cleanup_terms
    )
    if not checks["public_handoff_doc_states_cleanup_boundary"]:
        notes.append("public handoff doc does not state the cleanup safety boundary")

    return {
        "valid": all(checks.values()) if checks else False,
        "artifact": artifact,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "checks": checks,
        "notes": notes,
        "missing_claim_valid_summaries": missing_summaries,
        "readiness_blocker_ids": blocker_ids,
        "readiness_command_renderer_groups": renderer_groups,
    }


def _operator_matrix_consistency(
    *,
    plan_path: Path,
    status_path: Path,
    readiness_artifact: str,
    status: dict[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    notes: list[str] = []
    evidence_artifacts = _dict_or_empty(status.get("evidence_artifacts"))
    operator_artifact = str(evidence_artifacts.get("operator_matrix") or "")

    checks["operator_matrix_referenced"] = bool(operator_artifact)
    if not checks["operator_matrix_referenced"]:
        notes.append("status.evidence_artifacts.operator_matrix is missing")
        return {"valid": False, "artifact": operator_artifact, "checks": checks, "notes": notes}

    operator_path = _resolve_path(repo_root, Path(operator_artifact))
    operator_matrix = _load_manifest(
        operator_path,
        notes=notes,
        label="operator matrix artifact",
    )
    checks["operator_matrix_loaded"] = bool(operator_matrix)
    if not checks["operator_matrix_loaded"]:
        return {"valid": False, "artifact": operator_artifact, "checks": checks, "notes": notes}

    checks["operator_matrix_schema_matches"] = operator_matrix.get("schema") == MATRIX_SCHEMA
    if not checks["operator_matrix_schema_matches"]:
        notes.append("operator matrix schema mismatch")

    source_artifacts = _dict_or_empty(operator_matrix.get("source_artifacts"))
    checks["operator_matrix_sources_match_audit"] = (
        source_artifacts.get("plan") == _display_path(plan_path)
        and source_artifacts.get("status") == _display_path(status_path)
        and source_artifacts.get("readiness") == readiness_artifact
        and source_artifacts.get("regeneration_commands")
        == evidence_artifacts.get("regeneration_commands")
        and source_artifacts.get("regeneration_resume_commands")
        == evidence_artifacts.get("regeneration_resume_commands")
    )
    if not checks["operator_matrix_sources_match_audit"]:
        notes.append("operator matrix source_artifacts do not match audit inputs")

    generator = _dict_or_empty(operator_matrix.get("generator"))
    checks["operator_matrix_generator_is_non_runtime"] = (
        generator.get("command") == "wod2sim-benchmark-operators"
        and generator.get("no_download_or_rollout_probes") is True
    )
    if not checks["operator_matrix_generator_is_non_runtime"]:
        notes.append("operator matrix generator metadata is not public-safe")

    expected = _expected_operator_matrix(
        plan_path=plan_path,
        status_path=status_path,
        readiness_artifact=readiness_artifact,
        repo_root=repo_root,
        notes=notes,
    )
    checks["operator_matrix_expected_rebuilt"] = bool(expected)
    if expected:
        for key in (
            "summary",
            "public_artifact_policy",
            "current_local_state",
            "command_execution",
            "resume_command_execution",
            "resume_repair_scope",
            "roles",
            "task_matrix",
        ):
            check_key = f"operator_matrix_{key}_matches_sources"
            checks[check_key] = operator_matrix.get(key) == expected.get(key)
            if not checks[check_key]:
                notes.append(f"operator matrix {key} does not match audited sources")
    else:
        notes.append("operator matrix could not be rebuilt from audited sources")

    roles = [row for row in _list_or_empty(operator_matrix.get("roles")) if isinstance(row, dict)]
    tasks = [
        row for row in _list_or_empty(operator_matrix.get("task_matrix")) if isinstance(row, dict)
    ]
    return {
        "valid": all(checks.values()) if checks else False,
        "artifact": operator_artifact,
        "checks": checks,
        "notes": notes,
        "role_count": len(roles),
        "task_count": len(tasks),
    }


def _readiness_consistency(
    *,
    plan_path: Path,
    status_path: Path,
    readiness: dict[str, Any],
    stage_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    notes: list[str] = []

    checks["readiness_artifact_loaded"] = bool(readiness)
    if not checks["readiness_artifact_loaded"]:
        notes.append("readiness artifact is missing or invalid JSON")
        return {"valid": False, "checks": checks, "notes": notes}

    checks["readiness_plan_artifact_matches_audit"] = readiness.get(
        "plan_artifact"
    ) == _display_path(plan_path)
    if not checks["readiness_plan_artifact_matches_audit"]:
        notes.append("readiness.plan_artifact does not match the audited plan")

    checks["readiness_status_artifact_matches_audit"] = readiness.get(
        "status_artifact"
    ) == _display_path(status_path)
    if not checks["readiness_status_artifact_matches_audit"]:
        notes.append("readiness.status_artifact does not match the audited status")

    readiness_stages = [
        stage for stage in _list_or_empty(readiness.get("stages")) if isinstance(stage, dict)
    ]
    readiness_by_preset = {
        str(stage.get("scene_preset") or ""): stage for stage in readiness_stages
    }
    checks["readiness_stage_count_matches_plan"] = len(readiness_stages) == len(stage_reports)
    if not checks["readiness_stage_count_matches_plan"]:
        notes.append("readiness stage count does not match the regeneration plan")

    for stage in stage_reports:
        preset = str(stage.get("scene_preset") or "")
        readiness_stage = _dict_or_empty(readiness_by_preset.get(preset))
        stage_key = f"{preset}_readiness_stage_matches_audit"
        checks[stage_key] = (
            bool(readiness_stage)
            and readiness_stage.get("stage") == stage.get("stage")
            and _int_value(readiness_stage.get("scene_count")) == stage.get("expected_scene_count")
        )
        if not checks[stage_key]:
            notes.append(f"readiness stage does not match audit for {preset}")
            continue

        public_summary = _dict_or_empty(readiness_stage.get("public_summary"))
        summary_key = f"{preset}_readiness_summary_state_matches_audit"
        checks[summary_key] = bool(public_summary.get("present")) == bool(
            stage.get("summary_present")
        ) and bool(public_summary.get("claim_valid")) == bool(stage.get("claim_valid"))
        if not checks[summary_key]:
            notes.append(f"readiness public_summary state does not match audit for {preset}")

        cache_requirements = _dict_or_empty(readiness_stage.get("cache_requirements"))
        cache_requirements_key = f"{preset}_readiness_cache_requirements_match_preset"
        checks[cache_requirements_key] = _cache_requirements_match_stage(
            cache_requirements=cache_requirements,
            readiness_stage=readiness_stage,
            preset=preset,
        )
        if not checks[cache_requirements_key]:
            notes.append(f"readiness cache_requirements do not match preset for {preset}")

    scale_stage_claims = [
        bool(stage.get("claim_valid"))
        for stage in stage_reports
        if "public2602" in str(stage.get("scene_preset") or "")
    ]
    readiness_flags = _dict_or_empty(readiness.get("readiness"))
    scale_readiness_stages = [
        stage for stage in readiness_stages if bool(stage.get("requires_local_usdz_cache"))
    ]
    local_cache_validity = [
        _dict_or_empty(_dict_or_empty(stage.get("local_usdz_cache")).get("validation")).get("valid")
        is True
        for stage in scale_readiness_stages
    ]
    source_cache_validity = [
        _dict_or_empty(_dict_or_empty(stage.get("source_usdz_cache")).get("validation")).get(
            "valid"
        )
        is True
        for stage in scale_readiness_stages
    ]
    checks["readiness_scale_summary_flag_matches_audit"] = bool(
        readiness_flags.get("claim_valid_scale_summaries_present")
    ) == (all(scale_stage_claims) if scale_stage_claims else False)
    if not checks["readiness_scale_summary_flag_matches_audit"]:
        notes.append("readiness.claim_valid_scale_summaries_present does not match audit")
    checks["readiness_local_cache_flag_matches_stage_state"] = bool(
        readiness_flags.get("all_scale_caches_valid")
    ) == (all(local_cache_validity) if local_cache_validity else False)
    if not checks["readiness_local_cache_flag_matches_stage_state"]:
        notes.append("readiness.all_scale_caches_valid does not match stage cache state")
    checks["readiness_source_cache_flag_matches_stage_state"] = bool(
        readiness_flags.get("all_scale_source_caches_valid")
    ) == (all(source_cache_validity) if source_cache_validity else False)
    if not checks["readiness_source_cache_flag_matches_stage_state"]:
        notes.append("readiness.all_scale_source_caches_valid does not match source cache state")
    checks["readiness_source_cache_link_flag_matches_stage_state"] = bool(
        readiness_flags.get("source_cache_link_ready")
    ) == (all(source_cache_validity) if source_cache_validity else False)
    if not checks["readiness_source_cache_link_flag_matches_stage_state"]:
        notes.append("readiness.source_cache_link_ready does not match source cache state")

    for stage in scale_readiness_stages:
        preset = str(stage.get("scene_preset") or "")
        source_cache = _dict_or_empty(stage.get("source_usdz_cache"))
        source_validation = _dict_or_empty(source_cache.get("validation"))
        source_key = f"{preset}_readiness_source_cache_state_present"
        checks[source_key] = (
            source_cache.get("required") is True
            and source_cache.get("source_usdz_dir") is not None
            and source_validation.get("schema") == "wod2sim_local_usdz_cache_validation_v1"
            and _int_value(source_validation.get("expected_scene_count"))
            == _int_value(stage.get("scene_count"))
            and _int_value(source_validation.get("present_scene_count"))
            <= _int_value(source_validation.get("expected_scene_count"))
        )
        if not checks[source_key]:
            notes.append(f"readiness source_usdz_cache state is incomplete for {preset}")
        for cache_name in ("local_usdz_cache", "source_usdz_cache"):
            cache = _dict_or_empty(stage.get(cache_name))
            inventory_key = f"{preset}_readiness_{cache_name}_inventory_counts_match_validation"
            checks[inventory_key] = _cache_inventory_counts_match_validation(cache)
            if not checks[inventory_key]:
                notes.append(
                    f"readiness {cache_name} inventory counts do not match validation for {preset}"
                )

    blocker_ids = [
        str(row.get("id") or "")
        for row in _list_or_empty(readiness.get("blocking_requirements"))
        if isinstance(row, dict)
    ]
    expected_blocker_ids = _expected_readiness_blocker_ids(
        readiness=readiness,
        readiness_stages=readiness_stages,
    )
    checks["readiness_blocking_requirement_ids_match_state"] = sorted(blocker_ids) == sorted(
        expected_blocker_ids
    )
    if not checks["readiness_blocking_requirement_ids_match_state"]:
        notes.append("readiness.blocking_requirements ids do not match readiness state")

    next_groups = [
        row for row in _list_or_empty(readiness.get("next_command_groups")) if isinstance(row, dict)
    ]
    group_names = [str(row.get("name") or "") for row in next_groups]
    expected_group_names = _expected_readiness_next_group_names(readiness_stages=readiness_stages)
    checks["readiness_next_command_group_names_match_state"] = group_names == expected_group_names
    if not checks["readiness_next_command_group_names_match_state"]:
        notes.append("readiness.next_command_groups names do not match readiness state")

    renderer_groups = {
        str(row.get("name") or ""): [
            str(group)
            for group in _list_or_empty(row.get("command_renderer_groups"))
            if isinstance(group, str)
        ]
        for row in next_groups
    }
    expected_renderer_groups = _expected_readiness_command_renderer_groups(
        readiness_stages=readiness_stages
    )
    checks["readiness_next_command_group_renderer_groups_match_state"] = (
        renderer_groups == expected_renderer_groups
    )
    if not checks["readiness_next_command_group_renderer_groups_match_state"]:
        notes.append("readiness.next_command_groups command_renderer_groups do not match state")

    group_orders = [_int_value(row.get("order")) for row in next_groups]
    checks["readiness_next_command_group_orders_are_contiguous"] = group_orders == list(
        range(1, len(next_groups) + 1)
    )
    if not checks["readiness_next_command_group_orders_are_contiguous"]:
        notes.append("readiness.next_command_groups order values are not contiguous")

    return {
        "valid": all(checks.values()) if checks else False,
        "checks": checks,
        "notes": notes,
    }


def _stage_by_scene_count(
    stage_reports: list[dict[str, Any]],
    scene_count: int,
) -> dict[str, Any] | None:
    for stage in stage_reports:
        if stage.get("expected_scene_count") == scene_count:
            return stage
    return None


def _stages_by_preset(stages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(stage.get("scene_preset") or ""): stage for stage in stages}


def _expected_readiness_blocker_ids(
    *,
    readiness: dict[str, Any],
    readiness_stages: list[dict[str, Any]],
) -> list[str]:
    ids: list[str] = []
    credentials = _dict_or_empty(readiness.get("credentials"))
    scale_stages = [
        stage for stage in readiness_stages if bool(stage.get("requires_local_usdz_cache"))
    ]
    source_cache_link_ready = bool(scale_stages) and all(
        _dict_or_empty(_dict_or_empty(stage.get("source_usdz_cache")).get("validation")).get(
            "valid"
        )
        is True
        for stage in scale_stages
    )
    if (
        credentials.get("hf_token_required_for_cache_build") is True
        and not bool(credentials.get("hf_token_present"))
        and not source_cache_link_ready
    ):
        ids.append("hf_token_missing")

    disk = _dict_or_empty(readiness.get("disk"))
    if disk.get("meets_min_free_disk_gb") is False:
        ids.append("free_disk_below_threshold")

    host = _dict_or_empty(readiness.get("host"))
    if host.get("closed_loop_runner_supported") is False:
        ids.append("unsupported_closed_loop_host")

    runtime_probes = _dict_or_empty(readiness.get("runtime_probes"))
    probe_ids = {
        "docker_daemon": "docker_daemon_unavailable",
        "alpasim_base_image": "alpasim_base_image_missing",
        "nvidia_smi": "nvidia_gpu_unavailable",
    }
    for probe_name, requirement_id in probe_ids.items():
        probe = _dict_or_empty(runtime_probes.get(probe_name))
        if probe and probe.get("ok") is not True:
            ids.append(requirement_id)
    docker_nvidia_runtime = _dict_or_empty(runtime_probes.get("docker_nvidia_runtime"))
    if docker_nvidia_runtime and docker_nvidia_runtime.get("declares_nvidia_runtime") is not True:
        ids.append("docker_nvidia_runtime_unavailable")

    for stage in readiness_stages:
        if not bool(stage.get("requires_local_usdz_cache")):
            continue
        preset = str(stage.get("scene_preset") or "")
        local_cache = _dict_or_empty(stage.get("local_usdz_cache"))
        validation = _dict_or_empty(local_cache.get("validation"))
        if validation.get("valid") is not True:
            ids.append(f"{preset}_cache_invalid")
        public_summary = _dict_or_empty(stage.get("public_summary"))
        if public_summary.get("claim_valid") is not True:
            ids.append(f"{preset}_claim_summary_missing")
    return ids


def _cache_requirements_match_stage(
    *,
    cache_requirements: dict[str, Any],
    readiness_stage: dict[str, Any],
    preset: str,
) -> bool:
    scene_ids = _scene_ids_for_preset(preset)
    requires_cache = bool(readiness_stage.get("requires_local_usdz_cache"))
    expected_local_dir = _dict_or_empty(readiness_stage.get("local_usdz_cache")).get(
        "local_usdz_dir"
    )
    expected_source_dir = _dict_or_empty(readiness_stage.get("source_usdz_cache")).get(
        "source_usdz_dir"
    )
    return (
        bool(cache_requirements)
        and cache_requirements.get("required") is requires_cache
        and cache_requirements.get("scene_preset_file") == _scene_preset_file(preset)
        and _int_value(cache_requirements.get("scene_count")) == len(scene_ids)
        and cache_requirements.get("scene_ids_sha256") == _scene_ids_sha256(scene_ids)
        and cache_requirements.get("scene_ids_sample") == scene_ids[:10]
        and (
            (cache_requirements.get("local_usdz_dir") == expected_local_dir)
            if requires_cache
            else cache_requirements.get("local_usdz_dir") is None
        )
        and (
            (cache_requirements.get("source_usdz_dir") == expected_source_dir)
            if requires_cache
            else cache_requirements.get("source_usdz_dir") is None
        )
    )


def _cache_inventory_counts_match_validation(cache: dict[str, Any]) -> bool:
    if cache.get("required") is not True:
        return True
    validation = _dict_or_empty(cache.get("validation"))
    usdz_file_count = _int_value(cache.get("usdz_file_count"))
    present_scene_count = _int_value(validation.get("present_scene_count"))
    matching_scene_count = _int_value(cache.get("matching_scene_count"))
    nonmatching_usdz_file_count = _int_value(cache.get("nonmatching_usdz_file_count"))
    return (
        usdz_file_count >= present_scene_count
        and matching_scene_count == present_scene_count
        and nonmatching_usdz_file_count == usdz_file_count - present_scene_count
    )


def _scene_ids_for_preset(preset: str) -> list[str]:
    from wod2sim.cli.commands.run_alpasim_local_external import _scene_ids

    return _scene_ids(preset, [])


def _scene_preset_file(preset: str) -> str:
    return f"src/wod2sim/simulator/alpasim_scene_presets/{preset}.yaml"


def _scene_ids_sha256(scene_ids: list[str]) -> str:
    return hashlib.sha256(("\n".join(scene_ids) + "\n").encode("utf-8")).hexdigest()


def _expected_readiness_next_group_names(*, readiness_stages: list[dict[str, Any]]) -> list[str]:
    names = ["refresh_readiness"]
    scale_stages = [
        stage for stage in readiness_stages if bool(stage.get("requires_local_usdz_cache"))
    ]
    if any(
        _dict_or_empty(_dict_or_empty(stage.get("local_usdz_cache")).get("validation")).get("valid")
        is not True
        for stage in scale_stages
    ):
        names.append("build_and_validate_scale_caches")
    if any(
        _dict_or_empty(stage.get("public_summary")).get("claim_valid") is not True
        for stage in scale_stages
    ):
        names.append("run_scale_shards_and_promote_summaries")
    names.extend(["refresh_status", "verify_claim_gate"])
    return names


def _expected_readiness_command_renderer_groups(
    *, readiness_stages: list[dict[str, Any]]
) -> dict[str, list[str]]:
    renderer_groups: dict[str, list[str]] = {"refresh_readiness": ["readiness"]}
    scale_stages = [
        stage for stage in readiness_stages if bool(stage.get("requires_local_usdz_cache"))
    ]
    if any(
        _dict_or_empty(_dict_or_empty(stage.get("local_usdz_cache")).get("validation")).get("valid")
        is not True
        for stage in scale_stages
    ):
        renderer_groups["build_and_validate_scale_caches"] = ["cache"]
    if any(
        _dict_or_empty(stage.get("public_summary")).get("claim_valid") is not True
        for stage in scale_stages
    ):
        renderer_groups["run_scale_shards_and_promote_summaries"] = [
            "shards",
            "merge",
            "promote",
        ]
    renderer_groups["refresh_status"] = ["post"]
    renderer_groups["verify_claim_gate"] = ["post"]
    return renderer_groups


def _load_json(path: Path, *, errors: list[str], label: str) -> dict[str, Any]:
    if not path.is_file():
        errors.append(f"{label} missing: {path}")
        return {}
    try:
        return _read_json(path)
    except json.JSONDecodeError as exc:
        errors.append(f"{label} is not valid JSON: {path}: {exc}")
        return {}


def _load_manifest(path: Path, *, notes: list[str], label: str) -> dict[str, Any]:
    if not path.is_file():
        notes.append(f"{label} missing: {path}")
        return {}
    try:
        return _read_json(path)
    except json.JSONDecodeError as exc:
        notes.append(f"{label} is not valid JSON: {path}: {exc}")
        return {}


def _expected_operator_matrix(
    *,
    plan_path: Path,
    status_path: Path,
    readiness_artifact: str,
    repo_root: Path,
    notes: list[str],
) -> dict[str, Any]:
    if not readiness_artifact:
        notes.append("operator matrix cannot be rebuilt without readiness_artifact")
        return {}
    try:
        return build_operator_matrix(
            plan_path=plan_path,
            status_path=status_path,
            readiness_path=Path(readiness_artifact),
            repo_root=repo_root,
            created_at="audit_expected",
        )
    except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError) as exc:
        notes.append(f"operator matrix rebuild failed: {exc}")
        return {}


def _expected_status(
    *,
    plan_path: Path,
    readiness_artifact: str,
    status: dict[str, Any],
    repo_root: Path,
    notes: list[str],
) -> dict[str, Any]:
    if not readiness_artifact:
        notes.append("status cannot be rebuilt without readiness_artifact")
        return {}
    try:
        from wod2sim.cli.commands.benchmark_regeneration_status import build_status

        return build_status(
            plan_path=plan_path,
            readiness_path=Path(readiness_artifact),
            repo_root=repo_root,
            created_at=str(status.get("created_at") or "audit_expected"),
        )
    except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError) as exc:
        notes.append(f"status rebuild failed: {exc}")
        return {}


def _manifest_hash_mismatches(
    artifacts: list[dict[str, Any]],
    *,
    repo_root: Path,
    audit_artifact: str,
) -> list[str]:
    mismatches: list[str] = []
    for artifact in artifacts:
        display_path = str(artifact.get("path") or "")
        if display_path == audit_artifact:
            # The audit artifact is the output of this command, so enforcing its
            # recorded hash here would create a circular fixed-point requirement.
            continue
        path = _resolve_path(repo_root, Path(display_path))
        if not path.is_file():
            mismatches.append(f"manifest artifact missing: {display_path}")
            continue
        raw = path.read_bytes()
        expected_size = _int_value(artifact.get("size_bytes"))
        expected_hash = str(artifact.get("sha256") or "")
        actual_hash = hashlib.sha256(raw).hexdigest()
        if expected_size != len(raw):
            mismatches.append(f"manifest size mismatch: {display_path}")
        if expected_hash != actual_hash:
            mismatches.append(f"manifest hash mismatch: {display_path}")
    return mismatches


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise json.JSONDecodeError("JSON root must be an object", doc="", pos=0)
    return payload


def _list_or_empty(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _dict_or_empty(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _int_value(value)


def _resolve_path(repo_root: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return repo_root / path


def _display_path(path: Path) -> str:
    return str(path) if path.is_absolute() else path.as_posix()


def _print_human_summary(audit: dict[str, Any]) -> None:
    status = "ready" if audit["claim_ready"] else "not-ready"
    print(f"{audit['schema']}: {status}")
    for stage in audit["stages"]:
        marker = "ok" if stage["claim_valid"] else "missing"
        print(
            f"- {marker}: {stage['scene_preset']} "
            f"({stage['expected_scene_count']} scenes) -> {stage['summary_artifact']}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
