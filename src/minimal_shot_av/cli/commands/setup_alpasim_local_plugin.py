from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from shutil import which
import shutil


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ALPASIM_ROOT = ROOT / "workspace" / "alpasim"
ALPASIM_OVERRIDE_ROOT = ROOT / "third_party" / "alpasim_overrides"
REQUIRED_MODELS = ("spotlight_reflex", "token_dagger_bc", "direct_actor_planner")
TORCH_PACKAGE = "torch==2.11.0+cu129"
TORCH_INDEX_URL = "https://download.pytorch.org/whl/cu129"
ALPASIM_CORE_DEPENDENCIES = (
    "PyYAML>=6",
    "aiofiles",
    "GitPython",
    "boto3",
    "click",
    "csaps",
    "dataclasses-json>=0.6.7",
    "filelock",
    "grpcio",
    "grpcio-tools",
    "huggingface_hub",
    "hydra-core",
    "imageio[ffmpeg]",
    "matplotlib",
    "numpy",
    "omegaconf",
    "opencv-python-headless",
    "pandas",
    "pandas-stubs",
    "pillow",
    "polars>=1.0.0",
    "protobuf>=4.0.0,<5.0.0",
    "pyarrow",
    "pygame>=2.5.0",
    "pytest",
    "pytest-asyncio",
    "rich",
    "scipy",
    "setuptools<82",
    "tqdm",
    "types-PyYAML",
    "typing-extensions",
)
ALPASIM_EDITABLE_PACKAGES = (
    "src/plugins",
    "src/grpc",
    "src/utils_rs",
    "src/utils",
    "src/driver",
    "src/wizard",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install this repo into the local AlpaSim driver env and verify plugin discovery."
    )
    parser.add_argument(
        "--alpasim-root",
        type=Path,
        default=None,
        help="AlpaSim checkout root. Defaults to $ALPASIM_ROOT or ./workspace/alpasim.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Skip installation and only verify the current AlpaSim driver registry.",
    )
    parser.add_argument(
        "--skip-overrides",
        action="store_true",
        help="Do not copy repo-tracked AlpaSim override files into ALPASIM_ROOT before checking.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    uv_bin = _require_uv()
    alpasim_root = _resolve_alpasim_root(args.alpasim_root)
    _validate_alpasim_checkout(alpasim_root)
    driver_project = alpasim_root / "src" / "driver"
    venv_python = alpasim_root / ".venv" / "bin" / "python"

    if not driver_project.is_dir():
        raise SystemExit(f"AlpaSim driver project not found: {driver_project}")
    if not args.skip_overrides:
        _apply_local_alpasim_overrides(alpasim_root)
    _bootstrap_alpasim_venv(alpasim_root, uv_bin=uv_bin)
    if not venv_python.is_file():
        raise SystemExit(f"AlpaSim virtualenv python not found after bootstrap: {venv_python}")

    if not args.check_only:
        _run(
            [
                uv_bin,
                "pip",
                "install",
                "--cache-dir",
                str(ROOT / ".uv-cache"),
                "--python",
                str(venv_python),
                "--no-deps",
                "-e",
                str(ROOT),
            ],
            cwd=ROOT,
        )

    plugin_names = _plugin_names(venv_python)
    missing = [name for name in REQUIRED_MODELS if name not in plugin_names]
    if missing:
        raise SystemExit(
            "AlpaSim plugin registration is incomplete. "
            f"Missing {missing}; discovered {plugin_names}."
        )

    print("AlpaSim driver registry OK")
    print(f"Models: {', '.join(plugin_names)}")
    print()
    print("Next:")
    print(
        "  ALPASIM_ROOT="
        + shlex_quote(str(alpasim_root))
        + " ./.venv/bin/python scripts/run_alpasim_local_external.py "
        "--mode print --model token_dagger_iter2_hybrid_clamped --scene-preset fresh_3scene"
    )


def _resolve_alpasim_root(cli_value: Path | None) -> Path:
    if cli_value is not None:
        return cli_value.resolve()
    env_value = os.getenv("ALPASIM_ROOT", "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()
    return DEFAULT_ALPASIM_ROOT.resolve()


def _validate_alpasim_checkout(alpasim_root: Path) -> None:
    required_dirs = (
        alpasim_root / "src" / "driver",
        alpasim_root / "src" / "wizard",
    )
    for required_dir in required_dirs:
        if not required_dir.is_dir():
            raise SystemExit(f"AlpaSim checkout missing required path: {required_dir}")

    pyproject_file = alpasim_root / "pyproject.toml"
    if not pyproject_file.is_file():
        raise SystemExit(
            "AlpaSim checkout is missing pyproject.toml at "
            f"{pyproject_file}. Recreate it with ./scripts/bootstrap_alpasim_checkout.sh."
        )

    git_marker = alpasim_root / ".git"
    if not git_marker.exists():
        raise SystemExit(
            "ALPASIM_ROOT points at a copied directory, not a real AlpaSim checkout: "
            f"{alpasim_root}. The wizard resolves configs from the nearest git root and "
            "will break in this layout. Recreate the nested checkout with "
            "./scripts/bootstrap_alpasim_checkout.sh."
        )


def _require_uv() -> str:
    uv_bin = which("uv")
    if uv_bin:
        return uv_bin
    raise SystemExit(
        "uv is required for AlpaSim setup. Install it first, e.g. "
        "`python3 -m pip install --user uv`, then rerun this script."
    )


def _apply_local_alpasim_overrides(alpasim_root: Path) -> None:
    if not ALPASIM_OVERRIDE_ROOT.is_dir():
        return
    patch_files = sorted(ALPASIM_OVERRIDE_ROOT.rglob("*.patch"))
    for patch_file in patch_files:
        _apply_alpasim_patch(alpasim_root, patch_file)

    copied: list[str] = []
    for source in ALPASIM_OVERRIDE_ROOT.rglob("*"):
        if not source.is_file():
            continue
        if source.suffix == ".patch":
            continue
        relative = source.relative_to(ALPASIM_OVERRIDE_ROOT)
        target = alpasim_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(str(relative))
    if copied:
        print("Applied repo-tracked AlpaSim overrides:")
        for relative in copied:
            print(f"  {relative}")


def _apply_alpasim_patch(alpasim_root: Path, patch_file: Path) -> None:
    relative = patch_file.relative_to(ALPASIM_OVERRIDE_ROOT)
    reverse_check = subprocess.run(
        ["git", "apply", "--reverse", "--check", str(patch_file)],
        cwd=alpasim_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if reverse_check.returncode == 0:
        print(f"AlpaSim patch already applied: {relative}")
        return

    check = subprocess.run(
        ["git", "apply", "--check", str(patch_file)],
        cwd=alpasim_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if check.returncode != 0:
        message = check.stderr.strip() or check.stdout.strip() or "git apply --check failed"
        raise SystemExit(f"Cannot apply AlpaSim patch {relative}: {message}")

    _run(["git", "apply", str(patch_file)], cwd=alpasim_root)
    print(f"Applied AlpaSim patch: {relative}")


def _bootstrap_alpasim_venv(alpasim_root: Path, *, uv_bin: str) -> None:
    venv_root = alpasim_root / ".venv"
    venv_python = venv_root / "bin" / "python"
    if not venv_python.is_file():
        _run([uv_bin, "venv", str(venv_root)], cwd=alpasim_root)

    _run(
        [
            uv_bin,
            "pip",
            "install",
            "--cache-dir",
            str(ROOT / ".uv-cache"),
            "--python",
            str(venv_python),
            *ALPASIM_CORE_DEPENDENCIES,
        ],
        cwd=alpasim_root,
    )

    _install_torch_for_alpasim(uv_bin=uv_bin, venv_python=venv_python, cwd=alpasim_root)

    _compile_alpasim_protos(alpasim_root, venv_python=venv_python)

    for relative in ALPASIM_EDITABLE_PACKAGES:
        package_path = alpasim_root / relative
        if not package_path.is_dir():
            raise SystemExit(f"Expected AlpaSim package path missing: {package_path}")
        _run(
            [
                uv_bin,
                "pip",
                "install",
                "--cache-dir",
                str(ROOT / ".uv-cache"),
                "--python",
                str(venv_python),
                "--no-deps",
                "-e",
                str(package_path),
            ],
            cwd=alpasim_root,
        )


def _compile_alpasim_protos(alpasim_root: Path, *, venv_python: Path) -> None:
    grpc_root = alpasim_root / "src" / "grpc"
    if not grpc_root.is_dir():
        raise SystemExit(f"Expected AlpaSim gRPC package path missing: {grpc_root}")
    proto_root = grpc_root / "alpasim_grpc" / "v0"
    if not proto_root.is_dir():
        raise SystemExit(f"Expected AlpaSim proto directory missing: {proto_root}")

    generated = tuple(proto_root.glob("*_pb2.py")) + tuple(proto_root.glob("*_pb2_grpc.py"))
    for path in generated:
        path.unlink()

    for proto_file in sorted(proto_root.glob("*.proto")):
        _run(
            [
                str(venv_python),
                "-m",
                "grpc_tools.protoc",
                f"-I{grpc_root}",
                f"--python_out={grpc_root}",
                f"--grpc_python_out={grpc_root}",
                str(proto_file.relative_to(grpc_root)),
            ],
            cwd=grpc_root,
        )

    required_outputs = (
        proto_root / "common_pb2.py",
        proto_root / "egodriver_pb2.py",
        proto_root / "sensorsim_pb2.py",
    )
    missing = [str(path) for path in required_outputs if not path.is_file()]
    if missing:
        raise SystemExit(
            "Failed to generate required AlpaSim protobuf modules: "
            + ", ".join(missing)
        )


def _install_torch_for_alpasim(*, uv_bin: str, venv_python: Path, cwd: Path) -> None:
    uv_cmd = [
        uv_bin,
        "pip",
        "install",
        "--cache-dir",
        str(ROOT / ".uv-cache"),
        "--python",
        str(venv_python),
        "--index-url",
        TORCH_INDEX_URL,
        TORCH_PACKAGE,
    ]
    result = subprocess.run(
        uv_cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
        return

    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    sys.stderr.write(
        "uv torch install failed inside AlpaSim env; retrying with pip in the same environment.\n"
    )
    _ensure_venv_pip(venv_python=venv_python, cwd=cwd)
    _run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--index-url",
            TORCH_INDEX_URL,
            TORCH_PACKAGE,
        ],
        cwd=cwd,
    )


def _ensure_venv_pip(*, venv_python: Path, cwd: Path) -> None:
    try:
        probe = subprocess.run(
            [str(venv_python), "-m", "pip", "--version"],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        if probe.returncode == 0:
            return
    except OSError:
        pass
    _run([str(venv_python), "-m", "ensurepip", "--upgrade"], cwd=cwd)


def _plugin_names(venv_python: Path) -> list[str]:
    script = "\n".join(
        [
            "from importlib.metadata import entry_points",
            "import sys",
            "names = []",
            "failures = []",
            "for ep in sorted(entry_points(group='alpasim.models'), key=lambda item: item.name):",
            "    try:",
            "        ep.load()",
            "        names.append(ep.name)",
            "    except Exception as exc:",
            "        failures.append(f'{ep.name}: {exc}')",
            "if failures:",
            "    sys.stderr.write('Skipped unloadable model entry points:\\n' + '\\n'.join(failures) + '\\n')",
            "print('\\n'.join(names))",
        ]
    )
    result = _run([str(venv_python), "-c", script], cwd=ROOT, capture_output=True)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def shlex_quote(text: str) -> str:
    return "'" + text.replace("'", "'\"'\"'") + "'"


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=capture_output,
        check=False,
    )
    if result.returncode != 0:
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    if not capture_output:
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
    return result


if __name__ == "__main__":
    main()
