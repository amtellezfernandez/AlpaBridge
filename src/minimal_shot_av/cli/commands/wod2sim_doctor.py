from __future__ import annotations

import argparse
import json
import os
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

from minimal_shot_av.cli.commands.check_alpasim_readiness import _preflight_alpasim_base_image
from minimal_shot_av.cli.commands.check_alpasim_readiness import _preflight_docker_access
from minimal_shot_av.cli.commands.check_alpasim_readiness import _preflight_nvidia_container_runtime
from minimal_shot_av.cli.commands.check_alpasim_readiness import _preflight_platform_compatibility
from minimal_shot_av.cli.commands.check_alpasim_readiness import _preflight_scene_artifacts
from minimal_shot_av.cli.commands.check_alpasim_readiness import _scene_ids
from minimal_shot_av.cli.commands.check_alpasim_readiness import _validate_alpasim_checkout
from minimal_shot_av.cli.commands.run_alpasim_local_external import MODEL_PRESETS, PUBLIC_RELEASE_MODELS, SCENE_PRESETS


ROOT = Path(__file__).resolve().parents[4]
EXPECTED_CONSOLE_SCRIPTS = (
    "wod2sim-doctor",
    "wod2sim-setup",
    "wod2sim-ready",
    "wod2sim-launch",
    "wod2sim-batch",
    "wod2sim-audit-signal",
    "wod2sim-evidence",
)
EXPECTED_WRAPPERS = {
    "wod2sim-doctor": ROOT / "scripts" / "wod2sim_doctor.py",
    "wod2sim-setup": ROOT / "scripts" / "setup_alpasim_local_plugin.py",
    "wod2sim-ready": ROOT / "scripts" / "check_alpasim_readiness.py",
    "wod2sim-launch": ROOT / "scripts" / "run_alpasim_local_external.py",
    "wod2sim-batch": ROOT / "scripts" / "run_alpasim_scene_batch.py",
    "wod2sim-audit-signal": ROOT / "scripts" / "audit_alpasignal_bridge.py",
}
PUBLIC_MODEL_CONFIGS = {
    model: Path(MODEL_PRESETS[model]["config_file"]).resolve()
    for model in PUBLIC_RELEASE_MODELS
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the public WOD2Sim release surface before wiring it into AlpaSim."
    )
    parser.add_argument(
        "--alpasim-root",
        type=Path,
        default=None,
        help="Optional AlpaSim checkout root to validate alongside the WOD2Sim release surface.",
    )
    parser.add_argument(
        "--scene-preset",
        choices=tuple(SCENE_PRESETS),
        default="fresh_3scene",
        help="Scene preset whose artifacts should be checked when validating an AlpaSim root.",
    )
    parser.add_argument(
        "--scene-id",
        action="append",
        default=[],
        help="Explicit scene id override. If set, replaces the preset scene list for doctor checks.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the doctor report as JSON.",
    )
    parser.add_argument(
        "--strict-installed",
        action="store_true",
        help="Require installed console-script entry points instead of allowing source-tree wrappers.",
    )
    parser.add_argument(
        "--skip-docker",
        action="store_true",
        help="Skip checking Docker daemon access when validating an AlpaSim root.",
    )
    parser.add_argument(
        "--skip-gpu-runtime",
        action="store_true",
        help="Skip checking NVIDIA container runtime access when validating an AlpaSim root.",
    )
    parser.add_argument(
        "--skip-image",
        action="store_true",
        help="Skip checking for the local alpasim-base image when validating an AlpaSim root.",
    )
    parser.add_argument(
        "--skip-scene-artifacts",
        action="store_true",
        help="Skip checking gated/local scene artifacts when validating an AlpaSim root.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON output path.",
    )
    return parser.parse_args()


