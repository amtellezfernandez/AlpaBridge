from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

AUDIT_SCHEMA = "wod2sim_benchmark_regeneration_audit_v1"
PLAN_SCHEMA = "wod2sim_benchmark_regeneration_plan_v1"
STATUS_SCHEMA = "wod2sim_benchmark_regeneration_status_v1"
BATCH_SCHEMA = "wod2sim_closed_loop_batch_summary_v1"
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

    if plan and plan.get("schema") != PLAN_SCHEMA:
        errors.append(f"plan schema must be {PLAN_SCHEMA}")
    if status and status.get("schema") != STATUS_SCHEMA:
        errors.append(f"status schema must be {STATUS_SCHEMA}")

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
        status=status,
        stage_reports=stage_reports,
        claim_ready=claim_ready,
    )
    valid = input_valid and status_consistency["valid"]

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
        "errors": errors,
        "missing_claim_valid_summaries": [
            stage["summary_artifact"] for stage in stage_reports if not stage["claim_valid"]
        ],
        "status_consistency": status_consistency,
        "stages": stage_reports,
    }


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
            "planned_scene_count": _optional_int(aggregate.get("planned_scene_count")),
            "completed_scene_count": _optional_int(aggregate.get("completed_scene_count")),
            "failed_scene_count": _optional_int(aggregate.get("failed_scene_count")),
            "sensor_failure_scene_count": _optional_int(
                aggregate.get("sensor_failure_scene_count")
            ),
            "total_audited_frames": _optional_int(aggregate.get("total_audited_frames")),
        },
        "merge_provenance": merge_provenance,
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
