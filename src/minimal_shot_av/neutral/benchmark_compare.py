from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MetricSpec:
    name: str
    value: float
    higher_is_better: bool = True
    unit: str = ""
    uncertainty: float = 0.0


@dataclass(frozen=True)
class MetricReport:
    system: str
    suite: str
    source: str
    metrics: dict[str, MetricSpec]
    notes: list[str]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class MetricComparison:
    metric: str
    subject_value: float
    baseline_value: float
    delta: float
    relative_delta: float | None
    required_margin: float
    higher_is_better: bool
    beats_baseline: bool
    unit: str


@dataclass(frozen=True)
class BenchmarkComparison:
    subject_system: str
    baseline_system: str
    suite: str
    source_subject: str
    source_baseline: str
    comparisons: list[MetricComparison]
    beats_all_shared_metrics: bool
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_metric_report(path: str | Path) -> MetricReport:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_metric_report(payload, source_path=str(path))


def parse_metric_report(payload: dict[str, Any], *, source_path: str = "<memory>") -> MetricReport:
    system = _required_string(payload, "system", source_path)
    suite = _required_string(payload, "suite", source_path)
    source = _required_string(payload, "source", source_path)
    raw_metrics = payload.get("metrics")
    if not isinstance(raw_metrics, dict) or not raw_metrics:
        raise ValueError(f"{source_path}: metrics must be a non-empty object")
    metrics: dict[str, MetricSpec] = {}
    for name, value in raw_metrics.items():
        metrics[str(name)] = _parse_metric(str(name), value, source_path)
    raw_notes = payload.get("notes", [])
    if not isinstance(raw_notes, list) or not all(isinstance(item, str) for item in raw_notes):
        raise ValueError(f"{source_path}: notes must be a list of strings")
    raw_metadata = payload.get("metadata", {})
    if not isinstance(raw_metadata, dict):
        raise ValueError(f"{source_path}: metadata must be an object")
    return MetricReport(
        system=system,
        suite=suite,
        source=source,
        metrics=metrics,
        notes=list(raw_notes),
        metadata=dict(raw_metadata),
    )


def compare_reports(subject: MetricReport, baseline: MetricReport) -> BenchmarkComparison:
    if subject.suite != baseline.suite:
        raise ValueError(
            f"Cannot compare different suites: subject={subject.suite!r}, baseline={baseline.suite!r}. "
            "Run the same benchmark on both systems first."
        )
    _validate_fair_metadata(subject, baseline)
    shared = sorted(set(subject.metrics) & set(baseline.metrics))
    if not shared:
        raise ValueError(
            f"No shared metrics between {subject.system!r} and {baseline.system!r} for suite {subject.suite!r}"
        )

    comparisons: list[MetricComparison] = []
    for name in shared:
        comparisons.append(_compare_metric(name, subject.metrics[name], baseline.metrics[name]))

    notes = [
        "Only shared metric names from the same benchmark suite are compared.",
        "Missing metrics are not filled or inferred.",
        *subject.notes,
        *baseline.notes,
    ]
    return BenchmarkComparison(
        subject_system=subject.system,
        baseline_system=baseline.system,
        suite=subject.suite,
        source_subject=subject.source,
        source_baseline=baseline.source,
        comparisons=comparisons,
        beats_all_shared_metrics=all(item.beats_baseline for item in comparisons),
        notes=notes,
    )


def _compare_metric(name: str, subject: MetricSpec, baseline: MetricSpec) -> MetricComparison:
    if subject.higher_is_better != baseline.higher_is_better:
        raise ValueError(f"Metric {name!r} has inconsistent direction between reports")
    if subject.unit != baseline.unit:
        raise ValueError(f"Metric {name!r} has inconsistent units: {subject.unit!r} vs {baseline.unit!r}")
    delta = subject.value - baseline.value
    required_margin = max(subject.uncertainty, baseline.uncertainty)
    return MetricComparison(
        metric=name,
        subject_value=subject.value,
        baseline_value=baseline.value,
        delta=delta,
        relative_delta=None if baseline.value == 0 else delta / abs(baseline.value),
        required_margin=required_margin,
        higher_is_better=subject.higher_is_better,
        beats_baseline=_beats_baseline(delta, required_margin, higher_is_better=subject.higher_is_better),
        unit=subject.unit,
    )


def _beats_baseline(delta: float, required_margin: float, *, higher_is_better: bool) -> bool:
    return delta > required_margin if higher_is_better else delta < -required_margin


