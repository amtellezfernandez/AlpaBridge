from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLAN_RELATIVE = Path("docs/evidence/benchmark_regeneration_plan_20260706.json")
AUDIT_RELATIVE = Path("docs/evidence/benchmark_regeneration_audit_20260706.json")
COMMANDS_RELATIVE = Path("docs/evidence/benchmark_regeneration_commands_20260706.json")
RESUME_COMMANDS_RELATIVE = Path(
    "docs/evidence/benchmark_regeneration_resume_commands_20260706.json"
)


def test_command_renderer_outputs_selected_shard_commands() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_commands")

    rows = module.render_commands(
        plan_path=ROOT / PLAN_RELATIVE,
        stages=["front_camera_50scene_public2602"],
        groups=["cache", "shards", "merge", "promote", "post"],
        shard_indexes=[2],
    )
    displays = [row["display"] for row in rows]

    assert rows[0]["command"] == "link_local_cache_from_all_usdzs"
    assert rows[0]["group"] == "cache"
    assert rows[0]["execution_boundary"] == "private_cache_preparation"
    assert rows[0]["operator_role"] == "cache_builder"
    assert rows[0]["requires_private_execution_context"] is True
    assert "--source-usdz-dir /path/to/alpasim/data/nre-artifacts/all-usdzs" in rows[0]["display"]
    assert any("HF_TOKEN=required wod2sim-build-local-cache" in display for display in displays)
    assert [row["shard_index"] for row in rows if row["group"] == "shards"] == [2, 2]
    assert any("shards/010_019" in display for display in displays)
    assert any("wod2sim-batch-summary --merge-summary" in display for display in displays)
    assert any("wod2sim-promote-batch-summary" in display for display in displays)
    assert displays[-2] == (
        "wod2sim-benchmark-status "
        "--output docs/evidence/benchmark_regeneration_status_20260706.json --json"
    )
    assert displays[-1] == "wod2sim-benchmark-audit --strict --json"


def test_command_renderer_all_prefers_shards_for_scale_stages() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_commands")

    rows = module.render_commands(plan_path=ROOT / PLAN_RELATIVE, groups=["all"])

    assert rows[0]["command"] == "cleanup_ignored_benchmark_artifacts"
    assert rows[0]["group"] == "cleanup"
    assert rows[0]["display"] == "wod2sim-benchmark-cleanup --json"
    assert rows[0]["execution_boundary"] == "public_metadata_review"
    assert rows[0]["operator_role"] == "open_repo_reviewer"
    assert rows[0]["requires_private_execution_context"] is False
    assert rows[1]["command"] == "check_readiness"
    assert any(
        row["group"] == "run" and row["scene_preset"] == "front_camera_10scene_smoke"
        for row in rows
    )
    assert any(row["group"] == "shards" for row in rows)
    assert not any(
        row["group"] == "run" and row["scene_preset"] == "front_camera_50scene_public2602"
        for row in rows
    )
    assert any(row["command"] == "merge_shard_summaries" for row in rows)
    assert rows[-1]["command"] == "verify_claim_gate"


