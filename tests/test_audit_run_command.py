from __future__ import annotations

import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPT = ROOT / "scripts" / "audit_run.py"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_module():
    return importlib.import_module("wod2sim.cli.commands.audit_run")


def _load_script_module():
    spec = importlib.util.spec_from_file_location("wod2sim_audit_run_script", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WOD2SimAuditRunTests(unittest.TestCase):
    def test_build_report_summarizes_sensor_failure(self) -> None:
        module = _load_module()
        with TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "run"
            (run_dir / "driver").mkdir(parents=True)
            (run_dir / "launch-metadata.json").write_text(
                json.dumps({"model": "spotlight_reflex", "scene_preset": "fresh_3scene", "scene_ids": ["clipgt-1"]}),
                encoding="utf-8",
            )
            (run_dir / "run-status.json").write_text(
                json.dumps({"state": "failed", "phase": "both", "driver_returncode": -15, "wizard_returncode": 1}),
                encoding="utf-8",
            )
            (run_dir / "driver" / "spotlight-log.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "frame_index": 1,
                                "scene_id": "clipgt-1",
                                "command": "straight",
                                "result": "ok",
                                "sensor_freshness": {
                                    "status": "ok_initial",
                                    "pose_camera_lag_us": 0,
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "frame_index": 2,
                                "scene_id": "clipgt-1",
                                "command": "straight",
                                "result": "sensor_failure",
                                "sensor_error": "stale camera stream",
                                "sensor_freshness": {
                                    "status": "stale_camera_timestamp",
                                    "pose_camera_lag_us": 100,
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            report = module.build_report(run_dir=run_dir)

        self.assertFalse(report["valid"])
        self.assertTrue(report["run_status"]["present"])
        self.assertEqual("failed", report["run_status"]["state"])
        self.assertEqual("spotlight", report["driver_log"]["kind"])
        self.assertEqual(2, report["frame_count"])
        self.assertFalse(report["sensor_pipeline_ok"])
        self.assertEqual(1, report["sensor_failure_count"])
        self.assertEqual(100, report["max_pose_camera_lag_us"])
        self.assertEqual("stale_camera_timestamp", report["first_sensor_failure"]["status"])

    def test_build_report_can_export_normalized_audit_bundle(self) -> None:
        module = _load_module()
        with TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "run"
            audit_dir = Path(tmpdir) / "audit"
            (run_dir / "driver").mkdir(parents=True)
            (run_dir / "launch-metadata.json").write_text(
                json.dumps({"model": "spotlight_reflex", "scene_preset": "fresh_3scene", "scene_ids": ["clipgt-1"]}),
                encoding="utf-8",
            )
            (run_dir / "driver" / "spotlight-log.jsonl").write_text(
                json.dumps(
                    {
                        "frame_index": 1,
                        "scene_id": "clipgt-1",
                        "command": "straight",
                        "selected_maneuver": "maintain",
                        "candidate_count": 9,
                        "reference_count": 2,
                        "result": "ok",
                        "alpasim_signal": {"structured_hazards": [], "route_waypoints": []},
                        "sensor_freshness": {"status": "ok_initial", "pose_camera_lag_us": 0},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            report = module.build_report(run_dir=run_dir, audit_dir=audit_dir)

            self.assertTrue(report["valid"])
            self.assertIsNotNone(report["audit_export"])
            assert report["audit_export"] is not None
            self.assertEqual(str(audit_dir.resolve()), report["audit_export"]["audit_dir"])
            self.assertEqual(1, report["audit_export"]["frame_count"])
            self.assertTrue((audit_dir / "manifest.json").is_file())
            self.assertTrue((audit_dir / "frames.jsonl").is_file())

    def test_script_can_write_json_report(self) -> None:
        _load_script_module()
        with TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "run"
            output = Path(tmpdir) / "audit-report.json"
            (run_dir / "driver").mkdir(parents=True)
            (run_dir / "launch-metadata.json").write_text(
                json.dumps({"model": "spotlight_reflex", "scene_preset": "fresh_3scene", "scene_ids": ["clipgt-1"]}),
                encoding="utf-8",
            )
            (run_dir / "driver" / "spotlight-log.jsonl").write_text(
                json.dumps(
                    {
                        "frame_index": 1,
                        "scene_id": "clipgt-1",
                        "command": "straight",
                        "result": "ok",
                        "sensor_freshness": {"status": "ok_initial", "pose_camera_lag_us": 0},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--run-dir", str(run_dir), "--json", "--output", str(output)],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            payload = json.loads(result.stdout)
            self.assertEqual("wod2sim_run_audit_v1", payload["schema"])
            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
