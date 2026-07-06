from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from wod2sim.cli.commands.benchmark_operator_matrix import (
    MATRIX_SCHEMA,
    build_operator_matrix,
)
from wod2sim.cli.commands.benchmark_regeneration_commands import (
    COMMANDS_SCHEMA,
    render_commands,
)

AUDIT_SCHEMA = "wod2sim_benchmark_regeneration_audit_v1"
PLAN_SCHEMA = "wod2sim_benchmark_regeneration_plan_v1"
STATUS_SCHEMA = "wod2sim_benchmark_regeneration_status_v1"
READINESS_SCHEMA = "wod2sim_benchmark_regeneration_readiness_v1"
BATCH_SCHEMA = "wod2sim_closed_loop_batch_summary_v1"
PUBLIC_EVIDENCE_MANIFEST_SCHEMA = "wod2sim_benchmark_public_evidence_manifest_v1"
DEFAULT_AUDIT = Path("docs/evidence/benchmark_regeneration_audit_20260706.json")
DEFAULT_PLAN = Path("docs/evidence/benchmark_regeneration_plan_20260706.json")
DEFAULT_STATUS = Path("docs/evidence/benchmark_regeneration_status_20260706.json")


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
        _load_json(_resolve_path(repo_root, Path(readiness_artifact)), errors=errors, label="readiness")
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
    status_consistency = _status_consistency(
        plan_path=plan_path,
        readiness_artifact=readiness_artifact,
        status=status,
        stage_reports=stage_reports,
        claim_ready=claim_ready,
    )
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
    regeneration_commands = _regeneration_commands_consistency(
        plan_path=plan_path,
        status=status,
        repo_root=repo_root,
    )
    operator_matrix = _operator_matrix_consistency(
        plan_path=plan_path,
        status_path=status_path,
        readiness_artifact=readiness_artifact,
        status=status,
        repo_root=repo_root,
    )
    expected_valid_without_manifest = (
        input_valid
        and status_consistency["valid"]
        and readiness_consistency["valid"]
        and diagnostic_evidence["valid"]
        and regeneration_commands["valid"]
        and operator_matrix["valid"]
    )
    public_evidence_manifest = _public_evidence_manifest_consistency(
        plan_path=plan_path,
        status_path=status_path,
        status=status,
        stage_reports=stage_reports,
        claim_ready=claim_ready,
        expected_audit_valid_without_manifest=expected_valid_without_manifest,
        repo_root=repo_root,
    )
    valid = (
        expected_valid_without_manifest
        and public_evidence_manifest["valid"]
    )

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
        "regeneration_commands": regeneration_commands,
        "operator_matrix": operator_matrix,
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
    merge_provenance = _merge_provenance(summary=summary, stage=stage)
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


