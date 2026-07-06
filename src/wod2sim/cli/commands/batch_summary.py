from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

SUMMARY_SCHEMA = "wod2sim_closed_loop_batch_summary_v1"
STATUS_NAME = "batch-status.json"
MANIFEST_NAME = "batch-manifest.json"

CORE_METRICS = (
    "collision_any",
    "collision_at_fault",
    "offroad",
    "wrong_lane",
    "offroad_or_collision",
    "offroad_or_collision_at_fault",
    "progress",
    "progress_rel",
    "dist_to_gt_trajectory",
    "dist_to_gt_location",
    "dist_traveled_m",
    "plan_deviation",
    "duration_frac_20s",
    "img_is_black",
    "safety_monitor_triggered",
)

RATE_METRICS = frozenset(
    {
        "collision_any",
        "collision_at_fault",
        "offroad",
        "wrong_lane",
        "offroad_or_collision",
        "offroad_or_collision_at_fault",
        "img_is_black",
        "safety_monitor_triggered",
    }
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a compact, public-safe summary from a wod2sim-batch directory. "
            "The summary records metrics, failures, and hashes without embedding gated media."
        )
    )
    parser.add_argument("--batch-dir", type=Path, default=None, help="Directory created by wod2sim-batch.")
    parser.add_argument(
        "--batch-status",
        type=Path,
        default=None,
        help="Explicit batch-status.json path. Defaults to --batch-dir/batch-status.json.",
    )
    parser.add_argument(
        "--merge-summary",
        type=Path,
        action="append",
        default=[],
        help=(
            "Public-safe wod2sim-batch-summary JSON to merge. Repeat for each shard. "
            "Cannot be combined with --batch-dir or --batch-status."
        ),
    )
    parser.add_argument(
        "--expected-scene-count",
        type=int,
        default=None,
        help="Expected full-stage scene count when merging shard summaries.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON summary output path.")
    parser.add_argument("--json", action="store_true", help="Print the summary as JSON.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit nonzero unless every planned scene completed with a clean sensor pipeline.",
    )
    parser.add_argument(
        "--low-progress-threshold",
        type=float,
        default=0.5,
        help="Progress value below which a scene is counted as low-progress.",
    )
    parser.add_argument(
        "--high-plan-deviation-threshold",
        type=float,
        default=4.0,
        help="Plan-deviation value above which a scene is counted as high-deviation.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.merge_summary:
        if args.batch_dir is not None or args.batch_status is not None:
            raise SystemExit("--merge-summary cannot be combined with --batch-dir or --batch-status.")
        summary = merge_summaries(
            summary_paths=args.merge_summary,
            expected_scene_count=args.expected_scene_count,
            low_progress_threshold=args.low_progress_threshold,
            high_plan_deviation_threshold=args.high_plan_deviation_threshold,
        )
    else:
        summary = build_summary(
            batch_dir=args.batch_dir,
            batch_status=args.batch_status,
            low_progress_threshold=args.low_progress_threshold,
            high_plan_deviation_threshold=args.high_plan_deviation_threshold,
        )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        _print_human_summary(summary)
    if args.strict and not summary["clean_closed_loop_batch"]:
        return 1
    return 0 if summary["valid"] else 1


def build_summary(
    *,
    batch_dir: Path | None = None,
    batch_status: Path | None = None,
    low_progress_threshold: float = 0.5,
    high_plan_deviation_threshold: float = 4.0,
) -> dict[str, Any]:
    status_path = _resolve_status_path(batch_dir=batch_dir, batch_status=batch_status)
    root = status_path.parent
    status = _load_json(status_path)
    manifest = _load_json(root / MANIFEST_NAME, required=False)
    runs = [
        _summarize_run(root=root, row=row)
        for row in _list_value(status.get("runs"))
        if isinstance(row, dict)
    ]
    aggregate = _aggregate_runs(
        runs,
        planned_scene_count=_planned_scene_count(status=status, manifest=manifest),
    )
    failure_taxonomy = _failure_taxonomy(
        runs,
        low_progress_threshold=low_progress_threshold,
        high_plan_deviation_threshold=high_plan_deviation_threshold,
    )
    clean_closed_loop_batch = bool(runs) and aggregate["completed_scene_count"] == aggregate[
        "planned_scene_count"
    ] and not (
        aggregate["failed_scene_count"]
        or aggregate["sensor_failure_scene_count"]
        or aggregate["missing_aggregate_scene_count"]
    )

    return {
        "schema": SUMMARY_SCHEMA,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "valid": bool(runs),
        "clean_closed_loop_batch": clean_closed_loop_batch,
        "claim_boundary": (
            "This is local closed-loop AlpaSim evidence generated from user-provided or gated "
            "scene assets. The summary intentionally excludes raw scene assets and videos."
        ),
        "source": {
            "batch_dir_name": root.name,
            "batch_status": STATUS_NAME,
            "batch_manifest": MANIFEST_NAME if (root / MANIFEST_NAME).is_file() else None,
        },
        "run_config": {
            "mode": status.get("mode") or manifest.get("mode"),
            "model": status.get("model") or manifest.get("model"),
            "scene_preset": manifest.get("scene_preset"),
            "topology": manifest.get("topology"),
            "timeout": manifest.get("timeout"),
            "max_retries": manifest.get("max_retries"),
        },
        "artifact_policy": {
            "raw_scene_assets_included": False,
            "raw_rollout_videos_included": False,
            "local_video_hashes_are_recorded": True,
            "redistribution_note": (
                "Do not publish rollout frames or videos unless the Waymo/AlpaSim asset terms "
                "explicitly permit redistribution."
            ),
        },
        "aggregate": aggregate,
        "metrics": _aggregate_metrics(runs),
        "failure_taxonomy": failure_taxonomy,
        "open_loop_closed_loop_mismatch": {
            "open_loop_reference_available": False,
            "status": "closed_loop_only_summary",
            "closed_loop_failure_indicators": {
                key: failure_taxonomy[key]
                for key in (
                    "collision_scene_count",
                    "offroad_scene_count",
                    "wrong_lane_scene_count",
                    "low_progress_scene_count",
                    "high_plan_deviation_scene_count",
                )
            },
            "advice": (
                "Add paired open-loop metrics per scene to claim measured mismatch; this file "
                "currently reports closed-loop failures that open-loop evaluation should be "
                "compared against."
            ),
        },
        "runs": runs,
    }


def merge_summaries(
    *,
    summary_paths: list[Path],
    expected_scene_count: int | None = None,
    low_progress_threshold: float = 0.5,
    high_plan_deviation_threshold: float = 4.0,
) -> dict[str, Any]:
    inputs = [_load_json(path) for path in summary_paths]
    errors = _merge_errors(inputs=inputs, expected_scene_count=expected_scene_count)
    runs = [
        run
        for summary in inputs
        for run in _list_value(summary.get("runs"))
        if isinstance(run, dict)
    ]
    runs.sort(key=lambda run: (_int_or_zero(run.get("index")), str(run.get("scene_id") or "")))
    planned_scene_count = expected_scene_count or sum(
        _int_or_zero(_dict_value(summary.get("aggregate")).get("planned_scene_count"))
        for summary in inputs
    )
    aggregate = _aggregate_runs(runs, planned_scene_count=planned_scene_count)
    failure_taxonomy = _failure_taxonomy(
        runs,
        low_progress_threshold=low_progress_threshold,
        high_plan_deviation_threshold=high_plan_deviation_threshold,
    )
    valid = bool(inputs) and not errors and all(bool(summary.get("valid")) for summary in inputs)
    clean_closed_loop_batch = valid and bool(runs) and aggregate["completed_scene_count"] == aggregate[
        "planned_scene_count"
    ] and not (
        aggregate["failed_scene_count"]
        or aggregate["sensor_failure_scene_count"]
        or aggregate["missing_aggregate_scene_count"]
    )

    return {
        "schema": SUMMARY_SCHEMA,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "valid": valid,
        "clean_closed_loop_batch": clean_closed_loop_batch,
        "claim_boundary": (
            "This is a merged public-safe summary built from shard-level WOD2Sim closed-loop "
            "batch summaries. It intentionally excludes raw scene assets and videos."
        ),
        "source": {
            "summary_kind": "merged_batch_summaries",
            "batch_dir_name": None,
            "batch_status": None,
            "batch_manifest": None,
            "input_summaries": [str(path) for path in summary_paths],
        },
        "run_config": _merge_run_config(inputs),
        "artifact_policy": {
            "raw_scene_assets_included": False,
            "raw_rollout_videos_included": False,
            "local_video_hashes_are_recorded": True,
            "redistribution_note": (
                "Do not publish rollout frames or videos unless the Waymo/AlpaSim asset terms "
                "explicitly permit redistribution."
            ),
        },
        "aggregate": aggregate,
        "metrics": _aggregate_metrics(runs),
        "failure_taxonomy": failure_taxonomy,
        "open_loop_closed_loop_mismatch": {
            "open_loop_reference_available": False,
            "status": "closed_loop_only_summary",
            "closed_loop_failure_indicators": {
                key: failure_taxonomy[key]
                for key in (
                    "collision_scene_count",
                    "offroad_scene_count",
                    "wrong_lane_scene_count",
                    "low_progress_scene_count",
                    "high_plan_deviation_scene_count",
                )
            },
            "advice": (
                "Add paired open-loop metrics per scene to claim measured mismatch; this merged "
                "file currently reports closed-loop failures that open-loop evaluation should be "
                "compared against."
            ),
        },
        "merge": {
            "input_summary_count": len(inputs),
            "input_clean_count": sum(
                1 for summary in inputs if bool(summary.get("clean_closed_loop_batch"))
            ),
            "expected_scene_count": planned_scene_count,
            "errors": errors,
        },
        "runs": runs,
    }


def _resolve_status_path(*, batch_dir: Path | None, batch_status: Path | None) -> Path:
    if batch_status is not None:
        return batch_status.resolve()
    if batch_dir is None:
        raise SystemExit("Provide --batch-dir or --batch-status.")
    return (batch_dir / STATUS_NAME).resolve()


def _summarize_run(*, root: Path, row: dict[str, Any]) -> dict[str, Any]:
    run_dir = Path(str(row.get("run_dir", "")))
    if not run_dir.is_absolute():
        run_dir = root / run_dir
    diagnostics = row.get("diagnostics") if isinstance(row.get("diagnostics"), dict) else {}
    metrics = _load_metrics(run_dir)
    artifacts = _artifact_hashes(root=root, run_dir=run_dir)
    return {
        "index": _int_or_zero(row.get("index")),
        "scene_id": str(row.get("scene_id") or ""),
        "result": str(row.get("result") or row.get("status") or "unknown"),
        "status": str(row.get("status") or "unknown"),
        "run_dir": _relative_or_name(run_dir, root=root),
        "attempts": _int_or_zero(row.get("attempts")),
        "returncode": _optional_int(row.get("returncode")),
        "state": diagnostics.get("state"),
        "aggregate_status": diagnostics.get("aggregate_status"),
        "frame_count": _int_or_zero(diagnostics.get("frame_count")),
        "sensor_pipeline_ok": _optional_bool(diagnostics.get("sensor_pipeline_ok")),
        "sensor_failure_count": _int_or_zero(diagnostics.get("sensor_failure_count")),
        "first_sensor_failure": diagnostics.get("first_sensor_failure"),
        "metrics": metrics,
        "artifacts": artifacts,
    }


def _load_metrics(run_dir: Path) -> dict[str, float | None]:
    txt_path = run_dir / "aggregate" / "metrics_results.txt"
    metrics = _parse_metrics_text(txt_path)
    return {name: metrics.get(name) for name in CORE_METRICS if name in metrics}


def _parse_metrics_text(path: Path) -> dict[str, float | None]:
    if not path.is_file():
        return {}
    metrics: dict[str, float | None] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped.startswith("│") or "Metric Name" in stripped:
            continue
        parts = [part.strip() for part in stripped.strip("│").split("│")]
        if len(parts) < 2:
            continue
        name, raw_value = parts[0], parts[1]
        if not name or set(name) <= {"─", "━", "╇", "┄"}:
            continue
        metrics[name] = _float_or_none(raw_value)
    return metrics


def _artifact_hashes(*, root: Path, run_dir: Path) -> dict[str, Any]:
    metrics_txt = run_dir / "aggregate" / "metrics_results.txt"
    metrics_png = run_dir / "aggregate" / "metrics_results.png"
    videos = sorted((run_dir / "rollouts").glob("**/*.mp4")) if (run_dir / "rollouts").exists() else []
    return {
        "metrics_results_txt": _file_record(metrics_txt, root=root, gated_media=False),
        "metrics_results_png": _file_record(metrics_png, root=root, gated_media=False),
        "rollout_videos": [
            _file_record(path, root=root, gated_media=True)
            for path in videos[:3]
        ],
        "rollout_video_count": len(videos),
    }


def _file_record(path: Path, *, root: Path, gated_media: bool) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return {
        "path": _relative_or_name(path, root=root),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "gated_scene_media": gated_media,
    }


def _aggregate_runs(runs: list[dict[str, Any]], *, planned_scene_count: int) -> dict[str, Any]:
    result_counts = Counter(str(run["result"]) for run in runs)
    state_counts = Counter(str(run.get("state") or "unknown") for run in runs)
    aggregate_status_counts = Counter(str(run.get("aggregate_status") or "unknown") for run in runs)
    completed = [run for run in runs if run["result"] in {"completed", "skipped_completed"}]
    failed = [run for run in runs if run["result"] == "failed"]
    sensor_failed = [
        run
        for run in runs
        if run["sensor_failure_count"] > 0 or run.get("sensor_pipeline_ok") is False
    ]
    missing_aggregate = [
        run
        for run in runs
        if run["result"] in {"completed", "skipped_completed"}
        and run.get("aggregate_status") != "completed"
    ]
    return {
        "planned_scene_count": planned_scene_count or len(runs),
        "observed_scene_count": len(runs),
        "completed_scene_count": len(completed),
        "failed_scene_count": len(failed),
        "sensor_failure_scene_count": len(sensor_failed),
        "missing_aggregate_scene_count": len(missing_aggregate),
        "total_audited_frames": sum(int(run["frame_count"]) for run in runs),
        "result_counts": dict(sorted(result_counts.items())),
        "run_state_counts": dict(sorted(state_counts.items())),
        "aggregate_status_counts": dict(sorted(aggregate_status_counts.items())),
    }


def _aggregate_metrics(runs: list[dict[str, Any]]) -> dict[str, dict[str, float | int | str]]:
    values_by_metric: dict[str, list[float]] = {name: [] for name in CORE_METRICS}
    for run in runs:
        metrics = run.get("metrics") if isinstance(run.get("metrics"), dict) else {}
        for name in CORE_METRICS:
            value = metrics.get(name)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                values_by_metric[name].append(float(value))

    summary: dict[str, dict[str, float | int | str]] = {}
    for name, values in values_by_metric.items():
        if not values:
            continue
        item: dict[str, float | int | str] = {
            "count": len(values),
            "mean": round(sum(values) / len(values), 6),
            "min": round(min(values), 6),
            "max": round(max(values), 6),
        }
        if name in RATE_METRICS:
            item["interpretation"] = "scene_rate"
        summary[name] = item
    return summary


def _failure_taxonomy(
    runs: list[dict[str, Any]],
    *,
    low_progress_threshold: float,
    high_plan_deviation_threshold: float,
) -> dict[str, Any]:
    collision = _metric_positive(runs, "collision_any")
    at_fault_collision = _metric_positive(runs, "collision_at_fault")
    offroad = _metric_positive(runs, "offroad")
    wrong_lane = _metric_positive(runs, "wrong_lane")
    black_image = _metric_positive(runs, "img_is_black")
    safety_monitor = _metric_positive(runs, "safety_monitor_triggered")
    low_progress = _metric_below(runs, "progress", low_progress_threshold)
    high_plan_deviation = _metric_above(runs, "plan_deviation", high_plan_deviation_threshold)
    runtime_failed = [run for run in runs if run["result"] == "failed"]
    sensor_failed = [
        run
        for run in runs
        if run["sensor_failure_count"] > 0 or run.get("sensor_pipeline_ok") is False
    ]
    return {
        "runtime_failed_scene_count": len(runtime_failed),
        "sensor_pipeline_failure_scene_count": len(sensor_failed),
        "collision_scene_count": len(collision),
        "at_fault_collision_scene_count": len(at_fault_collision),
        "offroad_scene_count": len(offroad),
        "wrong_lane_scene_count": len(wrong_lane),
        "black_image_scene_count": len(black_image),
        "safety_monitor_scene_count": len(safety_monitor),
        "low_progress_scene_count": len(low_progress),
        "high_plan_deviation_scene_count": len(high_plan_deviation),
        "thresholds": {
            "low_progress_lt": low_progress_threshold,
            "high_plan_deviation_gt_m": high_plan_deviation_threshold,
        },
    }


def _metric_positive(runs: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [
        run
        for run in runs
        if isinstance(run.get("metrics"), dict)
        and isinstance(run["metrics"].get(name), (int, float))
        and float(run["metrics"][name]) > 0.0
    ]


def _metric_below(runs: list[dict[str, Any]], name: str, threshold: float) -> list[dict[str, Any]]:
    return [
        run
        for run in runs
        if isinstance(run.get("metrics"), dict)
        and isinstance(run["metrics"].get(name), (int, float))
        and float(run["metrics"][name]) < threshold
    ]


def _metric_above(runs: list[dict[str, Any]], name: str, threshold: float) -> list[dict[str, Any]]:
    return [
        run
        for run in runs
        if isinstance(run.get("metrics"), dict)
        and isinstance(run["metrics"].get(name), (int, float))
        and float(run["metrics"][name]) > threshold
    ]


def _load_json(path: Path, *, required: bool = True) -> dict[str, Any]:
    if not path.is_file():
        if required:
            raise SystemExit(f"Missing JSON file: {path}")
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected JSON object: {path}")
    return payload


def _planned_scene_count(*, status: dict[str, Any], manifest: dict[str, Any]) -> int:
    explicit = _int_or_zero(status.get("scene_count"))
    if explicit:
        return explicit
    scene_ids = manifest.get("scene_ids")
    return len(scene_ids) if isinstance(scene_ids, list) else 0


def _merge_errors(*, inputs: list[dict[str, Any]], expected_scene_count: int | None) -> list[str]:
    errors: list[str] = []
    if not inputs:
        errors.append("no_input_summaries")
        return errors

    run_configs = [_dict_value(summary.get("run_config")) for summary in inputs]
    models = sorted({str(config.get("model") or "") for config in run_configs})
    presets = sorted({str(config.get("scene_preset") or "") for config in run_configs})
    if len(models) > 1:
        errors.append(f"mixed_models:{','.join(models)}")
    if len(presets) > 1:
        errors.append(f"mixed_scene_presets:{','.join(presets)}")

    for index, summary in enumerate(inputs, start=1):
        if summary.get("schema") != SUMMARY_SCHEMA:
            errors.append(f"summary_{index}_schema_mismatch:{summary.get('schema')}")
        if not summary.get("valid"):
            errors.append(f"summary_{index}_invalid")
        if not summary.get("clean_closed_loop_batch"):
            errors.append(f"summary_{index}_not_clean")

    scene_ids = [
        str(run.get("scene_id") or "")
        for summary in inputs
        for run in _list_value(summary.get("runs"))
        if isinstance(run, dict) and str(run.get("scene_id") or "")
    ]
    duplicates = sorted(scene_id for scene_id, count in Counter(scene_ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate_scene_ids:{','.join(duplicates[:8])}")

    observed_scene_count = len(scene_ids)
    planned_scene_count = expected_scene_count or sum(
        _int_or_zero(_dict_value(summary.get("aggregate")).get("planned_scene_count"))
        for summary in inputs
    )
    if planned_scene_count != observed_scene_count:
        errors.append(f"scene_count_mismatch:planned={planned_scene_count},observed={observed_scene_count}")
    return errors


def _merge_run_config(inputs: list[dict[str, Any]]) -> dict[str, Any]:
    configs = [_dict_value(summary.get("run_config")) for summary in inputs]
    first = configs[0] if configs else {}
    return {
        "mode": first.get("mode"),
        "model": first.get("model"),
        "scene_preset": first.get("scene_preset"),
        "topology": first.get("topology"),
        "timeout": first.get("timeout"),
        "max_retries": first.get("max_retries"),
    }


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _int_or_zero(value: Any) -> int:
    parsed = _optional_int(value)
    return 0 if parsed is None else parsed


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "N/A", "nan", "NaN"):
        return None
    try:
        parsed = float(str(value).strip())
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _relative_or_name(path: Path, *, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return path.name


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _print_human_summary(summary: dict[str, Any]) -> None:
    aggregate = summary["aggregate"]
    print("WOD2Sim closed-loop batch summary")
    print(f"  valid: {summary['valid']}")
    print(f"  clean closed-loop batch: {summary['clean_closed_loop_batch']}")
    print(f"  model: {summary['run_config']['model']}")
    print(f"  scene preset: {summary['run_config']['scene_preset']}")
    print(f"  scenes: {aggregate['completed_scene_count']}/{aggregate['planned_scene_count']} completed")
    print(f"  audited frames: {aggregate['total_audited_frames']}")
    print(f"  sensor-failure scenes: {aggregate['sensor_failure_scene_count']}")
    print(f"  failure taxonomy: {summary['failure_taxonomy']}")
    if summary["metrics"]:
        print("  metrics:")
        for name, item in summary["metrics"].items():
            print(f"    {name}: mean={item['mean']} count={item['count']}")


if __name__ == "__main__":
    raise SystemExit(main())