FAIR_COMPARISON_METADATA_KEYS = (
    "evaluation_contract",
    "split",
    "frame_count",
    "score_backend",
    "selection_mode",
)

ALPASIM_COMPARISON_METADATA_KEYS = (
    "evaluation_contract",
    "scenario_set",
    "score_backend",
    "sensor_contract",
    "camera_ids",
    "context_length",
    "ego_history_hz",
    "output_horizon",
    "route_command_source",
    "alpasim_version",
)


def _validate_fair_metadata(subject: MetricReport, baseline: MetricReport) -> None:
    if subject.suite.endswith("_online_runtime"):
        _validate_runtime_metadata(subject, baseline)
        return
    if subject.suite == "physicalai_nurec_alpasim":
        _validate_matching_metadata(subject, baseline, ALPASIM_COMPARISON_METADATA_KEYS, label="AlpaSim")
        return
    if not subject.suite.startswith("wod_e2e"):
        return
    _validate_matching_metadata(subject, baseline, FAIR_COMPARISON_METADATA_KEYS, label="WOD")


def _validate_matching_metadata(
    subject: MetricReport,
    baseline: MetricReport,
    keys: tuple[str, ...],
    *,
    label: str,
) -> None:
    for key in keys:
        subject_has = key in subject.metadata
        baseline_has = key in baseline.metadata
        if not subject_has and not baseline_has:
            raise ValueError(f"Cannot compare {label} reports with missing metadata for {key!r}")
        if subject_has != baseline_has:
            raise ValueError(
                f"Cannot compare {label} reports with incomplete metadata for {key!r}: "
                f"subject_has={subject_has}, baseline_has={baseline_has}"
            )
        if subject_has and (subject.metadata[key] == "unknown" or baseline.metadata[key] == "unknown"):
            raise ValueError(f"Cannot compare {label} reports with unknown metadata for {key!r}")
        if subject_has and subject.metadata[key] != baseline.metadata[key]:
            raise ValueError(
                f"Cannot compare {label} reports with different {key}: "
                f"subject={subject.metadata[key]!r}, baseline={baseline.metadata[key]!r}"
            )


def _validate_runtime_metadata(subject: MetricReport, baseline: MetricReport) -> None:
    for key in ("runtime_contract", "excludes_io_and_training"):
        subject_has = key in subject.metadata
        baseline_has = key in baseline.metadata
        if subject_has != baseline_has:
            raise ValueError(
                f"Cannot compare runtime reports with incomplete metadata for {key!r}: "
                f"subject_has={subject_has}, baseline_has={baseline_has}"
            )
        if subject_has and subject.metadata[key] != baseline.metadata[key]:
            raise ValueError(
                f"Cannot compare runtime reports with different {key}: "
                f"subject={subject.metadata[key]!r}, baseline={baseline.metadata[key]!r}"
            )


def _parse_metric(name: str, raw: Any, source_path: str) -> MetricSpec:
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return MetricSpec(name=name, value=float(raw))
    if not isinstance(raw, dict):
        raise ValueError(f"{source_path}: metric {name!r} must be a number or object")
    value = raw.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{source_path}: metric {name!r} must have numeric value")
    higher_is_better = raw.get("higher_is_better", True)
    if not isinstance(higher_is_better, bool):
        raise ValueError(f"{source_path}: metric {name!r} higher_is_better must be boolean")
    unit = raw.get("unit", "")
    if not isinstance(unit, str):
        raise ValueError(f"{source_path}: metric {name!r} unit must be string")
    uncertainty = raw.get("uncertainty", 0.0)
    if not isinstance(uncertainty, (int, float)) or isinstance(uncertainty, bool) or uncertainty < 0:
        raise ValueError(f"{source_path}: metric {name!r} uncertainty must be a non-negative number")
    return MetricSpec(
        name=name,
        value=float(value),
        higher_is_better=higher_is_better,
        unit=unit,
        uncertainty=float(uncertainty),
    )


def _required_string(payload: dict[str, Any], key: str, source_path: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{source_path}: {key} must be a non-empty string")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two same-suite benchmark metric reports.")
    parser.add_argument("subject", help="Metric report for the system being improved.")
    parser.add_argument("baseline", help="Metric report for the baseline system.")
    parser.add_argument("--output", help="Optional JSON output path.")
    args = parser.parse_args()

    comparison = compare_reports(load_metric_report(args.subject), load_metric_report(args.baseline)).to_dict()
    payload = json.dumps(comparison, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
