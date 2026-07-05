from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from wod2sim.audit import export_alpasim_audit_log, summarize_audit_log


DRIVER_LOG_SPECS = (
    ("spotlight_reflex", "spotlight", "driver/spotlight-log.jsonl"),
    ("token_dagger_bc", "selection", "driver/selection-log.jsonl"),
    ("direct_actor_planner", "direct_planner", "driver/direct-planner-log.jsonl"),
)
FAILED_SENSOR_STATUSES = frozenset(
    {
        "stale_pose_leads_camera",
        "stale_camera_timestamp",
        "frozen_camera_content",
    }
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize a completed WOD2Sim/AlpaSim run and surface camera-pipeline failures."
    )
    parser.add_argument("--run-dir", type=Path, required=True, help="Completed run directory to inspect.")
    parser.add_argument(
        "--audit-dir",
        type=Path,
        default=None,
        help="Optional output directory for a normalized audit export bundle.",
    )
    parser.add_argument("--json", action="store_true", help="Print the audit report as JSON.")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero if the run audit is not clean.")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    return parser.parse_args()


def build_report(*, run_dir: Path, audit_dir: Path | None = None) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    launch_metadata = _load_json_if_exists(run_dir / "launch-metadata.json")
    run_status = _load_json_if_exists(run_dir / "run-status.json")
    preferred_model = str(launch_metadata.get("model", "") or "")
    driver_log_kind, driver_log_path, driver_rows = _select_driver_log(run_dir, preferred_model=preferred_model)

    result_counts = Counter(str(row.get("result", "unknown")) for row in driver_rows)
    sensor_status_counts = Counter(_sensor_status(row) for row in driver_rows)
    sensor_failures = [
        {
            "frame_index": int(row.get("frame_index", 0)),
            "scene_id": row.get("scene_id"),
            "status": _sensor_status(row),
            "result": str(row.get("result", "unknown")),
            "error": row.get("sensor_error"),
            "pose_camera_lag_us": _pose_camera_lag_us(row),
        }
        for row in driver_rows
        if _is_sensor_failure(row)
    ]
    pose_camera_lags = [lag for lag in (_pose_camera_lag_us(row) for row in driver_rows) if lag is not None]

    audit_export = None
    if audit_dir is not None:
        audit_dir = audit_dir.resolve()
        manifest = export_alpasim_audit_log(run_dir, audit_dir)
        audit_summary = summarize_audit_log(audit_dir)
        audit_export = {
            "requested": True,
            "audit_dir": str(audit_dir),
            "manifest_path": str(audit_dir / "manifest.json"),
            "frame_count": int(audit_summary.get("frame_count", 0)),
            "bookmark_count": int(audit_summary.get("bookmark_count", 0)),
            "manifest": manifest,
        }

    driver_log_present = driver_log_path is not None
    sensor_pipeline_ok = driver_log_present and not sensor_failures
    valid = driver_log_present and bool(driver_rows) and sensor_pipeline_ok

    report = {
        "schema": "wod2sim_run_audit_v1",
        "valid": valid,
        "run_dir": str(run_dir),
        "model": preferred_model or None,
        "scene_preset": launch_metadata.get("scene_preset"),
        "scene_ids": launch_metadata.get("scene_ids", []),
        "run_status": {
            "present": bool(run_status),
            "state": run_status.get("state"),
            "phase": run_status.get("phase"),
            "driver_returncode": run_status.get("driver_returncode"),
            "wizard_returncode": run_status.get("wizard_returncode"),
            "aggregate_status": run_status.get("aggregate_status"),
            "completed_at": run_status.get("completed_at"),
        },
        "driver_log": {
            "kind": driver_log_kind,
            "path": None if driver_log_path is None else str(driver_log_path),
            "present": driver_log_present,
        },
        "frame_count": len(driver_rows),
        "sensor_pipeline_ok": sensor_pipeline_ok,
        "sensor_failure_count": len(sensor_failures),
        "result_counts": dict(sorted(result_counts.items())),
        "sensor_status_counts": dict(sorted(sensor_status_counts.items())),
        "max_pose_camera_lag_us": max(pose_camera_lags) if pose_camera_lags else None,
        "first_sensor_failure": sensor_failures[0] if sensor_failures else None,
        "audit_export": audit_export,
        "advice": _advice(
            run_dir=run_dir,
            driver_log_path=driver_log_path,
            driver_rows=driver_rows,
            sensor_failures=sensor_failures,
        ),
    }
    return report


