from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class PluginDependencyBoundaryTests(unittest.TestCase):
    def test_plugin_base_model_contract_imports_without_optional_backends(self) -> None:
        result = _run_python(
            """
            import importlib.abc
            import json
            import sys

            BLOCKED_ROOTS = {"alpasim_driver", "torch", "tensorflow", "jax"}

            class OptionalBackendBlocker(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname.split(".", 1)[0] in BLOCKED_ROOTS:
                        raise ModuleNotFoundError(f"blocked optional backend: {fullname}")
                    return None

            sys.meta_path.insert(0, OptionalBackendBlocker())

            from wod2sim.simulator.alpasim_contract import (
                BaseTrajectoryModel,
                DriveCommand,
                ModelPrediction,
            )
            from wod2sim.simulator.baseline_drivers import (
                ConstantVelocityAlpaSimModel,
                RouteFollowingAlpaSimModel,
            )
            from wod2sim.simulator.alpasim_direct_actor_planner import (
                DirectActorPlannerAlpaSimModel,
            )

            blocked_loaded = sorted(
                name for name in sys.modules if name.split(".", 1)[0] in BLOCKED_ROOTS
            )
            print(json.dumps({
                "base": BaseTrajectoryModel.__name__,
                "command_straight": DriveCommand.STRAIGHT,
                "prediction": ModelPrediction.__name__,
                "models": sorted([
                    ConstantVelocityAlpaSimModel.__name__,
                    RouteFollowingAlpaSimModel.__name__,
                    DirectActorPlannerAlpaSimModel.__name__,
                ]),
                "blocked_loaded": blocked_loaded,
            }, sort_keys=True))
            """
        )
        payload = json.loads(result.stdout)

        self.assertEqual("BaseTrajectoryModel", payload["base"])
        self.assertEqual("ModelPrediction", payload["prediction"])
        self.assertEqual(
            [
                "ConstantVelocityAlpaSimModel",
                "DirectActorPlannerAlpaSimModel",
                "RouteFollowingAlpaSimModel",
            ],
            payload["models"],
        )
        self.assertEqual([], payload["blocked_loaded"])

    def test_plugin_unselected_alpamayo_or_vam_is_not_imported(self) -> None:
        result = _run_python(
            """
            import importlib.abc
            import json
            import sys

            class OptionalAlpaSimModelBlocker(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    lowered = fullname.lower()
                    if "alpamayo" in lowered or ".vam" in lowered or lowered.startswith("vam"):
                        raise ModuleNotFoundError(f"blocked unselected AlpaSim model: {fullname}")
                    return None

            sys.meta_path.insert(0, OptionalAlpaSimModelBlocker())

            from wod2sim.simulator.baseline_drivers import (
                ConstantVelocityAlpaSimModel,
                RouteFollowingAlpaSimModel,
            )
            from wod2sim.simulator.alpasim_direct_actor_planner import (
                DirectActorPlannerAlpaSimModel,
            )

            leaked = sorted(
                name for name in sys.modules
                if "alpamayo" in name.lower()
                or ".vam" in name.lower()
                or name.lower().startswith("vam")
            )
            print(json.dumps({
                "loaded_wod2sim_models": [
                    ConstantVelocityAlpaSimModel.__name__,
                    RouteFollowingAlpaSimModel.__name__,
                    DirectActorPlannerAlpaSimModel.__name__,
                ],
                "unselected_loaded": leaked,
            }, sort_keys=True))
            """
        )
        payload = json.loads(result.stdout)

        self.assertEqual(
            [
                "ConstantVelocityAlpaSimModel",
                "RouteFollowingAlpaSimModel",
                "DirectActorPlannerAlpaSimModel",
            ],
            payload["loaded_wod2sim_models"],
        )
        self.assertEqual([], payload["unselected_loaded"])

    def test_plugin_missing_optional_backend_has_actionable_error(self) -> None:
        result = _run_python(
            """
            import importlib.abc
            import json
            import sys

            class TorchBlocker(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname.split(".", 1)[0] == "torch":
                        raise ModuleNotFoundError(f"blocked optional backend: {fullname}")
                    return None

            sys.meta_path.insert(0, TorchBlocker())

            from wod2sim.simulator.alpasim_token_bc import TokenBCAlpaSimModel

            try:
                TokenBCAlpaSimModel("missing-token-bc-checkpoint.pt", device="cpu")
            except ImportError as exc:
                print(json.dumps({"error": str(exc)}, sort_keys=True))
            else:
                raise AssertionError("TokenBCAlpaSimModel unexpectedly loaded without torch")
            """
        )
        payload = json.loads(result.stdout)

        self.assertIn("requires torch", payload["error"])
        self.assertIn("alpasim extra", payload["error"])


def _run_python(source: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{SRC}{os.pathsep}{env.get('PYTHONPATH', '')}"
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            "subprocess failed\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


if __name__ == "__main__":
    unittest.main()
