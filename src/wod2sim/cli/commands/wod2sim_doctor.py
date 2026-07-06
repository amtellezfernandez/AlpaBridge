from __future__ import annotations

import argparse
import json
import os
import sys
from importlib.metadata import PackageNotFoundError, distribution, distributions
from pathlib import Path

from wod2sim.cli.commands.check_alpasim_readiness import (
    _preflight_alpasim_base_image,
    _preflight_docker_access,
    _preflight_nvidia_container_runtime,
    _preflight_platform_compatibility,
    _preflight_scene_artifacts,
    _scene_catalog_paths,
    _scene_ids,
    _validate_alpasim_checkout,
)
from wod2sim.cli.commands.run_alpasim_local_external import (
    MODEL_PRESETS,
    PUBLIC_RELEASE_MODELS,
    SCENE_PRESETS,
)
from wod2sim.cli.runtime_paths import SOURCE_REPO_ROOT, package_path, repo_path, workspace_path

EXPECTED_CONSOLE_SCRIPTS = (
    "wod2sim-doctor",
    "wod2sim-setup",
    "wod2sim-ready",
    "wod2sim-launch",
    "wod2sim-batch",
    "wod2sim-build-local-cache",
    "wod2sim-build-oracle-proxy",
    "wod2sim-audit-signal",
    "wod2sim-audit-run",
    "wod2sim-support-bundle",
    "wod2sim-reproduce",
    "wod2sim-benchmark-plan",
    "wod2sim-benchmark-summary",
    "wod2sim-batch-summary",
    "wod2sim-evidence",
)
EXPECTED_WRAPPERS = {
    "wod2sim-doctor": "scripts/wod2sim_doctor.py",
    "wod2sim-setup": "scripts/setup_alpasim_local_plugin.py",
    "wod2sim-ready": "scripts/check_alpasim_readiness.py",
    "wod2sim-launch": "scripts/run_alpasim_local_external.py",
    "wod2sim-batch": "scripts/run_alpasim_scene_batch.py",
    "wod2sim-build-local-cache": "scripts/build_alpasim_local_usdz_cache.py",
    "wod2sim-build-oracle-proxy": "scripts/build_alpasim_oracle_actor_proxy.py",
    "wod2sim-audit-signal": "scripts/audit_alpasignal_bridge.py",
    "wod2sim-audit-run": "scripts/audit_run.py",
    "wod2sim-support-bundle": "scripts/support_bundle.py",
    "wod2sim-reproduce": "scripts/reproduce_closed_loop.py",
    "wod2sim-benchmark-plan": "scripts/benchmark_regeneration_plan.py",
    "wod2sim-benchmark-summary": "scripts/benchmark_summary.py",
    "wod2sim-batch-summary": "scripts/batch_summary.py",
}
PUBLIC_MODEL_CONFIGS = {
    model: Path(MODEL_PRESETS[model]["config_file"]).resolve()
    for model in PUBLIC_RELEASE_MODELS
}
LEGACY_DISTRIBUTIONS = ("slipway", "minimal-shot-av", "wayspan", "way2sim")


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
        "--probe-default-environment",
        action="store_true",
        help=(
            "Probe the default AlpaSim root path even when --alpasim-root and ALPASIM_ROOT "
            "are not set. Useful for fresh-machine host audits before the checkout exists."
        ),
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


def _default_alpasim_root() -> Path:
    return workspace_path("workspace", "alpasim").resolve()


def _run_check(func, *args, **kwargs) -> tuple[str, str | None]:
    try:
        func(*args, **kwargs)
    except SystemExit as exc:
        return "failed", str(exc)
    except Exception as exc:  # pragma: no cover - defensive fallback
        return "failed", f"{type(exc).__name__}: {exc}"
    return "ok", None