def _load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _load_jsonl_if_exists(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _select_driver_log(run_dir: Path, *, preferred_model: str) -> tuple[str | None, Path | None, list[dict[str, Any]]]:
    preferred = None
    for model_name, kind, relative in DRIVER_LOG_SPECS:
        if model_name == preferred_model:
            preferred = (kind, run_dir / relative)
            break
    if preferred is not None:
        rows = _load_jsonl_if_exists(preferred[1])
        if rows or preferred[1].is_file():
            return preferred[0], preferred[1], rows

    for _, kind, relative in DRIVER_LOG_SPECS:
        path = run_dir / relative
        rows = _load_jsonl_if_exists(path)
        if rows:
            return kind, path, rows
    for _, kind, relative in DRIVER_LOG_SPECS:
        path = run_dir / relative
        if path.is_file():
            return kind, path, []
    return None, None, []


def _sensor_status(row: dict[str, Any]) -> str:
    sensor_freshness = row.get("sensor_freshness")
    if not isinstance(sensor_freshness, dict):
        return "missing"
    status = sensor_freshness.get("status")
    return str(status) if status not in (None, "") else "missing"


def _pose_camera_lag_us(row: dict[str, Any]) -> int | None:
    sensor_freshness = row.get("sensor_freshness")
    if not isinstance(sensor_freshness, dict):
        return None
    value = sensor_freshness.get("pose_camera_lag_us")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_sensor_failure(row: dict[str, Any]) -> bool:
    result = str(row.get("result", ""))
    status = _sensor_status(row)
    return result == "sensor_failure" or status in FAILED_SENSOR_STATUSES


def _advice(
    *,
    run_dir: Path,
    driver_log_path: Path | None,
    driver_rows: list[dict[str, Any]],
    sensor_failures: list[dict[str, Any]],
) -> list[str]:
    advice: list[str] = []
    if driver_log_path is None:
        advice.append(
            "No public driver log was found. This command expects an executed run dir, not a --mode print plan."
        )
        return advice
    if not driver_rows:
        advice.append(f"Driver log exists but contains no rows: {driver_log_path}")
        return advice
    advice.append(f"Inspect the structured driver log first: {driver_log_path}")
    if sensor_failures:
        status = str(sensor_failures[0].get("status", "unknown"))
        if status in {"stale_pose_leads_camera", "stale_camera_timestamp", "frozen_camera_content"}:
            advice.append(
                "The failure is upstream of the policy adapter. Inspect the AlpaSim/sensorsim camera pipeline before tuning the policy."
            )
        advice.append(
            "If you need a normalized audit bundle, rerun this command with --audit-dir /path/to/audit."
        )
        return advice
    advice.append(
        "No camera-pipeline failures were detected in the structured driver log. If the run still failed, inspect controller/runtime artifacts next."
    )
    if not (run_dir / "aggregate").exists():
        advice.append("The run has no aggregate output yet. Finish the rollout before comparing metrics.")
    return advice


def _print_human_report(report: dict[str, Any]) -> None:
    print("WOD2Sim run audit")
    print(f"  valid: {report['valid']}")
    print(f"  run dir: {report['run_dir']}")
    print(f"  model: {report['model'] or 'unknown'}")
    print(f"  scene preset: {report['scene_preset'] or 'unknown'}")
    print(f"  scene count: {len(report['scene_ids'])}")
    run_status = report["run_status"]
    print(f"  run status: {run_status['state'] or 'missing'}")
    if run_status["phase"]:
        print(f"    phase: {run_status['phase']}")
    if run_status["driver_returncode"] is not None or run_status["wizard_returncode"] is not None:
        print(f"    driver returncode: {run_status['driver_returncode']}")
        print(f"    wizard returncode: {run_status['wizard_returncode']}")
    if run_status["aggregate_status"]:
        print(f"    aggregate status: {run_status['aggregate_status']}")
    driver_log = report["driver_log"]
    print(f"  driver log: {driver_log['kind'] or 'missing'}")
    if driver_log["path"]:
        print(f"    path: {driver_log['path']}")
    print(f"  frames: {report['frame_count']}")
    print(f"  sensor pipeline ok: {report['sensor_pipeline_ok']}")
    print(f"  sensor failures: {report['sensor_failure_count']}")
    print(f"  sensor statuses: {report['sensor_status_counts']}")
    print(f"  result counts: {report['result_counts']}")
    if report["max_pose_camera_lag_us"] is not None:
        print(f"  max pose-camera lag us: {report['max_pose_camera_lag_us']}")
    first_failure = report["first_sensor_failure"]
    if first_failure is not None:
        print("  first sensor failure:")
        print(f"    frame: {first_failure['frame_index']}")
        print(f"    status: {first_failure['status']}")
        if first_failure["pose_camera_lag_us"] is not None:
            print(f"    pose-camera lag us: {first_failure['pose_camera_lag_us']}")
        if first_failure["error"]:
            print(f"    error: {first_failure['error']}")
    audit_export = report["audit_export"]
    if isinstance(audit_export, dict):
        print(f"  audit export: {audit_export['audit_dir']}")
        print(f"    frames: {audit_export['frame_count']}")
        print(f"    bookmarks: {audit_export['bookmark_count']}")
    print("  next:")
    for index, line in enumerate(report["advice"], start=1):
        print(f"    {index}. {line}")


def main() -> int:
    args = _parse_args()
    report = build_report(run_dir=args.run_dir, audit_dir=args.audit_dir)
    if args.output is not None:
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human_report(report)
    if args.strict and not report["valid"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
