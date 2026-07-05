from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release_bootstrap_smoke.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("release_bootstrap_smoke", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseBootstrapSmokeTests(unittest.TestCase):
    def test_resolve_installer_prefers_uv_when_available(self) -> None:
        module = _load_module()
        with patch.object(module.shutil, "which", return_value="/usr/bin/uv"):
            self.assertEqual("uv", module._resolve_installer("auto"))

    def test_resolve_installer_falls_back_to_stdlib_venv(self) -> None:
        module = _load_module()
        with patch.object(module.shutil, "which", return_value=None):
            self.assertEqual("venv", module._resolve_installer("auto"))

    def test_bootstrap_install_steps_for_uv_backend(self) -> None:
        module = _load_module()
        steps = module._bootstrap_install_steps(
            checkout_root=ROOT,
            venv_root=Path("/tmp/bootstrap-venv"),
            installer="uv",
        )

        self.assertEqual("uv_venv", steps[0][0])
        self.assertEqual(["uv", "venv", "/tmp/bootstrap-venv"], steps[0][1])
        self.assertEqual(
            [
                "uv",
                "pip",
                "install",
                "--python",
                "/tmp/bootstrap-venv/bin/python",
                "-e",
                ".[dev]",
            ],
            steps[1][1],
        )

    def test_bootstrap_install_steps_for_stdlib_venv_backend(self) -> None:
        module = _load_module()
        steps = module._bootstrap_install_steps(
            checkout_root=ROOT,
            venv_root=Path("/tmp/bootstrap-venv"),
            installer="venv",
        )

        self.assertEqual(
            [sys.executable, "-m", "venv", "/tmp/bootstrap-venv"],
            steps[0][1],
        )
        self.assertEqual(
            [
                "/tmp/bootstrap-venv/bin/python",
                "-m",
                "ensurepip",
                "--upgrade",
            ],
            steps[1][1],
        )
        self.assertEqual(
            [
                "/tmp/bootstrap-venv/bin/python",
                "-m",
                "pip",
                "install",
                "--upgrade",
                "pip",
            ],
            steps[2][1],
        )
        self.assertEqual(
            [
                "/tmp/bootstrap-venv/bin/python",
                "-m",
                "pip",
                "install",
                "-e",
                ".[dev]",
            ],
            steps[3][1],
        )


if __name__ == "__main__":
    unittest.main()
