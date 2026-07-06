from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

MATRIX_SCHEMA = "wod2sim_benchmark_operator_matrix_v1"
PLAN_SCHEMA = "wod2sim_benchmark_regeneration_plan_v1"
STATUS_SCHEMA = "wod2sim_benchmark_regeneration_status_v1"
READINESS_SCHEMA = "wod2sim_benchmark_regeneration_readiness_v1"
DEFAULT_MATRIX = Path("docs/evidence/benchmark_operator_matrix_20260706.json")
DEFAULT_PLAN = Path("docs/evidence/benchmark_regeneration_plan_20260706.json")
DEFAULT_STATUS = Path("docs/evidence/benchmark_regeneration_status_20260706.json")
DEFAULT_READINESS = Path("docs/evidence/benchmark_regeneration_readiness_20260706.json")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render the public benchmark operator capability matrix from tracked "
            "plan/status/readiness JSON. This command does not probe Docker, GPUs, "
            "caches, or gated assets."
        )
    )
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--readiness", type=Path, default=DEFAULT_READINESS)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--created-at", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    matrix = build_operator_matrix(
        plan_path=args.plan,
        status_path=args.status,
        readiness_path=args.readiness,
        repo_root=args.repo_root,
        created_at=args.created_at,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(matrix, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(matrix, indent=2, sort_keys=True))
    else:
        _print_human_summary(matrix)
    return 0


def build_operator_matrix(
    *,
    plan_path: Path = DEFAULT_PLAN,
    status_path: Path = DEFAULT_STATUS,
    readiness_path: Path = DEFAULT_READINESS,
    repo_root: Path = Path.cwd(),
    created_at: str | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    plan = _read_json(_resolve_path(repo_root, plan_path))
    status = _read_json(_resolve_path(repo_root, status_path))
    readiness = _read_json(_resolve_path(repo_root, readiness_path))

    _require_schema(plan, PLAN_SCHEMA, "plan")
    _require_schema(status, STATUS_SCHEMA, "status")
    _require_schema(readiness, READINESS_SCHEMA, "readiness")

    readiness_flags = _dict_or_empty(readiness.get("readiness"))
    blockers = _list_of_dicts(readiness.get("blocking_requirements"))
    next_command_groups = _list_of_dicts(readiness.get("next_command_groups"))
    current_runtime = _dict_or_empty(status.get("current_local_runtime_state"))
    evidence_artifacts = _dict_or_empty(status.get("evidence_artifacts"))
    command_artifact_path = Path(str(evidence_artifacts.get("regeneration_commands") or ""))
    resume_command_artifact_path = Path(
        str(evidence_artifacts.get("regeneration_resume_commands") or "")
    )
    command_artifact = _read_json(_resolve_path(repo_root, command_artifact_path))
    resume_command_artifact = _read_json(_resolve_path(repo_root, resume_command_artifact_path))
    public_policy = _dict_or_empty(status.get("public_artifact_policy"))
    current_local_state = _current_local_state(
        readiness_flags=readiness_flags,
        current_runtime=current_runtime,
    )
    command_execution = _command_execution_summary(
        command_artifact=command_artifact,
        command_artifact_path=command_artifact_path,
    )
    resume_command_execution = _command_execution_summary(
        command_artifact=resume_command_artifact,
        command_artifact_path=resume_command_artifact_path,
    )
    resume_repair_scope = _resume_repair_scope(
        command_artifact=resume_command_artifact,
        command_artifact_path=resume_command_artifact_path,
    )
    roles = _roles(readiness_flags=readiness_flags, blockers=blockers)
    task_matrix = _task_matrix(
        readiness_flags=readiness_flags,
        blockers=blockers,
        evidence_artifacts=evidence_artifacts,
    )

    return {
        "schema": MATRIX_SCHEMA,
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "summary": _matrix_summary(
            readiness_flags=readiness_flags,
            blockers=blockers,
            next_command_groups=next_command_groups,
            roles=roles,
            task_matrix=task_matrix,
            command_execution=command_execution,
            resume_command_execution=resume_command_execution,
            resume_repair_scope=resume_repair_scope,
        ),
        "source_artifacts": {
            "plan": _display_path(plan_path),
            "status": _display_path(status_path),
            "readiness": _display_path(readiness_path),
            "regeneration_commands": _display_path(command_artifact_path),
            "regeneration_resume_commands": _display_path(resume_command_artifact_path),
        },
        "generator": {
            "command": "wod2sim-benchmark-operators",
            "no_download_or_rollout_probes": True,
        },
        "public_artifact_policy": {
            "tracked": public_policy.get("tracked"),
            "untracked": public_policy.get("untracked"),
        },
        "current_local_state": current_local_state,
        "command_execution": command_execution,
        "resume_command_execution": resume_command_execution,
        "resume_repair_scope": resume_repair_scope,
        "roles": roles,
        "task_matrix": task_matrix,
    }


def _current_local_state(
    *,
    readiness_flags: dict[str, Any],
    current_runtime: dict[str, Any],
) -> dict[str, Any]:
    return {
        "host_machine": current_runtime.get("host_machine"),
        "closed_loop_runner_supported": current_runtime.get("closed_loop_runner_supported"),
        "docker_daemon_ok": current_runtime.get("docker_daemon_ok"),
        "docker_nvidia_runtime_present": current_runtime.get("docker_nvidia_runtime_present"),
        "nvidia_smi_ok": current_runtime.get("nvidia_smi_ok"),
        "alpasim_base_image_present": current_runtime.get("alpasim_base_image_present"),
        "cache_build_ready": bool(readiness_flags.get("cache_build_ready")),
        "closed_loop_runner_ready": bool(readiness_flags.get("closed_loop_runner_ready")),
        "all_scale_caches_valid": bool(readiness_flags.get("all_scale_caches_valid")),
        "all_scale_source_caches_valid": bool(readiness_flags.get("all_scale_source_caches_valid")),
        "source_cache_link_ready": bool(readiness_flags.get("source_cache_link_ready")),
        "claim_valid_scale_summaries_present": bool(
            readiness_flags.get("claim_valid_scale_summaries_present")
        ),
    }


def _roles(
    *,
    readiness_flags: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cache_blockers = _blocker_ids(blockers, blocks={"scale_cache_build"})
    rollout_blockers = _blocker_ids(blockers, blocks={"closed_loop_rollout"})
    claim_blockers = _blocker_ids(blockers, blocks={"full_benchmark_claim"})
    return [
        {
            "role": "open_repo_reviewer",
            "who_can_do": "Anyone with the repository and a supported Python environment.",
            "can_run_now_from_tracked_state": True,
            "requires_private_assets": False,
            "requires_gpu": False,
            "requires_x86_64_linux": False,
            "can_run": [
                "public tests",
                "dry benchmark plans",
                "compact summary/status/command/operator artifacts",
                "non-mutating evidence audits",
            ],
            "cannot_run": [
                "download gated USDZ artifacts",
                "build private local scene caches without credentials",
                "execute live AlpaSim SensorSim rollouts",
            ],
            "claim_scope": "Can review existing public evidence but cannot create new closed-loop scale claims.",
            "current_blocker_ids": [],
        },
        {
            "role": "cache_builder",
            "who_can_do": (
                "Operator with Hugging Face access to the 26.02 artifacts, enough disk, "
                "and the Python cache-builder dependencies."
            ),
            "can_run_now_from_tracked_state": bool(readiness_flags.get("cache_build_ready")),
            "requires_private_assets": True,
            "requires_gpu": False,
            "requires_x86_64_linux": False,
            "can_run": [
                "wod2sim-build-local-cache",
                "wod2sim-build-local-cache --validate-only",
            ],
            "cannot_run": [
                "produce claim-valid closed-loop summaries without a separate live runner",
            ],
            "claim_scope": "Can prepare required local USDZ caches; cache validity alone is not a benchmark claim.",
            "current_blocker_ids": cache_blockers,
        },
        {
            "role": "closed_loop_runner",
            "who_can_do": (
                "Operator on x86_64 Linux with Docker, NVIDIA runtime, AlpaSim images, "
                "valid local scene caches, and gated scene access."
            ),
            "can_run_now_from_tracked_state": bool(readiness_flags.get("closed_loop_runner_ready")),
            "requires_private_assets": True,
            "requires_gpu": True,
            "requires_x86_64_linux": True,
            "can_run": [
                "wod2sim-batch live AlpaSim rollouts",
                "scale-stage shard commands",
                "wod2sim-batch-summary for completed shard summaries",
            ],
            "cannot_run": [
                "publish a full 50/100 claim until every planned shard is complete and merged",
            ],
            "claim_scope": "Can produce the raw inputs for claim-valid scale summaries when prerequisites are ready.",
            "current_blocker_ids": rollout_blockers,
        },
        {
            "role": "claim_promoter",
            "who_can_do": (
                "Maintainer with completed closed-loop summaries, shard provenance, and "
                "permission to publish compact public evidence."
            ),
            "can_run_now_from_tracked_state": bool(
                readiness_flags.get("claim_valid_scale_summaries_present")
            ),
            "requires_private_assets": False,
            "requires_gpu": False,
            "requires_x86_64_linux": False,
            "can_run": [
                "wod2sim-promote-batch-summary",
                "wod2sim-benchmark-status",
                "wod2sim-benchmark-audit --strict --json",
            ],
            "cannot_run": [
                "promote missing or partial 50/100 summaries as full benchmark claims",
            ],
            "claim_scope": "Can publish compact claim evidence only after full-stage summaries pass the audit gate.",
            "current_blocker_ids": claim_blockers,
        },
        {
            "role": "arm_dgx_spark_host",
            "who_can_do": "ARM/Linux operator, including DGX Spark-style hosts.",
            "can_run_now_from_tracked_state": True,
            "requires_private_assets": False,
            "requires_gpu": False,
            "requires_x86_64_linux": False,
            "can_run": [
                "cache preparation when credentials and disk are available",
                "diagnostic commands that do not start the amd64 SensorSim container",
            ],
            "cannot_run": [
                "live SensorSim rollouts by default because the required AlpaSim image is amd64-only",
            ],
            "claim_scope": "Can assist with preparation but is not a supported live rollout host by default.",
            "current_blocker_ids": ["live_rollout_blocked_by_default_on_arm64"],
        },
    ]


def _task_matrix(
    *,
    readiness_flags: dict[str, Any],
    blockers: list[dict[str, Any]],
    evidence_artifacts: dict[str, Any],
) -> list[dict[str, Any]]:
    cache_blockers = _blocker_ids(blockers, blocks={"scale_cache_build"})
    rollout_blockers = _blocker_ids(blockers, blocks={"closed_loop_rollout"})
    claim_blockers = _blocker_ids(blockers, blocks={"full_benchmark_claim"})
    return [
        {
            "task": "review_public_evidence",
            "who_can_run": "open_repo_reviewer",
            "current_state": "ready",
            "requires_private_assets": False,
            "command_groups": ["status", "commands", "operators", "audit"],
            "evidence_artifacts": sorted(str(value) for value in evidence_artifacts.values()),
            "claim_boundary": "Review only; does not create new benchmark evidence.",
            "current_blocker_ids": [],
        },
        {
            "task": "build_and_validate_26_02_usdz_cache",
            "who_can_run": "cache_builder",
            "current_state": (
                "ready" if readiness_flags.get("cache_build_ready") else "blocked_in_tracked_state"
            ),
            "requires_private_assets": True,
            "command_groups": ["cache"],
            "claim_boundary": "Required prerequisite for scale rollouts, not a closed-loop claim.",
            "current_blocker_ids": cache_blockers,
        },
        {
            "task": "run_live_scale_shards",
            "who_can_run": "closed_loop_runner",
            "current_state": (
                "ready"
                if readiness_flags.get("closed_loop_runner_ready")
                else "blocked_in_tracked_state"
            ),
            "requires_private_assets": True,
            "command_groups": ["shards", "merge"],
            "claim_boundary": "Shard outputs are checkpoints until full-stage summaries are merged.",
            "current_blocker_ids": rollout_blockers,
        },
        {
            "task": "promote_claim_valid_50_100_summaries",
            "who_can_run": "claim_promoter",
            "current_state": (
                "ready"
                if readiness_flags.get("claim_valid_scale_summaries_present")
                else "blocked_in_tracked_state"
            ),
            "requires_private_assets": False,
            "command_groups": ["promote", "post"],
            "claim_boundary": "Only complete 50/100 summaries may satisfy the strict claim gate.",
            "current_blocker_ids": claim_blockers,
        },
    ]


def _matrix_summary(
    *,
    readiness_flags: dict[str, Any],
    blockers: list[dict[str, Any]],
    next_command_groups: list[dict[str, Any]],
    roles: list[dict[str, Any]],
    task_matrix: list[dict[str, Any]],
    command_execution: dict[str, Any],
    resume_command_execution: dict[str, Any],
    resume_repair_scope: dict[str, Any],
) -> dict[str, Any]:
    ready_roles = [
        str(role.get("role"))
        for role in roles
        if role.get("role") and role.get("can_run_now_from_tracked_state") is True
    ]
    blocked_roles = [
        str(role.get("role"))
        for role in roles
        if role.get("role") and role.get("can_run_now_from_tracked_state") is not True
    ]
    ready_tasks = [
        str(task.get("task"))
        for task in task_matrix
        if task.get("task") and task.get("current_state") == "ready"
    ]
    blocked_tasks = [
        str(task.get("task"))
        for task in task_matrix
        if task.get("task") and task.get("current_state") != "ready"
    ]
    return {
        "claim_ready": bool(readiness_flags.get("claim_valid_scale_summaries_present")),
        "open_repo_review_ready": "open_repo_reviewer" in ready_roles,
        "ready_roles": ready_roles,
        "blocked_roles": blocked_roles,
        "ready_tasks": ready_tasks,
        "blocked_tasks": blocked_tasks,
        "remaining_blocker_ids": [
            str(blocker.get("id")) for blocker in blockers if blocker.get("id")
        ],
        "next_command_groups": [
            str(group.get("name")) for group in next_command_groups if group.get("name")
        ],
        "next_command_renderer_groups": {
            str(group.get("name")): [
                str(renderer_group)
                for renderer_group in _list_or_empty(group.get("command_renderer_groups"))
                if isinstance(renderer_group, str)
            ]
            for group in next_command_groups
            if group.get("name")
        },
        "command_execution_boundary_counts": _dict_or_empty(
            command_execution.get("execution_boundary_counts")
        ),
        "command_operator_role_counts": _dict_or_empty(
            command_execution.get("operator_role_counts")
        ),
        "public_review_command_count": command_execution.get("public_review_command_count"),
        "private_execution_command_count": command_execution.get("private_execution_command_count"),
        "resume_command_execution_boundary_counts": _dict_or_empty(
            resume_command_execution.get("execution_boundary_counts")
        ),
        "resume_command_operator_role_counts": _dict_or_empty(
            resume_command_execution.get("operator_role_counts")
        ),
        "resume_public_review_command_count": resume_command_execution.get(
            "public_review_command_count"
        ),
        "resume_private_execution_command_count": resume_command_execution.get(
            "private_execution_command_count"
        ),
        "resume_affected_stage_count": resume_repair_scope.get("affected_stage_count"),
        "resume_missing_shard_summary_count": resume_repair_scope.get(
            "missing_shard_summary_count"
        ),
        "resume_repair_included_groups": _list_or_empty(resume_repair_scope.get("included_groups")),
        "resume_repair_command_group_counts": _dict_or_empty(
            resume_repair_scope.get("command_group_counts")
        ),
        "live_rollout_host_requirement": (
            "x86_64 Linux with Docker, NVIDIA runtime, AlpaSim images, "
            "valid local USDZ caches, and gated scene access"
        ),
        "public_claim_boundary": (
            "Open-repo reviewers can audit compact public evidence; new 50/100 "
            "closed-loop claims require completed full-stage summaries."
        ),
    }


def _command_execution_summary(
    *,
    command_artifact: dict[str, Any],
    command_artifact_path: Path,
) -> dict[str, Any]:
    return {
        "artifact": _display_path(command_artifact_path),
        "row_count": _optional_int(command_artifact.get("row_count")),
        "group_counts": _dict_or_empty(command_artifact.get("group_counts")),
        "execution_boundary_counts": _dict_or_empty(
            command_artifact.get("execution_boundary_counts")
        ),
        "operator_role_counts": _dict_or_empty(command_artifact.get("operator_role_counts")),
        "public_review_command_count": _optional_int(
            command_artifact.get("public_review_command_count")
        ),
        "private_execution_command_count": _optional_int(
            command_artifact.get("private_execution_command_count")
        ),
    }


def _resume_repair_scope(
    *,
    command_artifact: dict[str, Any],
    command_artifact_path: Path,
) -> dict[str, Any]:
    resume_plan = _dict_or_empty(command_artifact.get("resume_plan"))
    stages = []
    for stage in _list_of_dicts(resume_plan.get("stages")):
        stages.append(
            {
                "stage": stage.get("stage"),
                "scene_preset": stage.get("scene_preset"),
                "scene_count": _optional_int(stage.get("scene_count")),
                "public_summary_target": stage.get("public_summary_target"),
                "missing_shard_summary_count": _optional_int(
                    stage.get("missing_shard_summary_count")
                ),
                "missing_shard_indexes": [
                    index
                    for index in (
                        _optional_int(value)
                        for value in _list_or_empty(stage.get("missing_shard_indexes"))
                    )
                    if index is not None
                ],
                "missing_shard_summary_paths": [
                    str(path)
                    for path in _list_or_empty(stage.get("missing_shard_summary_paths"))
                    if isinstance(path, str) and path
                ],
                "merge_command_included": bool(stage.get("merge_command_included")),
                "promote_command_included": bool(stage.get("promote_command_included")),
                "post_review_commands_included": bool(stage.get("post_review_commands_included")),
            }
        )
    return {
        "artifact": _display_path(command_artifact_path),
        "claim_boundary": resume_plan.get("claim_boundary"),
        "affected_stage_count": _optional_int(resume_plan.get("affected_stage_count")),
        "missing_shard_summary_count": _optional_int(
            resume_plan.get("missing_shard_summary_count")
        ),
        "included_groups": [
            str(group)
            for group in _list_or_empty(resume_plan.get("included_groups"))
            if isinstance(group, str) and group
        ],
        "command_group_counts": _dict_or_empty(resume_plan.get("command_group_counts")),
        "stages": stages,
    }


def _blocker_ids(blockers: list[dict[str, Any]], *, blocks: set[str]) -> list[str]:
    return [
        str(blocker.get("id"))
        for blocker in blockers
        if blocker.get("blocks") in blocks and blocker.get("id")
    ]


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object JSON at {path}")
    return payload


def _require_schema(payload: dict[str, Any], schema: str, label: str) -> None:
    actual = payload.get("schema")
    if actual != schema:
        raise ValueError(f"{label} schema must be {schema}, got {actual!r}")


def _resolve_path(repo_root: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return repo_root / path


def _display_path(path: Path) -> str:
    return str(path) if path.is_absolute() else path.as_posix()


def _dict_or_empty(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _list_or_empty(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return None


def _print_human_summary(matrix: dict[str, Any]) -> None:
    print(matrix["schema"])
    summary = _dict_or_empty(matrix.get("summary"))
    if summary:
        print(f"claim_ready: {summary.get('claim_ready')}")
        blockers = ", ".join(str(item) for item in summary.get("remaining_blocker_ids", []))
        print(f"remaining_blocker_ids: {blockers or 'none'}")
    for role in matrix["roles"]:
        state = "ready" if role["can_run_now_from_tracked_state"] else "blocked"
        print(f"- {role['role']}: {state}")


if __name__ == "__main__":
    raise SystemExit(main())
