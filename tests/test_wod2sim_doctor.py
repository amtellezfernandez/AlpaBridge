from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "wod2sim_doctor.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wod2sim_doctor", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WOD2SimDoctorTests(unittest.TestCase):
    def test_build_report_validates_public_release_surface(self) -> None:
        module = _load_module()

        report = module.build_report()

        self.assertTrue(report["valid"])
        self.assertEqual("wod2sim_doctor_v1", report["schema"])
        self.assertEqual(
            ["spotlight_reflex", "token_dagger_bc", "direct_actor_planner"],
            report["public_models"],
        )
        self.assertTrue(report["checks"]["scene_presets_present"])
        self.assertTrue(report["checks"]["public_model_configs_present"])
        self.assertTrue(
            report["checks"]["installed_entry_points_present"]
            or report["checks"]["wrapper_scripts_present"]
        )

    def test_script_can_write_json_report(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "doctor.json"

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--json", "--output", str(output)],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            payload = json.loads(result.stdout)
            self.assertEqual("wod2sim_doctor_v1", payload["schema"])
            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