def test_command_renderer_resumes_missing_shards_from_audit() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_commands")

    rows = module.render_commands(
        plan_path=ROOT / PLAN_RELATIVE,
        audit_path=ROOT / AUDIT_RELATIVE,
        resume_missing_shards_from_audit=True,
    )
    shard_rows = [row for row in rows if row["group"] == "shards"]

    assert [row["group"] for row in rows[-2:]] == ["post", "post"]
    assert len(shard_rows) == 30
    assert {row["scene_preset"] for row in shard_rows} == {
        "front_camera_50scene_public2602",
        "front_camera_100scene_public2602",
    }
    assert {
        row["shard_index"]
        for row in shard_rows
        if row["scene_preset"] == "front_camera_50scene_public2602"
    } == {1, 2, 3, 4, 5}
    assert {
        row["shard_index"]
        for row in shard_rows
        if row["scene_preset"] == "front_camera_100scene_public2602"
    } == {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
    assert all(row["resume_from_audit"] == (ROOT / AUDIT_RELATIVE).as_posix() for row in rows)
    assert all(row["resume_summary_errors"] == ["summary_missing"] for row in shard_rows)
    assert all(
        str(row["resume_summary_path"]).endswith("wod2sim-batch-summary.json") for row in shard_rows
    )
    assert {row["command"] for row in rows if row["group"] == "merge"} == {"merge_shard_summaries"}
    assert {row["command"] for row in rows if row["group"] == "promote"} == {
        "promote_public_summary"
    }


def test_command_renderer_resume_mode_honors_stage_group_and_shard_filters() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_commands")

    rows = module.render_commands(
        plan_path=ROOT / PLAN_RELATIVE,
        audit_path=ROOT / AUDIT_RELATIVE,
        stages=["front_camera_50scene_public2602"],
        groups=["shards"],
        shard_indexes=[2],
        resume_missing_shards_from_audit=True,
    )

    assert len(rows) == 2
    assert {row["command"] for row in rows} == {"run_batch", "write_batch_summary"}
    assert all(row["scene_preset"] == "front_camera_50scene_public2602" for row in rows)
    assert all(row["shard_index"] == 2 for row in rows)
    assert all("shards/010_019" in row["display"] for row in rows)


def test_command_renderer_main_writes_json_rows() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_commands")
    with TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "commands.json"

        with (
            output.open("w", encoding="utf-8") as handle,
            patch.object(
                sys,
                "argv",
                [
                    "wod2sim-benchmark-commands",
                    "--plan",
                    str(ROOT / PLAN_RELATIVE),
                    "--stage",
                    "workshop_scale",
                    "--group",
                    "shards",
                    "--shard-index",
                    "1",
                    "--json",
                ],
            ),
            patch("sys.stdout", handle),
        ):
            returncode = module.main()

        payload = json.loads(output.read_text(encoding="utf-8"))

    assert returncode == 0
    assert len(payload) == 2
    assert {row["command"] for row in payload} == {"run_batch", "write_batch_summary"}
    assert all(row["shard_index"] == 1 for row in payload)


def test_command_renderer_main_writes_resume_rows() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_commands")
    with TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "resume.json"

        with (
            output.open("w", encoding="utf-8") as handle,
            patch.object(
                sys,
                "argv",
                [
                    "wod2sim-benchmark-commands",
                    "--plan",
                    str(ROOT / PLAN_RELATIVE),
                    "--audit",
                    str(ROOT / AUDIT_RELATIVE),
                    "--resume-missing-shards-from-audit",
                    "--stage",
                    "front_camera_50scene_public2602",
                    "--group",
                    "shards",
                    "--shard-index",
                    "1",
                    "--json",
                ],
            ),
            patch("sys.stdout", handle),
        ):
            returncode = module.main()

        payload = json.loads(output.read_text(encoding="utf-8"))

    assert returncode == 0
    assert len(payload) == 2
    assert all(row["resume_summary_errors"] == ["summary_missing"] for row in payload)


def test_command_renderer_builds_public_command_artifact() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_commands")

    artifact = module.build_command_artifact(
        plan_path=ROOT / PLAN_RELATIVE,
        groups=["all"],
        created_at="2026-07-06",
    )

    assert artifact["schema"] == "wod2sim_benchmark_regeneration_commands_v1"
    assert artifact["created_at"] == "2026-07-06"
    assert artifact["plan_artifact"] == (ROOT / PLAN_RELATIVE).as_posix()
    assert artifact["renderer"]["no_runtime_execution"] is True
    assert artifact["row_count"] == len(artifact["commands"])
    assert artifact["group_counts"]["shards"] == 30
    assert artifact["group_counts"]["cache"] == 6
    assert artifact["group_counts"]["cleanup"] == 1
    assert artifact["execution_boundary_counts"] == {
        "claim_summary_merge": 2,
        "claim_summary_promotion": 3,
        "live_closed_loop_rollout": 32,
        "private_cache_preparation": 6,
        "public_metadata_review": 4,
    }
    assert artifact["operator_role_counts"] == {
        "cache_builder": 6,
        "claim_promoter": 5,
        "closed_loop_runner": 32,
        "open_repo_reviewer": 4,
    }
    assert artifact["private_execution_command_count"] == 43
    assert artifact["public_review_command_count"] == 4
    assert artifact["commands"][-1]["command"] == "verify_claim_gate"


def test_command_renderer_builds_resume_artifact() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_commands")

    artifact = module.build_command_artifact(
        plan_path=ROOT / PLAN_RELATIVE,
        audit_path=ROOT / AUDIT_RELATIVE,
        groups=["shards"],
        resume_missing_shards_from_audit=True,
        created_at="2026-07-06",
    )

    assert artifact["filters"]["resume_missing_shards_from_audit"] is True
    assert artifact["filters"]["audit_artifact"] == (ROOT / AUDIT_RELATIVE).as_posix()
    assert artifact["group_counts"] == {"shards": 30}
    assert artifact["execution_boundary_counts"] == {"live_closed_loop_rollout": 30}
    assert artifact["operator_role_counts"] == {"closed_loop_runner": 30}
    assert artifact["private_execution_command_count"] == 30
    assert artifact["public_review_command_count"] == 0
    assert artifact["resume_plan"]["included_groups"] == ["shards"]
    assert artifact["resume_plan"]["affected_stage_count"] == 2
    assert artifact["resume_plan"]["missing_shard_summary_count"] == 15
    assert artifact["resume_plan"]["command_group_counts"] == {"shards": 30}
    assert artifact["resume_plan"]["stages"][0]["missing_shard_indexes"] == [1, 2, 3, 4, 5]
    assert artifact["resume_plan"]["stages"][1]["missing_shard_indexes"] == [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
    ]


def test_command_renderer_output_writes_artifact_without_changing_stdout_rows() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_commands")
    with TemporaryDirectory() as tmpdir:
        stdout = Path(tmpdir) / "stdout.json"
        output = Path(tmpdir) / "artifact.json"

        with (
            stdout.open("w", encoding="utf-8") as handle,
            patch.object(
                sys,
                "argv",
                [
                    "wod2sim-benchmark-commands",
                    "--plan",
                    str(ROOT / PLAN_RELATIVE),
                    "--group",
                    "all",
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

        rows = json.loads(stdout.read_text(encoding="utf-8"))
        artifact = json.loads(output.read_text(encoding="utf-8"))

    assert returncode == 0
    assert isinstance(rows, list)
    assert artifact["created_at"] == "2026-07-06"
    assert artifact["commands"] == rows


def test_tracked_command_artifact_is_public_safe_and_complete() -> None:
    artifact = json.loads((ROOT / COMMANDS_RELATIVE).read_text(encoding="utf-8"))
    rendered = json.dumps(artifact, sort_keys=True)

    assert artifact["schema"] == "wod2sim_benchmark_regeneration_commands_v1"
    assert artifact["plan_artifact"] == PLAN_RELATIVE.as_posix()
    assert artifact["renderer"]["no_runtime_execution"] is True
    assert artifact["row_count"] == 47
    assert artifact["group_counts"] == {
        "cache": 6,
        "cleanup": 1,
        "merge": 2,
        "post": 2,
        "promote": 3,
        "readiness": 1,
        "run": 2,
        "shards": 30,
    }
    assert artifact["execution_boundary_counts"]["private_cache_preparation"] == 6
    assert artifact["execution_boundary_counts"]["public_metadata_review"] == 4
    assert artifact["execution_boundary_counts"]["live_closed_loop_rollout"] == 32
    assert artifact["operator_role_counts"]["open_repo_reviewer"] == 4
    assert artifact["operator_role_counts"]["closed_loop_runner"] == 32
    assert artifact["private_execution_command_count"] == 43
    assert artifact["public_review_command_count"] == 4
    assert artifact["commands"][0]["display"] == "wod2sim-benchmark-cleanup --json"
    assert all("execution_boundary" in row for row in artifact["commands"])
    assert all("operator_role" in row for row in artifact["commands"])
    assert all("requires_private_execution_context" in row for row in artifact["commands"])
    assert "wod2sim-benchmark-audit --strict --json" in rendered
    assert "/home/" not in rendered
    assert "HF_TOKEN=required" in rendered


def test_tracked_resume_command_artifact_targets_missing_scale_shards() -> None:
    artifact = json.loads((ROOT / RESUME_COMMANDS_RELATIVE).read_text(encoding="utf-8"))
    rendered = json.dumps(artifact, sort_keys=True)
    rows = artifact["commands"]
    shard_rows = [row for row in rows if row["group"] == "shards"]

    assert artifact["schema"] == "wod2sim_benchmark_regeneration_commands_v1"
    assert artifact["plan_artifact"] == PLAN_RELATIVE.as_posix()
    assert artifact["renderer"]["no_runtime_execution"] is True
    assert artifact["filters"] == {
        "audit_artifact": AUDIT_RELATIVE.as_posix(),
        "groups": ["all"],
        "resume_missing_shards_from_audit": True,
        "shard_indexes": [],
        "stages": [],
    }
    assert artifact["row_count"] == 36
    assert artifact["group_counts"] == {
        "merge": 2,
        "post": 2,
        "promote": 2,
        "shards": 30,
    }
    assert artifact["execution_boundary_counts"] == {
        "claim_summary_merge": 2,
        "claim_summary_promotion": 2,
        "live_closed_loop_rollout": 30,
        "public_metadata_review": 2,
    }
    assert artifact["operator_role_counts"] == {
        "claim_promoter": 4,
        "closed_loop_runner": 30,
        "open_repo_reviewer": 2,
    }
    assert artifact["private_execution_command_count"] == 34
    assert artifact["public_review_command_count"] == 2
    assert artifact["resume_plan"] == {
        "affected_stage_count": 2,
        "audit_artifact": AUDIT_RELATIVE.as_posix(),
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
        "selected_shard_indexes": [],
        "selected_stage_filters": [],
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
                "missing_summary_errors_by_path": {
                    "runs/benchmark_spotlight_reflex_50scene_public2602_fresh/shards/000_009/wod2sim-batch-summary.json": [
                        "summary_missing"
                    ],
                    "runs/benchmark_spotlight_reflex_50scene_public2602_fresh/shards/010_019/wod2sim-batch-summary.json": [
                        "summary_missing"
                    ],
                    "runs/benchmark_spotlight_reflex_50scene_public2602_fresh/shards/020_029/wod2sim-batch-summary.json": [
                        "summary_missing"
                    ],
                    "runs/benchmark_spotlight_reflex_50scene_public2602_fresh/shards/030_039/wod2sim-batch-summary.json": [
                        "summary_missing"
                    ],
                    "runs/benchmark_spotlight_reflex_50scene_public2602_fresh/shards/040_049/wod2sim-batch-summary.json": [
                        "summary_missing"
                    ],
                },
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
                "missing_summary_errors_by_path": {
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/000_009/wod2sim-batch-summary.json": [
                        "summary_missing"
                    ],
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/010_019/wod2sim-batch-summary.json": [
                        "summary_missing"
                    ],
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/020_029/wod2sim-batch-summary.json": [
                        "summary_missing"
                    ],
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/030_039/wod2sim-batch-summary.json": [
                        "summary_missing"
                    ],
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/040_049/wod2sim-batch-summary.json": [
                        "summary_missing"
                    ],
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/050_059/wod2sim-batch-summary.json": [
                        "summary_missing"
                    ],
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/060_069/wod2sim-batch-summary.json": [
                        "summary_missing"
                    ],
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/070_079/wod2sim-batch-summary.json": [
                        "summary_missing"
                    ],
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/080_089/wod2sim-batch-summary.json": [
                        "summary_missing"
                    ],
                    "runs/benchmark_spotlight_reflex_100scene_public2602_fresh/shards/090_099/wod2sim-batch-summary.json": [
                        "summary_missing"
                    ],
                },
                "post_review_commands_included": True,
                "promote_command_included": True,
                "public_summary_target": "docs/evidence/closed_loop_spotlight_reflex_100scene_batch.json",
                "scene_count": 100,
                "scene_preset": "front_camera_100scene_public2602",
                "stage": "stronger_benchmark",
            },
        ],
    }
    assert len(shard_rows) == 30
    assert all(row["resume_summary_errors"] == ["summary_missing"] for row in shard_rows)
    assert {row["scene_preset"] for row in shard_rows} == {
        "front_camera_50scene_public2602",
        "front_camera_100scene_public2602",
    }
    assert "/home/" not in rendered
    assert "HF_TOKEN=required" not in rendered
