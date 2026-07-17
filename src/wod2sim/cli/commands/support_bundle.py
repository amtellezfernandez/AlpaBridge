from __future__ import annotations

import argparse
import gzip
import json
import shutil
import tarfile
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
DETERMINISTIC_TAR_MTIME = 0


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


def build_report(
    *, run_dir: Path, output: Path | None = None, public_root: Path | None = None
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run dir not found: {run_dir}")
    bundle_path = _resolve_output_path(run_dir, output)
    redaction_root = public_root.resolve() if public_root is not None else None
    redact_home = redaction_root is not None

    with tempfile.TemporaryDirectory(prefix="wod2sim-support-bundle-") as tmpdir:
        staging_root = Path(tmpdir) / f"{run_dir.name}_support_bundle"
        redaction_roots = ((staging_root.parent, "<bundle_tmp>"),)
        if redaction_root is not None:
            redaction_roots = ((redaction_root, "<repo>"), *redaction_roots)
        staging_root.mkdir(parents=True, exist_ok=True)
        copied_files, missing_files = _copy_run_artifacts(run_dir, staging_root)

        audit_dir = staging_root / "audit"
        run_audit = build_run_audit_report(run_dir=run_dir, audit_dir=audit_dir)
        run_audit = _redact_paths(run_audit, roots=redaction_roots, redact_home=redact_home)
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
        manifest = _redact_paths(manifest, roots=redaction_roots, redact_home=redact_home)
        manifest_path = staging_root / "support-bundle-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _sanitize_json_files(staging_root, roots=redaction_roots, redact_home=redact_home)

        _write_deterministic_gztar(staging_root=staging_root, bundle_path=bundle_path)

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
            "route_contract_ok": bool(run_audit.get("route_contract_ok")),
            "route_contract_failure_count": int(run_audit.get("route_contract_failure_count", 0)),
            "driver_log_kind": run_audit.get("driver_log", {}).get("kind"),
        },
    }
    if redaction_root is not None:
        report = _redact_paths(
            report,
            roots=((redaction_root, "<repo>"),),
            redact_home=True,
        )
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


def _write_deterministic_gztar(*, staging_root: Path, bundle_path: Path) -> None:
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with bundle_path.open("wb") as raw_file:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_file,
            mtime=DETERMINISTIC_TAR_MTIME,
        ) as gzip_file:
            with tarfile.open(fileobj=gzip_file, mode="w", format=tarfile.PAX_FORMAT) as archive:
                _add_tar_entry(archive, staging_root, staging_root.name)
                for path in sorted(
                    staging_root.rglob("*"),
                    key=lambda item: item.relative_to(staging_root).as_posix(),
                ):
                    arcname = f"{staging_root.name}/{path.relative_to(staging_root).as_posix()}"
                    _add_tar_entry(archive, path, arcname)


def _add_tar_entry(archive: tarfile.TarFile, path: Path, arcname: str) -> None:
    info = tarfile.TarInfo(arcname)
    info.mtime = DETERMINISTIC_TAR_MTIME
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    if path.is_dir():
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        archive.addfile(info)
        return
    if path.is_file():
        info.size = path.stat().st_size
        info.mode = path.stat().st_mode & 0o777
        with path.open("rb") as file_obj:
            archive.addfile(info, file_obj)


def _sanitize_json_files(
    root_dir: Path,
    *,
    roots: tuple[tuple[Path, str], ...],
    redact_home: bool,
) -> None:
    for path in sorted(root_dir.rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(
            json.dumps(
                _redact_paths(payload, roots=roots, redact_home=redact_home),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


def _redact_paths(
    value: Any,
    *,
    roots: tuple[tuple[Path, str], ...],
    redact_home: bool,
) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_paths(item, roots=roots, redact_home=redact_home)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_paths(item, roots=roots, redact_home=redact_home) for item in value]
    if isinstance(value, str):
        text = value
        for root, replacement in roots:
            text = text.replace(str(root), replacement)
        if redact_home:
            home = str(Path.home())
            if all(home != str(root) for root, _ in roots):
                text = text.replace(home, "~")
        return text
    return value


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
    print(f"  route contract ok: {run_audit['route_contract_ok']}")
    print(f"  route contract failures: {run_audit['route_contract_failure_count']}")
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
