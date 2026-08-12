from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from shutil import which

from alpabridge.cli.commands.run_alpasim_local_external import PUBLIC_RELEASE_MODELS
from alpabridge.cli.runtime_paths import package_path, repo_path, workspace_path

DEFAULT_ALPASIM_ROOT = workspace_path("workspace", "alpasim")
ALPASIM_OVERRIDE_ROOT = package_path("alpasim_overrides")
REPO_ROOT = repo_path()
INSTALL_ROOT = REPO_ROOT or Path.cwd()
UV_CACHE_DIR = workspace_path(".uv-cache")
REQUIRED_MODELS = PUBLIC_RELEASE_MODELS
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
OVERRIDE_COPY_IGNORED_DIR_NAMES = {"__pycache__"}
OVERRIDE_COPY_IGNORED_SUFFIXES = {".patch", ".pyc", ".pyo"}


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
    alpasim_root = _resolve_alpasim_root(args.alpasim_root)
    _validate_alpasim_checkout(alpasim_root)
    driver_project = alpasim_root / "src" / "driver"
    venv_python = alpasim_root / ".venv" / "bin" / "python"

    if not driver_project.is_dir():
        raise SystemExit(f"AlpaSim driver project not found: {driver_project}")
    if args.check_only:
        if not venv_python.is_file():
            raise SystemExit(
                "AlpaSim virtualenv python not found for --check-only mode: "
                f"{venv_python}. Run alpabridge-setup without --check-only first."
            )
    else:
        if REPO_ROOT is None:
            raise SystemExit(
                "Full `alpabridge-setup` requires a source checkout so the package can be installed "
                "into the AlpaSim environment. Re-run from a cloned AlpaBridge repo, or use "
                "`alpabridge-setup --check-only` with an environment that already has AlpaBridge installed."
            )
        uv_bin = _require_uv()
        if not args.skip_overrides:
            _apply_local_alpasim_overrides(alpasim_root)
        _bootstrap_alpasim_venv(alpasim_root, uv_bin=uv_bin)
        if not venv_python.is_file():
            raise SystemExit(f"AlpaSim virtualenv python not found after bootstrap: {venv_python}")
        _run(
            [
                uv_bin,
                "pip",
                "install",
                "--cache-dir",
                str(UV_CACHE_DIR),
                "--python",
                str(venv_python),
                "--no-deps",
                "-e",
                str(INSTALL_ROOT),
            ],
            cwd=INSTALL_ROOT,
        )

    plugin_snapshot = _plugin_registry_snapshot(venv_python)
    _fail_on_duplicate_public_model_entry_points(plugin_snapshot)
    plugin_names = _plugin_names_from_snapshot(plugin_snapshot)
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
        + " alpabridge-launch --mode print --model token_dagger_bc"
        + " --checkpoint /path/to/token_dagger_bc.pt --scene-preset fresh_3scene"
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
        raise SystemExit(
            "AlpaBridge override payload is missing from this installation: "
            f"{ALPASIM_OVERRIDE_ROOT}"
        )
    patch_files = sorted(ALPASIM_OVERRIDE_ROOT.rglob("*.patch"))
    for patch_file in patch_files:
        _apply_alpasim_patch(alpasim_root, patch_file)

    copied: list[str] = []
    for source in ALPASIM_OVERRIDE_ROOT.rglob("*"):
        if not _should_copy_override_path(source, ALPASIM_OVERRIDE_ROOT):
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


