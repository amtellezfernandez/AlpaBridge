from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .alpasim_metrics import load_alpasim_metrics


LOWER_IS_BETTER_METRICS = frozenset(
    {
        "collision",
        "collision_any",
        "collision_at_fault",
        "collision_front",
        "collision_lateral",
        "collision_rear",
        "dist_to_gt_trajectory",
        "dist_to_gt_location",
        "duration_failure",
        "img_is_black",
        "offroad",
        "offroad_or_collision",
        "offroad_or_collision_at_fault",
        "plan_deviation",
        "route_deviation_m",
        "safety_monitor_triggered",
        "wrong_lane",
    }
)
HIGHER_IS_BETTER_METRICS = frozenset(
    {
        "alpasim_score",
        "avg_dist_between_incidents",
        "avg_dist_between_incidents_at_fault",
        "dist_traveled_m",
        "duration_frac_20s",
        "eval_relevant",
        "progress",
        "progress_rel",
    }
)


def wod_eval_report_to_metric_report(
    path: str | Path,
    *,
    system: str,
    suite: str,
    source: str | None = None,
) -> dict[str, Any]:
    source_path = Path(path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    metrics: dict[str, dict[str, float | bool | str]] = {}
    for field in ("mean_rfs", "median_rfs", "min_rfs", "max_rfs"):
        value = payload.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            metrics[field.replace("mean_", "").replace("median_", "median_")] = {
                "value": float(value),
                "higher_is_better": True,
                "unit": "RFS",
            }
    for field in ("mean_best_candidate_rfs", "mean_selection_regret"):
        value = payload.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            metrics[field.replace("mean_", "")] = {
                "value": float(value),
                "higher_is_better": field == "mean_best_candidate_rfs",
                "unit": "RFS",
            }
    latency = payload.get("mean_latency_ms")
    if isinstance(latency, (int, float)) and not isinstance(latency, bool):
        metrics["mean_latency_ms"] = {"value": float(latency), "higher_is_better": False, "unit": "ms"}
    evaluated = payload.get("evaluated_frames")
    if isinstance(evaluated, int):
        metrics["evaluated_frames"] = {"value": float(evaluated), "higher_is_better": True, "unit": "frames"}
    if not metrics:
        raise ValueError(f"No numeric WOD evaluation metrics found in {source_path}")
    return {
        "system": system,
        "suite": suite,
        "source": source or str(source_path),
        "metrics": metrics,
        "metadata": {
            "evaluation_contract": "wod_e2e_rfs",
            "split": _wod_split_from_suite(suite),
            "frame_count": _optional_int(payload.get("evaluated_frames")),
            "score_backend": str(payload.get("score_backend", "unknown")),
            "selection_mode": str(payload.get("candidate_selection_mode", "unknown")),
        },
        "notes": [
            f"Generated from {source_path}.",
            "Use only against reports from the same WOD-E2E evaluation contract.",
        ],
    }


def wod_cv_report_to_metric_report(
    path: str | Path,
    *,
    system: str,
    suite: str,
    source: str | None = None,
) -> dict[str, Any]:
    source_path = Path(path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    if payload.get("benchmark_type") != "segment_grouped_cross_validation":
        raise ValueError(f"{source_path}: expected segment_grouped_cross_validation report")
    metric_fields = {
        "combined_ranker_mean_rfs": True,
        "combined_oracle_mean_rfs": True,
        "combined_ranker_regret_to_oracle": False,
        "combined_ranker_top1_oracle_match_rate": True,
        "learned_mean_gain_vs_constant_velocity": True,
        "combined_ranker_gain_vs_constant_velocity": True,
    }
    metrics: dict[str, dict[str, float | bool | str]] = {}
    for field, higher_is_better in metric_fields.items():
        value = payload.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            metrics[field] = {
                "value": float(value),
                "higher_is_better": higher_is_better,
                "unit": "rate" if field.endswith("_rate") else "RFS",
            }
    for source_name in ("learned", "temporal", "kinematic", "anchor", "world"):
        field = f"selected_{source_name}_rate"
        value = payload.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            metrics[field] = {"value": float(value), "higher_is_better": True, "unit": "rate"}
    if not metrics:
        raise ValueError(f"No numeric WOD CV metrics found in {source_path}")
    selected_rates: dict[str, float] = {}
    for source_name in ("learned", "temporal", "kinematic", "anchor", "world"):
        field = f"selected_{source_name}_rate"
        value = payload.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            selected_rates[source_name] = float(value)
    notes = [
        f"Generated from {source_path}.",
        "This is an internal held-out development benchmark, not a leaderboard/test score.",
        "Use only against reports from the same WOD-E2E CV contract and score backend.",
    ]
    for note in payload.get("notes", []):
        if isinstance(note, str) and note not in notes:
            notes.append(note)
    return {
        "system": system,
        "suite": suite,
        "source": source or str(source_path),
        "metrics": metrics,
        "metadata": {
            "evaluation_contract": "wod_e2e_rfs",
            "split": f"validation_{payload.get('frames', 0)}_preference_frames_segment_grouped_cv",
            "frame_count": _optional_int(payload.get("frames")),
            "score_backend": str(payload.get("score_backend", "unknown")),
            "selection_mode": "segment_grouped_cv_candidate_ranker",
            "fold_count": _optional_int(payload.get("fold_count")),
            "ridge": payload.get("ridge"),
            "selector_ridge": payload.get("selector_ridge"),
            "selector_target": payload.get("selector_target"),
            "selector_features": payload.get("selector_features"),
            "selector_fallback_router": payload.get("selector_fallback_router"),
            "selected_source_rates": selected_rates,
        },
        "notes": notes,
    }


def scenario_eval_report_to_metric_report(
    path: str | Path,
    *,
    system: str,
    suite: str,
    source: str | None = None,
) -> dict[str, Any]:
    source_path = Path(path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    runs = payload.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError(f"{source_path}: runs must be a non-empty list")
    metrics = _aggregate_run_metrics(runs)
    return {
        "system": system,
        "suite": suite,
        "source": source or str(source_path),
        "metrics": metrics,
        "notes": [
            f"Generated from {source_path}.",
            "Procedural simulator metrics are not WOD-E2E RFS and are not comparable to AlpaSim model-card scores.",
        ],
    }


def alpasim_metrics_report_to_metric_report(
    path: str | Path,
    *,
    system: str,
    suite: str,
    source: str | None = None,
    required_metrics: tuple[str, ...] = (),
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics_path, raw_metrics, run_count = load_alpasim_metrics(path)
    missing = [name for name in required_metrics if name not in raw_metrics]
    if missing:
        raise ValueError(f"{metrics_path}: missing required AlpaSim metric(s): {', '.join(missing)}")
    metrics = _alpasim_metric_specs(raw_metrics)
    if run_count is not None:
        metrics["run_count"] = {"value": float(run_count), "higher_is_better": True, "unit": "runs"}
    return {
        "system": system,
        "suite": suite,
        "source": source or str(metrics_path),
        "metrics": metrics,
        "metadata": _alpasim_metadata(metadata),
        "notes": [
            f"Generated from {metrics_path}.",
            "Use only against reports from the same AlpaSim scenario set and scoring version.",
        ],
    }


def runtime_report_to_metric_report(
    path: str | Path,
    *,
    system: str,
    suite: str,
    source: str | None = None,
) -> dict[str, Any]:
    source_path = Path(path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    total_ms = _required_latency_block(payload, "total_ms", source_path)
    generation_ms = _required_latency_block(payload, "generation_ms", source_path)
    feature_ms = _required_latency_block(payload, "feature_ms", source_path)
    selection_ms = _required_latency_block(payload, "selection_ms", source_path)
    throughput = payload.get("throughput_fps")
    candidate_count = payload.get("candidate_count_mean")
    metrics: dict[str, dict[str, float | bool | str]] = {
        "p95_total_latency_ms": {"value": total_ms["p95"], "higher_is_better": False, "unit": "ms"},
        "mean_total_latency_ms": {"value": total_ms["mean"], "higher_is_better": False, "unit": "ms"},
        "p95_generation_ms": {"value": generation_ms["p95"], "higher_is_better": False, "unit": "ms"},
        "p95_feature_ms": {"value": feature_ms["p95"], "higher_is_better": False, "unit": "ms"},
        "p95_selection_ms": {"value": selection_ms["p95"], "higher_is_better": False, "unit": "ms"},
    }
    if isinstance(throughput, (int, float)) and not isinstance(throughput, bool):
        metrics["throughput_fps"] = {"value": float(throughput), "higher_is_better": True, "unit": "fps"}
    if isinstance(candidate_count, (int, float)) and not isinstance(candidate_count, bool):
        metrics["candidate_count_mean"] = {
            "value": float(candidate_count),
            "higher_is_better": True,
            "unit": "candidates",
        }
    return {
        "system": system,
        "suite": suite,
        "source": source or str(source_path),
        "metrics": metrics,
        "metadata": {
            "runtime_contract": str(payload.get("benchmark_type", "unknown")),
            "frames": _optional_int(payload.get("frames")),
            "warmup": _optional_int(payload.get("warmup")),
            "excludes_io_and_training": True,
        },
        "notes": [
            f"Generated from {source_path}.",
            "Runtime report measures online numeric controller latency only.",
            "Do not compare against model-card quality scores or closed-loop simulator metrics.",
        ],
    }


def _alpasim_metric_specs(raw_metrics: dict[str, float]) -> dict[str, dict[str, float | bool | str]]:
    specs: dict[str, dict[str, float | bool | str]] = {}
    for name, value in sorted(raw_metrics.items()):
        if name in {"n_clips", "n_rollouts"}:
            continue
        specs[name] = {
            "value": value,
            "higher_is_better": _alpasim_higher_is_better(name),
            "unit": _alpasim_metric_unit(name),
        }
    return specs


def _required_latency_block(payload: dict[str, Any], key: str, source_path: Path) -> dict[str, float]:
    raw = payload.get(key)
    if not isinstance(raw, dict):
        raise ValueError(f"{source_path}: missing latency block {key!r}")
    values: dict[str, float] = {}
    for field in ("mean", "p95"):
        value = raw.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{source_path}: {key}.{field} must be numeric")
        values[field] = float(value)
    return values


def _aggregate_run_metrics(runs: list[Any]) -> dict[str, dict[str, float | bool | str]]:
    typed_runs = [run for run in runs if isinstance(run, dict)]
    if not typed_runs:
        raise ValueError("No object runs found")
    count = len(typed_runs)
    metrics: dict[str, dict[str, float | bool | str]] = {
        "run_count": {"value": float(count), "higher_is_better": True, "unit": "runs"},
        "success_rate": {
            "value": _bool_rate(typed_runs, "success"),
            "higher_is_better": True,
            "unit": "rate",
        },
        "collision_rate": {
            "value": _bool_rate(typed_runs, "collision"),
            "higher_is_better": False,
            "unit": "rate",
        },
        "benchmark_pass_rate": {
            "value": _bool_rate(typed_runs, "benchmark_pass"),
            "higher_is_better": True,
            "unit": "rate",
        },
    }
    for source_field, metric_name, higher_is_better, unit in (
        ("min_clearance", "mean_min_clearance_m", True, "m"),
        ("p05_clearance", "mean_p05_clearance_m", True, "m"),
        ("intervention_rate", "mean_intervention_rate", False, "rate"),
        ("avg_progress", "mean_avg_progress", True, "m/step"),
    ):
        value = _mean_numeric(typed_runs, source_field)
        if value is not None:
            metrics[metric_name] = {"value": value, "higher_is_better": higher_is_better, "unit": unit}
    return metrics


def _bool_rate(rows: list[dict[str, Any]], key: str) -> float:
    values = [row.get(key) for row in rows]
    invalid = [index for index, value in enumerate(values) if not isinstance(value, bool)]
    if invalid:
        raise ValueError(f"Missing or non-boolean values for {key!r} at run indices: {invalid[:10]}")
    return sum(1.0 for value in values if value) / len(values)


def _mean_numeric(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row.get(key) for row in rows]
    numeric = [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
    if not numeric:
        return None
    return sum(numeric) / len(numeric)


def _wod_split_from_suite(suite: str) -> str:
    if "val479" in suite:
        return "validation_479_preference_frames"
    if "records2000" in suite:
        return "validation_first_2000_raw_records"
    if "smoke" in suite:
        return "validation_smoke"
    if "leaderboard" in suite:
        return "test_leaderboard"
    return "unknown"


def _optional_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _alpasim_metadata(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "evaluation_contract": "unknown",
        "scenario_set": "unknown",
        "score_backend": "alpasim",
        "sensor_contract": "unknown",
        "camera_ids": "unknown",
        "context_length": "unknown",
        "ego_history_hz": "unknown",
        "output_horizon": "unknown",
        "route_command_source": "unknown",
        "alpasim_version": "unknown",
    }
    if overrides:
        metadata.update(overrides)
    return metadata


def _alpasim_metric_unit(name: str) -> str:
    if name.endswith("_rate") or name.startswith("collision") or name in {"offroad", "safety_monitor_triggered"}:
        return "rate"
    if "dist" in name or "deviation" in name:
        return "m"
    if name == "alpasim_score":
        return "score"
    if name == "duration_frac_20s":
        return "fraction"
    return "value"


def _alpasim_higher_is_better(name: str) -> bool:
    if name in LOWER_IS_BETTER_METRICS:
        return False
    if name in HIGHER_IS_BETTER_METRICS:
        return True
    raise ValueError(
        f"Unknown AlpaSim metric direction for {name!r}. "
        "Add it to LOWER_IS_BETTER_METRICS or HIGHER_IS_BETTER_METRICS before reporting it."
    )


def _metadata_from_json(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("--metadata-json must be a JSON object")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build benchmark metric reports from raw evaluation artifacts.")
    parser.add_argument("kind", choices=("wod-eval", "wod-cv", "scenario-eval", "alpasim-metrics", "runtime"))
    parser.add_argument("path")
    parser.add_argument("--system", required=True)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--source")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--require-metric",
        action="append",
        default=[],
        help="Require a metric to exist in the source artifact. Can be repeated.",
    )
    parser.add_argument(
        "--metadata-json",
        help="JSON object with benchmark contract metadata. Used by AlpaSim metric reports.",
    )
    args = parser.parse_args()

    if args.kind == "wod-eval":
        report = wod_eval_report_to_metric_report(args.path, system=args.system, suite=args.suite, source=args.source)
    elif args.kind == "wod-cv":
        report = wod_cv_report_to_metric_report(args.path, system=args.system, suite=args.suite, source=args.source)
    elif args.kind == "scenario-eval":
        report = scenario_eval_report_to_metric_report(
            args.path,
            system=args.system,
            suite=args.suite,
            source=args.source,
        )
    elif args.kind == "runtime":
        report = runtime_report_to_metric_report(
            args.path,
            system=args.system,
            suite=args.suite,
            source=args.source,
        )
    else:
        report = alpasim_metrics_report_to_metric_report(
            args.path,
            system=args.system,
            suite=args.suite,
            source=args.source,
            required_metrics=tuple(args.require_metric),
            metadata=_metadata_from_json(args.metadata_json),
        )
    payload = json.dumps(report, indent=2, sort_keys=True)
    Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
