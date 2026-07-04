from __future__ import annotations

import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPT = ROOT / "scripts" / "wod2sim_doctor.py"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_module():
    return importlib.import_module("minimal_shot_av.cli.commands.wod2sim_doctor")


def _load_script_module():
    spec = importlib.util.spec_from_file_location("wod2sim_doctor_script", SCRIPT)
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
        self.assertIsNone(report["environment"])

    def test_build_report_can_validate_optional_alpasim_environment(self) -> None:
        module = _load_module()

        with patch.object(module, "_scene_ids", return_value=["scene-1", "scene-2"]), patch.object(
            module, "_validate_alpasim_checkout"
        ), patch.object(
            module, "_preflight_platform_compatibility"
        ), patch.object(
            module, "_preflight_docker_access"
        ), patch.object(
            module, "_preflight_nvidia_container_runtime"
        ), patch.object(
            module, "_preflight_alpasim_base_image"
        ), patch.object(
            module, "_preflight_scene_artifacts"
        ):
            report = module.build_report(alpasim_root=Path("/tmp/alpasim"))

        self.assertIsNotNone(report["environment"])
        self.assertTrue(report["environment"]["valid"])
        self.assertEqual("ok", report["environment"]["statuses"]["alpasim_checkout"])
        self.assertEqual(["scene-1", "scene-2"], report["environment"]["scene_ids"])

    def test_build_report_surfaces_environment_failures(self) -> None:
        module = _load_module()

        with patch.object(module, "_scene_ids", return_value=["scene-1"]), patch.object(
            module, "_validate_alpasim_checkout", side_effect=SystemExit("missing checkout")
        ), patch.object(
            module, "_preflight_platform_compatibility"
        ), patch.object(
            module, "_preflight_docker_access", side_effect=SystemExit("docker denied")
        ):
            report = module.build_report(
                alpasim_root=Path("/tmp/alpasim"),
                skip_gpu_runtime=True,
                skip_image=True,
                skip_scene_artifacts=False,
            )

        self.assertFalse(report["valid"])
        self.assertEqual("failed", report["environment"]["statuses"]["alpasim_checkout"])
        self.assertEqual("failed", report["environment"]["statuses"]["docker_access"])
        self.assertEqual("blocked", report["environment"]["statuses"]["scene_artifacts"])
        self.assertIn("missing checkout", report["environment"]["errors"]["alpasim_checkout"])

    def test_script_can_write_json_report(self) -> None:
        _load_script_module()
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
