from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_sii2027_matrix.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_sii2027_matrix", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base_config() -> dict:
    return {
        "name": "core",
        "execution": {
            "mode": "closed_loop",
            "alpasim_root": "workspace/alpasim-clean",
            "local_usdz_dir": (
                "workspace/alpasim-clean/data/nre-artifacts/"
                "local-usdzs-front-camera-15"
            ),
            "scene_preset": "front_camera_50scene_public2602",
            "timeout_seconds": 900,
            "required_docker_image": "alpasim-base:0.66.0",
        },
    }


def _base_row() -> dict[str, str]:
    return {
        "run_id": "core_constant_velocity_clipgt-scene_17_full_contract",
        "matrix": "core",
        "policy": "constant_velocity",
        "scene_id": "clipgt-scene",
        "seed": "17",
        "adapter_config": "full_contract",
        "status": "blocked",
        "attempted": "false",
        "completed": "false",
        "blocked": "true",
        "failure_layer": "deployment",
        "failure_code": "execution_not_requested",
        "detail": "planned",
        "claim_valid": "false",
    }


class RunSII2027MatrixTests(unittest.TestCase):
    def test_closed_loop_launch_plan_uses_alpasim_relative_local_usdz_cache(self) -> None:
        module = _load_module()
        python = str(ROOT / ".venv" / "bin" / "python")

        plan = module._closed_loop_launch_plan(
            config=_base_config(),
            row=_base_row(),
            output=Path("artifacts/sii2027/results/core"),
            python_executable=python,
        )

        self.assertIsNotNone(plan)
        self.assertTrue(plan["supported"])
        self.assertEqual("data/nre-artifacts/local-usdzs-front-camera-15", plan["local_usdz_dir"])
        self.assertIn(
            "scenes.local_usdz_dir=data/nre-artifacts/local-usdzs-front-camera-15",
            plan["command"],
        )
        self.assertIn("--local-usdz-dir", plan["readiness_command"])
        self.assertIn("data/nre-artifacts/local-usdzs-front-camera-15", plan["readiness_command"])
        self.assertEqual(".venv/bin/python", plan["command"][0])
        self.assertFalse(any("/home/" in str(item) for item in plan["command"]))

    def test_closed_loop_launch_plan_blocks_unimplemented_semantic_ablation(self) -> None:
        module = _load_module()
        config = _base_config()
        config["name"] = "semantic_ablation"
        config["execution"]["mode"] = "closed_loop_ablation"
        row = _base_row()
        row["matrix"] = "semantic_ablation"
        row["adapter_config"] = "command_only_route"

        plan = module._closed_loop_launch_plan(
            config=config,
            row=row,
            output=Path("artifacts/sii2027/results/semantic_ablation"),
            python_executable="python",
        )

        self.assertIsNotNone(plan)
        self.assertFalse(plan["supported"])
        self.assertIsNone(plan["command"])
        self.assertEqual(
            "semantic_ablation_runtime_flag_missing",
            plan["unsupported_reasons"][0]["code"],
        )

    def test_run_manifest_contains_closed_loop_launch_plan(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            manifest_dir = Path(tmp) / "manifests"
            config_path = Path(tmp) / "core.yaml"
            config_path.write_text("name: core\n", encoding="utf-8")

            module._write_run_manifest(
                manifest_dir,
                row=_base_row(),
                config=_base_config(),
                config_path=config_path,
                python_executable="python",
                output=Path("artifacts/sii2027/results/core"),
            )

            manifest_path = next(manifest_dir.glob("*.json"))
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual("sii2027_run_manifest_v1", payload["schema"])
        self.assertIn("planned_launch", payload)
        self.assertTrue(payload["planned_launch"]["supported"])
        self.assertIn("--scene-id", payload["planned_launch"]["command"])


if __name__ == "__main__":
    unittest.main()
