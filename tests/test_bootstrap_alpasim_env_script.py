from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bootstrap_alpasim_env.sh"


class BootstrapAlpaSimEnvScriptTests(unittest.TestCase):
    def test_script_can_fallback_to_stdlib_venv_when_uv_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp) / "repo"
            scripts_dir = temp_root / "scripts"
            fake_bin = Path(tmp) / "fake-bin"
            fake_bin.mkdir(parents=True)
            scripts_dir.mkdir(parents=True)

            shutil.copy2(SCRIPT, scripts_dir / "bootstrap_alpasim_env.sh")
            (temp_root / ".uv-cache").mkdir()

            setup_stub = scripts_dir / "setup_alpasim_local_plugin.py"
            setup_stub.write_text("raise SystemExit(0)\n", encoding="utf-8")

            fake_venv_python = Path(tmp) / "fake-venv-python"
            fake_venv_python.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    log_file="${LOG_FILE:?}"
                    if [[ "${1:-}" == "-m" && "${2:-}" == "pip" && "${3:-}" == "--version" ]]; then
                      printf '%s\\n' "$*" >>"$log_file"
                      exit 1
                    fi
                    printf '%s\\n' "$*" >>"$log_file"
                    exit 0
                    """
                ),
                encoding="utf-8",
            )
            fake_venv_python.chmod(0o755)

            python_wrapper = fake_bin / "python3"
            python_wrapper.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    log_file="${LOG_FILE:?}"
                    fake_venv_python="${FAKE_VENV_PYTHON:?}"
                    if [[ "${1:-}" == "-m" && "${2:-}" == "venv" ]]; then
                      venv_root="${3:?}"
                      mkdir -p "$venv_root/bin"
                      cp "$fake_venv_python" "$venv_root/bin/python"
                      chmod +x "$venv_root/bin/python"
                      printf '%s\\n' "$*" >>"$log_file"
                      exit 0
                    fi
                    printf '%s\\n' "$*" >>"$log_file"
                    exit 0
                    """
                ),
                encoding="utf-8",
            )
            python_wrapper.chmod(0o755)

            log_file = Path(tmp) / "python-calls.log"
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:/usr/bin:/bin"
            env["LOG_FILE"] = str(log_file)
            env["FAKE_VENV_PYTHON"] = str(fake_venv_python)
            env["PYTHON_BIN"] = "python3"
            env["ALPASIM_ROOT"] = str(temp_root / "workspace" / "alpasim-missing")

            subprocess.run(
                ["bash", str(scripts_dir / "bootstrap_alpasim_env.sh")],
                cwd=temp_root,
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            calls = log_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual("-m venv " + str(temp_root / ".venv"), calls[0])
            self.assertIn("-m pip --version", calls[1])
            self.assertIn("-m ensurepip --upgrade", calls[2])
            self.assertIn("-m pip install --upgrade pip", calls[3])
            self.assertIn("-m pip install -e " + str(temp_root) + "[alpasim]", calls[4])
            self.assertIn("torch==2.11.0+cu129", calls[5])


if __name__ == "__main__":
    unittest.main()
