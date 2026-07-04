from __future__ import annotations

import argparse
import json
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

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
        "--output",
        type=Path,
        default=None,
        help="Optional JSON output path.",
    )
    return parser.parse_args()


def build_report() -> dict[str, object]:
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

    report = {
        "schema": "wod2sim_doctor_v1",
        "valid": bool(
            checks["python_supported"]
            and checks["public_model_surface_curated"]
            and checks["scene_presets_present"]
            and checks["public_model_configs_present"]
            and release_surface_ok
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

    print("  next:")
    print("    1. Read docs/integration_guide.md")
    print("    2. Run wod2sim-ready --alpasim-root /path/to/alpasim")
    print("    3. Start with wod2sim-launch --mode print --model spotlight_reflex")


def main() -> int:
    args = _parse_args()
    report = build_report()
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
