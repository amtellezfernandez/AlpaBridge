from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLAN_RELATIVE = Path("docs/evidence/benchmark_regeneration_plan_20260706.json")
STATUS_RELATIVE = Path("docs/evidence/benchmark_regeneration_status_20260706.json")
READINESS_RELATIVE = Path("docs/evidence/benchmark_regeneration_readiness_20260706.json")
OPERATOR_MATRIX_RELATIVE = Path("docs/evidence/benchmark_operator_matrix_20260706.json")
COMMANDS_RELATIVE = Path("docs/evidence/benchmark_regeneration_commands_20260706.json")
RESUME_COMMANDS_RELATIVE = Path(
    "docs/evidence/benchmark_regeneration_resume_commands_20260706.json"
)


def _expected_missing_shard(
    scene_count: int, shard_index: int, scene_offset: int
) -> dict[str, object]:
    shard_name = f"{scene_offset:03d}_{scene_offset + 9:03d}"
    base = (
        f"runs/benchmark_spotlight_reflex_{scene_count}scene_public2602_fresh/shards/{shard_name}"
    )
    return {
        "run_command_included": True,
        "run_dir": base,
        "scene_limit": 10,
        "scene_offset": scene_offset,
        "shard_index": shard_index,
        "summary_errors": ["summary_missing"],
        "summary_path": f"{base}/wod2sim-batch-summary.json",
        "write_summary_command_included": True,
    }


EXPECTED_50_MISSING_SHARDS = [
    _expected_missing_shard(50, shard_index, scene_offset)
    for shard_index, scene_offset in enumerate(range(0, 50, 10), start=1)
]
EXPECTED_100_MISSING_SHARDS = [
    _expected_missing_shard(100, shard_index, scene_offset)
    for shard_index, scene_offset in enumerate(range(0, 100, 10), start=1)
]


def test_operator_matrix_builder_reflects_tracked_readiness_blockers() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_operator_matrix")

    matrix = module.build_operator_matrix(
        plan_path=ROOT / PLAN_RELATIVE,
        status_path=ROOT / STATUS_RELATIVE,
        readiness_path=ROOT / READINESS_RELATIVE,
        created_at="2026-07-06",
    )
    roles = {role["role"]: role for role in matrix["roles"]}
    summary = matrix["summary"]

    assert matrix["schema"] == "wod2sim_benchmark_operator_matrix_v1"
    assert matrix["created_at"] == "2026-07-06"
    assert matrix["source_artifacts"]["plan"] == (ROOT / PLAN_RELATIVE).as_posix()
    assert matrix["source_artifacts"]["regeneration_commands"] == COMMANDS_RELATIVE.as_posix()
    assert (
        matrix["source_artifacts"]["regeneration_resume_commands"]
        == RESUME_COMMANDS_RELATIVE.as_posix()
    )
    assert matrix["generator"]["no_download_or_rollout_probes"] is True
    assert summary["open_repo_review_ready"] is True
    assert summary["claim_ready"] is False
    assert summary["command_execution_boundary_counts"]["public_metadata_review"] == 4
    assert summary["command_operator_role_counts"]["closed_loop_runner"] == 32
    assert summary["private_execution_command_count"] == 43
    assert summary["public_review_command_count"] == 4
    assert summary["resume_private_execution_command_count"] == 34
    assert summary["resume_public_review_command_count"] == 2
    assert summary["resume_command_execution_boundary_counts"] == {
        "claim_summary_merge": 2,
        "claim_summary_promotion": 2,
        "live_closed_loop_rollout": 30,
        "public_metadata_review": 2,
    }
    assert summary["resume_affected_stage_count"] == 2
    assert summary["resume_missing_shard_summary_count"] == 15
    assert summary["resume_repair_included_groups"] == [
        "shards",
        "merge",
        "promote",
        "post",
    ]
    assert summary["resume_repair_command_group_counts"] == {
        "merge": 2,
        "post": 2,
        "promote": 2,
        "shards": 30,
    }
    assert matrix["resume_repair_scope"]["stages"][0]["missing_shard_indexes"] == [
        1,
        2,
        3,
        4,
        5,
    ]
    assert matrix["resume_repair_scope"]["stages"][1]["missing_shard_summary_count"] == 10
    assert (
        matrix["resume_repair_scope"]["stages"][0]["missing_shards"][0]
        == (EXPECTED_50_MISSING_SHARDS[0])
    )
    assert (
        matrix["resume_repair_scope"]["stages"][1]["missing_shards"][-1]
        == (EXPECTED_100_MISSING_SHARDS[-1])
    )
    assert "open_repo_reviewer" in summary["ready_roles"]
    assert "closed_loop_runner" in summary["blocked_roles"]
    assert "build_and_validate_scale_caches" in summary["next_command_groups"]
    assert summary["next_command_renderer_groups"]["build_and_validate_scale_caches"] == ["cache"]
    assert "hf_token_missing" in summary["remaining_blocker_ids"]
    assert roles["open_repo_reviewer"]["can_run_now_from_tracked_state"] is True
    assert roles["open_repo_reviewer"]["requires_private_assets"] is False
    assert roles["cache_builder"]["can_run_now_from_tracked_state"] is False
    assert "hf_token_missing" in roles["cache_builder"]["current_blocker_ids"]
    assert roles["closed_loop_runner"]["requires_x86_64_linux"] is True
    assert "alpasim_base_image_missing" in roles["closed_loop_runner"]["current_blocker_ids"]
    assert roles["claim_promoter"]["can_run_now_from_tracked_state"] is False
    assert (
        "front_camera_100scene_public2602_claim_summary_missing"
        in roles["claim_promoter"]["current_blocker_ids"]
    )
    assert "amd64-only" in roles["arm_dgx_spark_host"]["cannot_run"][0]


