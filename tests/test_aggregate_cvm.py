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
        self.assertEqual(0, summary["policy_behavior_attributable_rows"])
        self.assertEqual(0, summary["policy_failure_attributable_rows"])
        self.assertEqual(1, summary["integration_failure_attributable_rows"])
        self.assertEqual(3, summary["diagnostic_not_policy_rows"])
        self.assertEqual(4, summary["non_policy_attributed_rows"])

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


if __name__ == "__main__":
    unittest.main()
