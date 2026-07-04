from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_alpasignal_bridge.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_alpasignal_bridge", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuditAlpaSignalBridgeTests(unittest.TestCase):
    def test_report_validates_signal_bridge_cases(self) -> None:
        module = _load_module()

        report = module.build_report()

        self.assertTrue(report["valid"])
        self.assertEqual("alpasignal_bridge_audit_v1", report["schema"])
        self.assertEqual(3, len(report["cases"]))
        self.assertTrue(report["gates"]["structured_hazard_consumed"])
        self.assertTrue(report["gates"]["moving_hazard_preserved_as_actor"])
        self.assertTrue(report["gates"]["low_visibility_adds_caution_zone"])

    def test_main_writes_report(self) -> None:
        module = _load_module()
        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "alpasignal_bridge_audit.json"

            subprocess.run(
                [sys.executable, str(SCRIPT), "--output", str(output)],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
