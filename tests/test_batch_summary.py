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

    def test_merge_summaries_combines_clean_shards_into_claim_summary(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.batch_summary")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shard_a = root / "shard-a"
            shard_b = root / "shard-b"
            _write_batch(shard_a, scene_ids=("scene-a", "scene-b"))
            _write_run(shard_a, "001_scene-a", collision_any=1.0, wrong_lane=1.0, progress=0.35)
            _write_run(shard_a, "002_scene-b", collision_any=0.0, wrong_lane=0.0, progress=0.92)
            _write_batch(shard_b, scene_ids=("scene-c", "scene-d"))
            _write_run(shard_b, "001_scene-c", collision_any=0.0, wrong_lane=0.0, progress=0.75)
            _write_run(shard_b, "002_scene-d", collision_any=1.0, wrong_lane=0.0, progress=0.45)
            summary_a = module.build_summary(batch_dir=shard_a)
            summary_b = module.build_summary(batch_dir=shard_b)
            summary_a_path = root / "summary-a.json"
            summary_b_path = root / "summary-b.json"
            _write_json(summary_a_path, summary_a)
            _write_json(summary_b_path, summary_b)

            merged = module.merge_summaries(
                summary_paths=[summary_a_path, summary_b_path],
                expected_scene_count=4,
            )

        self.assertTrue(merged["valid"])
        self.assertTrue(merged["clean_closed_loop_batch"])
        self.assertEqual("merged_batch_summaries", merged["source"]["summary_kind"])
        self.assertEqual(4, merged["aggregate"]["planned_scene_count"])
        self.assertEqual(4, merged["aggregate"]["completed_scene_count"])
        self.assertEqual(796, merged["aggregate"]["total_audited_frames"])
        self.assertEqual(0.5, merged["metrics"]["collision_any"]["mean"])
        self.assertEqual(2, merged["failure_taxonomy"]["collision_scene_count"])
        self.assertEqual(2, merged["failure_taxonomy"]["low_progress_scene_count"])
        self.assertEqual([], merged["merge"]["errors"])

    def test_merge_main_fails_strict_when_expected_scene_count_is_missing(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.batch_summary")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shard = root / "shard"
            output = root / "merged.json"
            _write_batch(shard, scene_ids=("scene-a", "scene-b"))
            _write_run(shard, "001_scene-a", collision_any=0.0, wrong_lane=0.0, progress=0.75)
            _write_run(shard, "002_scene-b", collision_any=0.0, wrong_lane=0.0, progress=0.8)
            summary_path = root / "summary.json"
            _write_json(summary_path, module.build_summary(batch_dir=shard))

            with patch.object(
                sys,
                "argv",
                [
                    "wod2sim-batch-summary",
                    "--merge-summary",
                    str(summary_path),
                    "--expected-scene-count",
                    "4",
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
        self.assertEqual(
            ["scene_count_mismatch:planned=4,observed=2"],
            payload["merge"]["errors"],
        )


def _write_batch(
    root: Path,
    *,
    completed: bool = True,
    scene_ids: tuple[str, str] = ("scene-a", "scene-b"),
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    scene_a, scene_b = scene_ids
    _write_json(
        root / "batch-manifest.json",
        {
            "schema": "alpasim_scene_batch_v1",
            "mode": "both",
            "model": "spotlight_reflex",
            "scene_preset": "front_camera_10scene_smoke",
            "scene_ids": [scene_a, scene_b],
            "topology": "1gpu",
            "timeout": 900,
            "max_retries": 1,
        },
    )
    runs = [
        {
            "index": 1,
            "scene_id": scene_a,
            "run_dir": str(root / f"001_{scene_a}"),
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
            "scene_id": scene_b,
            "run_dir": str(root / f"002_{scene_b}"),
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
