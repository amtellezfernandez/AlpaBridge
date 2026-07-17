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
        self.assertIn("T", summary["created_at"])
        self.assertTrue(summary["clean_closed_loop_batch"])
        self.assertIn("strict public audit accepts", summary["claim_boundary"])
        self.assertNotIn("not a claim-valid stage summary", summary["claim_boundary"])
        self.assertEqual("wod2sim_closed_loop_batch_summary_v1", summary["schema"])
        self.assertEqual(2, summary["aggregate"]["completed_scene_count"])
        self.assertEqual(0, summary["aggregate"]["audit_invalid_scene_count"])
        self.assertEqual(0, summary["aggregate"]["route_contract_failure_scene_count"])
        self.assertEqual({"alpasim_waypoints": 398}, summary["aggregate"]["route_source_counts"])
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
        self.assertIn("not a claim-valid stage summary", payload["claim_boundary"])
        self.assertIn("1/2 planned scene(s) reached completed state", payload["claim_boundary"])
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

    def test_launch_metadata_drift_prevents_clean_claim_summary(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.batch_summary")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_batch(root)
            _write_run(root, "001_scene-a", collision_any=0.0, wrong_lane=0.0, progress=0.7)
            _write_run(root, "002_scene-b", collision_any=0.0, wrong_lane=0.0, progress=0.8)
            _write_launch_metadata(root, "001_scene-a", scene_preset="fresh_3scene")
            _write_launch_metadata(root, "002_scene-b", scene_preset="front_camera_10scene_smoke")

            summary = module.build_summary(batch_dir=root)

        self.assertTrue(summary["valid"])
        self.assertFalse(summary["clean_closed_loop_batch"])
        self.assertEqual(1, summary["provenance"]["critical_error_count"])
        self.assertIn(
            "run_001:scene-a:scene_preset_mismatch:fresh_3scene",
            summary["provenance"]["critical_errors"],
        )

    def test_route_contract_failure_prevents_clean_claim_summary(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.batch_summary")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_batch(root, route_contract_ok=False)
            _write_run(root, "001_scene-a", collision_any=0.0, wrong_lane=0.0, progress=0.7)
            _write_run(root, "002_scene-b", collision_any=0.0, wrong_lane=0.0, progress=0.8)

            summary = module.build_summary(batch_dir=root)

        self.assertTrue(summary["valid"])
        self.assertFalse(summary["clean_closed_loop_batch"])
        self.assertIn("not a claim-valid stage summary", summary["claim_boundary"])
        self.assertIn("2/2 planned scene(s) reached completed state", summary["claim_boundary"])
        self.assertNotIn("completed cleanly", summary["claim_boundary"])
        self.assertEqual(1, summary["aggregate"]["audit_invalid_scene_count"])
        self.assertEqual(1, summary["aggregate"]["route_contract_failure_scene_count"])
        self.assertEqual(
            {"alpasim_waypoints": 199, "command_proxy": 199},
            summary["aggregate"]["route_source_counts"],
        )

    def test_legacy_smoke_launch_label_is_a_warning_when_scene_ids_match_manifest(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.batch_summary")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_batch(
                root,
                scene_ids=(
                    "clipgt-a309e228-26e1-423e-a44c-cb00aa7378cb",
                    "clipgt-804afc4a-fd1e-4f58-bd39-a4c486a916e5",
                ),
            )
            _write_run(
                root,
                "001_clipgt-a309e228-26e1-423e-a44c-cb00aa7378cb",
                collision_any=0.0,
                wrong_lane=0.0,
                progress=0.7,
            )
            _write_run(
                root,
                "002_clipgt-804afc4a-fd1e-4f58-bd39-a4c486a916e5",
                collision_any=0.0,
                wrong_lane=0.0,
                progress=0.8,
            )
            _write_launch_metadata(
                root,
                "001_clipgt-a309e228-26e1-423e-a44c-cb00aa7378cb",
                scene_preset="fresh_3scene",
            )
            _write_launch_metadata(
                root,
                "002_clipgt-804afc4a-fd1e-4f58-bd39-a4c486a916e5",
                scene_preset="fresh_3scene",
            )

            summary = module.build_summary(batch_dir=root)

        self.assertTrue(summary["clean_closed_loop_batch"])
        self.assertEqual(0, summary["provenance"]["critical_error_count"])
        self.assertEqual(2, summary["provenance"]["warning_count"])
        self.assertIn(
            (
                "run_001:clipgt-a309e228-26e1-423e-a44c-cb00aa7378cb:"
                "legacy_scene_preset_label:fresh_3scene"
            ),
            summary["provenance"]["warnings"],
        )

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
                created_at="2026-07-06",
            )

        self.assertTrue(merged["valid"])
        self.assertEqual("2026-07-06", merged["created_at"])
        self.assertTrue(merged["clean_closed_loop_batch"])
        self.assertIn("strict public audit accepts", merged["claim_boundary"])
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
                    "--created-at",
                    "2026-07-06",
                    "--strict",
                    "--json",
                ],
            ):
                returncode = module.main()

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(1, returncode)
        self.assertEqual("2026-07-06", payload["created_at"])
        self.assertFalse(payload["clean_closed_loop_batch"])
        self.assertIn("not a claim-valid stage summary", payload["claim_boundary"])
        self.assertEqual(
            ["scene_count_mismatch:planned=4,observed=2"],
            payload["merge"]["errors"],
        )


def _write_batch(
    root: Path,
    *,
    completed: bool = True,
    route_contract_ok: bool = True,
    scene_ids: tuple[str, str] = ("scene-a", "scene-b"),
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    scene_a, scene_b = scene_ids
    _write_json(
        root / "batch-manifest.json",
        {
            "schema": "alpasim_scene_batch_v1",
            "mode": "both",
            "model": "token_dagger_bc",
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
                "run_audit_valid": True,
                "frame_count": 199,
                "sensor_pipeline_ok": True,
                "sensor_failure_count": 0,
                "route_contract_ok": True,
                "route_contract_failure_count": 0,
                "route_source_counts": {"alpasim_waypoints": 199},
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
                "run_audit_valid": completed and route_contract_ok,
                "frame_count": 199 if completed else 0,
                "sensor_pipeline_ok": True if completed else None,
                "sensor_failure_count": 0,
                "route_contract_ok": route_contract_ok if completed else None,
                "route_contract_failure_count": 0 if route_contract_ok else 1,
                "route_source_counts": {"alpasim_waypoints" if route_contract_ok else "command_proxy": 199}
                if completed
                else {},
            },
        },
    ]
    _write_json(
        root / "batch-status.json",
        {
            "schema": "alpasim_scene_batch_summary_v1",
            "batch_dir": str(root),
            "mode": "both",
            "model": "token_dagger_bc",
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


def _write_launch_metadata(root: Path, name: str, *, scene_preset: str) -> None:
    scene_id = name.split("_", 1)[1]
    _write_json(
        root / name / "launch-metadata.json",
        {
            "model": "token_dagger_bc",
            "scene_preset": scene_preset,
            "scene_ids": [scene_id],
            "wizard_args": [],
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
