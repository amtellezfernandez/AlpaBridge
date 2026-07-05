from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class BatchSummaryTests(unittest.TestCase):
    def test_build_summary_extracts_metrics_and_failure_taxonomy(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.batch_summary")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_batch(root)
            _write_run(root, "001_scene-a", collision_any=1.0, wrong_lane=1.0, progress=0.35)
            _write_run(root, "002_scene-b", collision_any=0.0, wrong_lane=0.0, progress=0.92)

            summary = module.build_summary(batch_dir=root)

        self.assertTrue(summary["valid"])
        self.assertTrue(summary["clean_closed_loop_batch"])
        self.assertEqual("wod2sim_closed_loop_batch_summary_v1", summary["schema"])
        self.assertEqual(2, summary["aggregate"]["completed_scene_count"])
        self.assertEqual(398, summary["aggregate"]["total_audited_frames"])
        self.assertEqual(0.5, summary["metrics"]["collision_any"]["mean"])
        self.assertEqual("scene_rate", summary["metrics"]["collision_any"]["interpretation"])
        self.assertEqual(1, summary["failure_taxonomy"]["collision_scene_count"])
        self.assertEqual(1, summary["failure_taxonomy"]["wrong_lane_scene_count"])
        self.assertEqual(1, summary["failure_taxonomy"]["low_progress_scene_count"])
        self.assertFalse(summary["artifact_policy"]["raw_rollout_videos_included"])
        self.assertTrue(summary["runs"][0]["artifacts"]["rollout_videos"][0]["gated_scene_media"])

    def test_strict_main_fails_for_incomplete_batch(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.batch_summary")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_batch(root, completed=False)
            output = root / "summary.json"

            with patch.object(
                sys,
                "argv",
                [
                    "wod2sim-batch-summary",
                    "--batch-dir",
                    str(root),
                    "--output",
                    str(output),
                    "--strict",
                    "--json",
                ],
            ):
                returncode = module.main()

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(1, returncode)
        self.assertFalse(payload["clean_closed_loop_batch"])
        self.assertEqual(1, payload["aggregate"]["failed_scene_count"])

    def test_manifest_scene_ids_provide_planned_count_fallback(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.batch_summary")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_batch(root)
            status_path = root / "batch-status.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            del status["scene_count"]
            _write_json(status_path, status)
            _write_run(root, "001_scene-a", collision_any=0.0, wrong_lane=0.0, progress=0.7)
            _write_run(root, "002_scene-b", collision_any=0.0, wrong_lane=0.0, progress=0.8)

            summary = module.build_summary(batch_dir=root)

        self.assertEqual(2, summary["aggregate"]["planned_scene_count"])
        self.assertTrue(summary["clean_closed_loop_batch"])


def _write_batch(root: Path, *, completed: bool = True) -> None:
    _write_json(
        root / "batch-manifest.json",
        {
            "schema": "alpasim_scene_batch_v1",
            "mode": "both",
            "model": "spotlight_reflex",
            "scene_preset": "front_camera_10scene_smoke",
            "scene_ids": ["scene-a", "scene-b"],
            "topology": "1gpu",
            "timeout": 900,
            "max_retries": 1,
        },
    )
    runs = [
        {
            "index": 1,
            "scene_id": "scene-a",
            "run_dir": str(root / "001_scene-a"),
            "status": "completed",
            "result": "completed",
            "attempts": 1,
            "returncode": 0,
            "diagnostics": {
                "state": "completed",
                "aggregate_status": "completed",
                "frame_count": 199,
                "sensor_pipeline_ok": True,
                "sensor_failure_count": 0,
            },
        },
        {
            "index": 2,
            "scene_id": "scene-b",
            "run_dir": str(root / "002_scene-b"),
            "status": "completed" if completed else "partial",
            "result": "completed" if completed else "failed",
            "attempts": 1,
            "returncode": 0 if completed else 1,
            "diagnostics": {
                "state": "completed" if completed else "failed",
                "aggregate_status": "completed" if completed else None,
                "frame_count": 199 if completed else 0,
                "sensor_pipeline_ok": True if completed else None,
                "sensor_failure_count": 0,
            },
        },
    ]
    _write_json(
        root / "batch-status.json",
        {
            "schema": "alpasim_scene_batch_summary_v1",
            "batch_dir": str(root),
            "mode": "both",
            "model": "spotlight_reflex",
            "scene_count": 2,
            "runs": runs,
        },
    )


def _write_run(
    root: Path,
    name: str,
    *,
    collision_any: float,
    wrong_lane: float,
    progress: float,
) -> None:
    run = root / name
    aggregate = run / "aggregate"
    rollout = run / "rollouts" / "scene" / "rollout"
    aggregate.mkdir(parents=True, exist_ok=True)
    rollout.mkdir(parents=True, exist_ok=True)
    (aggregate / "metrics_results.txt").write_text(
        "\n".join(
            [
                "│ Metric Name                         │ Metric Value │ Time Aggregation │",
                f"│ collision_any                       │     {collision_any:.2f}     │       max        │",
                f"│ wrong_lane                          │     {wrong_lane:.2f}     │       max        │",
                f"│ progress                            │     {progress:.2f}     │       last       │",
                "│ plan_deviation                      │     8.00     │       mean       │",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (aggregate / "metrics_results.png").write_bytes(b"png\n")
    (rollout / "camera_front.mp4").write_bytes(b"mp4\n")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
