from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from wod2sim.cli.commands.benchmark_regeneration_audit import audit_stage_claim

STATUS_SCHEMA = "wod2sim_benchmark_regeneration_status_v1"
BATCH_SCHEMA = "wod2sim_closed_loop_batch_summary_v1"
PLAN_SCHEMA = "wod2sim_benchmark_regeneration_plan_v1"
READINESS_SCHEMA = "wod2sim_benchmark_regeneration_readiness_v1"
DEFAULT_STATUS = Path("docs/evidence/benchmark_regeneration_status_20260706.json")
DEFAULT_PILOT = Path("docs/evidence/closed_loop_spotlight_reflex_10scene_batch.json")
DEFAULT_SCALE_PROBE_50 = Path(
    "docs/evidence/closed_loop_spotlight_reflex_50scene_localprobe_1scene.json"
)
DEFAULT_SCALE_ATTEMPT_50 = Path(
    "docs/evidence/closed_loop_spotlight_reflex_50scene_attempt_partial.json"
)
DEFAULT_PLAN = Path("docs/evidence/benchmark_regeneration_plan_20260706.json")
DEFAULT_READINESS = Path("docs/evidence/benchmark_regeneration_readiness_20260706.json")
DEFAULT_AUDIT = Path("docs/evidence/benchmark_regeneration_audit_20260706.json")
DEFAULT_COMMANDS = Path("docs/evidence/benchmark_regeneration_commands_20260706.json")
DEFAULT_RESUME_COMMANDS = Path("docs/evidence/benchmark_regeneration_resume_commands_20260706.json")
DEFAULT_OPERATOR_MATRIX = Path("docs/evidence/benchmark_operator_matrix_20260706.json")
DEFAULT_EVIDENCE_MANIFEST = Path("docs/evidence/benchmark_public_evidence_manifest_20260706.json")
DEFAULT_HANDOFF = Path("docs/benchmark_regeneration_handoff.md")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate the public WOD2Sim benchmark status from tracked compact "
            "evidence artifacts. This command does not probe Docker, GPUs, or caches."
        )
    )
    parser.add_argument("--pilot-summary", type=Path, default=DEFAULT_PILOT)
    parser.add_argument("--scale-probe-50-summary", type=Path, default=DEFAULT_SCALE_PROBE_50)
    parser.add_argument(
        "--scale-attempt-50-summary",
        type=Path,
        default=DEFAULT_SCALE_ATTEMPT_50,
    )
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--readiness", type=Path, default=DEFAULT_READINESS)
    parser.add_argument(
        "--audit",
        type=Path,
        default=DEFAULT_AUDIT,
        help="Audit artifact path to reference in the status evidence chain. The file is not read.",
    )
    parser.add_argument(
        "--commands-artifact",
        type=Path,
        default=DEFAULT_COMMANDS,
        help=(
            "Rendered command artifact path to reference in the status evidence chain. "
            "The file is not read."
        ),
    )
    parser.add_argument(
        "--resume-commands-artifact",
        type=Path,
        default=DEFAULT_RESUME_COMMANDS,
        help=(
            "Audit-derived missing-shard resume command artifact path to reference in the "
            "status evidence chain. The file is not read."
        ),
    )
    parser.add_argument(
        "--operator-matrix",
        type=Path,
        default=DEFAULT_OPERATOR_MATRIX,
        help=(
            "Operator capability matrix artifact path to reference in the status evidence "
            "chain. The file is not read."
        ),
    )
    parser.add_argument(
        "--evidence-manifest",
        type=Path,
        default=DEFAULT_EVIDENCE_MANIFEST,
        help=(
            "Public evidence manifest artifact path to reference in the status evidence "
            "chain. The file is not read."
        ),
    )
    parser.add_argument(
        "--handoff-doc",
        type=Path,
        default=DEFAULT_HANDOFF,
        help=(
            "Public handoff documentation path to reference in the status evidence chain. "
            "The file is not read."
        ),
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--created-at", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    status = build_status(
        pilot_path=args.pilot_summary,
        scale_probe_50_path=args.scale_probe_50_summary,
        scale_attempt_50_path=args.scale_attempt_50_summary,
        plan_path=args.plan,
        readiness_path=args.readiness,
        audit_path=args.audit,
        commands_path=args.commands_artifact,
        resume_commands_path=args.resume_commands_artifact,
        operator_matrix_path=args.operator_matrix,
        evidence_manifest_path=args.evidence_manifest,
        handoff_doc_path=args.handoff_doc,
        repo_root=args.repo_root,
        created_at=args.created_at,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        _print_human_summary(status)
    return 0


def build_status(
    *,
    pilot_path: Path = DEFAULT_PILOT,
    scale_probe_50_path: Path = DEFAULT_SCALE_PROBE_50,
    scale_attempt_50_path: Path = DEFAULT_SCALE_ATTEMPT_50,
    plan_path: Path = DEFAULT_PLAN,
    readiness_path: Path = DEFAULT_READINESS,
    audit_path: Path = DEFAULT_AUDIT,
    commands_path: Path = DEFAULT_COMMANDS,
    resume_commands_path: Path = DEFAULT_RESUME_COMMANDS,
    operator_matrix_path: Path = DEFAULT_OPERATOR_MATRIX,
    evidence_manifest_path: Path = DEFAULT_EVIDENCE_MANIFEST,
    handoff_doc_path: Path = DEFAULT_HANDOFF,
    repo_root: Path = Path.cwd(),
    created_at: str | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    pilot = _read_json(_resolve_path(repo_root, pilot_path))
    scale_probe_50 = _read_json_if_exists(_resolve_path(repo_root, scale_probe_50_path))
    scale_attempt_50 = _read_json_if_exists(_resolve_path(repo_root, scale_attempt_50_path))
    plan = _read_json(_resolve_path(repo_root, plan_path))
    readiness = _read_json(_resolve_path(repo_root, readiness_path))

    _require_schema(pilot, BATCH_SCHEMA, "pilot summary")
    if scale_probe_50:
        _require_schema(scale_probe_50, BATCH_SCHEMA, "50-scene local probe summary")
    if scale_attempt_50:
        _require_schema(scale_attempt_50, BATCH_SCHEMA, "50-scene partial attempt summary")
    _require_schema(plan, PLAN_SCHEMA, "plan")
    _require_schema(readiness, READINESS_SCHEMA, "readiness")

    evidence_artifacts = {
        "ten_scene_pilot": _display_path(pilot_path),
        "fifty_scene_local_probe": _display_path(scale_probe_50_path),
        "fifty_scene_partial_attempt": _display_path(scale_attempt_50_path),
        "regeneration_plan": _display_path(plan_path),
        "readiness_snapshot": _display_path(readiness_path),
        "regeneration_commands": _display_path(commands_path),
        "regeneration_resume_commands": _display_path(resume_commands_path),
        "operator_matrix": _display_path(operator_matrix_path),
        "public_evidence_manifest": _display_path(evidence_manifest_path),
        "public_handoff_doc": _display_path(handoff_doc_path),
        "claim_audit": _display_path(audit_path),
    }
    stage_reports = [
        audit_stage_claim(stage, repo_root=repo_root)
        for stage in _list_of_dicts(plan.get("stages"))
    ]
    scale_status = _scale_status(plan=plan, readiness=readiness, stage_reports=stage_reports)
    claim_ready = bool(stage_reports) and all(stage["claim_valid"] for stage in stage_reports)
    current_public_evidence = {
        "ten_scene_pilot": _pilot_status(pilot=pilot, pilot_path=pilot_path),
        "fifty_scene_local_probe": _scale_probe_status(
            summary=scale_probe_50,
            summary_path=scale_probe_50_path,
        ),
        "fifty_scene_partial_attempt": _scale_attempt_status(
            summary=scale_attempt_50,
            summary_path=scale_attempt_50_path,
        ),
    }
    objective_completion = _objective_completion_status(
        stage_reports=stage_reports,
        readiness=readiness,
        current_public_evidence=current_public_evidence,
        claim_ready=claim_ready,
    )

    return {
        "schema": STATUS_SCHEMA,
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "objective": (
            "Regenerate WOD2Sim closed-loop benchmark artifacts from scratch, validate "
            "10-scene pilot evidence, scale to 50/100 scenes when runtime prerequisites "
            "are available, and track only public-safe artifacts."
        ),
        "evidence_artifacts": evidence_artifacts,
        "status_generator": {
            "command": "wod2sim-benchmark-status",
            "inputs": {
                "ten_scene_pilot": _display_path(pilot_path),
                "fifty_scene_local_probe": _display_path(scale_probe_50_path),
                "fifty_scene_partial_attempt": _display_path(scale_attempt_50_path),
                "regeneration_plan": _display_path(plan_path),
                "readiness_snapshot": _display_path(readiness_path),
            },
            "referenced_artifacts": {
                "regeneration_commands": _display_path(commands_path),
                "regeneration_resume_commands": _display_path(resume_commands_path),
                "operator_matrix": _display_path(operator_matrix_path),
                "public_evidence_manifest": _display_path(evidence_manifest_path),
                "public_handoff_doc": _display_path(handoff_doc_path),
                "claim_audit": _display_path(audit_path),
            },
            "no_download_or_rollout_probes": True,
        },
        "public_artifact_policy": {
            "tracked": "Compact JSON summaries, documentation, commands, tests, and public-safe hashes/metrics.",
            "untracked": (
                "Raw AlpaSim media, support bundles, USDZ scene assets, Hugging Face "
                "caches, Docker layers, and gated scene-derived files."
            ),
        },
        "claim_ready": claim_ready,
        "objective_completion": objective_completion,
        "current_public_evidence": current_public_evidence,
        "current_local_runtime_state": _runtime_state_from_readiness(
            readiness=readiness,
            readiness_path=readiness_path,
        ),
        "scale_status": scale_status,
        "completion_status": {
            "full_objective_complete": claim_ready,
            "reason": _completion_reason(claim_ready=claim_ready, scale_status=scale_status),
        },
    }


def _pilot_status(*, pilot: dict[str, Any], pilot_path: Path) -> dict[str, Any]:
    aggregate = _dict_or_empty(pilot.get("aggregate"))
    failure_taxonomy = _dict_or_empty(pilot.get("failure_taxonomy"))
    return {
        "artifact": _display_path(pilot_path),
        "schema": pilot.get("schema"),
        "clean_closed_loop_batch": pilot.get("clean_closed_loop_batch"),
        "planned_scene_count": _optional_int(aggregate.get("planned_scene_count")),
        "completed_scene_count": _optional_int(aggregate.get("completed_scene_count")),
        "failed_scene_count": _optional_int(aggregate.get("failed_scene_count")),
        "sensor_failure_scene_count": _optional_int(aggregate.get("sensor_failure_scene_count")),
        "total_audited_frames": _optional_int(aggregate.get("total_audited_frames")),
        "failure_taxonomy": {
            "collision_scene_count": _optional_int(failure_taxonomy.get("collision_scene_count")),
            "at_fault_collision_scene_count": _optional_int(
                failure_taxonomy.get("at_fault_collision_scene_count")
            ),
            "wrong_lane_scene_count": _optional_int(failure_taxonomy.get("wrong_lane_scene_count")),
            "offroad_scene_count": _optional_int(failure_taxonomy.get("offroad_scene_count")),
            "low_progress_scene_count": _optional_int(
                failure_taxonomy.get("low_progress_scene_count")
            ),
            "high_plan_deviation_scene_count": _optional_int(
                failure_taxonomy.get("high_plan_deviation_scene_count")
            ),
        },
        "status": "tracked_public_summary",
    }


def _scale_probe_status(*, summary: dict[str, Any], summary_path: Path) -> dict[str, Any]:
    if not summary:
        return {
            "artifact": _display_path(summary_path),
            "present": False,
            "status": "not_tracked",
            "claim_scope": "diagnostic_only_not_full_stage_claim",
        }
    aggregate = _dict_or_empty(summary.get("aggregate"))
    failure_taxonomy = _dict_or_empty(summary.get("failure_taxonomy"))
    run_config = _dict_or_empty(summary.get("run_config"))
    return {
        "artifact": _display_path(summary_path),
        "present": True,
        "schema": summary.get("schema"),
        "clean_closed_loop_batch": summary.get("clean_closed_loop_batch"),
        "scene_preset": run_config.get("scene_preset"),
        "planned_scene_count": _optional_int(aggregate.get("planned_scene_count")),
        "observed_scene_count": _optional_int(aggregate.get("observed_scene_count")),
        "completed_scene_count": _optional_int(aggregate.get("completed_scene_count")),
        "failed_scene_count": _optional_int(aggregate.get("failed_scene_count")),
        "sensor_failure_scene_count": _optional_int(aggregate.get("sensor_failure_scene_count")),
        "total_audited_frames": _optional_int(aggregate.get("total_audited_frames")),
        "failure_taxonomy": {
            "collision_scene_count": _optional_int(failure_taxonomy.get("collision_scene_count")),
            "at_fault_collision_scene_count": _optional_int(
                failure_taxonomy.get("at_fault_collision_scene_count")
            ),
            "wrong_lane_scene_count": _optional_int(failure_taxonomy.get("wrong_lane_scene_count")),
            "offroad_scene_count": _optional_int(failure_taxonomy.get("offroad_scene_count")),
            "low_progress_scene_count": _optional_int(
                failure_taxonomy.get("low_progress_scene_count")
            ),
            "high_plan_deviation_scene_count": _optional_int(
                failure_taxonomy.get("high_plan_deviation_scene_count")
            ),
        },
        "status": "tracked_public_probe_summary",
        "claim_scope": (
            "Diagnostic one-scene probe from the 50-scene public preset. This is not a "
            "claim-valid 50-scene stage summary and does not satisfy the strict audit gate."
        ),
    }


def _scale_attempt_status(*, summary: dict[str, Any], summary_path: Path) -> dict[str, Any]:
    if not summary:
        return {
            "artifact": _display_path(summary_path),
            "present": False,
            "status": "not_tracked",
            "claim_scope": "diagnostic_only_not_full_stage_claim",
        }
    aggregate = _dict_or_empty(summary.get("aggregate"))
    run_config = _dict_or_empty(summary.get("run_config"))
    return {
        "artifact": _display_path(summary_path),
        "present": True,
        "schema": summary.get("schema"),
        "clean_closed_loop_batch": summary.get("clean_closed_loop_batch"),
        "scene_preset": run_config.get("scene_preset"),
        "planned_scene_count": _optional_int(aggregate.get("planned_scene_count")),
        "observed_scene_count": _optional_int(aggregate.get("observed_scene_count")),
        "completed_scene_count": _optional_int(aggregate.get("completed_scene_count")),
        "failed_scene_count": _optional_int(aggregate.get("failed_scene_count")),
        "sensor_failure_scene_count": _optional_int(aggregate.get("sensor_failure_scene_count")),
        "total_audited_frames": _optional_int(aggregate.get("total_audited_frames")),
        "status": "tracked_public_partial_attempt_summary",
        "claim_scope": (
            "Diagnostic partial attempt from the 50-scene public preset. This records an "
            "early failed scale attempt and is not a claim-valid 50-scene stage summary."
        ),
    }


def _runtime_state_from_readiness(
    *,
    readiness: dict[str, Any],
    readiness_path: Path,
) -> dict[str, Any]:
    runtime_probes = _dict_or_empty(readiness.get("runtime_probes"))
    readiness_flags = _dict_or_empty(readiness.get("readiness"))
    host = _dict_or_empty(readiness.get("host"))
    disk = _dict_or_empty(readiness.get("disk"))
    docker_nvidia_runtime = _dict_or_empty(runtime_probes.get("docker_nvidia_runtime"))
    return {
        "derived_from": _display_path(readiness_path),
        "host_machine": host.get("machine"),
        "closed_loop_runner_supported": host.get("closed_loop_runner_supported"),
        "docker_daemon_ok": _probe_ok(runtime_probes.get("docker_daemon")),
        "docker_nvidia_runtime_present": docker_nvidia_runtime.get("declares_nvidia_runtime"),
        "alpasim_base_image_present": _probe_ok(runtime_probes.get("alpasim_base_image")),
        "nvidia_smi_ok": _probe_ok(runtime_probes.get("nvidia_smi")),
        "all_scale_caches_valid": readiness_flags.get("all_scale_caches_valid"),
        "all_scale_source_caches_valid": readiness_flags.get("all_scale_source_caches_valid"),
        "source_cache_link_ready": readiness_flags.get("source_cache_link_ready"),
        "claim_valid_scale_summaries_present": readiness_flags.get(
            "claim_valid_scale_summaries_present"
        ),
        "disk_free_gib_at_readiness": disk.get("free_gib"),
        "disk_meets_min_free_disk_gb": disk.get("meets_min_free_disk_gb"),
    }


def _scale_status(
    *,
    plan: dict[str, Any],
    readiness: dict[str, Any],
    stage_reports: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    readiness_by_preset = _by_preset(_list_of_dicts(readiness.get("stages")))
    reports_by_preset = _by_preset(stage_reports)
    rows: dict[str, dict[str, Any]] = {}
    for stage in _list_of_dicts(plan.get("stages")):
        if not stage.get("requires_local_usdz_cache"):
            continue
        preset = str(stage.get("scene_preset") or "")
        readiness_stage = readiness_by_preset.get(preset, {})
        stage_report = reports_by_preset.get(preset, {})
        local_usdz_cache = _dict_or_empty(readiness_stage.get("local_usdz_cache"))
        source_usdz_cache = _dict_or_empty(readiness_stage.get("source_usdz_cache"))
        validation = _dict_or_empty(local_usdz_cache.get("validation"))
        claim_valid = bool(stage_report.get("claim_valid"))
        rows[preset] = {
            "stage": stage.get("stage"),
            "scene_count": _optional_int(stage.get("scene_count")),
            "preset_tracked": True,
            "cache_builder_workflow_tracked": _has_command(stage, "build_local_cache"),
            "local_usdz_cache_valid": validation.get("valid"),
            "local_usdz_cache": _cache_inventory_status(local_usdz_cache),
            "source_usdz_cache": _cache_inventory_status(source_usdz_cache),
            "summary_artifact": stage.get("public_summary_target"),
            "summary_present": bool(stage_report.get("summary_present")),
            "claim_valid_closed_loop_summary_tracked": claim_valid,
            "remaining_runtime_requirement": _scale_runtime_requirement(
                claim_valid=claim_valid,
                local_cache_valid=validation.get("valid") is True,
            ),
        }
    return rows


def _objective_completion_status(
    *,
    stage_reports: list[dict[str, Any]],
    readiness: dict[str, Any],
    current_public_evidence: dict[str, Any],
    claim_ready: bool,
) -> dict[str, Any]:
    requirements = _objective_requirements(
        stage_reports=stage_reports,
        current_public_evidence=current_public_evidence,
        claim_ready=claim_ready,
    )
    remaining_requirements = [
        str(requirement["requirement"])
        for requirement in requirements
        if requirement.get("satisfied") is not True
    ]
    return {
        "complete": claim_ready,
        "satisfied_count": len(requirements) - len(remaining_requirements),
        "total_count": len(requirements),
        "remaining_requirements": remaining_requirements,
        "blocking_requirements": [] if claim_ready else _readiness_blocker_ids(readiness),
        "next_command_groups": [] if claim_ready else _readiness_next_group_names(readiness),
        "next_command_renderer_groups": (
            {} if claim_ready else _readiness_next_command_renderer_groups(readiness)
        ),
        "requirements": requirements,
    }


def _objective_requirements(
    *,
    stage_reports: list[dict[str, Any]],
    current_public_evidence: dict[str, Any],
    claim_ready: bool,
) -> list[dict[str, Any]]:
    ten_scene = _stage_report_by_scene_count(stage_reports, 10)
    fifty_scene = _stage_report_by_scene_count(stage_reports, 50)
    hundred_scene = _stage_report_by_scene_count(stage_reports, 100)
    diagnostic_progress = claim_ready or any(
        _dict_or_empty(current_public_evidence.get(key)).get("present") is True
        for key in ("fifty_scene_local_probe", "fifty_scene_partial_attempt")
    )
    return [
        {
            "requirement": "validate_10_scene_pilot",
            "satisfied": bool(ten_scene and ten_scene.get("claim_valid")),
            "evidence": ten_scene.get("summary_artifact") if ten_scene else None,
        },
        {
            "requirement": "track_50_scene_scale_progress",
            "satisfied": diagnostic_progress,
            "evidence": [
                _dict_or_empty(current_public_evidence.get(key)).get("artifact")
                for key in ("fifty_scene_local_probe", "fifty_scene_partial_attempt")
                if _dict_or_empty(current_public_evidence.get(key)).get("present") is True
            ],
        },
        {
            "requirement": "produce_claim_valid_50_scene_summary",
            "satisfied": bool(fifty_scene and fifty_scene.get("claim_valid")),
            "evidence": fifty_scene.get("summary_artifact") if fifty_scene else None,
        },
        {
            "requirement": "produce_claim_valid_100_scene_summary",
            "satisfied": bool(hundred_scene and hundred_scene.get("claim_valid")),
            "evidence": hundred_scene.get("summary_artifact") if hundred_scene else None,
        },
        {
            "requirement": "pass_strict_claim_gate",
            "satisfied": claim_ready,
            "evidence": "wod2sim-benchmark-audit --strict --json",
        },
    ]


def _stage_report_by_scene_count(
    stage_reports: list[dict[str, Any]], scene_count: int
) -> dict[str, Any]:
    for stage_report in stage_reports:
        if _optional_int(stage_report.get("expected_scene_count")) == scene_count:
            return stage_report
    return {}


def _readiness_blocker_ids(readiness: dict[str, Any]) -> list[str]:
    return [
        str(blocker.get("id"))
        for blocker in _list_of_dicts(readiness.get("blocking_requirements"))
        if blocker.get("id")
    ]


def _readiness_next_group_names(readiness: dict[str, Any]) -> list[str]:
    return [
        str(group.get("name"))
        for group in _list_of_dicts(readiness.get("next_command_groups"))
        if group.get("name")
    ]


def _readiness_next_command_renderer_groups(readiness: dict[str, Any]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for group in _list_of_dicts(readiness.get("next_command_groups")):
        name = group.get("name")
        if not isinstance(name, str) or not name:
            continue
        groups[name] = [
            str(value)
            for value in _list_or_empty(group.get("command_renderer_groups"))
            if isinstance(value, str) and value
        ]
    return groups


def _cache_inventory_status(cache: dict[str, Any]) -> dict[str, Any]:
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


def _scale_runtime_requirement(*, claim_valid: bool, local_cache_valid: bool) -> str:
    if claim_valid:
        return (
            "No remaining runtime requirement for the tracked public claim; rerunning still "
            "requires an x86_64 AlpaSim runner with Docker/NVIDIA runtime images installed."
        )
    if local_cache_valid:
        return (
            "The local 26.02 USDZ cache is ready; run the remaining stage and promote its "
            "summary on an x86_64 AlpaSim runner with Docker/NVIDIA runtime images installed."
        )
    return (
        "Build or restore a metadata-valid local 26.02 USDZ cache, then run the stage on an "
        "x86_64 AlpaSim runner with Docker/NVIDIA runtime images installed."
    )


def _completion_reason(
    *,
    claim_ready: bool,
    scale_status: dict[str, dict[str, Any]],
) -> str:
    if claim_ready:
        return (
            "The repository tracks claim-valid public summaries for every planned stage "
            "in the regeneration plan."
        )
    missing = [
        row["summary_artifact"]
        for row in scale_status.values()
        if not row["claim_valid_closed_loop_summary_tracked"]
    ]
    missing_text = ", ".join(missing) if missing else "scale summaries"
    return (
        "The repository tracks a valid 10-scene public summary plus a plan, readiness "
        "snapshot, and audit gate, but fresh regenerated claim-valid scale summaries "
        f"are not currently present: {missing_text}."
    )


def _has_command(stage: dict[str, Any], name: str) -> bool:
    commands = _dict_or_empty(stage.get("commands"))
    return isinstance(commands.get(name), dict)


def _by_preset(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("scene_preset") or ""): row for row in rows}


def _probe_ok(value: object) -> bool | None:
    if not isinstance(value, dict):
        return None
    ok = value.get("ok")
    return ok if isinstance(ok, bool) else None


def _require_schema(payload: dict[str, Any], schema: str, label: str) -> None:
    actual = payload.get("schema")
    if actual != schema:
        raise ValueError(f"{label} schema must be {schema}, got {actual!r}")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object JSON at {path}")
    return payload


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return _read_json(path)


def _list_of_dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _list_or_empty(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _dict_or_empty(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
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
            return None
    return None


def _resolve_path(repo_root: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return repo_root / path


def _display_path(path: Path) -> str:
    return str(path) if path.is_absolute() else path.as_posix()


def _print_human_summary(status: dict[str, Any]) -> None:
    completion = status["completion_status"]
    marker = "complete" if completion["full_objective_complete"] else "incomplete"
    print(f"{status['schema']}: {marker}")
    print(f"- ten_scene_pilot: {status['current_public_evidence']['ten_scene_pilot']['artifact']}")
    for preset, row in status["scale_status"].items():
        claim = "claim-valid" if row["claim_valid_closed_loop_summary_tracked"] else "not-ready"
        print(f"- {preset}: {claim} -> {row['summary_artifact']}")


if __name__ == "__main__":
    raise SystemExit(main())