def _merge_provenance(*, summary: dict[str, Any], stage: dict[str, Any]) -> dict[str, Any]:
    commands = _dict_or_empty(stage.get("commands"))
    merge_command = _dict_or_empty(commands.get("merge_shard_summaries"))
    expected_inputs = _merge_summary_inputs_from_command(merge_command)
    source = _dict_or_empty(summary.get("source"))
    actual_inputs = [
        str(item)
        for item in _list_or_empty(source.get("input_summaries"))
        if isinstance(item, str)
    ]
    is_merged = source.get("summary_kind") == "merged_batch_summaries"
    errors: list[str] = []
    if is_merged and expected_inputs and actual_inputs != expected_inputs:
        errors.append("merge_input_summaries_mismatch")

    return {
        "required_for_stage": bool(expected_inputs),
        "summary_is_merged": is_merged,
        "expected_input_summaries": expected_inputs,
        "actual_input_summaries": actual_inputs,
        "input_summaries_match_plan": actual_inputs == expected_inputs if is_merged else None,
        "errors": errors,
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
    expected_summary_kind = "merged_batch_summaries" if expected_inputs else "batch_directory_summary"
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
    checks["diagnostic_probe_status_scope_is_non_claim"] = (
        status_row.get("status") == "tracked_public_probe_summary"
        and "not a claim-valid 50-scene" in str(status_row.get("claim_scope") or "")
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
    checks["partial_attempt_status_scope_is_non_claim"] = (
        status_row.get("status") == "tracked_public_partial_attempt_summary"
        and "not a claim-valid 50-scene" in str(status_row.get("claim_scope") or "")
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
    by_count = {
        _int_value(stage.get("expected_scene_count")): stage for stage in stage_reports
    }
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
    return {
        "objective": (
            "Regenerate WOD2Sim closed-loop benchmark artifacts from scratch, validate "
            "10-scene pilot, scale as feasible to 50/100 scenes, and track public-safe evidence."
        ),
        "complete": claim_ready,
        "requirements": requirements,
        "satisfied_count": sum(1 for requirement in requirements if requirement["satisfied"]),
        "total_count": len(requirements),
        "remaining_requirements": [
            requirement["requirement"]
            for requirement in requirements
            if not requirement["satisfied"]
        ],
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
        if blocker_map.get("scene_preset") == scene_preset or blocker_map.get("scene_preset") is None:
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
    status: dict[str, Any],
    stage_reports: list[dict[str, Any]],
    claim_ready: bool,
) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    notes: list[str] = []

    completion_status = _dict_or_empty(status.get("completion_status"))
    checks["full_objective_flag_matches_audit"] = (
        completion_status.get("full_objective_complete") is claim_ready
    )
    if not checks["full_objective_flag_matches_audit"]:
        notes.append("completion_status.full_objective_complete does not match audited claim_ready")

    public_evidence = _dict_or_empty(status.get("current_public_evidence"))
    ten_scene_status = _dict_or_empty(public_evidence.get("ten_scene_pilot"))
    ten_scene_stage = _stage_by_scene_count(stage_reports, 10)
    if ten_scene_stage is not None:
        checks["ten_scene_status_matches_audit"] = (
            ten_scene_status.get("artifact") == ten_scene_stage["summary_artifact"]
            and bool(ten_scene_status.get("clean_closed_loop_batch"))
            == bool(ten_scene_stage["claim_valid"])
        )
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
        and evidence_artifacts.get("claim_audit") == _display_path(DEFAULT_AUDIT)
    )
    if not checks["status_evidence_artifacts_match_audit_inputs"]:
        notes.append("status.evidence_artifacts does not match the audited evidence chain")

    scale_status = _dict_or_empty(status.get("scale_status"))
    for stage in stage_reports:
        preset = str(stage.get("scene_preset") or "")
        if "public2602" not in preset:
            continue
        status_row = _dict_or_empty(scale_status.get(preset))
        key = f"{preset}_claim_flag_matches_audit"
        checks[key] = (
            bool(status_row.get("claim_valid_closed_loop_summary_tracked"))
            == bool(stage["claim_valid"])
        )
        if not checks[key]:
            notes.append(f"scale_status.{preset}.claim_valid_closed_loop_summary_tracked mismatch")

    return {
        "valid": all(checks.values()) if checks else False,
        "checks": checks,
        "notes": notes,
    }


def _public_evidence_manifest_consistency(
    *,
    plan_path: Path,
    status_path: Path,
    status: dict[str, Any],
    stage_reports: list[dict[str, Any]],
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

    artifacts = [
        artifact for artifact in _list_or_empty(manifest.get("artifacts")) if isinstance(artifact, dict)
    ]
    checks["public_evidence_manifest_artifact_count_matches"] = (
        _int_value(manifest.get("artifact_count")) == len(artifacts)
    )
    if not checks["public_evidence_manifest_artifact_count_matches"]:
        notes.append("public evidence manifest artifact_count does not match artifacts length")

    artifact_paths = [str(artifact.get("path") or "") for artifact in artifacts]
    checks["public_evidence_manifest_artifact_paths_unique"] = (
        len(artifact_paths) == len(set(artifact_paths)) and all(artifact_paths)
    )
    if not checks["public_evidence_manifest_artifact_paths_unique"]:
        notes.append("public evidence manifest artifact paths are missing or duplicated")

    checks["public_evidence_manifest_excludes_self_hash"] = manifest_artifact not in set(artifact_paths)
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


def _regeneration_commands_consistency(
    *,
    plan_path: Path,
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

    checks["regeneration_commands_plan_matches_audit"] = (
        commands.get("plan_artifact") == _display_path(plan_path)
    )
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
            "public_artifact_policy",
            "current_local_state",
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

    checks["readiness_plan_artifact_matches_audit"] = (
        readiness.get("plan_artifact") == _display_path(plan_path)
    )
    if not checks["readiness_plan_artifact_matches_audit"]:
        notes.append("readiness.plan_artifact does not match the audited plan")

    checks["readiness_status_artifact_matches_audit"] = (
        readiness.get("status_artifact") == _display_path(status_path)
    )
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
        checks[summary_key] = (
            bool(public_summary.get("present")) == bool(stage.get("summary_present"))
            and bool(public_summary.get("claim_valid")) == bool(stage.get("claim_valid"))
        )
        if not checks[summary_key]:
            notes.append(f"readiness public_summary state does not match audit for {preset}")

    scale_stage_claims = [
        bool(stage.get("claim_valid"))
        for stage in stage_reports
        if "public2602" in str(stage.get("scene_preset") or "")
    ]
    readiness_flags = _dict_or_empty(readiness.get("readiness"))
    checks["readiness_scale_summary_flag_matches_audit"] = (
        bool(readiness_flags.get("claim_valid_scale_summaries_present"))
        == (all(scale_stage_claims) if scale_stage_claims else False)
    )
    if not checks["readiness_scale_summary_flag_matches_audit"]:
        notes.append("readiness.claim_valid_scale_summaries_present does not match audit")

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
