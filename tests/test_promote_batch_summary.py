from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class PromoteBatchSummaryTests(unittest.TestCase):
    def test_promote_summary_validates_and_copies_public_safe_summary(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.promote_batch_summary")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "wod2sim-batch-summary.json"
            output = root / "docs" / "evidence" / "closed_loop_spotlight_reflex_2scene_batch.json"
            _write_json(source, _summary(scene_count=2))

            report = module.promote_summary(
                summary_path=source,
                output_path=output,
                expected_scene_count=2,
                model="spotlight_reflex",
                scene_preset="front_camera_10scene_smoke",
            )

            self.assertTrue(report["promoted"])
            self.assertEqual(_summary(scene_count=2), json.loads(output.read_text(encoding="utf-8")))

    def test_promote_summary_requires_overwrite_for_existing_output(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.promote_batch_summary")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "wod2sim-batch-summary.json"
            output = root / "public.json"
            _write_json(source, _summary(scene_count=2))
            output.write_text("{}\n", encoding="utf-8")

            report = module.promote_summary(
                summary_path=source,
                output_path=output,
                expected_scene_count=2,
                model="spotlight_reflex",
                scene_preset="front_camera_10scene_smoke",
            )

        self.assertFalse(report["promoted"])
        self.assertTrue(any(error.startswith("output_exists:") for error in report["errors"]))

    def test_main_fails_for_mismatched_scene_preset(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.promote_batch_summary")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "wod2sim-batch-summary.json"
            output = root / "public.json"
            _write_json(source, _summary(scene_count=2))

            with patch.object(
                sys,
                "argv",
                [
                    "wod2sim-promote-batch-summary",
                    "--summary",
                    str(source),
                    "--output",
                    str(output),
                    "--expected-scene-count",
                    "2",
                    "--model",
                    "spotlight_reflex",
                    "--scene-preset",
                    "front_camera_50scene_public2602",
                    "--json",
                ],
            ):
                returncode = module.main()

        self.assertEqual(1, returncode)
        self.assertFalse(output.exists())


def _summary(*, scene_count: int) -> dict[str, object]:
    return {
        "schema": "wod2sim_closed_loop_batch_summary_v1",
        "valid": True,
        "clean_closed_loop_batch": True,
        "run_config": {
            "model": "spotlight_reflex",
            "scene_preset": "front_camera_10scene_smoke",
        },
        "aggregate": {
            "planned_scene_count": scene_count,
            "completed_scene_count": scene_count,
            "failed_scene_count": 0,
            "sensor_failure_scene_count": 0,
        },
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
