from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class BenchmarkReadinessTests(unittest.TestCase):
    def test_default_gate_rejects_partial_single_model_evidence(self) -> None:
        module = importlib.import_module("alpabridge.cli.commands.benchmark_readiness")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            summary_path = root / "token.json"
            _write_summary(summary_path, model="token_dagger_bc", scene_ids=("scene-a", "scene-b"))

            report = module.build_readiness_report(summary_paths=[summary_path], created_at="2026-07-17")

        self.assertFalse(report["ready_for_public_benchmark_claim"])
        self.assertEqual("2026-07-17", report["created_at"])
        self.assertIn("insufficient_unique_scenes:2/15", report["failures"])
        self.assertIn(
            "missing_required_baseline_families:replay_or_constant_velocity,route_following",
            report["failures"],
        )
        self.assertEqual({"token_dagger_bc": 2}, report["evidence"]["models"])
        self.assertEqual({"token_dagger_bc": 2}, report["evidence"]["baseline_families"])

    def test_gate_accepts_clean_minimum_matrix(self) -> None:
        module = importlib.import_module("alpabridge.cli.commands.benchmark_readiness")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = [
                root / "replay.json",
                root / "route.json",
                root / "token.json",
            ]
            _write_summary(
                paths[0],
                model="constant_velocity",
                scene_ids=tuple(f"scene-{index:02d}" for index in range(1, 6)),
            )
            _write_summary(
                paths[1],
                model="route_following",
                scene_ids=tuple(f"scene-{index:02d}" for index in range(6, 11)),
            )
            _write_summary(
                paths[2],
                model="token_dagger_bc",
                scene_ids=tuple(f"scene-{index:02d}" for index in range(11, 16)),
            )

            report = module.build_readiness_report(summary_paths=paths, created_at="2026-07-17")

        self.assertTrue(report["ready_for_public_benchmark_claim"])
        self.assertEqual([], report["failures"])
        self.assertEqual(15, report["evidence"]["unique_scene_count"])
        self.assertEqual(
            {
                "constant_velocity": 5,
                "route_following": 5,
                "token_dagger_bc": 5,
            },
            report["evidence"]["models"],
        )
        self.assertEqual(
            {
                "replay_or_constant_velocity": 5,
                "route_following": 5,
                "token_dagger_bc": 5,
            },
            report["evidence"]["baseline_families"],
        )

    def test_gate_rejects_unclean_or_command_proxy_summaries(self) -> None:
        module = importlib.import_module("alpabridge.cli.commands.benchmark_readiness")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            summary_path = root / "summary.json"
            _write_summary(
                summary_path,
                model="token_dagger_bc",
                scene_ids=tuple(f"scene-{index:02d}" for index in range(1, 16)),
                clean=False,
                route_source_counts={"alpasim_waypoints": 140, "command_proxy": 10},
            )

            report = module.build_readiness_report(
                summary_paths=[summary_path],
                required_families=("token_dagger_bc",),
            )

        self.assertFalse(report["ready_for_public_benchmark_claim"])
        self.assertIn("summary_1:not_clean_closed_loop_batch", report["failures"])
        self.assertIn("summary_1:route_source_not_claim_valid:command_proxy", report["failures"])

    def test_gate_requires_metric_coverage_for_every_scene(self) -> None:
        module = importlib.import_module("alpabridge.cli.commands.benchmark_readiness")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            summary_path = root / "summary.json"
            _write_summary(summary_path, model="token_dagger_bc", scene_ids=("scene-a", "scene-b"))
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            payload["metrics"]["progress"]["count"] = 1
            summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            report = module.build_readiness_report(
                summary_paths=[summary_path],
                min_scenes=2,
                required_families=("token_dagger_bc",),
            )

        self.assertFalse(report["ready_for_public_benchmark_claim"])
        self.assertIn("insufficient_metric_coverage:progress:1/2", report["failures"])

    def test_main_returns_nonzero_for_not_ready_after_writing_output(self) -> None:
        module = importlib.import_module("alpabridge.cli.commands.benchmark_readiness")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            summary_path = root / "summary.json"
            output = root / "readiness.json"
            _write_summary(summary_path, model="token_dagger_bc", scene_ids=("scene-a",))

            with patch.object(
                sys,
                "argv",
                [
                    "alpabridge-benchmark-readiness",
                    "--batch-summary",
                    str(summary_path),
                    "--output",
                    str(output),
                    "--json",
                ],
            ):
                returncode = module.main()

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(1, returncode)
        self.assertFalse(payload["ready_for_public_benchmark_claim"])

    def test_required_model_keyword_is_backward_compatible_family_alias(self) -> None:
        module = importlib.import_module("alpabridge.cli.commands.benchmark_readiness")
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.json"
            _write_summary(summary_path, model="constant_velocity", scene_ids=("scene-a", "scene-b"))

            report = module.build_readiness_report(
                summary_paths=[summary_path],
                min_scenes=2,
                required_models=("replay_or_constant_velocity",),
            )

        self.assertTrue(report["ready_for_public_benchmark_claim"])


def _write_summary(
    path: Path,
    *,
    model: str,
    scene_ids: tuple[str, ...],
    clean: bool = True,
    route_source_counts: dict[str, int] | None = None,
) -> None:
    metric_count = len(scene_ids)
    metrics = {
        name: {"count": metric_count, "mean": 0.0, "min": 0.0, "max": 0.0}
        for name in (
            "collision_any",
            "collision_at_fault",
            "offroad",
            "wrong_lane",
            "progress",
            "plan_deviation",
            "duration_frac_20s",
        )
    }
    payload = {
        "schema": "alpabridge_closed_loop_batch_summary_v1",
        "valid": True,
        "clean_closed_loop_batch": clean,
        "run_config": {
            "model": model,
            "scene_preset": "front_camera_10scene_smoke",
        },
        "aggregate": {
            "planned_scene_count": len(scene_ids),
            "completed_scene_count": len(scene_ids) if clean else len(scene_ids) - 1,
            "total_audited_frames": len(scene_ids) * 10,
            "route_source_counts": route_source_counts or {"alpasim_waypoints": len(scene_ids) * 10},
        },
        "metrics": metrics,
        "runs": [{"scene_id": scene_id} for scene_id in scene_ids],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