def test_operator_matrix_main_writes_artifact_without_runtime_probes() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_operator_matrix")
    with TemporaryDirectory() as tmpdir:
        stdout = Path(tmpdir) / "stdout.json"
        output = Path(tmpdir) / "operator-matrix.json"

        with (
            stdout.open("w", encoding="utf-8") as handle,
            patch.object(
                sys,
                "argv",
                [
                    "wod2sim-benchmark-operators",
                    "--repo-root",
                    str(ROOT),
                    "--created-at",
                    "2026-07-06",
                    "--output",
                    str(output),
                    "--json",
                ],
            ),
            patch("sys.stdout", handle),
        ):
            returncode = module.main()

        emitted = json.loads(stdout.read_text(encoding="utf-8"))
        artifact = json.loads(output.read_text(encoding="utf-8"))

    assert returncode == 0
    assert emitted == artifact
    assert artifact["created_at"] == "2026-07-06"
    assert artifact["current_local_state"]["closed_loop_runner_ready"] is False
    assert artifact["current_local_state"]["source_cache_link_ready"] is False


def test_tracked_operator_matrix_is_public_safe_and_explicit_about_who_can_run() -> None:
    matrix = json.loads((ROOT / OPERATOR_MATRIX_RELATIVE).read_text(encoding="utf-8"))
    rendered = json.dumps(matrix, sort_keys=True)
    roles = {role["role"]: role for role in matrix["roles"]}
    tasks = {task["task"]: task for task in matrix["task_matrix"]}
    summary = matrix["summary"]

    assert matrix["schema"] == "wod2sim_benchmark_operator_matrix_v1"
    assert matrix["source_artifacts"] == {
        "regeneration_commands": COMMANDS_RELATIVE.as_posix(),
        "regeneration_resume_commands": RESUME_COMMANDS_RELATIVE.as_posix(),
        "plan": PLAN_RELATIVE.as_posix(),
        "readiness": READINESS_RELATIVE.as_posix(),
        "status": STATUS_RELATIVE.as_posix(),
    }
    assert matrix["generator"]["command"] == "wod2sim-benchmark-operators"
    assert "/home/" not in rendered
    assert summary["claim_ready"] is False
    assert summary["open_repo_review_ready"] is True
    assert matrix["command_execution"] == {
        "artifact": COMMANDS_RELATIVE.as_posix(),
        "execution_boundary_counts": {
            "claim_summary_merge": 2,
            "claim_summary_promotion": 3,
            "live_closed_loop_rollout": 32,
            "private_cache_preparation": 6,
            "public_metadata_review": 4,
        },
        "group_counts": {
            "cache": 6,
            "cleanup": 1,
            "merge": 2,
            "post": 2,
            "promote": 3,
            "readiness": 1,
            "run": 2,
            "shards": 30,
        },
        "operator_role_counts": {
            "cache_builder": 6,
            "claim_promoter": 5,
            "closed_loop_runner": 32,
            "open_repo_reviewer": 4,
        },
        "private_execution_command_count": 43,
        "public_review_command_count": 4,
        "row_count": 47,
    }
    assert matrix["resume_command_execution"] == {
        "artifact": RESUME_COMMANDS_RELATIVE.as_posix(),
        "execution_boundary_counts": {
            "claim_summary_merge": 2,
            "claim_summary_promotion": 2,
            "live_closed_loop_rollout": 30,
            "public_metadata_review": 2,
        },
        "group_counts": {
            "merge": 2,
            "post": 2,
            "promote": 2,
            "shards": 30,
        },
        "operator_role_counts": {
            "claim_promoter": 4,
            "closed_loop_runner": 30,
            "open_repo_reviewer": 2,
        },
        "private_execution_command_count": 34,
        "public_review_command_count": 2,
        "row_count": 36,
    }
    assert matrix["resume_repair_scope"] == {
        "affected_stage_count": 2,
        "artifact": RESUME_COMMANDS_RELATIVE.as_posix(),
        "claim_boundary": (
            "Audit-derived resume rows are operational repair inputs only; the strict "
            "claim gate remains false until full 50/100 summaries are merged, promoted, "
            "and claim-valid."
        ),
        "command_group_counts": {
            "merge": 2,
            "post": 2,
            "promote": 2,
            "shards": 30,
        },
        "included_groups": ["shards", "merge", "promote", "post"],
        "missing_shard_summary_count": 15,
        "stages": [
            {
                "merge_command_included": True,
                "missing_shard_indexes": [1, 2, 3, 4, 5],
                "missing_shard_summary_count": 5,
                "missing_shard_summary_paths": [
                    "runs/benchmark_spotlight_reflex_50scene_public2602_fresh/shards/000_009/wod2sim-batch-summary.json",
                    "runs/benchmark_spotlight_reflex_50scene_public2602_fresh/shards/010_019/wod2sim-batch-summary.json",
                    "runs/benchmark_spotlight_reflex_50scene_public2602_fresh/shards/020_029/wod2sim-batch-summary.json",
                    "runs/benchmark_spotlight_reflex_50scene_public2602_fresh/shards/030_039/wod2sim-batch-summary.json",
                    "runs/benchmark_spotlight_reflex_50scene_public2602_fresh/shards/040_049/wod2sim-batch-summary.json",
                ],
                "missing_shards": EXPECTED_50_MISSING_SHARDS,
                "post_review_commands_included": True,
                "promote_command_included": True,
                "public_summary_target": "docs/evidence/closed_loop_spotlight_reflex_50scene_batch.json",
                "scene_count": 50,
                "scene_preset": "front_camera_50scene_public2602",
                "stage": "workshop_scale",
            },
            {
                "merge_command_included": True,
                "missing_shard_indexes": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                "missing_shard_summary_count": 10,
                "missing_shard_summary_paths": [
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/000_009/wod2sim-batch-summary.json",
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/010_019/wod2sim-batch-summary.json",
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/020_029/wod2sim-batch-summary.json",
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/030_039/wod2sim-batch-summary.json",
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/040_049/wod2sim-batch-summary.json",
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/050_059/wod2sim-batch-summary.json",
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/060_069/wod2sim-batch-summary.json",
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/070_079/wod2sim-batch-summary.json",
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/080_089/wod2sim-batch-summary.json",
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/090_099/wod2sim-batch-summary.json",
                ],
                "missing_shards": EXPECTED_100_MISSING_SHARDS,
                "post_review_commands_included": True,
                "promote_command_included": True,
                "public_summary_target": "docs/evidence/closed_loop_spotlight_reflex_100scene_batch.json",
                "scene_count": 100,
                "scene_preset": "front_camera_100scene_public2602",
                "stage": "stronger_benchmark",
            },
        ],
    }
    assert summary["ready_tasks"] == ["review_public_evidence"]
    assert summary["blocked_tasks"] == [
        "build_and_validate_26_02_usdz_cache",
        "run_live_scale_shards",
        "promote_claim_valid_50_100_summaries",
    ]
    assert summary["next_command_renderer_groups"] == {
        "build_and_validate_scale_caches": ["cache"],
        "refresh_readiness": ["readiness"],
        "refresh_status": ["post"],
        "run_scale_shards_and_promote_summaries": ["shards", "merge", "promote"],
        "verify_claim_gate": ["post"],
    }
    assert summary["remaining_blocker_ids"] == [
        "hf_token_missing",
        "docker_daemon_unavailable",
        "alpasim_base_image_missing",
        "nvidia_gpu_unavailable",
        "docker_nvidia_runtime_unavailable",
        "front_camera_50scene_public2602_cache_invalid",
        "front_camera_50scene_public2602_claim_summary_missing",
        "front_camera_100scene_public2602_cache_invalid",
        "front_camera_100scene_public2602_claim_summary_missing",
    ]
    assert (
        RESUME_COMMANDS_RELATIVE.as_posix() in tasks["review_public_evidence"]["evidence_artifacts"]
    )
    assert "x86_64 Linux" in summary["live_rollout_host_requirement"]
    assert roles["open_repo_reviewer"]["can_run_now_from_tracked_state"] is True
    assert roles["cache_builder"]["requires_gpu"] is False
    assert roles["cache_builder"]["requires_private_assets"] is True
    assert matrix["current_local_state"]["all_scale_source_caches_valid"] is False
    assert matrix["current_local_state"]["source_cache_link_ready"] is False
    assert roles["closed_loop_runner"]["requires_gpu"] is True
    assert roles["closed_loop_runner"]["can_run_now_from_tracked_state"] is False
    assert roles["arm_dgx_spark_host"]["claim_scope"].endswith(
        "not a supported live rollout host by default."
    )
    assert tasks["review_public_evidence"]["current_state"] == "ready"
    assert tasks["build_and_validate_26_02_usdz_cache"]["current_state"] == (
        "blocked_in_tracked_state"
    )
    assert tasks["promote_claim_valid_50_100_summaries"]["current_blocker_ids"] == [
        "front_camera_50scene_public2602_claim_summary_missing",
        "front_camera_100scene_public2602_claim_summary_missing",
    ]
