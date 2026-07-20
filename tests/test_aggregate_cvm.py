from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aggregate_cvm.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("aggregate_cvm", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row() -> dict[str, str]:
    return {
        "run_id": "core_constant_velocity_scene-a_17_full_contract",
        "matrix": "core",
        "policy": "constant_velocity",
        "scene_id": "scene-a",
        "seed": "17",
        "adapter_config": "full_contract",
        "status": "planned",
        "attempted": "false",
        "completed": "false",
        "blocked": "false",
        "failure_layer": "",
        "failure_code": "",
        "detail": "expanded but not launched",
        "claim_valid": "false",
    }


def _write_rows(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def _write_manifest(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "cvm_run_manifest_v1",
        "run_id": row["run_id"],
        "matrix": row["matrix"],
        "policy": row["policy"],
        "scene_id": row["scene_id"],
        "seed": row["seed"],
        "adapter_config": row["adapter_config"],
        "status": row["status"],
        "attempted": row["attempted"] == "true",
        "completed": row["completed"] == "true",
        "blocked": row["blocked"] == "true",
        "claim_valid": row["claim_valid"] == "true",
        "failure_layer": row["failure_layer"],
        "failure_code": row["failure_code"],
    }
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class AggregateCVMTests(unittest.TestCase):
    def test_validate_run_rows_accepts_matching_manifest(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = root / "results"
            row = _row()
            _write_rows(inputs / "core" / "runs.csv", row)
            _write_manifest(root / "manifests" / "run_manifests" / f"{row['run_id']}.json", row)

            rows = module._load_run_rows(inputs)
            errors = module._validate_run_rows(rows, inputs)

        self.assertEqual([], errors)

    def test_validate_run_rows_reports_missing_manifest(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            inputs = Path(tmp) / "results"
            row = _row()
            _write_rows(inputs / "core" / "runs.csv", row)

            rows = module._load_run_rows(inputs)
            errors = module._validate_run_rows(rows, inputs)

        self.assertTrue(any(error.startswith("missing_run_manifest:") for error in errors))

    def test_validate_run_rows_reports_manifest_mismatch(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = root / "results"
            row = _row()
            manifest_row = dict(row)
            manifest_row["status"] = "completed"
            _write_rows(inputs / "core" / "runs.csv", row)
            _write_manifest(
                root / "manifests" / "run_manifests" / f"{row['run_id']}.json",
                manifest_row,
            )

            rows = module._load_run_rows(inputs)
            errors = module._validate_run_rows(rows, inputs)

        self.assertIn(
            f"run_manifest_field_mismatch:{inputs / 'core' / 'runs.csv'}:{row['run_id']}:status",
            errors,
        )

    def test_failure_attribution_separates_integration_and_policy_rows(self) -> None:
        module = _load_module()
        rows = [
            {
                **_row(),
                "run_id": "contract-valid",
                "status": "completed",
                "attempted": "true",
                "completed": "true",
            },
            {
                **_row(),
                "run_id": "command-proxy",
                "status": "completed",
                "attempted": "true",
                "completed": "true",
            },
            {
                **_row(),
                "run_id": "blocked-direct-actor",
                "status": "blocked",
                "blocked": "true",
                "failure_layer": "deployment",
                "failure_code": "direct_actor_oracle_proxy_missing",
            },
            {
                **_row(),
                "run_id": "synthetic-diagnostic",
                "matrix": "fault_injection",
                "status": "completed",
                "attempted": "true",
                "completed": "true",
            },
        ]
        evidence = [
            {
                "run_id": "contract-valid",
                "audit_valid": "true",
                "route_contract_ok": "true",
                "sensor_pipeline_ok": "true",
            },
            {
                "run_id": "command-proxy",
                "audit_valid": "false",
                "route_contract_ok": "false",
                "sensor_pipeline_ok": "true",
            },
        ]

        summary = module._failure_attribution_summary(rows, evidence)

        self.assertEqual(1, summary["contract_valid_closed_loop_rows"])
        self.assertEqual(1, summary["integration_or_evidence_invalid_closed_loop_rows"])
        self.assertEqual(1, summary["precondition_blocked_rows"])
        self.assertEqual(1, summary["synthetic_diagnostic_rows"])
        self.assertEqual(0, summary["claim_valid_policy_benchmark_rows"])
        self.assertEqual(1, summary["policy_behavior_attributable_rows"])
        self.assertEqual(0, summary["policy_failure_attributable_rows"])
        self.assertEqual(1, summary["integration_failure_attributable_rows"])
        self.assertEqual(2, summary["diagnostic_not_policy_rows"])
        self.assertEqual(3, summary["non_policy_attributed_rows"])

    def test_integration_effectiveness_counts_status_only_route_baseline(self) -> None:
        module = _load_module()
        evidence = [
            {
                "run_id": "semantic_route_following_scene-a_17_full_contract",
                "matrix": "semantic_ablation",
                "policy": "route_following",
                "scene_id": "scene-a",
                "seed": "17",
                "adapter_config": "full_contract",
                "audit_valid": "true",
                "route_contract_ok": "true",
                "metrics_present": "true",
                "progress": "0.25",
            },
            {
                "run_id": "semantic_route_following_scene-a_17_command_only_route",
                "matrix": "semantic_ablation",
                "policy": "route_following",
                "scene_id": "scene-a",
                "seed": "17",
                "adapter_config": "command_only_route",
                "audit_valid": "false",
                "route_contract_ok": "false",
                "metrics_present": "true",
                "progress": "0.10",
            },
        ]

        summary = module._integration_effectiveness_summary(evidence)

        self.assertEqual(1, summary["full_contract_completed_runs"])
        self.assertEqual(1, summary["full_contract_audit_valid_runs"])
        self.assertNotIn("valid_full_contract_false_blocked_runs", summary)
        self.assertEqual(1, summary["semantic_ablation_comparison_eligible_pairs"])
        self.assertEqual(1, summary["status_only_baseline_accepted_runs"])
        self.assertEqual(
            1,
            summary["status_only_baseline_acceptance_denominator"],
        )
        self.assertEqual(1, summary["contract_invalid_evidence_rejected_runs"])
        self.assertEqual(1.0, summary["contract_invalid_evidence_rejection_rate"])
        self.assertEqual(1, summary["status_only_accepted_contract_rejected_runs"])

    def test_semantic_deltas_exclude_pair_with_invalid_full_contract_arm(self) -> None:
        module = _load_module()
        evidence = [
            {
                "run_id": "valid-full",
                "matrix": "semantic_ablation",
                "policy": "route_following",
                "scene_id": "valid-scene",
                "seed": "17",
                "adapter_config": "full_contract",
                "audit_valid": "true",
                "route_contract_ok": "true",
                "metrics_present": "true",
                "progress": "0.4",
            },
            {
                "run_id": "valid-command",
                "matrix": "semantic_ablation",
                "policy": "route_following",
                "scene_id": "valid-scene",
                "seed": "17",
                "adapter_config": "command_only_route",
                "audit_valid": "false",
                "route_contract_ok": "false",
                "metrics_present": "true",
                "progress": "0.1",
            },
            {
                "run_id": "invalid-full",
                "matrix": "semantic_ablation",
                "policy": "route_following",
                "scene_id": "invalid-scene",
                "seed": "17",
                "adapter_config": "full_contract",
                "audit_valid": "false",
                "route_contract_ok": "false",
                "metrics_present": "true",
                "progress": "0.9",
            },
            {
                "run_id": "invalid-command",
                "matrix": "semantic_ablation",
                "policy": "route_following",
                "scene_id": "invalid-scene",
                "seed": "17",
                "adapter_config": "command_only_route",
                "audit_valid": "false",
                "route_contract_ok": "false",
                "metrics_present": "true",
                "progress": "0.2",
            },
        ]

        pair_counts = module._semantic_ablation_pairs(evidence)
        pair_rows = module._semantic_ablation_pair_rows(evidence)
        deltas = module._semantic_ablation_delta_summary(pair_rows)

        self.assertEqual(2, pair_counts["completed_pairs"])
        self.assertEqual(1, pair_counts["comparison_eligible_pairs"])
        self.assertEqual(["false", "true"], sorted(row["comparison_eligible"] for row in pair_rows))
        self.assertEqual(1, deltas["progress"]["count"])
        self.assertEqual(0.3, deltas["progress"]["mean_delta_full_minus_command_only"])

    def test_external_compatibility_summary_counts_driver_conformance(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "challenge-driver-fixed.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"event": "start_session"}),
                        json.dumps({"event": "image"}),
                        json.dumps({"event": "route"}),
                        json.dumps(
                            {
                                "event": "drive",
                                "latency_ms": 2.0,
                                "latency_target_met": True,
                            }
                        ),
                        json.dumps(
                            {
                                "event": "drive",
                                "latency_ms": 4.0,
                                "latency_target_met": True,
                            }
                        ),
                        json.dumps({"event": "close_session"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (root / "results-summary.json").write_text(
                json.dumps(
                    {
                        "rollouts": [
                            {
                                "passed": True,
                                "status": "pass",
                                "score": 0.25,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = module._external_compatibility_summary(root)

        self.assertTrue(summary["available"])
        self.assertEqual(1, summary["rollouts"])
        self.assertEqual(1, summary["passed_rollouts"])
        self.assertEqual(2, summary["drive_rpc_count"])
        self.assertEqual(1, summary["image_event_count"])
        self.assertEqual(2, summary["latency_target_met_count"])
        self.assertEqual(2, summary["latency_target_denominator"])
        self.assertEqual(3.0, summary["driver_latency_mean_ms"])
        self.assertEqual(4.0, summary["driver_latency_max_ms"])
        self.assertEqual(0.25, summary["score"])

    def test_protocol_replay_summary_revalidates_tracked_evidence(self) -> None:
        module = _load_module()

        summary = module._protocol_replay_summary(
            ROOT / "artifacts" / "external" / "alpasim_protocol_replay"
        )

        self.assertTrue(summary["available"])
        self.assertEqual(60, summary["media"]["camera_frames"])
        self.assertEqual(18, summary["media"]["displayed_camera_frames"])
        self.assertEqual(30, summary["media"]["start_drive_index"])
        self.assertEqual(47, summary["media"]["end_drive_index"])
        self.assertEqual(
            1.505999,
            summary["media"]["maximum_endpoint_separation_m"],
        )
        full = summary["arms"]["full_contract"]
        command = summary["arms"]["command_only_route"]
        learned_full = summary["arms"]["navsim_ego_status_mlp_full_contract"]
        learned_command = summary["arms"][
            "navsim_ego_status_mlp_command_only_route"
        ]
        self.assertEqual(60, full["drive_calls"])
        self.assertEqual(60, full["finite_drive_outputs"])
        self.assertEqual(60, full["nonstationary_drive_outputs"])
        self.assertEqual([], full["diagnostic_codes"])
        self.assertEqual(60, command["drive_calls"])
        self.assertEqual(60, command["finite_drive_outputs"])
        self.assertEqual(60, command["nonstationary_drive_outputs"])
        self.assertEqual(["semantic.command_only"], command["diagnostic_codes"])
        self.assertLess(full["drive_rpc_latency_ms"]["p95"], 100.0)
        self.assertLess(command["drive_rpc_latency_ms"]["p95"], 100.0)
        self.assertEqual("navsim_ego_status_mlp", learned_full["model"])
        self.assertEqual(60, learned_full["drive_calls"])
        self.assertEqual(60, learned_full["finite_drive_outputs"])
        self.assertEqual(60, learned_full["nonstationary_drive_outputs"])
        self.assertEqual([], learned_full["diagnostic_codes"])
        self.assertEqual("navsim_ego_status_mlp", learned_command["model"])
        self.assertEqual(60, learned_command["drive_calls"])
        self.assertEqual(60, learned_command["finite_drive_outputs"])
        self.assertEqual(60, learned_command["nonstationary_drive_outputs"])
        self.assertEqual([], learned_command["diagnostic_codes"])
        self.assertLess(learned_full["drive_rpc_latency_ms"]["p95"], 100.0)
        self.assertLess(learned_command["drive_rpc_latency_ms"]["p95"], 100.0)
        route_divergence = summary["trajectory_divergence"]["route_following"]
        learned_divergence = summary["trajectory_divergence"][
            "navsim_ego_status_mlp"
        ]
        self.assertEqual(60, route_divergence["paired_calls"])
        self.assertEqual(56, route_divergence["endpoint_difference_gt_0_1m"])
        self.assertEqual(22, route_divergence["endpoint_difference_gt_1m"])
        self.assertEqual(47, route_divergence["endpoint_difference_max_drive_index"])
        self.assertEqual(60, learned_divergence["paired_calls"])
        self.assertEqual(0, learned_divergence["endpoint_difference_gt_0_1m"])
        self.assertEqual(0.0, learned_divergence["endpoint_difference_max_m"])

    def test_navsim_reactive_summary_revalidates_tracked_evidence(self) -> None:
        module = _load_module()

        summary = module._navsim_reactive_summary(
            ROOT / "artifacts" / "external" / "alpasim_navsim_reactive_rollout"
        )

        self.assertTrue(summary["available"])
        self.assertEqual(1, summary["rollouts"])
        self.assertEqual(1, summary["passed_rollouts"])
        self.assertEqual(197, summary["drive_rpc_count"])
        self.assertEqual(197, summary["finite_drive_outputs"])
        self.assertEqual(198, summary["camera_event_count"])
        self.assertEqual(198, summary["render_call_count"])
        self.assertAlmostEqual(
            3.3624532,
            summary["internal_driver_latency_ms"]["p95"],
        )
        self.assertEqual(
            "recorded_seed_frame_replay",
            summary["renderer"]["camera_contract"],
        )
        self.assertEqual(
            4,
            summary["negative_control"]["drive_calls_before_rejection"],
        )
        self.assertEqual(
            1.0,
            summary["behavior_metrics_not_used_as_policy_quality_claims"]["wrong_lane"],
        )

    def test_release_scope_separates_public_core_from_gated_extensions(self) -> None:
        module = _load_module()
        rows = [
            {
                **_row(),
                "run_id": "core-constant",
                "policy": "constant_velocity",
                "status": "completed",
                "attempted": "true",
                "completed": "true",
            },
            {
                **_row(),
                "run_id": "core-route",
                "policy": "route_following",
                "status": "completed",
                "attempted": "true",
                "completed": "true",
            },
            {
                **_row(),
                "run_id": "core-direct",
                "policy": "direct_actor_planner",
                "status": "blocked",
                "blocked": "true",
                "failure_layer": "deployment",
                "failure_code": "direct_actor_oracle_proxy_missing",
            },
        ]
        evidence = [
            {"run_id": "core-constant", "matrix": "core", "policy": "constant_velocity", "audit_valid": "true"},
            {"run_id": "core-route", "matrix": "core", "policy": "route_following", "audit_valid": "true"},
        ]

        summary = module._release_scope_summary(rows, evidence)

        self.assertEqual(2, summary["public_core_configured_rows"])
        self.assertEqual(2, summary["public_core_completed_runs"])
        self.assertEqual(2, summary["public_core_audit_valid_runs"])
        self.assertEqual(0, summary["public_core_blocked_rows"])
        self.assertEqual(1, summary["optional_gated_configured_rows"])
        self.assertEqual(1, summary["optional_gated_blocked_rows"])
        self.assertEqual(1, summary["direct_actor_blocked_rows"])

    def test_scenario_coverage_requires_authoritative_category_metadata(self) -> None:
        module = _load_module()
        evidence = [
            {
                "run_id": "scene-a-run",
                "scene_id": "scene-a",
                "scenario_category": "available_front_camera_26_02_unclassified",
                "categories_verified": "false",
            },
            {
                "run_id": "scene-b-run",
                "scene_id": "scene-b",
                "scenario_category": "intersection",
                "categories_verified": "true",
            },
        ]

        summary = module._scenario_coverage_summary(evidence)

        self.assertEqual(2, summary["closed_loop_scene_count"])
        self.assertEqual(6, summary["required_category_count"])
        self.assertEqual(1, summary["verified_required_category_count"])
        self.assertEqual(1, summary["unclassified_closed_loop_scene_count"])
        self.assertFalse(summary["scenario_category_coverage_claimed"])
        self.assertEqual(0, summary["scenario_category_coverage_claimed_int"])

    def test_empty_frames_csv_keeps_public_frame_schema(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"

            module._write_empty_frames(path)
            with path.open(newline="", encoding="utf-8") as handle:
                header = next(csv.reader(handle))

        self.assertEqual(list(module.FRAME_FIELDS), header)
        self.assertIn("camera_count", header)
        self.assertIn("route_waypoint_count", header)
        self.assertIn("end_to_end_action_latency_ms", header)
        self.assertIn("policy_reasoning_status_code", header)

    def test_closed_loop_evidence_uses_public_fallback_without_raw_run_dir(self) -> None:
        module = _load_module()
        row = {
            **_row(),
            "run_id": "core_constant_velocity_scene-a_17_full_contract",
            "status": "completed",
            "attempted": "true",
            "completed": "true",
            "_source": "artifacts/cvm/results/core/runs.csv",
        }
        fallback = {
            row["run_id"]: {
                "run_id": row["run_id"],
                "matrix": "core",
                "policy": "constant_velocity",
                "scene_id": "scene-a",
                "seed": "17",
                "adapter_config": "full_contract",
                "audit_valid": "true",
                "route_contract_ok": "true",
                "sensor_pipeline_ok": "true",
                "metrics_present": "true",
                "progress": "0.4",
                "collision_any": "0",
                "offroad": "0",
            }
        }

        evidence = module._closed_loop_evidence([row], fallback_rows=fallback)

        self.assertEqual("true", evidence[0]["audit_valid"])
        self.assertEqual("true", evidence[0]["metrics_present"])
        self.assertEqual("0.4", evidence[0]["progress"])

    def test_core_policy_results_include_latency_and_terminal_crashes(self) -> None:
        module = _load_module()
        completed = {
            **_row(),
            "run_id": "core_constant_velocity_scene-a_17_full_contract",
            "status": "completed",
            "attempted": "true",
            "completed": "true",
        }
        crashed = {
            **_row(),
            "run_id": "core_constant_velocity_scene-b_17_full_contract",
            "status": "failed",
            "attempted": "true",
            "failure_layer": "lifecycle",
            "failure_code": "service_crash",
            "detail": "external driver crashed",
        }
        evidence = [
            {
                "run_id": completed["run_id"],
                "matrix": "core",
                "policy": "constant_velocity",
                "metrics_present": "true",
                "progress": "0.4",
                "collision_any": "0",
                "offroad": "0",
                "action_latency_p95_ms": "12.5",
            }
        ]

        results = module._core_policy_results([completed, crashed], evidence)

        self.assertEqual(1, len(results))
        self.assertEqual(12.5, results[0]["action_latency_p95_ms"])
        self.assertEqual(1, results[0]["service_crash_rows"])


if __name__ == "__main__":
    unittest.main()
