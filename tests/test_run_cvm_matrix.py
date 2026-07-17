from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_cvm_matrix.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_cvm_matrix", SCRIPT)
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


class RunCVMMatrixTests(unittest.TestCase):
    def test_closed_loop_launch_plan_uses_alpasim_relative_local_usdz_cache(self) -> None:
        module = _load_module()
        python = str(ROOT / ".venv" / "bin" / "python")

        plan = module._closed_loop_launch_plan(
            config=_base_config(),
            row=_base_row(),
            output=Path("artifacts/cvm/results/core"),
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

    def test_closed_loop_launch_plan_supports_command_only_route_ablation(self) -> None:
        module = _load_module()
        config = _base_config()
        config["name"] = "semantic_ablation"
        config["execution"]["mode"] = "closed_loop_ablation"
        config["execution"]["wizard_args"] = ["eval.video.render_video=false"]
        row = _base_row()
        row["matrix"] = "semantic_ablation"
        row["policy"] = "route_following"
        row["adapter_config"] = "command_only_route"

        plan = module._closed_loop_launch_plan(
            config=config,
            row=row,
            output=Path("artifacts/cvm/results/semantic_ablation"),
            python_executable="python",
        )

        self.assertIsNotNone(plan)
        self.assertTrue(plan["supported"])
        self.assertIn("--driver-env", plan["command"])
        self.assertIn("WOD2SIM_ROUTE_CONTRACT_MODE=command_only_route", plan["command"])
        self.assertIn("eval.video.render_video=false", plan["command"])
        self.assertEqual(
            {"WOD2SIM_ROUTE_CONTRACT_MODE": "command_only_route"},
            plan["driver_env"],
        )

    def test_alpasim_state_is_absent_without_configured_root(self) -> None:
        module = _load_module()

        state = module._alpasim_checkout_state({"mode": "synthetic_harness"})

        self.assertEqual("", state["path"])
        self.assertFalse(state["present"])
        self.assertIsNone(state["dirty"])
        self.assertEqual([], state["status_paths"])

    def test_execution_not_requested_is_planned_not_blocked(self) -> None:
        module = _load_module()

        row = module._planned_row(_base_row())

        self.assertEqual("planned", row["status"])
        self.assertEqual("false", row["attempted"])
        self.assertEqual("false", row["completed"])
        self.assertEqual("false", row["blocked"])
        self.assertEqual("", row["failure_code"])

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
                output=Path("artifacts/cvm/results/core"),
            )

            manifest_path = next(manifest_dir.glob("*.json"))
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual("cvm_run_manifest_v1", payload["schema"])
        self.assertTrue(payload["blocked"])
        self.assertIn("planned_launch", payload)
        self.assertTrue(payload["planned_launch"]["supported"])
        self.assertIn("--scene-id", payload["planned_launch"]["command"])
        self.assertIn("provenance", payload)
        self.assertIn("repository", payload["provenance"])
        self.assertIn("patches", payload["provenance"])
        self.assertEqual(
            "integration_precondition_or_unsupported_contract",
            payload["failure_attribution"]["category"],
        )
        self.assertFalse(payload["failure_attribution"]["policy_attributable"])
        self.assertFalse(payload["failure_attribution"]["policy_behavior_attributable"])
        self.assertFalse(payload["failure_attribution"]["policy_failure_attributable"])
        self.assertTrue(payload["failure_attribution"]["integration_failure_attributable"])
        self.assertEqual(
            "integration_precondition_blocker_not_policy_failure",
            payload["failure_attribution"]["interpretation"],
        )
        self.assertIn("contract_expectations", payload)
        self.assertEqual("scene_metadata_unavailable", payload["scenario_category"])
        self.assertEqual("clipgt-scene", payload["scene"]["scene_id"])
        self.assertEqual("scene_metadata_unavailable", payload["scene"]["category"])
        self.assertEqual("alpasim_waypoints", payload["contract_expectations"]["route_source"])
        self.assertEqual(5.0, payload["contract_expectations"]["source_horizon_seconds"])
        self.assertEqual(4, payload["contract_expectations"]["target_runtime_frequency_hz"])

    def test_scene_metadata_uses_configured_scene_manifest(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            scene_manifest = Path(tmp) / "scene_manifest.yaml"
            scene_manifest.write_text(
                "\n".join(
                    [
                        "schema: cvm_scene_manifest_v1",
                        "source:",
                        "  categories_verified: false",
                        "scenes:",
                        "  - scene_id: clipgt-scene",
                        "    category: available_front_camera_26_02_unclassified",
                        "    selection_rationale: local cache entry",
                        "    asset_availability: local_usdz_present",
                        "    expected_route_feature: unverified",
                        "    expected_interaction_feature: unverified",
                        "    license_gating_status: gated_asset_referenced_not_redistributed",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            config = _base_config()
            config["scene_manifest"] = str(scene_manifest)

            metadata = module._scene_metadata(config, _base_row())

        self.assertEqual("clipgt-scene", metadata["scene_id"])
        self.assertEqual("available_front_camera_26_02_unclassified", metadata["category"])
        self.assertEqual(
            "available_front_camera_26_02_unclassified",
            metadata["scenario_category"],
        )
        self.assertEqual("local_usdz_present", metadata["asset_availability"])
        self.assertFalse(metadata["categories_verified"])

    def test_scene_metadata_marks_synthetic_harness_public(self) -> None:
        module = _load_module()
        config = {"execution": {"mode": "synthetic_fault_injection"}}
        row = {**_base_row(), "scene_id": "synthetic_fault_harness"}

        metadata = module._scene_metadata(config, row)

        self.assertEqual("synthetic_fault_harness", metadata["category"])
        self.assertEqual("public_synthetic", metadata["license_gating_status"])
        self.assertTrue(metadata["categories_verified"])

    def test_command_only_manifest_records_proxy_route_expectation(self) -> None:
        module = _load_module()
        config = _base_config()
        config["name"] = "semantic_ablation"
        config["execution"]["mode"] = "closed_loop_ablation"
        row = _base_row()
        row["matrix"] = "semantic_ablation"
        row["policy"] = "route_following"
        row["adapter_config"] = "command_only_route"

        expectations = module._contract_expectations(config, row)

        self.assertEqual("command_proxy", expectations["route_source"])
        self.assertFalse(expectations["claim_valid_requires_route_waypoints"])

    def test_source_state_pathspec_ignores_generated_release_artifacts(self) -> None:
        module = _load_module()

        pathspec = module._source_state_pathspec()

        self.assertEqual(".", pathspec[0])
        self.assertIn(":(exclude)artifacts/cvm", pathspec)
        self.assertIn(":(exclude)paper/cvm/generated", pathspec)
        self.assertIn(":(exclude)wod2sim.pdf", pathspec)

    def test_git_status_paths_extracts_modified_and_untracked_paths(self) -> None:
        module = _load_module()

        paths = module._git_status_paths(
            " M Dockerfile\n"
            "R  old/path.py -> new/path.py\n"
            "?? src/wizard/configs/deploy/local_arm_external_driver.yaml\n"
        )

        self.assertEqual(
            [
                "Dockerfile",
                "new/path.py",
                "src/wizard/configs/deploy/local_arm_external_driver.yaml",
            ],
            paths,
        )
        self.assertEqual(["Dockerfile"], module._git_status_paths("M Dockerfile\n"))

    def test_failure_attribution_never_treats_unvalidated_rows_as_policy_failure(self) -> None:
        module = _load_module()

        blocked = module._failure_attribution(_base_row())
        completed = module._failure_attribution(
            {
                **_base_row(),
                "status": "completed",
                "attempted": "true",
                "completed": "true",
                "blocked": "false",
                "failure_layer": "",
                "failure_code": "",
            }
        )

        self.assertEqual("integration_precondition_or_unsupported_contract", blocked["category"])
        self.assertFalse(blocked["policy_attributable"])
        self.assertFalse(blocked["policy_failure_attributable"])
        self.assertEqual(
            "integration_precondition_blocker_not_policy_failure",
            blocked["interpretation"],
        )
        self.assertEqual("diagnostic_rollout_pending_claim_gate", completed["category"])
        self.assertFalse(completed["policy_attributable"])
        self.assertFalse(completed["policy_failure_attributable"])
        self.assertEqual(
            "completed_diagnostic_pending_evidence_gate_not_policy_failure",
            completed["interpretation"],
        )

    def test_policy_failure_attribution_requires_claim_valid_policy_layer(self) -> None:
        module = _load_module()

        policy_row = {
            **_base_row(),
            "status": "completed",
            "attempted": "true",
            "completed": "true",
            "blocked": "false",
            "failure_layer": "policy",
            "failure_code": "collision",
            "claim_valid": "true",
        }

        attribution = module._failure_attribution(policy_row)

        self.assertEqual("policy_attributable_behavior", attribution["category"])
        self.assertTrue(attribution["policy_behavior_attributable"])
        self.assertTrue(attribution["policy_failure_attributable"])
        self.assertFalse(attribution["integration_or_evidence_invalid"])
        self.assertEqual("policy_behavior_allowed", attribution["interpretation"])

    def test_resume_without_execute_preserves_completed_rows(self) -> None:
        module = _load_module()
        row = _base_row()
        existing = dict(row)
        existing.update(
            {
                "status": "completed",
                "attempted": "true",
                "completed": "true",
                "blocked": "false",
                "failure_layer": "",
                "failure_code": "",
                "detail": "existing completed evidence",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            with (output / "runs.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=module.RUN_FIELDS)
                writer.writeheader()
                writer.writerow(existing)

            rows = module._load_existing_rows(output)
            preserved = module._resume_preserved_row(rows, row, execute=False)

        self.assertIsNotNone(preserved)
        self.assertEqual("completed", preserved["status"])
        self.assertEqual("true", preserved["completed"])
        self.assertEqual("existing completed evidence", preserved["detail"])


if __name__ == "__main__":
    unittest.main()
