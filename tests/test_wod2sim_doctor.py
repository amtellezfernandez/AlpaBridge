from __future__ import annotations

import importlib
import importlib.util
import json
import subprocess
import sys
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPT = ROOT / "scripts" / "wod2sim_doctor.py"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_module():
    return importlib.import_module("wod2sim.cli.commands.wod2sim_doctor")


def _load_script_module():
    spec = importlib.util.spec_from_file_location("wod2sim_doctor_script", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeDist:
    def __init__(self, name: str, entry_points: list[SimpleNamespace]) -> None:
        self.metadata = {"Name": name}
        self.entry_points = entry_points
        self.version = "0.1.0"


def _clean_wod2sim_dist(module) -> FakeDist:
    wod2sim_console_scripts = [
        SimpleNamespace(name=name, group="console_scripts", value=f"wod2sim.cli:{name}")
        for name in module.EXPECTED_CONSOLE_SCRIPTS
    ]
    wod2sim_model_entry_points = [
        SimpleNamespace(
            name="spotlight_reflex",
            group="alpasim.models",
            value="wod2sim.simulator.alpasim_spotlight:SpotlightReflexAlpaSimModel",
        ),
        SimpleNamespace(
            name="token_dagger_bc",
            group="alpasim.models",
            value="wod2sim.simulator.alpasim_token_bc:TokenBCAlpaSimModel",
        ),
        SimpleNamespace(
            name="direct_actor_planner",
            group="alpasim.models",
            value="wod2sim.simulator.alpasim_direct_actor_planner:DirectActorPlannerAlpaSimModel",
        ),
    ]
    return FakeDist("wod2sim", wod2sim_console_scripts + wod2sim_model_entry_points)


class WOD2SimDoctorTests(unittest.TestCase):
    def test_build_report_validates_public_release_surface(self) -> None:
        module = _load_module()
        wod2sim_dist = _clean_wod2sim_dist(module)

        with patch.object(module, "distribution", return_value=wod2sim_dist), patch.object(
            module, "distributions", return_value=[wod2sim_dist]
        ):
            report = module.build_report()

        self.assertTrue(report["valid"])
        self.assertEqual("wod2sim_doctor_v1", report["schema"])
        self.assertEqual(
            ["spotlight_reflex", "token_dagger_bc", "direct_actor_planner"],
            report["public_models"],
        )
        self.assertTrue(report["checks"]["public_model_registry_curated"])
        self.assertTrue(report["checks"]["scene_presets_present"])
        self.assertTrue(report["checks"]["public_model_configs_present"])
        self.assertTrue(report["checks"]["legacy_distributions_absent"])
        self.assertTrue(report["checks"]["public_model_entry_points_unique"])
        self.assertTrue(report["checks"]["public_model_entry_points_owned_by_wod2sim"])
        self.assertTrue(
            report["checks"]["installed_entry_points_present"]
            or report["checks"]["wrapper_scripts_present"]
        )
        self.assertIsNone(report["environment"])
        self.assertEqual([], report["conflicts"]["legacy_distributions"])
        self.assertEqual([], report["conflicts"]["duplicate_public_model_entry_points"])
        self.assertEqual([], report["conflicts"]["unexpected_public_model_providers"])

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

    def test_build_report_can_probe_default_environment_without_explicit_root(self) -> None:
        module = _load_module()

        with patch.object(module, "_default_alpasim_root", return_value=Path("/tmp/default-alpasim")), patch.object(
            module, "_scene_ids", return_value=["scene-1"]
        ), patch.object(
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
            report = module.build_report(probe_default_environment=True)

        self.assertIsNotNone(report["environment"])
        self.assertEqual("/tmp/default-alpasim", report["environment"]["alpasim_root"])
        self.assertTrue(report["environment"]["valid"])

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

    def test_human_report_suggests_scene_artifact_bypass_when_cache_is_missing(self) -> None:
        module = _load_module()
        wod2sim_dist = _clean_wod2sim_dist(module)
        with patch.object(module, "distribution", return_value=wod2sim_dist), patch.object(
            module, "distributions", return_value=[wod2sim_dist]
        ):
            report = module.build_report()
        report["environment"] = {
            "valid": False,
            "alpasim_root": "/tmp/alpasim",
            "scene_preset": "fresh_3scene",
            "scene_ids": ["scene-1"],
            "statuses": {
                "alpasim_checkout": "ok",
                "platform_compatibility": "ok",
                "docker_access": "ok",
                "base_image": "ok",
                "gpu_runtime": "ok",
                "scene_artifacts": "failed",
            },
            "errors": {
                "scene_artifacts": "missing assets",
            },
        }
        report["valid"] = False

        with patch("sys.stdout", new_callable=StringIO) as stdout:
            module._print_human_report(report, strict_installed=False)

        rendered = stdout.getvalue()
        self.assertIn("--skip-scene-artifacts", rendered)
        self.assertIn("--scene-preset", rendered)

    def test_human_report_suggests_bootstrap_when_checkout_is_missing(self) -> None:
        module = _load_module()
        wod2sim_dist = _clean_wod2sim_dist(module)
        with patch.object(module, "distribution", return_value=wod2sim_dist), patch.object(
            module, "distributions", return_value=[wod2sim_dist]
        ):
            report = module.build_report()
        report["environment"] = {
            "valid": False,
            "alpasim_root": "/tmp/alpasim",
            "scene_preset": "fresh_3scene",
            "scene_ids": ["scene-1"],
            "statuses": {
                "alpasim_checkout": "failed",
                "platform_compatibility": "ok",
                "docker_access": "ok",
                "base_image": "ok",
                "gpu_runtime": "ok",
                "scene_artifacts": "blocked",
            },
            "errors": {
                "alpasim_checkout": "missing checkout",
                "scene_artifacts": "blocked by missing checkout",
            },
        }
        report["valid"] = False

        with patch("sys.stdout", new_callable=StringIO) as stdout:
            module._print_human_report(report, strict_installed=False)

        rendered = stdout.getvalue()
        self.assertIn("bootstrap_alpasim_checkout.sh", rendered)
        self.assertIn("--probe-default-environment", rendered)

    def test_build_report_flags_legacy_distribution_and_duplicate_model_provider_conflicts(self) -> None:
        module = _load_module()

        wod2sim_console_scripts = [
            SimpleNamespace(name=name, group="console_scripts", value=f"wod2sim.cli:{name}")
            for name in module.EXPECTED_CONSOLE_SCRIPTS
        ]
        wod2sim_model_entry_points = [
            SimpleNamespace(
                name="spotlight_reflex",
                group="alpasim.models",
                value="wod2sim.simulator.alpasim_spotlight:SpotlightReflexAlpaSimModel",
            ),
            SimpleNamespace(
                name="token_dagger_bc",
                group="alpasim.models",
                value="wod2sim.simulator.alpasim_token_bc:TokenBCAlpaSimModel",
            ),
            SimpleNamespace(
                name="direct_actor_planner",
                group="alpasim.models",
                value="wod2sim.simulator.alpasim_direct_actor_planner:DirectActorPlannerAlpaSimModel",
            ),
        ]
        wod2sim_dist = FakeDist("wod2sim", wod2sim_console_scripts + wod2sim_model_entry_points)
        stale_slipway_dist = FakeDist(
            "slipway",
            [
                SimpleNamespace(
                    name="spotlight_reflex",
                    group="alpasim.models",
                    value="slipway.simulator.alpasim_spotlight:SpotlightReflexAlpaSimModel",
                )
            ],
        )

        with patch.object(module, "distribution", return_value=wod2sim_dist), patch.object(
            module, "distributions", return_value=[wod2sim_dist, stale_slipway_dist]
        ):
            report = module.build_report()

        self.assertFalse(report["valid"])
        self.assertFalse(report["checks"]["legacy_distributions_absent"])
        self.assertFalse(report["checks"]["public_model_entry_points_unique"])
        self.assertFalse(report["checks"]["public_model_entry_points_owned_by_wod2sim"])
        self.assertEqual(["slipway"], report["conflicts"]["legacy_distributions"])
        self.assertEqual(
            [
                "spotlight_reflex: wod2sim -> wod2sim.simulator.alpasim_spotlight:SpotlightReflexAlpaSimModel, "
                "slipway -> slipway.simulator.alpasim_spotlight:SpotlightReflexAlpaSimModel"
            ],
            report["conflicts"]["duplicate_public_model_entry_points"],
        )
        self.assertEqual(
            [
                "spotlight_reflex: slipway -> slipway.simulator.alpasim_spotlight:SpotlightReflexAlpaSimModel"
            ],
            report["conflicts"]["unexpected_public_model_providers"],
        )

    def test_build_report_deduplicates_identical_model_entry_points_from_same_distribution(self) -> None:
        module = _load_module()

        duplicated_spotlight = SimpleNamespace(
            name="spotlight_reflex",
            group="alpasim.models",
            value="wod2sim.simulator.alpasim_spotlight:SpotlightReflexAlpaSimModel",
        )
        wod2sim_console_scripts = [
            SimpleNamespace(name=name, group="console_scripts", value=f"wod2sim.cli:{name}")
            for name in module.EXPECTED_CONSOLE_SCRIPTS
        ]
        wod2sim_dist = FakeDist(
            "wod2sim",
            wod2sim_console_scripts
            + [
                duplicated_spotlight,
                duplicated_spotlight,
                SimpleNamespace(
                    name="token_dagger_bc",
                    group="alpasim.models",
                    value="wod2sim.simulator.alpasim_token_bc:TokenBCAlpaSimModel",
                ),
                SimpleNamespace(
                    name="direct_actor_planner",
                    group="alpasim.models",
                    value="wod2sim.simulator.alpasim_direct_actor_planner:DirectActorPlannerAlpaSimModel",
                ),
            ],
        )

        with patch.object(module, "distribution", return_value=wod2sim_dist), patch.object(
            module, "distributions", return_value=[wod2sim_dist]
        ):
            report = module.build_report()

        self.assertTrue(report["valid"])
        self.assertEqual([], report["conflicts"]["duplicate_public_model_entry_points"])
        self.assertEqual(
            [
                {
                    "dist": "wod2sim",
                    "value": "wod2sim.simulator.alpasim_spotlight:SpotlightReflexAlpaSimModel",
                }
            ],
            report["public_model_entry_point_providers"]["spotlight_reflex"],
        )

    def test_human_report_surfaces_environment_conflicts(self) -> None:
        module = _load_module()
        wod2sim_dist = _clean_wod2sim_dist(module)
        with patch.object(module, "distribution", return_value=wod2sim_dist), patch.object(
            module, "distributions", return_value=[wod2sim_dist]
        ):
            report = module.build_report()
        report["valid"] = False
        report["conflicts"] = {
            "legacy_distributions": ["slipway"],
            "duplicate_public_model_entry_points": [
                "spotlight_reflex: wod2sim -> wod2sim.simulator.alpasim_spotlight:SpotlightReflexAlpaSimModel, slipway -> slipway.simulator.alpasim_spotlight:SpotlightReflexAlpaSimModel"
            ],
            "unexpected_public_model_providers": [
                "spotlight_reflex: slipway -> slipway.simulator.alpasim_spotlight:SpotlightReflexAlpaSimModel"
            ],
        }

        with patch("sys.stdout", new_callable=StringIO) as stdout:
            module._print_human_report(report, strict_installed=False)

        rendered = stdout.getvalue()
        self.assertIn("legacy_distributions: slipway", rendered)
        self.assertIn("duplicate_public_model_entry_points", rendered)
        self.assertIn("rerun wod2sim-setup", rendered)

    def test_script_can_write_json_report(self) -> None:
        _load_script_module()
        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "doctor.json"

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--json", "--output", str(output)],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn(result.returncode, {0, 1})
            payload = json.loads(result.stdout)
            self.assertEqual("wod2sim_doctor_v1", payload["schema"])
            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
