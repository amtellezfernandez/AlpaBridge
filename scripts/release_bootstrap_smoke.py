#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
IGNORE_DIR_NAMES = {
    ".git",
    ".pytest_cache",
    ".venv",
    ".uv-cache",
    "build",
    "dist",
    "__pycache__",
}
IGNORE_SUFFIXES = {".pyc", ".pyo"}
IGNORE_FILE_NAMES = {".DS_Store"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Copy the current repo into a temporary checkout, install it into a fresh venv, "
            "and run the public non-AlpaSim bootstrap checks."
        )
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=ROOT,
        help="Repo root to copy into the temporary bootstrap checkout.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON report output path.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the temporary checkout on disk for debugging.",
    )
    parser.add_argument(
        "--installer",
        choices=("auto", "uv", "venv"),
        default="auto",
        help="Installer backend for the temporary bootstrap environment.",
    )
    return parser.parse_args()


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _ignore_repo_junk(_directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        path = Path(name)
        if name in IGNORE_DIR_NAMES or name in IGNORE_FILE_NAMES:
            ignored.add(name)
            continue
        if any(part in IGNORE_DIR_NAMES for part in path.parts):
            ignored.add(name)
            continue
        if path.suffix in IGNORE_SUFFIXES:
            ignored.add(name)
            continue
        if name.endswith(".egg-info"):
            ignored.add(name)
    return ignored


def _copy_checkout(source_root: Path, destination_root: Path) -> Path:
    checkout_root = destination_root / "checkout"
    shutil.copytree(source_root, checkout_root, ignore=_ignore_repo_junk)
    return checkout_root


def _step(name: str, command: list[str], *, cwd: Path) -> dict[str, Any]:
    try:
        result = _run(command, cwd=cwd)
    except FileNotFoundError as exc:
        return {
            "name": name,
            "command": command,
            "cwd": str(cwd),
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc),
            "ok": False,
        }
    return {
        "name": name,
        "command": command,
        "cwd": str(cwd),
        "returncode": int(result.returncode),
        "stdout": result.stdout,
        "stderr": result.stderr,
        "ok": result.returncode == 0,
    }


def _doctor_summary(report_path: Path) -> dict[str, Any]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        "valid": bool(payload["valid"]),
        "public_models": list(payload["public_models"]),
        "public_model_registry_curated": bool(payload["checks"]["public_model_registry_curated"]),
        "release_surface_mode": payload["release_surface_mode"],
    }


def _resolve_installer(installer: str) -> str:
    if installer != "auto":
        return installer
    return "uv" if shutil.which("uv") else "venv"