def _normalized_distribution_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _distribution_display_name(dist) -> str:
    metadata = getattr(dist, "metadata", {}) or {}
    raw = metadata.get("Name", "") or getattr(dist, "name", "") or "unknown"
    return str(raw)


def _legacy_distributions_present() -> list[str]:
    normalized_legacy = {_normalized_distribution_name(name) for name in LEGACY_DISTRIBUTIONS}
    present: list[str] = []
    for dist in distributions():
        name = _distribution_display_name(dist)
        normalized = _normalized_distribution_name(name)
        if normalized in normalized_legacy and normalized not in present:
            present.append(normalized)
    return sorted(present)


def _public_model_entry_point_providers() -> dict[str, list[dict[str, str]]]:
    providers: dict[str, list[dict[str, str]]] = {name: [] for name in PUBLIC_RELEASE_MODELS}
    seen: dict[str, set[tuple[str, str]]] = {name: set() for name in PUBLIC_RELEASE_MODELS}
    for dist in distributions():
        dist_name = _distribution_display_name(dist)
        for entry_point in getattr(dist, "entry_points", ()):
            if getattr(entry_point, "group", "") != "alpasim.models":
                continue
            if entry_point.name not in providers:
                continue
            value = str(getattr(entry_point, "value", ""))
            provider_key = (dist_name, value)
            if provider_key in seen[entry_point.name]:
                continue
            seen[entry_point.name].add(provider_key)
            providers[entry_point.name].append({"dist": dist_name, "value": value})
    return providers


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
    scene_catalog_paths = _scene_catalog_paths(scene_preset, alpasim_root)
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
            scene_catalog_paths=scene_catalog_paths,
        )
        record("scene_artifacts", status, error)

    valid = all(status in {"ok", "skipped"} for status in statuses.values())
    return {
        "requested": True,
        "alpasim_root": str(alpasim_root),
        "scene_preset": scene_preset,
        "scene_ids": scene_ids,
        "scene_catalog_paths": [str(path) for path in scene_catalog_paths],
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
    probe_default_environment: bool = False,
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

    repo_root = repo_path()
    wrapper_missing: list[str] = []
    wrapper_scripts_present = False
    if repo_root is not None:
        wrapper_scripts_present = True
        wrapper_missing = [
            name for name, relative in EXPECTED_WRAPPERS.items() if not (repo_root / relative).is_file()
        ]
        wrapper_scripts_present = not wrapper_missing
    missing_scene_presets = [
        name for name, path in SCENE_PRESETS.items() if not Path(path).is_file()
    ]
    missing_model_configs = [
        name for name, path in PUBLIC_MODEL_CONFIGS.items() if not path.is_file()
    ]
    legacy_distributions_present = _legacy_distributions_present()
    public_model_entry_point_providers = _public_model_entry_point_providers()
    missing_public_model_entry_points = [
        name for name, entries in public_model_entry_point_providers.items() if not entries
    ]
    duplicate_public_model_entry_points = []
    unexpected_public_model_providers = []
    for name, entries in public_model_entry_point_providers.items():
        if len(entries) > 1:
            duplicate_public_model_entry_points.append(
                f"{name}: " + ", ".join(f"{entry['dist']} -> {entry['value']}" for entry in entries)
            )
        for entry in entries:
            if _normalized_distribution_name(entry["dist"]) != "wod2sim":
                unexpected_public_model_providers.append(
                    f"{name}: {entry['dist']} -> {entry['value']}"
                )

    checks = {
        "python_supported": sys.version_info >= (3, 10),
        "public_model_surface_curated": tuple(PUBLIC_RELEASE_MODELS)
        == ("spotlight_reflex", "token_dagger_bc", "direct_actor_planner"),
        "public_model_registry_curated": tuple(MODEL_PRESETS) == tuple(PUBLIC_RELEASE_MODELS),
        "scene_presets_present": not missing_scene_presets,
        "public_model_configs_present": not missing_model_configs,
        "wrapper_scripts_present": wrapper_scripts_present,
        "installed_entry_points_present": not installed_entry_points_missing,
        "legacy_distributions_absent": not legacy_distributions_present,
        "public_model_entry_points_unique": not duplicate_public_model_entry_points,
        "public_model_entry_points_owned_by_wod2sim": not unexpected_public_model_providers,
        "installed_public_model_entry_points_present": install_mode != "installed"
        or not missing_public_model_entry_points,
    }
    release_surface_ok = checks["installed_entry_points_present"] or checks["wrapper_scripts_present"]
    if checks["installed_entry_points_present"]:
        release_surface_mode = "installed-entry-points"
    elif checks["wrapper_scripts_present"]:
        release_surface_mode = "source-tree-wrappers"
    else:
        release_surface_mode = "missing"

    requested_alpasim_root = _requested_alpasim_root(alpasim_root)
    if requested_alpasim_root is None and probe_default_environment:
        requested_alpasim_root = _default_alpasim_root()
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
            and checks["public_model_registry_curated"]
            and checks["scene_presets_present"]
            and checks["public_model_configs_present"]
            and release_surface_ok
            and checks["legacy_distributions_absent"]
            and checks["public_model_entry_points_unique"]
            and checks["public_model_entry_points_owned_by_wod2sim"]
            and checks["installed_public_model_entry_points_present"]
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
            "public_model_entry_points": missing_public_model_entry_points if install_mode == "installed" else [],
        },
        "conflicts": {
            "legacy_distributions": legacy_distributions_present,
            "duplicate_public_model_entry_points": duplicate_public_model_entry_points,
            "unexpected_public_model_providers": unexpected_public_model_providers,
        },
        "artifacts": {
            "repo_root": None if repo_root is None else str(repo_root),
            "docs_integration_guide": None if repo_root is None else str(repo_root / "docs" / "integration_guide.md"),
            "paper_source": None if repo_root is None else str(repo_root / "paper"),
            "package_root": str(package_path()),
            "source_repo_root": None if SOURCE_REPO_ROOT is None else str(SOURCE_REPO_ROOT),
        },
        "public_model_entry_point_providers": public_model_entry_point_providers,
        "environment": environment,
    }
    return report


