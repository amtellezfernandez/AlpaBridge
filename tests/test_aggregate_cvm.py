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


if __name__ == "__main__":
    unittest.main()
