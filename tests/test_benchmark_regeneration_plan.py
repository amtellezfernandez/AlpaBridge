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


class BenchmarkRegenerationPlanTests(unittest.TestCase):
    def test_build_plan_covers_pilot_and_scale_presets(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_plan")

        plan = module.build_plan(created_at="2026-07-06")
        stages = {stage["scene_preset"]: stage for stage in plan["stages"]}

        self.assertEqual("wod2sim_benchmark_regeneration_plan_v1", plan["schema"])
        self.assertEqual(STATUS_RELATIVE.as_posix(), plan["status_artifact"])
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
        self.assertIn(
            "scenes.local_usdz_dir=/path/to/alpasim/data/nre-artifacts/local-2602-usdzs-50",
            scale_stage["commands"]["run_batch"]["argv"],
        )

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

    def test_tracked_plan_links_current_public_status_and_docs(self) -> None:
        plan = _read_json(ROOT / PLAN_RELATIVE)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        evaluation_protocol = (ROOT / "docs/evaluation_protocol.md").read_text(encoding="utf-8")

        self.assertEqual("wod2sim_benchmark_regeneration_plan_v1", plan["schema"])
        self.assertEqual(STATUS_RELATIVE.as_posix(), plan["status_artifact"])
        self.assertIn(PLAN_RELATIVE.as_posix(), readme)
        self.assertIn(PLAN_RELATIVE.name, evaluation_protocol)

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
