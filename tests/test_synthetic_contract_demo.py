from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_synthetic_contract_demo.py"
VOLATILE_TIMESTAMP_KEYS = {"generated_at", "completed_at"}


def _load_script_module():
    spec = importlib.util.spec_from_file_location("alpabridge_synthetic_contract_demo", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AlpaBridgeSyntheticContractDemoTests(unittest.TestCase):
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
                bundle_text = "\n".join(
                    archive.extractfile(name).read().decode("utf-8")
                    for name in sorted(names)
                    if name.endswith(".json")
                )
            self.assertIn("demo-run_support_bundle/run-audit.json", names)
            self.assertIn("demo-run_support_bundle/aggregate/synthetic-contract-metrics.json", names)
            self.assertIn("demo-run_support_bundle/driver/baseline-log.jsonl", names)
            public_json = "\n".join(
                path.read_text(encoding="utf-8")
                for path in sorted(output.rglob("*.json"))
            )
            self.assertNotIn(str(ROOT), public_json)
            self.assertNotIn(str(ROOT), bundle_text)

    def test_generate_demo_is_stable_after_normalizing_intentional_volatility(self) -> None:
        module = _load_script_module()
        with TemporaryDirectory() as left_tmp, TemporaryDirectory() as right_tmp:
            left_root = Path(left_tmp)
            right_root = Path(right_tmp)
            left_output = left_root / "demo-run"
            right_output = right_root / "demo-run"

            module.generate_demo(output=left_output)
            module.generate_demo(output=right_output)

            self.assertEqual(
                _normalized_demo_tree(left_output, volatile_root=left_root),
                _normalized_demo_tree(right_output, volatile_root=right_root),
            )

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


def _normalized_demo_tree(output: Path, *, volatile_root: Path) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for path in sorted(item for item in output.rglob("*") if item.is_file()):
        relative = path.relative_to(output).as_posix()
        if relative == "support-bundle.tar.gz":
            files[relative] = _normalized_archive(path, volatile_root=volatile_root)
        elif path.suffix == ".json":
            files[relative] = _normalize_json(
                json.loads(path.read_text(encoding="utf-8")),
                volatile_root=volatile_root,
            )
        else:
            files[relative] = _normalize_text(path.read_text(encoding="utf-8"), volatile_root)
    return files


def _normalized_archive(path: Path, *, volatile_root: Path) -> dict[str, Any]:
    entries: dict[str, Any] = {}
    with tarfile.open(path, "r:gz") as archive:
        for member in sorted(archive.getmembers(), key=lambda item: item.name):
            if member.isdir():
                entries[member.name] = {
                    "type": "dir",
                    "mode": member.mode,
                    "mtime": member.mtime,
                    "uid": member.uid,
                    "gid": member.gid,
                }
                continue
            extracted = archive.extractfile(member)
            assert extracted is not None
            raw = extracted.read()
            if member.name.endswith(".json"):
                content: Any = _normalize_json(json.loads(raw.decode("utf-8")), volatile_root=volatile_root)
            else:
                content = _normalize_text(raw.decode("utf-8"), volatile_root)
            entries[member.name] = {
                "type": "file",
                "mode": member.mode,
                "mtime": member.mtime,
                "uid": member.uid,
                "gid": member.gid,
                "content": content,
            }
    return entries


def _normalize_json(value: Any, *, volatile_root: Path, key: str | None = None) -> Any:
    if key in VOLATILE_TIMESTAMP_KEYS:
        return "<timestamp>"
    if isinstance(value, dict):
        return {
            item_key: _normalize_json(item_value, volatile_root=volatile_root, key=item_key)
            for item_key, item_value in sorted(value.items())
        }
    if isinstance(value, list):
        return [_normalize_json(item, volatile_root=volatile_root) for item in value]
    if isinstance(value, str):
        return _normalize_text(value, volatile_root)
    return value


def _normalize_text(value: str, volatile_root: Path) -> str:
    return value.replace(str(volatile_root), "<tmp>")


if __name__ == "__main__":
    unittest.main()