def _requested_alpasim_root(cli_value: Path | None) -> Path | None:
    if cli_value is not None:
        return cli_value.resolve()
    env_value = os.getenv("ALPASIM_ROOT", "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()
    return None


def _run_check(func, *args, **kwargs) -> tuple[str, str | None]:
    try:
        func(*args, **kwargs)
    except SystemExit as exc:
        return "failed", str(exc)
    except Exception as exc:  # pragma: no cover - defensive fallback
        return "failed", f"{type(exc).__name__}: {exc}"
    return "ok", None


def _build_environment_report(
    *,
    alpasim_root: Path,
    scene_preset: str,
    explicit_scene_ids: list[str],
    skip_docker: bool,
    skip_gpu_runtime: bool,
    skip_image: bool,
    skip_scene_artifacts: bool,
) -> dict[str, object]:
    scene_ids = _scene_ids(scene_preset, explicit_scene_ids)
    statuses: dict[str, str] = {}
    errors: dict[str, str] = {}

    def record(name: str, status: str, error: str | None) -> None:
        statuses[name] = status
        if error:
            errors[name] = error

    status, error = _run_check(_validate_alpasim_checkout, alpasim_root)
    record("alpasim_checkout", status, error)

    status, error = _run_check(_preflight_platform_compatibility)
    record("platform_compatibility", status, error)

    if skip_docker:
        statuses["docker_access"] = "skipped"
    else:
        status, error = _run_check(_preflight_docker_access)
        record("docker_access", status, error)

    if skip_image:
        statuses["base_image"] = "skipped"
    else:
        status, error = _run_check(_preflight_alpasim_base_image)
        record("base_image", status, error)

    if skip_gpu_runtime:
        statuses["gpu_runtime"] = "skipped"
    else:
        status, error = _run_check(_preflight_nvidia_container_runtime)
        record("gpu_runtime", status, error)

    if skip_scene_artifacts:
        statuses["scene_artifacts"] = "skipped"
    elif statuses["alpasim_checkout"] != "ok":
        statuses["scene_artifacts"] = "blocked"
        errors["scene_artifacts"] = "AlpaSim checkout validation failed; scene artifact check not run."
    else:
        status, error = _run_check(
            _preflight_scene_artifacts,
            alpasim_root=alpasim_root,
            scene_ids=scene_ids,
        )
        record("scene_artifacts", status, error)

    valid = all(status in {"ok", "skipped"} for status in statuses.values())
    return {
        "requested": True,
        "alpasim_root": str(alpasim_root),
        "scene_preset": scene_preset,
        "scene_ids": scene_ids,
        "statuses": statuses,
        "errors": errors,
        "valid": valid,
    }


def build_report(
    *,
    alpasim_root: Path | None = None,
    scene_preset: str = "fresh_3scene",
    explicit_scene_ids: list[str] | None = None,
    skip_docker: bool = False,
    skip_gpu_runtime: bool = False,
    skip_image: bool = False,
    skip_scene_artifacts: bool = False,
) -> dict[str, object]:
    explicit_scene_ids = explicit_scene_ids or []
    installed_entry_points: list[str] = []
    installed_entry_points_missing = list(EXPECTED_CONSOLE_SCRIPTS)
    package_version: str | None = None
    install_mode = "source-tree"

    try:
        dist = distribution("wod2sim")
        package_version = dist.version
        install_mode = "installed"
        installed_entry_points = sorted(
            entry_point.name
            for entry_point in dist.entry_points
            if entry_point.group == "console_scripts"
        )
        installed_entry_points_missing = [
            name for name in EXPECTED_CONSOLE_SCRIPTS if name not in installed_entry_points
        ]
    except PackageNotFoundError:
        pass

    wrapper_missing = [
        name for name, path in EXPECTED_WRAPPERS.items() if not path.is_file()
    ]
    missing_scene_presets = [
        name for name, path in SCENE_PRESETS.items() if not Path(path).is_file()
    ]
    missing_model_configs = [
        name for name, path in PUBLIC_MODEL_CONFIGS.items() if not path.is_file()
    ]

    checks = {
        "python_supported": sys.version_info >= (3, 10),
        "public_model_surface_curated": tuple(PUBLIC_RELEASE_MODELS)
        == ("spotlight_reflex", "token_dagger_bc", "direct_actor_planner"),
        "scene_presets_present": not missing_scene_presets,
        "public_model_configs_present": not missing_model_configs,
        "wrapper_scripts_present": not wrapper_missing,
        "installed_entry_points_present": not installed_entry_points_missing,
    }
    release_surface_ok = checks["installed_entry_points_present"] or checks["wrapper_scripts_present"]
    if checks["installed_entry_points_present"]:
        release_surface_mode = "installed-entry-points"
    elif checks["wrapper_scripts_present"]:
        release_surface_mode = "source-tree-wrappers"
    else:
        release_surface_mode = "missing"

    requested_alpasim_root = _requested_alpasim_root(alpasim_root)
    environment = None
    if requested_alpasim_root is not None:
        environment = _build_environment_report(
            alpasim_root=requested_alpasim_root,
            scene_preset=scene_preset,
            explicit_scene_ids=explicit_scene_ids,
            skip_docker=skip_docker,
            skip_gpu_runtime=skip_gpu_runtime,
            skip_image=skip_image,
            skip_scene_artifacts=skip_scene_artifacts,
        )

    report = {
        "schema": "wod2sim_doctor_v1",
        "valid": bool(
            checks["python_supported"]
            and checks["public_model_surface_curated"]
            and checks["scene_presets_present"]
            and checks["public_model_configs_present"]
            and release_surface_ok
            and (environment is None or environment["valid"])
        ),
        "install_mode": install_mode,
        "release_surface_mode": release_surface_mode,
        "package_version": package_version,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "public_models": list(PUBLIC_RELEASE_MODELS),
        "scene_presets": sorted(SCENE_PRESETS),
        "checks": checks,
        "missing": {
            "installed_entry_points": installed_entry_points_missing,
            "wrapper_scripts": wrapper_missing,
            "scene_presets": missing_scene_presets,
            "model_configs": missing_model_configs,
        },
        "artifacts": {
            "repo_root": str(ROOT),
            "docs_integration_guide": str(ROOT / "docs" / "integration_guide.md"),
            "paper_pdf": str(ROOT / "paper" / "paper.pdf"),
        },
        "environment": environment,
    }
    return report


def _print_human_report(report: dict[str, object], *, strict_installed: bool) -> None:
    checks = report["checks"]
    missing = report["missing"]

    print("WOD2Sim doctor")
    print(f"  valid: {report['valid']}")
    print(f"  install mode: {report['install_mode']}")
    print(f"  release surface: {report['release_surface_mode']}")
    print(f"  package version: {report['package_version'] or 'source-tree'}")
    print(f"  python: {report['python_version']}")
    print(f"  public models: {', '.join(report['public_models'])}")
    print(f"  scene presets: {', '.join(report['scene_presets'])}")
    print("  checks:")
    for name, value in checks.items():
        print(f"    {name}: {'ok' if value else 'missing'}")
    if strict_installed:
        print("  strict installed mode: enabled")

    if any(missing.values()):
        print("  missing:")
        for name, values in missing.items():
            if values:
                print(f"    {name}: {', '.join(values)}")

    environment = report["environment"]
    if environment is None:
        print("  alpasim environment: not requested")
    else:
        print(f"  alpasim environment: {'valid' if environment['valid'] else 'invalid'}")
        print(f"    root: {environment['alpasim_root']}")
        print(f"    scene preset: {environment['scene_preset']}")
        print(f"    scene count: {len(environment['scene_ids'])}")
        for name, status in environment["statuses"].items():
            print(f"    {name}: {status}")
        for name, error in environment["errors"].items():
            print(f"    {name} error: {error}")

    print("  next:")
    print("    1. Read docs/integration_guide.md")
    if environment is None:
        print("    2. Run wod2sim-doctor --alpasim-root /path/to/alpasim")
        print("    3. Run wod2sim-ready --alpasim-root /path/to/alpasim")
    else:
        print("    2. Fix any failing environment checks above")
        print("    3. Start with wod2sim-launch --mode print --model spotlight_reflex")


def main() -> int:
    args = _parse_args()
    report = build_report(
        alpasim_root=args.alpasim_root,
        scene_preset=args.scene_preset,
        explicit_scene_ids=list(args.scene_id),
        skip_docker=args.skip_docker,
        skip_gpu_runtime=args.skip_gpu_runtime,
        skip_image=args.skip_image,
        skip_scene_artifacts=args.skip_scene_artifacts,
    )
    if args.strict_installed and report["missing"]["installed_entry_points"]:
        report["valid"] = False

    if args.output is not None:
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human_report(report, strict_installed=args.strict_installed)

    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