def _should_copy_override_path(source: Path, root: Path | None = None) -> bool:
    if not source.is_file():
        return False
    if source.name in OVERRIDE_COPY_IGNORED_DIR_NAMES:
        return False
    if any(parent.name in OVERRIDE_COPY_IGNORED_DIR_NAMES for parent in source.parents):
        return False
    if source.suffix in OVERRIDE_COPY_IGNORED_SUFFIXES:
        return False
    # The override root's own `__init__.py` is what makes alpasim_overrides an importable
    # package inside AlpaBridge - it is not payload. Copying it wrote a stray `__init__.py`
    # into the root of the user's AlpaSim checkout (visible there as untracked noise, and
    # enough to make Python treat the repo root as a package). Only the root-level one is
    # excluded: `src/driver/**/models/__init__.py` is a genuine override and still copies.
    if source.name == "__init__.py" and source.parent == (root or ALPASIM_OVERRIDE_ROOT):
        return False
    return True


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
    if check.returncode == 0:
        _run(["git", "apply", str(patch_file)], cwd=alpasim_root)
        print(f"Applied AlpaSim patch: {relative}")
        return

    # Plain apply failed - the checkout's context lines have drifted from what
    # this patch expects (e.g. an upstream release moved on since the patch
    # was cut). Try a real three-way merge, keyed off the blob hashes recorded
    # in the patch's own `index` lines, before giving up: this resolves benign
    # drift the same way `git am --3way`/`git cherry-pick` do, without a
    # hand-maintained side channel duplicating the patch's own content.
    #
    # `--3way --check` is not a reliable predictor here: it can report success
    # even when the real merge would leave conflict markers in place, so the
    # real attempt is what actually decides success or failure. On failure we
    # restore exactly the pre-attempt bytes of the files this patch touches -
    # not `git checkout HEAD`, which would also discard any uncommitted local
    # changes the checkout already had on those files before this ran.
    touched = _patch_touched_files(alpasim_root, patch_file)
    snapshot = {path: path.read_bytes() for path in touched if path.is_file()}
    three_way = subprocess.run(
        ["git", "apply", "--3way", str(patch_file)],
        cwd=alpasim_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if three_way.returncode == 0:
        print(f"Applied AlpaSim patch via three-way merge: {relative}")
        return

    for path, original_bytes in snapshot.items():
        path.write_bytes(original_bytes)
    if touched:
        # A failed --3way also stages conflict entries in the index; unstage
        # them (working tree is already restored above by byte content).
        subprocess.run(
            ["git", "reset", "--", *(str(path.relative_to(alpasim_root)) for path in touched)],
            cwd=alpasim_root,
            capture_output=True,
            check=False,
        )
    message = three_way.stderr.strip() or three_way.stdout.strip() or "git apply --3way failed"
    raise SystemExit(
        f"Cannot apply AlpaSim patch {relative}: {message}\n"
        f"This AlpaSim checkout ({alpasim_root}) may not be at the pinned release. "
        "Re-sync it with ./scripts/bootstrap_alpasim_checkout.sh."
    )


def _patch_touched_files(alpasim_root: Path, patch_file: Path) -> list[Path]:
    numstat = subprocess.run(
        ["git", "apply", "--numstat", str(patch_file)],
        cwd=alpasim_root,
        text=True,
        capture_output=True,
        check=False,
    )
    return [
        alpasim_root / line.split("\t", 2)[-1]
        for line in numstat.stdout.splitlines()
        if line.strip()
    ]


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
                str(UV_CACHE_DIR),
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
                str(UV_CACHE_DIR),
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
    del uv_bin  # Torch wheels are installed with pip directly; uv fails on this dependency chain.
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
            "torchvision",
        ],
        cwd=cwd,
    )
    _verify_torch_torchvision_pair(venv_python=venv_python, cwd=cwd)


def _verify_torch_torchvision_pair(*, venv_python: Path, cwd: Path) -> None:
    """`torch` and `torchvision` must come from matching CUDA builds or
    torchvision fails at import time with `operator torchvision::nms does not
    exist` -- a real, repeated failure mode on this project's checkouts
    (something installed earlier, e.g. the checkout's own setup script,
    pulls in a `torchvision` resolved against a different `torch` than the
    pin above). Pinning both together above is the fix; this re-imports
    `torchvision` immediately after to catch a mismatch at setup time rather
    than at the first live rollout. Uses `_run` (not a direct `subprocess.run`
    call) so this stays covered by the same mocking seam the rest of this
    module's subprocess calls already use.
    """
    print(f"Verifying torch/torchvision compatibility in {venv_python}...")
    _run([str(venv_python), "-c", "import torchvision"], cwd=cwd, capture_output=True)


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


def _plugin_registry_snapshot(venv_python: Path) -> dict[str, object]:
    script = "\n".join(
        [
            "from importlib.metadata import entry_points",
            "import json",
            "import sys",
            "loaded = []",
            "failures = []",
            "for ep in sorted(entry_points(group='alpasim.models'), key=lambda item: item.name):",
            "    try:",
            "        ep.load()",
            "        loaded.append({",
            "            'name': ep.name,",
            "            'value': ep.value,",
            "            'dist': getattr(getattr(ep, 'dist', None), 'name', 'unknown'),",
            "        })",
            "    except Exception as exc:",
            "        failures.append(f'{ep.name}: {exc}')",
            "print(json.dumps({'loaded': loaded, 'failures': failures}))",
        ]
    )
    result = _run([str(venv_python), "-c", script], cwd=INSTALL_ROOT, capture_output=True)
    snapshot = json.loads(result.stdout)
    failures = snapshot.get("failures", [])
    if failures:
        sys.stderr.write("Skipped unloadable model entry points:\n" + "\n".join(failures) + "\n")
    return snapshot


def _plugin_names(venv_python: Path) -> list[str]:
    snapshot = _plugin_registry_snapshot(venv_python)
    return _plugin_names_from_snapshot(snapshot)


def _plugin_names_from_snapshot(snapshot: dict[str, object]) -> list[str]:
    names: list[str] = []
    for entry in snapshot.get("loaded", []):
        name = str(entry.get("name", "")).strip()
        if name and name not in names:
            names.append(name)
    return names


def _fail_on_duplicate_public_model_entry_points(snapshot: dict[str, object]) -> None:
    duplicate_messages: list[str] = []
    by_name: dict[str, list[dict[str, str]]] = {}
    for entry in snapshot.get("loaded", []):
        name = str(entry.get("name", "")).strip()
        if name not in REQUIRED_MODELS:
            continue
        by_name.setdefault(name, []).append(entry)
    for name, entries in by_name.items():
        if len(entries) < 2:
            continue
        sources = ", ".join(f"{item.get('dist', 'unknown')} -> {item.get('value', 'unknown')}" for item in entries)
        duplicate_messages.append(f"{name}: {sources}")
    if duplicate_messages:
        raise SystemExit(
            "Duplicate public AlpaBridge model entry points detected in the AlpaSim environment. "
            "Remove stale installations and rerun alpabridge-setup.\n"
            + "\n".join(duplicate_messages)
        )


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
