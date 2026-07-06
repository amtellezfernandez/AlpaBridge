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
    current_runtime = _dict_or_empty(status.get("current_local_runtime_state"))
    evidence_artifacts = _dict_or_empty(status.get("evidence_artifacts"))
    public_policy = _dict_or_empty(status.get("public_artifact_policy"))

    return {
        "schema": MATRIX_SCHEMA,
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "source_artifacts": {
            "plan": _display_path(plan_path),
            "status": _display_path(status_path),
            "readiness": _display_path(readiness_path),
        },
        "generator": {
            "command": "wod2sim-benchmark-operators",
            "no_download_or_rollout_probes": True,
        },
        "public_artifact_policy": {
            "tracked": public_policy.get("tracked"),
            "untracked": public_policy.get("untracked"),
        },
        "current_local_state": _current_local_state(
            readiness_flags=readiness_flags,
            current_runtime=current_runtime,
        ),
        "roles": _roles(readiness_flags=readiness_flags, blockers=blockers),
        "task_matrix": _task_matrix(
            readiness_flags=readiness_flags,
            blockers=blockers,
            evidence_artifacts=evidence_artifacts,
        ),
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


def _print_human_summary(matrix: dict[str, Any]) -> None:
    print(matrix["schema"])
    for role in matrix["roles"]:
        state = "ready" if role["can_run_now_from_tracked_state"] else "blocked"
        print(f"- {role['role']}: {state}")


if __name__ == "__main__":
    raise SystemExit(main())
