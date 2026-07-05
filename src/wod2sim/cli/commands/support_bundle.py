from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from wod2sim.cli.commands.audit_run import build_report as build_run_audit_report


BUNDLE_INCLUDE_PATTERNS = (
    "launch-metadata.json",
    "run-status.json",
    "driver-command.sh",
    "wizard-command.sh",
    "external-driver-config.yaml",
    "driver.stdout.log",
    "driver.stderr.log",
    "driver/*.jsonl",
    "controller/*.csv",
    "aggregate/*.parquet",
    "aggregate/*.csv",
    "aggregate/*.json",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a portable WOD2Sim run support bundle with audit output and key logs."
    )
    parser.add_argument("--run-dir", type=Path, required=True, help="Executed run directory to package.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output .tar.gz path. Defaults to <run_dir>_wod2sim_support_bundle.tar.gz next to the run.",
    )
    parser.add_argument("--json", action="store_true", help="Print the bundle report as JSON.")
    parser.add_argument("--output-report", type=Path, default=None, help="Optional path for the JSON report.")
    return parser.parse_args()


def build_report(*, run_dir: Path, output: Path | None = None) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run dir not found: {run_dir}")
    bundle_path = _resolve_output_path(run_dir, output)

    with tempfile.TemporaryDirectory(prefix="wod2sim-support-bundle-") as tmpdir:
        staging_root = Path(tmpdir) / f"{run_dir.name}_support_bundle"
        staging_root.mkdir(parents=True, exist_ok=True)
        copied_files, missing_files = _copy_run_artifacts(run_dir, staging_root)

        audit_dir = staging_root / "audit"
        run_audit = build_run_audit_report(run_dir=run_dir, audit_dir=audit_dir)
        run_audit_path = staging_root / "run-audit.json"
        run_audit_path.write_text(json.dumps(run_audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        manifest = {
            "schema": "wod2sim_support_bundle_manifest_v1",
            "run_dir": str(run_dir),
            "bundle_path": str(bundle_path),
            "copied_files": copied_files,
            "missing_files": missing_files,
            "run_audit_path": str(run_audit_path.relative_to(staging_root)),
            "audit_dir": str(audit_dir.relative_to(staging_root)),
        }
        manifest_path = staging_root / "support-bundle-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        archive_base = bundle_path.with_suffix("")
        if archive_base.suffix == ".tar":
            archive_base = archive_base.with_suffix("")
        created_archive = Path(
            shutil.make_archive(
                str(archive_base),
                "gztar",
                root_dir=staging_root.parent,
                base_dir=staging_root.name,
            )
        ).resolve()
        if created_archive != bundle_path:
            created_archive.replace(bundle_path)

    report = {
        "schema": "wod2sim_support_bundle_v1",
        "valid": bundle_path.is_file(),
        "run_dir": str(run_dir),
        "bundle_path": str(bundle_path),
        "copied_file_count": len(copied_files),
        "missing_file_count": len(missing_files),
        "copied_files": copied_files,
        "missing_files": missing_files,
        "run_audit": {
            "valid": bool(run_audit.get("valid")),
            "sensor_pipeline_ok": bool(run_audit.get("sensor_pipeline_ok")),
            "sensor_failure_count": int(run_audit.get("sensor_failure_count", 0)),
            "driver_log_kind": run_audit.get("driver_log", {}).get("kind"),
        },
    }
    return report


def _resolve_output_path(run_dir: Path, output: Path | None) -> Path:
    if output is not None:
        return output.resolve()
    return (run_dir.parent / f"{run_dir.name}_wod2sim_support_bundle.tar.gz").resolve()


def _copy_run_artifacts(run_dir: Path, staging_root: Path) -> tuple[list[str], list[str]]:
    copied: list[str] = []
    missing: list[str] = []
    seen_sources: set[Path] = set()
    for pattern in BUNDLE_INCLUDE_PATTERNS:
        matches = sorted(run_dir.glob(pattern))
        if not matches:
            missing.append(pattern)
            continue
        for source in matches:
            if source in seen_sources or not source.is_file():
                continue
            seen_sources.add(source)
            relative = source.relative_to(run_dir)
            destination = staging_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied.append(str(relative))
    return copied, missing


def _print_human_report(report: dict[str, Any]) -> None:
    print("WOD2Sim support bundle")
    print(f"  valid: {report['valid']}")
    print(f"  run dir: {report['run_dir']}")
    print(f"  bundle path: {report['bundle_path']}")
    print(f"  copied files: {report['copied_file_count']}")
    print(f"  missing patterns: {report['missing_file_count']}")
    run_audit = report["run_audit"]
    print(f"  run audit valid: {run_audit['valid']}")
    print(f"  sensor pipeline ok: {run_audit['sensor_pipeline_ok']}")
    print(f"  sensor failures: {run_audit['sensor_failure_count']}")
    print(f"  driver log: {run_audit['driver_log_kind'] or 'missing'}")
    if report["missing_files"]:
        print("  missing patterns:")
        for pattern in report["missing_files"]:
            print(f"    - {pattern}")


def main() -> int:
    args = _parse_args()
    report = build_report(run_dir=args.run_dir, output=args.output)
    if args.output_report is not None:
        args.output_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human_report(report)
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
