#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from wod2sim.cli.runtime_paths import workspace_path

from wod2sim.cli.commands.audit_run import build_report as build_run_audit_report
from wod2sim.cli.commands.run_alpasim_local_external import RUN_STATUS_FILENAME
from wod2sim.cli.commands.run_alpasim_local_external import DEFAULT_RUNS_ROOT, PUBLIC_RELEASE_MODELS, SCENE_PRESETS, _scene_ids


RUNNER_CWD = workspace_path()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run AlpaSim local-external evaluations scene-by-scene so each scene becomes a clean "
            "statistical unit for downstream transfer audits."
        )
    )
    parser.add_argument("--mode", choices=("print", "both"), default="print")
    parser.add_argument("--model", choices=PUBLIC_RELEASE_MODELS, required=True)
    parser.add_argument("--scene-preset", choices=tuple(SCENE_PRESETS), default="fresh_3scene")
    parser.add_argument("--scene-id", action="append", default=[])
    parser.add_argument("--batch-dir", type=Path, default=None)
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--baseport", type=int, default=6000)
    parser.add_argument("--port", type=int, default=6789)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--topology", default="1gpu")
    parser.add_argument("--driver-warmup-seconds", type=float, default=10.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--wizard-dry-run", action="store_true")
    parser.add_argument("--wizard-arg", action="append", default=[])
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--oracle-actor-proxy", type=Path, default=None)
    parser.add_argument("--alpasim-root", type=Path, default=None)
    parser.add_argument("--allow-existing-batch-dir", action="store_true")
    parser.add_argument("--rerun-existing", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--scene-offset", type=int, default=0)
    parser.add_argument("--scene-limit", type=int, default=None)
    return parser


def _parse_args() -> argparse.Namespace:
    return _build_parser().parse_args()


def main() -> int:
    args = _parse_args()
    scene_ids = _selected_scene_ids(args)
    batch_dir = _resolve_batch_dir(args)
    _prepare_batch_dir(batch_dir, allow_existing=args.allow_existing_batch_dir)

    manifest = {
        "schema": "alpasim_scene_batch_v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "mode": args.mode,
        "model": args.model,
        "scene_preset": args.scene_preset,
        "scene_ids": scene_ids,
        "topology": args.topology,
        "timeout": args.timeout,
        "max_retries": args.max_retries,
        "baseport": args.baseport,
        "port": args.port,
        "wizard_args": list(args.wizard_arg),
        "oracle_actor_proxy": str(args.oracle_actor_proxy) if args.oracle_actor_proxy else None,
        "runs": [],
    }
    _write_json(batch_dir / "batch-manifest.json", manifest)

    statuses: list[dict[str, Any]] = []
    for index, scene_id in enumerate(scene_ids, start=args.scene_offset + 1):
        run_dir = batch_dir / f"{index:03d}_{scene_id}"
        command = _scene_command(args, scene_id=scene_id, run_dir=run_dir)
        status = _scene_status(run_dir)
        row = {
            "index": index,
            "scene_id": scene_id,
            "run_dir": str(run_dir),
            "command": command,
            "status": status,
            "diagnostics": _scene_diagnostics(run_dir),
        }
        if status == "completed" and not args.rerun_existing:
            statuses.append(
                {
                    **row,
                    "result": "skipped_completed",
                    "returncode": 0,
                    "diagnostics": _scene_diagnostics(run_dir),
                }
            )
            continue

        if args.mode == "print":
            statuses.append(
                {
                    **row,
                    "result": "planned",
                    "returncode": 0,
                    "diagnostics": _scene_diagnostics(run_dir),
                }
            )
            continue

        run_dir.mkdir(parents=True, exist_ok=True)
        returncode, attempts = _run_scene_with_retries(command, cwd=RUNNER_CWD, max_retries=args.max_retries)
        result = "completed" if returncode == 0 else "failed"
        diagnostics = _scene_diagnostics(run_dir)
        statuses.append(
            {
                **row,
                "status": _scene_status(run_dir),
                "result": result,
                "returncode": int(returncode),
                "attempts": attempts,
                "diagnostics": diagnostics,
            }
        )
        _write_json(
            batch_dir / "batch-status.json",
            _build_batch_summary(
                batch_dir=batch_dir,
                mode=args.mode,
                model=args.model,
                scene_count=len(scene_ids),
                statuses=statuses,
            ),
        )
        if returncode != 0 and not args.continue_on_error:
            break

    summary = _build_batch_summary(
        batch_dir=batch_dir,
        mode=args.mode,
        model=args.model,
        scene_count=len(scene_ids),
        statuses=statuses,
    )
    _write_json(batch_dir / "batch-status.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not summary["failed_runs"] else 1


def _selected_scene_ids(args: argparse.Namespace) -> list[str]:
    scene_ids = _scene_ids(args.scene_preset, args.scene_id)
    start = max(0, int(args.scene_offset))
    stop = None if args.scene_limit is None else start + max(0, int(args.scene_limit))
    sliced = scene_ids[start:stop]
    if not sliced:
        raise ValueError("scene selection is empty")
    return sliced


def _resolve_batch_dir(args: argparse.Namespace) -> Path:
    if args.batch_dir is not None:
        return args.batch_dir.resolve()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"alpasim_batch_{args.model}_{args.scene_preset}_{stamp}"
    return (args.runs_root.resolve() / name)


def _prepare_batch_dir(batch_dir: Path, *, allow_existing: bool) -> None:
    if batch_dir.exists():
        if not allow_existing:
            raise SystemExit(f"Batch dir already exists: {batch_dir}")
    else:
        batch_dir.mkdir(parents=True)


def _scene_command(args: argparse.Namespace, *, scene_id: str, run_dir: Path) -> list[str]:
    command = [
        str(args.python),
        "-m",
        "wod2sim.cli.commands.run_alpasim_local_external",
        "--mode",
        args.mode,
        "--model",
        args.model,
        "--scene-id",
        scene_id,
        "--run-dir",
        str(run_dir),
        "--allow-existing-run-dir",
        "--baseport",
        str(args.baseport),
        "--port",
        str(args.port),
        "--timeout",
        str(args.timeout),
        "--topology",
        str(args.topology),
        "--driver-warmup-seconds",
        str(args.driver_warmup_seconds),
    ]
    if args.wizard_dry_run:
        command.append("--wizard-dry-run")
    if args.checkpoint is not None:
        command.extend(["--checkpoint", str(args.checkpoint)])
    if args.oracle_actor_proxy is not None:
        command.extend(["--oracle-actor-proxy", str(args.oracle_actor_proxy)])
    if args.alpasim_root is not None:
        command.extend(["--alpasim-root", str(args.alpasim_root)])
    for override in args.wizard_arg:
        command.extend(["--wizard-arg", override])
    return command


def _scene_status(run_dir: Path) -> str:
    aggregate_dir = run_dir / "aggregate"
    if any(
        candidate.is_file()
        for candidate in (
            aggregate_dir / "metrics_unprocessed.parquet",
            aggregate_dir / "metrics_results.parquet",
            aggregate_dir / "metrics_results.txt",
        )
    ):
        return "completed"
    if run_dir.exists():
        return "partial"
    return "missing"


def _run_scene_with_retries(command: list[str], *, cwd: Path, max_retries: int) -> tuple[int, int]:
    attempts = 0
    last_returncode = 0
    for _ in range(max(0, int(max_retries)) + 1):
        attempts += 1
        last_returncode = subprocess.run(command, cwd=cwd, check=False).returncode
        if last_returncode == 0 and _scene_artifacts_complete(command):
            break
        last_returncode = 1
        _cleanup_failed_scene(command, cwd=cwd)
    return int(last_returncode), attempts


def _cleanup_failed_scene(command: list[str], *, cwd: Path) -> None:
    run_dir = _extract_run_dir(command)
    if run_dir is None:
        return
    compose_path = run_dir / "docker-compose.yaml"
    if not compose_path.is_file():
        return
    subprocess.run(
        ["docker", "compose", "-f", str(compose_path), "down", "-v"],
        cwd=cwd,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _extract_run_dir(command: list[str]) -> Path | None:
    try:
        index = command.index("--run-dir")
    except ValueError:
        return None
    if index + 1 >= len(command):
        return None
    return Path(command[index + 1])


def _scene_artifacts_complete(command: list[str]) -> bool:
    run_dir = _extract_run_dir(command)
    if run_dir is None:
        return False
    return _scene_status(run_dir) == "completed"


def _scene_diagnostics(run_dir: Path) -> dict[str, Any]:
    run_status = _load_json_if_exists(run_dir / RUN_STATUS_FILENAME)
    if not run_dir.exists():
        return {
            "run_status_present": False,
            "state": None,
            "phase": None,
            "aggregate_status": None,
            "driver_returncode": None,
            "wizard_returncode": None,
            "driver_log_present": False,
            "driver_log_kind": None,
            "driver_log_path": None,
            "run_audit_valid": False,
            "frame_count": 0,
            "sensor_pipeline_ok": None,
            "sensor_failure_count": None,
            "first_sensor_failure": None,
        }

    audit = build_run_audit_report(run_dir=run_dir)
    driver_log = audit.get("driver_log", {})
    driver_log_present = bool(driver_log.get("present"))
    return {
        "run_status_present": bool(run_status),
        "state": run_status.get("state"),
        "phase": run_status.get("phase"),
        "aggregate_status": run_status.get("aggregate_status"),
        "driver_returncode": run_status.get("driver_returncode"),
        "wizard_returncode": run_status.get("wizard_returncode"),
        "driver_log_present": driver_log_present,
        "driver_log_kind": driver_log.get("kind"),
        "driver_log_path": driver_log.get("path"),
        "run_audit_valid": bool(audit.get("valid")),
        "frame_count": int(audit.get("frame_count", 0)),
        "sensor_pipeline_ok": audit.get("sensor_pipeline_ok") if driver_log_present else None,
        "sensor_failure_count": int(audit.get("sensor_failure_count", 0)) if driver_log_present else None,
        "first_sensor_failure": audit.get("first_sensor_failure") if driver_log_present else None,
    }


def _build_batch_summary(
    *,
    batch_dir: Path,
    mode: str,
    model: str,
    scene_count: int,
    statuses: list[dict[str, Any]],
) -> dict[str, Any]:
    status_counts = Counter(str(row.get("status", "unknown")) for row in statuses)
    result_counts = Counter(str(row.get("result", "unknown")) for row in statuses)
    run_state_counts = Counter(
        str(row.get("diagnostics", {}).get("state") or "missing")
        for row in statuses
    )
    aggregate_status_counts = Counter(
        str(row.get("diagnostics", {}).get("aggregate_status") or "missing")
        for row in statuses
    )
    sensor_failure_runs = [
        row["run_dir"]
        for row in statuses
        if (row.get("diagnostics", {}).get("sensor_failure_count") or 0) > 0
    ]
    return {
        "schema": "alpasim_scene_batch_summary_v1",
        "batch_dir": str(batch_dir),
        "mode": mode,
        "model": model,
        "scene_count": scene_count,
        "completed_runs": [row["run_dir"] for row in statuses if row["result"] == "completed"],
        "planned_runs": [row["run_dir"] for row in statuses if row["result"] == "planned"],
        "failed_runs": [row["run_dir"] for row in statuses if row["result"] == "failed"],
        "status_counts": dict(sorted(status_counts.items())),
        "result_counts": dict(sorted(result_counts.items())),
        "run_state_counts": dict(sorted(run_state_counts.items())),
        "aggregate_status_counts": dict(sorted(aggregate_status_counts.items())),
        "sensor_failure_runs": sensor_failure_runs,
        "runs": statuses,
    }


def _load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
