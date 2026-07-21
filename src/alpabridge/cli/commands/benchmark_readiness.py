from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

BATCH_SUMMARY_SCHEMA = "alpabridge_closed_loop_batch_summary_v1"
READINESS_SCHEMA = "alpabridge_benchmark_readiness_v1"

DEFAULT_MIN_SCENES = 15
DEFAULT_REQUIRED_BASELINE_FAMILIES = (
    "replay_or_constant_velocity",
    "route_following",
    "token_dagger_bc",
)
DEFAULT_MODEL_FAMILIES = {
    "constant_velocity": "replay_or_constant_velocity",
    "route_following": "route_following",
    "token_dagger_bc": "token_dagger_bc",
    "direct_actor_planner": "route_following",
}
DEFAULT_REQUIRED_METRICS = (
    "collision_any",
    "collision_at_fault",
    "offroad",
    "wrong_lane",
    "progress",
    "plan_deviation",
    "duration_frac_20s",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Gate public benchmark claims against executed AlpaBridge closed-loop batch summaries. "
            "This command does not run evaluation; it refuses readiness until the required "
            "executed-scene matrix is present."
        )
    )
    parser.add_argument(
        "--batch-summary",
        type=Path,
        action="append",
        default=[],
        help="Public-safe JSON produced by alpabridge-batch-summary. Repeat for each driver/shard.",
    )
    parser.add_argument(
        "--min-scenes",
        type=int,
        default=DEFAULT_MIN_SCENES,
        help="Minimum unique executed scenes required for a public benchmark claim.",
    )
    parser.add_argument(
        "--required-family",
        action="append",
        default=None,
        help=(
            "Required benchmark baseline family. Repeat to override the default minimum matrix: "
            + ", ".join(DEFAULT_REQUIRED_BASELINE_FAMILIES)
        ),
    )
    parser.add_argument(
        "--required-model",
        dest="required_family",
        action="append",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--model-family",
        action="append",
        default=[],
        metavar="MODEL=FAMILY",
        help=(
            "Map a summary run_config.model value to a benchmark family. Defaults include "
            "constant_velocity=replay_or_constant_velocity, route_following=route_following, "
            "token_dagger_bc=token_dagger_bc, and direct_actor_planner=route_following."
        ),
    )
    parser.add_argument(
        "--require-metric",
        action="append",
        default=None,
        help=(
            "Metric that must be present in at least one supplied summary. Repeat to override "
            "the default reporting set."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON readiness report path.",
    )
    parser.add_argument("--json", action="store_true", help="Print the readiness report as JSON.")
    parser.add_argument(
        "--created-at",
        default=None,
        help="Override the report timestamp, useful for reproducible tracked reports.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = build_readiness_report(
        summary_paths=args.batch_summary,
        min_scenes=args.min_scenes,
        required_families=tuple(args.required_family)
        if args.required_family is not None
        else DEFAULT_REQUIRED_BASELINE_FAMILIES,
        required_metrics=tuple(args.require_metric)
        if args.require_metric is not None
        else DEFAULT_REQUIRED_METRICS,
        model_families=_model_family_overrides(args.model_family),
        created_at=args.created_at,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human_report(report)
    return 0 if report["ready_for_public_benchmark_claim"] else 1


def build_readiness_report(
    *,
    summary_paths: list[Path],
    min_scenes: int = DEFAULT_MIN_SCENES,
    required_families: tuple[str, ...] = DEFAULT_REQUIRED_BASELINE_FAMILIES,
    required_models: tuple[str, ...] | None = None,
    required_metrics: tuple[str, ...] = DEFAULT_REQUIRED_METRICS,
    model_families: dict[str, str] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    inputs = [_load_summary(path) for path in summary_paths]
    summaries = [item["summary"] for item in inputs if item["summary"]]
    family_map = {**DEFAULT_MODEL_FAMILIES, **(model_families or {})}
    if required_models is not None:
        required_families = required_models
    evidence = _evidence(inputs=inputs, summaries=summaries, model_families=family_map)
    failures = _failures(
        inputs=inputs,
        evidence=evidence,
        min_scenes=min_scenes,
        required_families=required_families,
        required_metrics=required_metrics,
    )
    ready = not failures
    return {
        "schema": READINESS_SCHEMA,
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "ready_for_public_benchmark_claim": ready,
        "claim_boundary": (
            "Ready only means the supplied public-safe summaries satisfy the minimum executed "
            "closed-loop matrix gate. It does not redistribute gated scene assets, checkpoints, "
            "or rollout media."
        ),
        "requirements": {
            "batch_summary_schema": BATCH_SUMMARY_SCHEMA,
            "clean_closed_loop_batches_only": True,
            "min_unique_scenes": min_scenes,
            "required_baseline_families": list(required_families),
            "required_metrics": list(required_metrics),
            "model_families": dict(sorted(family_map.items())),
            "route_contract": "all audited frames must use route_source=alpasim_waypoints",
        },
        "evidence": evidence,
        "failures": failures,
        "advice": _advice(failures),
        "inputs": [_input_record(item) for item in inputs],
    }


def _load_summary(path: Path) -> dict[str, Any]:
    record: dict[str, Any] = {"path": str(path), "summary": {}, "errors": []}
    if not path.is_file():
        record["errors"].append("missing_summary_file")
        return record
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        record["errors"].append(f"invalid_json:{exc}")
        return record
    if not isinstance(payload, dict):
        record["errors"].append("summary_not_object")
        return record
    record["summary"] = payload
    return record


def _evidence(
    *,
    inputs: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
    model_families: dict[str, str],
) -> dict[str, Any]:
    model_counts = Counter()
    family_counts = Counter()
    scene_ids: set[str] = set()
    metric_counts = Counter()
    route_source_counts = Counter()
    total_frames = 0
    clean_count = 0
    invalid_input_count = sum(1 for item in inputs if item["errors"])

    for summary in summaries:
        if _is_clean_summary(summary):
            clean_count += 1
        run_config = _dict_value(summary.get("run_config"))
        model = str(run_config.get("model") or "")
        aggregate = _dict_value(summary.get("aggregate"))
        metrics = _dict_value(summary.get("metrics"))
        route_source_counts.update(_counter_dict(aggregate.get("route_source_counts")))
        total_frames += _int_or_zero(aggregate.get("total_audited_frames"))
        if model:
            completed_scene_count = _int_or_zero(aggregate.get("completed_scene_count"))
            model_counts[model] += completed_scene_count
            family_counts[model_families.get(model, model)] += completed_scene_count
        for metric_name, metric_summary in metrics.items():
            if isinstance(metric_summary, dict) and _int_or_zero(metric_summary.get("count")) > 0:
                metric_counts[str(metric_name)] += _int_or_zero(metric_summary.get("count"))
        for run in _list_value(summary.get("runs")):
            if isinstance(run, dict) and str(run.get("scene_id") or ""):
                scene_ids.add(str(run["scene_id"]))

    return {
        "input_summary_count": len(inputs),
        "clean_summary_count": clean_count,
        "invalid_input_count": invalid_input_count,
        "unique_scene_count": len(scene_ids),
        "unique_scene_ids": sorted(scene_ids),
        "models": dict(sorted(model_counts.items())),
        "baseline_families": dict(sorted(family_counts.items())),
        "metrics": dict(sorted(metric_counts.items())),
        "route_source_counts": dict(sorted(route_source_counts.items())),
        "total_audited_frames": total_frames,
    }


def _failures(
    *,
    inputs: list[dict[str, Any]],
    evidence: dict[str, Any],
    min_scenes: int,
    required_families: tuple[str, ...],
    required_metrics: tuple[str, ...],
) -> list[str]:
    failures: list[str] = []
    if not inputs:
        failures.append("no_batch_summaries")
    for index, item in enumerate(inputs, start=1):
        summary = _dict_value(item.get("summary"))
        for error in _list_value(item.get("errors")):
            failures.append(f"summary_{index}:{error}")
        if not summary:
            continue
        if summary.get("schema") != BATCH_SUMMARY_SCHEMA:
            failures.append(f"summary_{index}:schema_mismatch:{summary.get('schema')}")
        if not summary.get("valid"):
            failures.append(f"summary_{index}:invalid")
        if not summary.get("clean_closed_loop_batch"):
            failures.append(f"summary_{index}:not_clean_closed_loop_batch")
        aggregate = _dict_value(summary.get("aggregate"))
        total_audited_frames = _int_or_zero(aggregate.get("total_audited_frames"))
        if total_audited_frames <= 0:
            failures.append(f"summary_{index}:no_audited_frames")
        route_sources = _counter_dict(aggregate.get("route_source_counts"))
        disallowed_sources = sorted(source for source in route_sources if source != "alpasim_waypoints")
        if disallowed_sources:
            failures.append(
                f"summary_{index}:route_source_not_claim_valid:{','.join(disallowed_sources)}"
            )
        route_source_frame_count = sum(route_sources.values())
        if total_audited_frames > 0 and route_source_frame_count != total_audited_frames:
            failures.append(
                "summary_"
                f"{index}:route_source_frame_count_mismatch:"
                f"{route_source_frame_count}/{total_audited_frames}"
            )

    if _int_or_zero(evidence.get("unique_scene_count")) < min_scenes:
        failures.append(
            f"insufficient_unique_scenes:{evidence.get('unique_scene_count')}/{min_scenes}"
        )

    families = set(_dict_value(evidence.get("baseline_families")).keys())
    missing_families = [family for family in required_families if family not in families]
    if missing_families:
        failures.append(f"missing_required_baseline_families:{','.join(missing_families)}")

    metrics = set(_dict_value(evidence.get("metrics")).keys())
    missing_metrics = [metric for metric in required_metrics if metric not in metrics]
    if missing_metrics:
        failures.append(f"missing_required_metrics:{','.join(missing_metrics)}")
    scene_count = _int_or_zero(evidence.get("unique_scene_count"))
    metric_counts = _dict_value(evidence.get("metrics"))
    for metric in required_metrics:
        count = _int_or_zero(metric_counts.get(metric))
        if scene_count and count < scene_count:
            failures.append(f"insufficient_metric_coverage:{metric}:{count}/{scene_count}")
    return failures


def _advice(failures: list[str]) -> list[str]:
    if not failures:
        return ["The supplied summaries satisfy the minimum public benchmark readiness gate."]
    advice: list[str] = []
    if any(failure == "no_batch_summaries" for failure in failures):
        advice.append("Run closed-loop batches and pass their alpabridge-batch-summary JSON files.")
    if any(failure.startswith("insufficient_unique_scenes:") for failure in failures):
        advice.append("Add executed, clean scene summaries until the minimum unique-scene count is met.")
    if any(failure.startswith("missing_required_baseline_families:") for failure in failures):
        advice.append("Add clean summaries for every required benchmark baseline family.")
    if any(failure.startswith("missing_required_metrics:") for failure in failures):
        advice.append("Ensure each batch summary includes the required behavior and runtime metrics.")
    if any(failure.startswith("insufficient_metric_coverage:") for failure in failures):
        advice.append("Report every required metric for every unique executed scene.")
    if any("route_source_not_claim_valid" in failure for failure in failures):
        advice.append("Exclude or rerun summaries with command-proxy route sources.")
    if any("not_clean_closed_loop_batch" in failure for failure in failures):
        advice.append("Only clean alpabridge-batch-summary outputs can support benchmark readiness.")
    return advice


def _input_record(item: dict[str, Any]) -> dict[str, Any]:
    summary = _dict_value(item.get("summary"))
    aggregate = _dict_value(summary.get("aggregate"))
    run_config = _dict_value(summary.get("run_config"))
    return {
        "path": item.get("path"),
        "errors": _list_value(item.get("errors")),
        "schema": summary.get("schema"),
        "valid": summary.get("valid"),
        "clean_closed_loop_batch": summary.get("clean_closed_loop_batch"),
        "model": run_config.get("model"),
        "scene_preset": run_config.get("scene_preset"),
        "planned_scene_count": aggregate.get("planned_scene_count"),
        "completed_scene_count": aggregate.get("completed_scene_count"),
    }


def _model_family_overrides(values: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            raise SystemExit(f"Invalid --model-family value {raw!r}; expected MODEL=FAMILY.")
        model, family = (part.strip() for part in raw.split("=", 1))
        if not model or not family:
            raise SystemExit(f"Invalid --model-family value {raw!r}; expected MODEL=FAMILY.")
        overrides[model] = family
    return overrides


def _is_clean_summary(summary: dict[str, Any]) -> bool:
    return bool(
        summary.get("schema") == BATCH_SUMMARY_SCHEMA
        and summary.get("valid")
        and summary.get("clean_closed_loop_batch")
    )


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _counter_dict(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _int_or_zero(raw) for key, raw in value.items()}


def _int_or_zero(value: Any) -> int:
    try:
        return 0 if value is None else int(value)
    except (TypeError, ValueError):
        return 0


def _print_human_report(report: dict[str, Any]) -> None:
    evidence = report["evidence"]
    print("AlpaBridge benchmark readiness")
    print(f"  ready for public benchmark claim: {report['ready_for_public_benchmark_claim']}")
    print(f"  input summaries: {evidence['input_summary_count']}")
    print(f"  clean summaries: {evidence['clean_summary_count']}")
    print(
        "  scenes: "
        f"{evidence['unique_scene_count']}/{report['requirements']['min_unique_scenes']}"
    )
    print(f"  models: {evidence['models']}")
    print(f"  baseline families: {evidence['baseline_families']}")
    print(f"  metrics: {sorted(evidence['metrics'])}")
    print(f"  route sources: {evidence['route_source_counts']}")
    if report["failures"]:
        print("  failures:")
        for failure in report["failures"]:
            print(f"    - {failure}")
    if report["advice"]:
        print("  advice:")
        for item in report["advice"]:
            print(f"    - {item}")


if __name__ == "__main__":
    raise SystemExit(main())