def _print_human_report(report: dict[str, object], *, strict_installed: bool) -> None:
    checks = report["checks"]
    missing = report["missing"]
    conflicts = report["conflicts"]
    environment = report["environment"]

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

    if any(conflicts.values()):
        print("  conflicts:")
        for name, values in conflicts.items():
            if values:
                print(f"    {name}: {', '.join(values)}")

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
    if any(conflicts.values()):
        print("    2. Remove stale legacy distributions or duplicate public model providers")
        print("    3. If this is an AlpaSim plugin env, rerun wod2sim-setup --alpasim-root /path/to/alpasim")
        print("    4. Then rerun wod2sim-doctor")
        return
    if environment is None:
        print("    2. Run wod2sim-doctor --alpasim-root /path/to/alpasim")
        print("    3. Run wod2sim-ready --alpasim-root /path/to/alpasim")
    else:
        print("    2. Fix any failing environment checks above")
        if environment["statuses"].get("alpasim_checkout") == "failed":
            print("    3. If the checkout is missing, run ./scripts/bootstrap_alpasim_checkout.sh")
            print("    4. Then rerun wod2sim-doctor --probe-default-environment")
            print("    5. After the checkout exists, run wod2sim-ready --alpasim-root /path/to/alpasim")
        elif environment["statuses"].get("scene_artifacts") == "failed":
            print("    3. If you only want host/runtime validation, rerun with --skip-scene-artifacts")
            print("    4. Or point doctor at a different cached preset with --scene-preset ...")
            print("    5. After the cache issue is fixed, start with wod2sim-launch --mode print --model spotlight_reflex")
        else:
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
        probe_default_environment=args.probe_default_environment,
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
