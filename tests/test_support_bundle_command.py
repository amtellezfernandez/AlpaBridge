from __future__ import annotations

import importlib
import importlib.util
import json
import subprocess
import sys
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPT = ROOT / "scripts" / "support_bundle.py"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_module():
    return importlib.import_module("wod2sim.cli.commands.support_bundle")


def _load_script_module():
    spec = importlib.util.spec_from_file_location("wod2sim_support_bundle_script", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WOD2SimSupportBundleTests(unittest.TestCase):
    def test_build_report_creates_bundle_with_audit_outputs(self) -> None:
        module = _load_module()
        with TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "run"
            output = Path(tmpdir) / "bundle.tar.gz"
            (run_dir / "driver").mkdir(parents=True)
            (run_dir / "launch-metadata.json").write_text(
                json.dumps({"model": "spotlight_reflex", "scene_preset": "fresh_3scene", "scene_ids": ["clipgt-1"]}),
                encoding="utf-8",
            )
            (run_dir / "run-status.json").write_text(
                json.dumps({"state": "failed", "phase": "both"}, indent=2),
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
            (run_dir / "driver.stdout.log").write_text("driver ok\n", encoding="utf-8")

            report = module.build_report(run_dir=run_dir, output=output)

            self.assertTrue(report["valid"])
            self.assertTrue(output.is_file())
            self.assertEqual(4, report["copied_file_count"])
            with tarfile.open(output, "r:gz") as archive:
                names = set(archive.getnames())
            self.assertIn("run_support_bundle/run-audit.json", names)
            self.assertIn("run_support_bundle/run-status.json", names)
            self.assertIn("run_support_bundle/audit/manifest.json", names)
            self.assertIn("run_support_bundle/driver/spotlight-log.jsonl", names)
            self.assertIn("run_support_bundle/support-bundle-manifest.json", names)

    def test_script_can_write_json_report(self) -> None:
        _load_script_module()
        with TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "run"
            output = Path(tmpdir) / "bundle.tar.gz"
            report_path = Path(tmpdir) / "bundle-report.json"
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
                [
                    sys.executable,
                    str(SCRIPT),
                    "--run-dir",
                    str(run_dir),
                    "--output",
                    str(output),
                    "--json",
                    "--output-report",
                    str(report_path),
                ],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            payload = json.loads(result.stdout)
            self.assertEqual("wod2sim_support_bundle_v1", payload["schema"])
            self.assertTrue(output.exists())
            self.assertTrue(report_path.exists())


if __name__ == "__main__":
    unittest.main()
