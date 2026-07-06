from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLAN_RELATIVE = Path("docs/evidence/benchmark_regeneration_plan_20260706.json")
COMMANDS_RELATIVE = Path("docs/evidence/benchmark_regeneration_commands_20260706.json")


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

    assert rows[0]["command"] == "check_readiness"
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
    assert artifact["commands"][-1]["command"] == "verify_claim_gate"


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
    assert artifact["row_count"] == 46
    assert artifact["group_counts"] == {
        "cache": 6,
        "merge": 2,
        "post": 2,
        "promote": 3,
        "readiness": 1,
        "run": 2,
        "shards": 30,
    }
    assert "wod2sim-benchmark-audit --strict --json" in rendered
    assert "/home/" not in rendered
    assert "HF_TOKEN=required" in rendered
