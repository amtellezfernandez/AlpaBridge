from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_synthetic_contract_demo.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("wod2sim_synthetic_contract_demo", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WOD2SimSyntheticContractDemoTests(unittest.TestCase):
    def test_generate_demo_writes_audited_public_artifacts(self) -> None:
        module = _load_script_module()
        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "demo-run"

            summary = module.generate_demo(output=output)

            self.assertTrue(summary["artifact_valid"])
            self.assertFalse(summary["benchmark_claim"])
            self.assertFalse(summary["valid_claim_evidence"])
            self.assertTrue((output / "synthetic-rollout.svg").is_file())
            self.assertTrue((output / "support-bundle.tar.gz").is_file())
            self.assertTrue((output / "support-bundle-report.json").is_file())

            audit = json.loads((output / "run-audit.json").read_text(encoding="utf-8"))
            self.assertTrue(audit["valid"])
            self.assertTrue(audit["route_contract_ok"])
            self.assertEqual({"alpasim_waypoints": 8}, audit["route_source_counts"])

            metrics = json.loads(
                (output / "aggregate" / "synthetic-contract-metrics.json").read_text(encoding="utf-8")
            )
            self.assertEqual("wod2sim_synthetic_contract_metrics_v1", metrics["schema"])
            self.assertFalse(metrics["benchmark_claim"])
            self.assertIsNone(metrics["policy_quality_metrics"])
            self.assertTrue(metrics["route_contract_ok"])
            diagnostics = metrics["contract_diagnostics"]
            self.assertEqual("wod2sim_synthetic_contract_diagnostics_v1", diagnostics["schema"])
            self.assertFalse(diagnostics["benchmark_claim"])
            self.assertEqual(8, diagnostics["sample_count"])
            self.assertEqual(
                1.312,
                diagnostics["route_command_information_loss"]["same_x_lateral_rmse_m"],
            )
            self.assertEqual(
                4.508,
                diagnostics["road_center_vs_ego_route"]["mean_abs_lateral_offset_m"],
            )
            self.assertIn("samples", diagnostics)

            rows = [
                json.loads(line)
                for line in (output / "driver" / "baseline-log.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(8, len(rows))
            self.assertTrue(all(row["route_source"] == "alpasim_waypoints" for row in rows))
            self.assertTrue(
                all(row["alpasim_signal"]["route_source"] == "alpasim_waypoints" for row in rows)
            )

            with tarfile.open(output / "support-bundle.tar.gz", "r:gz") as archive:
                names = set(archive.getnames())
            self.assertIn("demo-run_support_bundle/run-audit.json", names)
            self.assertIn("demo-run_support_bundle/aggregate/synthetic-contract-metrics.json", names)
            self.assertIn("demo-run_support_bundle/driver/baseline-log.jsonl", names)

    def test_script_prints_json_summary(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "demo-run"

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--output", str(output), "--json"],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            payload = json.loads(result.stdout)
            self.assertEqual("wod2sim_synthetic_contract_demo_v1", payload["schema"])
            self.assertTrue(payload["artifact_valid"])
            self.assertFalse(payload["valid_claim_evidence"])
            self.assertEqual(1.312, payload["contract_diagnostics"]["route_command_lateral_rmse_m"])
            self.assertEqual(4.508, payload["contract_diagnostics"]["road_center_mean_abs_lateral_offset_m"])
            self.assertTrue((output / "demo-summary.json").is_file())


if __name__ == "__main__":
    unittest.main()
