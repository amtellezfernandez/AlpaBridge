from __future__ import annotations

import argparse
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ReproduceClosedLoopTests(unittest.TestCase):
    def test_build_plan_uses_closed_loop_launch_and_evidence_steps(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.reproduce_closed_loop")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            checkpoint = root / "token_dagger_bc.pt"
            checkpoint.write_text("placeholder\n", encoding="utf-8")
            args = argparse.Namespace(
                skip_setup=False,
                alpasim_root=root / "alpasim",
                model="token_dagger_bc",
                checkpoint=checkpoint,
                oracle_actor_proxy=None,
                scene_preset="fresh_3scene",
                scene_id=["scene-a"],
                run_dir=root / "run",
                runs_root=root / "runs",
                evidence_dir=root / "evidence",
                topology="1gpu",
                timeout=120,
                baseport=6000,
                port=6789,
                driver_warmup_seconds=0.1,
                wizard_arg=["wizard.timeout=120"],
            )

            plan = module.build_plan(args)

        self.assertEqual(
            ["setup", "ready", "launch_closed_loop", "audit_run", "support_bundle"],
            [step["name"] for step in plan],
        )
        launch = next(step for step in plan if step["name"] == "launch_closed_loop")
        self.assertIn("--mode", launch["command"])
        self.assertEqual("both", launch["command"][launch["command"].index("--mode") + 1])
        self.assertIn("--checkpoint", launch["command"])
        self.assertIn("--scene-id", launch["command"])
        audit = next(step for step in plan if step["name"] == "audit_run")
        self.assertIn("--audit-dir", audit["command"])
        bundle = next(step for step in plan if step["name"] == "support_bundle")
        self.assertTrue(any(item.endswith("support-bundle.tar.gz") for item in bundle["command"]))

    def test_dry_run_writes_manifest_without_private_assets(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.reproduce_closed_loop")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            run_dir = root / "run"
            evidence_dir = root / "evidence"
            argv = [
                "wod2sim-reproduce",
                "--alpasim-root",
                str(root / "missing-alpasim"),
                "--scene-id",
                "scene-a",
                "--run-dir",
                str(run_dir),
                "--evidence-dir",
                str(evidence_dir),
            ]
            with patch.object(sys, "argv", argv):
                returncode = module.main()

            manifest_path = evidence_dir / "closed-loop-reproduction-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(0, returncode)
        self.assertEqual("planned", manifest["status"])
        self.assertFalse(manifest["valid_claim_evidence"])
        self.assertEqual("plan", manifest["mode"])
        self.assertEqual(["scene-a"], manifest["scene_ids"])
        self.assertIn("claim_boundary", manifest)
        self.assertEqual([], manifest["executed_steps"])