def _bootstrap_install_steps(*, checkout_root: Path, venv_root: Path, installer: str) -> list[tuple[str, list[str]]]:
    venv_python = venv_root / "bin" / "python"
    if installer == "uv":
        return [
            ("uv_venv", ["uv", "venv", str(venv_root)]),
            ("editable_install", ["uv", "pip", "install", "--python", str(venv_python), "-e", ".[dev]"]),
        ]
    return [
        ("stdlib_venv", [sys.executable, "-m", "venv", str(venv_root)]),
        ("ensurepip", [str(venv_python), "-m", "ensurepip", "--upgrade"]),
        ("pip_upgrade", [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"]),
        ("editable_install", [str(venv_python), "-m", "pip", "install", "-e", ".[dev]"]),
    ]


def run_release_bootstrap_smoke(*, source_root: Path, keep_temp: bool, installer: str = "auto") -> dict[str, Any]:
    source_root = source_root.resolve()
    if not (source_root / "pyproject.toml").is_file():
        raise FileNotFoundError(f"Not a repo root: {source_root}")

    installer_backend = _resolve_installer(installer)
    temp_dir = tempfile.mkdtemp(prefix="wod2sim-bootstrap-")
    temp_root = Path(temp_dir)
    checkout_root = _copy_checkout(source_root, temp_root)
    venv_root = temp_root / "venv"
    venv_python = venv_root / "bin" / "python"
    venv_bin = venv_root / "bin"
    doctor_json = checkout_root / "bootstrap-doctor.json"
    source_doctor_json = checkout_root / "bootstrap-doctor-source.json"
    audit_json = checkout_root / "bootstrap-audit.json"
    batch_dir = checkout_root / "bootstrap-batch"
    reproduce_dir = checkout_root / "bootstrap-reproduce"

    step_specs = [
        *_bootstrap_install_steps(
            checkout_root=checkout_root,
            venv_root=venv_root,
            installer=installer_backend,
        ),
        (
            "installed_doctor",
            [
                str(venv_bin / "wod2sim-doctor"),
                "--strict-installed",
                "--json",
                "--output",
                str(doctor_json),
            ],
        ),
        (
            "source_doctor_wrapper",
            [
                str(venv_python),
                "scripts/wod2sim_doctor.py",
                "--json",
                "--output",
                str(source_doctor_json),
            ],
        ),
        ("launch_help", [str(venv_bin / "wod2sim-launch"), "--help"]),
        ("setup_help", [str(venv_bin / "wod2sim-setup"), "--help"]),
        ("ready_help", [str(venv_bin / "wod2sim-ready"), "--help"]),
        ("oracle_proxy_help", [str(venv_bin / "wod2sim-build-oracle-proxy"), "--help"]),
        ("audit_run_help", [str(venv_bin / "wod2sim-audit-run"), "--help"]),
        ("support_bundle_help", [str(venv_bin / "wod2sim-support-bundle"), "--help"]),
        ("reproduce_help", [str(venv_bin / "wod2sim-reproduce"), "--help"]),
        (
            "reproduce_plan",
            [
                str(venv_bin / "wod2sim-reproduce"),
                "--scene-id",
                "bootstrap-scene",
                "--run-dir",
                str(reproduce_dir / "run"),
                "--evidence-dir",
                str(reproduce_dir / "evidence"),
            ],
        ),
        ("audit_signal", [str(venv_bin / "wod2sim-audit-signal"), "--output", str(audit_json)]),
        (
            "batch_print",
            [
                str(venv_bin / "wod2sim-batch"),
                "--mode",
                "print",
                "--model",
                "spotlight_reflex",
                "--scene-limit",
                "1",
                "--batch-dir",
                str(batch_dir),
            ],
        ),
    ]

    ok = True
    completed_steps: list[dict[str, Any]] = []
    for name, command in step_specs:
        step = _step(name, command, cwd=checkout_root)
        completed_steps.append(step)
        if not step["ok"]:
            ok = False
            break

    installed_summary = None
    source_summary = None
    artifacts = {
        "doctor_json": str(doctor_json),
        "source_doctor_json": str(source_doctor_json),
        "audit_json": str(audit_json),
        "batch_dir": str(batch_dir),
        "reproduce_manifest": str(
            reproduce_dir / "evidence" / "closed-loop-reproduction-manifest.json"
        ),
    }
    if ok:
        installed_summary = _doctor_summary(doctor_json)
        source_summary = _doctor_summary(source_doctor_json)
        ok = bool(
            installed_summary["valid"]
            and source_summary["valid"]
            and installed_summary["public_models"] == ["spotlight_reflex", "token_dagger_bc", "direct_actor_planner"]
            and source_summary["public_models"] == ["spotlight_reflex", "token_dagger_bc", "direct_actor_planner"]
            and installed_summary["public_model_registry_curated"]
            and source_summary["public_model_registry_curated"]
            and audit_json.is_file()
            and (reproduce_dir / "evidence" / "closed-loop-reproduction-manifest.json").is_file()
            and (batch_dir / "batch-status.json").is_file()
        )

    report = {
        "schema": "wod2sim_release_bootstrap_smoke_v1",
        "valid": ok,
        "installer_backend": installer_backend,
        "source_root": str(source_root),
        "temp_root": str(temp_root),
        "checkout_root": str(checkout_root),
        "artifacts": artifacts,
        "installed_doctor": installed_summary,
        "source_doctor": source_summary,
        "steps": completed_steps,
    }

    if not keep_temp:
        shutil.rmtree(temp_root)
        report["temp_root"] = None
        report["checkout_root"] = None
    return report


def main() -> int:
    args = _parse_args()
    report = run_release_bootstrap_smoke(
        source_root=args.source_root,
        keep_temp=bool(args.keep_temp),
        installer=str(args.installer),
    )
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
