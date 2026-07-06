from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLAN_RELATIVE = Path("docs/evidence/benchmark_regeneration_plan_20260706.json")
STATUS_RELATIVE = Path("docs/evidence/benchmark_regeneration_status_20260706.json")
READINESS_RELATIVE = Path("docs/evidence/benchmark_regeneration_readiness_20260706.json")


class BenchmarkRegenerationPlanTests(unittest.TestCase):
    def test_build_plan_covers_pilot_and_scale_presets(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_plan")

        plan = module.build_plan(created_at="2026-07-06")
        stages = {stage["scene_preset"]: stage for stage in plan["stages"]}

        self.assertEqual("wod2sim_benchmark_regeneration_plan_v1", plan["schema"])
        self.assertEqual(STATUS_RELATIVE.as_posix(), plan["status_artifact"])
        self.assertEqual(READINESS_RELATIVE.as_posix(), plan["readiness_artifact"])
        readiness_command = plan["commands"]["check_readiness"]["argv"]
        self.assertEqual("wod2sim-benchmark-readiness", readiness_command[0])
        self.assertIn(READINESS_RELATIVE.as_posix(), readiness_command)
        self.assertIn("--stable-public-snapshot", readiness_command)
        self.assertEqual(
            {
                "front_camera_10scene_smoke",
                "front_camera_50scene_public2602",
                "front_camera_100scene_public2602",
            },
            set(stages),
        )
        self.assertEqual(10, stages["front_camera_10scene_smoke"]["scene_count"])
        self.assertEqual(50, stages["front_camera_50scene_public2602"]["scene_count"])
        self.assertEqual(100, stages["front_camera_100scene_public2602"]["scene_count"])
        self.assertFalse(stages["front_camera_10scene_smoke"]["requires_local_usdz_cache"])
        self.assertIsNone(stages["front_camera_10scene_smoke"]["commands"]["build_local_cache"])

        scale_stage = stages["front_camera_50scene_public2602"]
        self.assertTrue(scale_stage["requires_local_usdz_cache"])
        self.assertEqual(
            {"HF_TOKEN": "required"},
            scale_stage["commands"]["build_local_cache"]["env"],
        )
        validate_cache_command = scale_stage["commands"]["validate_local_cache"]["argv"]
        self.assertEqual("wod2sim-build-local-cache", validate_cache_command[0])
        self.assertIn("--validate-only", validate_cache_command)
        self.assertIn("/path/to/alpasim/data/nre-artifacts/local-2602-usdzs-50", validate_cache_command)
        self.assertIn(
            "scenes.local_usdz_dir=/path/to/alpasim/data/nre-artifacts/local-2602-usdzs-50",
            scale_stage["commands"]["run_batch"]["argv"],
        )
        merge_command = scale_stage["commands"]["merge_shard_summaries"]["argv"]
        self.assertEqual("wod2sim-batch-summary", merge_command[0])
        self.assertEqual(5, merge_command.count("--merge-summary"))
        self.assertIn("--expected-scene-count", merge_command)
        self.assertEqual("50", merge_command[merge_command.index("--expected-scene-count") + 1])
        self.assertIn(
            "runs/benchmark_spotlight_reflex_50scene/wod2sim-batch-summary.json",
            merge_command,
        )
        promote_command = scale_stage["commands"]["promote_public_summary"]["argv"]
        self.assertEqual("wod2sim-promote-batch-summary", promote_command[0])
        self.assertIn("runs/benchmark_spotlight_reflex_50scene/wod2sim-batch-summary.json", promote_command)
        self.assertIn("docs/evidence/closed_loop_spotlight_reflex_50scene_batch.json", promote_command)
        self.assertIn("--overwrite", promote_command)
        self.assertEqual(5, len(scale_stage["shards"]))
        self.assertEqual(0, scale_stage["shards"][0]["scene_offset"])
        self.assertEqual(10, scale_stage["shards"][0]["scene_limit"])
        self.assertIn("--scene-offset", scale_stage["shards"][0]["commands"]["run_batch"]["argv"])
        self.assertIn("--scene-limit", scale_stage["shards"][0]["commands"]["run_batch"]["argv"])
        self.assertEqual(
            "runs/benchmark_spotlight_reflex_50scene/shards/040_049",
            scale_stage["shards"][-1]["run_dir"],
        )
        self.assertEqual(10, len(stages["front_camera_100scene_public2602"]["shards"]))

    def test_main_writes_plan_json(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_plan")
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "plan.json"

            with patch.object(
                sys,
                "argv",
                [
                    "wod2sim-benchmark-plan",
                    "--created-at",
                    "2026-07-06",
                    "--output",
                    str(output),
                    "--json",
                ],
            ):
                returncode = module.main()

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(0, returncode)
        self.assertEqual("2026-07-06", payload["created_at"])
        self.assertEqual(3, len(payload["stages"]))

    def test_shards_can_be_omitted_for_compact_plan_output(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_plan")

        plan = module.build_plan(created_at="2026-07-06", shard_size=0)

        for stage in plan["stages"]:
            self.assertEqual([], stage["shards"])
            self.assertIsNone(stage["shard_note"])
            self.assertIsNone(stage["commands"]["merge_shard_summaries"])
            if stage["requires_local_usdz_cache"]:
                self.assertIsNotNone(stage["commands"]["validate_local_cache"])
            else:
                self.assertIsNone(stage["commands"]["validate_local_cache"])
            self.assertIsNotNone(stage["commands"]["promote_public_summary"])

    def test_tracked_plan_links_current_public_status_and_docs(self) -> None:
        plan = _read_json(ROOT / PLAN_RELATIVE)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        evaluation_protocol = (ROOT / "docs/evaluation_protocol.md").read_text(encoding="utf-8")

        self.assertEqual("wod2sim_benchmark_regeneration_plan_v1", plan["schema"])
        self.assertEqual(STATUS_RELATIVE.as_posix(), plan["status_artifact"])
        self.assertEqual(READINESS_RELATIVE.as_posix(), plan["readiness_artifact"])
        self.assertIn(PLAN_RELATIVE.as_posix(), readme)
        self.assertIn(READINESS_RELATIVE.as_posix(), readme)
        self.assertIn(PLAN_RELATIVE.name, evaluation_protocol)
        self.assertIn(READINESS_RELATIVE.name, evaluation_protocol)

    def test_tracked_plan_stage_counts_match_packaged_presets(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_plan")
        plan = _read_json(ROOT / PLAN_RELATIVE)

        for stage in plan["stages"]:
            self.assertEqual(
                len(module._scene_ids_for(stage["scene_preset"])),
                stage["scene_count"],
            )


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
