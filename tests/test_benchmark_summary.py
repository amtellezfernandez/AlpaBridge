from __future__ import annotations

import hashlib
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class BenchmarkSummaryTests(unittest.TestCase):
    def test_build_summary_aggregates_executed_and_plan_runs(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_summary")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            executed = root / "executed" / "evidence"
            planned = root / "planned" / "evidence"
            _write_valid_evidence(executed)
            _write_plan_evidence(planned)

            summary = module.build_summary(evidence_dirs=[executed, planned])

        self.assertTrue(summary["valid"])
        self.assertFalse(summary["valid_claim_evidence"])
        self.assertEqual(2, summary["run_count"])
        self.assertEqual(1, summary["valid_claim_evidence_count"])
        self.assertEqual({"planned": 1, "completed": 1}, summary["aggregate"]["statuses"])
        self.assertEqual({"spotlight_reflex": 2}, summary["aggregate"]["models"])
        self.assertEqual(2, summary["aggregate"]["scene_count"])
        self.assertEqual(42, summary["aggregate"]["total_frames"])
        self.assertEqual(0, summary["aggregate"]["sensor_failure_count"])
        self.assertEqual({"ok": 42}, summary["aggregate"]["result_counts"])
        self.assertEqual([_sha256(b"bundle\n")], summary["aggregate"]["support_bundle_hashes"])
        self.assertTrue(any("Plan-only runs" in item for item in summary["advice"]))

    def test_strict_main_fails_for_plan_only_summary(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_summary")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            evidence = root / "evidence"
            output = root / "summary.json"
            _write_plan_evidence(evidence)

            with patch.object(
                sys,
                "argv",
                [
                    "wod2sim-benchmark-summary",
                    "--evidence-dir",
                    str(evidence),
                    "--output",
                    str(output),
                    "--strict",
                    "--json",
                ],
            ):
                returncode = module.main()

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(1, returncode)
        self.assertTrue(payload["valid"])
        self.assertFalse(payload["valid_claim_evidence"])

    def test_strict_main_accepts_valid_executed_summary(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_summary")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            evidence = root / "evidence"
            _write_valid_evidence(evidence)

            with patch.object(
                sys,
                "argv",
                [
                    "wod2sim-benchmark-summary",
                    "--manifest",
                    str(evidence / "closed-loop-reproduction-manifest.json"),
                    "--strict",
                    "--json",
                ],
            ):
                returncode = module.main()

        self.assertEqual(0, returncode)


def _write_valid_evidence(evidence_dir: Path) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        evidence_dir / "closed-loop-reproduction-manifest.json",
        {
            "schema": "wod2sim_closed_loop_reproduction_v1",
            "status": "completed",
            "mode": "execute",
            "valid_claim_evidence": True,
            "model": "spotlight_reflex",
            "scene_preset": "front_camera_10scene_smoke",
            "scene_ids": ["scene-a"],
            "run_dir": str(evidence_dir.parent / "run"),
            "requires_gated_or_user_assets": {"alpasim_scene_assets": True},
            "user_supplied_artifacts": {"checkpoint": None, "oracle_actor_proxy": None},
            "provenance": {"git": {"commit": "abc123", "branch": "main", "dirty": False}},
        },
    )
    _write_json(
        evidence_dir / "run-audit.json",
        {
            "schema": "wod2sim_run_audit_v1",
            "valid": True,
            "model": "spotlight_reflex",
            "scene_ids": ["scene-a"],
            "frame_count": 42,
            "sensor_pipeline_ok": True,
            "sensor_failure_count": 0,
            "result_counts": {"ok": 42},
            "sensor_status_counts": {"ok_camera_advanced": 42},
            "max_pose_camera_lag_us": 0,
            "run_status": {"state": "completed", "phase": "both", "aggregate_status": "completed"},
            "driver_log": {"kind": "spotlight", "present": True},
        },
    )
    _write_json(
        evidence_dir / "support-bundle-report.json",
        {
            "schema": "wod2sim_support_bundle_v1",
            "valid": True,
            "copied_file_count": 9,
            "missing_file_count": 0,
            "missing_files": [],
            "bundle_path": str(evidence_dir / "support-bundle.tar.gz"),
            "run_audit": {
                "valid": True,
                "sensor_pipeline_ok": True,
                "sensor_failure_count": 0,
                "driver_log_kind": "spotlight",
            },
        },
    )
    (evidence_dir / "support-bundle.tar.gz").write_bytes(b"bundle\n")


def _write_plan_evidence(evidence_dir: Path) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        evidence_dir / "closed-loop-reproduction-manifest.json",
        {
            "schema": "wod2sim_closed_loop_reproduction_v1",
            "status": "planned",
            "mode": "plan",
            "valid_claim_evidence": False,
            "model": "spotlight_reflex",
            "scene_preset": "fresh_3scene",
            "scene_ids": ["scene-b"],
            "run_dir": str(evidence_dir.parent / "run"),
            "requires_gated_or_user_assets": {"alpasim_scene_assets": True},
            "user_supplied_artifacts": {},
            "provenance": {"git": {"commit": "abc123", "branch": "main", "dirty": False}},
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


if __name__ == "__main__":
    unittest.main()
